-- Multi-City Migration: Add city_id to Districts and Streets
-- Date: 03.11.2025
-- Purpose: Normalize District and Street models with City foreign keys

-- ============================================
-- 1. ADD CITY_ID TO DISTRICTS
-- ============================================

-- Step 1.1: Add city_id column (nullable for migration)
ALTER TABLE districts 
ADD COLUMN IF NOT EXISTS city_id INTEGER REFERENCES cities(id);

-- Step 1.2: Set city_id = 1 (Краснодар) for all existing districts
UPDATE districts 
SET city_id = 1 
WHERE city_id IS NULL;

-- Step 1.3: Make city_id NOT NULL after migration
ALTER TABLE districts 
ALTER COLUMN city_id SET NOT NULL;

-- Step 1.4: Drop old UNIQUE constraint on slug (if exists)
ALTER TABLE districts 
DROP CONSTRAINT IF EXISTS districts_slug_key;

-- Step 1.5: Add new UNIQUE constraint (city_id, slug)
ALTER TABLE districts 
ADD CONSTRAINT unique_district_slug_per_city UNIQUE (city_id, slug);

SELECT 'Districts migration completed' AS status;

-- ============================================
-- 2. ADD CITY_ID TO STREETS  
-- ============================================

-- Step 2.1: Add city_id column (nullable for migration)
ALTER TABLE streets 
ADD COLUMN IF NOT EXISTS city_id INTEGER REFERENCES cities(id);

-- Step 2.2: Set city_id = 1 (Краснодар) for all existing streets
UPDATE streets 
SET city_id = 1 
WHERE city_id IS NULL;

-- Step 2.3: Make city_id NOT NULL after migration
ALTER TABLE streets 
ALTER COLUMN city_id SET NOT NULL;

-- Step 2.4: Drop old UNIQUE constraint on slug (if exists)
ALTER TABLE streets 
DROP CONSTRAINT IF EXISTS streets_slug_key;

-- Step 2.5: Add new UNIQUE constraint (city_id, slug)
ALTER TABLE streets 
ADD CONSTRAINT unique_street_slug_per_city UNIQUE (city_id, slug);

SELECT 'Streets migration completed' AS status;

-- ============================================
-- 3. VERIFICATION
-- ============================================

-- Show districts with their cities
SELECT 
    d.id,
    d.name as district_name,
    d.slug as district_slug,
    c.name as city_name
FROM districts d
LEFT JOIN cities c ON d.city_id = c.id
ORDER BY c.name, d.name
LIMIT 10;

-- Show streets with their cities
SELECT 
    s.id,
    s.name as street_name,
    s.slug as street_slug,
    c.name as city_name,
    d.name as district_name
FROM streets s
LEFT JOIN cities c ON s.city_id = c.id
LEFT JOIN districts d ON s.district_id = d.id
ORDER BY c.name, s.name
LIMIT 10;

-- Count districts and streets per city
SELECT 
    c.name as city_name,
    COUNT(DISTINCT d.id) as districts_count,
    COUNT(DISTINCT s.id) as streets_count
FROM cities c
LEFT JOIN districts d ON d.city_id = c.id
LEFT JOIN streets s ON s.city_id = c.id
GROUP BY c.id, c.name
ORDER BY c.name;
