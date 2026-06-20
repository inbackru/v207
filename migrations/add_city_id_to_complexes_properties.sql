-- Multi-City Migration: Add city_id to ResidentialComplexes and Properties
-- Date: 03.11.2025
-- Purpose: Complete multi-city support for core property data

-- ============================================
-- 1. ADD CITY_ID TO RESIDENTIAL_COMPLEXES
-- ============================================

-- Step 1.1: Add city_id column (nullable for migration)
ALTER TABLE residential_complexes 
ADD COLUMN IF NOT EXISTS city_id INTEGER REFERENCES cities(id);

-- Step 1.2: Set city_id based on coordinates (intelligent migration)
-- Sochi bounding box: lat 43.4-43.9, lon 39.4-40.0
UPDATE residential_complexes 
SET city_id = 2  -- Sochi
WHERE city_id IS NULL 
  AND latitude BETWEEN 43.4 AND 43.9 
  AND longitude BETWEEN 39.4 AND 40.0;

-- Default to Krasnodar for remaining complexes
UPDATE residential_complexes 
SET city_id = 1  -- Krasnodar
WHERE city_id IS NULL;

-- Step 1.3: Make city_id NOT NULL after migration
ALTER TABLE residential_complexes 
ALTER COLUMN city_id SET NOT NULL;

-- Step 1.4: Drop old UNIQUE constraint on slug (if exists)
ALTER TABLE residential_complexes 
DROP CONSTRAINT IF EXISTS residential_complexes_slug_key;

-- Step 1.5: Add new UNIQUE constraint (city_id, slug)
ALTER TABLE residential_complexes 
ADD CONSTRAINT unique_complex_slug_per_city UNIQUE (city_id, slug);

SELECT 'ResidentialComplexes migration completed' AS status;

-- ============================================
-- 2. ADD CITY_ID TO PROPERTIES
-- ============================================

-- Step 2.1: Add city_id column (nullable for migration)
ALTER TABLE properties 
ADD COLUMN IF NOT EXISTS city_id INTEGER REFERENCES cities(id);

-- Step 2.2: Set city_id based on parsed_city and coordinates (intelligent migration)
-- First: Use parsed_city if available
UPDATE properties 
SET city_id = 2  -- Sochi
WHERE city_id IS NULL 
  AND (parsed_city = 'Сочи' OR parsed_city LIKE '%Дагомыс%');

-- Second: Use coordinates for properties without parsed_city
-- Sochi bounding box: lat 43.4-43.9, lon 39.4-40.0
UPDATE properties 
SET city_id = 2  -- Sochi
WHERE city_id IS NULL 
  AND latitude BETWEEN 43.4 AND 43.9 
  AND longitude BETWEEN 39.4 AND 40.0;

-- Default to Krasnodar for remaining properties
-- Note: parsed_city field remains as legacy/debugging field
UPDATE properties 
SET city_id = 1  -- Krasnodar
WHERE city_id IS NULL;

-- Step 2.3: Make city_id NOT NULL after migration
ALTER TABLE properties 
ALTER COLUMN city_id SET NOT NULL;

-- Step 2.4: Drop old UNIQUE constraint on slug (if exists)
ALTER TABLE properties 
DROP CONSTRAINT IF EXISTS properties_slug_key;

-- Step 2.5: Add new UNIQUE constraint (city_id, slug) for properties with slugs
ALTER TABLE properties 
ADD CONSTRAINT unique_property_slug_per_city UNIQUE (city_id, slug);

SELECT 'Properties migration completed' AS status;

-- ============================================
-- 3. VERIFICATION
-- ============================================

-- Show residential complexes with their cities
SELECT 
    c.name as city_name,
    COUNT(rc.id) as complexes_count,
    STRING_AGG(rc.name, ', ' ORDER BY rc.name) as complexes
FROM cities c
LEFT JOIN residential_complexes rc ON rc.city_id = c.id
GROUP BY c.id, c.name
ORDER BY c.name
LIMIT 10;

-- Show properties per city
SELECT 
    c.name as city_name,
    COUNT(p.id) as properties_count,
    COUNT(DISTINCT p.complex_id) as complexes_with_properties,
    MIN(p.price) as min_price,
    MAX(p.price) as max_price
FROM cities c
LEFT JOIN properties p ON p.city_id = c.id
GROUP BY c.id, c.name
ORDER BY c.name;

-- Verify parsed_city vs city_id alignment (should all be Краснодар)
SELECT 
    p.parsed_city,
    c.name as city_name,
    COUNT(*) as count
FROM properties p
JOIN cities c ON p.city_id = c.id
GROUP BY p.parsed_city, c.name
ORDER BY count DESC
LIMIT 10;
