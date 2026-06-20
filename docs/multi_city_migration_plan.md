# Multi-City/Multi-Region Migration Plan

## Дата: 03.11.2025
## Цель: Масштабирование системы для работы с Краснодаром, Сочи, Анапой, Геленджиком и Республикой Адыгея

---

## 1. Текущее состояние базы данных

### ✅ Уже реализовано:
- **Region → City иерархия существует**
  - `Region` модель с `cities` relationship
  - `City` модель с `region_id` foreign key
  - Unique constraint: `(region_id, name)` и `(region_id, slug)`
  
### ❌ Отсутствует:
- **City → District связь**: District НЕ имеет `city_id`
- **City → Street связь**: Street НЕ имеет `city_id`
- **City → Property связь**: Property имеет только текстовое поле `parsed_city`, без foreign key
- **City → ResidentialComplex связь**: ResidentialComplex НЕ имеет `city_id`

### 🔴 Критические проблемы:
1. `District.slug` имеет UNIQUE constraint без учета города → одинаковые названия районов в разных городах конфликтуют
2. `Street.slug` имеет UNIQUE constraint без учета города → одинаковые названия улиц конфликтуют
3. Все модели жестко привязаны к Краснодару через docstrings и defaults

---

## 2. План миграции базы данных

### Шаг 1: Добавить city_id в District
```python
class District(db.Model):
    """Districts within cities"""  # ← Обновить docstring
    __tablename__ = 'districts'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), nullable=False)
    
    # NEW: Foreign key to City
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    city = db.relationship('City', backref='districts')
    
    # Остальные поля...
    
    # UPDATED: Уникальность slug в пределах города
    __table_args__ = (
        db.UniqueConstraint('city_id', 'slug', name='unique_district_slug_per_city'),
        {'extend_existing': True}
    )
```

### Шаг 2: Добавить city_id в Street
```python
class Street(db.Model):
    """Streets within cities"""  # ← Обновить docstring
    __tablename__ = 'streets'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), nullable=False)
    
    # NEW: Foreign key to City
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    city = db.relationship('City', backref='streets')
    
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'))
    district = db.relationship('District', backref='streets')
    
    # Остальные поля...
    
    # UPDATED: Уникальность slug в пределах города
    __table_args__ = (
        db.UniqueConstraint('city_id', 'slug', name='unique_street_slug_per_city'),
        {'extend_existing': True}
    )
```

### Шаг 3: Добавить city_id в ResidentialComplex
```python
class ResidentialComplex(db.Model):
    """Residential complexes"""
    __tablename__ = 'residential_complexes'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), nullable=False, unique=True)
    
    # NEW: Foreign key to City
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=True)  # Nullable для миграции
    city = db.relationship('City', backref='residential_complexes')
    
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'))
    developer_id = db.Column(db.Integer, db.ForeignKey('developers.id'))
    
    # Relationships
    city = db.relationship('City', backref='residential_complexes')
    district = db.relationship('District', backref='complexes')
    developer = db.relationship('Developer', backref='complexes')
```

### Шаг 4: Добавить city_id в Property
```python
class Property(db.Model):
    """Property/Apartment model"""
    __tablename__ = 'properties'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # NEW: Foreign key to City (в дополнение к parsed_city)
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=True)  # Nullable для миграции
    
    # Existing parsed fields (keep for backwards compatibility)
    parsed_city = db.Column(db.String(100), nullable=True)
    parsed_district = db.Column(db.String(100), nullable=True)
    
    # Foreign keys
    developer_id = db.Column(db.Integer, db.ForeignKey('developers.id'), nullable=True)
    complex_id = db.Column(db.Integer, db.ForeignKey('residential_complexes.id'), nullable=True)
    building_id = db.Column(db.Integer, db.ForeignKey('buildings.id'), nullable=True)
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=True)
    
    # Relationships
    city = db.relationship('City', backref='properties')
    developer = db.relationship('Developer', backref='properties')
    residential_complex = db.relationship('ResidentialComplex', backref='properties', foreign_keys=[complex_id])
    district = db.relationship('District', backref='properties')
```

---

## 3. Миграция существующих данных

