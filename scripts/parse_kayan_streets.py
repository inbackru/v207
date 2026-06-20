#!/usr/bin/env python3
"""
Parse street geometry data from kayan.ru
"""

import os
import sys
import time
import re
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

KAYAN_BASE_URL = "https://www.kayan.ru/ulicy/"
REQUEST_DELAY = 0.5  # Be polite, 2 requests per second max

# Transliteration map (Russian to Latin)
TRANSLIT_MAP = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    ' ': '-', '.': '', '(': '', ')': '', ',': '', '/': '-', 'й': 'y'
}

def get_db_connection():
    """Create database connection"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable not set")
    
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    return Session()

def transliterate(text):
    """Transliterate Russian text to Latin"""
    text = text.lower()
    
    # Handle ordinal numbers: "1-й" → "1", "2-я" → "2", etc.
    import re
    text = re.sub(r'(\d+)-[йяе]', r'\1', text)
    
    result = []
    for char in text:
        result.append(TRANSLIT_MAP.get(char, char))
    return ''.join(result)

def generate_slug_variants(street_name):
    """Generate possible slug variants for a street name"""
    slugs = []
    
    # Clean street name
    clean_name = street_name.lower().strip()
    
    # Expand abbreviations FIRST (most important!)
    abbreviations = {
        'пер.': 'переулок',
        'ул.': 'улица', 
        'пр.': 'проезд',
        'пр-т': 'проспект',
        'пр-кт': 'проспект',
        'бул.': 'бульвар',
        'наб.': 'набережная',
        'туп.': 'тупик',
        'ш.': 'шоссе',
        'пл.': 'площадь'
    }
    
    # Create variant with expanded abbreviations
    expanded_name = clean_name
    for abbr, full in abbreviations.items():
        expanded_name = expanded_name.replace(abbr, full)
    expanded_name = expanded_name.strip()
    
    # Priority order of variants:
    
    # 1. Expanded abbreviations (most reliable)
    if expanded_name != clean_name:
        slugs.append(transliterate(expanded_name))
    
    # 2. Direct transliteration of original
    slugs.append(transliterate(clean_name))
    
    # 3. Without abbreviations at all
    clean_no_abbr = clean_name
    for abbr in abbreviations.keys():
        clean_no_abbr = clean_no_abbr.replace(abbr, '').strip()
    if clean_no_abbr != clean_name:
        slugs.append(transliterate(clean_no_abbr))
    
    # 4. With Latin type words
    latin_types = {
        'переулок': 'pereulok',
        'улица': 'ulitsa',
        'проезд': 'proezd',
        'проспект': 'prospekt',
        'бульвар': 'bulvar',
        'шоссе': 'shosse'
    }
    
    for rus, lat in latin_types.items():
        if rus in expanded_name:
            # Try transliterating base + latin type word
            variant = expanded_name.replace(rus, lat).strip()
            # Transliterate only the non-latin parts
            parts = variant.split()
            translit_parts = []
            for part in parts:
                if part in latin_types.values():
                    translit_parts.append(part)
                else:
                    translit_parts.append(transliterate(part))
            slugs.append('-'.join(translit_parts))
    
    # Remove duplicates while preserving order
    return list(dict.fromkeys(slugs))

def fetch_street_from_kayan(street_name):
    """
    Fetch street geometry from kayan.ru
    
    Returns:
        dict with geometry data or None
    """
    slug_variants = generate_slug_variants(street_name)
    
    for slug in slug_variants:
        url = f"{KAYAN_BASE_URL}{slug}"
        
        try:
            logging.debug(f"Trying URL: {url}")
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                # Extract street_data from JavaScript
                match = re.search(r'var street_data="([^"]+)"', response.text)
                
                if match:
                    geometry = match.group(1)
                    logging.info(f"✅ Found geometry for '{street_name}' at {url}")
                    logging.debug(f"   Geometry length: {len(geometry)} chars")
                    
                    return {
                        'geometry': geometry,
                        'source': 'kayan',
                        'url': url
                    }
                else:
                    logging.debug(f"No street_data found on page")
            
            elif response.status_code == 404:
                logging.debug(f"404 Not Found: {url}")
            else:
                logging.warning(f"HTTP {response.status_code} for {url}")
                
        except Exception as e:
            logging.error(f"Error fetching {url}: {str(e)}")
            continue
    
    logging.warning(f"❌ Could not find geometry for: {street_name}")
    logging.debug(f"   Tried slugs: {', '.join(slug_variants)}")
    return None

def enrich_street_from_kayan(street_id, street_name, dry_run=False):
    """
    Enrich a single street with geometry from kayan.ru
    
    Returns:
        bool: Success status
    """
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
        
        # Fetch from kayan.ru
        result = fetch_street_from_kayan(street_name)
        
        if not result:
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
    """Main parsing process"""
    
    # Parse arguments
    dry_run = '--dry-run' in sys.argv
    limit = None
    
    for arg in sys.argv:
        if arg.startswith('--limit='):
            limit = int(arg.split('=')[1])
    
    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be saved to database\n")
    
    session = get_db_connection()
    
    # Get streets without geometry from kayan
    query = """
        SELECT id, name 
        FROM streets 
        WHERE geometry IS NULL OR geometry_source != 'kayan'
        ORDER BY name
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    streets = session.execute(text(query)).fetchall()
    session.close()
    
    total = len(streets)
    logging.info(f"📊 Found {total} streets to process from kayan.ru")
    
    if total == 0:
        logging.info("✅ All streets already have geometry from kayan!")
        return
    
    success_count = 0
    failed_count = 0
    
    for idx, street in enumerate(streets, 1):
        street_id, street_name = street.id, street.name
        
        logging.info(f"\n[{idx}/{total}] Processing: {street_name}")
        
        success = enrich_street_from_kayan(street_id, street_name, dry_run)
        
        if success:
            success_count += 1
        else:
            failed_count += 1
        
        # Rate limiting
        if idx < total:
            time.sleep(REQUEST_DELAY)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"📊 KAYAN PARSING SUMMARY:")
    print(f"{'='*60}")
    print(f"✅ Success: {success_count}/{total} ({success_count*100//total if total > 0 else 0}%)")
    print(f"❌ Failed:  {failed_count}/{total}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
