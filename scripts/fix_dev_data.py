#!/usr/bin/env python3
"""
Повторно скрапит страницы застройщиков у которых в БД нет
founded_year / completed_projects / under_construction.
Использует SESSION с прокси + анти-капча из enrich_complexes.py.
"""
import os, sys, time, psycopg2

sys.path.insert(0, os.path.dirname(__file__))
print('Загружаем SESSION из enrich_complexes...')
from enrich_complexes import (
    SESSION, ANTICAPTCHA_KEY, scrape_developer_page, update_developer_db, _download_logo
)
print(f'Прокси: {"✅" if SESSION.proxies else "❌"}  Анти-капча: {"✅ " + ANTICAPTCHA_KEY[:6] if ANTICAPTCHA_KEY else "❌"}')

def main():
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur  = conn.cursor()

    # Застройщики у которых есть source_url но нет хотя бы одного из полей
    cur.execute("""
        SELECT id, name, source_url, external_id,
               founded_year, completed_projects, under_construction
        FROM developers
        WHERE source_url IS NOT NULL AND source_url != ''
          AND (founded_year IS NULL
               OR completed_projects IS NULL OR completed_projects = 0
               OR under_construction  IS NULL OR under_construction  = 0)
        ORDER BY id
    """)
    rows = cur.fetchall()
    print(f'\nЗастройщиков для дозаполнения: {len(rows)}\n')

    ok = skip = 0
    for dev_id, name, source_url, ext_id, fy, cp, uc in rows:
        print(f'  → {name[:45]:45}', end=' ', flush=True)
        pdata = scrape_developer_page(source_url)
        if not pdata:
            print('❌ пустой ответ')
            skip += 1
            time.sleep(1)
            continue

        # Качаем логотип если его нет
        if not pdata.get('logo_url') and ext_id:
            local = _download_logo(str(ext_id))
            if local:
                pdata['logo_url'] = local

        update_developer_db(cur, dev_id, {}, pdata, ext_id)
        conn.commit()

        got = []
        if pdata.get('founded_year'):     got.append(f'год={pdata["founded_year"]}')
        if pdata.get('completed_projects'):got.append(f'сдано={pdata["completed_projects"]}')
        if pdata.get('under_construction'):got.append(f'строится={pdata["under_construction"]}')
        if pdata.get('logo_url'):          got.append('лого')
        print('✅ ' + (', '.join(got) if got else 'обновлено'))
        ok += 1
        time.sleep(0.5)

    conn.close()
    print(f'\nГотово: {ok} обновлено, {skip} пропущено')

if __name__ == '__main__':
    main()
