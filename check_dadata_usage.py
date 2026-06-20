#!/usr/bin/env python3
"""
Скрипт мониторинга использования DaData API
Проверяет текущий план и оставшийся лимит запросов
"""

import os
import sys
import logging
from datetime import datetime
from services.dadata_client import get_dadata_client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_api_plan():
    """
    Проверяет текущий план DaData API
    
    FREE план: 10,000 запросов/день
    PRO план: больше лимиты
    """
    try:
        client = get_dadata_client()
        
        # Делаем тестовый запрос для получения информации о плане
        test_address = "Москва, Красная площадь, 1"
        result = client.suggest_address(test_address, count=1)
        
        # DaData возвращает план в заголовке X-Plan
        plan = client.last_response_plan if hasattr(client, 'last_response_plan') else 'FREE'
        
        logger.info("=" * 80)
        logger.info("📊 МОНИТОРИНГ DaData API")
        logger.info("=" * 80)
        logger.info(f"📅 Дата проверки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"🔑 API Key: {'✅ Настроен' if os.environ.get('DADATA_API_KEY') else '❌ Отсутствует'}")
        logger.info(f"🎯 План: {plan}")
        
        if plan == 'FREE':
            logger.info("📉 Лимит: 10,000 запросов/день")
            logger.warning("⚠️  FREE план имеет ограничения:")
            logger.warning("   - 10,000 запросов в день")
            logger.warning("   - Сброс лимита в 00:00 UTC+3 (Московское время)")
            logger.warning("   - Рекомендуется мониторить использование")
        elif plan == 'PRO':
            logger.info("✅ PRO план - расширенные лимиты")
        
        logger.info("=" * 80)
        logger.info("")
        
        # Рекомендации по использованию
        logger.info("💡 РЕКОМЕНДАЦИИ:")
        logger.info("   1. Используйте batch обогащение с разумным batch_size (20-50)")
        logger.info("   2. Включайте dry-run режим для тестирования перед реальными запросами")
        logger.info("   3. Используйте кэширование DaData (TTL: 3600s)")
        logger.info("   4. Избегайте обогащения неполных адресов (ЖК названия)")
        logger.info("")
        
        # Статистика из базы данных
        try:
            from app import app, db
            from models import Property
            
            with app.app_context():
                total_properties = Property.query.count()
                enriched_properties = Property.query.filter(
                    Property.parsed_area.isnot(None),
                    Property.parsed_settlement.isnot(None),
                    Property.parsed_house.isnot(None)
                ).count()
                
                logger.info("📊 СТАТИСТИКА БАЗЫ ДАННЫХ:")
                logger.info(f"   Всего объектов: {total_properties}")
                logger.info(f"   Полностью обогащено: {enriched_properties} ({enriched_properties/total_properties*100:.1f}%)")
                logger.info(f"   Требует обогащения: {total_properties - enriched_properties}")
                logger.info("")
                
        except Exception as e:
            logger.debug(f"Не удалось получить статистику БД: {e}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке API: {e}")
        logger.error("   Проверьте:")
        logger.error("   1. Наличие DADATA_API_KEY и DADATA_SECRET_KEY в .env")
        logger.error("   2. Корректность ключей")
        logger.error("   3. Подключение к интернету")
        return False


def estimate_enrichment_cost(num_properties: int = None):
    """
    Оценивает стоимость обогащения в запросах API
    
    Args:
        num_properties: Количество объектов для обогащения (None = все необогащенные)
    """
    try:
        from app import app, db
        from models import Property
        
        with app.app_context():
            if num_properties is None:
                # Подсчитываем необогащенные объекты
                num_properties = Property.query.filter(
                    Property.parsed_area.is_(None)
                ).count()
            
            logger.info("=" * 80)
            logger.info("💰 ОЦЕНКА СТОИМОСТИ ОБОГАЩЕНИЯ")
            logger.info("=" * 80)
            logger.info(f"📦 Объектов для обогащения: {num_properties}")
            logger.info(f"📡 Запросов к API: ~{num_properties} (1 запрос на объект)")
            
            # Расчет для FREE плана
            days_needed = (num_properties // 10000) + (1 if num_properties % 10000 > 0 else 0)
            
            if days_needed > 1:
                logger.warning(f"⏱️  Время выполнения: ~{days_needed} дней (FREE план: 10,000/день)")
                logger.warning(f"   Рекомендуется обрабатывать партиями по 10,000 объектов")
            else:
                logger.info(f"✅ Время выполнения: <1 дня (в пределах FREE лимита)")
            
            logger.info("=" * 80)
            logger.info("")
            
            # Команда для запуска
            logger.info("🚀 КОМАНДА ДЛЯ ЗАПУСКА:")
            if num_properties <= 10000:
                logger.info(f"   python backfill_address_fields.py --batch-size 20")
            else:
                logger.info(f"   python backfill_address_fields.py --batch-size 20 --limit 10000")
            logger.info("")
            logger.info("🧪 ТЕСТОВЫЙ ЗАПУСК (DRY-RUN):")
            logger.info(f"   python backfill_address_fields.py --batch-size 20 --limit 10 --dry-run")
            logger.info("")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при оценке стоимости: {e}")


def main():
    """Главная функция"""
    logger.info("🔍 Проверка состояния DaData API...")
    logger.info("")
    
    # Проверяем API план
    if not check_api_plan():
        sys.exit(1)
    
    # Оцениваем стоимость обогащения
    estimate_enrichment_cost()
    
    logger.info("✅ Проверка завершена!")
    logger.info("")


if __name__ == '__main__':
    main()
