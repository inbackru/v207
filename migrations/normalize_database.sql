-- =====================================================
-- МИГРАЦИЯ: Нормализация excel_properties
-- Цель: Разделить данные на developers → residential_complexes → properties
-- Автор: InBack Database Migration
-- Дата: 2025-10-21
-- =====================================================

-- =====================================================
-- ФАЗА 0: Подготовка - Backup и Staging таблицы
-- =====================================================

BEGIN;

-- Backup исходной таблицы (на случай rollback)
DROP TABLE IF EXISTS excel_properties_backup;
CREATE TABLE excel_properties_backup AS SELECT * FROM excel_properties;

-- Очистка целевых таблиц (если есть данные)
TRUNCATE TABLE properties CASCADE;
TRUNCATE TABLE residential_complexes CASCADE;
TRUNCATE TABLE developers CASCADE;

-- Создание staging таблиц для промежуточных данных
DROP TABLE IF EXISTS stg_developers;
CREATE TABLE stg_developers AS
SELECT DISTINCT
    developer_id as legacy_developer_id,
    TRIM(developer_name) as name,
    developer_site as website,
    developer_holding_id as holding_id
FROM excel_properties
WHERE developer_name IS NOT NULL;

DROP TABLE IF EXISTS stg_complexes;
CREATE TABLE stg_complexes AS
SELECT DISTINCT ON (complex_id)
    complex_id as legacy_complex_id,
    developer_id as legacy_developer_id,
    TRIM(complex_name) as name,
    complex_phone as phone,
    complex_sales_phone as sales_phone,
    complex_sales_address as sales_address,
    complex_object_class_id as object_class_id,
    complex_object_class_display_name as object_class_display_name,
    complex_start_build_year as start_build_year,
    complex_start_build_quarter as start_build_quarter,
    complex_first_build_year as first_build_year,
    complex_first_build_quarter as first_build_quarter,
    complex_end_build_year as end_build_year,
    complex_end_build_quarter as end_build_quarter,
    complex_has_accreditation as has_accreditation,
    complex_has_green_mortgage as has_green_mortgage,
    complex_has_big_check as has_big_check,
    complex_with_renovation as with_renovation,
    complex_financing_sber as financing_sber,
    address_display_name as address,
    address_position_lat as latitude,
    address_position_lon as longitude
FROM excel_properties
WHERE complex_name IS NOT NULL
ORDER BY complex_id, inner_id;

DROP TABLE IF EXISTS stg_properties;
CREATE TABLE stg_properties AS
SELECT
    inner_id as legacy_inner_id,
    complex_id as legacy_complex_id,
    url,
    photos as gallery_images,
    object_area as area,
    object_rooms as rooms,
    object_max_floor as total_floors,
    price,
    min_price,
    max_price,
    square_price as price_per_sqm,
    mortgage_price,
    renovation_type,
    renovation_display_name,
    description,
    deal_type,
    trade_in,
    is_auction,
    address_display_name as address,
    address_position_lat as latitude,
    address_position_lon as longitude
FROM excel_properties;

-- Создание mapping таблиц для связи старых и новых ID
DROP TABLE IF EXISTS map_developer_ids;
CREATE TABLE map_developer_ids (
    legacy_developer_id BIGINT,
    new_developer_id INTEGER
);

DROP TABLE IF EXISTS map_complex_ids;
CREATE TABLE map_complex_ids (
    legacy_complex_id BIGINT,
    new_complex_id INTEGER
);

DROP TABLE IF EXISTS map_property_ids;
CREATE TABLE map_property_ids (
    legacy_inner_id BIGINT,
    new_property_id INTEGER
);

-- Проверка подготовки
SELECT 
    'STAGING ГОТОВ' as status,
    (SELECT COUNT(*) FROM stg_developers) as developers_staged,
    (SELECT COUNT(*) FROM stg_complexes) as complexes_staged,
    (SELECT COUNT(*) FROM stg_properties) as properties_staged;

COMMIT;

-- =====================================================
-- ФАЗА 1: Миграция Застройщиков (developers)
-- =====================================================

BEGIN;

-- Вставка застройщиков с генерацией slug
INSERT INTO developers (name, slug, full_name, website, is_active, created_at, updated_at)
SELECT 
    name,
    lower(regexp_replace(
        regexp_replace(name, '[^a-zA-Zа-яА-ЯёЁ0-9\s-]', '', 'g'),
        '\s+', '-', 'g'
    )),
    name as full_name,
    website,
    true as is_active,
    NOW() as created_at,
    NOW() as updated_at
