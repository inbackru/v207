#!/usr/bin/env python3
"""
Пример использования ParserImportService для импорта данных от парсера

Этот скрипт показывает, как парсер может автоматически добавлять данные
о застройщиках, ЖК, корпусах и квартирах с автоматической транслитерацией slug

ВАЖНО:
- Все функции import_* поддерживают параметр auto_commit (по умолчанию True)
- Для batch импорта используйте auto_commit=False и делайте commit вручную
- Это критично для производительности при импорте 10,000+ квартир
"""

import sys
import os

# Добавляем путь к приложению
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from services.parser_import_service import ParserImportService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def example_import_full_hierarchy():
    """
    Пример импорта полной иерархии: Застройщик → ЖК → Корпуса → Квартиры
    """
    with app.app_context():
        # Данные застройщика от парсера
        developer_data = {
            'name': 'НОВЫЙ ЗАСТРОЙЩИК 2025',
            'external_id': 'dev_2025_001',
            'full_name': 'ООО "Новый Застройщик 2025"',
            'website': 'novyy-zastroyschik.ru',
            'phone': '+7 (861) 123-45-67',
            'email': 'info@novyy-zastroyschik.ru',
            'address': 'г. Краснодар, ул. Красная, 1',
            'latitude': 45.035470,
            'longitude': 38.975313,
            'established_year': 2025,
            'description': 'Современная строительная компания'
        }
        
        # Данные ЖК от парсера
        complex_data = {
            'name': 'ЖК Новый Горизонт',
            'external_id': 'complex_2025_001',
            'address': 'г. Краснодар, ул. Тургенева, 100',
            'phone': '+7 (861) 234-56-78',
            'latitude': 45.040000,
            'longitude': 38.980000,
            'description': 'Современный жилой комплекс бизнес-класса',
            'complex_type': 'residential',
            'class_name': 'Бизнес'
        }
        
        # Данные корпусов от парсера
        buildings_data = [
            {
                'name': 'Корпус 1',
                'external_id': 'building_2025_001_1',
                'end_build_year': 2026,
                'end_build_quarter': 2,
                'released': False,
                'has_accreditation': True,
                'has_green_mortgage': True
            },
            {
                'name': 'Корпус 2',
                'external_id': 'building_2025_001_2',
                'end_build_year': 2026,
                'end_build_quarter': 4,
                'released': False,
                'has_accreditation': True,
                'has_green_mortgage': False
            }
        ]
        
        # Данные квартир от парсера
        properties_data = [
            {
                'external_id': 'prop_2025_001',
                'building_name': 'Корпус 1',
                'rooms': 2,
                'area': 65.5,
                'floor': 5,
                'total_floors': 17,
                'price': 5500000,
                'price_per_sqm': 84000,
                'has_balcony': True,
                'has_loggia': False,
                'ceiling_height': 2.7,
                'finishing': 'Без отделки'
            },
            {
                'external_id': 'prop_2025_002',
                'building_name': 'Корпус 1',
                'rooms': 1,
                'area': 42.3,
                'floor': 3,
                'total_floors': 17,
                'price': 3800000,
                'price_per_sqm': 89800,
                'has_balcony': True,
                'has_loggia': False,
                'ceiling_height': 2.7,
                'finishing': 'Чистовая'
            },
            {
                'external_id': 'prop_2025_003',
                'building_name': 'Корпус 2',
                'rooms': 3,
                'area': 85.2,
                'floor': 10,
                'total_floors': 20,
                'price': 7800000,
                'price_per_sqm': 91500,
                'has_balcony': True,
                'has_loggia': True,
                'ceiling_height': 2.9,
                'finishing': 'Без отделки'
            }
        ]
        
        # Импортируем полную иерархию
        result = ParserImportService.import_full_hierarchy(
            developer_data=developer_data,
            complex_data=complex_data,
            buildings_data=buildings_data,
            properties_data=properties_data,
            city_name='Краснодар'
        )
        
        # Выводим результаты
        print("\n" + "="*80)
        print("✅ ИМПОРТ ЗАВЕРШЁН УСПЕШНО!")
        print("="*80)
        print(f"\n📍 Застройщик: {result['developer'].name}")
        print(f"   Slug: {result['developer'].slug}")
        print(f"   URL: /developer/{result['developer'].slug}")
        
        print(f"\n🏘️  ЖК: {result['complex'].name}")
        print(f"   Slug: {result['complex'].slug}")
        print(f"   URL: /krasnodar/zhk/{result['complex'].slug}")
        
        print(f"\n🏢 Корпусов: {len(result['buildings'])}")
        for building in result['buildings']:
            print(f"   - {building.name} (slug: {building.slug})")
        
        print(f"\n🏠 Квартир: {len(result['properties'])}")
        for prop in result['properties']:
            print(f"   - {prop.title} (external_id: {prop.external_id})")
        
        print("\n" + "="*80)


def example_import_single_property():
    """
    Пример импорта отдельной квартиры
    (когда парсер обновляет данные существующих квартир)
    """
    with app.app_context():
        property_data = {
            'external_id': 'prop_2025_001',  # Существующая квартира
            'rooms': 2,
            'area': 65.5,
            'floor': 5,
            'total_floors': 17,
            'price': 5400000,  # Обновлённая цена
            'price_per_sqm': 82400,  # Обновлённая цена за м²
            'has_balcony': True,
            'has_loggia': False,
            'ceiling_height': 2.7,
            'finishing': 'Без отделки'
        }
        
        property_obj = ParserImportService.import_property(
            property_data,
            complex_name='ЖК Новый Горизонт',
            building_name='Корпус 1',
            city_name='Краснодар'
        )
        
        print("\n✅ Квартира обновлена:")
        print(f"   {property_obj.title}")
        print(f"   Цена: {property_obj.price:,} ₽")
        print(f"   external_id: {property_obj.external_id}")


