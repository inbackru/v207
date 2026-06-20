#!/usr/bin/env python3
"""
BACKGROUND JOB: Автоматическое определение проданных объектов

Запускается по расписанию (cron/scheduler) для проверки объектов,
которые исчезли из источников данных.

Использование:
    # Запуск вручную
    python scripts/auto_detect_sold_cron.py
    
    # Настройка cron (каждый день в 3:00)
    0 3 * * * cd /path/to/project && python scripts/auto_detect_sold_cron.py >> logs/sold_detection.log 2>&1

Как работает:
1. Проверяет все объекты с external_id
2. Находит объекты которые давно не обновлялись (cutoff_hours)
3. Помечает их как проданные (is_active=False)
4. Отправляет уведомления пользователям
"""

import sys
import os
from datetime import datetime, timedelta
import logging

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from services.property_sync_service import PropertySyncService

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_sold_detection(cutoff_hours: int = 24, source_name: str = None, notify_users: bool = True):
    """
    Запустить автоматическое определение проданных объектов.
    
    Args:
        cutoff_hours: Часов с последнего обновления (объекты старше считаются проданными)
        source_name: Фильтр по источнику данных (опционально)
        notify_users: Отправлять уведомления пользователям
    """
    logger.info(f"🚀 Запуск автоматического определения проданных объектов")
    logger.info(f"⏱️  Cutoff: {cutoff_hours} часов")
    
    try:
        # Вычисляем время отсечки
        cutoff_time = datetime.utcnow() - timedelta(hours=cutoff_hours)
        logger.info(f"📅 Cutoff time: {cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Запускаем определение проданных
        sync_service = PropertySyncService()
        stats = sync_service.detect_sold_properties(
            cutoff_time=cutoff_time,
            source_name=source_name,
            notify_users=notify_users
        )
        
        # Выводим статистику
        logger.info(f"\n{'='*60}")
        logger.info(f"📊 РЕЗУЛЬТАТЫ ПРОВЕРКИ")
        logger.info(f"{'='*60}")
        logger.info(f"✅ Проверено объектов: {stats['total_checked']}")
        logger.info(f"🏷️  Помечено как проданные: {stats['newly_sold']}")
        logger.info(f"👥 Пользователей уведомлено: {stats['users_notified']}")
        logger.info(f"📧 Уведомлений отправлено: {stats['notifications_sent']}")
        logger.info(f"{'='*60}\n")
        
        # Получаем общую статистику
        overall_stats = sync_service.get_sync_statistics(days=7)
        logger.info(f"📈 ОБЩАЯ СТАТИСТИКА (последние 7 дней):")
        logger.info(f"  • Всего объектов: {overall_stats['total_properties']}")
        logger.info(f"  • Активных: {overall_stats['active_properties']}")
        logger.info(f"  • Проданных: {overall_stats['sold_properties']}")
        logger.info(f"  • Недавно обновленных: {overall_stats['recently_updated']}")
        logger.info(f"  • Недавно проданных: {overall_stats['recently_sold']}")
        logger.info(f"  • С external_id: {overall_stats['with_external_id']}")
        
        if stats['newly_sold'] > 0:
            logger.warning(f"⚠️  ВНИМАНИЕ: {stats['newly_sold']} объектов были помечены как проданные!")
        else:
            logger.info(f"✅ Все объекты актуальны, проданных не обнаружено")
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Автоматическое определение проданных объектов")
    parser.add_argument(
        '--cutoff-hours',
        type=int,
        default=24,
        help='Часов с последнего обновления для пометки как проданный (по умолчанию 24)'
    )
    parser.add_argument(
        '--source',
        help='Фильтр по источнику данных (например: parser, api, excel)'
    )
    parser.add_argument(
        '--no-notify',
        action='store_true',
        help='Не отправлять уведомления пользователям (только пометить как проданные)'
    )
    
    args = parser.parse_args()
    
    with app.app_context():
        try:
            stats = run_sold_detection(
                cutoff_hours=args.cutoff_hours,
                source_name=args.source,
                notify_users=not args.no_notify
            )
            
            # Возвращаем код выхода 0 если все ок, 1 если были проданные объекты
            exit_code = 0 if stats['newly_sold'] == 0 else 1
            sys.exit(exit_code)
            
        except Exception as e:
            logger.error(f"❌ Ошибка выполнения: {e}")
            sys.exit(2)
