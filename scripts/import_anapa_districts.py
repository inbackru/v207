#!/usr/bin/env python3
"""
Импорт полного справочника районов и микрорайонов Анапы.

Использование:
    python scripts/import_anapa_districts.py
    
    # С проверкой (не сохраняет)
    python scripts/import_anapa_districts.py --dry-run
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import District
import logging
from utils.transliteration import create_slug

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Полный справочник районов и микрорайонов Анапы
ANAPA_DISTRICTS = [
    # ======================
    # АДМИНИСТРАТИВНЫЕ ОКРУГА
    # ======================
    "Анапский",
    
    # ======================
    # МИКРОРАЙОНЫ ГОРОДА
    # ======================
    "Центральный",
    "12-й",
    "Высокий берег",
    "Ореховая роща",
    "Южный рынок",
    "Алексеевка",
    "Горгиппия",
    "3-й",
    "3-А",
    "4-й",
    "5-й",
    "Пионерский проспект",
    "Супсех",
    
    # ======================
    # ПОСЕЛКИ И НАСЕЛЕННЫЕ ПУНКТЫ
    # ======================
    "Джемете",
    "Витязево",
    "Благовещенская",
    "Сукко",
    "Большой Утриш",
    "Малый Утриш",
    "Варваровка",
    "Гай-Кодзор",
    "Анапская",
    "Виноградный",
    "Цибанобалка",
    "Уташ",
    
    # ======================
    # УЛИЦЫ И РАЙОНЫ
    # ======================
    "ул. Крымская",
    "ул. Астраханская",
    "ул. Горького",
    "Набережная",
]


def import_anapa_districts(dry_run=False):
    """
    Импортирует районы Анапы в таблицу districts.
    
    Args:
        dry_run: Если True, только показывает что будет импортировано
    """
    logger.info("=" * 60)
    logger.info(f"🏙️  Импорт районов для города: Анапа")
    if dry_run:
        logger.info("⚠️  РЕЖИМ ПРОВЕРКИ (dry-run) - изменения НЕ сохраняются")
    logger.info("=" * 60)
    logger.info("")
    
    with app.app_context():
        # Динамически получаем город по имени (не хардкодим ID!)
        from models import City
        city = City.query.filter_by(name='Анапа').first()
        if not city:
            logger.error(f"❌ Город 'Анапа' не найден в БД!")
            return 0
        
        city_id = city.id
        logger.info(f"✅ Город найден: {city.name} (ID={city_id})")
        logger.info("")
        logger.info(f"📋 Найдено районов для импорта: {len(ANAPA_DISTRICTS)}")
        logger.info("")
        
        if dry_run:
            logger.info("Будут импортированы следующие районы:")
            for idx, name in enumerate(ANAPA_DISTRICTS, 1):
                slug = create_slug(name)
                logger.info(f"  {idx}. {name} (slug: {slug})")
            logger.info("")
            logger.info(f"ℹ️  Всего будет добавлено: {len(ANAPA_DISTRICTS)} районов")
            return len(ANAPA_DISTRICTS)
        
        # Импортируем в БД
        logger.info("💾 Импорт в базу данных...")
        logger.info("")
        
        imported = 0
        skipped = 0
        
        for name in ANAPA_DISTRICTS:
            # Проверяем, существует ли уже
            existing = District.query.filter_by(
                city_id=city_id,
                name=name
            ).first()
            
            if existing:
                logger.info(f"  ⏭️  Пропущен (уже существует): {name}")
                skipped += 1
                continue
            
            # Создаём новый район
            slug = create_slug(name)
            
            new_district = District(
                city_id=city_id,
                name=name,
                slug=slug
            )
            
            db.session.add(new_district)
            logger.info(f"  ✅ Импортирован: {name} (slug: {slug})")
            imported += 1
        
        db.session.commit()
        
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"✅ Импорт завершён!")
        logger.info(f"   • Импортировано: {imported}")
        logger.info(f"   • Пропущено (дубли): {skipped}")
        logger.info(f"   • Всего в БД для Анапы: {District.query.filter_by(city_id=city_id).count()}")
        logger.info("=" * 60)
        
        return imported


def main():
    """Основная функция"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Импорт полного справочника районов Анапы',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Проверка (без сохранения)
  python scripts/import_anapa_districts.py --dry-run
  
  # Реальный импорт
  python scripts/import_anapa_districts.py
        """
    )
    
    parser.add_argument('--dry-run', action='store_true', help='Только показать что будет импортировано (не сохранять)')
    
    args = parser.parse_args()
    
    try:
        count = import_anapa_districts(dry_run=args.dry_run)
        
        if args.dry_run:
            logger.info("")
            logger.info(f"💡 Для реального импорта запустите без --dry-run:")
            logger.info(f"   python scripts/import_anapa_districts.py")
        
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
