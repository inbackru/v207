#!/usr/bin/env python3
"""
ПРИМЕР ИМПОРТА С АВТОМАТИЧЕСКИМ ОПРЕДЕЛЕНИЕМ ПРОДАННЫХ ОБЪЕКТОВ

Использование:
    python scripts/import_with_auto_sold_detection.py path/to/data.xlsx
    python scripts/import_with_auto_sold_detection.py --source=api --url=https://api.example.com/properties

Как работает:
1. Импортирует данные из Excel/API/парсера
2. Для каждого объекта устанавливает external_id и last_seen_at
3. После импорта автоматически определяет какие объекты исчезли (проданы)
4. Отправляет уведомления пользователям о проданных объектах
"""

import sys
import os
import pandas as pd
import logging
from datetime import datetime
from typing import List, Dict

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db
from services.property_sync_service import PropertySyncService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def import_from_excel(excel_path: str, source_name: str = "excel") -> Dict:
    """
    Импорт объектов из Excel файла с автоматическим определением проданных.
    
    Args:
        excel_path: Путь к Excel файлу
        source_name: Название источника данных
    
    Returns:
        Статистика импорта
    """
    logger.info(f"📥 Начинаем импорт из {excel_path}")
    
    # Читаем Excel
    df = pd.read_excel(excel_path)
    logger.info(f"📊 Загружено {len(df)} строк из Excel")
    
    # Конвертируем DataFrame в список словарей
    properties_data = []
    
    for idx, row in df.iterrows():
        try:
            prop_dict = {
                # Уникальный идентификатор (ОБЯЗАТЕЛЬНО!)
                'external_id': row.get('ID') or row.get('id') or f"row_{idx}",
                
                # Основные данные
                'title': row.get('Название') or row.get('title') or f"Объект {idx}",
                'description': row.get('Описание') or row.get('description'),
                'address': row.get('Адрес') or row.get('address'),
                
                # Характеристики
                'rooms': int(row['Комнаты']) if pd.notna(row.get('Комнаты')) else None,
                'area': float(row['Площадь']) if pd.notna(row.get('Площадь')) else None,
                'floor': int(row['Этаж']) if pd.notna(row.get('Этаж')) else None,
                'total_floors': int(row['Этажность']) if pd.notna(row.get('Этажность')) else None,
                
                # Цена
                'price': int(row['Цена']) if pd.notna(row.get('Цена')) else None,
                'price_per_sqm': int(row['Цена за м²']) if pd.notna(row.get('Цена за м²')) else None,
                
                # Координаты
                'latitude': float(row['Широта']) if pd.notna(row.get('Широта')) else None,
                'longitude': float(row['Долгота']) if pd.notna(row.get('Долгота')) else None,
                
                # Город (по умолчанию Краснодар)
                'city_id': int(row.get('city_id', 1)),
                
                # Ссылка на источник
                'source_url': row.get('URL') or row.get('url'),
                'main_image': row.get('Фото') or row.get('image')
            }
            
            properties_data.append(prop_dict)
            
        except Exception as e:
            logger.warning(f"Ошибка обработки строки {idx}: {e}")
            continue
    
    logger.info(f"✅ Подготовлено {len(properties_data)} объектов для импорта")
    
    # Запускаем импорт через PropertySyncService
    sync_service = PropertySyncService()
    stats = sync_service.process_import_batch(
        properties_data=properties_data,
        source_name=source_name,
        auto_detect_sold=True  # АВТОМАТИЧЕСКОЕ ОПРЕДЕЛЕНИЕ ПРОДАННЫХ
    )
    
    return stats


def import_from_api(api_url: str, source_name: str = "api") -> Dict:
    """
    Импорт объектов из API с автоматическим определением проданных.
    
    Args:
        api_url: URL API endpoint
        source_name: Название источника данных
    
    Returns:
        Статистика импорта
    """
    import requests
    
    logger.info(f"📥 Получаем данные из API: {api_url}")
    
    try:
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Предполагаем что API возвращает список объектов
        if isinstance(data, dict) and 'properties' in data:
            properties_data = data['properties']
        elif isinstance(data, list):
            properties_data = data
        else:
            raise ValueError("Неожиданный формат данных от API")
        
        logger.info(f"✅ Получено {len(properties_data)} объектов из API")
        
        # Запускаем импорт
        sync_service = PropertySyncService()
        stats = sync_service.process_import_batch(
            properties_data=properties_data,
            source_name=source_name,
            auto_detect_sold=True
        )
        
        return stats
        
    except Exception as e:
        logger.error(f"Ошибка получения данных из API: {e}")
        raise


def import_from_parser(parser_output: List[Dict], source_name: str = "parser") -> Dict:
    """
    Импорт объектов из парсера с автоматическим определением проданных.
    
    Args:
        parser_output: Список объектов от парсера
        source_name: Название источника данных
    
    Returns:
        Статистика импорта
    """
    logger.info(f"📥 Импорт из парсера: {len(parser_output)} объектов")
    
    sync_service = PropertySyncService()
    stats = sync_service.process_import_batch(
        properties_data=parser_output,
        source_name=source_name,
        auto_detect_sold=True
    )
    
    return stats


def print_stats(stats: Dict):
    """Красиво выводим статистику импорта."""
    print("\n" + "="*60)
    print("📊 СТАТИСТИКА ИМПОРТА")
    print("="*60)
    print(f"Источник: {stats['source']}")
    print(f"Время: {stats['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n📦 Обработано объектов:")
    print(f"  • Всего: {stats['total']}")
    print(f"  • Создано новых: {stats['created']}")
    print(f"  • Обновлено существующих: {stats['updated']}")
    print(f"  • Ошибок: {stats['errors']}")
    
    if 'sold_detected' in stats:
        sold = stats['sold_detected']
        print(f"\n🏷️  Автоматическое определение проданных:")
        print(f"  • Проверено объектов: {sold['total_checked']}")
        print(f"  • Помечено как проданные: {sold['newly_sold']}")
        print(f"  • Пользователей уведомлено: {sold['users_notified']}")
        print(f"  • Уведомлений отправлено: {sold['notifications_sent']}")
    
    print("="*60 + "\n")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Импорт объектов с автоматическим определением проданных")
    parser.add_argument('file', nargs='?', help='Путь к файлу Excel')
    parser.add_argument('--source', default='excel', help='Название источника данных')
    parser.add_argument('--api-url', help='URL API для получения данных')
    
    args = parser.parse_args()
    
    with app.app_context():
        try:
            if args.api_url:
                # Импорт из API
                stats = import_from_api(args.api_url, source_name=args.source)
            elif args.file:
                # Импорт из Excel
                if not os.path.exists(args.file):
                    print(f"❌ Файл не найден: {args.file}")
                    sys.exit(1)
                stats = import_from_excel(args.file, source_name=args.source)
            else:
                print("❌ Укажите файл или --api-url")
                parser.print_help()
                sys.exit(1)
            
            print_stats(stats)
            print("✅ Импорт завершен успешно!")
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