def example_batch_import_large_dataset():
    """
    Пример BATCH импорта большого количества квартир (10,000+)
    
    Демонстрирует правильное управление транзакциями для максимальной производительности.
    auto_commit=False позволяет контролировать, когда делать commit.
    """
    with app.app_context():
        print("\n" + "="*80)
        print("🚀 BATCH ИМПОРТ: Импорт 10,000+ квартир с оптимальной производительностью")
        print("="*80)
        
        # 1. Создаём застройщика и ЖК один раз (с auto_commit=True)
        developer_data = {
            'name': 'БОЛЬШОЙ ЗАСТРОЙЩИК',
            'external_id': 'dev_batch_001',
            'description': 'Застройщик для batch импорта'
        }
        
        complex_data = {
            'name': 'ЖК Большой Комплекс',
            'external_id': 'complex_batch_001',
            'address': 'г. Краснодар, ул. Примерная, 1'
        }
        
        developer = ParserImportService.import_developer(developer_data, auto_commit=True)
        complex = ParserImportService.import_residential_complex(
            complex_data,
            developer_name=developer.name,
            city_name='Краснодар',
            auto_commit=True
        )
        
        print(f"\n✅ Создан застройщик: {developer.name}")
        print(f"✅ Создан ЖК: {complex.name}")
        
        # 2. Создаём корпуса (batch, без commit после каждого)
        print("\n📦 Импорт корпусов...")
        buildings_count = 10  # Например, 10 корпусов
        
        for i in range(1, buildings_count + 1):
            building_data = {
                'name': f'Корпус {i}',
                'external_id': f'building_batch_{i:03d}',
                'end_build_year': 2026,
                'end_build_quarter': (i % 4) + 1
            }
            ParserImportService.import_building(
                building_data,
                complex_name=complex.name,
                city_name='Краснодар',
                auto_commit=False  # НЕ делаем commit после каждого корпуса
            )
        
        # Commit для всех корпусов один раз
        db.session.commit()
        print(f"✅ Импортировано {buildings_count} корпусов (1 commit)")
        
        # 3. Импортируем квартиры ПАЧКАМИ (batch processing)
        print("\n🏠 Импорт квартир пачками...")
        
        # Генерируем данные квартир (в реальности это данные от парсера)
        total_properties = 1000  # Например, 1000 квартир для демо (в реале 10,000+)
        batch_size = 100  # Commit каждые 100 квартир
        
        properties_imported = 0
        
        for batch_start in range(0, total_properties, batch_size):
            batch_end = min(batch_start + batch_size, total_properties)
            
            # Импортируем batch без commit
            for i in range(batch_start, batch_end):
                property_data = {
                    'external_id': f'prop_batch_{i:05d}',
                    'building_name': f'Корпус {(i % buildings_count) + 1}',
                    'rooms': (i % 3) + 1,  # 1, 2 или 3 комнаты
                    'area': 40 + (i % 50),  # 40-90 м²
                    'floor': (i % 17) + 1,  # 1-17 этаж
                    'total_floors': 17,
                    'price': 4000000 + (i * 10000),  # Разные цены
                    'price_per_sqm': 85000
                }
                
                ParserImportService.import_property(
                    property_data,
                    complex_name=complex.name,
                    building_name=property_data['building_name'],
                    city_name='Краснодар',
                    auto_commit=False  # НЕ делаем commit после каждой квартиры
                )
            
            # Commit для batch
            db.session.commit()
            properties_imported = batch_end
            print(f"   ✅ Импортировано {properties_imported}/{total_properties} квартир "
                  f"(batch {batch_start//batch_size + 1}/{(total_properties + batch_size - 1)//batch_size})")
        
        print("\n" + "="*80)
        print(f"🎉 BATCH ИМПОРТ ЗАВЕРШЁН!")
        print(f"   Застройщиков: 1")
        print(f"   ЖК: 1")
        print(f"   Корпусов: {buildings_count}")
        print(f"   Квартир: {total_properties}")
        print(f"   Commits: {1 + 1 + (total_properties // batch_size)} (вместо {1 + 1 + buildings_count + total_properties})")
        print("="*80)
        print("\n💡 КЛЮЧЕВЫЕ МОМЕНТЫ:")
        print("   - auto_commit=False позволяет контролировать транзакции")
        print("   - Batch processing сокращает количество commits в сотни раз")
        print("   - last_seen_at обновляется автоматически для каждой квартиры")
        print("   - external_id используется для поиска существующих записей")
        print("="*80)


if __name__ == '__main__':
    print("Пример 1: Импорт полной иерархии")
    print("-" * 80)
    example_import_full_hierarchy()
    
    print("\n\nПример 2: Обновление отдельной квартиры")
    print("-" * 80)
    example_import_single_property()
    
    print("\n\nПример 3: BATCH ИМПОРТ для больших данных (10,000+ квартир)")
    print("-" * 80)
    example_batch_import_large_dataset()
