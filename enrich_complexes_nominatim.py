#!/usr/bin/env python3
"""
Batch enrichment script for ResidentialComplex objects.

Fills three fields per complex using a three-step fallback chain:
  1. PIP (point-in-polygon, instant, no API)  — district_id + names from geometry
  2. Yandex reverse geocoding (fast, cached)  — city_district + settlement strings
  3. Nominatim reverse geocoding (slow, 1/s)  — last resort when Yandex has no data

Saves to DB:
  address_quarter        — microrayon name (e.g. "Самолёт")
  address_city_district  — okrug name      (e.g. "Прикубанский округ")
  district_id            — FK to districts.id (most specific polygon match)

Usage:
  python enrich_complexes_nominatim.py [options]

Options:
  --city-id N      City to process (default: all cities)
  --limit N        Max complexes to process (0 = all)
  --force          Re-enrich even if address_city_district already set
  --no-nominatim   Disable Nominatim fallback (PIP + Yandex only, much faster)
"""

import os
import sys
import time
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import ResidentialComplex
from services.geocoding import get_geocoding_service

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)

NOMINATIM_DELAY = 1.1  # respect 1 req/sec Nominatim policy


def enrich(city_id=None, limit=None, force=False, use_nominatim=True):
    """
    Enrich complexes using PIP → Yandex → Nominatim chain.

    Args:
        city_id:        Restrict to one city (None = all cities).
        limit:          Max number of complexes to process.
        force:          If False, skip complexes that already have address_city_district.
        use_nominatim:  Enable Nominatim as last-resort fallback.
    """
    service = get_geocoding_service()

    log.info("Загрузка полигонов районов для PIP…")
    service.preload_pip()

    stats = service.get_stats()
    log.info(f"PIP: загружено {stats.get('pip_districts', 0)} районов")

    query = db.session.query(ResidentialComplex).filter(
        ResidentialComplex.latitude.isnot(None),
        ResidentialComplex.longitude.isnot(None),
    )
    if city_id is not None:
        query = query.filter(ResidentialComplex.city_id == city_id)
    if not force:
        # Process those without district info OR without district_id
        query = query.filter(
            db.or_(
                ResidentialComplex.address_city_district.is_(None),
                ResidentialComplex.address_city_district == '',
                ResidentialComplex.district_id.is_(None),
            )
        )
    if limit:
        query = query.limit(limit)

    complexes = query.all()
    log.info(f"Обработка {len(complexes)} ЖК "
             f"(city_id={city_id or 'все'}, force={force}, nominatim={use_nominatim})")

    updated  = 0
    skipped  = 0
    yandex_hits = 0
    pip_hits    = 0
    nom_hits    = 0

    for idx, rc in enumerate(complexes):
        lat, lon = float(rc.latitude), float(rc.longitude)
        log.info(f"[{idx + 1}/{len(complexes)}] {rc.name} ({lat:.4f}, {lon:.4f})")

        # Nominatim delay only when that step is actually needed; pass 0 to disable
        nom_delay = NOMINATIM_DELAY if use_nominatim else 0.0

        try:
            enriched = service.enrich_complex_address(lat, lon,
                                                      nominatim_delay=nom_delay)
        except Exception as e:
            log.warning(f"  ⚠️  enrich_complex_address failed: {e}")
            skipped += 1
            continue

        addr_cd  = enriched.get('address_city_district', '') or ''
        addr_q   = enriched.get('address_quarter', '') or ''
        dist_id  = enriched.get('district_id')

        if not addr_cd and not addr_q and not dist_id:
            log.info("  — нет данных, пропускаем")
            skipped += 1
            continue

        # Track which step provided useful data (for stats)
        if dist_id and dist_id != rc.district_id:
            pip_hits += 1
        if enriched.get('city'):
            yandex_hits += 1

        # Update fields (only overwrite if we have better data)
        changed = False
        if addr_cd and addr_cd != rc.address_city_district:
            rc.address_city_district = addr_cd
            changed = True
        if addr_q and addr_q != rc.address_quarter:
            rc.address_quarter = addr_q
            changed = True
        if dist_id and dist_id != rc.district_id:
            rc.district_id = dist_id
            changed = True

        if changed:
            updated += 1
            log.info(f"  ✅ okrug={addr_cd!r}  micro={addr_q!r}  district_id={dist_id}")
        else:
            log.info("  ⏭️  Без изменений")

        if (idx + 1) % 20 == 0:
            db.session.commit()
            log.info(f"  ✓ Сохранено {updated} из {idx + 1} обработанных")

    db.session.commit()

    log.info(f"\n{'='*60}")
    log.info("ИТОГ")
    log.info(f"  Обработано:  {len(complexes)}")
    log.info(f"  Обновлено:   {updated}")
    log.info(f"  Пропущено:   {skipped}")
    log.info(f"  PIP hits:    {pip_hits}")
    log.info(f"  Yandex hits: {yandex_hits}")

    # Summary by district
    from sqlalchemy import func
    filter_q = db.session.query(
        ResidentialComplex.address_city_district,
        func.count(ResidentialComplex.id)
    )
    if city_id is not None:
        filter_q = filter_q.filter(ResidentialComplex.city_id == city_id)
    rows = filter_q.group_by(ResidentialComplex.address_city_district).all()
    log.info("\nРаспределение по округам:")
    for name, cnt in sorted(rows, key=lambda r: -(r[1])):
        log.info(f"  {name or '(без округа)'}: {cnt} ЖК")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Enrich ResidentialComplex with district hierarchy (PIP→Yandex→Nominatim)"
    )
    parser.add_argument("--city-id", type=int, default=None,
                        help="Restrict to city ID (default: all cities)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max complexes to process (0 = all)")
    parser.add_argument("--force", action="store_true",
                        help="Re-enrich even if already enriched")
    parser.add_argument("--no-nominatim", action="store_true",
                        help="Disable Nominatim fallback (faster, PIP+Yandex only)")
    args = parser.parse_args()

    with app.app_context():
        enrich(
            city_id=args.city_id,
            limit=args.limit or None,
            force=args.force,
            use_nominatim=not args.no_nominatim,
        )
