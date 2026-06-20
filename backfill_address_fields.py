#!/usr/bin/env python3
"""
Скрипт для backfill детальных адресных полей существующих недвижимостей
Использует DaData API для обогащения parsed_area, parsed_settlement, parsed_house, parsed_block
"""

import os
import sys
import logging
from app import app, db
from models import Property
from services.auto_geocoding import get_auto_geocoding_service

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def backfill_address_fields(batch_size=50, limit=None, dry_run=False):
    """
    Обновить детальные адресные поля для всех существующих недвижимостей
    
    Args:
        batch_size: Размер пакета для коммита в БД
        limit: Максимальное количество объектов для обработки (None = все)
        dry_run: Если True, не сохранять изменения в БД
    """
    with app.app_context():
        # Получаем сервис автообогащения
        auto_service = get_auto_geocoding_service()
        auto_service.enable_batch_mode()  # Отключаем event listeners
        
        logger.info("=" * 80)
        logger.info("🚀 BACKFILL ДЕТАЛЬНЫХ АДРЕСНЫХ ПОЛЕЙ")
        logger.info("=" * 80)
        
        # Находим недвижимости которые нужно обогатить
        # Критерий: есть address, но нет parsed_area (новое поле)
        query = Property.query.filter(
            Property.address.isnot(None),
            Property.address != '',
            Property.parsed_area.is_(None)  # Новое поле пустое
        )
        
        if limit:
            query = query.limit(limit)
        
        properties = query.all()
        total = len(properties)
        
        if total == 0:
            logger.info("✅ Нет недвижимостей для обогащения. Все уже обработаны!")
            return
        
        logger.info(f"📍 Найдено {total} недвижимостей для обогащения")
        logger.info(f"📦 Размер пакета: {batch_size}")
        logger.info(f"🔑 DaData API лимит: 10,000 запросов/день")
        logger.info("-" * 80)
        
        # Используем метод enrich_batch из AutoGeocodingService
        stats = auto_service.enrich_batch(properties, batch_size=batch_size, dry_run=dry_run)
        
        # Восстанавливаем автоматическое обогащение
        auto_service.disable_batch_mode()
        
        logger.info("=" * 80)
        logger.info("✅ BACKFILL ЗАВЕРШЁН")
        logger.info(f"   Обработано: {stats['total']}")
        logger.info(f"   Успешно обогащено: {stats['enriched']}")
        logger.info(f"   Ошибок: {stats['errors']}")
        logger.info(f"   Пропущено: {stats['skipped']}")
        logger.info("=" * 80)
        
        return stats


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Backfill детальных адресных полей')
    parser.add_argument('--batch-size', type=int, default=50, help='Размер пакета для коммита (default: 50)')
    parser.add_argument('--limit', type=int, default=None, help='Максимальное количество для обработки (default: все)')
    parser.add_argument('--dry-run', action='store_true', help='Тестовый запуск без сохранения в БД')
    
    args = parser.parse_args()
    
    if args.dry_run:
        logger.warning("⚠️  DRY RUN MODE - изменения НЕ будут сохранены в БД")
    
    logger.info(f"Запуск backfill с параметрами:")
    logger.info(f"  - Batch size: {args.batch_size}")
    logger.info(f"  - Limit: {args.limit or 'все'}")
    logger.info(f"  - Dry run: {args.dry_run}")
    logger.info("")
    
    try:
        stats = backfill_address_fields(
            batch_size=args.batch_size,
            limit=args.limit,
            dry_run=args.dry_run
        )
        
        logger.info("\n✅ Скрипт выполнен успешно!")
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"\n❌ Ошибка выполнения скрипта: {e}", exc_info=True)
        sys.exit(1)
