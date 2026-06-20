from models import Property, ResidentialComplex, Developer
from app import db
from typing import List, Optional, Dict

class PropertyMatcher:
    """
    Сервис для поиска похожих объектов недвижимости
    """
    
    @staticmethod
    def find_similar_properties(
        property_id: int,
        limit: int = 10,
        city_id: Optional[int] = None
    ) -> List[Dict]:
        """
        Найти похожие объекты для заданного property_id
        
        Критерии поиска:
        1. Город (обязательно тот же)
        2. Количество комнат (точное совпадение)
        3. Площадь (±15%)
        4. Цена (±20%)
        5. Тот же застройщик (приоритет, но не обязательно)
        
        Args:
            property_id: ID объекта для поиска аналогов
            limit: Максимальное количество результатов
            city_id: Опциональный city_id (если известен заранее)
        
        Returns:
            List[Dict]: Список похожих объектов с полями:
                - id, inner_id, title, price, area, rooms
                - complex_name, developer_name, cashback_rate
                - similarity_score (0-100)
        """
        # Получить исходный объект
        original = Property.query.get(property_id)
        if not original:
            return []
        
        # Базовые параметры для поиска
        area_min = original.area * 0.85  # -15%
        area_max = original.area * 1.15  # +15%
        price_min = original.price * 0.80  # -20%
        price_max = original.price * 1.20  # +20%
        
        # Строим запрос
        query = db.session.query(
            Property,
            ResidentialComplex.name.label('complex_name'),
            ResidentialComplex.cashback_rate,
            Developer.name.label('developer_name')
        ).outerjoin(
            ResidentialComplex, Property.complex_id == ResidentialComplex.id
        ).outerjoin(
            Developer, Property.developer_id == Developer.id
        ).filter(
            Property.id != property_id,  # Не включать сам объект
            Property.is_active == True,  # Только активные
            Property.city_id == (city_id or original.city_id),  # Тот же город
            Property.rooms == original.rooms,  # Точное количество комнат
            Property.area >= area_min,
            Property.area <= area_max,
            Property.price >= price_min,
            Property.price <= price_max
        )
        
        # Приоритет: тот же застройщик
        if original.developer_id:
            query = query.order_by(
                (Property.developer_id == original.developer_id).desc(),
                db.func.abs(Property.price - original.price).asc()  # Ближайшая цена
            )
        else:
            query = query.order_by(
                db.func.abs(Property.price - original.price).asc()
            )
        
        results = query.limit(limit).all()
        
        # Форматируем результаты
        similar_properties = []
        for prop, complex_name, cashback_rate, developer_name in results:
            # Вычисляем similarity_score (0-100)
            price_diff = abs(prop.price - original.price) / original.price
            area_diff = abs(prop.area - original.area) / original.area
            
            # Чем меньше разница, тем выше score
            price_score = max(0, 100 - (price_diff * 100))
            area_score = max(0, 100 - (area_diff * 100))
            developer_bonus = 20 if prop.developer_id == original.developer_id else 0
            
            similarity_score = int((price_score + area_score) / 2 + developer_bonus)
            similarity_score = min(100, similarity_score)  # Максимум 100
            
            rooms_text = f"{prop.rooms}-комн" if prop.rooms and prop.rooms > 0 else "Студия"
            
            similar_properties.append({
                'id': prop.id,
                'inner_id': prop.inner_id,
                'title': f"{rooms_text}, {prop.area} м², {prop.floor}/{prop.total_floors} эт.",
                'price': prop.price or 0,
                'area': prop.area,
                'rooms': prop.rooms,
                'floor': prop.floor,
                'total_floors': prop.total_floors,
                'complex_name': complex_name or 'ЖК не указан',
                'developer_name': developer_name or 'Застройщик не указан',
                'cashback_rate': cashback_rate or 3.5,
                'cashback_amount': int((prop.price or 0) * (cashback_rate or 3.5) / 100),
                'image': prop.main_image or '/static/images/no-photo.jpg',
                'similarity_score': similarity_score,
                'url': f'/property/{prop.inner_id}'
            })
        
        # Сортируем по similarity_score (высший сначала)
        similar_properties.sort(key=lambda x: x['similarity_score'], reverse=True)
        
        return similar_properties
    
    @staticmethod
    def get_property_search_params(property_id: int) -> Optional[Dict]:
        """
        Получить параметры поиска для объекта (для формирования URL)
        
        Returns:
            Dict с параметрами или None если объект не найден
        """
        prop = Property.query.get(property_id)
        if not prop:
            return None
        
        return {
            'city_id': prop.city_id,
            'rooms': prop.rooms,
            'area_min': int(prop.area * 0.85),
            'area_max': int(prop.area * 1.15),
            'price_min': int(prop.price * 0.80),
            'price_max': int(prop.price * 1.20)
        }
