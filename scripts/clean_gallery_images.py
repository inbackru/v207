#!/usr/bin/env python3
"""
clean_gallery_images.py — одноразовая очистка gallery_images всех ЖК.

Фильтрует из gallery_images URL, чей файл начинается с числового ID
(это квартирные фото CIAN с водяными знаками, например '2807664603-1.jpg').
Оставляет только именованные ЖК-фото (например 'garantiya-na-obryvnoy-krasnodar-jk-...-1.jpg').

Запуск:
    python3 scripts/clean_gallery_images.py [--dry-run] [--id 282,370]
"""
import os, sys, re, json, argparse

import psycopg2


def is_watermarked(url: str) -> bool:
    """
    Возвращает True если URL — квартирное фото CIAN с водяным знаком.
    Признак: имя файла начинается с чисел (напр. '2807664603-1.jpg').
    Чистые ЖК-фото имеют slug комплекса в имени.
    """
    filename = url.split('/')[-1]
    first_segment = filename.split('-')[0]
    return first_segment.isdigit()


def clean_gallery(urls: list[str]) -> list[str]:
    clean = [u for u in urls if u and isinstance(u, str) and not is_watermarked(u)]
    return clean


def main():
    ap = argparse.ArgumentParser(description='Очистка gallery_images ЖК от водяных знаков')
    ap.add_argument('--dry-run', action='store_true', help='Показать что будет сделано без записи в БД')
    ap.add_argument('--id', type=str, default='', help='Только указанные ID (через запятую), иначе все ЖК')
    args = ap.parse_args()

    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print('❌ DATABASE_URL не задан')
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    # Выбираем ЖК с gallery_images
    if args.id:
        ids = [int(x.strip()) for x in args.id.split(',') if x.strip()]
        cur.execute(
            "SELECT id, name, gallery_images, main_image "
            "FROM residential_complexes "
            "WHERE id = ANY(%s) AND gallery_images IS NOT NULL",
            (ids,)
        )
    else:
        cur.execute(
            "SELECT id, name, gallery_images, main_image "
            "FROM residential_complexes "
            "WHERE gallery_images IS NOT NULL ORDER BY id"
        )

    rows = cur.fetchall()
    print(f'📦 Найдено ЖК с gallery_images: {len(rows)}')
    print()

    total_removed = 0
    total_updated = 0
    total_empty = 0

    for rc_id, name, gallery_raw, main_image in rows:
        try:
            gallery = json.loads(gallery_raw) if isinstance(gallery_raw, str) else gallery_raw
            if not isinstance(gallery, list):
                continue
        except Exception:
            continue

        original_count = len(gallery)
        cleaned = clean_gallery(gallery)
        removed = original_count - len(cleaned)

        if removed == 0:
            continue  # Всё чисто

        total_removed += removed

        if not cleaned:
            # Все фото были с водяными знаками — оставляем main_image если есть
            cleaned = [main_image] if main_image else []
            total_empty += 1
            status = '⚠️  пусто после очистки'
        else:
            status = '✅'

        print(f'{status} ЖК #{rc_id} «{name}»: {original_count} → {len(cleaned)} фото (убрано: {removed})')

        if not args.dry_run:
            new_gallery_json = json.dumps(cleaned, ensure_ascii=False)
            new_main = cleaned[0] if cleaned else None

            cur.execute(
                "UPDATE residential_complexes "
                "SET gallery_images=%s, main_image=COALESCE(%s, main_image), updated_at=NOW() "
                "WHERE id=%s",
                (new_gallery_json, new_main, rc_id)
            )
            total_updated += 1

    if not args.dry_run:
        conn.commit()
        print()
        print(f'✅ Обновлено ЖК: {total_updated}')
        print(f'🗑️  Убрано водяных фото: {total_removed}')
        if total_empty:
            print(f'⚠️  ЖК без фото после очистки: {total_empty} (оставлен main_image)')
    else:
        print()
        print(f'[DRY RUN] Было бы обновлено ЖК: {total_updated if total_updated else total_removed > 0}')
        print(f'[DRY RUN] Убрать водяных фото: {total_removed}')

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
