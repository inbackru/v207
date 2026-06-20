#!/usr/bin/env python3
"""
Final improved street geometry enrichment from kayan.ru
Combines: 
  1. Full street list from kayan.ru for accurate matching
  2. Working geometry extraction mechanism
"""

import os
import sys
import time
import logging
import requests
import re
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from urllib.parse import urljoin
import argparse

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
    
    # Remove trailing type words for better matching
    name = re.sub(r'\s+(улица|переулок|проезд|проспект|бульвар|набережная|тупик|шоссе|площадь)$', '', name)
    
    return name.strip()

def fetch_kayan_streets_map():
    """Fetch complete street list from kayan.ru and create mapping"""
    logging.info(f"📥 Fetching street list from {STREETS_LIST_URL}...")
    
    try:
        response = requests.get(STREETS_LIST_URL, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        street_links = soup.find_all('div', class_='streets-name')
        
        streets_map = {}
        for link_div in street_links:
            link = link_div.find('a')
            if link and link.get('href'):
                street_name = link.get_text(strip=True)
                street_url = urljoin(BASE_URL, link['href'])
                
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
    """Extract geometry from kayan.ru street page using street_data variable"""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Extract street_data from JavaScript (this is the working method!)
        match = re.search(r'var street_data="([^"]+)"', response.text)
        
        if match:
            geometry = match.group(1)
            return geometry
        
        return None
        
    except Exception as e:
        logging.debug(f"Error extracting geometry from {url}: {e}")
        return None

def enrich_streets(kayan_map, limit=None, skip_existing=True):
    """Enrich database streets with kayan.ru geometry"""
    session = get_db_session()
    
    try:
        # Get all streets from database
        result = session.execute(text("""
            SELECT id, name, geometry, geometry_source
            FROM streets 
            ORDER BY name
        """))
        
        db_streets = result.fetchall()
        
        if limit:
            db_streets = db_streets[:limit]
        
        total = len(db_streets)
        logging.info(f"📊 Processing {total} streets from database...")
        
        success_count = 0
        failed_count = 0
        skipped_count = 0
        
        for idx, (street_id, street_name, existing_geometry, existing_source) in enumerate(db_streets, 1):
            # Skip if already enriched from kayan
            if skip_existing and existing_geometry and existing_source == 'kayan':
                if idx % 100 == 0:  # Log every 100th skipped
                    logging.info(f"[{idx}/{total}] Skipping already enriched streets...")
                skipped_count += 1
                continue
            
            logging.info(f"\n[{idx}/{total}] Processing: {street_name}")
            
            # Normalize and find in kayan map
            normalized = normalize_street_name(street_name)
            
            if normalized in kayan_map:
                kayan_data = kayan_map[normalized]
                logging.info(f"✅ Match found: '{street_name}' → '{kayan_data['original_name']}'")
                logging.debug(f"   URL: {kayan_data['url']}")
                
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
                    logging.info(f"✅ Saved: {coords_count} coordinates")
                    success_count += 1
                else:
                    logging.warning(f"⚠️  Page found but no geometry extracted")
                    failed_count += 1
            else:
                logging.warning(f"❌ Not found on kayan.ru")
                failed_count += 1
            
            # Rate limiting
            time.sleep(0.5)
        
        # Summary
        print("\n" + "="*60)
        print("📊 FINAL ENRICHMENT SUMMARY:")
        print("="*60)
        print(f"✅ Success:  {success_count}/{total} ({success_count*100//total if total > 0 else 0}%)")
        print(f"⏭️  Skipped:  {skipped_count}/{total} (already enriched)")
        print(f"❌ Failed:   {failed_count}/{total}")
        print(f"📈 Coverage: {success_count + skipped_count}/{total} ({(success_count + skipped_count)*100//total if total > 0 else 0}%)")
        print("="*60)
        
    finally:
        session.close()

def main():
    """Main execution"""
    parser = argparse.ArgumentParser(description='Enrich streets with kayan.ru geometry')
    parser.add_argument('--limit', type=int, help='Limit number of streets to process')
    parser.add_argument('--force', action='store_true', help='Re-enrich even if already has geometry')
    args = parser.parse_args()
    
    logging.info("🚀 Starting kayan.ru street enrichment...")
    
    # Step 1: Fetch complete street list from kayan.ru
    kayan_map = fetch_kayan_streets_map()
    
    if not kayan_map:
        logging.error("❌ Failed to fetch streets from kayan.ru")
        sys.exit(1)
    
    # Step 2: Match and enrich database streets
    enrich_streets(kayan_map, limit=args.limit, skip_existing=not args.force)
    
    logging.info("✅ Complete!")

if __name__ == "__main__":
    main()
