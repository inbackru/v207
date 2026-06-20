#!/usr/bin/env python3
"""
Автоматическая привязка объектов к районам через DaData по АДРЕСУ.

Использует API DaData /suggest/address для стандартизации адреса и извлечения района.
Намного точнее, чем reverse geocoding по координатам.

Пример адреса: "Россия, Краснодарский край, Сочи, Кудепста м-н, Искра, 88 лит7"
Результат: city_district="Кудепста" → District "Адлерский"
"""

import os
import sys
import time
import requests

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Property, District, ResidentialComplex

# DaData API configuration
DADATA_API_KEY = os.environ.get('DADATA_API_KEY')
DADATA_SECRET_KEY = os.environ.get('DADATA_SECRET_KEY')
DADATA_SUGGEST_URL = 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address'

REQUEST_DELAY = 0.035  # 35ms between requests


def suggest_address(query):
    """
    Стандартизировать адрес через DaData suggest.
    
    Args:
        query: Строка адреса (например, "Сочи, Кудепста м-н")
    
    Returns:
        dict: Данные адреса с полями city_district, area, settlement и др.
        None: Если запрос не удался
    """
    if not DADATA_API_KEY or not query:
        return None
    
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Token {DADATA_API_KEY}'
    }
    
    if DADATA_SECRET_KEY:
        headers['X-Secret'] = DADATA_SECRET_KEY
    
    payload = {
        'query': query,
        'count': 1
    }
    
    try:
        response = requests.post(DADATA_SUGGEST_URL, json=payload, headers=headers, timeout=5)
        response.raise_for_status()
        
        data = response.json()
        suggestions = data.get('suggestions', [])
        
        if suggestions:
            return suggestions[0].get('data', {})
        
        return None
    
    except requests.exceptions.RequestException as e:
        print(f"⚠️  Ошибка запроса к DaData: {e}")
        return None


def extract_district_from_address(address_data):
    """
    Извлечь название района из DaData address data.
    
    Приоритет полей:
    1. city_district - район города (например, "Адлерский")
    2. area - административный район (для Сочи тоже может быть)
    3. settlement - населенный пункт в составе города
    4. city_area - территориальная зона
    """
    if not address_data:
        return None
    
    # Попробовать city_district
    district = address_data.get('city_district')
    if district:
        return district
    
    # Попробовать area (для Сочи районы могут быть здесь)
    area = address_data.get('area')
    area_type = address_data.get('area_type')
    if area and area_type in ['р-н', 'район']:
        return area
    
    # Попробовать settlement
    settlement = address_data.get('settlement')
    settlement_type = address_data.get('settlement_type')
    if settlement and settlement_type in ['мкр', 'микрорайон', 'м-н']:
        return settlement
    
    # Попробовать city_area
    city_area = address_data.get('city_area')
    if city_area:
        return city_area
    
    return None


def normalize_district_name(name):
    """Нормализовать название района."""
    if not name:
        return None
    
    # Удаляем префиксы
    prefixes = ['р-н ', 'район ', 'мкр ', 'микрорайон ', 'м-н ']
    clean_name = name
    for prefix in prefixes:
        if clean_name.lower().startswith(prefix):
            clean_name = clean_name[len(prefix):]
    
    return clean_name.strip()


def find_district_in_db(district_name, city_id):
    """Найти район в БД по имени и city_id."""
    if not district_name or not city_id:
        return None
    
    normalized_name = normalize_district_name(district_name)
    
    # Специальные маппинги для микрорайонов Сочи
    microdistrict_mappings = {
        'Кудепста': 'Адлерский',
        'Бытха': 'Центральный',
        'Мамайка': 'Центральный',
        'Дагомыс': 'Лазаревский',
        'Лоо': 'Лазаревский',
        'Аибга': 'Адлерский',
        'Красная Поляна': 'Адлерский'
    }
    
    # Проверить маппинг микрорайонов
    if normalized_name in microdistrict_mappings:
        mapped_name = microdistrict_mappings[normalized_name]
        district = District.query.filter(
            District.city_id == city_id,
            District.name.ilike(f'%{mapped_name}%')
        ).first()
        if district:
            return district
    
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
    
    # Попытка с окончанием "округ" для Краснодара
    district = District.query.filter(
        District.city_id == city_id,
        District.name.ilike(f'{normalized_name}%округ')
    ).first()
    if district:
        return district
    
    return None


