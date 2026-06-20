"""
Автоматическое обогащение адресов для новых объектов недвижимости
Поддерживает 3 режима:
1. Автоматический - при создании каждого объекта (через SQLAlchemy events)
2. Batch - массовое обогащение пакетами (оптимизировано для импорта)
3. Асинхронный - фоновая обработка без блокировки (для тысяч объектов)
"""

from sqlalchemy import event
from services.geocoding import get_geocoding_service
from services.dadata_client import get_dadata_client
import logging

logger = logging.getLogger(__name__)


class AutoGeocodingService:
    """Сервис автоматического обогащения адресов"""
    
    def __init__(self):
        self.geocoding_service = get_geocoding_service()  # Yandex (для координат)
        self.dadata_client = get_dadata_client()  # DaData (для детальной разбивки адреса)
        self.batch_mode = False  # Флаг для отключения автоматического обогащения
        self.stats = {
            'total_processed': 0,
            'total_enriched': 0,
            'total_errors': 0,
            'total_skipped': 0
        }
    
    def enable_batch_mode(self):
        """Включить batch режим (отключает автоматическое обогащение)"""
        self.batch_mode = True
        logger.info("🔄 Batch mode enabled - автоматическое обогащение отключено")
    
    def disable_batch_mode(self):
        """Выключить batch режим (включает автоматическое обогащение)"""
        self.batch_mode = False
        logger.info("✅ Batch mode disabled - автоматическое обогащение включено")
    
    def enrich_property(self, property_obj):
        """
        Обогатить один объект недвижимости используя DaData
        
        Args:
            property_obj: Property model instance
            
        Returns:
            bool: True если успешно обогащён
        """
        # Пропускаем если batch mode включён
        if self.batch_mode:
            return False
        
        # Пропускаем если уже обогащён (проверяем новые поля)
        if property_obj.parsed_city and property_obj.parsed_area:
            self.stats['total_skipped'] += 1
            return False
        
        # Нужен адрес для DaData
        if not property_obj.address:
            self.stats['total_skipped'] += 1
            return False
        
        try:
            # Используем DaData для полной разбивки адреса
            enriched_data = self.dadata_client.enrich_property_address(property_obj.address)
            
            if enriched_data:
                # Заполняем все адресные поля
                property_obj.parsed_city = enriched_data.get('parsed_city', '')
                property_obj.parsed_district = enriched_data.get('parsed_district', '')  # Legacy: area + settlement
                property_obj.parsed_street = enriched_data.get('parsed_street', '')
                property_obj.parsed_area = enriched_data.get('parsed_area', '')
                property_obj.parsed_settlement = enriched_data.get('parsed_settlement', '')
                property_obj.parsed_house = enriched_data.get('parsed_house', '')
                property_obj.parsed_block = enriched_data.get('parsed_block', '')
                
                # Обновляем координаты если их не было
                if not property_obj.latitude and enriched_data.get('latitude'):
                    property_obj.latitude = enriched_data.get('latitude')
                    property_obj.longitude = enriched_data.get('longitude')
                
                self.stats['total_enriched'] += 1
                logger.info(f"✅ Обогащён: {property_obj.title[:50]} → {property_obj.parsed_city}, {property_obj.parsed_street} {property_obj.parsed_house}")
                return True
            else:
                self.stats['total_errors'] += 1
                return False
                
        except Exception as e:
            self.stats['total_errors'] += 1
            logger.error(f"❌ Ошибка обогащения {property_obj.id}: {e}")
            return False
        finally:
            self.stats['total_processed'] += 1
    
    def enrich_batch(self, properties, batch_size=50, dry_run=False):
        """
        Массовое обогащение объектов пакетами
        Оптимизировано для импорта тысяч объектов
        
        Args:
            properties: List of Property objects
            batch_size: Размер пакета для коммита в БД
            dry_run: Если True, не сохранять изменения в БД (только тестирование)
            
        Returns:
            dict: Статистика обработки
        """
        from app import db
        
        total = len(properties)
        logger.info(f"\n{'='*80}")
        logger.info(f"🚀 МАССОВОЕ ОБОГАЩЕНИЕ: {total} объектов")
        logger.info(f"   Размер пакета: {batch_size}")
        if dry_run:
            logger.warning(f"   ⚠️  DRY RUN MODE - изменения НЕ будут сохранены!")
        logger.info(f"{'='*80}\n")
        
        enriched = 0
        errors = 0
        skipped = 0
        
        for i, prop in enumerate(properties, 1):
            # Пропускаем если уже обогащён (проверяем новые поля)
            if prop.parsed_city and prop.parsed_area:
                skipped += 1
                continue
            
            # Нужен адрес для DaData
            if not prop.address:
                skipped += 1
                continue
            
            try:
                # Используем DaData для полной разбивки адреса
                enriched_data = self.dadata_client.enrich_property_address(prop.address)
                
                if enriched_data:
                    prop.parsed_city = enriched_data.get('parsed_city', '')
                    prop.parsed_district = enriched_data.get('parsed_district', '')
                    prop.parsed_street = enriched_data.get('parsed_street', '')
                    prop.parsed_area = enriched_data.get('parsed_area', '')
                    prop.parsed_settlement = enriched_data.get('parsed_settlement', '')
                    prop.parsed_house = enriched_data.get('parsed_house', '')
                    prop.parsed_block = enriched_data.get('parsed_block', '')
                    
                    # Обновляем координаты если их не было
                    if not prop.latitude and enriched_data.get('latitude'):
                        prop.latitude = enriched_data.get('latitude')
                        prop.longitude = enriched_data.get('longitude')
                    
                    enriched += 1
                    
                    # Логируем прогресс каждые 10 объектов
                    if i % 10 == 0:
                        logger.info(f"[{i}/{total}] Обработано: {enriched} обогащено, {errors} ошибок, {skipped} пропущено")
                else:
                    errors += 1
                    
            except Exception as e:
                errors += 1
                logger.error(f"❌ Ошибка [{i}/{total}]: {e}")
            
            # Сохраняем в БД каждые batch_size объектов (пропускаем в dry_run режиме)
            if i % batch_size == 0:
                if dry_run:
                    logger.info(f"🔍 [DRY RUN] Пропускаем сохранение {i} объектов")
                else:
                    try:
                        db.session.commit()
                        logger.info(f"💾 Сохранено {i} объектов в БД")
                    except Exception as e:
                        logger.error(f"❌ Ошибка сохранения в БД: {e}")
                        db.session.rollback()
        
        # Финальный коммит (пропускаем в dry_run режиме)
        if dry_run:
            logger.info(f"🔍 [DRY RUN] Откатываем все изменения")
            db.session.rollback()
        else:
            try:
                db.session.commit()
                logger.info(f"✅ Финальное сохранение в БД")
            except Exception as e:
                logger.error(f"❌ Ошибка финального сохранения: {e}")
                db.session.rollback()
        
        # Статистика
        stats = {
            'total': total,
            'enriched': enriched,
            'errors': errors,
            'skipped': skipped,
            'cache_stats': self.geocoding_service.get_stats()
        }
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 ИТОГИ ОБОГАЩЕНИЯ")
        logger.info(f"   Всего объектов: {total}")
        logger.info(f"   ✅ Обогащено: {enriched}")
        logger.info(f"   ❌ Ошибок: {errors}")
        logger.info(f"   ⏭️  Пропущено: {skipped}")
        logger.info(f"   📡 API запросов: {stats['cache_stats']['api_requests']}")
        logger.info(f"   💾 Cache hit rate: {stats['cache_stats']['cache_hit_rate']}%")
        logger.info(f"{'='*80}\n")
        
        return stats
    
    def get_stats(self):
        """Получить статистику обработки"""
        return self.stats
    
    def reset_stats(self):
        """Сбросить статистику"""
        self.stats = {
            'total_processed': 0,
            'total_enriched': 0,
            'total_errors': 0,
            'total_skipped': 0
        }


