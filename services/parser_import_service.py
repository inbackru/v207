"""
Универсальный сервис для импорта данных от парсера
Автоматически создаёт slug, устанавливает связи, обновляет существующие записи
"""

from app import db
from models import Developer, ResidentialComplex, Building, Property, City, District
from utils.transliteration import create_developer_slug, create_complex_slug, create_slug
from utils.address_parser import apply_parsed_address
from services.district_assignment import full_pipeline as _assign_district
from datetime import datetime
import logging
import os
import requests as _requests

logger = logging.getLogger(__name__)


class ParserImportService:
    """Сервис для импорта данных от парсера с автоматической обработкой"""
    
    @staticmethod
    def import_developer(data, auto_commit=True):
        """
        Импорт застройщика
        
        Args:
            data (dict): {
                'name': 'Название застройщика',
                'external_id': 'dev_123',  # ID из внешнего источника (опционально)
                'full_name': 'ООО "Застройщик"',
                'website': 'example.com',
                'phone': '+7 (XXX) XXX-XX-XX',
                'email': 'info@example.com',
                'address': 'г. Краснодар, ул. ...',
                'latitude': 45.035470,
                'longitude': 38.975313,
                'established_year': 2010,
                'description': 'Описание компании',
                'logo_url': 'https://...'
            }
            auto_commit (bool): Автоматически делать commit (по умолчанию True)
        
        Returns:
            Developer: Созданный или обновлённый застройщик
        """
        name = data.get('name')
        if not name:
            raise ValueError("Developer name is required")
        
        # Ищем существующего застройщика: сначала по external_id, потом по name
        developer = None
        if data.get('external_id'):
            developer = db.session.query(Developer).filter_by(external_id=data['external_id']).first()
        
        if not developer:
            developer = db.session.query(Developer).filter_by(name=name).first()
        
        # Автоматически создаём slug
        slug = create_developer_slug(name)
        
        if developer:
            # Обновляем существующего
            logger.info(f"Обновление застройщика: {name}")
            for key, value in data.items():
                if key != 'name' and hasattr(developer, key) and value is not None:
                    setattr(developer, key, value)
            developer.slug = slug
            developer.updated_at = datetime.utcnow()
        else:
            # Создаём нового
            logger.info(f"Создание застройщика: {name}")
            developer = Developer(
                name=name,
                slug=slug,
                external_id=data.get('external_id'),
                full_name=data.get('full_name'),
                website=data.get('website'),
                phone=data.get('phone'),
                email=data.get('email'),
                address=data.get('address'),
                latitude=data.get('latitude'),
                longitude=data.get('longitude'),
                established_year=data.get('established_year'),
                description=data.get('description'),
                logo_url=data.get('logo_url'),
                created_at=datetime.utcnow()
            )
            db.session.add(developer)
        
        if auto_commit:
            db.session.commit()
        return developer
    
    @staticmethod
    def import_residential_complex(data, developer_name=None, city_name='Краснодар', auto_commit=True):
        """
        Импорт жилого комплекса
        
        Args:
            data (dict): {
                'name': 'Название ЖК',
                'external_id': 'complex_456',  # ID из внешнего источника
                'address': 'ул. ...',
                'phone': '+7 (XXX) XXX-XX-XX',
                'latitude': 45.035470,
                'longitude': 38.975313,
                'description': 'Описание ЖК',
                'complex_type': 'residential',  # или 'cottage'
                'class_name': 'Комфорт',
                'images': ['url1', 'url2', ...]
            }
            developer_name (str): Название застройщика
            city_name (str): Название города (по умолчанию 'Краснодар')
            auto_commit (bool): Автоматически делать commit (по умолчанию True)
        
        Returns:
            ResidentialComplex: Созданный или обновлённый ЖК
        """
        name = data.get('name')
        if not name:
            raise ValueError("Residential complex name is required")
        
        # Находим город
        city = db.session.query(City).filter_by(name=city_name).first()
        if not city:
            raise ValueError(f"City '{city_name}' not found in database")
        
        # Находим застройщика
        developer = None
        if developer_name:
            developer = db.session.query(Developer).filter_by(name=developer_name).first()
            if not developer:
                logger.warning(f"Developer '{developer_name}' not found, creating ЖК without developer")
        
        # Ищем существующий ЖК: сначала по external_id, потом по name
        complex = None
        if data.get('external_id'):
            complex = db.session.query(ResidentialComplex).filter_by(
                complex_id=data['external_id']
            ).first()
        
        if not complex:
            complex = db.session.query(ResidentialComplex).filter_by(
                name=name,
                city_id=city.id
            ).first()
        
        # Автоматически создаём slug
        slug = create_complex_slug(name)
        
        if complex:
            # Обновляем существующий
            logger.info(f"Обновление ЖК: {name}")
            # Обновляем complex_id если передан external_id
            if data.get('external_id'):
                complex.complex_id = data['external_id']
            
            for key, value in data.items():
                if key not in ['name', 'external_id'] and hasattr(complex, key) and value is not None:
                    setattr(complex, key, value)
            complex.slug = slug
            if developer:
                complex.developer_id = developer.id
            # Авто-разбор ЦИАН адреса при обновлении
            if data.get('address'):
                apply_parsed_address(complex, data['address'])
            complex.updated_at = datetime.utcnow()
        else:
            # Создаём новый — автогеокодинг если нет координат
            logger.info(f"Создание ЖК: {name}")
            lat = data.get('latitude')
            lon = data.get('longitude')
            address = data.get('address')
            if (not lat or not lon) and address:
                lat, lon = ParserImportService._geocode_address(address, city_name)
            complex = ResidentialComplex(
                name=name,
                slug=slug,
                city_id=city.id,
                developer_id=developer.id if developer else None,
                complex_id=data.get('external_id'),
                complex_phone=data.get('phone'),
                address=address,
                latitude=lat,
                longitude=lon,
                description=data.get('description'),
                complex_type=data.get('complex_type', 'residential'),
                object_class_display_name=data.get('class_name'),
                is_active=True,
                created_at=datetime.utcnow()
            )
            # Авто-разбор ЦИАН адреса при создании
            if address:
                apply_parsed_address(complex, address)
            db.session.add(complex)

        # ── Автоматическое назначение района ─────────────────────────────────
        # Flush so the ORM has an id before district_assignment queries it.
        db.session.flush()
        _assign_district(complex, commit=False)
        # ─────────────────────────────────────────────────────────────────────

        if auto_commit:
            db.session.commit()
        return complex

    @staticmethod
    def _geocode_address(address, city_name='Краснодар'):
        """Геокодирование через Яндекс Карты. Возвращает (lat, lon) или (None, None)."""
        try:
            api_key = os.environ.get('YANDEX_MAPS_API_KEY') or os.environ.get('YANDEX_API_KEY')
            if not api_key:
                return None, None
            full_address = f"{city_name}, {address}" if city_name not in address else address
            resp = _requests.get(
                'https://geocode-maps.yandex.ru/1.x/',
                params={'apikey': api_key, 'geocode': full_address, 'format': 'json', 'results': 1},
                timeout=5
            )
            if resp.status_code != 200:
                return None, None
            members = resp.json().get('response', {}).get('GeoObjectCollection', {}).get('featureMember', [])
            if not members:
                return None, None
            lon_str, lat_str = members[0]['GeoObject']['Point']['pos'].split()
            logger.info(f"Геокодирован '{address}' → {lat_str}, {lon_str}")
            return float(lat_str), float(lon_str)
        except Exception as e:
            logger.warning(f"Геокодинг ошибка '{address}': {e}")
            return None, None

    @staticmethod
    def import_building(data, complex_name, city_name='Краснодар', auto_commit=True):
        """
        Импорт корпуса/литера
        
        Args:
            data (dict): {
                'name': 'Корпус 1' или 'Литер А',
                'external_id': 'building_789',  # ID из внешнего источника
                'end_build_year': 2025,
                'end_build_quarter': 2,
                'released': False,
                'has_accreditation': True,
                'has_green_mortgage': False
            }
            complex_name (str): Название ЖК
            city_name (str): Название города
            auto_commit (bool): Автоматически делать commit (по умолчанию True)
        
        Returns:
            Building: Созданный или обновлённый корпус
        """
        name = data.get('name')
        if not name:
            raise ValueError("Building name is required")
        
        # Находим город
        city = db.session.query(City).filter_by(name=city_name).first()
        if not city:
            raise ValueError(f"City '{city_name}' not found in database")
        
        # Находим ЖК
        complex = db.session.query(ResidentialComplex).filter_by(
            name=complex_name,
            city_id=city.id
        ).first()
        if not complex:
            raise ValueError(f"Residential complex '{complex_name}' not found in city '{city_name}'")
        
        # Ищем существующий корпус: сначала по external_id, потом по name
        building = None
        if data.get('external_id'):
            building = db.session.query(Building).filter_by(
                building_id=data['external_id']
            ).first()
        
        if not building:
            building = db.session.query(Building).filter_by(
                name=name,
                complex_id=complex.id
            ).first()
        
        # Автоматически создаём slug
        slug = create_slug(name)
        
        if building:
            # Обновляем существующий
            logger.info(f"Обновление корпуса: {name}")
            # Обновляем building_id если передан external_id
            if data.get('external_id'):
                building.building_id = data['external_id']
            
            for key, value in data.items():
                if key not in ['name', 'external_id'] and hasattr(building, key) and value is not None:
                    setattr(building, key, value)
            building.slug = slug
            building.updated_at = datetime.utcnow()
        else:
            # Создаём новый
            logger.info(f"Создание корпуса: {name}")
            building = Building(
                name=name,
                slug=slug,
                complex_id=complex.id,
                building_id=data.get('external_id'),
                building_name=data.get('name'),
                end_build_year=data.get('end_build_year'),
                end_build_quarter=data.get('end_build_quarter'),
                released=data.get('released', False),
                is_unsafe=data.get('is_unsafe', False),
                has_accreditation=data.get('has_accreditation', False),
                has_green_mortgage=data.get('has_green_mortgage', False),
                created_at=datetime.utcnow()
            )
            db.session.add(building)
        
        if auto_commit:
            db.session.commit()
        return building
    
    @staticmethod
    def import_property(data, complex_name, building_name=None, city_name='Краснодар', auto_commit=True):
        """
        Импорт квартиры
        
        Args:
            data (dict): {
                'external_id': 'prop_999',  # ID из внешнего источника (ОБЯЗАТЕЛЬНО)
                'rooms': 2,
                'area': 65.5,
                'floor': 5,
                'total_floors': 17,
                'price': 5500000,
                'price_per_sqm': 84000,
                'has_balcony': True,
                'has_loggia': False,
                'ceiling_height': 2.7,
                'finishing': 'Без отделки'
            }
            complex_name (str): Название ЖК
            building_name (str): Название корпуса (опционально)
            city_name (str): Название города
            auto_commit (bool): Автоматически делать commit (по умолчанию True)
        
        Returns:
            Property: Созданная или обновлённая квартира
        """
        external_id = data.get('external_id')
        if not external_id:
            raise ValueError("Property external_id is required")
        
        # Находим город
        city = db.session.query(City).filter_by(name=city_name).first()
        if not city:
            raise ValueError(f"City '{city_name}' not found in database")
        
        # Находим ЖК
        complex = db.session.query(ResidentialComplex).filter_by(
            name=complex_name,
            city_id=city.id
        ).first()
        if not complex:
            raise ValueError(f"Residential complex '{complex_name}' not found in city '{city_name}'")
        
        # Находим корпус (если указан)
        building = None
        if building_name:
            building = db.session.query(Building).filter_by(
                name=building_name,
                complex_id=complex.id
            ).first()
        
        # Ищем существующую квартиру по external_id
        property_obj = db.session.query(Property).filter_by(
            external_id=external_id
        ).first()
        
        # Генерируем title
        rooms = data.get('rooms', 0)
        area = data.get('area', 0)
        room_text = 'Студия' if rooms == 0 else f'{rooms}-комн.'
        title = f"{room_text} квартира, {area} м²"
        
        # Автоматически создаём slug
        slug = create_slug(f"{complex_name}-{external_id}")
        
        if property_obj:
            # Обновляем существующую
            logger.info(f"Обновление квартиры: {external_id}")
            property_obj.title = title
            property_obj.slug = slug
            property_obj.rooms = data.get('rooms')
            property_obj.area = data.get('area')
            property_obj.floor = data.get('floor')
            property_obj.total_floors = data.get('total_floors')
            property_obj.price = data.get('price')
            property_obj.price_per_sqm = data.get('price_per_sqm')
            property_obj.complex_id = complex.id
            property_obj.building_id = building.id if building else None
            property_obj.complex_building_name = building_name
            property_obj.has_balcony = data.get('has_balcony')
            property_obj.ceiling_height = data.get('ceiling_height')
            property_obj.renovation_type = data.get('finishing')  # finishing mapped to renovation_type
            property_obj.updated_at = datetime.utcnow()
            # КРИТИЧНО: обновляем last_seen_at для системы автоопределения проданных квартир
            property_obj.last_seen_at = datetime.utcnow()
        else:
            # Создаём новую
            logger.info(f"Создание квартиры: {external_id}")
            property_obj = Property(
                title=title,
                slug=slug,
                external_id=external_id,
                city_id=city.id,
                complex_id=complex.id,
                developer_id=complex.developer_id,
                building_id=building.id if building else None,
                complex_building_name=building_name,
                rooms=data.get('rooms'),
                area=data.get('area'),
                floor=data.get('floor'),
                total_floors=data.get('total_floors'),
                price=data.get('price'),
                price_per_sqm=data.get('price_per_sqm'),
                has_balcony=data.get('has_balcony'),
                ceiling_height=data.get('ceiling_height'),
                renovation_type=data.get('finishing'),  # finishing mapped to renovation_type
                is_active=True,
                created_at=datetime.utcnow(),
                # КРИТИЧНО: устанавливаем last_seen_at для системы автоопределения проданных квартир
                last_seen_at=datetime.utcnow()
            )
            db.session.add(property_obj)
        
        if auto_commit:
            db.session.commit()
        return property_obj
    
    @staticmethod
    def import_full_hierarchy(developer_data, complex_data, buildings_data, properties_data, city_name='Краснодар', auto_commit=True):
        """
        Импорт полной иерархии: Застройщик → ЖК → Корпуса → Квартиры
        
        Эта функция управляет транзакциями для всей иерархии.
        Все изменения выполняются в одной транзакции для производительности.
        
        Args:
            developer_data (dict): Данные застройщика
            complex_data (dict): Данные ЖК
            buildings_data (list): Список данных корпусов
            properties_data (list): Список данных квартир
            city_name (str): Название города
            auto_commit (bool): Автоматически делать commit (по умолчанию True).
                               Если False, вызывающий код должен сам вызвать db.session.commit()
        
        Returns:
            dict: {
                'developer': Developer,
                'complex': ResidentialComplex,
                'buildings': [Building, ...],
                'properties': [Property, ...]
            }
        """
        logger.info(f"Импорт полной иерархии для ЖК '{complex_data.get('name')}'")
        
        # Все операции выполняются без автоматического commit для производительности
        # 1. Импортируем застройщика
        developer = ParserImportService.import_developer(developer_data, auto_commit=False)
        
        # 2. Импортируем ЖК
        complex = ParserImportService.import_residential_complex(
            complex_data, 
            developer_name=developer.name,
            city_name=city_name,
            auto_commit=False
        )
        
        # 3. Импортируем корпуса
        buildings = []
        for building_data in buildings_data:
            building = ParserImportService.import_building(
                building_data,
                complex_name=complex.name,
                city_name=city_name,
                auto_commit=False
            )
            buildings.append(building)
        
        # 4. Импортируем квартиры
        properties = []
        for property_data in properties_data:
            property_obj = ParserImportService.import_property(
                property_data,
                complex_name=complex.name,
                building_name=property_data.get('building_name'),
                city_name=city_name,
                auto_commit=False
            )
            properties.append(property_obj)
        
        # Делаем commit один раз для всей иерархии (если auto_commit=True)
        if auto_commit:
            db.session.commit()
            logger.info(f"Импорт завершён и сохранён: {len(buildings)} корпусов, {len(properties)} квартир")
        else:
            logger.info(f"Импорт завершён (без commit): {len(buildings)} корпусов, {len(properties)} квартир")
        
        return {
            'developer': developer,
            'complex': complex,
            'buildings': buildings,
            'properties': properties
        }
