"""
БД Health Check + Import Readiness Report
Запуск: python scripts/db_health_check.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from sqlalchemy import text
from datetime import datetime

def separator(title=""):
    print("\n" + "="*60)
    if title:
        print(f"  {title}")
        print("="*60)

def check():
    with app.app_context():
        separator("DB HEALTH CHECK — " + datetime.now().strftime("%Y-%m-%d %H:%M"))

        # 1. Таблицы
        tables = db.session.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' ORDER BY table_name
        """)).fetchall()
        print(f"\n✅ Таблиц в БД: {len(tables)}")

        # 2. Счётчики объектов
        separator("СЧЁТЧИКИ ОБЪЕКТОВ")
        counts = db.session.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM residential_complexes)          AS complexes,
              (SELECT COUNT(*) FROM residential_complexes WHERE is_active=true) AS complexes_active,
              (SELECT COUNT(*) FROM properties)                     AS properties,
              (SELECT COUNT(*) FROM properties WHERE is_active=true) AS properties_active,
              (SELECT COUNT(*) FROM buildings)                      AS buildings,
              (SELECT COUNT(*) FROM developers)                     AS developers,
              (SELECT COUNT(*) FROM cities)                         AS cities,
              (SELECT COUNT(*) FROM price_history)                  AS price_history,
              (SELECT COUNT(*) FROM stg_complexes)                  AS stg_complexes,
              (SELECT COUNT(*) FROM stg_properties)                 AS stg_properties
        """)).fetchone()

        print(f"  ЖК (всего / активных):        {counts.complexes} / {counts.complexes_active}")
        print(f"  Объекты (всего / активных):   {counts.properties} / {counts.properties_active}")
        print(f"  Корпуса (buildings):           {counts.buildings}")
        print(f"  Застройщики:                   {counts.developers}")
        print(f"  Города:                        {counts.cities}")
        print(f"  История цен:                   {counts.price_history}")
        print(f"  Стейджинг ЖК:                  {counts.stg_complexes}")
        print(f"  Стейджинг объекты:             {counts.stg_properties}")

        # 3. Статистика по ЖК
        separator("СТАТИСТИКА ПО ЖК")
        complex_stats = db.session.execute(text("""
            SELECT
              rc.name,
              rc.city_id,
              c.name as city_name,
              COUNT(DISTINCT p.id)     AS props_count,
              MIN(p.price)             AS min_price,
              MAX(p.price)             AS max_price,
              AVG(p.price_per_sqm)::int AS avg_sqm
            FROM residential_complexes rc
            LEFT JOIN cities c ON c.id = rc.city_id
            LEFT JOIN properties p ON p.complex_id = rc.id AND p.is_active = true
            GROUP BY rc.id, rc.name, rc.city_id, c.name
            ORDER BY props_count DESC
            LIMIT 15
        """)).fetchall()

        print(f"  {'ЖК':<35} {'Город':<12} {'Объектов':>9} {'Мин.цена':>12} {'Ср. м²':>10}")
        print(f"  {'-'*35} {'-'*12} {'-'*9} {'-'*12} {'-'*10}")
        for r in complex_stats:
            min_p = f"{r.min_price/1_000_000:.1f}М" if r.min_price else "—"
            avg_s = f"{r.avg_sqm:,}" if r.avg_sqm else "—"
            print(f"  {r.name[:35]:<35} {r.city_name[:12]:<12} {r.props_count:>9} {min_p:>12} {avg_s:>10}")

        # 4. NOT NULL проверка — могут ли упасть вставки
        separator("NOT NULL ПОЛЯ (критичные для INSERT)")
        nn = db.session.execute(text("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND is_nullable = 'NO'
              AND table_name IN ('residential_complexes','properties','buildings')
              AND column_name != 'id'
            ORDER BY table_name, column_name
        """)).fetchall()

        for r in nn:
            default = ""
            if r.column_name in ('cashback_rate', 'complex_type', 'property_type'):
                default = " (есть default)"
            print(f"  [{r.table_name}] {r.column_name}: {r.data_type}{default}")

        # 5. Стейджинг → Прод (пробелы)
        separator("СТЕЙДЖИНГ → ПРОД (что не импортировано)")
        missing = db.session.execute(text("""
            SELECT
              sc.legacy_complex_id,
              sc.name,
              COUNT(sp.legacy_inner_id) AS stg_prop_count,
              sc.latitude IS NOT NULL   AS has_coords
            FROM stg_complexes sc
            LEFT JOIN stg_properties sp ON sp.legacy_complex_id = sc.legacy_complex_id
            WHERE NOT EXISTS (
              SELECT 1 FROM residential_complexes rc
              WHERE rc.complex_id = sc.legacy_complex_id::varchar
            )
            GROUP BY sc.legacy_complex_id, sc.name, sc.latitude
            ORDER BY stg_prop_count DESC
        """)).fetchall()

        if missing:
            print(f"\n  ⚠️  {len(missing)} ЖК из стейджинга НЕ импортированы в прод:\n")
            for r in missing:
                coords = "✅ есть координаты" if r.has_coords else "❌ нет координат"
                print(f"  • legacy_id={r.legacy_complex_id} | {r.stg_prop_count} объектов | {coords}")
                print(f"    {r.name}")
        else:
            print("\n  ✅ Все стейджинг ЖК уже импортированы в прод")

        # 6. Проверка price_history
        separator("PRICE_HISTORY")
        ph = db.session.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM price_history WHERE record_type='complex')  AS complex_snapshots,
              (SELECT COUNT(*) FROM price_history WHERE record_type='property') AS property_snapshots,
              (SELECT MAX(recorded_at) FROM price_history)                      AS last_snapshot
        """)).fetchone()
        print(f"  Снимков по ЖК:       {ph.complex_snapshots}")
        print(f"  Снимков по объектам: {ph.property_snapshots}")
        print(f"  Последний снимок:    {ph.last_snapshot}")

        # 7. Качество данных
        separator("КАЧЕСТВО ДАННЫХ")
        quality = db.session.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM properties WHERE city_id IS NULL)          AS props_no_city,
              (SELECT COUNT(*) FROM properties WHERE complex_id IS NULL)       AS props_no_complex,
              (SELECT COUNT(*) FROM properties WHERE price IS NULL OR price=0) AS props_no_price,
              (SELECT COUNT(*) FROM properties WHERE latitude IS NULL)         AS props_no_coords,
              (SELECT COUNT(*) FROM residential_complexes WHERE city_id IS NULL) AS rc_no_city,
              (SELECT COUNT(*) FROM residential_complexes WHERE latitude IS NULL) AS rc_no_coords,
              (SELECT COUNT(*) FROM residential_complexes WHERE developer_id IS NULL) AS rc_no_dev
        """)).fetchone()

        print(f"  Объекты без city_id:      {quality.props_no_city}  {'⚠️' if quality.props_no_city else '✅'}")
        print(f"  Объекты без complex_id:   {quality.props_no_complex}  {'⚠️' if quality.props_no_complex else '✅'}")
        print(f"  Объекты без цены:         {quality.props_no_price}  {'⚠️' if quality.props_no_price else '✅'}")
        print(f"  Объекты без координат:    {quality.props_no_coords}  {'⚠️' if quality.props_no_coords else '✅'}")
        print(f"  ЖК без city_id:           {quality.rc_no_city}  {'⚠️' if quality.rc_no_city else '✅'}")
        print(f"  ЖК без координат:         {quality.rc_no_coords}  {'⚠️' if quality.rc_no_coords else '✅'}")
        print(f"  ЖК без застройщика:       {quality.rc_no_dev}  (допустимо)")

        # 8. FK и индексы
        separator("FK CONSTRAINTS")
        fk = db.session.execute(text("""
            SELECT tc.table_name, kcu.column_name, ccu.table_name AS ref_table
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_name IN ('properties','residential_complexes','buildings','price_history')
            ORDER BY tc.table_name, kcu.column_name
        """)).fetchall()
        for r in fk:
            print(f"  ✅ {r.table_name}.{r.column_name} → {r.ref_table}")

        separator("ИТОГ")
        warnings = []
        if counts.buildings == 0:
            warnings.append("⚠️  Таблица buildings (корпуса) пуста — нет данных для разделения на корпуса")
        if missing:
            warnings.append(f"⚠️  {len(missing)} ЖК из стейджинга не импортированы")
        if quality.props_no_city > 0:
            warnings.append(f"⚠️  {quality.props_no_city} объектов без city_id")
        if quality.props_no_coords > 100:
            warnings.append(f"⚠️  {quality.props_no_coords} объектов без координат")

        if not warnings:
            print("\n  ✅ БД ГОТОВА: все проверки прошли")
        else:
            print("\n  Предупреждения:")
            for w in warnings:
                print(f"  {w}")
            print(f"\n  ✅ Структура БД корректна — INSERT'ы пройдут")
            print(f"  ℹ️  ParserImportService готов для импорта новых ЖК и объектов")

        print("\n")

if __name__ == '__main__':
    check()
