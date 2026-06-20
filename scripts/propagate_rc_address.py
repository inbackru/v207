#!/usr/bin/env python3
"""
propagate_rc_address.py — Propagate address fields from ResidentialComplex to Properties.

Copies RC address breakdown (okrug/quarter/street/city) into the matching
property parsed_* fields for any property where the field is currently NULL.

Run after CIAN enrichment (fix_jk_bulk.py) to keep properties in sync.

Usage:
    python3 scripts/propagate_rc_address.py
    python3 scripts/propagate_rc_address.py --force   # Overwrite existing values too
    python3 scripts/propagate_rc_address.py --city 1  # Only city_id=1
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault('SESSION_SECRET', 'propagate_script')

from app import app, db
from sqlalchemy import text


def propagate(force: bool = False, city_id: int | None = None) -> dict:
    """
    Propagate RC address fields to linked properties.

    Fields propagated:
      RC.address_city_district → Property.parsed_area        (окrug/жилрайон)
      RC.address_quarter       → Property.parsed_settlement  (микрорайон)
      RC.addr_street           → Property.parsed_street      (улица)
      RC.addr_city             → Property.parsed_city        (город)

    With force=False: only fills NULL property fields (COALESCE preserves existing).
    With force=True:  overwrites all property fields from RC data.
    """
    stats = {}
    with app.app_context():
        city_filter = '' if city_id is None else f'AND p.city_id = {int(city_id)}'

        if force:
            # Overwrite everything from RC
            sql_okrug = text(f'''
                UPDATE properties p
                SET parsed_area = rc.address_city_district
                FROM residential_complexes rc
                WHERE p.complex_id = rc.id
                  AND rc.address_city_district IS NOT NULL
                  {city_filter}
            ''')
            sql_quarter = text(f'''
                UPDATE properties p
                SET parsed_settlement = rc.address_quarter
                FROM residential_complexes rc
                WHERE p.complex_id = rc.id
                  AND rc.address_quarter IS NOT NULL
                  {city_filter}
            ''')
            sql_street = text(f'''
                UPDATE properties p
                SET parsed_street = rc.addr_street
                FROM residential_complexes rc
                WHERE p.complex_id = rc.id
                  AND rc.addr_street IS NOT NULL
                  {city_filter}
            ''')
            sql_city = text(f'''
                UPDATE properties p
                SET parsed_city = rc.addr_city
                FROM residential_complexes rc
                WHERE p.complex_id = rc.id
                  AND rc.addr_city IS NOT NULL
                  AND (p.parsed_city IS NULL OR p.parsed_city = '')
                  {city_filter}
            ''')
        else:
            # Only fill NULL fields
            sql_okrug = text(f'''
                UPDATE properties p
                SET parsed_area = rc.address_city_district
                FROM residential_complexes rc
                WHERE p.complex_id = rc.id
                  AND p.parsed_area IS NULL
                  AND rc.address_city_district IS NOT NULL
                  {city_filter}
            ''')
            sql_quarter = text(f'''
                UPDATE properties p
                SET parsed_settlement = rc.address_quarter
                FROM residential_complexes rc
                WHERE p.complex_id = rc.id
                  AND p.parsed_settlement IS NULL
                  AND rc.address_quarter IS NOT NULL
                  {city_filter}
            ''')
            sql_street = text(f'''
                UPDATE properties p
                SET parsed_street = rc.addr_street
                FROM residential_complexes rc
                WHERE p.complex_id = rc.id
                  AND p.parsed_street IS NULL
                  AND rc.addr_street IS NOT NULL
                  {city_filter}
            ''')
            sql_city = text(f'''
                UPDATE properties p
                SET parsed_city = rc.addr_city
                FROM residential_complexes rc
                WHERE p.complex_id = rc.id
                  AND (p.parsed_city IS NULL OR p.parsed_city = '')
                  AND rc.addr_city IS NOT NULL
                  {city_filter}
            ''')

        r1 = db.session.execute(sql_okrug)
        stats['parsed_area'] = r1.rowcount
        r2 = db.session.execute(sql_quarter)
        stats['parsed_settlement'] = r2.rowcount
        r3 = db.session.execute(sql_street)
        stats['parsed_street'] = r3.rowcount
        r4 = db.session.execute(sql_city)
        stats['parsed_city'] = r4.rowcount
        db.session.commit()

        # Final totals
        total_q = text('''
            SELECT
                count(*) FILTER (WHERE parsed_area IS NOT NULL) as has_area,
                count(*) FILTER (WHERE parsed_settlement IS NOT NULL) as has_quarter,
                count(*) FILTER (WHERE parsed_street IS NOT NULL) as has_street,
                count(*) total
            FROM properties WHERE is_active=true
        ''')
        row = db.session.execute(total_q).fetchone()
        stats['totals'] = {
            'total_active': row[3],
            'has_area': row[0],
            'has_quarter': row[1],
            'has_street': row[2],
        }
    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Propagate RC address fields to properties')
    parser.add_argument('--force', action='store_true', help='Overwrite existing property address fields')
    parser.add_argument('--city', type=int, default=None, help='Limit to city_id')
    args = parser.parse_args()

    print(f'Propagating RC address → properties (force={args.force}, city={args.city}) ...')
    stats = propagate(force=args.force, city_id=args.city)
    print(f'  parsed_area updated:       {stats["parsed_area"]}')
    print(f'  parsed_settlement updated: {stats["parsed_settlement"]}')
    print(f'  parsed_street updated:     {stats["parsed_street"]}')
    print(f'  parsed_city updated:       {stats["parsed_city"]}')
    print()
    t = stats['totals']
    pct = lambda n: f'{n}/{t["total_active"]} ({100*n//max(t["total_active"],1)}%)'
    print(f'Final coverage:')
    print(f'  Окrug  (parsed_area):       {pct(t["has_area"])}')
    print(f'  Мкр    (parsed_settlement): {pct(t["has_quarter"])}')
    print(f'  Улица  (parsed_street):     {pct(t["has_street"])}')
    print('Done.')