FROM stg_developers
ON CONFLICT DO NOTHING;

-- Заполнение mapping таблицы
INSERT INTO map_developer_ids (legacy_developer_id, new_developer_id)
SELECT 
    sd.legacy_developer_id,
    d.id
FROM stg_developers sd
JOIN developers d ON TRIM(d.name) = TRIM(sd.name);

-- Проверка фазы 1
SELECT 
    'ФАЗА 1 ЗАВЕРШЕНА' as status,
    (SELECT COUNT(*) FROM developers) as developers_count,
    (SELECT COUNT(*) FROM map_developer_ids) as mapped_count;

COMMIT;

-- =====================================================
-- ФАЗА 2: Миграция Жилых Комплексов (residential_complexes)
-- =====================================================

BEGIN;

-- Вставка ЖК с привязкой к застройщикам
INSERT INTO residential_complexes (
    name, slug, developer_id, complex_id, complex_phone, sales_phone, sales_address,
    object_class_id, object_class_display_name,
    start_build_year, start_build_quarter,
    first_build_year, first_build_quarter,
    end_build_year, end_build_quarter,
    has_accreditation, has_green_mortgage, has_big_check,
    with_renovation, financing_sber,
    cashback_rate,
    is_active, created_at, updated_at
)
SELECT 
    sc.name,
    lower(regexp_replace(
        regexp_replace(sc.name, '[^a-zA-Zа-яА-ЯёЁ0-9\s-]', '', 'g'),
        '\s+', '-', 'g'
    )),
    md.new_developer_id,
    sc.legacy_complex_id::VARCHAR,
    sc.phone,
    sc.sales_phone,
    sc.sales_address,
    sc.object_class_id::VARCHAR,
    sc.object_class_display_name,
    sc.start_build_year,
    sc.start_build_quarter,
    sc.first_build_year,
    sc.first_build_quarter,
    sc.end_build_year,
    sc.end_build_quarter,
    sc.has_accreditation,
    sc.has_green_mortgage,
    sc.has_big_check,
    sc.with_renovation,
    sc.financing_sber,
    3.5 as cashback_rate,
    true as is_active,
    NOW() as created_at,
    NOW() as updated_at
FROM stg_complexes sc
LEFT JOIN map_developer_ids md ON sc.legacy_developer_id = md.legacy_developer_id
ON CONFLICT DO NOTHING;

-- Заполнение mapping таблицы
INSERT INTO map_complex_ids (legacy_complex_id, new_complex_id)
SELECT 
    sc.legacy_complex_id,
    rc.id
FROM stg_complexes sc
JOIN residential_complexes rc ON rc.complex_id = sc.legacy_complex_id::VARCHAR;

-- Проверка фазы 2
SELECT 
    'ФАЗА 2 ЗАВЕРШЕНА' as status,
    (SELECT COUNT(*) FROM residential_complexes) as complexes_count,
    (SELECT COUNT(*) FROM map_complex_ids) as mapped_count;

COMMIT;

-- =====================================================
-- ФАЗА 3: Миграция Квартир (properties)
-- =====================================================

BEGIN;

-- Вставка квартир с привязкой к ЖК
INSERT INTO properties (
    title, inner_id, url, gallery_images,
    area, rooms, total_floors,
    price, price_per_sqm, mortgage_price,
    renovation_type, description, deal_type,
    address, latitude, longitude,
    complex_id, developer_id,
    is_active, created_at, updated_at
)
SELECT 
    CONCAT(
        COALESCE(sp.rooms || '-комн. ', 'Квартира '),
        COALESCE(sp.area || ' м², ', ''),
        COALESCE(rc.name, 'ЖК')
    ) as title,
    sp.legacy_inner_id::VARCHAR,
    sp.url,
    sp.gallery_images,
    sp.area,
    sp.rooms,
    sp.total_floors,
    COALESCE(sp.price, sp.min_price) as price,
    sp.price_per_sqm,
    sp.mortgage_price,
    sp.renovation_type,
    sp.description,
    sp.deal_type,
    sp.address,
    sp.latitude::DOUBLE PRECISION,
    sp.longitude::DOUBLE PRECISION,
    mc.new_complex_id,
    rc.developer_id,
    true as is_active,
    NOW() as created_at,
    NOW() as updated_at
