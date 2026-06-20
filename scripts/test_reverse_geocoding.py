"""
Пример: Обратное геокодирование (координаты → адрес с районом/микрорайоном)

Использует существующие сервисы:
1. Yandex Geocoder - быстрый reverse geocoding
2. DaData - детальная разбивка адреса

Применение: Найти квартиры в районе "Гидрострой" по координатам
"""

import sys
from app import app
from services.geocoding import get_geocoding_service
from services.dadata_client import get_dadata_client


def test_yandex_reverse_geocoding():
    """Тест Yandex Geocoder API - reverse geocoding"""
    print("\n" + "="*80)
    print("🗺️  YANDEX GEOCODER - Reverse Geocoding (координаты → адрес)")
    print("="*80 + "\n")
    
    geocoding_service = get_geocoding_service()
    
    # Пример координат разных районов Краснодара
    test_locations = [
        {"name": "Гидрострой", "lat": 45.0355, "lon": 38.9753},
        {"name": "Центр", "lat": 45.0355, "lon": 38.9753},
        {"name": "Прикубанский округ", "lat": 45.0211, "lon": 39.0222},
    ]
    
    for location in test_locations:
        print(f"\n📍 Тестируем: {location['name']}")
        print(f"   Координаты: {location['lat']}, {location['lon']}")
        print("-" * 80)
        
        result = geocoding_service.reverse_geocode(
            latitude=location['lat'],
            longitude=location['lon']
        )
        
        if result:
            print(f"✅ Полный адрес: {result['formatted_address']}")
            print(f"   🏙️  Город: {result.get('city', 'Не указано')}")
            print(f"   🗺️  Район: {result.get('district', 'Не указано')}")
            print(f"   🛣️  Улица: {result.get('street', 'Не указано')}")
            print(f"   🏠 Дом: {result.get('house', 'Не указано')}")
            print(f"   📮 Индекс: {result.get('postal_code', 'Не указано')}")
            print(f"   🎯 Точность: {result.get('precision', 'unknown')}")
        else:
            print("❌ Не удалось получить адрес")
    
    # Статистика
    stats = geocoding_service.get_stats()
    print("\n" + "="*80)
    print("📊 СТАТИСТИКА YANDEX GEOCODER")
    print(f"   API запросов: {stats['api_requests']}")
    print(f"   Cache hits: {stats['cache_hits']}")
    print(f"   Cache hit rate: {stats['cache_hit_rate']}")
    print("="*80 + "\n")


def test_dadata_address_parsing():
    """Тест DaData - детальная разбивка адреса"""
    print("\n" + "="*80)
    print("🔍 DADATA - Детальная разбивка адреса")
    print("="*80 + "\n")
    
    dadata_client = get_dadata_client()
    
    if not dadata_client.is_available():
        print("⚠️  DaData API недоступна (нет DADATA_API_KEY)")
        print("   Для использования DaData установите переменные окружения:")
        print("   - DADATA_API_KEY")
        print("   - DADATA_SECRET_KEY (опционально)")
        return
    
    # Пример адреса для разбивки
    test_address = "Краснодар, микрорайон Гидрострой, улица Российская"
    
    print(f"📝 Входной адрес: {test_address}")
    print("-" * 80)
    
    result = dadata_client.enrich_property_address(
        address_text=test_address,
        city_id=1  # Краснодар
    )
    
    if result:
        print(f"✅ Обогащённый адрес:")
        print(f"   🏙️  Город: {result.get('parsed_city', 'Не указано')}")
        print(f"   🗺️  Административный район: {result.get('parsed_area', 'Не указано')}")
        print(f"   🏘️  Микрорайон/НП: {result.get('parsed_settlement', 'Не указано')}")
        print(f"   🛣️  Улица: {result.get('parsed_street', 'Не указано')}")
        print(f"   🏠 Дом: {result.get('parsed_house', 'Не указано')}")
        print(f"   🏢 Корпус: {result.get('parsed_block', 'Не указано')}")
        print(f"   📍 Координаты: {result.get('latitude')}, {result.get('longitude')}")
        print(f"   📝 Полный адрес: {result.get('full_address', '')}")
    else:
        print("❌ Не удалось обогатить адрес")


def test_find_properties_by_district():
    """Пример: Найти квартиры в районе по координатам"""
    print("\n" + "="*80)
    print("🏘️  ПОИСК КВАРТИР В РАЙОНЕ ПО КООРДИНАТАМ")
    print("="*80 + "\n")
    
    from models import Property
    
    # 1. Получаем название района по координатам
    geocoding_service = get_geocoding_service()
    
    district_coords = {"lat": 45.0355, "lon": 38.9753}
    print(f"📍 Координаты района: {district_coords['lat']}, {district_coords['lon']}")
    
    result = geocoding_service.reverse_geocode(
        latitude=district_coords['lat'],
        longitude=district_coords['lon']
    )
    
    if not result:
        print("❌ Не удалось определить район")
        return
    
    district_name = result.get('district', '')
    city_name = result.get('city', '')
    
    print(f"✅ Определён район: {district_name}, {city_name}")
    print("-" * 80)
    
    # 2. Ищем квартиры в этом районе
    if district_name:
        properties = Property.query.filter(
            Property.parsed_district.ilike(f"%{district_name}%"),
            Property.is_active == True
        ).limit(5).all()
        
        print(f"\n🏠 Найдено квартир в районе '{district_name}': {len(properties)}")
        print("-" * 80)
        
        for i, prop in enumerate(properties, 1):
            print(f"\n{i}. {prop.title}")
            print(f"   💰 Цена: {prop.price:,.0f} ₽")
            print(f"   📏 Площадь: {prop.area} м²")
            print(f"   📍 Адрес: {prop.address}")
            print(f"   🗺️  Район: {prop.parsed_district}")
    else:
        print("⚠️  Район не определён")


def main():
    """Главная функция для тестирования"""
    with app.app_context():
        print("\n" + "🚀"*40)
        print("REVERSE GEOCODING - Тестирование")
        print("🚀"*40)
        
        # Тест 1: Yandex Geocoder
        test_yandex_reverse_geocoding()
        
        # Тест 2: DaData
        test_dadata_address_parsing()
        
        # Тест 3: Поиск квартир по координатам района
        test_find_properties_by_district()
        
        print("\n" + "✅"*40)
        print("Тестирование завершено!")
        print("✅"*40 + "\n")


if __name__ == "__main__":
    main()
