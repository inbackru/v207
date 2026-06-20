#!/usr/bin/env python3
"""
Автоматическое заполнение районов для объектов Краснодара из адресов.

Этот скрипт:
1. Берёт объекты с адресами, но без районов
2. Парсит адрес и извлекает район/микрорайон
3. Заполняет поля parsed_district, parsed_settlement, parsed_area
4. Связывает с таблицей districts (если район существует)

Использование:
    python scripts/auto_fill_districts_from_addresses.py
"""

import sys
import os
import re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Property, District
from sqlalchemy import and_
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_district_from_address(address):
    """
    Извлекает район из адреса.
    
    Примеры адресов:
    - "г. Краснодар, мкр. Западный обход, ул. Тургенева, 100"
    - "Краснодар, Карасунский округ, ул. Красная, 1"
    - "г. Краснодар, ул. Красная, 32" (центр - Красная площадь)
    """
    if not address or not isinstance(address, str):
        return None, None, None
    
    address_lower = address.lower()
    
    # Паттерны для микрорайонов
    microdistrict_patterns = [
        r'мкр\.?\s+([а-яё\s\-]+)',
        r'микрорайон\s+([а-яё\s\-]+)',
        r'м-н\.?\s+([а-яё\s\-]+)',
        r'мр\.?\s+([а-яё\s\-]+)',
    ]
    
    # Паттерны для округов/районов
    district_patterns = [
        r'([а-яё]+)\s+округ',
        r'([а-яё]+)\s+район',
        r'р-н\.?\s+([а-яё\s\-]+)',
    ]
    
    parsed_settlement = None
    parsed_district = None
    parsed_area = None
    
    # Ищем микрорайон
    for pattern in microdistrict_patterns:
        match = re.search(pattern, address_lower)
        if match:
            parsed_settlement = match.group(1).strip().title()
            break
    
    # Ищем округ/район
    for pattern in district_patterns:
        match = re.search(pattern, address_lower)
        if match:
            district_name = match.group(1).strip().title()
            parsed_district = f"{district_name} округ" if 'округ' in pattern else district_name
            parsed_area = district_name
            break
    
    # Определяем район по известным улицам (для центра города)
    if not parsed_district and not parsed_settlement:
        # Центральные улицы
        central_streets = ['красная', 'красноармейская', 'гоголя', 'рашпилевская']
        if any(street in address_lower for street in central_streets):
            parsed_district = 'Центральный'
            parsed_area = 'Центральный'
    
    return parsed_district, parsed_settlement, parsed_area


def find_matching_district(district_name, city_id=1):
    """Находит район в справочнике по названию"""
    if not district_name:
        return None
    
    # Точное совпадение
    district = District.query.filter(
        and_(
            District.city_id == city_id,
            District.name == district_name
        )
    ).first()
    
    if district:
        return district
    
    # Частичное совпадение (например, "Западный" найдёт "Западный обход")
    district = District.query.filter(
        and_(
            District.city_id == city_id,
            District.name.ilike(f'%{district_name}%')
        )
    ).first()
    
    return district


