#!/usr/bin/env python3
"""
Скачивает логотипы CIAN для всех застройщиков в БД.
Использует SESSION, прокси и анти-капчу из enrich_complexes.py.
Обновляет logo_url в developers на локальный путь.
"""
import os
import sys
import time
import psycopg2

sys.path.insert(0, os.path.dirname(__file__))

print('Загружаем SESSION и анти-капчу из enrich_complexes...')
from enrich_complexes import (
    SESSION,
    ANTICAPTCHA_KEY,
    LOGO_SAVE_DIR,
    _download_logo,
)

print(f'Прокси: {"✅" if SESSION.proxies else "❌ не настроен"}')
print(f'Анти-капча: {"✅ ключ установлен (" + ANTICAPTCHA_KEY[:6] + "...)" if ANTICAPTCHA_KEY else "❌ не настроена"}')


def main():
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, logo_url, external_id
        FROM developers
        WHERE logo_url IS NULL OR logo_url = '' OR logo_url LIKE '/api/cian-logo/%'
        ORDER BY id
    """)
    rows = cur.fetchall()
    print(f'\nЗастройщиков для обработки: {len(rows)}\n')

    updated = 0
    failed = 0

    for dev_id, dev_name, logo_url, external_id in rows:
        company_id = None
        if logo_url and '/api/cian-logo/' in (logo_url or ''):
            company_id = logo_url.split('/api/cian-logo/')[-1].strip()
        elif external_id:
            company_id = str(external_id)

        if not company_id:
            print(f'  — {dev_name[:40]:40} нет company_id, пропуск')
            continue

        local_url = _download_logo(company_id)
        if local_url:
            cur.execute('UPDATE developers SET logo_url=%s WHERE id=%s', (local_url, dev_id))
            conn.commit()
            print(f'  ✅ {dev_name[:40]:40} → {local_url}')
            updated += 1
        else:
            print(f'  — {dev_name[:40]:40} нет логотипа в CIAN')
            failed += 1

        time.sleep(0.3)

    conn.close()
    print(f'\nГотово: {updated} обновлено, {failed} без логотипа')


if __name__ == '__main__':
    main()
