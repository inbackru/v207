#!/usr/bin/env python3
"""
Показывает сводку по всем городам: ЖК, квартиры, последнее обновление, кэш.

Запуск: python3 scripts/city_status.py
"""
import os, sys, json, glob
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2

_DIR = os.path.dirname(os.path.abspath(__file__))


def load_city_config() -> dict:
    path = os.path.join(_DIR, 'city_config.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def cache_info(city_id: int) -> str:
    # Per-city файл — приоритет; старый общий файл — только для города 1 (обратная совместимость)
    candidates = [f'.enrich_cache_city{city_id}.json']
    if city_id == 1:
        candidates.append('.enrich_cache.json')
    for fname in candidates:
        p = os.path.join(_DIR, fname)
        if os.path.exists(p):
            size_kb = os.path.getsize(p) // 1024
            mtime   = datetime.fromtimestamp(os.path.getmtime(p))
            try:
                c     = json.load(open(p))
                phase = c.get('phase', '?')
                apts  = len(c.get('apt_data', {}))
                jks   = len(c.get('jk_search_data', {}))
                return (f'{fname} | phase={phase} | '
                        f'{jks} ЖК / {apts} кв | '
                        f'{size_kb} KB | '
                        f'{mtime.strftime("%d.%m %H:%M")}')
            except Exception:
                return f'{fname} | {size_kb} KB | {mtime.strftime("%d.%m %H:%M")}'
    return '—  (кэша нет)'


def main():
    configs = load_city_config()

    try:
        conn = psycopg2.connect(
            host=os.environ.get('PGHOST', 'helium'),
            database=os.environ.get('PGDATABASE', 'heliumdb'),
            user=os.environ.get('PGUSER', 'postgres'),
            password=os.environ.get('PGPASSWORD', ''),
        )
        cur = conn.cursor()
        # Узнаём какие city_id вообще есть в БД
        cur.execute("SELECT city_id, COUNT(*) FROM residential_complexes GROUP BY city_id")
        rc_counts = dict(cur.fetchall())

        cur.execute("SELECT city_id, COUNT(*) FROM properties WHERE is_active=TRUE GROUP BY city_id")
        prop_active = dict(cur.fetchall())

        cur.execute("SELECT city_id, COUNT(*) FROM properties WHERE is_active=FALSE GROUP BY city_id")
        prop_sold = dict(cur.fetchall())

        cur.execute("""
            SELECT city_id, MAX(updated_at)
            FROM properties GROUP BY city_id
        """)
        prop_updated = {r[0]: r[1] for r in cur.fetchall()}

        cur.execute("""
            SELECT city_id, MAX(updated_at)
            FROM residential_complexes GROUP BY city_id
        """)
        rc_updated = {r[0]: r[1] for r in cur.fetchall()}

        cur.execute("SELECT id, name FROM cities ORDER BY id")
        db_cities = {r[0]: r[1] for r in cur.fetchall()}

        conn.close()
        db_ok = True
    except Exception as e:
        print(f'⚠️  Не удалось подключиться к БД: {e}')
        rc_counts = prop_active = prop_sold = prop_updated = rc_updated = db_cities = {}
        db_ok = False

    print()
    print('╔══════════════════════════════════════════════════════════════════╗')
    print('║            СТАТУС ПАРСЕРА ПО ГОРОДАМ                            ║')
    print('╠══╦═══════════════════╦════════╦════════╦════════╦═══════════════╣')
    print('║ # ║ Город             ║   ЖК   ║  Акт   ║ Прод  ║  Обновлено   ║')
    print('╠══╬═══════════════════╬════════╬════════╬════════╬═══════════════╣')

    for cid_str, cfg in sorted(configs.items(), key=lambda x: int(x[0])):
        cid  = int(cid_str)
        name = db_cities.get(cid, cfg['name'])
        jks  = rc_counts.get(cid, 0)
        act  = prop_active.get(cid, 0)
        sld  = prop_sold.get(cid, 0)
        upd  = prop_updated.get(cid) or rc_updated.get(cid)
        upd_s = upd.strftime('%d.%m %H:%M') if upd else '—'
        mark = '✓' if jks > 0 else ' '
        print(f'║{mark}{cid} ║ {name:<17} ║ {jks:>6} ║ {act:>6} ║ {sld:>6} ║ {upd_s:<13} ║')

    print('╚══╩═══════════════════╩════════╩════════╩════════╩═══════════════╝')
    print()

    # Кэш-файлы
    print('── Кэш-файлы ──────────────────────────────────────────────────────')
    for cid_str, cfg in sorted(configs.items(), key=lambda x: int(x[0])):
        cid = int(cid_str)
        info = cache_info(cid)
        if '—' not in info:
            print(f'  [{cid}] {info}')

    # Какие воркфлоу для какого города
    print()
    print('── Команды запуска ────────────────────────────────────────────────')
    for cid_str, cfg in sorted(configs.items(), key=lambda x: int(x[0])):
        cid  = int(cid_str)
        name = cfg['name']
        jks  = rc_counts.get(cid, 0)
        status = '(есть данные)' if jks > 0 else '(нет данных — нужен полный прогон)'
        print(f'  [{cid}] {name:<15} python3 scripts/run_city.py --city {cid} --mode prices   {status}')
    print()


if __name__ == '__main__':
    main()
