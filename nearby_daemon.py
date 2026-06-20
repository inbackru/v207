#!/usr/bin/env python3
"""
Фоновый процесс для автоматического обновления nearby данных
Запускается один раз и работает постоянно в фоне
"""

import time
import sys
from datetime import datetime
from app import app
import nearby_auto_updater

def log(message):
    """Вывод с временной меткой"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {message}", flush=True)

def main():
    log("="*70)
    log("  🤖 Nearby Daemon - Автоматическое обновление nearby данных")
    log("="*70)
    log("Режим работы: проверка каждые 30 минут")
    log("Обновление: 5 ЖК за раз")
    log("="*70)
    log("")
    
    iteration = 0
    
    while True:
        iteration += 1
        
        try:
            log(f"🔄 Итерация #{iteration}: Поиск ЖК для обновления...")
            
            with app.app_context():
                # Найти ЖК требующие обновления
                complexes = nearby_auto_updater.find_complexes_needing_update(limit=5)
                
                if len(complexes) == 0:
                    log("✅ Все ЖК имеют актуальные nearby данные")
                else:
                    log(f"📍 Найдено ЖК для обновления: {len(complexes)}")
                    
                    success_count = 0
                    error_count = 0
                    
                    for i, complex in enumerate(complexes, 1):
                        log(f"   [{i}/{len(complexes)}] Обновляем: {complex.name}")
                        
                        result = nearby_auto_updater.update_nearby_for_complex(complex)
                        
                        if result['success']:
                            success_count += 1
                            log(f"      ✅ Найдено {result['objects_found']} объектов")
                        else:
                            error_count += 1
                            log(f"      ❌ Ошибка: {result.get('error', 'Unknown')}")
                        
                        # Пауза между ЖК
                        if i < len(complexes):
                            time.sleep(3)
                    
                    log(f"📊 Результаты: успешно {success_count}, ошибок {error_count}")
            
            # Ждём 30 минут до следующей проверки
            log(f"⏳ Следующая проверка через 30 минут...")
            log("")
            time.sleep(1800)  # 30 минут = 1800 секунд
            
        except KeyboardInterrupt:
            log("⚠️  Получен сигнал остановки")
            log("👋 Daemon остановлен")
            sys.exit(0)
            
        except Exception as e:
            log(f"❌ Критическая ошибка: {e}")
            log("⏳ Повтор через 5 минут...")
            time.sleep(300)  # При ошибке - ждём 5 минут

if __name__ == "__main__":
    main()
