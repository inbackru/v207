# Маппинг полей: excel_properties → Normalized Schema

## Структура нормализованных таблиц

```
Developer (developers)
    ↓
ResidentialComplex (residential_complexes)
    ↓
Building (buildings)
    ↓
Property (properties)
```

## Маппинг полей

### Property (Объекты недвижимости)

| excel_properties | Normalized Schema | Путь |
|-----------------|-------------------|------|
| `inner_id` | `properties.inner_id` | Direct |
| `price` | `properties.price` | Direct |
| `object_area` | `properties.area` | Direct |
| `object_rooms` | `properties.rooms` | Direct |
| `object_min_floor` | `properties.floor` | Direct |
| `object_max_floor` | `properties.total_floors` | Direct |
| `renovation_display_name` | `properties.renovation_type` | Direct |
| `photos` | `properties.gallery_images` | Direct |
| `address_display_name` | `properties.address` | Direct |
| `address_position_lat` | `properties.latitude` | Direct |
| `address_position_lon` | `properties.longitude` | Direct |
| `description` | `properties.description` | Direct |

### ResidentialComplex (Жилые комплексы)

| excel_properties | Normalized Schema | Путь |
|-----------------|-------------------|------|
| `complex_name` | `residential_complexes.name` | Via JOIN |
| `complex_id` | `properties.complex_id` → `residential_complexes.id` | Relationship |
| `complex_object_class_display_name` | `residential_complexes.object_class_display_name` | Via JOIN |
| `complex_building_end_build_year` | `residential_complexes.end_build_year` | Via JOIN |
| `complex_building_end_build_quarter` | `residential_complexes.end_build_quarter` | Via JOIN |
| `complex_has_big_check` | `residential_complexes.has_big_check` | Via JOIN |
| `complex_financing_sber` | `residential_complexes.financing_sber` | Via JOIN |
| `complex_has_green_mortgage` | `residential_complexes.has_green_mortgage` | Via JOIN |
| `cashback_rate` | `residential_complexes.cashback_rate` | Via JOIN |

### Developer (Застройщики)

| excel_properties | Normalized Schema | Путь |
|-----------------|-------------------|------|
| `developer_name` | `developers.name` | Via JOIN |
| `developer_id` | `properties.developer_id` → `developers.id` | Relationship |

### District (Районы)

| excel_properties | Normalized Schema | Путь |
|-----------------|-------------------|------|
| `address_locality_name` | `districts.name` | Via JOIN |
| `district_id` | `properties.district_id` → `districts.id` | Relationship |

## SQL JOIN Pattern

### Полный запрос с JOIN

```sql
SELECT 
    -- Property fields
    p.inner_id,
    p.price,
    p.area,
    p.rooms,
    p.floor,
    p.total_floors,
    p.address,
    p.renovation_type,
    p.gallery_images as photos,
    p.latitude,
    p.longitude,
    p.description,
    
    -- ResidentialComplex fields
    rc.name as complex_name,
    rc.object_class_display_name,
    rc.end_build_year,
    rc.end_build_quarter,
    rc.has_big_check,
    rc.financing_sber,
    rc.has_green_mortgage,
    COALESCE(rc.cashback_rate, 5.0) as cashback_rate,
    
    -- Developer fields
    d.name as developer_name,
    
    -- District fields
    dist.name as district_name

FROM properties p
LEFT JOIN residential_complexes rc ON p.complex_id = rc.id
LEFT JOIN developers d ON p.developer_id = d.id
LEFT JOIN districts dist ON p.district_id = dist.id

WHERE p.inner_id = :property_id
```

## Эндпоинты для миграции

1. ✅ `manager_get_favorites_list()` - строка ~11395
2. ✅ `manager_toggle_complex_favorite()` - строка ~11625  
3. ✅ `admin_complex_cashback()` - строка ~13122
4. ✅ `fetch_pdf_context()` - строка ~15680

## Примечания

- **Фотографии**: В excel_properties хранятся в поле `photos`, в normalized - в `properties.gallery_images`
- **Кэшбек**: Теперь управляется через `residential_complexes.cashback_rate` в админке
- **Координаты**: Перенесены на уровень Property для точного расположения квартиры
