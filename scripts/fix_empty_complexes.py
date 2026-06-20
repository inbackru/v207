"""
Обновление ЖК без фото и/или описания.
Использование:
  python scripts/fix_empty_complexes.py [mode]

Режимы (mode):
  no_photo_no_desc  — только ЖК у которых НЕТ ни фото, ни описания (default)
  no_photo          — ЖК без фото (даже если есть описание)
  no_desc           — ЖК без описания
  all_empty         — и без фото, и без описания (отдельно)

Для каждого такого ЖК берёт его cian_url и запускает parse_jk_by_url.py,
сохраняя прогресс в .enrich_log.txt
"""

import sys, os, json, time
import psycopg2
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRIPTS_DIR  = os.path.dirname(os.path.abspath(__file__))
STOP_FLAG    = os.path.join(SCRIPTS_DIR, '.enrich_stop')
PARSE_SCRIPT = os.path.join(SCRIPTS_DIR, 'parse_jk_by_url.py')

REQUEST_DELAY = float(os.environ.get('ENRICH_DELAY', 1.0))
CITY_ID       = os.environ.get('ENRICH_CITY_ID', '1')

DB_PARAMS = dict(
    host=os.environ.get('PGHOST', 'helium'),
    database=os.environ.get('PGDATABASE', 'heliumdb'),
    user=os.environ.get('PGUSER', 'postgres'),
    password=os.environ.get('PGPASSWORD', 'password'),
)


def _check_stop() -> bool:
    if os.path.exists(STOP_FLAG):
        try:
            os.remove(STOP_FLAG)
        except Exception:
            pass
        print('\n🛑 Получен сигнал остановки.')
        return True
    return False


def get_empty_complexes(mode: str) -> list[dict]:
    """Возвращает список ЖК из БД у которых не хватает данных."""
    conn = psycopg2.connect(**DB_PARAMS)
    cur = conn.cursor()

    if mode == 'no_photo':
        condition = "(rc.photos IS NULL OR rc.photos = '[]' OR rc.photos = '')"
    elif mode == 'no_desc':
        condition = "(rc.description IS NULL OR rc.description = '')"
    else:
        condition = (
            "(rc.photos IS NULL OR rc.photos = '[]' OR rc.photos = '') "
            "AND (rc.description IS NULL OR rc.description = '')"
        )

    cur.execute(f"""
        SELECT rc.id, rc.name, rc.cian_url, c.id as city_id
        FROM residential_complexes rc
        JOIN cities c ON c.id = rc.city_id
        WHERE rc.is_active = TRUE
          AND rc.cian_url IS NOT NULL
          AND rc.cian_url != ''
          AND {condition}
        ORDER BY rc.id
    """)
    rows = cur.fetchall()
    conn.close()
    return [
        {'id': r[0], 'name': r[1], 'cian_url': r[2], 'city_id': r[3]}
        for r in rows
    ]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'no_photo_no_desc'
    valid_modes = {'no_photo_no_desc', 'no_photo', 'no_desc'}
    if mode not in valid_modes:
        mode = 'no_photo_no_desc'

    mode_labels = {
        'no_photo_no_desc': 'без фото и описания',
        'no_photo':         'без фото',
        'no_desc':          'без описания',
    }
    print(f'🔍 Режим: {mode_labels.get(mode, mode)}')

    complexes = get_empty_complexes(mode)
    total = len(complexes)
    print(f'📋 Найдено ЖК для обновления: {total}')

    if not complexes:
        print('✅ Нет ЖК требующих обновления')
        return

    ok = 0
    fail = 0

    for i, jk in enumerate(complexes, 1):
        if _check_stop():
            break

        name     = jk['name']
        cian_url = jk['cian_url']
        city_id  = str(jk['city_id'])

        print(f'\n[{i}/{total}] {name}')
        print(f'  URL: {cian_url}')

        try:
            proc = subprocess.run(
                [sys.executable, PARSE_SCRIPT, cian_url, city_id],
                timeout=180,
                env={**os.environ, 'ENRICH_CITY_ID': city_id},
            )
            if proc.returncode == 0:
                print(f'  ✅ Готово')
                ok += 1
            else:
                print(f'  ⚠️  Завершился с кодом {proc.returncode}')
                fail += 1
        except subprocess.TimeoutExpired:
            print(f'  ⏱️  Таймаут 3 мин — пропущен')
            fail += 1
        except Exception as e:
            print(f'  ❌ Ошибка: {e}')
            fail += 1

        time.sleep(REQUEST_DELAY)

    print(f'\n{"="*50}')
    print(f'✅ Обновлено: {ok}')
    print(f'❌ С ошибками: {fail}')
    print(f'{"="*50}')


if __name__ == '__main__':
    main()
