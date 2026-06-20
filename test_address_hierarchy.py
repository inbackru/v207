#!/usr/bin/env python3
"""
Test Address Hierarchy Parsing
Shows how addresses are parsed into: Region → City → District → Street → House
"""

from services.geocoding import get_geocoding_service
from app import app, db
from models import Property
import json


def test_address_hierarchy():
    """Test geocoding with real properties from database"""
    
    with app.app_context():
        service = get_geocoding_service()
        
        print("=" * 80)
        print("ТЕСТ ИЕРАРХИИ АДРЕСОВ")
        print("=" * 80)
        
        # Get sample properties with coordinates
        properties = Property.query.filter(
            Property.latitude.isnot(None),
            Property.longitude.isnot(None)
        ).limit(5).all()
        
        if not properties:
            print("❌ Нет объектов с координатами в базе данных")
            return
        
        print(f"\nНайдено объектов: {len(properties)}\n")
        
        for i, prop in enumerate(properties, 1):
            print(f"\n{'='*80}")
            print(f"ОБЪЕКТ #{i}: {prop.title}")
            print(f"{'='*80}")
            print(f"ID объекта: {prop.id}")
            print(f"Координаты: {prop.latitude}, {prop.longitude}")
            print(f"Адрес в БД: {prop.address or 'не указан'}")
            
            # Get address components via geocoding
            print("\n🔍 ГЕОКОДИРОВАНИЕ...")
            result = service.reverse_geocode(prop.latitude, prop.longitude)
            
            if result:
                print("\n✅ УСПЕШНО РАСПАРСЕНО:")
                print("-" * 80)
                print(f"📍 ПОЛНЫЙ АДРЕС: {result.get('formatted_address', 'N/A')}")
                print("\n🏛️  ИЕРАРХИЯ АДРЕСА:")
                print(f"   ├─ Страна:          {result.get('country', 'не определена')}")
                print(f"   ├─ Регион:          {result.get('region', 'не определён')}")
                print(f"   ├─ Город:           {result.get('city', 'не определён')}")
                print(f"   ├─ Округ/Район:     {result.get('district', 'не определён') or 'не определён'}")
                print(f"   ├─ Улица:           {result.get('street', 'не определена')}")
                print(f"   ├─ Дом:             {result.get('house', 'не определён')}")
                print(f"   └─ Индекс:          {result.get('postal_code', 'не определён') or 'не определён'}")
                
                print("\n📊 МЕТАДАННЫЕ:")
                print(f"   ├─ Тип объекта:     {result.get('kind', 'unknown')}")
                print(f"   └─ Точность:        {result.get('precision', 'unknown')}")
                
                # Show what will be saved to database
                print("\n💾 ДАННЫЕ ДЛЯ БАЗЫ:")
                print(f"   ├─ parsed_city:     '{result.get('city', '')}'")
                print(f"   ├─ parsed_district: '{result.get('district', '')}'")
                print(f"   └─ parsed_street:   '{result.get('street', '')}'")
                
            else:
                print("❌ Не удалось получить адрес")
        
        # Show service statistics
        print(f"\n{'='*80}")
        print("СТАТИСТИКА СЕРВИСА")
        print(f"{'='*80}")
        stats = service.get_stats()
        print(f"API запросов: {stats['api_requests']}")
        print(f"Попаданий в кэш: {stats['cache_hits']}")
        print(f"Размер кэша: {stats['cache_size']}")
        print(f"Процент попаданий: {stats['cache_hit_rate']}")
        
        print(f"\n{'='*80}")
        print("ТЕСТ ЗАВЕРШЁН")
        print(f"{'='*80}\n")


if __name__ == "__main__":
    test_address_hierarchy()
