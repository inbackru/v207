#!/usr/bin/env python3
"""
Обогащение координат улиц через Yandex Geocoder API
Получает координаты для улиц без данных
"""
import os
import time
import requests
from app import app, db
from sqlalchemy import text

YANDEX_API_KEY = os.environ.get('YANDEX_MAPS_API_KEY')
GEOCODER_URL = 'https://geocode-maps.yandex.ru/1.x/'

def geocode_street(street_name, city="Краснодар"):
    """Получить координаты улицы через Yandex Geocoder"""
    
    if not YANDEX_API_KEY:
        print("❌ YANDEX_MAPS_API_KEY не найден в переменных окружения")
        return None
    
    # Формируем полный адрес
    full_address = f"Россия, Краснодарский край, {city}, {street_name}"
    
    params = {
        'apikey': YANDEX_API_KEY,
        'geocode': full_address,
        'format': 'json',
        'results': 1,
        'kind': 'street'  # Указываем что ищем именно улицу
    }
    
    try:
        response = requests.get(GEOCODER_URL, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Извлекаем координаты
        try:
            geo_object = data['response']['GeoObjectCollection']['featureMember'][0]['GeoObject']
            coords = geo_object['Point']['pos'].split()
            
            # Yandex возвращает longitude, latitude (в обратном порядке!)
            longitude = float(coords[0])
            latitude = float(coords[1])
            
            # Проверяем что координаты действительно в Краснодаре
            # Краснодар: примерно 45.0 ± 0.2, 38.9 ± 0.3
            if not (44.8 <= latitude <= 45.2 and 38.6 <= longitude <= 39.3):
                print(f"  ⚠️  Координаты вне Краснодара: {latitude:.6f}, {longitude:.6f}")
                return None
            
            return {
                'latitude': latitude,
                'longitude': longitude,
                'address': geo_object.get('metaDataProperty', {}).get('GeocoderMetaData', {}).get('text', full_address)
            }
        except (KeyError, IndexError) as e:
            print(f"  ⚠️  Координаты не найдены для: {full_address}")
            return None
            
    except requests.RequestException as e:
        print(f"  ❌ Ошибка запроса для {full_address}: {e}")
        return None

def enrich_streets():
    """Обогатить улицы координатами"""
    
    print(f"\n{'='*60}")
    print(f"🗺️  ОБОГАЩЕНИЕ КООРДИНАТ УЛИЦ (Yandex Geocoder)")
    print(f"{'='*60}\n")
    
    with app.app_context():
        # Получаем улицы без координат
        streets = db.session.execute(text("""
            SELECT id, name, slug 
            FROM streets 
            WHERE latitude IS NULL OR longitude IS NULL
            ORDER BY id
        """)).fetchall()
        
        total = len(streets)
        print(f"📍 Улиц без координат: {total}\n")
        
        if total == 0:
            print("✅ Все улицы уже имеют координаты!")
            return
        
        enriched = 0
        not_found = 0
        errors = 0
        
        print("🚀 Начинаю обогащение...\n")
        
        for idx, street in enumerate(streets, 1):
            street_id = street[0]
            street_name = street[1]
            
            print(f"[{idx}/{total}] {street_name}...", end=" ")
            
            # Получаем координаты
            result = geocode_street(street_name)
            
            if result:
                # Обновляем БД
                try:
                    db.session.execute(text("""
                        UPDATE streets 
                        SET latitude = :lat, longitude = :lon
                        WHERE id = :id
                    """), {
                        'lat': result['latitude'],
                        'lon': result['longitude'],
                        'id': street_id
                    })
                    db.session.commit()
                    
                    print(f"✅ ({result['latitude']:.6f}, {result['longitude']:.6f})")
                    enriched += 1
                    
                except Exception as e:
                    print(f"❌ Ошибка БД: {e}")
                    errors += 1
                    db.session.rollback()
            else:
                print("⚠️  Не найдено")
                not_found += 1
            
            # Задержка между запросами (rate limiting)
            if idx < total:
                time.sleep(0.2)  # 5 запросов в секунду
        
        # Итоговая статистика
        print(f"\n{'='*60}")
        print(f"📊 РЕЗУЛЬТАТЫ")
        print(f"{'='*60}")
        print(f"✅ Обогащено: {enriched}")
        print(f"⚠️  Не найдено: {not_found}")
        print(f"❌ Ошибок: {errors}")
        
        # Проверяем финальное состояние
        total_streets = db.session.execute(text("SELECT COUNT(*) FROM streets")).scalar()
        with_coords = db.session.execute(text("SELECT COUNT(*) FROM streets WHERE latitude IS NOT NULL")).scalar()
        
        print(f"\n📍 Улиц с координатами: {with_coords}/{total_streets} ({with_coords*100//total_streets}%)")
        print(f"{'='*60}\n")

if __name__ == '__main__':
    enrich_streets()
