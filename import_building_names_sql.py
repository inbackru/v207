#!/usr/bin/env python3
"""Import complex_building_name using direct SQL"""
import os
from sqlalchemy import create_engine, text

# Connect to database
DATABASE_URL = os.environ.get('DATABASE_URL')
engine = create_engine(DATABASE_URL)

# Read backup data
with open('/tmp/excel_backup_data.tsv', 'r', encoding='utf-8') as f:
    lines = f.readlines()

updated_count = 0
with engine.connect() as conn:
    for line in lines:
        if not line.strip() or line.startswith('COPY'):
            continue
            
        parts = line.strip().split('\t')
        if len(parts) < 22:
            continue
        
        inner_id = parts[0]
        building_name = parts[21] if parts[21] and parts[21] not in ['\\N', ''] else None
        
        if not building_name:
            continue
        
        # Direct SQL update
        result = conn.execute(text("""
            UPDATE properties 
            SET complex_building_name = :building_name
            WHERE inner_id = :inner_id
        """), {"building_name": building_name, "inner_id": inner_id})
        
        if result.rowcount > 0:
            updated_count += 1
            if updated_count % 50 == 0:
                print(f"Updated {updated_count} properties...")
                conn.commit()
    
    conn.commit()

print(f"\n✅ Import complete! Updated: {updated_count} properties")

# Show statistics
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT COUNT(*) as total, 
               COUNT(complex_building_name) as filled
        FROM properties
    """)).fetchone()
    print(f"\n📊 Statistics:")
    print(f"   Total: {result[0]}, With names: {result[1]} ({100*result[1]/result[0]:.1f}%)")
    
    # Show Kislorod examples
    kislorod = conn.execute(text("""
        SELECT inner_id, complex_building_name
        FROM properties
        WHERE complex_id = 27 AND complex_building_name IS NOT NULL
        LIMIT 10
    """)).fetchall()
    print(f"\n🏢 ЖК Кислород examples:")
    for p in kislorod:
        print(f"   {p[0]}: {p[1]}")