# Глобальный экземпляр сервиса
_auto_geocoding_service = None

def get_auto_geocoding_service():
    """Получить singleton экземпляр AutoGeocodingService"""
    global _auto_geocoding_service
    if _auto_geocoding_service is None:
        _auto_geocoding_service = AutoGeocodingService()
    return _auto_geocoding_service


def setup_auto_geocoding(db):
    """
    Настроить автоматическое обогащение через SQLAlchemy events
    Вызывается один раз при инициализации приложения
    
    Args:
        db: SQLAlchemy database instance
    """
    from models import Property
    
    auto_service = get_auto_geocoding_service()
    
    @event.listens_for(Property, 'before_insert')
    def enrich_before_insert(mapper, connection, target):
        """Обогащаем адрес перед созданием объекта"""
        # Только если есть координаты и ещё не обогащён
        if target.latitude and target.longitude and not target.parsed_city:
            logger.debug(f"🔍 Auto-geocoding: {target.title[:50]}")
            auto_service.enrich_property(target)
    
    @event.listens_for(Property, 'before_update')
    def enrich_before_update(mapper, connection, target):
        """Обогащаем адрес если координаты изменились"""
        # Проверяем что координаты изменились
        state = db.inspect(target)
        lat_changed = state.attrs.latitude.history.has_changes()
        lon_changed = state.attrs.longitude.history.has_changes()
        
        if (lat_changed or lon_changed) and target.latitude and target.longitude:
            logger.debug(f"🔄 Coordinates changed, re-geocoding: {target.title[:50]}")
            auto_service.enrich_property(target)
    
    logger.info("✅ Auto-geocoding events registered for Property model")
