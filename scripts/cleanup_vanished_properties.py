"""
Cleanup Vanished Properties
Находит объекты которые исчезли с ЦИАН и помечает их как неактивные/проданные.

Логика (два прохода):

Проход 1 (частичная пропажа внутри ЖК):
- Берём все активные объекты с inner_id, группируем по ЖК
- Если в ЖК есть хотя бы 1 свежий объект (updated < N дней) — значит ЦИАН работает
- Устаревшие внутри этого ЖК → деактивируем

Проход 2 (весь ЖК пропал с ЦИАН):
- Если весь ЖК не обновлялся >stale_days*4 (т.е. несколько прогонов) — ЖК покинул ЦИАН
- Все его объекты деактивируем

Объекты без inner_id — НЕ трогаем (добавлены вручную).

Запуск:
    python scripts/cleanup_vanished_properties.py [--city 1] [--dry-run] [--days 7]
    python scripts/cleanup_vanished_properties.py --all-cities --days 7
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--city', type=int, default=1, help='City ID (default: 1 = Краснодар)')
    p.add_argument('--dry-run', action='store_true', help='Не менять БД, только показать что будет')
    p.add_argument('--days', type=int, default=7, help='Объект исчез если не обновлялся N дней (default: 7)')
    p.add_argument('--all-cities', action='store_true', help='Обработать все города')
    return p.parse_args()


def cleanup_city(city_id: int, dry_run: bool, stale_days: int):
    """Cleanup vanished properties for a specific city."""
    from app import app, db
    from models import Property, ResidentialComplex

    cutoff_date = datetime.utcnow() - timedelta(days=stale_days)
    # Второй порог: если весь ЖК не обновлялся 4× дольше — считаем что покинул ЦИАН
    hard_cutoff = datetime.utcnow() - timedelta(days=stale_days * 4)

    with app.app_context():
        stale_props = Property.query.filter(
            Property.city_id == city_id,
            Property.is_active == True,
            Property.inner_id.isnot(None),
            Property.inner_id != '',
        ).all()

        if not stale_props:
            logger.info(f'Город {city_id}: нет активных объектов с inner_id')
            return

        logger.info(f'Город {city_id}: найдено {len(stale_props)} активных объектов с inner_id')

        by_complex = {}
        for p in stale_props:
            cid = p.complex_id
            if cid not in by_complex:
                by_complex[cid] = []
            by_complex[cid].append(p)

        logger.info(f'Город {city_id}: {len(by_complex)} ЖК с активными объектами')

        total_deactivated = 0
        complexes_with_fresh = 0
        complexes_gone = 0

        for complex_id, props in by_complex.items():
            if complex_id is None:
                continue

            fresh_props = [p for p in props
                           if (p.updated_at or p.created_at or datetime(2020, 1, 1)) >= cutoff_date]
            stale_here = [p for p in props
                          if (p.updated_at or p.created_at or datetime(2020, 1, 1)) < cutoff_date]

            if not fresh_props:
                # ЖК полностью не обновлялся — проверяем "жёсткий" порог
                latest = max(
                    (p.updated_at or p.created_at or datetime(2020, 1, 1))
                    for p in props
                )
                if latest >= hard_cutoff:
                    # Слишком свежо — пропускаем (возможно парсер временно пропустил ЖК)
                    continue
                # ЖК не обновлялся дольше stale_days*4 — всё ЖК покинуло ЦИАН
                complex_obj = ResidentialComplex.query.get(complex_id)
                complex_name = complex_obj.name if complex_obj else f'ЖК #{complex_id}'
                days_gone = (datetime.utcnow() - latest).days
                logger.info(f'  ЖК "{complex_name}" (ID={complex_id}): '
                            f'покинул ЦИАН {days_gone} дней назад — '
                            f'деактивируем {len(props)} объектов')
                complexes_gone += 1
                for p in props:
                    if not dry_run:
                        p.is_active = False
                        p.status = 'sold'
                        total_deactivated += 1
                continue

            complexes_with_fresh += 1

            if not stale_here:
                continue

            complex_obj = ResidentialComplex.query.get(complex_id)
            complex_name = complex_obj.name if complex_obj else f'ЖК #{complex_id}'

            logger.info(f'  ЖК "{complex_name}" (ID={complex_id}): '
                        f'{len(fresh_props)} свежих, {len(stale_here)} устаревших')

            for p in stale_here:
                last_seen = p.updated_at or p.created_at
                days_since = (datetime.utcnow() - last_seen).days if last_seen else 9999
                logger.info(f'    → [{p.inner_id}] {p.title or "?"} '
                            f'этаж {p.floor}, {p.area}м² — не обновлялся {days_since} дней')
                if not dry_run:
                    p.is_active = False
                    p.status = 'sold'
                    total_deactivated += 1

        if not dry_run and total_deactivated > 0:
            db.session.commit()
            logger.info(f'✅ Город {city_id}: деактивировано {total_deactivated} объектов '
                        f'(ЖК с частичной пропажей: {complexes_with_fresh}, '
                        f'ЖК покинули ЦИАН: {complexes_gone})')
        elif dry_run:
            logger.info(f'🔍 DRY RUN — Город {city_id}: '
                        f'было бы деактивировано {total_deactivated} объектов '
                        f'(ЖК с обновлением: {complexes_with_fresh}, '
                        f'ЖК покинули ЦИАН: {complexes_gone})')
        else:
            logger.info(f'✅ Город {city_id}: пропавших объектов не найдено')


def print_stats(city_id: int):
    """Print current stats for a city."""
    from app import app, db
    from models import Property

    with app.app_context():
        total = Property.query.filter_by(city_id=city_id).count()
        active = Property.query.filter_by(city_id=city_id, is_active=True).count()
        inactive = Property.query.filter_by(city_id=city_id, is_active=False).count()
        sold = Property.query.filter_by(city_id=city_id, status='sold').count()
        with_inner_id = Property.query.filter(
            Property.city_id == city_id,
            Property.inner_id.isnot(None),
            Property.is_active == True
        ).count()

        logger.info(f'\nСтатистика по городу {city_id}:')
        logger.info(f'  Всего объектов: {total}')
        logger.info(f'  Активных: {active}')
        logger.info(f'  С inner_id (актив): {with_inner_id}')
        logger.info(f'  Неактивных: {inactive}')
        logger.info(f'  Статус "продано": {sold}')


def main():
    args = parse_args()

    logger.info('=' * 60)
    logger.info('Cleanup Vanished Properties')
    logger.info(f'Dry run: {args.dry_run}')
    logger.info(f'Порог устаревания: {args.days} дней')
    logger.info(f'Жёсткий порог (весь ЖК пропал): {args.days * 4} дней')
    logger.info('=' * 60)

    from app import app, db
    from models import City

    with app.app_context():
        if args.all_cities:
            cities = City.query.filter_by(is_active=True).all()
            city_ids = [c.id for c in cities]
            logger.info(f'Режим "все города": {[c.name for c in cities]}')
        else:
            city_ids = [args.city]

    for city_id in city_ids:
        try:
            print_stats(city_id)
            cleanup_city(city_id, args.dry_run, args.days)
        except Exception as e:
            logger.error(f'Ошибка для города {city_id}: {e}', exc_info=True)

    logger.info('\n✅ Готово!')


if __name__ == '__main__':
    main()
