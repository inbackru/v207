"""
PropertySyncService - автоматическое определение проданных объектов
при массовом импорте данных из внешних источников (10,000+ объектов)
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from app import db
from models import Property, User, UserFavorite, UserComparison
from services.alert_service import AlertService
import logging

logger = logging.getLogger(__name__)


class PropertySyncService:
    """
    Сервис для синхронизации состояния объектов недвижимости.
    
    Принцип работы:
    1. При импорте объектов обновляем external_id и last_seen_at
    2. После импорта запускаем detect_sold_properties()
    3. Объекты которые не были обновлены (исчезли из источника) → is_active=False
    4. Автоматически отправляем уведомления пользователям
    """
    
    def __init__(self):
        self.alert_service = AlertService()
    
    def process_import_batch(
        self,
        properties_data: List[Dict],
        source_name: str = "parser",
        auto_detect_sold: bool = True
    ) -> Dict:
        """
        Обработать батч импортированных объектов.
        
        Args:
            properties_data: Список объектов из парсера/API
            source_name: Название источника данных
            auto_detect_sold: Автоматически определять проданные после импорта
            
        Returns:
            Статистика импорта
        """
        stats = {
            'total': len(properties_data),
            'created': 0,
            'updated': 0,
            'errors': 0,
            'source': source_name,
            'timestamp': datetime.utcnow()
        }
        
        current_time = datetime.utcnow()
        
        try:
            for prop_data in properties_data:
                try:
                    # Получаем уникальный идентификатор
                    external_id = self._extract_external_id(prop_data, source_name)
                    
                    if not external_id:
                        logger.warning(f"Пропущен объект без external_id: {prop_data.get('title', 'Unknown')}")
                        stats['errors'] += 1
                        continue
                    
                    # Ищем существующий объект
                    existing = Property.query.filter_by(external_id=external_id).first()
                    
                    if existing:
                        # Обновляем существующий объект
                        self._update_property(existing, prop_data, current_time)
                        stats['updated'] += 1
                        logger.debug(f"Обновлен объект {external_id}: {existing.title}")
                    else:
                        # Создаем новый объект
                        new_property = self._create_property(prop_data, external_id, current_time)
                        db.session.add(new_property)
                        stats['created'] += 1
                        logger.debug(f"Создан новый объект {external_id}: {new_property.title}")
                    
                    # Коммитим каждые 100 объектов для производительности
                    if (stats['created'] + stats['updated']) % 100 == 0:
                        db.session.commit()
                        logger.info(f"Импортировано {stats['created'] + stats['updated']} объектов...")
                
                except Exception as e:
                    logger.error(f"Ошибка обработки объекта: {e}")
                    stats['errors'] += 1
                    db.session.rollback()
            
            # Финальный коммит
            db.session.commit()
            logger.info(f"✅ Импорт завершен: создано {stats['created']}, обновлено {stats['updated']}, ошибок {stats['errors']}")
            
            # Автоматически определяем проданные объекты
            if auto_detect_sold:
                sold_stats = self.detect_sold_properties(
                    cutoff_time=current_time,
                    source_name=source_name
                )
                stats['sold_detected'] = sold_stats
            
        except Exception as e:
            logger.error(f"Критическая ошибка импорта: {e}")
            db.session.rollback()
            raise
        
        return stats
    
    def detect_sold_properties(
        self,
        cutoff_time: Optional[datetime] = None,
        source_name: Optional[str] = None,
        notify_users: bool = True
    ) -> Dict:
        """
        Определить проданные объекты (которые исчезли из источника).
        
        Args:
            cutoff_time: Время отсечки (объекты не обновленные после этого времени считаются проданными)
            source_name: Фильтр по источнику данных
            notify_users: Отправлять уведомления пользователям
            
        Returns:
            Статистика обнаруженных проданных объектов
        """
        if cutoff_time is None:
            cutoff_time = datetime.utcnow()
        
        stats = {
            'total_checked': 0,
            'newly_sold': 0,
            'users_notified': 0,
            'notifications_sent': 0
        }
        
        try:
            # Ищем объекты которые:
            # 1. Были активны (is_active=True)
            # 2. Не были обновлены в текущем импорте (last_seen_at < cutoff_time или NULL)
            # 3. Имеют external_id (были импортированы из источника)
            query = Property.query.filter(
                Property.is_active == True,
                Property.external_id.isnot(None)
            )
            
            # Фильтр по времени
            query = query.filter(
                db.or_(
                    Property.last_seen_at < cutoff_time,
                    Property.last_seen_at.is_(None)
                )
            )
            
            # Фильтр по источнику (опционально)
            if source_name:
                query = query.filter(Property.external_id.like(f"{source_name}%"))
            
            properties_to_mark_sold = query.all()
            stats['total_checked'] = len(properties_to_mark_sold)
            
            logger.info(f"🔍 Найдено {len(properties_to_mark_sold)} объектов для проверки на продажу")
            
            # Помечаем как проданные и отправляем уведомления
            for prop in properties_to_mark_sold:
                try:
                    # Помечаем как проданный
                    prop.is_active = False
                    prop.status = 'sold'
                    prop.sold_detected_at = datetime.utcnow()
                    
                    logger.info(f"📍 Объект помечен как проданный: {prop.title} (external_id: {prop.external_id})")
                    stats['newly_sold'] += 1
                    
                    # Отправляем уведомления пользователям
                    if notify_users:
                        notification_stats = self._notify_users_about_sold_property(prop)
                        stats['users_notified'] += notification_stats['users']
                        stats['notifications_sent'] += notification_stats['total']
                
                except Exception as e:
                    logger.error(f"Ошибка обработки проданного объекта {prop.id}: {e}")
                    continue
            
            db.session.commit()
            logger.info(f"✅ Обработка завершена: {stats['newly_sold']} объектов помечены как проданные")
            
        except Exception as e:
            logger.error(f"Ошибка определения проданных объектов: {e}")
            db.session.rollback()
            raise
        
        return stats
    
    def _extract_external_id(self, prop_data: Dict, source_name: str) -> Optional[str]:
        """
        Извлечь уникальный external_id из данных объекта.
        
        Формат: {source_name}:{unique_id}
        Например: parser:12345, api:abc-def-ghi
        """
        # Попытка получить ID из разных полей
        unique_id = (
            prop_data.get('external_id') or
            prop_data.get('id') or
            prop_data.get('inner_id') or
            prop_data.get('parser_id') or
            prop_data.get('source_id')
        )
        
        if unique_id:
            return f"{source_name}:{unique_id}"
        
        # Если нет явного ID, создаем из комбинации полей (адрес + площадь + этаж)
        address = prop_data.get('address', '')
        area = prop_data.get('area', '')
        floor = prop_data.get('floor', '')
        
        if address and area:
            import hashlib
            composite_key = f"{address}_{area}_{floor}"
            hash_id = hashlib.md5(composite_key.encode()).hexdigest()[:16]
            return f"{source_name}:hash_{hash_id}"
        
        return None
    
    def _create_property(self, prop_data: Dict, external_id: str, current_time: datetime) -> Property:
        """Создать новый объект Property из данных импорта."""
        prop = Property(
            external_id=external_id,
            last_seen_at=current_time,
            is_active=True,
            status='available',
            # Базовые поля
            title=prop_data.get('title', 'Объект недвижимости'),
            description=prop_data.get('description'),
            rooms=prop_data.get('rooms'),
            area=prop_data.get('area'),
            floor=prop_data.get('floor'),
            total_floors=prop_data.get('total_floors'),
            price=prop_data.get('price'),
            price_per_sqm=prop_data.get('price_per_sqm'),
            # Обязательное поле city_id
            city_id=prop_data.get('city_id', 1),  # Default: Краснодар
            # Дополнительные поля
            address=prop_data.get('address'),
            latitude=prop_data.get('latitude'),
            longitude=prop_data.get('longitude'),
            main_image=prop_data.get('main_image'),
            source_url=prop_data.get('source_url'),
            scraped_at=current_time
        )
        return prop
    
    def _update_property(self, prop: Property, prop_data: Dict, current_time: datetime):
        """Обновить существующий объект Property."""
        # Обновляем timestamp и статус
        prop.last_seen_at = current_time
        
        # Если объект был помечен как проданный, но снова появился - восстанавливаем
        if not prop.is_active:
            logger.info(f"🔄 Объект {prop.external_id} снова в продаже, восстанавливаем")
            prop.is_active = True
            prop.status = 'available'
            prop.sold_detected_at = None
        
        # Обновляем основные данные (цена может измениться)
        if 'price' in prop_data and prop_data['price']:
            prop.price = prop_data['price']
        if 'price_per_sqm' in prop_data and prop_data['price_per_sqm']:
            prop.price_per_sqm = prop_data['price_per_sqm']
        if 'description' in prop_data:
            prop.description = prop_data['description']
        if 'main_image' in prop_data:
            prop.main_image = prop_data['main_image']
        
        prop.updated_at = current_time
    
    def _notify_users_about_sold_property(self, prop: Property) -> Dict:
        """Отправить уведомления пользователям о продаже объекта."""
        stats = {'users': 0, 'total': 0}
        
        try:
            # Находим всех пользователей у которых объект в избранном или сравнении
            users_to_notify = set()
            
            # Пользователи с объектом в избранном
            favorites = UserFavorite.query.filter_by(property_id=prop.id).all()
            for fav in favorites:
                if fav.user_id:
                    users_to_notify.add(fav.user_id)
            
            # Пользователи с объектом в сравнении
            comparisons = UserComparison.query.filter_by(property_id=prop.id).all()
            for comp in comparisons:
                if comp.user_id:
                    users_to_notify.add(comp.user_id)
            
            # Отправляем уведомления
            for user_id in users_to_notify:
                try:
                    user = User.query.get(user_id)
                    if user:
                        self.alert_service.notify_property_sold(user, prop)
                        stats['total'] += 1
                        logger.info(f"📧 Уведомление отправлено пользователю {user.email} о продаже {prop.title}")
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
            
            stats['users'] = len(users_to_notify)
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений для объекта {prop.id}: {e}")
        
        return stats
    
    def get_sync_statistics(self, days: int = 7) -> Dict:
        """
        Получить статистику синхронизации за последние N дней.
        
        Returns:
            Dict с общей информацией о синхронизации
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        stats = {
            'total_properties': Property.query.count(),
            'active_properties': Property.query.filter_by(is_active=True).count(),
            'sold_properties': Property.query.filter_by(is_active=False).count(),
            'recently_updated': Property.query.filter(Property.last_seen_at >= cutoff_date).count(),
            'recently_sold': Property.query.filter(Property.sold_detected_at >= cutoff_date).count(),
            'with_external_id': Property.query.filter(Property.external_id.isnot(None)).count(),
            'period_days': days
        }
        
        return stats
