#!/usr/bin/env python3
"""
Автоматическая привязка объектов к районам через DaData Reverse Geocoding.

Использует API DaData для определения района по координатам (lat/lon).
Обновляет поле district_id в таблице properties.

Требования:
- DADATA_API_KEY в environment variables
- Properties должны иметь latitude и longitude
- Districts должны быть созданы в БД для соответствующих городов

Лимиты DaData:
- Бесплатно: 10,000 запросов/день
- Частота: 30 запросов/сек
"""

import os
import sys
import time
import requests

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Property, District, City

# DaData API configuration
DADATA_API_KEY = os.environ.get('DADATA_API_KEY')
DADATA_SECRET_KEY = os.environ.get('DADATA_SECRET_KEY')
DADATA_GEOLOCATE_URL = 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/geolocate/address'

# Rate limiting: 30 requests/sec = 0.033 sec delay
REQUEST_DELAY = 0.035  # 35ms between requests (safe margin)


def geolocate_address(lat, lon):
    """
    Получить адрес и район по координатам через DaData.
    
    Args:
        lat: Широта (latitude)
        lon: Долгота (longitude)
    
    Returns:
        dict: Данные адреса с полями city_district, city, region и др.
        None: Если запрос не удался
    """
    if not DADATA_API_KEY:
        print("❌ DADATA_API_KEY не найден в environment variables")
        return None
    
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Token {DADATA_API_KEY}'
    }
    
    if DADATA_SECRET_KEY:
        headers['X-Secret'] = DADATA_SECRET_KEY
    
    payload = {
        'lat': lat,
        'lon': lon,
        'count': 1  # Нужен только ближайший адрес
    }
    
    try:
        response = requests.post(DADATA_GEOLOCATE_URL, json=payload, headers=headers, timeout=5)
        response.raise_for_status()
        
        data = response.json()
        suggestions = data.get('suggestions', [])
        
        if suggestions:
            return suggestions[0].get('data', {})
        
        return None
    
    except requests.exceptions.RequestException as e:
        print(f"⚠️  Ошибка запроса к DaData: {e}")
        return None


def normalize_district_name(name):
    """
    Нормализовать название района для поиска в БД.
    
    Примеры:
        'р-н Адлерский' -> 'Адлерский'
        'Западный округ' -> 'Западный округ'
        'Центральный' -> 'Центральный'
    """
    if not name:
        return None
    
    # Удаляем префиксы
    prefixes = ['р-н ', 'район ', 'мкр ', 'микрорайон ']
    clean_name = name
    for prefix in prefixes:
        if clean_name.lower().startswith(prefix):
            clean_name = clean_name[len(prefix):]
    
    return clean_name.strip()


def find_district_in_db(district_name, city_id):
    """
    Найти район в БД по имени и city_id.
    
    Пытается найти точное совпадение или частичное совпадение.
    """
    if not district_name or not city_id:
        return None
    
    normalized_name = normalize_district_name(district_name)
    
    # Точное совпадение
    district = District.query.filter_by(
        city_id=city_id,
        name=normalized_name
    ).first()
    
    if district:
        return district
    
    # Частичное совпадение (ILIKE)
    district = District.query.filter(
        District.city_id == city_id,
        District.name.ilike(f'%{normalized_name}%')
    ).first()
    
    if district:
        return district
    
    # Попытка с оригинальным именем
    district = District.query.filter(
        District.city_id == city_id,
        District.name.ilike(f'%{district_name}%')
    ).first()
    
    return district


