"""
Модуль для получения близлежащих объектов через OpenStreetMap Overpass API
"""
import requests
import json
import math
from datetime import datetime
from typing import Dict, List, Tuple, Optional


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """
    Вычислить расстояние между двумя точками (Haversine formula)
    Возвращает расстояние в метрах
    """
    R = 6371000  # Радиус Земли в метрах
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    distance = R * c
    return int(distance)


def fetch_nearby_places(latitude: float, longitude: float, radius_meters: int = 2000) -> Dict:
    """
    Получить близлежащие объекты через OpenStreetMap Overpass API
    
    Args:
        latitude: Широта ЖК
        longitude: Долгота ЖК
        radius_meters: Радиус поиска в метрах (по умолчанию 3000м = 3км)
    
    Returns:
        Dict с категориями близлежащих объектов
    """
    
    # Категории для поиска с OSM тегами и русские названия
    categories_config = {
        'transport': [
            ('highway', 'bus_stop', 'bus_stop', 'Остановка автобуса'),
            ('railway', 'tram_stop', 'tram_stop', 'Остановка трамвая'),
            ('railway', 'station', 'railway_station', 'Ж/д станция'),
            ('station', 'subway', 'metro_station', 'Станция метро'),
            ('amenity', 'bus_station', 'bus_station', 'Автовокзал'),
        ],
        'shopping': [
            ('shop', 'mall', 'mall', 'Торговый центр'),
            ('shop', 'supermarket', 'supermarket', 'Супермаркет'),
            ('shop', 'department_store', 'department_store', 'Универмаг'),
            ('shop', 'convenience', 'convenience', 'Магазин у дома'),
            ('amenity', 'marketplace', 'marketplace', 'Рынок'),
        ],
        'education': [
            ('amenity', 'kindergarten', 'kindergarten', 'Детский сад'),
            ('amenity', 'school', 'school', 'Школа'),
            ('amenity', 'university', 'university', 'Университет'),
            ('amenity', 'college', 'college', 'Колледж'),
        ],
        'healthcare': [
            ('amenity', 'hospital', 'hospital', 'Больница'),
            ('amenity', 'clinic', 'clinic', 'Поликлиника'),
            ('amenity', 'pharmacy', 'pharmacy', 'Аптека'),
            ('amenity', 'doctors', 'doctors', 'Медцентр'),
        ],
        'sport': [
            ('leisure', 'sports_centre', 'sports_centre', 'Спортивный центр'),
            ('leisure', 'fitness_centre', 'fitness_centre', 'Фитнес-клуб'),
            ('leisure', 'swimming_pool', 'swimming_pool', 'Бассейн'),
            ('leisure', 'stadium', 'stadium', 'Стадион'),
            ('sport', 'swimming', 'swimming_pool', 'Бассейн'),
        ],
        'leisure': [
            ('leisure', 'park', 'park', 'Парк'),
            ('leisure', 'playground', 'playground', 'Детская площадка'),
            ('tourism', 'attraction', 'attraction', 'Достопримечательность'),
            ('tourism', 'museum', 'museum', 'Музей'),
            ('amenity', 'cinema', 'cinema', 'Кинотеатр'),
            ('amenity', 'theatre', 'theatre', 'Театр'),
            ('amenity', 'arts_centre', 'arts_centre', 'Культурный центр'),
        ],
    }
    
    result = {}
    
    # Используем батч-запросы для каждой категории (быстрее и меньше ошибок)
    for category, tags_list in categories_config.items():
        category_places = []
        
        try:
            # Один батч-запрос для всей категории
            places = _query_overpass_batch(latitude, longitude, radius_meters, tags_list)
            
            for place in places:
                distance = calculate_distance(latitude, longitude, place['lat'], place['lon'])
                
                # ВАЖНО: пропускаем объекты без названия
                place_name = place.get('name')
                if not place_name:
                    continue
                
                # Фильтруем неправильно категоризированные объекты
                # Проверяем теги объекта для исключения образовательных/медицинских учреждений из досуга
                place_tags = place.get('tags', {})
                if category == 'leisure':
                    # Исключаем школы, детские сады, больницы из категории "Досуг"
                    amenity_tag = place_tags.get('amenity', '')
                    if amenity_tag in ['school', 'kindergarten', 'university', 'college', 'hospital', 'clinic', 'doctors']:
                        continue
                
                if distance <= radius_meters:
                    category_places.append({
                        'type': place['type'],
                        'type_display': place['type_display'],
                        'name': place_name,
                        'distance': distance,
                        'coordinates': [place['lat'], place['lon']]
                    })
                    
        except Exception as e:
            print(f"Error fetching {category}: {e}")
            import traceback
            traceback.print_exc()
        
        # ДЕДУПЛИКАЦИЯ: удаляем дубли по имени (оставляем ближайший)
        seen_names = {}
        deduplicated_places = []
        for place in category_places:
            name = place['name']
            if name not in seen_names or place['distance'] < seen_names[name]['distance']:
                if name in seen_names:
                    # Удаляем старый дубликат из списка
                    deduplicated_places = [p for p in deduplicated_places if p['name'] != name]
                seen_names[name] = place
                deduplicated_places.append(place)
        
        # Сортируем по расстоянию и берем топ-5 ближайших
        deduplicated_places.sort(key=lambda x: x['distance'])
        result[category] = deduplicated_places[:5]
    
    # Добавляем метку времени обновления
    result['updated_at'] = datetime.utcnow().isoformat()
    
    return result