### SQL скрипт для миграции:

```sql
-- 1. Создать регионы
INSERT INTO regions (name, slug, latitude, longitude, is_active, is_default) VALUES
('Краснодарский край', 'krasnodarskiy-krai', 45.0355, 38.9753, true, true),
('Республика Адыгея', 'adygeya', 44.6087, 40.1006, true, false);

-- 2. Создать города
INSERT INTO cities (name, slug, region_id, latitude, longitude, is_active, is_default) VALUES
-- Краснодарский край (region_id = 1)
('Краснодар', 'krasnodar', 1, 45.0355, 38.9753, true, true),
('Сочи', 'sochi', 1, 43.5855, 39.7231, true, false),
('Анапа', 'anapa', 1, 44.8951, 37.3167, true, false),
('Геленджик', 'gelendzhik', 1, 44.5619, 38.0775, true, false),
('Новороссийск', 'novorossiysk', 1, 44.7243, 37.7686, true, false),
-- Республика Адыгея (region_id = 2)
('Майкоп', 'maykop', 2, 44.6087, 40.1006, true, true);

-- 3. Добавить city_id в districts (сначала добавить колонку как nullable)
ALTER TABLE districts ADD COLUMN city_id INTEGER REFERENCES cities(id);

-- 4. Установить city_id = 1 (Краснодар) для всех существующих районов
UPDATE districts SET city_id = 1 WHERE city_id IS NULL;

-- 5. Сделать city_id NOT NULL
ALTER TABLE districts ALTER COLUMN city_id SET NOT NULL;

-- 6. Удалить старый UNIQUE constraint на slug
ALTER TABLE districts DROP CONSTRAINT IF EXISTS districts_slug_key;

-- 7. Добавить новый UNIQUE constraint (city_id, slug)
ALTER TABLE districts ADD CONSTRAINT unique_district_slug_per_city UNIQUE (city_id, slug);

-- 8. То же самое для streets
ALTER TABLE streets ADD COLUMN city_id INTEGER REFERENCES cities(id);
UPDATE streets SET city_id = 1 WHERE city_id IS NULL;
ALTER TABLE streets ALTER COLUMN city_id SET NOT NULL;
ALTER TABLE streets DROP CONSTRAINT IF EXISTS streets_slug_key;
ALTER TABLE streets ADD CONSTRAINT unique_street_slug_per_city UNIQUE (city_id, slug);

-- 9. Добавить city_id в residential_complexes (оставить nullable)
ALTER TABLE residential_complexes ADD COLUMN city_id INTEGER REFERENCES cities(id);
UPDATE residential_complexes SET city_id = 1 WHERE city_id IS NULL;

-- 10. Добавить city_id в properties (оставить nullable)
ALTER TABLE properties ADD COLUMN city_id INTEGER REFERENCES cities(id);

-- 11. Установить city_id на основе parsed_city
UPDATE properties 
SET city_id = CASE 
    WHEN parsed_city = 'Краснодар' THEN 1
    WHEN parsed_city = 'Сочи' THEN 2
    WHEN parsed_city = 'Анапа' THEN 3
    WHEN parsed_city = 'Геленджик' THEN 4
    WHEN parsed_city = 'Новороссийск' THEN 5
    WHEN parsed_city = 'Майкоп' THEN 6
    ELSE 1  -- Default to Краснодар
END
WHERE city_id IS NULL;
```

---

## 4. DaData Integration

### Текущая проблема:
```python
# services/dadata_client.py:80
self.krasnodar_region_fias = "d00e1013-16bd-4c09-b3d5-3cb09fc54bd8"

# services/dadata_client.py:124-125
if locations is None:
    locations = [{"region_fias_id": self.krasnodar_region_fias}]
```

