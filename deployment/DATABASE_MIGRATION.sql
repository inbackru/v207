-- =====================================================
-- InBack Database Migration Scripts
-- =====================================================
-- Используйте эти скрипты для экспорта/импорта данных
-- =====================================================

-- ============================================
-- 1. ЭКСПОРТ ДАННЫХ
-- ============================================

-- Экспорт всех районов (с геометрией)
COPY (
    SELECT id, name, name_en, description, polygon_coordinates, 
           latitude, longitude, zoom_level, created_at
    FROM district
    ORDER BY id
) TO '/tmp/districts_export.csv' CSV HEADER;

-- Экспорт всех улиц (с координатами)
COPY (
    SELECT id, name, district_id, latitude, longitude, created_at
    FROM street
    ORDER BY district_id, name
) TO '/tmp/streets_export.csv' CSV HEADER;

-- Экспорт всех жилых комплексов
COPY (
    SELECT id, name, developer_id, address, district_id, 
           latitude, longitude, description, image_url,
           completion_date, total_buildings, created_at
    FROM residential_complex
    ORDER BY name
) TO '/tmp/complexes_export.csv' CSV HEADER;

-- Экспорт всех объектов недвижимости
COPY (
    SELECT id, title, price, area, rooms, floor, total_floors,
           complex_id, developer_id, district_id, street_id,
           address, latitude, longitude, description, image_url,
           cashback_amount, created_at
    FROM property
    ORDER BY created_at DESC
) TO '/tmp/properties_export.csv' CSV HEADER;

-- Экспорт IT компаний (для IT-ипотеки)
COPY (
    SELECT id, name, inn, created_at
    FROM it_company
    ORDER BY name
) TO '/tmp/it_companies_export.csv' CSV HEADER;

-- Экспорт застройщиков
COPY (
    SELECT id, name, description, logo_url, website, rating, created_at
    FROM developer
    ORDER BY name
) TO '/tmp/developers_export.csv' CSV HEADER;

-- ============================================
-- 2. ИМПОРТ ДАННЫХ
-- ============================================

-- Импорт районов
COPY district(id, name, name_en, description, polygon_coordinates, 
              latitude, longitude, zoom_level, created_at)
FROM '/tmp/districts_export.csv' CSV HEADER;

-- Импорт улиц
COPY street(id, name, district_id, latitude, longitude, created_at)
FROM '/tmp/streets_export.csv' CSV HEADER;

-- Импорт жилых комплексов
COPY residential_complex(id, name, developer_id, address, district_id,
                         latitude, longitude, description, image_url,
                         completion_date, total_buildings, created_at)
FROM '/tmp/complexes_export.csv' CSV HEADER;

-- Импорт объектов недвижимости
COPY property(id, title, price, area, rooms, floor, total_floors,
              complex_id, developer_id, district_id, street_id,
              address, latitude, longitude, description, image_url,
              cashback_amount, created_at)
FROM '/tmp/properties_export.csv' CSV HEADER;

-- Импорт IT компаний
COPY it_company(id, name, inn, created_at)
FROM '/tmp/it_companies_export.csv' CSV HEADER;

-- Импорт застройщиков
COPY developer(id, name, description, logo_url, website, rating, created_at)
FROM '/tmp/developers_export.csv' CSV HEADER;

-- ============================================
-- 3. ПОЛНЫЙ БЭКАП БАЗЫ ДАННЫХ
-- ============================================

-- Выполните в командной строке (Replit Shell или локальный терминал):

-- Экспорт всей базы (схема + данные)
-- pg_dump $DATABASE_URL > /tmp/inback_full_backup.sql

-- Экспорт только схемы (структура таблиц)
-- pg_dump $DATABASE_URL --schema-only > /tmp/inback_schema.sql

-- Экспорт только данных (без структуры)
-- pg_dump $DATABASE_URL --data-only > /tmp/inback_data.sql

-- Экспорт с сжатием (экономия места)
-- pg_dump $DATABASE_URL --format=custom > /tmp/inback_backup.dump

-- ============================================
-- 4. ВОССТАНОВЛЕНИЕ ИЗ БЭКАПА
-- ============================================

-- Восстановление из SQL файла
-- psql $DATABASE_URL < /tmp/inback_full_backup.sql

-- Восстановление с очисткой существующих данных
-- psql $DATABASE_URL < /tmp/inback_full_backup.sql --clean

-- Восстановление из сжатого архива
-- pg_restore --dbname=$DATABASE_URL /tmp/inback_backup.dump