def auto_assign_districts_by_address(dry_run=False, limit=None):
    """
    Автоматически привязать объекты к районам через DaData suggest.
    
    Args:
        dry_run: Если True, не сохранять изменения в БД
        limit: Максимальное количество объектов для обработки
    """
    with app.app_context():
        # Получить объекты без привязки к району
        query = Property.query.filter(
            Property.is_active == True,
            Property.district_id.is_(None)
        )
        
        if limit:
            query = query.limit(limit)
        
        properties = query.all()
        
        print(f"\n📊 Найдено объектов без district_id: {len(properties)}")
        
        if dry_run:
            print("🔍 РЕЖИМ ТЕСТИРОВАНИЯ (изменения не сохраняются)\n")
        
        stats = {
            'total': len(properties),
            'assigned': 0,
            'failed': 0,
            'no_address': 0,
            'by_district': {}
        }
        
        for i, prop in enumerate(properties, 1):
            print(f"\n[{i}/{len(properties)}] ID={prop.id}: {prop.title}")
            
            # Get address from property or residential complex
            address = prop.address
            if not address and prop.complex_id:
                rc = ResidentialComplex.query.get(prop.complex_id)
                if rc:
                    address = rc.address
            
            if not address:
                print("  ⚠️  Нет адреса (Property.address и RC.address пусты)")
                stats['no_address'] += 1
                continue
            
            print(f"  📍 Адрес: {address}")
            
            # Suggest address through DaData
            address_data = suggest_address(address)
            
            if not address_data:
                print("  ❌ Не удалось стандартизировать адрес через DaData")
                stats['failed'] += 1
                time.sleep(REQUEST_DELAY)
                continue
            
            # Extract district
            district_name = extract_district_from_address(address_data)
            city = address_data.get('city')
            city_district = address_data.get('city_district')
            area = address_data.get('area')
            settlement = address_data.get('settlement')
            
            print(f"  🏙️  DaData: город={city}, район={city_district}, area={area}, settlement={settlement}")
            
            if not district_name:
                print("  ⚠️  DaData не вернул название района")
                stats['failed'] += 1
                time.sleep(REQUEST_DELAY)
                continue
            
            # Determine city_id from property's residential complex
            property_city_id = None
            if prop.complex_id:
                rc = ResidentialComplex.query.get(prop.complex_id)
                if rc:
                    property_city_id = rc.city_id
            
            if not property_city_id:
                print("  ⚠️  Не удалось определить city_id объекта")
                stats['failed'] += 1
                time.sleep(REQUEST_DELAY)
                continue
            
            # Find district in database
            district = find_district_in_db(district_name, property_city_id)
            
            if district:
                print(f"  ✅ Найден район: {district.name} (ID={district.id})")
                
                if not dry_run:
                    prop.district_id = district.id
                    db.session.commit()
                    print("  💾 Сохранено в БД")
                
                stats['assigned'] += 1
                stats['by_district'][district.name] = stats['by_district'].get(district.name, 0) + 1
            else:
                print(f"  ⚠️  Район '{district_name}' не найден в БД для city_id={property_city_id}")
                stats['failed'] += 1
            
            # Rate limiting
            time.sleep(REQUEST_DELAY)
        
        # Print summary
        print("\n" + "="*60)
        print("📊 ИТОГОВАЯ СТАТИСТИКА")
        print("="*60)
        print(f"Всего объектов: {stats['total']}")
        print(f"✅ Успешно привязано: {stats['assigned']}")
        print(f"📭 Нет адреса: {stats['no_address']}")
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
    
    parser = argparse.ArgumentParser(description='Автоматическая привязка объектов к районам через DaData (по адресу)')
    parser.add_argument('--dry-run', action='store_true', help='Режим тестирования (не сохранять изменения)')
    parser.add_argument('--limit', type=int, help='Максимальное количество объектов для обработки')
    
    args = parser.parse_args()
    
    print("🚀 Запуск автоматической привязки объектов к районам (по адресу)")
    print(f"DaData API Key: {'✅ Найден' if DADATA_API_KEY else '❌ Не найден'}")
    
    if not DADATA_API_KEY:
        print("\n❌ ОШИБКА: DADATA_API_KEY не найден в environment variables")
        sys.exit(1)
    
    auto_assign_districts_by_address(dry_run=args.dry_run, limit=args.limit)
