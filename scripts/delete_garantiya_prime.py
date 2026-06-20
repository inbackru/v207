#!/usr/bin/env python3
"""
Удаляет Гарантия PRIME (RC id=847) без интерактивного подтверждения.
Используйте только после проверки!
"""
import sys
sys.path.insert(0, '.')
from app import app, db
from sqlalchemy import text

RC_ID = 847

with app.app_context():
    rc = db.session.execute(text("SELECT id, name FROM residential_complexes WHERE id=:id"), {'id': RC_ID}).fetchone()
    if not rc:
        print(f"❌ ЖК id={RC_ID} не найден"); sys.exit(1)

    print(f"🏢 Удаляем: {rc[1]} (id={RC_ID})")

    # price_history
    r = db.session.execute(text("SELECT COUNT(*) FROM price_history WHERE complex_id=:id"), {'id': RC_ID}).scalar()
    if r:
        db.session.execute(text("DELETE FROM price_history WHERE complex_id=:id"), {'id': RC_ID})
        print(f"  ✅ price_history: {r} записей")

    # зависимые таблицы через property_id
    apt_ids = db.session.execute(text("SELECT id FROM properties WHERE complex_id=:id"), {'id': RC_ID}).fetchall()
    apt_ids_list = [row[0] for row in apt_ids]
    if apt_ids_list:
        for tbl, col in [('favorites','property_id'),('comparison_items','property_id'),('property_views','property_id')]:
            try:
                r2 = db.session.execute(text(f"DELETE FROM {tbl} WHERE {col} = ANY(:ids)"), {'ids': apt_ids_list})
                if r2.rowcount: print(f"  ✅ {tbl}: {r2.rowcount}")
            except Exception as e:
                db.session.rollback()
                print(f"  ⚠️ {tbl}: {e}")

    # квартиры
    cnt = len(apt_ids_list)
    db.session.execute(text("DELETE FROM properties WHERE complex_id=:id"), {'id': RC_ID})
    print(f"  ✅ properties: {cnt} квартир")

    # корпуса
    try:
        r = db.session.execute(text("DELETE FROM buildings WHERE complex_id=:id"), {'id': RC_ID})
        if r.rowcount: print(f"  ✅ buildings: {r.rowcount}")
    except Exception as e:
        db.session.rollback()
        print(f"  ⚠️ buildings: {e}")

    # сам ЖК
    db.session.execute(text("DELETE FROM residential_complexes WHERE id=:id"), {'id': RC_ID})
    print(f"  ✅ Удалён ЖК id={RC_ID}")

    db.session.commit()
    print("\n✅ Готово! Теперь запустите импорт через /admin/trendagent-import")
    print("   → выберите 'По конкретному ЖК'")
    print("   → вставьте Block ID: 5e9c7a62fc8e2c0001e83c0f  (Гарантия Prime, Краснодар)")
