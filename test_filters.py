#!/usr/bin/env python3
"""
Скрипт для тестирования всех фильтров на странице свойств
"""

import requests
import sys
from urllib.parse import urlencode

BASE_URL = "http://localhost:5000"

def test_filter(city_slug, filters, expected_min=None, expected_max=None, description=""):
    """Тестирует фильтр и проверяет результат"""
    url = f"{BASE_URL}/{city_slug}/properties?{urlencode(filters, doseq=True)}"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            print(f"❌ {description}: Ошибка {response.status_code}")
            return False
        
        # Проверяем, что страница загружается
        if "Найдите идеальную квартиру" not in response.text:
            print(f"❌ {description}: Страница не загрузилась корректно")
            return False
        
        print(f"✅ {description}: OK")
        return True
        
    except Exception as e:
        print(f"❌ {description}: Исключение - {str(e)}")
        return False

def test_api_count(city_id, filters, description=""):
    """Тестирует API подсчета через AJAX"""
    url = f"{BASE_URL}/api/properties/count"
    
    # Добавляем city_id к фильтрам
    filters['city_id'] = city_id
    
    try:
        response = requests.get(url, params=filters, timeout=10)
        if response.status_code != 200:
            print(f"❌ API {description}: Ошибка {response.status_code}")
            return False
        
        data = response.json()
        count = data.get('count', 0)
        print(f"✅ API {description}: {count} объектов")
        return True
        
    except Exception as e:
        print(f"❌ API {description}: Исключение - {str(e)}")
        return False

def main():
    print("\n" + "="*80)
    print("ТЕСТИРОВАНИЕ ФИЛЬТРОВ НЕДВИЖИМОСТИ")
    print("="*80 + "\n")
    
    cities = [
        {"id": 1, "slug": "krasnodar", "name": "Краснодар"},
        {"id": 2, "slug": "sochi", "name": "Сочи"},
        {"id": 3, "slug": "anapa", "name": "Анапа"}
    ]
    
    for city in cities:
        city_id = city['id']
        city_slug = city['slug']
        city_name = city['name']
        
        print(f"\n{'='*80}")
        print(f"ГОРОД: {city_name.upper()}")
        print(f"{'='*80}\n")
        
        # 1. ФИЛЬТРЫ ПЛОЩАДИ
        print(f"--- ПЛОЩАДЬ ---")
        test_api_count(city_id, {'area_min': '30'}, f"{city_name}: Площадь от 30м²")
        test_api_count(city_id, {'area_max': '60'}, f"{city_name}: Площадь до 60м²")
        test_api_count(city_id, {'area_min': '40', 'area_max': '80'}, f"{city_name}: Площадь 40-80м²")
        
        # 2. ФИЛЬТРЫ ЭТАЖА
        print(f"\n--- ЭТАЖ ---")
        test_api_count(city_id, {'floor_min': '2'}, f"{city_name}: Этаж от 2")
        test_api_count(city_id, {'floor_max': '10'}, f"{city_name}: Этаж до 10")
        test_api_count(city_id, {'floor_options[]': 'not_first'}, f"{city_name}: Не первый этаж")
        test_api_count(city_id, {'floor_options[]': 'not_last'}, f"{city_name}: Не последний этаж")
        test_api_count(city_id, {'floor_options[]': 'last'}, f"{city_name}: Последний этаж")
        
        # 3. ФИЛЬТРЫ ОТДЕЛКИ
        print(f"\n--- ОТДЕЛКА ---")
        test_api_count(city_id, {'renovation[]': 'no_renovation'}, f"{city_name}: Без отделки")
        test_api_count(city_id, {'renovation[]': 'with_renovation'}, f"{city_name}: Чистовая")
        
        # 4. ФИЛЬТРЫ ИПОТЕКИ
        print(f"\n--- ИПОТЕКА ---")
        test_api_count(city_id, {'features[]': 'accreditation'}, f"{city_name}: Аккредитация банков")
        test_api_count(city_id, {'features[]': 'green_mortgage'}, f"{city_name}: Льготная ипотека")
        
        # 5. СТАТУС ДОМА
        print(f"\n--- СТАТУС ДОМА ---")
        test_api_count(city_id, {'building_released[]': 'true'}, f"{city_name}: Сданный дом")
        test_api_count(city_id, {'building_released[]': 'false'}, f"{city_name}: В строительстве")
        
        # 6. СРОК СДАЧИ
        print(f"\n--- СРОК СДАЧИ ---")
        test_api_count(city_id, {'completion[]': '2024'}, f"{city_name}: Срок сдачи 2024")
        test_api_count(city_id, {'completion[]': '2025'}, f"{city_name}: Срок сдачи 2025")
        test_api_count(city_id, {'completion[]': '2026'}, f"{city_name}: Срок сдачи 2026")
        
        # 7. ЭТАЖНОСТЬ ДОМА
        print(f"\n--- ЭТАЖНОСТЬ ДОМА ---")
        test_api_count(city_id, {'building_floors_min': '5'}, f"{city_name}: Этажность от 5")
        test_api_count(city_id, {'building_floors_max': '15'}, f"{city_name}: Этажность до 15")
        
        # 8. КЛАСС ЖИЛЬЯ
        if city_id in [1, 2]:  # Только Краснодар и Сочи имеют классы
            print(f"\n--- КЛАСС ЖИЛЬЯ ---")
            test_api_count(city_id, {'object_classes[]': 'Бизнес'}, f"{city_name}: Класс Бизнес")
            test_api_count(city_id, {'object_classes[]': 'Комфорт'}, f"{city_name}: Класс Комфорт")
            test_api_count(city_id, {'object_classes[]': 'Премиум'}, f"{city_name}: Класс Премиум")
        
        # 9. КОМБИНИРОВАННЫЕ ФИЛЬТРЫ
        print(f"\n--- КОМБИНИРОВАННЫЕ ФИЛЬТРЫ ---")
        test_api_count(
            city_id, 
            {
                'area_min': '30',
                'area_max': '100',
                'floor_min': '2',
                'features[]': 'accreditation'
            }, 
            f"{city_name}: Площадь 30-100м² + этаж от 2 + аккредитация"
        )
        
        print("\n")
    
    print("\n" + "="*80)
    print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