def auto_assign_districts(dry_run=False, limit=None):
    """
    Автоматически привязать объекты к районам через DaData.
    
    Args:
        dry_run: Если True, не сохранять изменения в БД (только показать результаты)
        limit: Максимальное количество объектов для обработки (для тестирования)
    """
    with app.app_context():
        # Получить объекты с координатами, но без привязки к району
        query = Property.query.filter(
            Property.latitude.isnot(None),
            Property.longitude.isnot(None),
            Property.is_active == True
        )
        
        if limit:
            query = query.limit(limit)
        
        properties = query.all()
        
        print(f"\n📊 Найдено объектов с координатами: {len(properties)}")
        
        if dry_run:
            print("🔍 РЕЖИМ ТЕСТИРОВАНИЯ (изменения не сохраняются)\n")
        
        stats = {
            'total': len(properties),
            'assigned': 0,
            'failed': 0,
            'skipped': 0,
            'by_district': {}
        }
        
        for i, prop in enumerate(properties, 1):
            print(f"\n[{i}/{len(properties)}] ID={prop.id}: {prop.title}")
            print(f"  Координаты: {prop.latitude}, {prop.longitude}")
            
            # Skip if already assigned
            if prop.district_id:
                print(f"  ⏭️  Уже привязан к району (district_id={prop.district_id})")
                stats['skipped'] += 1
                continue
            
            # Get address from DaData
            address_data = geolocate_address(prop.latitude, prop.longitude)
            
            if not address_data:
                print("  ❌ Не удалось получить адрес от DaData")
                stats['failed'] += 1
                time.sleep(REQUEST_DELAY)
                continue
            
            # Extract district and city
            city_district = address_data.get('city_district')  # Район города
            city = address_data.get('city')  # Город
            region = address_data.get('region')  # Регион
            
            print(f"  📍 DaData: {region}, {city}, {city_district}")
            
            # Determine city_id from property's residential complex
            property_city_id = None
            if prop.complex_id:
                from models import ResidentialComplex
                rc = ResidentialComplex.query.get(prop.complex_id)
                if rc:
                    property_city_id = rc.city_id
            
            if not property_city_id:
                print("  ⚠️  Не удалось определить city_id объекта")
                stats['failed'] += 1
                time.sleep(REQUEST_DELAY)
                continue
            
            # Find district in database
            if not city_district:
                print("  ⚠️  DaData не вернул название района")
                stats['failed'] += 1
                time.sleep(REQUEST_DELAY)
                continue
            
            district = find_district_in_db(city_district, property_city_id)
            
            if district:
                print(f"  ✅ Найден район: {district.name} (ID={district.id})")
                
                if not dry_run:
                    prop.district_id = district.id
                    db.session.commit()
                    print("  💾 Сохранено в БД")
                
                stats['assigned'] += 1
                stats['by_district'][district.name] = stats['by_district'].get(district.name, 0) + 1
            else:
                print(f"  ⚠️  Район '{city_district}' не найден в БД для city_id={property_city_id}")
                stats['failed'] += 1
            
            # Rate limiting
            time.sleep(REQUEST_DELAY)
        
        # Print summary
        print("\n" + "="*60)
        print("📊 ИТОГОВАЯ СТАТИСТИКА")
        print("="*60)
        print(f"Всего объектов: {stats['total']}")
        print(f"✅ Успешно привязано: {stats['assigned']}")
        print(f"⏭️  Пропущено (уже привязаны): {stats['skipped']}")
        print(f"❌ Не удалось привязать: {stats['failed']}")
        
        if stats['by_district']:
            print("\n📍 Распределение по районам:")
            for district_name, count in sorted(stats['by_district'].items(), key=lambda x: x[1], reverse=True):
                print(f"  {district_name}: {count} объект(ов)")
        
        print("="*60)
        
        if dry_run:
            print("\n⚠️  РЕЖИМ ТЕСТИРОВАНИЯ: изменения не сохранены в БД")
        else:
            print("\n✅ Изменения сохранены в БД")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Автоматическая привязка объектов к районам через DaData')
    parser.add_argument('--dry-run', action='store_true', help='Режим тестирования (не сохранять изменения)')
    parser.add_argument('--limit', type=int, help='Максимальное количество объектов для обработки')
    
    args = parser.parse_args()
    
    print("🚀 Запуск автоматической привязки объектов к районам")
    print(f"DaData API Key: {'✅ Найден' if DADATA_API_KEY else '❌ Не найден'}")
    
    if not DADATA_API_KEY:
        print("\n❌ ОШИБКА: DADATA_API_KEY не найден в environment variables")
        print("Установите переменную окружения DADATA_API_KEY перед запуском скрипта")
        sys.exit(1)
    
    auto_assign_districts(dry_run=args.dry_run, limit=args.limit)
