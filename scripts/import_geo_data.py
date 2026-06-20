#!/usr/bin/env python3
"""
🚀 ФИНАЛЬНЫЙ АВТОМАТИЧЕСКИЙ ИМПОРТ ГЕОДАННЫХ
Импортирует районы и улицы через PostgreSQL COPY (максимальная скорость)

Использование:
    python3 import_geo_data.py              # Импорт всего
    python3 import_geo_data.py --districts  # Только районы
    python3 import_geo_data.py --streets    # Только улицы
"""
import pandas as pd
import os
import sys
from app import app, db
from sqlalchemy import text
from io import StringIO

def import_districts():
    """Импорт районов через COPY"""
    
    excel_file = 'attached_assets/districts (7)_1759430222840.xlsx'
    
    if not os.path.exists(excel_file):
        print(f"❌ Файл {excel_file} не найден!")
        return False
    
    print(f"\n{'='*60}")
    print(f"📍 ИМПОРТ РАЙОНОВ (PostgreSQL COPY)")
    print(f"{'='*60}")
    
    try:
        # Читаем Excel
        print(f"📂 Загрузка: {excel_file}")
        df = pd.read_excel(excel_file)
        print(f"✅ Загружено: {len(df)} районов")
        
        with app.app_context():
            # Очистка
            print("🗑️  Очистка таблицы districts...")
            db.session.execute(text("DELETE FROM districts"))
            db.session.commit()
            
            # Подготовка данных
            print("📥 Подготовка данных...")
            df_clean = df.where(pd.notna(df), None)
            
            columns_order = [
                'id', 'name', 'slug', 'latitude', 'longitude', 'zoom_level',
                'distance_to_center', 'infrastructure_data', 'description'
            ]
            
            # CSV в памяти
            csv_buffer = StringIO()
            
            for _, row in df_clean.iterrows():
                values = []
                for col in columns_order:
                    val = row.get(col)
                    if pd.isna(val) or val is None:
                        values.append('\\N')
                    elif isinstance(val, (int, float)):
                        values.append(str(val))
                    else:
                        val_str = str(val).replace('\\', '\\\\').replace('\t', '\\t').replace('\n', '\\n').replace('\r', '\\r')
                        values.append(val_str)
                
                csv_buffer.write('\t'.join(values) + '\n')
            
            csv_buffer.seek(0)
            
            # COPY
            print("⚡ Запуск COPY FROM...")
            raw_conn = db.session.connection().connection
            cursor = raw_conn.cursor()
            
            copy_sql = f"""
                COPY districts (
                    id, name, slug, latitude, longitude, zoom_level,
                    distance_to_center, infrastructure_data, description
                )
                FROM STDIN WITH (FORMAT TEXT, DELIMITER E'\\t', NULL '\\N')
            """
            
            cursor.copy_expert(copy_sql, csv_buffer)
            raw_conn.commit()
            
            # Обновляем sequence
            max_id = db.session.execute(text("SELECT MAX(id) FROM districts")).scalar()
            if max_id:
                db.session.execute(text(f"SELECT setval('districts_id_seq', {max_id}, true)"))
                db.session.commit()
            
            count = db.session.execute(text("SELECT COUNT(*) FROM districts")).scalar()
            
            print(f"\n✅ Районов импортировано: {count}")
            return True
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

def import_streets():
    """Импорт улиц через COPY"""
    
    excel_file = 'attached_assets/streets (2)_1759430222839.xlsx'
    
    if not os.path.exists(excel_file):
        print(f"❌ Файл {excel_file} не найден!")
        return False
    
    print(f"\n{'='*60}")
    print(f"🛣️  ИМПОРТ УЛИЦ (PostgreSQL COPY)")
    print(f"{'='*60}")
    
    try:
        # Читаем Excel
        print(f"📂 Загрузка: {excel_file}")
        df = pd.read_excel(excel_file)
        print(f"✅ Загружено: {len(df)} улиц")
        
        with app.app_context():
            # Очистка
            print("🗑️  Очистка таблицы streets...")
            db.session.execute(text("DELETE FROM streets"))
            db.session.commit()
            
            # Подготовка данных
            print("📥 Подготовка данных...")
            df_clean = df.where(pd.notna(df), None)
            
            columns_order = [
                'id', 'name', 'slug', 'district_id', 'latitude', 'longitude', 
                'zoom_level', 'street_type', 'distance_to_center', 
                'infrastructure_data', 'description'
            ]
            
            # CSV в памяти
            csv_buffer = StringIO()
            
            for _, row in df_clean.iterrows():
                values = []
                for col in columns_order:
                    val = row.get(col)
                    if pd.isna(val) or val is None:
                        values.append('\\N')
                    elif isinstance(val, (int, float)):
                        values.append(str(val))
                    else:
                        val_str = str(val).replace('\\', '\\\\').replace('\t', '\\t').replace('\n', '\\n').replace('\r', '\\r')
                        values.append(val_str)
                
                csv_buffer.write('\t'.join(values) + '\n')
            
            csv_buffer.seek(0)
            
            # COPY
            print("⚡ Запуск COPY FROM...")
            raw_conn = db.session.connection().connection
            cursor = raw_conn.cursor()
            
            copy_sql = f"""
                COPY streets (
                    id, name, slug, district_id, latitude, longitude, zoom_level,
                    street_type, distance_to_center, infrastructure_data, description
                )
                FROM STDIN WITH (FORMAT TEXT, DELIMITER E'\\t', NULL '\\N')
            """
            
            cursor.copy_expert(copy_sql, csv_buffer)
            raw_conn.commit()
            
            # Обновляем sequence
            max_id = db.session.execute(text("SELECT MAX(id) FROM streets")).scalar()
            if max_id:
                db.session.execute(text(f"SELECT setval('streets_id_seq', {max_id}, true)"))
                db.session.commit()
            
            count = db.session.execute(text("SELECT COUNT(*) FROM streets")).scalar()
            
            print(f"\n✅ Улиц импортировано: {count}")
            return True
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

def main():
    """Главная функция"""
    
    print(f"\n{'='*60}")
    print(f"🚀 АВТОМАТИЧЕСКИЙ ИМПОРТ ГЕОДАННЫХ")
    print(f"{'='*60}")
    
    # Проверка аргументов
    if len(sys.argv) > 1:
        if '--districts' in sys.argv:
            import_districts()
            return
        elif '--streets' in sys.argv:
            import_streets()
            return
    
    # Полный импорт
    districts_ok = import_districts()
    streets_ok = import_streets()
    
    # Статистика
    print(f"\n{'='*60}")
    print(f"📊 ИТОГОВАЯ СТАТИСТИКА")
    print(f"{'='*60}")
    
    with app.app_context():
        districts_count = db.session.execute(text("SELECT COUNT(*) FROM districts")).scalar()
        streets_count = db.session.execute(text("SELECT COUNT(*) FROM streets")).scalar()
        
        print(f"✅ Районов в БД: {districts_count}")
        print(f"✅ Улиц в БД: {streets_count}")
    
    print(f"\n{'='*60}")
    if districts_ok and streets_ok:
        print(f"✅ ИМПОРТ ЗАВЕРШЕН УСПЕШНО!")
    else:
        print(f"⚠️  ИМПОРТ ЗАВЕРШЕН С ОШИБКАМИ")
    print(f"{'='*60}\n")

if __name__ == '__main__':
    main()
