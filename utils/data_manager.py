"""
Инструмент для управления данными недвижимости мирового уровня
Простой Python скрипт для добавления застройщиков, ЖК и квартир
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Developer, ResidentialComplex, Property
import re
import unicodedata

def slugify(text):
    """Convert text to URL-friendly slug"""
    # Transliterate Cyrillic to Latin
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }
    
    text = text.lower()
    result = ''
    for char in text:
        result += translit_map.get(char, char)
    
    # Remove non-alphanumeric characters
    result = re.sub(r'[^a-z0-9]+', '-', result)
    return result.strip('-')


class DataManager:
    """Менеджер данных для работы с normalized таблицами"""
    
    def __init__(self):
        self.app = app
    
    def add_developer(self, name, phone=None, website=None, **kwargs):
        """
        Добавить застройщика
        
        Пример:
            dm.add_developer(
                name="Новый Застройщик",
                phone="+7 (999) 123-45-67",
                website="https://developer.ru"
            )
        """
        with self.app.app_context():
            # Check if already exists
            existing = Developer.query.filter_by(name=name).first()
            if existing:
                print(f"⚠️  Застройщик '{name}' уже существует (ID: {existing.id})")
                return existing
            
            developer = Developer(
                name=name,
                slug=kwargs.get('slug', slugify(name)),
                phone=phone,
                website=website,
                **kwargs
            )
            
            db.session.add(developer)
            db.session.commit()
            
            print(f"✅ Застройщик '{name}' добавлен (ID: {developer.id})")
            return developer
    
    def add_residential_complex(self, name, developer_name, cashback_rate=5.0, **kwargs):
        """
        Добавить жилой комплекс
        
        Пример:
            dm.add_residential_complex(
                name="ЖК Солнечный",
                developer_name="Новый Застройщик",
                cashback_rate=5.5,
                sales_phone="+7 (999) 111-22-33",
                address="ул. Красная, 100",
                latitude=45.123456,
                longitude=38.987654
            )
        """
        with self.app.app_context():
            # Find developer
            developer = Developer.query.filter_by(name=developer_name).first()
            if not developer:
                print(f"❌ Застройщик '{developer_name}' не найден. Сначала добавьте застройщика!")
                return None
            
            # Check if complex already exists
            existing = ResidentialComplex.query.filter_by(name=name).first()
            if existing:
                print(f"⚠️  ЖК '{name}' уже существует (ID: {existing.id})")
                return existing
            
            complex_obj = ResidentialComplex(
                name=name,
                slug=kwargs.get('slug', slugify(name)),
                developer_id=developer.id,
                cashback_rate=cashback_rate,
                **kwargs
            )
            
            db.session.add(complex_obj)
            db.session.commit()
            
            print(f"✅ ЖК '{name}' добавлен (ID: {complex_obj.id}, Застройщик: {developer_name})")
            return complex_obj
    
    def add_property(self, complex_name, title, price, area, rooms, **kwargs):
        """
        Добавить квартиру
        
        Пример:
            dm.add_property(
                complex_name="ЖК Солнечный",
                title="2-комн, 65 м²",
                price=7500000,
                area=65.0,
                rooms=2,
                floor=5,
                total_floors=15,
                latitude=45.123456,
                longitude=38.987654
            )
        """
        with self.app.app_context():
            # Find complex
            complex_obj = ResidentialComplex.query.filter_by(name=complex_name).first()
            if not complex_obj:
                print(f"❌ ЖК '{complex_name}' не найден. Сначала добавьте ЖК!")
                return None
            
            # Calculate price per sqm if not provided
            price_per_sqm = kwargs.get('price_per_sqm')
            if not price_per_sqm and price and area:
                price_per_sqm = int(price / area)
            
            property_obj = Property(
                title=title,
                slug=kwargs.get('slug', slugify(title)),
                complex_id=complex_obj.id,
                developer_id=complex_obj.developer_id,
                price=price,
                area=area,
                rooms=rooms,
                price_per_sqm=price_per_sqm,
                is_active=True,
                **kwargs
            )
            
            db.session.add(property_obj)
            db.session.commit()
            
            print(f"✅ Квартира '{title}' добавлена в '{complex_name}' (ID: {property_obj.id}, Цена: {property_obj.formatted_price})")
            return property_obj
    
    def list_developers(self):
        """Показать всех застройщиков"""
        with self.app.app_context():
            developers = Developer.query.filter_by(is_active=True).all()
            print(f"\n📊 Всего застройщиков: {len(developers)}")
            for dev in developers:
                complexes_count = len(dev.complexes)
                properties_count = Property.query.filter_by(developer_id=dev.id).count()
                print(f"  • {dev.name} (ID: {dev.id}) - ЖК: {complexes_count}, Квартир: {properties_count}")
    
    def list_complexes(self, developer_name=None):
        """Показать все ЖК (опционально фильтр по застройщику)"""
        with self.app.app_context():
            query = ResidentialComplex.query.filter_by(is_active=True)
            
            if developer_name:
                developer = Developer.query.filter_by(name=developer_name).first()
                if developer:
                    query = query.filter_by(developer_id=developer.id)
                else:
                    print(f"❌ Застройщик '{developer_name}' не найден")
                    return
            
            complexes = query.all()
            print(f"\n📊 Всего ЖК: {len(complexes)}")
            for cx in complexes:
                properties_count = len(cx.properties)
                dev_name = cx.developer.name if cx.developer else "Не указан"
                print(f"  • {cx.name} (ID: {cx.id}) - Застройщик: {dev_name}, Квартир: {properties_count}, Кэшбек: {cx.cashback_rate}%")
    
    def list_properties(self, complex_name=None, limit=20):
        """Показать квартиры (опционально фильтр по ЖК)"""
        with self.app.app_context():
            query = Property.query.filter_by(is_active=True)
            
            if complex_name:
                complex_obj = ResidentialComplex.query.filter_by(name=complex_name).first()
                if complex_obj:
                    query = query.filter_by(complex_id=complex_obj.id)
                else:
                    print(f"❌ ЖК '{complex_name}' не найден")
                    return
            
            properties = query.limit(limit).all()
            total = query.count()
            
            print(f"\n📊 Показано: {len(properties)} из {total} квартир")
            for prop in properties:
                cx_name = prop.residential_complex.name if prop.residential_complex else "Не указан"
                print(f"  • {prop.title} - {prop.formatted_price} ({cx_name})")


# ============================================
# ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ
# ============================================

def example_usage():
    """Примеры как использовать DataManager"""
    
    dm = DataManager()
    
    # 1. Добавить застройщика
    print("\n=== Пример 1: Добавить застройщика ===")
    developer = dm.add_developer(
        name="ПремиумСтрой",
        phone="+7 (861) 123-45-67",
        website="https://premium-stroy.ru",
        description="Крупный девелопер Краснодара",
        inn="2312345678"
    )
    
    # 2. Добавить ЖК
    print("\n=== Пример 2: Добавить ЖК ===")
    complex_obj = dm.add_residential_complex(
        name="ЖК Премиум Парк",
        developer_name="ПремиумСтрой",
        cashback_rate=5.5,
        sales_phone="+7 (861) 999-88-77",
        address="ул. Красная, 200, Краснодар",
        latitude=45.0401,
        longitude=38.9760,
        description="Элитный жилой комплекс в центре города",
        start_build_year=2024,
        end_build_year=2026
    )
    
    # 3. Добавить квартиру
    print("\n=== Пример 3: Добавить квартиру ===")
    property_obj = dm.add_property(
        complex_name="ЖК Премиум Парк",
        title="2-комн, 65 м², 8/15 эт.",
        price=8500000,
        area=65.0,
        rooms=2,
        floor=8,
        total_floors=15,
        latitude=45.0401,
        longitude=38.9760,
        description="Просторная двухкомнатная квартира с видом на парк",
        deal_type="Первичка"
    )
    
    # 4. Посмотреть что добавили
    print("\n=== Пример 4: Просмотр данных ===")
    dm.list_developers()
    dm.list_complexes()
    dm.list_properties(limit=10)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Управление данными недвижимости')
    parser.add_argument('command', choices=['example', 'list-developers', 'list-complexes', 'list-properties'],
                       help='Команда для выполнения')
    
    args = parser.parse_args()
    
    dm = DataManager()
    
    if args.command == 'example':
        example_usage()
    elif args.command == 'list-developers':
        dm.list_developers()
    elif args.command == 'list-complexes':
        dm.list_complexes()
    elif args.command == 'list-properties':
        dm.list_properties()