-- ============================================
-- 5. ПОЛЕЗНЫЕ ЗАПРОСЫ ДЛЯ ПРОВЕРКИ
-- ============================================

-- Количество записей в каждой таблице
SELECT 
    'Районы' as table_name, COUNT(*) as records FROM district
UNION ALL
SELECT 'Улицы', COUNT(*) FROM street
UNION ALL
SELECT 'Жилые комплексы', COUNT(*) FROM residential_complex
UNION ALL
SELECT 'Объекты недвижимости', COUNT(*) FROM property
UNION ALL
SELECT 'Застройщики', COUNT(*) FROM developer
UNION ALL
SELECT 'IT компании', COUNT(*) FROM it_company
UNION ALL
SELECT 'Пользователи', COUNT(*) FROM "user"
UNION ALL
SELECT 'Заявки', COUNT(*) FROM application;

-- Проверка районов с геометрией
SELECT 
    name,
    CASE 
        WHEN polygon_coordinates IS NOT NULL THEN 'Polygon'
        WHEN latitude IS NOT NULL THEN 'Point'
        ELSE 'No geometry'
    END as geometry_type
FROM district
ORDER BY name;

-- Проверка улиц с координатами
SELECT 
    d.name as district,
    COUNT(s.id) as streets_count,
    COUNT(s.latitude) as streets_with_coords
FROM district d
LEFT JOIN street s ON d.id = s.district_id
GROUP BY d.name
ORDER BY streets_count DESC;

-- Статистика по объектам недвижимости
SELECT 
    d.name as district,
    COUNT(p.id) as properties_count,
    AVG(p.price) as avg_price,
    AVG(p.cashback_amount) as avg_cashback
FROM district d
LEFT JOIN property p ON d.id = p.district_id
GROUP BY d.name
ORDER BY properties_count DESC;

-- ============================================
-- 6. ОЧИСТКА ДАННЫХ (ОСТОРОЖНО!)
-- ============================================

-- Очистить все заявки (безопасно - не влияет на основные данные)
-- TRUNCATE TABLE application CASCADE;

-- Очистить все объекты недвижимости (ОСТОРОЖНО!)
-- TRUNCATE TABLE property CASCADE;

-- Полная очистка БД (ОПАСНО! Удалит все данные!)
-- DROP SCHEMA public CASCADE;
-- CREATE SCHEMA public;

-- ============================================
-- 7. СБРОС АВТОИНКРЕМЕНТА (SERIAL)
-- ============================================

-- После импорта данных с ID нужно обновить sequence

-- Для таблицы district
SELECT setval('district_id_seq', (SELECT MAX(id) FROM district));

-- Для таблицы street
SELECT setval('street_id_seq', (SELECT MAX(id) FROM street));

-- Для таблицы property
SELECT setval('property_id_seq', (SELECT MAX(id) FROM property));

-- Для таблицы residential_complex
SELECT setval('residential_complex_id_seq', (SELECT MAX(id) FROM residential_complex));

-- Для таблицы developer
SELECT setval('developer_id_seq', (SELECT MAX(id) FROM developer));

-- Для таблицы it_company
SELECT setval('it_company_id_seq', (SELECT MAX(id) FROM it_company));

-- ============================================
-- 8. СОЗДАНИЕ ИНДЕКСОВ ДЛЯ ПРОИЗВОДИТЕЛЬНОСТИ
-- ============================================

-- Индексы для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_property_district ON property(district_id);
CREATE INDEX IF NOT EXISTS idx_property_complex ON property(complex_id);
CREATE INDEX IF NOT EXISTS idx_property_price ON property(price);
CREATE INDEX IF NOT EXISTS idx_property_rooms ON property(rooms);
CREATE INDEX IF NOT EXISTS idx_street_district ON street(district_id);
CREATE INDEX IF NOT EXISTS idx_it_company_inn ON it_company(inn);

-- Индекс для полнотекстового поиска (опционально)
-- CREATE INDEX idx_property_search ON property USING gin(to_tsvector('russian', title || ' ' || COALESCE(description, '')));

-- ============================================
-- ПРИМЕЧАНИЯ
-- ============================================
-- 
-- 1. Все пути /tmp/ на Replit доступны только во время сессии
-- 2. Для постоянного хранения используйте папку проекта
-- 3. На Replit используйте $DATABASE_URL вместо полных credentials
-- 4. Локально замените $DATABASE_URL на: postgresql://user:pass@host:port/db
-- 5. Всегда делайте бэкап перед миграцией!
-- 
-- ============================================
