#!/usr/bin/env python3
"""
Enrich districts with geometry using Yandex Geocoder API
Similar to successful street enrichment, but using Yandex API for better polygon coverage
"""

import os
import sys
import time
import logging
import requests
import json
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

YANDEX_API_KEY = os.environ.get('YANDEX_MAPS_API_KEY')
GEOCODER_URL = 'https://geocode-maps.yandex.ru/1.x/'

def get_db_session():
    """Create database session"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    return Session()

def get_district_geometry_yandex(district_name, city="Краснодар"):
    """Get district geometry using Yandex Geocoder API"""
    if not YANDEX_API_KEY:
        logging.error("YANDEX_MAPS_API_KEY not found")
        return None
    
    # Try multiple query variations
    queries = [
        f"{district_name} микрорайон {city}",
        f"микрорайон {district_name} {city}",
        f"район {district_name} {city}",
        f"{city} {district_name}"
    ]
    
    for query in queries:
        try:
            params = {
                'apikey': YANDEX_API_KEY,
                'geocode': query,
                'format': 'json',
                'kind': 'district',  # Request district-level results
                'results': 1,
                'lang': 'ru_RU'
            }
            
            response = requests.get(GEOCODER_URL, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract geometry
            geo_objects = data.get('response', {}).get('GeoObjectCollection', {}).get('featureMember', [])
            
            if not geo_objects:
                continue
            
            geo_object = geo_objects[0].get('GeoObject', {})
            
            # Check if it's the right location (Краснодар)
            address = geo_object.get('description', '') + ' ' + geo_object.get('name', '')
            if city.lower() not in address.lower():
                continue
            
            # Get envelope (bounding box) as approximate boundary
            envelope = geo_object.get('boundedBy', {}).get('Envelope', {})
            if envelope:
                lower_corner = envelope.get('lowerCorner', '').split()
                upper_corner = envelope.get('upperCorner', '').split()
                
                if len(lower_corner) == 2 and len(upper_corner) == 2:
                    # Create rectangle polygon from bounding box
                    lon1, lat1 = lower_corner
                    lon2, lat2 = upper_corner
                    
                    # Rectangle: bottom-left, bottom-right, top-right, top-left, bottom-left (closed)
                    geometry = f"{lat1},{lon1};{lat1},{lon2};{lat2},{lon2};{lat2},{lon1};{lat1},{lon1}"
                    
                    logging.info(f"✅ Found geometry for '{district_name}' via query: '{query}'")
                    return {
                        'geometry': geometry,
                        'geometry_source': 'yandex_geocoder'
                    }
            
        except Exception as e:
            logging.debug(f"Error with query '{query}': {e}")
            continue
    
    logging.warning(f"❌ No geometry found for '{district_name}'")
    return None

def enrich_districts(limit=None):
    """Enrich all districts with Yandex Geocoder geometry"""
    session = get_db_session()
    
    try:
        # Get districts without geometry
        result = session.execute(text("""
            SELECT id, name, slug, geometry, geometry_source
            FROM districts 
            WHERE geometry IS NULL OR geometry_source IS NULL
            ORDER BY name
        """))
        
        districts = result.fetchall()
        total = len(districts)
        
        if limit:
            districts = districts[:limit]
        
        logging.info(f"📊 Found {total} districts without geometry")
        logging.info(f"🎯 Processing {len(districts)} districts")
        
        success_count = 0
        
        for idx, district in enumerate(districts, 1):
            district_id, name, slug, current_geom, current_source = district
            
            logging.info(f"\n[{idx}/{len(districts)}] Processing: {name} ({slug})")
            
            # Get geometry from Yandex
            result = get_district_geometry_yandex(name)
            
            if result:
                # Update database
                session.execute(text("""
                    UPDATE districts 
                    SET geometry = :geometry, 
                        geometry_source = :source,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """), {
                    'geometry': result['geometry'],
                    'source': result['geometry_source'],
                    'id': district_id
                })
                session.commit()
                success_count += 1
                logging.info(f"✅ Updated district: {name}")
            
            # Rate limiting
            time.sleep(0.5)
        
        logging.info(f"\n" + "="*60)
        logging.info(f"📊 FINAL STATISTICS:")
        logging.info(f"✅ Successfully enriched: {success_count}/{len(districts)}")
        logging.info(f"❌ Failed: {len(districts) - success_count}/{len(districts)}")
        logging.info(f"📈 Success rate: {success_count/len(districts)*100:.1f}%")
        logging.info("="*60)
        
    except Exception as e:
        logging.error(f"Error during enrichment: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Enrich districts with Yandex Geocoder geometry')
    parser.add_argument('--limit', type=int, help='Limit number of districts to process')
    parser.add_argument('--test', action='store_true', help='Test mode (limit to 5 districts)')
    
    args = parser.parse_args()
    
    if args.test:
        logging.info("🧪 TEST MODE: Processing 5 districts")
        enrich_districts(limit=5)
    else:
        enrich_districts(limit=args.limit)
