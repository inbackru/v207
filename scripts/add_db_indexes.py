"""
Add PostgreSQL indexes for high-traffic filter columns.
Run once: python scripts/add_db_indexes.py
Safe to re-run (uses CREATE INDEX IF NOT EXISTS).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db

INDEXES = [
    # properties — most-filtered columns
    "CREATE INDEX IF NOT EXISTS idx_prop_city_id         ON properties(city_id)",
    "CREATE INDEX IF NOT EXISTS idx_prop_complex_id      ON properties(complex_id)",
    "CREATE INDEX IF NOT EXISTS idx_prop_rooms           ON properties(rooms)",
    "CREATE INDEX IF NOT EXISTS idx_prop_price           ON properties(price)",
    "CREATE INDEX IF NOT EXISTS idx_prop_area            ON properties(area)",
    "CREATE INDEX IF NOT EXISTS idx_prop_is_active       ON properties(is_active)",
    "CREATE INDEX IF NOT EXISTS idx_prop_floor           ON properties(floor)",
    "CREATE INDEX IF NOT EXISTS idx_prop_city_active     ON properties(city_id, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_prop_city_rooms      ON properties(city_id, rooms, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_prop_city_price      ON properties(city_id, price, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_prop_last_seen       ON properties(last_seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_prop_created_at      ON properties(created_at)",
    # residential_complexes
    "CREATE INDEX IF NOT EXISTS idx_rc_city_id           ON residential_complexes(city_id)",
    "CREATE INDEX IF NOT EXISTS idx_rc_is_active         ON residential_complexes(is_active)",
    "CREATE INDEX IF NOT EXISTS idx_rc_slug              ON residential_complexes(slug)",
    "CREATE INDEX IF NOT EXISTS idx_rc_coords            ON residential_complexes(latitude, longitude)",
    "CREATE INDEX IF NOT EXISTS idx_rc_city_active       ON residential_complexes(city_id, is_active)",
    # deals — manager CRM pipeline
    "CREATE INDEX IF NOT EXISTS idx_deals_manager_id     ON deals(manager_id)",
    "CREATE INDEX IF NOT EXISTS idx_deals_client_id      ON deals(client_id)",
    "CREATE INDEX IF NOT EXISTS idx_deals_status         ON deals(status)",
    "CREATE INDEX IF NOT EXISTS idx_deals_created_at     ON deals(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_deals_mgr_status     ON deals(manager_id, status)",
    # callback_requests — admin inbox
    "CREATE INDEX IF NOT EXISTS idx_cbr_created_at       ON callback_requests(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_cbr_status           ON callback_requests(status)",
    # saved_searches — alert matching
    "CREATE INDEX IF NOT EXISTS idx_ss_user_id           ON saved_searches(user_id)",
    # manager_notifications — polling
    "CREATE INDEX IF NOT EXISTS idx_mn_mgr_read          ON manager_notifications(manager_id, is_read)",
    "CREATE INDEX IF NOT EXISTS idx_mn_created_at        ON manager_notifications(created_at)",
    # price_history — charts
    "CREATE INDEX IF NOT EXISTS idx_ph_complex           ON price_history(complex_id, year, month)",
    "CREATE INDEX IF NOT EXISTS idx_ph_property          ON price_history(property_id, year, month)",
    # users — login & lookup
    "CREATE INDEX IF NOT EXISTS idx_users_phone          ON users(phone)",
    "CREATE INDEX IF NOT EXISTS idx_users_email          ON users(email)",
    # push_subscriptions
    "CREATE INDEX IF NOT EXISTS idx_push_user_id         ON push_subscriptions(user_id)",
    # property_alerts
    "CREATE INDEX IF NOT EXISTS idx_alerts_user_id       ON property_alerts(user_id)",
]

def run():
    with app.app_context():
        conn = db.engine.raw_connection()
        cur = conn.cursor()
        ok = fail = 0
        for sql in INDEXES:
            try:
                cur.execute(sql)
                conn.commit()
                name = sql.split('IF NOT EXISTS ')[1].split(' ON ')[0]
                print(f"  ✅ {name}")
                ok += 1
            except Exception as e:
                conn.rollback()
                print(f"  ⚠️  {e}")
                fail += 1
        cur.close()
        conn.close()
        print(f"\nDone: {ok} created/already exist, {fail} failed")

if __name__ == '__main__':
    print("Creating database indexes...")
    run()
