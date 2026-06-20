-- Multi-City Migration: Add Regions and Cities
-- Date: 03.11.2025
-- Purpose: Add Krasnodar Krai, Adygeya region and their cities

-- ============================================
-- 1. CREATE REGIONS
-- ============================================

-- Check if regions table exists and is empty before inserting
DO $$
BEGIN
    -- Insert Krasnodar Krai
    INSERT INTO regions (name, slug, latitude, longitude, zoom_level, is_active, is_default, created_at, updated_at)
    VALUES (
        'Краснодарский край',
        'krasnodarskiy-krai',
        45.0355,
        38.9753,
        8,
        true,
        true,
        NOW(),
        NOW()
    )
    ON CONFLICT (name) DO NOTHING;
    
    -- Insert Republic of Adygeya
    INSERT INTO regions (name, slug, latitude, longitude, zoom_level, is_active, is_default, created_at, updated_at)
    VALUES (
        'Республика Адыгея',
        'adygeya',
        44.6087,
        40.1006,
        8,
        true,
        false,
        NOW(),
        NOW()
    )
    ON CONFLICT (name) DO NOTHING;
    
    RAISE NOTICE 'Regions inserted successfully';
END $$;

-- ============================================
-- 2. CREATE CITIES
-- ============================================

DO $$
DECLARE
    krasnodar_region_id INTEGER;
    adygeya_region_id INTEGER;
BEGIN
    -- Get region IDs
    SELECT id INTO krasnodar_region_id FROM regions WHERE slug = 'krasnodarskiy-krai';
    SELECT id INTO adygeya_region_id FROM regions WHERE slug = 'adygeya';
    
    -- Insert cities in Krasnodar Krai
    
    -- 1. Krasnodar (default city)
    INSERT INTO cities (name, slug, region_id, latitude, longitude, zoom_level, is_active, is_default, created_at, updated_at)
    VALUES (
        'Краснодар',
        'krasnodar',
        krasnodar_region_id,
        45.0355,
        38.9753,
        12,
        true,
        true,
        NOW(),
        NOW()
    )
    ON CONFLICT ON CONSTRAINT unique_city_per_region DO NOTHING;
    
    -- 2. Sochi
    INSERT INTO cities (name, slug, region_id, latitude, longitude, zoom_level, is_active, is_default, created_at, updated_at)
    VALUES (
        'Сочи',
        'sochi',
        krasnodar_region_id,
        43.5855,
        39.7231,
        12,
        true,
        false,
        NOW(),
        NOW()
    )
    ON CONFLICT ON CONSTRAINT unique_city_per_region DO NOTHING;
    
    -- 3. Anapa
    INSERT INTO cities (name, slug, region_id, latitude, longitude, zoom_level, is_active, is_default, created_at, updated_at)
    VALUES (
        'Анапа',
        'anapa',
        krasnodar_region_id,
        44.8951,
        37.3167,
        13,
        true,
        false,
        NOW(),
        NOW()
    )
    ON CONFLICT ON CONSTRAINT unique_city_per_region DO NOTHING;
    
    -- 4. Gelendzhik
    INSERT INTO cities (name, slug, region_id, latitude, longitude, zoom_level, is_active, is_default, created_at, updated_at)
    VALUES (
        'Геленджик',
        'gelendzhik',
        krasnodar_region_id,
        44.5619,
        38.0775,
        13,
        true,
        false,
        NOW(),
        NOW()
    )
    ON CONFLICT ON CONSTRAINT unique_city_per_region DO NOTHING;
    
    -- 5. Novorossiysk
    INSERT INTO cities (name, slug, region_id, latitude, longitude, zoom_level, is_active, is_default, created_at, updated_at)
    VALUES (
        'Новороссийск',
        'novorossiysk',
        krasnodar_region_id,
        44.7243,
        37.7686,
        12,
        true,
        false,
        NOW(),
        NOW()
    )
    ON CONFLICT ON CONSTRAINT unique_city_per_region DO NOTHING;
    
    -- 6. Armavir
    INSERT INTO cities (name, slug, region_id, latitude, longitude, zoom_level, is_active, is_default, created_at, updated_at)
    VALUES (
        'Армавир',
        'armavir',
        krasnodar_region_id,
        45.0000,
        41.1237,
        13,
        true,
        false,
        NOW(),
        NOW()
    )
    ON CONFLICT ON CONSTRAINT unique_city_per_region DO NOTHING;
    
    -- 7. Tuapse
    INSERT INTO cities (name, slug, region_id, latitude, longitude, zoom_level, is_active, is_default, created_at, updated_at)
    VALUES (
        'Туапсе',
        'tuapse',
        krasnodar_region_id,
        44.1014,
        39.0758,
        13,
        true,
        false,
        NOW(),
        NOW()
    )
    ON CONFLICT ON CONSTRAINT unique_city_per_region DO NOTHING;
    
    -- Insert city in Republic of Adygeya
    
    -- 8. Maykop (capital of Adygeya)
    INSERT INTO cities (name, slug, region_id, latitude, longitude, zoom_level, is_active, is_default, created_at, updated_at)
    VALUES (
        'Майкоп',
        'maykop',
        adygeya_region_id,
        44.6087,
        40.1006,
        12,
        true,
        true,  -- Default city for Adygeya region
        NOW(),
        NOW()
    )
    ON CONFLICT ON CONSTRAINT unique_city_per_region DO NOTHING;
    
    RAISE NOTICE 'Cities inserted successfully';
END $$;

-- ============================================
-- 3. VERIFICATION
-- ============================================

-- Show created regions
SELECT 
    id, 
    name, 
    slug, 
    is_default,
    ROUND(latitude::numeric, 4) as lat,
    ROUND(longitude::numeric, 4) as lon
FROM regions
ORDER BY is_default DESC, name;

-- Show created cities
SELECT 
    c.id,
    c.name as city_name,
    c.slug as city_slug,
    r.name as region_name,
    c.is_default,
    ROUND(c.latitude::numeric, 4) as lat,
    ROUND(c.longitude::numeric, 4) as lon
FROM cities c
JOIN regions r ON c.region_id = r.id
ORDER BY r.name, c.is_default DESC, c.name;
