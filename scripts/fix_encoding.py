"""
Исправляет кодировку описаний ЖК и застройщиков в БД.
Проблема: текст был сохранён с неправильной кодировкой (Latin-1 вместо UTF-8).
Решение: encode('latin-1').decode('utf-8')
"""

import os, sys, re
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def try_fix_encoding(text: str) -> str:
    """
    Пытается исправить mojibake: Latin-1 → UTF-8.
    Если строка уже валидная — возвращает как есть.
    """
    if not text:
        return text

    # Если нет символов-признаков mojibake — текст уже правильный
    # Признак: 0xD0/0xD1 в диапазоне латинских букв с акцентами (Ð, Ñ)
    if 'Ð' not in text and 'Ñ' not in text:
        return text

    try:
        fixed = text.encode('latin-1').decode('utf-8')
        # Проверяем, что в результате есть кириллица
        if re.search(r'[а-яА-ЯёЁ]', fixed):
            return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    return text


def main():
    conn = psycopg2.connect(
        host=os.environ.get('PGHOST', 'localhost'),
        database=os.environ.get('PGDATABASE', 'heliumdb'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', ''),
    )
    cur = conn.cursor()

    # ── Исправляем описания ЖК ────────────────────────────────────────────────
    cur.execute("""
        SELECT id, name, description
        FROM residential_complexes
        WHERE description IS NOT NULL AND description != ''
        ORDER BY id
    """)
    rows = cur.fetchall()

    fixed_jk = 0
    for rc_id, name, desc in rows:
        fixed = try_fix_encoding(desc)
        if fixed != desc:
            cur.execute(
                "UPDATE residential_complexes SET description = %s WHERE id = %s",
                (fixed[:4999], rc_id)
            )
            fixed_jk += 1
            print(f'  ✅ ЖК "{name}" — исправлено')

    # ── Исправляем описания застройщиков ─────────────────────────────────────
    cur.execute("""
        SELECT id, name, description
        FROM developers
        WHERE description IS NOT NULL AND description != ''
        ORDER BY id
    """)
    rows = cur.fetchall()

    fixed_dev = 0
    for dev_id, name, desc in rows:
        fixed = try_fix_encoding(desc)
        if fixed != desc:
            cur.execute(
                "UPDATE developers SET description = %s WHERE id = %s",
                (fixed[:4999], dev_id)
            )
            fixed_dev += 1
            print(f'  ✅ Застройщик "{name}" — исправлено')

    conn.commit()

    print(f'\n{"="*50}')
    print(f'✅ Исправлено: {fixed_jk} ЖК, {fixed_dev} застройщиков')
    print(f'{"="*50}\n')

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
