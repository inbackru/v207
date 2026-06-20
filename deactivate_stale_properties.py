#!/usr/bin/env python3
"""
Деактивация устаревших объявлений.

Логика: помечает is_active=False для объявлений, которые:
  — не имеют inner_id (не связаны с ЦИАН-выгрузкой)
  — не связаны с АКТИВНЫМ жилым комплексом (ЖК застройщика могут продаваться годами)
  — не обновлялись более N дней (по умолчанию 60)

Таким образом объявления от застройщиков, привязанные к жилому комплексу,
НЕ деактивируются — лот у застройщика может продаваться годами.

Запуск:
  python deactivate_stale_properties.py [--days 60] [--dry-run]
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor


def get_db_conn():
    url = os.environ.get('DATABASE_URL')
    if not url:
        sys.exit('DATABASE_URL not set')
    return psycopg2.connect(url)


def deactivate_stale(days: int = 60, dry_run: bool = False):
    cutoff = datetime.utcnow() - timedelta(days=days)
    conn = get_db_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Кандидаты: активные, без inner_id, не обновлявшиеся N дней
            # И при этом НЕ привязаны к активному жилому комплексу.
            # Если объект привязан к активному ЖК — это лот застройщика,
            # он может продаваться годами, деактивировать нельзя.
            cur.execute("""
                SELECT p.id, p.title, p.updated_at, p.complex_id
                FROM properties p
                WHERE p.is_active = TRUE
                  AND (p.inner_id IS NULL OR p.inner_id = '')
                  AND p.updated_at < %s
                  AND (
                    p.complex_id IS NULL
                    OR NOT EXISTS (
                        SELECT 1 FROM residential_complexes rc
                        WHERE rc.id = p.complex_id
                          AND rc.is_active = TRUE
                    )
                  )
                ORDER BY p.updated_at ASC
            """, (cutoff,))
            candidates = cur.fetchall()

            print(f"[{datetime.utcnow():%Y-%m-%d %H:%M:%S}] Найдено устаревших объявлений: {len(candidates)}")
            print(f"  Порог: обновлены до {cutoff:%Y-%m-%d} (>{days} дней назад)")
            print(f"  (объекты, привязанные к активному ЖК, не затронуты)")

            if not candidates:
                print("  Нечего деактивировать.")
                return 0

            for row in candidates[:10]:
                print(f"  id={row['id']}  updated_at={row['updated_at']}  complex_id={row['complex_id']}  title={row['title']!r}")
            if len(candidates) > 10:
                print(f"  ... и ещё {len(candidates) - 10} объявлений")

            if dry_run:
                print("[DRY-RUN] Изменения НЕ применены.")
                return len(candidates)

            ids = [row['id'] for row in candidates]
            cur.execute("""
                UPDATE properties
                SET is_active = FALSE, updated_at = NOW()
                WHERE id = ANY(%s)
            """, (ids,))
            conn.commit()
            print(f"  ✓ Деактивировано {len(ids)} объявлений.")
            return len(ids)

    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Деактивация устаревших объявлений')
    parser.add_argument('--days', type=int, default=60,
                        help='Порог в днях (default: 60)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Не вносить изменения, только показать')
    args = parser.parse_args()
    n = deactivate_stale(days=args.days, dry_run=args.dry_run)
    sys.exit(0)
