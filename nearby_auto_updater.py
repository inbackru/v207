"""
Автоматическое обновление nearby данных для ЖК добавленных парсером
"""
import json
import time
from datetime import datetime, timedelta
from app import app, db, ResidentialComplex
import nearby_places


def find_complexes_needing_update(limit=10):
    """
    Найти ЖК которым нужно обновление nearby данных
    
    Returns:
        List[ResidentialComplex]: ЖК требующие обновления
    """
    with app.app_context():
        # Критерии для обновления:
        # 1. Есть координаты (latitude и longitude)
        # 2. Нет nearby данных ИЛИ данные старше 6 месяцев
        
        six_months_ago = datetime.utcnow() - timedelta(days=180)
        
        complexes = db.session.query(ResidentialComplex).filter(
            ResidentialComplex.latitude.isnot(None),
            ResidentialComplex.longitude.isnot(None),
            db.or_(
                ResidentialComplex.nearby.is_(None),  # Нет данных
                ResidentialComplex.nearby_updated_at.is_(None),  # Нет даты обновления
                ResidentialComplex.nearby_updated_at < six_months_ago  # Устаревшие данные
            )
        ).limit(limit).all()
        
        return complexes


def update_nearby_for_complex(complex):
    """
    Обновить nearby данные для одного ЖК
    
    Args:
        complex: объект ResidentialComplex
    
    Returns:
        dict: Результат обновления
    """
    result = {
        'complex_id': complex.id,
        'complex_name': complex.name,
        'success': False,
        'objects_found': 0,
        'error': None
    }
    
    try:
        print(f"🔄 Обновление nearby для ЖК: {complex.name}")
        print(f"   Координаты: {complex.latitude}, {complex.longitude}")
        
        # Получаем данные из OpenStreetMap
        nearby_data = nearby_places.fetch_nearby_places(
            latitude=float(complex.latitude),
            longitude=float(complex.longitude),
            radius_meters=3000  # 3 км для лучшего покрытия
        )
        
        # Подсчитываем найденные объекты
        total_objects = sum(
            len(nearby_data.get(cat, [])) 
            for cat in ['transport', 'shopping', 'education', 'healthcare', 'sport', 'leisure']
        )
        
        if total_objects > 0:
            # Сохраняем в БД
            # ВАЖНО: Re-query объект чтобы он был прикреплен к текущей сессии
            with app.app_context():
                complex_in_session = db.session.query(ResidentialComplex).get(complex.id)
                if complex_in_session:
                    complex_in_session.nearby = json.dumps(nearby_data, ensure_ascii=False)
                    complex_in_session.nearby_updated_at = datetime.utcnow()
                    db.session.commit()
                    
                    result['success'] = True
                    result['objects_found'] = total_objects
                else:
                    # Редкий случай: объект был удален между запросами
                    result['error'] = 'Complex not found in database'
                    print(f"   ⚠️  ЖК не найден в БД (возможно удален)")
                    return result
            
            
            print(f"   ✅ Найдено {total_objects} объектов")
            print(f"      Транспорт: {len(nearby_data.get('transport', []))}")
            print(f"      Торговля: {len(nearby_data.get('shopping', []))}")
            print(f"      Образование: {len(nearby_data.get('education', []))}")
            print(f"      Здравоохранение: {len(nearby_data.get('healthcare', []))}")
            print(f"      Спорт: {len(nearby_data.get('sport', []))}")
            print(f"      Досуг: {len(nearby_data.get('leisure', []))}")
        else:
            result['error'] = 'No objects found'
            print(f"   ⚠️  Объекты не найдены в радиусе 3 км")
        
    except Exception as e:
        result['error'] = str(e)
        print(f"   ❌ Ошибка: {e}")
    
    return result


def process_batch(batch_size=5, delay_between=2):
    """
    Обработать пакет ЖК
    
    Args:
        batch_size: Количество ЖК для обработки
        delay_between: Задержка между запросами (секунды)
    
    Returns:
        dict: Статистика обработки
    """
    print("="*70)
    print("  Автоматическое обновление nearby данных")
    print("="*70)
    print()
    
    # Находим ЖК требующие обновления
    complexes = find_complexes_needing_update(limit=batch_size)
    
    if not complexes:
        print("✅ Все ЖК уже обновлены!")
        return {
            'total': 0,
            'success': 0,
            'failed': 0,
            'objects_total': 0
        }
    
    print(f"📊 Найдено ЖК для обновления: {len(complexes)}")
    print()
    
    stats = {
        'total': len(complexes),
        'success': 0,
        'failed': 0,
        'objects_total': 0,
        'results': []
    }
    
    for i, complex in enumerate(complexes, 1):
        print(f"[{i}/{len(complexes)}] Обрабатываем: {complex.name}")
        
        # Обновляем
        result = update_nearby_for_complex(complex)
        stats['results'].append(result)
        
        if result['success']:
            stats['success'] += 1
            stats['objects_total'] += result['objects_found']
        else:
            stats['failed'] += 1
        
        # Задержка между запросами чтобы не перегружать API
        if i < len(complexes):
            print(f"   ⏱️  Пауза {delay_between} сек...")
            time.sleep(delay_between)
        
        print()
    
    # Итоги
    print("="*70)
    print("  Итоги обработки")
    print("="*70)
    print(f"✅ Успешно обновлено: {stats['success']}")
    print(f"❌ Ошибок: {stats['failed']}")
    print(f"📊 Всего объектов найдено: {stats['objects_total']}")
    print()
    
    return stats


def update_all_outdated(max_complexes=100, batch_size=5):
    """
    Обновить все устаревшие ЖК порциями
    
    Args:
        max_complexes: Максимум ЖК для обновления
        batch_size: Размер порции
    """
    total_stats = {
        'batches': 0,
        'success': 0,
        'failed': 0,
        'objects_total': 0
    }
    
    processed = 0
    
    while processed < max_complexes:
        print(f"\n{'='*70}")
        print(f"  Порция {total_stats['batches'] + 1}")
        print(f"{'='*70}\n")
        
        stats = process_batch(batch_size=batch_size, delay_between=3)
        
        if stats['total'] == 0:
            # Больше нет ЖК для обновления
            break
        
        total_stats['batches'] += 1
        total_stats['success'] += stats['success']
        total_stats['failed'] += stats['failed']
        total_stats['objects_total'] += stats['objects_total']
        
        processed += stats['total']
        
        if stats['total'] < batch_size:
            # Последняя порция
            break
    
    # Финальный отчет
    print("\n" + "="*70)
    print("  ФИНАЛЬНЫЙ ОТЧЕТ")
    print("="*70)
    print(f"Обработано порций: {total_stats['batches']}")
    print(f"✅ Успешно: {total_stats['success']} ЖК")
    print(f"❌ Ошибок: {total_stats['failed']} ЖК")
    print(f"📊 Всего объектов: {total_stats['objects_total']}")
    print("="*70 + "\n")
    
    return total_stats


# Для запуска вручную
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--all':
        # Обновить все
        print("Режим: Обновление всех устаревших ЖК")
        update_all_outdated(max_complexes=100, batch_size=5)
    else:
        # Обновить одну порцию
        print("Режим: Обновление одной порции (5 ЖК)")
        print("Для обновления всех используйте: python nearby_auto_updater.py --all")
        print()
        process_batch(batch_size=5, delay_between=2)
