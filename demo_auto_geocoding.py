"""
ДЕМОНСТРАЦИЯ АВТОМАТИЧЕСКОГО ОБОГАЩЕНИЯ АДРЕСОВ
Показывает 3 режима работы для разных сценариев
"""

from app import app, db
from models import Property
from services.auto_geocoding import get_auto_geocoding_service, setup_auto_geocoding
import time


def demo_1_single_object():
    """
    СЦЕНАРИЙ 1: Добавление ОДНОГО объекта
    Используется: Автоматическое обогащение через SQLAlchemy events
    """
    print("\n" + "="*80)
    print("📍 СЦЕНАРИЙ 1: Добавление одного объекта через веб-форму")
    print("="*80)
    
    with app.app_context():
        # Включаем автоматическое обогащение
        setup_auto_geocoding(db)
        
        # Создаём новый объект (как будто пользователь заполнил форму)
        new_property = Property(
            title="2-комн. 65 м², ЖК Новый",
            rooms=2,
            area=65.0,
            price=5500000,
            latitude=45.0355,  # Координаты Краснодара
            longitude=38.9753,
            is_active=True
        )
        
        print(f"\n📝 Создаём объект: {new_property.title}")
        print(f"   Координаты: {new_property.latitude}, {new_property.longitude}")
        print(f"   parsed_city ДО: {new_property.parsed_city or 'пусто'}")
        
        # При добавлении в БД автоматически сработает геокодирование
        db.session.add(new_property)
        db.session.commit()
        
        # Проверяем результат
        db.session.refresh(new_property)
        print(f"\n✅ РЕЗУЛЬТАТ после db.session.commit():")
        print(f"   parsed_city: {new_property.parsed_city or 'не определён'}")
        print(f"   parsed_district: {new_property.parsed_district or 'не определён'}")
        print(f"   parsed_street: {new_property.parsed_street or 'не определена'}")
        
        # Удаляем тестовый объект
        db.session.delete(new_property)
        db.session.commit()
        
        print("\n💡 ВЫВОД: Автоматическое обогащение срабатывает при db.session.add()")


def demo_2_batch_import():
    """
    СЦЕНАРИЙ 2: Импорт СОТЕН объектов из Excel/API
    Используется: Batch обогащение с отключением автоматики
    """
    print("\n" + "="*80)
    print("📦 СЦЕНАРИЙ 2: Массовый импорт 100 объектов из Excel")
    print("="*80)
    
    with app.app_context():
        auto_service = get_auto_geocoding_service()
        
        # ВАЖНО: Включаем batch режим чтобы не тормозить импорт
        auto_service.enable_batch_mode()
        
        print("\n1️⃣ ЭТАП 1: Быстрый импорт без обогащения")
        start_time = time.time()
        
        # Получаем первые 100 объектов с координатами
        properties = Property.query.filter(
            Property.latitude.isnot(None),
            Property.longitude.isnot(None)
        ).limit(100).all()
        
        print(f"   Загружено {len(properties)} объектов за {time.time() - start_time:.2f}с")
        
        print("\n2️⃣ ЭТАП 2: Массовое обогащение пакетами")
        start_time = time.time()
        
        # Обогащаем пакетами по 50 штук
        stats = auto_service.enrich_batch(properties, batch_size=50)
        
        elapsed = time.time() - start_time
        
        print(f"\n📊 ПРОИЗВОДИТЕЛЬНОСТЬ:")
        print(f"   Всего объектов: {stats['total']}")
        print(f"   Обогащено: {stats['enriched']}")
        print(f"   Время: {elapsed:.2f}с")
        print(f"   Скорость: {stats['total']/elapsed:.1f} объектов/сек")
        print(f"   API запросов: {stats['cache_stats']['api_requests']}")
        print(f"   Экономия через кэш: {stats['cache_stats']['cache_hit_rate']}%")
        
        # Выключаем batch режим
        auto_service.disable_batch_mode()
        
        print("\n💡 ВЫВОД: Batch обогащение ~10-20 объектов/сек с кэшированием")


