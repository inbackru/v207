#!/usr/bin/env python3
"""
Импорт всех районов и микрорайонов города из DaData API.

Этот скрипт использует DaData API для получения полного списка
административных районов и микрорайонов города, аналогично справочнику
Яндекс.Недвижимости.

Использование:
    # Для Краснодара
    python scripts/import_districts_from_dadata.py --city-name "Краснодар" --city-id 1
    
    # Для Сочи
    python scripts/import_districts_from_dadata.py --city-name "Сочи" --city-id 2
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import District, City
import requests
import logging
from utils.transliteration import create_slug

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DaDataDistrictImporter:
    """Импортер районов из DaData API"""
    
    def __init__(self, api_key=None, secret_key=None):
        self.api_key = api_key or os.environ.get('DADATA_API_KEY')
        self.secret_key = secret_key or os.environ.get('DADATA_SECRET_KEY')
        
        if not self.api_key:
            raise ValueError(
                "❌ DADATA_API_KEY не найден!\n"
                "Получите API ключ на https://dadata.ru/api/\n"
                "Установите через: export DADATA_API_KEY='ваш_ключ'"
            )
        
        self.base_url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs"
        self.headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def get_city_districts(self, city_name):
        """
        Получает список районов города через DaData API.
        
        Args:
            city_name: Название города ("Краснодар", "Сочи", и т.д.)
        
        Returns:
            List[dict]: Список районов с метаданными
        """
        logger.info(f"🔍 Получение районов для города: {city_name}")
        
        # Запрос всех адресов города с группировкой по районам
        url = f"{self.base_url}/suggest/address"
        
        districts = []
        seen_names = set()
        
        # Получаем районы через поиск по городу + "район"
        for query_suffix in ["округ", "район", "микрорайон", "мкр"]:
            query = f"г. {city_name}, {query_suffix}"
            
            payload = {
                "query": query,
                "count": 20,
                "locations": [{"city": city_name}],
                "restrict_value": True
            }
            
            try:
                response = requests.post(url, json=payload, headers=self.headers, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                for suggestion in data.get('suggestions', []):
                    district_data = suggestion.get('data', {})
                    
                    # Извлекаем район
                    district_name = (
                        district_data.get('city_district') or
                        district_data.get('settlement') or
                        district_data.get('area')
                    )
                    
                    if district_name and district_name not in seen_names:
                        districts.append({
                            'name': district_name,
                            'type': district_data.get('city_district_type', 'район'),
                            'fias_id': district_data.get('city_district_fias_id'),
                            'kladr_id': district_data.get('city_district_kladr_id'),
                        })
                        seen_names.add(district_name)
                
                logger.info(f"  ✅ Найдено {len(data.get('suggestions', []))} результатов для '{query_suffix}'")
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"  ⚠️  Ошибка при запросе '{query_suffix}': {e}")
                continue
        
        logger.info(f"📊 Всего уникальных районов: {len(districts)}")
        return districts
    
    def import_districts_to_db(self, city_id, city_name, dry_run=False):
        """
        Импортирует районы в таблицу districts.
        
        Args:
            city_id: ID города в БД
            city_name: Название города
            dry_run: Если True, только показывает что будет импортировано
        """
        logger.info("=" * 60)
        logger.info(f"🏙️  Импорт районов для города: {city_name} (ID={city_id})")
        if dry_run:
            logger.info("⚠️  DRY RUN MODE - изменения НЕ будут сохранены")
        logger.info("=" * 60)
        logger.info("")
        
        # Получаем районы из DaData
        districts = self.get_city_districts(city_name)
        
        if not districts:
            logger.warning("⚠️  Районы не найдены через DaData API")
            return 0
        
        logger.info("")
        logger.info("📋 Найденные районы:")
        for idx, district in enumerate(districts, 1):
            logger.info(f"  {idx}. {district['name']} ({district['type']})")
        
        if dry_run:
            logger.info("")
            logger.info(f"ℹ️  Будет импортировано: {len(districts)} районов")
            return len(districts)
        
        # Импортируем в БД
        logger.info("")
        logger.info("💾 Импорт в базу данных...")
        
        imported = 0
        skipped = 0
        
        for district in districts:
            # Проверяем, существует ли уже
            existing = District.query.filter_by(
                city_id=city_id,
                name=district['name']
            ).first()
            
            if existing:
                logger.info(f"  ⏭️  Пропущен (уже существует): {district['name']}")
                skipped += 1
                continue
            
            # Создаём новый район
            slug = create_slug(district['name'])
            
            new_district = District(
                city_id=city_id,
                name=district['name'],
                slug=slug
            )
            
            db.session.add(new_district)
            logger.info(f"  ✅ Импортирован: {district['name']} (slug: {slug})")
            imported += 1
        
        db.session.commit()
        
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"✅ Импорт завершён!")
        logger.info(f"   • Импортировано: {imported}")
        logger.info(f"   • Пропущено (дубли): {skipped}")
        logger.info(f"   • Всего в БД для города: {District.query.filter_by(city_id=city_id).count()}")
        logger.info("=" * 60)
        
        return imported


def main():
    """Основная функция"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Импорт районов из DaData API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Импорт для Краснодара (с проверкой)
  python scripts/import_districts_from_dadata.py --city-name "Краснодар" --city-id 1 --dry-run
  
  # Импорт для Краснодара (реальный)
  python scripts/import_districts_from_dadata.py --city-name "Краснодар" --city-id 1
  
  # Импорт для всех городов
  python scripts/import_districts_from_dadata.py --all-cities
        """
    )
    
    parser.add_argument('--city-name', type=str, help='Название города (например: Краснодар)')
    parser.add_argument('--city-id', type=int, help='ID города в БД')
    parser.add_argument('--all-cities', action='store_true', help='Импорт для всех городов из БД')
    parser.add_argument('--dry-run', action='store_true', help='Тестовый запуск без сохранения')
    
    args = parser.parse_args()
    
    if not args.all_cities and (not args.city_name or not args.city_id):
        parser.error("Укажите --city-name и --city-id или используйте --all-cities")
    
    with app.app_context():
        try:
            importer = DaDataDistrictImporter()
            
            if args.all_cities:
                # Импорт для всех городов
                cities = City.query.filter_by(is_active=True).all()
                logger.info(f"🌍 Импорт для {len(cities)} городов")
                logger.info("")
                
                total_imported = 0
                for city in cities:
                    imported = importer.import_districts_to_db(
                        city.id,
                        city.name,
                        dry_run=args.dry_run
                    )
                    total_imported += imported
                    logger.info("")
                
                logger.info(f"🎉 Всего импортировано районов: {total_imported}")
            else:
                # Импорт для одного города
                importer.import_districts_to_db(
                    args.city_id,
                    args.city_name,
                    dry_run=args.dry_run
                )
        
        except ValueError as e:
            logger.error(str(e))
            return 1
        except Exception as e:
            logger.error(f"❌ Ошибка: {str(e)}", exc_info=True)
            db.session.rollback()
            return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