### Решение:
```python
class DaDataClient:
    def __init__(self):
        # Region FIAS IDs map
        self.region_fias_map = {
            'krasnodarskiy-krai': 'd00e1013-16bd-4c09-b3d5-3cb09fc54bd8',
            'adygeya': '8d3f1d35-f0f4-41b5-b5b7-e7cadf3e7bd7'
        }
        
        # Default region from environment or config
        default_region_slug = os.getenv('DEFAULT_REGION_SLUG', 'krasnodarskiy-krai')
        self.default_region_fias = self.region_fias_map.get(default_region_slug)
    
    def suggest_address(self, query: str, region_slug: Optional[str] = None, 
                       city: Optional[str] = None, ...):
        """
        Args:
            region_slug: Region slug to filter by (e.g., 'krasnodarskiy-krai', 'adygeya')
            city: City name to filter by (e.g., 'Сочи', 'Майкоп')
        """
        locations = None
        
        if city:
            # Filter by specific city
            locations = [{"city": city}]
        elif region_slug and region_slug in self.region_fias_map:
            # Filter by region FIAS ID
            locations = [{"region_fias_id": self.region_fias_map[region_slug]}]
        elif self.default_region_fias:
            # Use default region
            locations = [{"region_fias_id": self.default_region_fias}]
```

---

## 5. Удаление Hardcoded "Краснодар"

### Места для замены (найдено 40+ вхождений):

1. **app.py:724** - Default city в парсинге
2. **app.py:1276** - District fallback
3. **app.py:2657** - Complex district fallback
4. **app.py:3062** - Complex detail district
5. **app.py:3128** - Default coordinates
6. **app.py:5314** - Geocoding fallback
7. **app.py:5627** - District name fallback

### Решение:
Использовать динамический default city из environment variable:

```python
# app.py или config.py
DEFAULT_CITY_ID = int(os.getenv('DEFAULT_CITY_ID', '1'))  # 1 = Краснодар

def get_default_city():
    """Get default city from database"""
    from models import City
    city = City.query.filter_by(is_default=True).first()
    if not city:
        city = City.query.get(DEFAULT_CITY_ID)
    return city

# Использование:
default_city = get_default_city()
'district': complex.district or default_city.name
coordinates = [default_city.latitude, default_city.longitude]
```

---

## 6. API Changes

### Новые endpoints:

```python
@app.route('/api/regions')
def get_regions():
    """Get all active regions"""
    regions = Region.query.filter_by(is_active=True).all()
    return jsonify([{
        'id': r.id,
        'name': r.name,
        'slug': r.slug
    } for r in regions])

@app.route('/api/regions/<region_slug>/cities')
def get_region_cities(region_slug):
    """Get cities in a region"""
    region = Region.query.filter_by(slug=region_slug).first_or_404()
    cities = City.query.filter_by(region_id=region.id, is_active=True).all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'slug': c.slug,
        'latitude': c.latitude,
        'longitude': c.longitude
    } for c in cities])

@app.route('/api/cities/<int:city_id>/districts')
def get_city_districts(city_id):
    """Get districts in a city"""
    city = City.query.get_or_404(city_id)
    districts = District.query.filter_by(city_id=city_id).all()
    return jsonify([{
        'id': d.id,
        'name': d.name,
        'slug': d.slug
    } for d in districts])
```

### Обновленный filter API:

```python
@app.route('/api/properties/filter')
def filter_properties():
    # NEW: Optional city_id parameter
    city_id = request.args.get('city_id', type=int)
    
    query = Property.query.filter_by(is_active=True)
    
    # Filter by city if provided
    if city_id:
        query = query.filter_by(city_id=city_id)
    
    # Filter by districts (validate they belong to selected city)
    district_ids = request.args.getlist('districts', type=int)
    if district_ids:
        if city_id:
            # Validate districts belong to city
            valid_districts = District.query.filter(
                District.id.in_(district_ids),
                District.city_id == city_id
            ).all()
            district_ids = [d.id for d in valid_districts]
        
        query = query.filter(Property.district_id.in_(district_ids))
```

---

## 7. UI Changes

### Добавить селектор региона/города:

```html
<!-- Фильтр на /properties странице -->
<div class="region-city-selector">
    <select id="region-select" class="form-control">
        <option value="">Все регионы</option>
        <option value="krasnodarskiy-krai" selected>Краснодарский край</option>
        <option value="adygeya">Республика Адыгея</option>
    </select>
    
    <select id="city-select" class="form-control">
        <option value="">Все города</option>
        <option value="1" selected>Краснодар</option>
        <option value="2">Сочи</option>
        <option value="3">Анапа</option>
        <option value="4">Геленджик</option>
        <option value="6">Майкоп</option>
    </select>
</div>
```

