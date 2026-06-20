"""
Auto-update distance_to_center for all ResidentialComplex records.
Calculates Haversine distance from complex lat/lng to city center lat/lng.
Run manually or schedule as a cron job.

Usage:
    python3 scripts/update_complex_distances.py
    python3 scripts/update_complex_distances.py --city 1   # only city_id=1
    python3 scripts/update_complex_distances.py --dry-run  # show without saving
"""
import sys
import os
import math
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import ResidentialComplex, City


def haversine_km(lat1, lon1, lat2, lon2):
    """Return distance in km between two lat/lng points."""
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return round(2 * R * math.asin(math.sqrt(a)), 1)


def run(city_id=None, dry_run=False):
    with app.app_context():
        # Load all active cities with coordinates
        city_q = City.query.filter(
            City.latitude.isnot(None),
            City.longitude.isnot(None),
            City.is_active == True
        )
        if city_id:
            city_q = city_q.filter_by(id=city_id)
        cities = {c.id: c for c in city_q.all()}

        if not cities:
            print("❌ Нет городов с координатами центра.")
            return

        print(f"🏙️  Города для обработки: {[c.name for c in cities.values()]}")

        # Load complexes
        q = ResidentialComplex.query.filter(
            ResidentialComplex.latitude.isnot(None),
            ResidentialComplex.longitude.isnot(None)
        )
        if city_id:
            q = q.filter_by(city_id=city_id)
        complexes = q.all()

        print(f"🏘️  ЖК с координатами: {len(complexes)}")

        updated = 0
        skipped = 0
        no_city_center = 0

        for c in complexes:
            city = cities.get(c.city_id)
            if not city:
                no_city_center += 1
                continue

            dist = haversine_km(c.latitude, c.longitude, city.latitude, city.longitude)

            if c.distance_to_center == dist:
                skipped += 1
                continue

            if dry_run:
                print(f"  [DRY] {c.name} (city: {city.name}): {c.distance_to_center} → {dist} км")
            else:
                c.distance_to_center = dist
                updated += 1

        if not dry_run and updated > 0:
            db.session.commit()
            print(f"✅ Обновлено: {updated} ЖК")
        else:
            print(f"✅ Без изменений: {skipped} ЖК | Без центра города: {no_city_center}")

        # Also handle complexes without coordinates — set None explicitly
        no_coords = ResidentialComplex.query.filter(
            (ResidentialComplex.latitude.is_(None)) | (ResidentialComplex.longitude.is_(None))
        )
        if city_id:
            no_coords = no_coords.filter_by(city_id=city_id)
        no_coords_list = no_coords.filter(ResidentialComplex.distance_to_center.isnot(None)).all()
        if no_coords_list and not dry_run:
            for c in no_coords_list:
                c.distance_to_center = None
            db.session.commit()
            print(f"🔄 Сброшено (нет координат): {len(no_coords_list)} ЖК")

        print(f"\n📊 Итог: обновлено={updated}, пропущено={skipped}, нет центра={no_city_center}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Update distance_to_center for residential complexes')
    parser.add_argument('--city', type=int, default=None, help='Process only this city_id')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without saving')
    args = parser.parse_args()
    run(city_id=args.city, dry_run=args.dry_run)
