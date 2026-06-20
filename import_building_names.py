#!/usr/bin/env python3
"""Import complex_building_name from backup to properties table"""
import os
import sys
from app import app, db
from models import Property

def import_building_names():
    with app.app_context():
        # Read backup data
        with open('/tmp/excel_backup_data.tsv', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Column 22 is complex_building_name (0-indexed: 21)
        # Column 1 is inner_id (0-indexed: 0)
        updated_count = 0
        skipped_count = 0
        
        for line in lines:
            if not line.strip() or line.startswith('COPY'):
                continue
                
            parts = line.strip().split('\t')
            if len(parts) < 22:
                continue
            
            inner_id = parts[0]
            building_name = parts[21] if parts[21] and parts[21] != '\\N' else None
            
            if not building_name:
                skipped_count += 1
                continue
            
            # Find property by inner_id and update
            prop = db.session.query(Property).filter_by(inner_id=inner_id).first()
            if prop:
                prop.complex_building_name = building_name
                updated_count += 1
                if updated_count % 50 == 0:
                    print(f"Updated {updated_count} properties...")
                    db.session.commit()
        
        db.session.commit()
        print(f"\n✅ Import complete!")
        print(f"   Updated: {updated_count} properties")
        print(f"   Skipped: {skipped_count} (no building name)")
        
        # Show statistics using raw SQL
        result = db.session.execute(db.text("""
            SELECT COUNT(*) as total, 
                   COUNT(complex_building_name) as filled
            FROM properties
        """)).fetchone()
        print(f"\n📊 Statistics:")
        print(f"   Total properties: {result[0]}")
        print(f"   With building names: {result[1]} ({100*result[1]/result[0]:.1f}%)")
        
        # Show examples for Kislorod using raw SQL
        kislorod_props = db.session.execute(db.text("""
            SELECT inner_id, complex_building_name
            FROM properties
            WHERE complex_id = 27
            LIMIT 5
        """)).fetchall()
        print(f"\n🏢 ЖК Кислород examples:")
        for p in kislorod_props:
            print(f"   {p[0]}: {p[1] or 'NULL'}")

if __name__ == '__main__':
    import_building_names()