def demo_3_estimate_performance():
    """
    СЦЕНАРИЙ 3: Оценка времени для ТЫСЯЧ объектов
    """
    print("\n" + "="*80)
    print("⏱️  СЦЕНАРИЙ 3: Оценка времени для разных объёмов")
    print("="*80)
    
    # Базовая производительность (из тестов)
    objects_per_sec = 15  # С кэшированием ~40%, без кэша ~8
    api_limit_per_day = 25000  # Yandex бесплатный лимит
    
    volumes = [
        ("100 объектов", 100),
        ("500 объектов", 500),
        ("1,000 объектов", 1000),
        ("5,000 объектов", 5000),
        ("25,000 объектов", 25000),
    ]
    
    print("\n📈 ПРОГНОЗ ПРОИЗВОДИТЕЛЬНОСТИ (с кэшированием ~40%):\n")
    print(f"{'Объём':<20} {'Время':<15} {'API запросы':<15} {'Статус'}")
    print("-" * 65)
    
    for name, count in volumes:
        time_sec = count / objects_per_sec
        api_requests = int(count * 0.6)  # 40% из кэша, 60% новые запросы
        
        # Форматируем время
        if time_sec < 60:
            time_str = f"{time_sec:.0f}с"
        elif time_sec < 3600:
            time_str = f"{time_sec/60:.1f}мин"
        else:
            time_str = f"{time_sec/3600:.1f}ч"
        
        # Проверяем лимит API
        if api_requests > api_limit_per_day:
            status = "⚠️ Требуется несколько дней"
        else:
            status = "✅ За 1 день"
        
        print(f"{name:<20} {time_str:<15} {api_requests:<15,} {status}")
    
    print("\n" + "-" * 65)
    print("\n💡 РЕКОМЕНДАЦИИ:")
    print("   • До 1,000 объектов: Batch обогащение за раз (~1 минута)")
    print("   • До 25,000 объектов: Batch обогащение за 1 день (лимит API)")
    print("   • Больше 25,000: Разбить на несколько дней или платный API ключ")
    print("   • Кэш работает 24 часа → повторные объекты обогащаются мгновенно")


def demo_4_integration_example():
    """
    СЦЕНАРИЙ 4: Интеграция в существующий скрипт импорта
    """
    print("\n" + "="*80)
    print("🔧 СЦЕНАРИЙ 4: Как добавить в скрипт импорта")
    print("="*80)
    
    example_code = '''
# ===== ПРИМЕР: scripts/import_excel_data.py =====

from services.auto_geocoding import get_auto_geocoding_service

def import_properties_from_excel(file_path):
    """Импорт объектов с автоматическим обогащением адресов"""
    
    auto_service = get_auto_geocoding_service()
    
    # ЭТАП 1: Быстрый импорт без обогащения
    auto_service.enable_batch_mode()
    
    properties = []
    for row in read_excel(file_path):
        prop = Property(
            title=row['title'],
            latitude=row['lat'],
            longitude=row['lon'],
            # ... остальные поля
        )
        db.session.add(prop)
        properties.append(prop)
    
    db.session.commit()
    print(f"✅ Импортировано {len(properties)} объектов")
    
    # ЭТАП 2: Массовое обогащение адресов
    stats = auto_service.enrich_batch(properties, batch_size=50)
    print(f"✅ Обогащено {stats['enriched']} адресов")
    
    auto_service.disable_batch_mode()
    
    return stats

# ===== АЛЬТЕРНАТИВА: Автоматическое обогащение =====

# В app.py при инициализации:
from services.auto_geocoding import setup_auto_geocoding

with app.app_context():
    setup_auto_geocoding(db)  # Включаем автоматику
    
# Теперь ЛЮБОЙ новый Property автоматически обогащается:
new_prop = Property(title="Квартира", latitude=45.0, longitude=38.9)
db.session.add(new_prop)
db.session.commit()
# new_prop.parsed_city автоматически заполнится!
'''
    
    print(example_code)
    
    print("\n💡 ВЫВОД: Два подхода на выбор")
    print("   1. Автоматический: setup_auto_geocoding() в app.py → работает всегда")
    print("   2. Batch: Вручную вызывать enrich_batch() → контроль производительности")


if __name__ == '__main__':
    print("\n" + "="*80)
    print("🚀 ДЕМОНСТРАЦИЯ АВТОМАТИЧЕСКОГО ОБОГАЩЕНИЯ АДРЕСОВ")
    print("="*80)
    
    choice = input("""
Выберите сценарий:
1. Добавление одного объекта (автоматическое обогащение)
2. Массовый импорт 100 объектов (batch режим)
3. Оценка производительности для тысяч объектов
4. Примеры интеграции в код
5. Запустить все сценарии

Ваш выбор (1-5): """).strip()
    
    if choice == '1':
        demo_1_single_object()
    elif choice == '2':
        demo_2_batch_import()
    elif choice == '3':
        demo_3_estimate_performance()
    elif choice == '4':
        demo_4_integration_example()
    elif choice == '5':
        demo_1_single_object()
        demo_2_batch_import()
        demo_3_estimate_performance()
        demo_4_integration_example()
    else:
        print("❌ Неверный выбор")
    
    print("\n" + "="*80)
    print("✅ ДЕМОНСТРАЦИЯ ЗАВЕРШЕНА")
    print("="*80 + "\n")
