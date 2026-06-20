#!/usr/bin/env python3
"""
Скрипт для автоматической привязки объектов и ЖК к районам в Краснодаре.

Алгоритм:
1. Для каждого ЖК находит ближайший район по координатам
2. Устанавливает district_id для ЖК
3. Копирует district_id от ЖК ко всем объектам в этом ЖК
4. Заполняет parsed_district для поиска

Использование:
    python scripts/link_krasnodar_districts.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Property, ResidentialComplex, District
from sqlalchemy import func, and_
import logging
import math

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def calculate_distance(lat1, lon1, lat2, lon2):
    """Вычисляет расстояние между двумя точками в километрах (формула Haversine)"""
    if not all([lat1, lon1, lat2, lon2]):
        return float('inf')
    
    R = 6371  # Радиус Земли в километрах
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) *
         math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def find_nearest_district(complex_lat, complex_lon, districts):
    """Находит ближайший район к координатам ЖК"""
    if not complex_lat or not complex_lon:
        return None
    
    min_distance = float('inf')
    nearest_district = None
    
    for district in districts:
        if district.latitude and district.longitude:
            distance = calculate_distance(
                complex_lat, complex_lon,
                district.latitude, district.longitude
            )
            if distance < min_distance:
                min_distance = distance
                nearest_district = district
    
    if nearest_district and min_distance < 10:  # Максимум 10 км
        logger.info(f"  📍 Ближайший район: {nearest_district.name} (расстояние: {min_distance:.2f} км)")
        return nearest_district
    
    return None


def link_complexes_to_districts(city_id=1):
    """Связывает ЖК с районами по координатам"""
    logger.info("=" * 60)
    logger.info("🏢 Привязка ЖК к районам в Краснодаре")
    logger.info("=" * 60)
    
    # Получаем все районы Краснодара
    districts = District.query.filter_by(city_id=city_id).all()
    logger.info(f"📊 Загружено районов: {len(districts)}")
    
    # Получаем ЖК без привязки к районам
    complexes = ResidentialComplex.query.filter(
        and_(
            ResidentialComplex.city_id == city_id,
            ResidentialComplex.district_id.is_(None),
            ResidentialComplex.latitude.isnot(None),
            ResidentialComplex.longitude.isnot(None)
        )
    ).all()
    
    logger.info(f"🏗️ ЖК без районов (с координатами): {len(complexes)}")
    logger.info("")
    
    updated_count = 0
    
    for idx, complex in enumerate(complexes, 1):
        logger.info(f"{idx}. {complex.name}")
        logger.info(f"  📌 Координаты: {complex.latitude}, {complex.longitude}")
        
        # Находим ближайший район
        nearest = find_nearest_district(
            complex.latitude, 
            complex.longitude, 
            districts
        )
        
        if nearest:
            complex.district_id = nearest.id
            db.session.add(complex)
            updated_count += 1
            logger.info(f"  ✅ Привязан к району: {nearest.name}")
        else:
            logger.info(f"  ⚠️ Район не найден (нет координат или слишком далеко)")
        
        logger.info("")
    
    if updated_count > 0:
        db.session.commit()
        logger.info(f"✅ Обновлено ЖК: {updated_count}")
    else:
        logger.info("ℹ️ Нет ЖК для обновления")
    
    return updated_count


def copy_districts_to_properties(city_id=1):
    """Копирует district_id от ЖК к объектам и заполняет parsed_district"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("🏠 Копирование районов от ЖК к объектам")
    logger.info("=" * 60)
    
    # Получаем ЖК с районами
    complexes_with_districts = ResidentialComplex.query.filter(
        and_(
            ResidentialComplex.city_id == city_id,
            ResidentialComplex.district_id.isnot(None)
        )
    ).all()
    
    logger.info(f"🏗️ ЖК с районами: {len(complexes_with_districts)}")
    logger.info("")
    
    total_updated = 0
    
    for complex in complexes_with_districts:
        # Получаем район
        district = District.query.get(complex.district_id)
        if not district:
            continue
        
        # Обновляем все объекты в этом ЖК
        properties = Property.query.filter(
            and_(
                Property.complex_id == complex.id,
                Property.city_id == city_id,
                Property.district_id.is_(None)
            )
        ).all()
        
        if properties:
            logger.info(f"📍 {complex.name} → {district.name}")
            logger.info(f"  Объектов для обновления: {len(properties)}")
            
            for prop in properties:
                prop.district_id = district.id
                prop.parsed_district = district.name
                db.session.add(prop)
                total_updated += 1
            
            logger.info(f"  ✅ Обновлено: {len(properties)} объектов")
            logger.info("")
    
    if total_updated > 0:
        db.session.commit()
        logger.info(f"✅ Всего обновлено объектов: {total_updated}")
    else:
        logger.info("ℹ️ Нет объектов для обновления")
    
    return total_updated


def show_statistics(city_id=1):
    """Показывает статистику по районам"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("📊 Статистика по районам")
    logger.info("=" * 60)
    
    # Статистика по объектам
    properties_with_districts = db.session.query(
        District.name,
        func.count(Property.id).label('count')
    ).join(
        Property, Property.district_id == District.id
    ).filter(
        Property.city_id == city_id,
        Property.is_active == True
    ).group_by(
        District.name
    ).order_by(
        func.count(Property.id).desc()
    ).all()
    
    logger.info(f"\n🏠 Объекты по районам:")
    for district_name, count in properties_with_districts:
        logger.info(f"  • {district_name}: {count} объектов")
    
    # Общая статистика
    total_properties = Property.query.filter_by(city_id=city_id, is_active=True).count()
    properties_with_district = Property.query.filter(
        and_(
            Property.city_id == city_id,
            Property.is_active == True,
            Property.district_id.isnot(None)
        )
    ).count()
    
    logger.info(f"\n📈 Общая статистика:")
    logger.info(f"  • Всего активных объектов: {total_properties}")
    logger.info(f"  • Объектов с районами: {properties_with_district}")
    logger.info(f"  • Покрытие: {properties_with_district / total_properties * 100:.1f}%")


def main():
    """Основная функция"""
    with app.app_context():
        try:
            city_id = 1  # Краснодар
            
            # Шаг 1: Связываем ЖК с районами
            complexes_updated = link_complexes_to_districts(city_id)
            
            # Шаг 2: Копируем районы к объектам
            properties_updated = copy_districts_to_properties(city_id)
            
            # Шаг 3: Показываем статистику
            show_statistics(city_id)
            
            logger.info("")
            logger.info("=" * 60)
            logger.info("✅ ГОТОВО!")
            logger.info("=" * 60)
            logger.info(f"• ЖК обновлено: {complexes_updated}")
            logger.info(f"• Объектов обновлено: {properties_updated}")
            logger.info("")
            logger.info("Теперь API /api/districts/1 вернёт список районов,")
            logger.info("и фильтр по районам будет работать!")
            
        except Exception as e:
            logger.error(f"❌ Ошибка: {str(e)}", exc_info=True)
            db.session.rollback()
            return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
