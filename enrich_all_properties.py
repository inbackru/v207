#!/usr/bin/env python3
"""
Batch enrich all properties with parsed address components.

For each property with coordinates, the geocoding service:
  1. Calls Yandex reverse geocoding → parsed_city, parsed_area (okrug),
     parsed_settlement (microrayon), parsed_street, parsed_house
  2. Runs PIP (point-in-polygon) against district polygons → district_id FK

Usage:
    python enrich_all_properties.py [--only-missing] [--batch-size 50] [--delay 0.1]

Options:
    --only-missing   Only process properties where district_id IS NULL
    --batch-size N   Properties per DB batch (default: 50)
    --delay S        Seconds between Yandex API requests (default: 0.1)
"""

import argparse
import time

from services.geocoding import get_geocoding_service
from app import app, db
from models import Property


def enrich_all_properties(batch_size: int = 50, delay: float = 0.1,
                          only_missing: bool = False):
    with app.app_context():
        service = get_geocoding_service()

        print("=" * 80)
        print("МАССОВОЕ ОБОГАЩЕНИЕ АДРЕСОВ ОБЪЕКТОВ")
        print("=" * 80)

        # Preload PIP polygons once (avoids repeated DB queries per property)
        print("\nЗагрузка полигонов районов для PIP…")
        service.preload_pip()

        base_q = Property.query.filter(
            Property.latitude.isnot(None),
            Property.longitude.isnot(None),
        )
        if only_missing:
            base_q = base_q.filter(Property.district_id.is_(None))

        total_properties = base_q.count()
        print(f"Всего объектов для обработки: {total_properties}")

        processed = 0
        updated   = 0
        errors    = 0

        while processed < total_properties:
            properties = (
                base_q
                .limit(batch_size)
                .offset(processed)
                .all()
            )
            if not properties:
                break

            print(f"\n{'='*80}")
            print(f"ПАКЕТ {processed // batch_size + 1}: "
                  f"объекты {processed + 1}–{processed + len(properties)} из {total_properties}")
            print(f"{'='*80}")

            for i, prop in enumerate(properties, 1):
                try:
                    print(f"\n[{processed + i}/{total_properties}] {prop.title}")
                    print(f"   Координаты: {prop.latitude}, {prop.longitude}")

                    enriched = service.enrich_property_address(
                        prop.latitude,
                        prop.longitude,
                    )

                    if enriched:
                        old_city       = prop.parsed_city
                        old_area       = prop.parsed_area
                        old_settlement = prop.parsed_settlement
                        old_district   = prop.parsed_district
                        old_street     = prop.parsed_street
                        old_house      = prop.parsed_house
                        old_dist_id    = prop.district_id

                        prop.parsed_city       = enriched.get('parsed_city', '')
                        prop.parsed_area       = enriched.get('parsed_area', '')
                        prop.parsed_settlement = enriched.get('parsed_settlement', '')
                        prop.parsed_district   = enriched.get('parsed_district', '')
                        prop.parsed_street     = enriched.get('parsed_street', '')
                        prop.parsed_house      = enriched.get('parsed_house', '')
                        prop.parsed_block      = enriched.get('parsed_block', '')

                        # Assign district_id from PIP (only overwrite if we got one)
                        new_district_id = enriched.get('district_id')
                        if new_district_id:
                            prop.district_id = new_district_id

                        changes = []
                        if old_city       != prop.parsed_city:
                            changes.append(f"city: {old_city!r}→{prop.parsed_city!r}")
                        if old_area       != prop.parsed_area:
                            changes.append(f"area: {old_area!r}→{prop.parsed_area!r}")
                        if old_settlement != prop.parsed_settlement:
                            changes.append(f"settlement: {old_settlement!r}→{prop.parsed_settlement!r}")
                        if old_dist_id    != prop.district_id:
                            changes.append(f"district_id: {old_dist_id}→{prop.district_id}")
                        if old_street     != prop.parsed_street:
                            changes.append(f"street: {old_street!r}→{prop.parsed_street!r}")
                        if old_house      != prop.parsed_house:
                            changes.append(f"house: {old_house!r}→{prop.parsed_house!r}")

                        if changes:
                            print(f"   ✅ Обновлено: {', '.join(changes)}")
                            updated += 1
                        else:
                            print("   ⏭️  Без изменений")

                        time.sleep(delay)

                    else:
                        print("   ⚠️  Геокодер не вернул данные")
                        errors += 1

                except Exception as e:
                    print(f"   ❌ Ошибка: {e}")
                    errors += 1

            try:
                db.session.commit()
                print(f"\n✅ Пакет сохранён")
            except Exception as e:
                db.session.rollback()
                print(f"\n❌ Ошибка сохранения: {e}")

            processed += len(properties)

        print(f"\n{'='*80}")
        print("ИТОГОВАЯ СТАТИСТИКА")
        print(f"{'='*80}")
        print(f"Обработано: {processed}")
        print(f"Обновлено:  {updated}")
        print(f"Ошибок:     {errors}")

        stats = service.get_stats()
        print(f"\nAPI запросов:      {stats['api_requests']}")
        print(f"Попаданий в кэш:   {stats['cache_hits']}")
        print(f"Процент попаданий: {stats['cache_hit_rate']}")
        print(f"Районов в PIP:     {stats.get('pip_districts', '—')}")

        print(f"\n{'='*80}")
        print("ОБОГАЩЕНИЕ ЗАВЕРШЕНО")
        print(f"{'='*80}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch-enrich property addresses")
    parser.add_argument("--only-missing", action="store_true",
                        help="Process only properties without district_id")
    parser.add_argument("--batch-size", type=int, default=50,
                        help="DB batch size (default: 50)")
    parser.add_argument("--delay", type=float, default=0.1,
                        help="Delay between Yandex API calls in seconds (default: 0.1)")
    args = parser.parse_args()

    enrich_all_properties(
        batch_size=args.batch_size,
        delay=args.delay,
        only_missing=args.only_missing,
    )
