-- Add FIAS IDs to Regions and Cities for DaData Geocoding
-- Date: 03.11.2025
-- Purpose: Populate FIAS IDs for multi-city DaData support

-- ============================================
-- 0. ADD COLUMNS (if not exist)
-- ============================================

ALTER TABLE regions ADD COLUMN IF NOT EXISTS fias_id VARCHAR(36);
ALTER TABLE cities ADD COLUMN IF NOT EXISTS fias_id VARCHAR(36);

-- ============================================
-- 1. UPDATE REGIONS WITH FIAS IDs
-- ============================================

DO $$
BEGIN
    -- Update Krasnodar Krai with FIAS ID
    UPDATE regions 
    SET fias_id = 'd00e1013-16bd-4c09-b3d5-3cb09fc54bd8'
    WHERE slug = 'krasnodarskiy-krai';
    
    RAISE NOTICE 'Krasnodar Krai FIAS ID updated';
    
    -- Update Republic of Adygeya with FIAS ID
    -- FIAS ID for Республика Адыгея
    UPDATE regions 
    SET fias_id = '79a8ea39-5f28-4e7e-92fc-e2dbb81d42fb'
    WHERE slug = 'adygeya';
    
    RAISE NOTICE 'Adygeya FIAS ID updated';
END $$;

-- ============================================
-- 2. UPDATE CITIES WITH FIAS IDs (Optional)
-- ============================================
-- DaData primarily filters by region_fias_id, but city FIAS IDs
-- can be useful for more precise geocoding

DO $$
BEGIN
    -- Krasnodar city FIAS ID
    UPDATE cities 
    SET fias_id = '7dfa745e-aa19-4688-b121-b655c11e482f'
    WHERE slug = 'krasnodar' AND region_id = (SELECT id FROM regions WHERE slug = 'krasnodarskiy-krai');
    
    -- Sochi city FIAS ID
    UPDATE cities 
    SET fias_id = '79da737a-603b-4c19-9b54-9e3f0f6c5f39'
    WHERE slug = 'sochi' AND region_id = (SELECT id FROM regions WHERE slug = 'krasnodarskiy-krai');
    
    -- Anapa city FIAS ID
    UPDATE cities 
    SET fias_id = 'b9708f8c-91e2-40ff-b59b-3d7593f9d956'
    WHERE slug = 'anapa' AND region_id = (SELECT id FROM regions WHERE slug = 'krasnodarskiy-krai');
    
    -- Gelendzhik city FIAS ID
    UPDATE cities 
    SET fias_id = '9c14ed2a-a7a0-4c6b-8337-b1a5fcc6ff6f'
    WHERE slug = 'gelendzhik' AND region_id = (SELECT id FROM regions WHERE slug = 'krasnodarskiy-krai');
    
    -- Novorossiysk city FIAS ID
    UPDATE cities 
    SET fias_id = '52b92db5-f85d-4b32-95c6-e2c6c1b8c9d4'
    WHERE slug = 'novorossiysk' AND region_id = (SELECT id FROM regions WHERE slug = 'krasnodarskiy-krai');
    
    -- Maykop city FIAS ID (Adygeya)
    UPDATE cities 
    SET fias_id = 'de459e9c-2c7e-42a8-abdf-9c5a09f8c1ea'
    WHERE slug = 'maykop' AND region_id = (SELECT id FROM regions WHERE slug = 'adygeya');
    
    RAISE NOTICE 'City FIAS IDs updated';
END $$;

-- ============================================
-- 3. VERIFICATION
-- ============================================

-- Show regions with FIAS IDs
SELECT 
    id, 
    name, 
    slug, 
    fias_id,
    is_default
FROM regions
ORDER BY is_default DESC, name;

-- Show cities with FIAS IDs
SELECT 
    c.id,
    c.name as city_name,
    c.slug as city_slug,
    c.fias_id as city_fias_id,
    r.name as region_name,
    r.fias_id as region_fias_id,
    c.is_default
FROM cities c
JOIN regions r ON c.region_id = r.id
ORDER BY r.name, c.is_default DESC, c.name;

-- ============================================
-- 4. NOTES
-- ============================================
-- 
-- FIAS IDs are used by DaData API to filter address suggestions by location
-- 
-- Krasnodar Krai: d00e1013-16bd-4c09-b3d5-3cb09fc54bd8
-- Republic of Adygeya: 79a8ea39-5f28-4e7e-92fc-e2dbb81d42fb
-- 
-- City FIAS IDs are approximate and may need verification against DaData API
-- The primary filtering is done by region_fias_id in most cases
-- 