def auto_fill_districts(city_id=1, dry_run=False):
    """
    Автоматически заполняет районы для объектов с адресами.
    
    Args:
        city_id: ID города (1 = Краснодар)
        dry_run: Если True, только показывает что будет сделано (без сохранения)
    """
    logger.info("=" * 60)
    logger.info(f"🏠 Автоматическое заполнение районов (city_id={city_id})")
    if dry_run:
        logger.info("⚠️  DRY RUN MODE - изменения НЕ будут сохранены")
    logger.info("=" * 60)
    
    # Получаем объекты с адресами, но без районов
    properties = Property.query.filter(
        and_(
            Property.city_id == city_id,
            Property.is_active == True,
            Property.address.isnot(None),
            Property.address != '',
            Property.parsed_district.is_(None)
        )
    ).all()
    
    logger.info(f"📊 Найдено объектов с адресами (без районов): {len(properties)}")
    logger.info("")
    
    updated_count = 0
    linked_count = 0
    
    for idx, prop in enumerate(properties, 1):
        # Парсим адрес
        district, settlement, area = parse_district_from_address(prop.address)
        
        if district or settlement or area:
            logger.info(f"{idx}. ID={prop.id}")
            logger.info(f"   Адрес: {prop.address}")
            
            if district:
                logger.info(f"   ✅ Район: {district}")
            if settlement:
                logger.info(f"   ✅ Микрорайон: {settlement}")
            if area:
                logger.info(f"   ✅ Область: {area}")
            
            # Пробуем найти в справочнике
            db_district = find_matching_district(district or settlement or area, city_id)
            
            if db_district:
                logger.info(f"   🔗 Связан с: {db_district.name} (ID={db_district.id})")
                if not dry_run:
                    prop.district_id = db_district.id
                linked_count += 1
            
            # Заполняем текстовые поля
            if not dry_run:
                if district:
                    prop.parsed_district = district
                if settlement:
                    prop.parsed_settlement = settlement
                if area:
                    prop.parsed_area = area
                
                db.session.add(prop)
            
            updated_count += 1
            logger.info("")
    
    if not dry_run and updated_count > 0:
        db.session.commit()
        logger.info(f"✅ Обновлено объектов: {updated_count}")
        logger.info(f"🔗 Связано с районами: {linked_count}")
    else:
        logger.info(f"ℹ️  Будет обновлено: {updated_count} объектов")
        logger.info(f"ℹ️  Будет связано: {linked_count} объектов")
    
    return updated_count, linked_count


def show_districts_statistics(city_id=1):
    """Показывает статистику по районам после обновления"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("📊 Статистика по районам после обновления")
    logger.info("=" * 60)
    
    # Подсчёт уникальных районов из текстовых полей
    from sqlalchemy import func
    
    districts_from_parsed = db.session.query(
        Property.parsed_district
    ).filter(
        and_(
            Property.city_id == city_id,
            Property.is_active == True,
            Property.parsed_district.isnot(None)
        )
    ).distinct().all()
    
    settlements_from_parsed = db.session.query(
        Property.parsed_settlement
    ).filter(
        and_(
            Property.city_id == city_id,
            Property.is_active == True,
            Property.parsed_settlement.isnot(None)
        )
    ).distinct().all()
    
    logger.info(f"\n🏘️ Уникальных районов (parsed_district): {len(districts_from_parsed)}")
    for d in districts_from_parsed[:10]:
        logger.info(f"   • {d[0]}")
    
    logger.info(f"\n🏡 Уникальных микрорайонов (parsed_settlement): {len(settlements_from_parsed)}")
    for s in settlements_from_parsed[:10]:
        logger.info(f"   • {s[0]}")
    
    # Общая статистика
    total = Property.query.filter_by(city_id=city_id, is_active=True).count()
    with_districts = Property.query.filter(
        and_(
            Property.city_id == city_id,
            Property.is_active == True,
            Property.parsed_district.isnot(None)
        )
    ).count()
    
    logger.info(f"\n📈 Покрытие:")
    logger.info(f"   • Всего объектов: {total}")
    logger.info(f"   • С районами: {with_districts}")
    logger.info(f"   • Процент: {with_districts / total * 100:.1f}%")


def main():
    """Основная функция"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Автозаполнение районов из адресов')
    parser.add_argument('--city-id', type=int, default=1, help='ID города (по умолчанию: 1 - Краснодар)')
    parser.add_argument('--dry-run', action='store_true', help='Тестовый запуск без сохранения')
    
    args = parser.parse_args()
    
    with app.app_context():
        try:
            # Шаг 1: Автозаполнение
            updated, linked = auto_fill_districts(
                city_id=args.city_id,
                dry_run=args.dry_run
            )
            
            if not args.dry_run:
                # Шаг 2: Статистика
                show_districts_statistics(city_id=args.city_id)
                
                logger.info("")
                logger.info("=" * 60)
                logger.info("✅ ГОТОВО!")
                logger.info("=" * 60)
                logger.info(f"Теперь API /api/districts/{args.city_id} вернёт все районы")
                logger.info("и фильтры автоматически заработают!")
            
        except Exception as e:
            logger.error(f"❌ Ошибка: {str(e)}", exc_info=True)
            db.session.rollback()
            return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
