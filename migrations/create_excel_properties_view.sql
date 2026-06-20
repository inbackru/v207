-- =====================================================
-- CREATE VIEW: excel_properties
-- Цель: Обратная совместимость после нормализации БД
-- Эмулирует старую таблицу excel_properties через JOIN normalized tables
-- =====================================================

-- Переименовываем оригинальную таблицу в backup
ALTER TABLE excel_properties RENAME TO excel_properties_old;

-- Создаем VIEW с тем же именем
CREATE OR REPLACE VIEW excel_properties AS
SELECT 
    -- Property основные поля (используем LEGACY значения!)
    p.inner_id::BIGINT as inner_id,
    p.url,
    p.gallery_images as photos,
    
    -- Address поля (из properties)
    NULL::integer as address_id,
    NULL::varchar(50) as address_guid,
    NULL::varchar(50) as address_kind,
    NULL::text as address_name,
    NULL::text as address_subways,
    NULL::integer as address_locality_id,
    NULL::varchar(50) as address_locality_kind,
    NULL::varchar(200) as address_locality_name,
    NULL::varchar(50) as address_locality_subkind,
    NULL::text as address_locality_display_name,
    p.latitude as address_position_lat,
    p.longitude as address_position_lon,
    p.address as address_display_name,
    p.address as address_short_display_name,
    
    -- Complex поля (из residential_complexes) - используем LEGACY значения!
    rc.complex_id::BIGINT as complex_id,
    rc.name as complex_name,
    rc.complex_phone as complex_phone,
    rc.main_image as complex_image,
    rc.gallery_images as complex_gallery_images,
    rc.latitude as complex_latitude,
    rc.longitude as complex_longitude,
    rc.address as complex_address,
    rc.description as complex_description,
    NULL::integer as complex_building_id,
    p.complex_building_name,  -- FIXED: Now pulling from properties table
    NULL::boolean as complex_building_released,
    NULL::boolean as complex_building_is_unsafe,
    rc.has_accreditation as complex_building_accreditation,
    rc.end_build_year as complex_building_end_build_year,
    NULL::boolean as complex_building_complex_product,
    rc.end_build_quarter as complex_building_end_build_quarter,
    rc.has_green_mortgage as complex_building_has_green_mortgage,
    NULL::integer as complex_min_rate,
    rc.sales_phone as complex_sales_phone,
    rc.sales_address as complex_sales_address,
    rc.object_class_id as complex_object_class_id,
    rc.object_class_display_name as complex_object_class_display_name,
    rc.has_big_check as complex_has_big_check,
    rc.end_build_year as complex_end_build_year,
    rc.financing_sber as complex_financing_sber,
    NULL::bigint as complex_telephony_b_number,
    NULL::bigint as complex_telephony_r_number,
    rc.with_renovation as complex_with_renovation,
    rc.first_build_year as complex_first_build_year,
    rc.start_build_year as complex_start_build_year,
    rc.end_build_quarter as complex_end_build_quarter,
    rc.has_accreditation as complex_has_accreditation,
    NULL::boolean as complex_has_approve_flats,
    NULL::boolean as complex_mortgage_tranches,
    rc.has_green_mortgage as complex_has_green_mortgage,
    NULL::bigint as complex_phone_substitution,
    NULL::boolean as complex_show_contact_block,
    rc.first_build_quarter as complex_first_build_quarter,
    rc.start_build_quarter as complex_start_build_quarter,
    NULL::boolean as complex_has_mortgage_subsidy,
    NULL::boolean as complex_has_government_program,
    
    -- Property pricing and details
    NULL::integer as min_rate,
    NULL::boolean as trade_in,
    p.deal_type,
    
    -- Developer поля (из developers) - legacy ID из excel_properties_old
    (SELECT developer_id FROM excel_properties_old WHERE inner_id = p.inner_id::BIGINT LIMIT 1) as developer_id,
    d.name as developer_name,
    NULL::integer as region_id,
    NULL::integer as city_id,
    'Краснодарский край'::varchar(200) as parsed_region,
    'Краснодар'::varchar(100) as parsed_city,
    NULL::varchar(200) as parsed_district,
    d.website as developer_site,
    NULL::integer as developer_holding_id,
    
    -- Property details
    NULL::boolean as is_auction,
    p.price,
    p.price as max_price,
    p.price as min_price,
    p.price_per_sqm as square_price,
    p.mortgage_price,
    p.renovation_type,
    NULL::varchar(100) as renovation_display_name,
    p.description,
    p.area as object_area,
    p.rooms as object_rooms,
    p.total_floors as object_max_floor,
    p.floor as object_current_floor,
    p.floor as object_min_floor,
    p.total_floors as object_floor,
    NULL::varchar(50) as object_type,
    NULL::varchar(100) as object_type_display_name,
    p.is_apartment as object_is_apartment,
    NULL::varchar(50) as placement_type,
    
    -- Additional fields
    p.created_at as parsed_at,
    p.updated_at as last_updated,
    p.is_active,
    
    -- Cashback (из residential_complexes)
    rc.cashback_rate

FROM properties p
LEFT JOIN residential_complexes rc ON p.complex_id = rc.id
LEFT JOIN developers d ON p.developer_id = d.id;

-- Создаем индексы для производительности VIEW
CREATE INDEX IF NOT EXISTS idx_properties_complex_id ON properties(complex_id);
CREATE INDEX IF NOT EXISTS idx_properties_developer_id ON properties(developer_id);
CREATE INDEX IF NOT EXISTS idx_properties_price ON properties(price);
CREATE INDEX IF NOT EXISTS idx_properties_area ON properties(area);
CREATE INDEX IF NOT EXISTS idx_properties_rooms ON properties(rooms);

-- Проверка VIEW
SELECT 
    'VIEW СОЗДАН' as status,
    COUNT(*) as records,
    COUNT(DISTINCT complex_id) as complexes,
    COUNT(DISTINCT developer_id) as developers
FROM excel_properties;

SELECT '✅ VIEW excel_properties готов к работе!' as message;