def _query_overpass_batch(lat: float, lon: float, radius: int, tags_list: List[Tuple]) -> List[Dict]:
    """
    Выполнить батч-запрос к Overpass API для нескольких тегов одновременно
    
    Args:
        lat: Широта центральной точки
        lon: Долгота центральной точки
        radius: Радиус поиска в метрах
        tags_list: Список кортежей (osm_key, osm_value, place_type, type_display)
    
    Returns:
        Список найденных объектов с типами
    """
    
    # Используем альтернативный инстанс для лучшей стабильности
    overpass_url = "https://overpass.kumi.systems/api/interpreter"
    
    # Собираем все условия в один запрос
    node_conditions = []
    way_conditions = []
    
    for osm_key, osm_value, _, _ in tags_list:
        node_conditions.append(f'node["{osm_key}"="{osm_value}"](around:{radius},{lat},{lon});')
        way_conditions.append(f'way["{osm_key}"="{osm_value}"](around:{radius},{lat},{lon});')
    
    # Объединенный запрос
    overpass_query = f"""
    [out:json][timeout:90];
    (
      {''.join(node_conditions)}
      {''.join(way_conditions)}
    );
    out center;
    """
    
    try:
        response = requests.post(
            overpass_url,
            data={'data': overpass_query},
            timeout=120,
            headers={'User-Agent': 'InBack.ru Real Estate Service'}
        )
        
        if response.status_code == 200:
            data = response.json()
            places = []
            
            # Создаем маппинг тегов для определения типа
            tag_mapping = {(osm_key, osm_value): (place_type, type_display) 
                          for osm_key, osm_value, place_type, type_display in tags_list}
            
            for element in data.get('elements', []):
                # Получаем координаты
                if element['type'] == 'node':
                    place_lat = element.get('lat')
                    place_lon = element.get('lon')
                elif element['type'] == 'way' and 'center' in element:
                    place_lat = element['center'].get('lat')
                    place_lon = element['center'].get('lon')
                else:
                    continue
                
                # Определяем тип объекта по тегам
                tags = element.get('tags', {})
                place_type = None
                type_display = None
                
                for osm_key, osm_value in tag_mapping.keys():
                    if tags.get(osm_key) == osm_value:
                        place_type, type_display = tag_mapping[(osm_key, osm_value)]
                        break
                
                if not place_type:
                    continue
                
                places.append({
                    'lat': place_lat,
                    'lon': place_lon,
                    'name': element.get('tags', {}).get('name', element.get('tags', {}).get('name:ru')),
                    'type': place_type,
                    'type_display': type_display,
                    'tags': element.get('tags', {})  # Сохраняем все теги для дополнительной фильтрации
                })
            
            return places
        else:
            print(f"Overpass API error: {response.status_code}")
            return []
    
    except requests.exceptions.Timeout:
        print("Overpass API timeout")
        return []
    except requests.exceptions.RequestException as e:
        print(f"Overpass API request error: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"Overpass API JSON decode error: {e}")
        return []


def format_nearby_display_name(place_type: str, lang: str = 'ru') -> str:
    """
    Получить читаемое название типа места
    
    Args:
        place_type: Тип места (например, 'bus_stop')
        lang: Язык ('ru' или 'en')
    
    Returns:
        Читаемое название
    """
    
    translations_ru = {
        'bus_stop': 'Автобусная остановка',
        'railway_station': 'Ж/д станция',
        'tram_stop': 'Трамвайная остановка',
        'bus_station': 'Автовокзал',
        'mall': 'ТЦ',
        'supermarket': 'Супермаркет',
        'department_store': 'Универмаг',
        'kindergarten': 'Детский сад',
        'school': 'Школа',
        'university': 'ВУЗ',
        'college': 'Колледж',
        'hospital': 'Больница',
        'clinic': 'Поликлиника',
        'pharmacy': 'Аптека',
        'doctors': 'Врач',
        'park': 'Парк',
        'sports_centre': 'Спортивный центр',
        'fitness_centre': 'Фитнес-центр',
        'stadium': 'Стадион',
    }
    
    if lang == 'ru':
        return translations_ru.get(place_type, place_type.replace('_', ' ').title())
    
    return place_type.replace('_', ' ').title()


def format_distance(distance_meters: int) -> str:
    """
    Форматировать расстояние для отображения
    
    Args:
        distance_meters: Расстояние в метрах
    
    Returns:
        Отформатированная строка (например, "200 м" или "1.2 км")
    """
    if distance_meters < 1000:
        return f"{distance_meters} м"
    else:
        km = distance_meters / 1000
        return f"{km:.1f} км"


# Пример использования:
if __name__ == "__main__":
    # Координаты ЖК Отражение в Краснодаре (примерные)
    test_lat = 45.0355
    test_lon = 38.9753
    
    print("Тестируем получение близлежащих объектов...")
    nearby_data = fetch_nearby_places(test_lat, test_lon, radius_meters=3000)
    
    print(json.dumps(nearby_data, ensure_ascii=False, indent=2))
