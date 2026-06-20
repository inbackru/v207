#!/usr/bin/env python3
"""
Полное удаление ЖК и всех его данных из базы.
Использование:
    python scripts/delete_rc.py --rc-id 847
    python scripts/delete_rc.py --slug garantiya-prime
"""
import sys, argparse
sys.path.insert(0, '.')
from app import app, db
from sqlalchemy import text

def delete_rc(rc_id: int, dry_run: bool = False):
    with app.app_context():
        # Проверяем существование
        rc = db.session.execute(text("SELECT id, name, slug, city_id FROM residential_complexes WHERE id=:id"), {'id': rc_id}).fetchone()
        if not rc:
            print(f"❌ ЖК с id={rc_id} не найден"); return

        print(f"\n🏢 ЖК: {rc[1]}  (id={rc[0]}, slug={rc[2]}, city_id={rc[3]})")

        # Считаем
        apt_count = db.session.execute(text("SELECT COUNT(*) FROM properties WHERE complex_id=:id"), {'id': rc_id}).scalar()
        ph_count  = db.session.execute(text("SELECT COUNT(*) FROM price_history WHERE complex_id=:id"), {'id': rc_id}).scalar() if _table_exists('price_history') else 0
        bld_count = db.session.execute(text("SELECT COUNT(*) FROM buildings WHERE complex_id=:id"), {'id': rc_id}).scalar() if _table_exists('buildings') else 0

        print(f"   Квартир:          {apt_count}")
        print(f"   Корпусов:         {bld_count}")
        print(f"   Записей PriceHistory: {ph_count}")

        if dry_run:
            print("\n[DRY RUN] Ничего не удалено. Запустите без --dry-run для реального удаления.")
            return

        print(f"\n⚠️  УДАЛЯЕМ {apt_count} квартир, {bld_count} корпусов и сам ЖК id={rc_id}...")
        confirm = input("Введите YES для подтверждения: ").strip()
        if confirm != 'YES':
            print("Отменено."); return

        # Удаляем в правильном порядке
        if ph_count:
            db.session.execute(text("DELETE FROM price_history WHERE complex_id=:id"), {'id': rc_id})
            print(f"  ✅ Удалено {ph_count} записей price_history")

        if apt_count:
            # Сначала favorites / comparisons
            for tbl, col in [('favorites','property_id'),('comparison_items','property_id'),('property_views','property_id')]:
                if _table_exists(tbl):
                    r = db.session.execute(text(f"DELETE FROM {tbl} WHERE {col} IN (SELECT id FROM properties WHERE complex_id=:id)"), {'id': rc_id})
                    if r.rowcount: print(f"  ✅ Удалено {r.rowcount} из {tbl}")

            db.session.execute(text("DELETE FROM properties WHERE complex_id=:id"), {'id': rc_id})
            print(f"  ✅ Удалено {apt_count} квартир")

        if bld_count:
            db.session.execute(text("DELETE FROM buildings WHERE complex_id=:id"), {'id': rc_id})
            print(f"  ✅ Удалено {bld_count} корпусов")

        # Удаляем сам ЖК
        db.session.execute(text("DELETE FROM residential_complexes WHERE id=:id"), {'id': rc_id})
        print(f"  ✅ Удалён ЖК id={rc_id}")

        db.session.commit()
        print("\n✅ Готово! Теперь запустите импорт через /admin/trendagent-import")

def _table_exists(name):
    r = db.session.execute(text("SELECT 1 FROM information_schema.tables WHERE table_name=:n"), {'n': name}).fetchone()
    return bool(r)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Удалить ЖК из базы данных')
    parser.add_argument('--rc-id', type=int, help='ID ЖК')
    parser.add_argument('--slug', type=str, help='Slug ЖК (как альтернатива ID)')
    parser.add_argument('--dry-run', action='store_true', help='Только показать что будет удалено, не удалять')
    args = parser.parse_args()

    if not args.rc_id and not args.slug:
        print("Укажите --rc-id или --slug"); sys.exit(1)

    with app.app_context():
        if args.slug and not args.rc_id:
            r = db.session.execute(text("SELECT id FROM residential_complexes WHERE slug=:s"), {'s': args.slug}).fetchone()
            if not r:
                print(f"❌ ЖК с slug='{args.slug}' не найден"); sys.exit(1)
            args.rc_id = r[0]

    delete_rc(args.rc_id, dry_run=args.dry_run)