FROM stg_properties sp
LEFT JOIN map_complex_ids mc ON sp.legacy_complex_id = mc.legacy_complex_id
LEFT JOIN residential_complexes rc ON rc.id = mc.new_complex_id
ON CONFLICT DO NOTHING;

-- Заполнение mapping таблицы
INSERT INTO map_property_ids (legacy_inner_id, new_property_id)
SELECT 
    sp.legacy_inner_id,
    p.id
FROM stg_properties sp
JOIN properties p ON p.inner_id = sp.legacy_inner_id::VARCHAR;

-- Проверка фазы 3
SELECT 
    'ФАЗА 3 ЗАВЕРШЕНА' as status,
    (SELECT COUNT(*) FROM properties) as properties_count,
    (SELECT COUNT(*) FROM map_property_ids) as mapped_count;

COMMIT;

-- =====================================================
-- ФАЗА 4: Добавление Foreign Key Constraints
-- =====================================================

BEGIN;

-- FK: residential_complexes.developer_id → developers.id
ALTER TABLE residential_complexes 
DROP CONSTRAINT IF EXISTS fk_complex_developer;

ALTER TABLE residential_complexes
ADD CONSTRAINT fk_complex_developer 
FOREIGN KEY (developer_id) REFERENCES developers(id) ON DELETE CASCADE;

-- FK: properties.complex_id → residential_complexes.id
ALTER TABLE properties
DROP CONSTRAINT IF EXISTS fk_property_complex;

ALTER TABLE properties
ADD CONSTRAINT fk_property_complex
FOREIGN KEY (complex_id) REFERENCES residential_complexes(id) ON DELETE CASCADE;

-- FK: properties.developer_id → developers.id
ALTER TABLE properties
DROP CONSTRAINT IF EXISTS fk_property_developer;

ALTER TABLE properties
ADD CONSTRAINT fk_property_developer
FOREIGN KEY (developer_id) REFERENCES developers(id) ON DELETE CASCADE;

-- Создание индексов для производительности
CREATE INDEX IF NOT EXISTS idx_complex_developer ON residential_complexes(developer_id);
CREATE INDEX IF NOT EXISTS idx_property_complex ON properties(complex_id);
CREATE INDEX IF NOT EXISTS idx_property_developer ON properties(developer_id);

SELECT 'FOREIGN KEYS СОЗДАНЫ' as status;

COMMIT;

-- =====================================================
-- ФАЗА 5: Проверка целостности данных
-- =====================================================

-- Итоговая статистика
SELECT 
    'МИГРАЦИЯ ЗАВЕРШЕНА' as status,
    (SELECT COUNT(*) FROM developers) as developers_migrated,
    (SELECT COUNT(*) FROM residential_complexes) as complexes_migrated,
    (SELECT COUNT(*) FROM properties) as properties_migrated,
    (SELECT COUNT(*) FROM excel_properties) as source_records;

-- Проверка связей
SELECT 
    'ПРОВЕРКА FK' as check_type,
    COUNT(*) as orphaned_complexes
FROM residential_complexes rc
WHERE developer_id IS NOT NULL 
  AND NOT EXISTS (SELECT 1 FROM developers d WHERE d.id = rc.developer_id);

SELECT 
    'ПРОВЕРКА FK' as check_type,
    COUNT(*) as orphaned_properties
FROM properties p
WHERE complex_id IS NOT NULL 
  AND NOT EXISTS (SELECT 1 FROM residential_complexes rc WHERE rc.id = p.complex_id);

-- Spot-check: примеры данных
SELECT 
    d.name as developer,
    rc.name as complex,
    COUNT(p.id) as properties_count
FROM developers d
LEFT JOIN residential_complexes rc ON rc.developer_id = d.id
LEFT JOIN properties p ON p.complex_id = rc.id
GROUP BY d.name, rc.name
ORDER BY d.name, rc.name;

-- =====================================================
-- ЗАВЕРШЕНИЕ
-- =====================================================

-- Очистка staging таблиц (опционально, можно оставить для анализа)
-- DROP TABLE IF EXISTS stg_developers;
-- DROP TABLE IF EXISTS stg_complexes;
-- DROP TABLE IF EXISTS stg_properties;

-- Сохраняем mapping таблицы для использования в приложении
-- DROP TABLE IF EXISTS map_developer_ids;
-- DROP TABLE IF EXISTS map_complex_ids;
-- DROP TABLE IF EXISTS map_property_ids;

SELECT '✅ МИГРАЦИЯ УСПЕШНО ЗАВЕРШЕНА!' as final_status;
