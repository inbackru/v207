#!/usr/bin/env python3
"""
Complete street geometry enrichment from kayan.ru
Strategy: First fetch ALL streets from kayan.ru, then match with our database
"""

import os
import sys
import time
import logging
import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import re
from urllib.parse import urljoin

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

BASE_URL = 'https://www.kayan.ru'
STREETS_LIST_URL = f'{BASE_URL}/ulicy'

def get_db_session():
    """Create database session"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    return Session()

def normalize_street_name(name):
    """Normalize street name for comparison"""
    # Remove extra spaces and convert to lowercase
    name = re.sub(r'\s+', ' ', name.lower().strip())
    
    # Standardize abbreviations
    abbreviations = {
        'ул.': 'улица',
        'пер.': 'переулок',
        'пр.': 'проезд',
        'пр-т': 'проспект',
        'пр-кт': 'проспект',
        'бул.': 'бульвар',
        'наб.': 'набережная',
        'туп.': 'тупик',
        'ш.': 'шоссе',
        'пл.': 'площадь'
    }
    
    for abbr, full in abbreviations.items():
        name = name.replace(f' {abbr}', f' {full}')
        if name.endswith(f' {abbr}'):
            name = name[:-len(abbr)] + full
    
    # Remove trailing type words for better matching
    name = re.sub(r'\s+(улица|переулок|проезд|проспект|бульвар|набережная|тупик|шоссе|площадь)$', '', name)
    
    return name.strip()

def fetch_all_kayan_streets():
    """Fetch all streets from kayan.ru main list"""
    logging.info(f"📥 Fetching complete street list from {STREETS_LIST_URL}...")
    
    try:
        response = requests.get(STREETS_LIST_URL, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all street links
        street_links = soup.find_all('div', class_='streets-name')
        
        streets_map = {}
        for link_div in street_links:
            link = link_div.find('a')
            if link and link.get('href'):
                street_name = link.get_text(strip=True)
                street_url = urljoin(BASE_URL, link['href'])
                
                # Store both original and normalized name
                normalized = normalize_street_name(street_name)
                streets_map[normalized] = {
                    'original_name': street_name,
                    'url': street_url
                }
        
        logging.info(f"✅ Found {len(streets_map)} streets on kayan.ru")
        return streets_map
        
    except Exception as e:
        logging.error(f"❌ Error fetching street list: {e}")
        return {}

def extract_geometry_from_page(url):
    """Extract geometry coordinates from a kayan.ru street page"""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find geometry data in JavaScript
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string and 'var geometry' in script.string:
                # Extract geometry array
                match = re.search(r'var geometry\s*=\s*(\[\[.*?\]\])', script.string, re.DOTALL)
                if match:
                    geometry_str = match.group(1)
                    # Parse coordinates
                    coords_matches = re.findall(r'\[([\d.]+),\s*([\d.]+)\]', geometry_str)
                    if coords_matches:
                        # Convert to our format: lat,lng;lat,lng;...
                        coords = ';'.join([f"{lat},{lng}" for lat, lng in coords_matches])
                        return coords
        
        return None
        
    except Exception as e:
        logging.error(f"Error extracting geometry from {url}: {e}")
        return None

def match_and_enrich_streets(kayan_streets_map):
    """Match database streets with kayan.ru and enrich with geometry"""
    session = get_db_session()
    
    try:
        # Get all streets from database
        result = session.execute(text("""
            SELECT id, name, geometry 
            FROM streets 
            ORDER BY name
        """))
        
        db_streets = result.fetchall()
        total = len(db_streets)
        
        logging.info(f"📊 Processing {total} streets from database...")
        
        success_count = 0
        failed_count = 0
        skipped_count = 0
        
        for idx, (street_id, street_name, existing_geometry) in enumerate(db_streets, 1):
            # Skip if already has geometry from kayan
            existing_source = session.execute(
                text("SELECT geometry_source FROM streets WHERE id = :id"),
                {"id": street_id}
            ).scalar()
            
            if existing_geometry and existing_source == 'kayan':
                logging.info(f"[{idx}/{total}] ⏭️  Skipping '{street_name}' (already enriched)")
                skipped_count += 1
                continue
            
            logging.info(f"\n[{idx}/{total}] Processing: {street_name}")
            
            # Normalize our street name
            normalized = normalize_street_name(street_name)
            
            # Try to find match in kayan map
            if normalized in kayan_streets_map:
                kayan_data = kayan_streets_map[normalized]
                logging.info(f"✅ Found match: '{street_name}' → '{kayan_data['original_name']}'")
                logging.info(f"   URL: {kayan_data['url']}")
                
                # Extract geometry
                geometry = extract_geometry_from_page(kayan_data['url'])
                
                if geometry:
                    # Save to database
                    session.execute(
                        text("""
                            UPDATE streets 
                            SET geometry = :geometry, geometry_source = 'kayan'
                            WHERE id = :id
                        """),
                        {"geometry": geometry, "id": street_id}
                    )
                    session.commit()
                    
                    coords_count = len(geometry.split(';'))
                    logging.info(f"✅ Saved geometry: {coords_count} coordinates")
                    success_count += 1
                else:
                    logging.warning(f"⚠️  No geometry found on page")
                    failed_count += 1
            else:
                logging.warning(f"❌ No match found for: {street_name} (normalized: {normalized})")
                failed_count += 1
            
            # Rate limiting
            time.sleep(0.5)
        
        # Summary
        print("\n" + "="*60)
        print("📊 KAYAN COMPLETE ENRICHMENT SUMMARY:")
        print("="*60)
        print(f"✅ Success:  {success_count}/{total} ({success_count*100//total if total > 0 else 0}%)")
        print(f"⏭️  Skipped:  {skipped_count}/{total} (already enriched)")
        print(f"❌ Failed:   {failed_count}/{total}")
        print("="*60)
        
    finally:
        session.close()

def main():
    """Main execution"""
    logging.info("🚀 Starting complete kayan.ru enrichment...")
    
    # Step 1: Fetch all streets from kayan.ru
    kayan_streets_map = fetch_all_kayan_streets()
    
    if not kayan_streets_map:
        logging.error("❌ Failed to fetch streets from kayan.ru")
        sys.exit(1)
    
    # Step 2: Match and enrich database streets
    match_and_enrich_streets(kayan_streets_map)
    
    logging.info("✅ Complete!")

if __name__ == "__main__":
    main()