### JavaScript для динамической загрузки:

```javascript
document.getElementById('region-select').addEventListener('change', async (e) => {
    const regionSlug = e.target.value;
    
    if (!regionSlug) {
        loadAllCities();
        return;
    }
    
    const response = await fetch(`/api/regions/${regionSlug}/cities`);
    const cities = await response.json();
    
    const citySelect = document.getElementById('city-select');
    citySelect.innerHTML = '<option value="">Все города</option>';
    cities.forEach(city => {
        citySelect.innerHTML += `<option value="${city.id}">${city.name}</option>`;
    });
    
    // Reload districts for selected region
    loadDistrictsForRegion(regionSlug);
});
```

---

## 8. Map Updates

### Динамическое центрирование карты:

```javascript
function initMap(cityId = null) {
    let center, zoom;
    
    if (cityId) {
        // Fetch city coordinates
        fetch(`/api/cities/${cityId}`)
            .then(r => r.json())
            .then(city => {
                center = [city.latitude, city.longitude];
                zoom = city.zoom_level || 12;
                createMap(center, zoom);
            });
    } else {
        // Default to region center (Krasnodar)
        center = [45.0355, 38.9753];
        zoom = 8;
        createMap(center, zoom);
    }
}
```

---

## 9. Testing Plan

### Тестовые сценарии:

1. ✅ Создать объект в Сочи
2. ✅ Фильтрация по городу Сочи
3. ✅ Показ на карте объектов из Сочи и Краснодара одновременно
4. ✅ Поиск по адресу "Сочи, улица Мечтателей"
5. ✅ DaData suggestions для Майкопа
6. ✅ Одинаковые названия районов в разных городах (Центральный в Краснодаре и Сочи)
7. ✅ Валидация: нельзя выбрать район Сочи для объекта в Краснодаре

---

## 10. Rollout Strategy

### Фаза 1: Database Migration (1 день)
- Добавить city_id в District, Street
- Добавить city_id в Property, ResidentialComplex
- Мигрировать существующие данные
- Создать регионы и города

### Фаза 2: DaData Refactoring (0.5 дня)
- Убрать hardcoded krasnodar_region_fias
- Добавить region_fias_map
- Обновить suggest_address для multi-region

### Фаза 3: Backend Updates (1 день)
- Удалить hardcoded "Краснодар"
- Обновить API endpoints
- Добавить валидацию city → district

### Фаза 4: Frontend Updates (1 день)
- Добавить селектор региона/города
- Обновить карты
- Обновить фильтры

### Фаза 5: Testing & QA (0.5 дня)
- Тестирование всех сценариев
- Проверка миграции данных
- Load testing

**Total: 4 дня**

---

## 11. Environment Variables

Добавить в `.env`:

```bash
# Multi-Region Configuration
DEFAULT_REGION_SLUG=krasnodarskiy-krai
DEFAULT_CITY_ID=1

# DaData Region FIAS IDs
KRASNODAR_KRAI_FIAS=d00e1013-16bd-4c09-b3d5-3cb09fc54bd8
ADYGEYA_FIAS=8d3f1d35-f0f4-41b5-b5b7-e7cadf3e7bd7
```

---

## 12. Rollback Plan

Если что-то пойдет не так:

```sql
-- 1. Удалить city_id из всех таблиц
ALTER TABLE districts DROP COLUMN city_id;
ALTER TABLE streets DROP COLUMN city_id;
ALTER TABLE residential_complexes DROP COLUMN city_id;
ALTER TABLE properties DROP COLUMN city_id;

-- 2. Восстановить старые UNIQUE constraints
ALTER TABLE districts ADD CONSTRAINT districts_slug_key UNIQUE (slug);
ALTER TABLE streets ADD CONSTRAINT streets_slug_key UNIQUE (slug);
```

---

## Статус: ✅ План готов
Следующий шаг: Начать с Фазы 1 - Database Migration
