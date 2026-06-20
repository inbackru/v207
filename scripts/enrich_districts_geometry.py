#!/usr/bin/env python3
"""
Enrich districts with geometry boundaries from OpenStreetMap/Nominatim
"""

import os
import sys
import time
import logging
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import json

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_db_session():
    """Create database session"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    return Session()

def search_nominatim(district_name, city="Краснодар"):
    """
    Search for district boundaries using Nominatim API
    """
    # Nominatim API endpoint
    url = "https://nominatim.openstreetmap.org/search"
    
    # Try different query variations
    queries = [
        f"{district_name}, {city}, Краснодарский край, Россия",
        f"микрорайон {district_name}, {city}",
        f"{district_name} район, {city}",
        f"{district_name}, Краснодар"
    ]
    
    for query in queries:
        params = {
            'q': query,
            'format': 'json',
            'polygon_geojson': 1,
            'limit': 1
        }
        
        headers = {
            'User-Agent': 'InBackRealEstate/1.0'
        }
        
        try:
            logging.debug(f"Trying query: {query}")
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data and len(data) > 0:
                result = data[0]
                
                # Check if we got a polygon
                if 'geojson' in result and result['geojson'].get('type') in ['Polygon', 'MultiPolygon']:
                    logging.info(f"✅ Found geometry for '{district_name}' - {result.get('display_name', '')}")
                    return result['geojson']
            
            # Rate limiting
            time.sleep(1)
            
        except Exception as e:
            logging.error(f"Error querying Nominatim for '{query}': {e}")
            continue
    
    logging.warning(f"❌ No geometry found for: {district_name}")
    return None

def convert_geojson_to_coordinates(geojson):
    """
    Convert GeoJSON to our coordinate format: lat,lng;lat,lng;...
    """
    try:
        geom_type = geojson.get('type')
        coordinates = geojson.get('coordinates', [])
        
        if geom_type == 'Polygon':
            # Polygon has one exterior ring
            coords = coordinates[0]  # First element is exterior ring
            # Convert [lng, lat] to lat,lng format
            formatted = ';'.join([f"{lat},{lng}" for lng, lat in coords])
            return formatted
            
        elif geom_type == 'MultiPolygon':
            # MultiPolygon has multiple polygons
            # Take the largest polygon (by number of points)
            largest = max(coordinates, key=lambda p: len(p[0]))
            coords = largest[0]  # First ring of largest polygon
            formatted = ';'.join([f"{lat},{lng}" for lng, lat in coords])
            return formatted
        
        return None
        
    except Exception as e:
        logging.error(f"Error converting GeoJSON: {e}")
        return None

def enrich_districts():
    """Enrich all districts with geometry from OSM"""
    session = get_db_session()
    
    try:
        # Get all districts without geometry
        result = session.execute(text("""
            SELECT id, name
            FROM districts
            WHERE geometry IS NULL OR geometry = ''
            ORDER BY name
        """))
        
        districts = result.fetchall()
        total = len(districts)
        
        logging.info(f"📊 Processing {total} districts...")
        
        success_count = 0
        failed_count = 0
        
        for idx, (district_id, district_name) in enumerate(districts, 1):
            logging.info(f"\n[{idx}/{total}] Processing: {district_name}")
            
            # Search OSM for boundaries
            geojson = search_nominatim(district_name)
            
            if geojson:
                # Convert to our format
                geometry = convert_geojson_to_coordinates(geojson)
                
                if geometry:
                    # Save to database
                    session.execute(
                        text("""
                            UPDATE districts
                            SET geometry = :geometry, geometry_source = 'osm'
                            WHERE id = :id
                        """),
                        {"geometry": geometry, "id": district_id}
                    )
                    session.commit()
                    
                    coords_count = len(geometry.split(';'))
                    logging.info(f"✅ Saved: {coords_count} coordinates")
                    success_count += 1
                else:
                    logging.warning(f"⚠️  Failed to convert geometry")
                    failed_count += 1
            else:
                failed_count += 1
            
            # Rate limiting for Nominatim (max 1 request per second)
            time.sleep(1.5)
        
        # Summary
        print("\n" + "="*60)
        print("📊 DISTRICTS ENRICHMENT SUMMARY:")
        print("="*60)
        print(f"✅ Success:  {success_count}/{total} ({success_count*100//total if total > 0 else 0}%)")
        print(f"❌ Failed:   {failed_count}/{total}")
        print("="*60)
        
    finally:
        session.close()

def main():
    """Main execution"""
    logging.info("🚀 Starting district geometry enrichment from OSM...")
    enrich_districts()
    logging.info("✅ Complete!")

if __name__ == "__main__":
    main()
