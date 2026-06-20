#!/usr/bin/env python3
"""
Массовое обновление nearby данных для всех ЖК
Использование: python3 update_all_nearby.py
"""

import time
from app import app, db, ResidentialComplex
import nearby_auto_updater

def main():
    print("="*70)
    print("  Массовое обновление nearby данных для ВСЕХ ЖК")
    print("="*70)
    print()
    
    with app.app_context():
        # Найти ВСЕ ЖК требующие обновления (без лимита)
        complexes = nearby_auto_updater.find_complexes_needing_update(limit=1000)
        
        total = len(complexes)
        print(f"📊 Найдено ЖК требующих обновления: {total}")
        
        if total == 0:
            print("\n✅ Все ЖК уже имеют актуальные nearby данные!")
            return
        
        print(f"\n⏳ Начинаем обновление... (ориентировочно {total * 20 // 60} минут)")
        print()
        
        success_count = 0
        error_count = 0
        
        for i, complex in enumerate(complexes, 1):
            print(f"\n[{i}/{total}] ", end="")
            
            result = nearby_auto_updater.update_nearby_for_complex(complex)
            
            if result['success']:
                success_count += 1
            else:
                error_count += 1
            
            # Пауза между ЖК чтобы не перегружать API
            if i < total:
                time.sleep(3)
        
        print("\n" + "="*70)
        print("  Результаты обновления")
        print("="*70)
        print(f"✅ Успешно обновлено: {success_count}")
        print(f"❌ Ошибок: {error_count}")
        print(f"📊 Итого обработано: {total}")
        print()
        
        if success_count > 0:
            print("🎉 Готово! Пользователи увидят обновленную информацию на сайте.")

if __name__ == "__main__":
    main()
