#!/usr/bin/env python3
"""
Script to enrich streets with geometry data from OpenStreetMap via Overpass API.
Extracts polyline coordinates for street highlighting on Yandex Maps.
"""

import os
import sys
import time
import json
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import logging

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
KRASNODAR_BBOX = "(44.8,38.6,45.2,39.3)"  # Krasnodar boundaries: (min_lat, min_lon, max_lat, max_lon)
REQUEST_DELAY = 1.0  # Rate limit: 1 request per second

def get_db_connection():
    """Create database connection"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable not set")
    
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    return Session()

def fetch_street_geometry_from_osm(street_name, city="Краснодар"):
    """
    Fetch street geometry from OpenStreetMap using Overpass API.
    
    Returns:
        dict: {
            'geometry': 'lat1,lng1;lat2,lng2;...',  # Formatted polyline
            'raw_coords': [[lat1, lng1], [lat2, lng2], ...],  # Raw coordinates
            'source': 'osm'
        } or None if not found
    """
    
    # Try different name variations
    # Extract base name and street type
    base_name = street_name
    street_type = ""
    
    # Common street types
    types = ['улица', 'проспект', 'переулок', 'проезд', 'бульвар', 'площадь', 'тупик', 'шоссе']
    for t in types:
        if f' {t}' in street_name:
            base_name = street_name.replace(f' {t}', '').strip()
            street_type = t
            break
    
    name_variations = [
        street_name,  # Original: "1-й Айвазовского проезд"
        base_name,  # Without type: "1-й Айвазовского"
        f"улица {street_name}",  # "улица 1-й Айвазовского проезд"
        f"ул. {street_name}",  # "ул. 1-й Айвазовского проезд"
    ]
    
    # If has type, add variations with type in different positions
    if street_type:
        name_variations.extend([
            f"{street_type} {base_name}",  # "проезд 1-й Айвазовского"
            f"улица {base_name}",  # "улица 1-й Айвазовского"
            f"ул. {base_name}",  # "ул. 1-й Айвазовского"
        ])
    
    # Remove duplicates while preserving order
    name_variations = list(dict.fromkeys(name_variations))
    
    # Overpass QL query using bounding box instead of area (more reliable)
    # Krasnodar bbox: (44.8,38.6,45.2,39.3)
    queries = []
    for name in name_variations:
        queries.append(f'way["highway"]["name"="{name}"]{KRASNODAR_BBOX};')
        queries.append(f'way["highway"]["name:ru"="{name}"]{KRASNODAR_BBOX};')
    
    overpass_query = f"""
    [out:json][timeout:25];
    (
      {chr(10).join(queries)}
    );
    out geom;
    """
    
    try:
        logging.info(f"Fetching OSM data for: {street_name}")
        
        response = requests.post(
            OVERPASS_URL,
            data={'data': overpass_query},
            timeout=30
        )
        
        if response.status_code != 200:
            logging.error(f"OSM API error {response.status_code}: {response.text}")
            return None
        
        data = response.json()
        elements = data.get('elements', [])
        
        if not elements:
            logging.warning(f"No OSM data found for: {street_name}")
            return None
        
        # Collect all coordinates from all way segments
        all_coords = []
        
        for element in elements:
            if element.get('type') == 'way' and 'geometry' in element:
                coords = [[node['lat'], node['lon']] for node in element['geometry']]
                all_coords.append(coords)
        
        if not all_coords:
            logging.warning(f"No geometry found in OSM data for: {street_name}")
            return None
        
        # Convert to kayan.ru format: "lat1,lng1;lat2,lng2;..."
        # Multiple segments separated by "#"
        geometry_string = format_geometry_for_map(all_coords)
        
        logging.info(f"✅ Found OSM geometry for {street_name}: {len(all_coords)} segment(s)")
        
        return {
            'geometry': geometry_string,
            'raw_coords': all_coords,
            'source': 'osm',
            'segments_count': len(all_coords)
        }
        
    except Exception as e:
        logging.error(f"Error fetching OSM data for {street_name}: {str(e)}")
        return None

def format_geometry_for_map(coords_segments):
    """
    Format coordinates to match kayan.ru format:
    "lat1,lng1;lat2,lng2;..." for single segment
    "segment1#segment2#segment3" for multiple segments
    
    Args:
        coords_segments: List of coordinate segments [[lat,lng], ...] or [[[lat,lng], ...], ...]
    """
    formatted_segments = []
    
    for segment in coords_segments:
        if segment:
            # Format each segment as "lat1,lng1;lat2,lng2;..."
            formatted_points = [f"{coord[0]},{coord[1]}" for coord in segment]
            formatted_segment = ";".join(formatted_points)
            formatted_segments.append(formatted_segment)
    
    # Join segments with "#"
    return "#".join(formatted_segments)

def enrich_street_geometry(street_id, street_name, dry_run=False):
    """
    Enrich a single street with geometry from OSM
    
    Args:
        street_id: Street ID in database
        street_name: Street name
        dry_run: If True, don't save to database
    
    Returns:
        bool: Success status
    """
    
    # Create fresh session for each street to avoid SSL connection issues
    session = get_db_connection()
    
    try:
        # Check if already has geometry
        existing = session.execute(
            text("SELECT geometry, geometry_source FROM streets WHERE id = :id"),
            {'id': street_id}
        ).fetchone()
    
        if existing and existing.geometry:
            logging.info(f"⏭️  Street '{street_name}' already has geometry from {existing.geometry_source}")
            return True
        
        # Fetch from OSM
        result = fetch_street_geometry_from_osm(street_name)
        
        if not result:
            logging.warning(f"❌ Could not get geometry for: {street_name}")
            return False
        
        if dry_run:
            logging.info(f"🔍 DRY RUN - Would save geometry for {street_name}: {result['geometry'][:100]}...")
            return True
        
        # Save to database
        session.execute(
            text("""
                UPDATE streets 
                SET geometry = :geometry, 
                    geometry_source = :source,
                    updated_at = NOW()
                WHERE id = :id
            """),
            {
                'id': street_id,
                'geometry': result['geometry'],
                'source': result['source']
            }
        )
        session.commit()
        logging.info(f"✅ Saved geometry for: {street_name}")
        return True
        
    except Exception as e:
        session.rollback()
        logging.error(f"❌ Error for {street_name}: {str(e)}")
        return False
    finally:
        session.close()

def main():
    """Main enrichment process"""
    
    # Parse arguments
    dry_run = '--dry-run' in sys.argv
    limit = None
    
    for arg in sys.argv:
        if arg.startswith('--limit='):
            limit = int(arg.split('=')[1])
    
    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be saved to database\n")
    
    session = get_db_connection()
    
    # Get streets without geometry
    query = """
        SELECT id, name 
        FROM streets 
        WHERE geometry IS NULL
        ORDER BY name
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    streets = session.execute(text(query)).fetchall()
    
    total = len(streets)
    logging.info(f"📊 Found {total} streets without geometry")
    
    if total == 0:
        logging.info("✅ All streets already have geometry!")
        return
    
    success_count = 0
    failed_count = 0
    
    for idx, street in enumerate(streets, 1):
        street_id, street_name = street.id, street.name
        
        logging.info(f"\n[{idx}/{total}] Processing: {street_name}")
        
        success = enrich_street_geometry(street_id, street_name, dry_run)
        
        if success:
            success_count += 1
        else:
            failed_count += 1
        
        # Rate limiting
        if idx < total:
            time.sleep(REQUEST_DELAY)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"📊 ENRICHMENT SUMMARY:")
    print(f"{'='*60}")
    print(f"✅ Success: {success_count}/{total}")
    print(f"❌ Failed:  {failed_count}/{total}")
    print(f"{'='*60}\n")
    
    session.close()

if __name__ == "__main__":
    main()
