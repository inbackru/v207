#!/usr/bin/env python3
"""
Обогащение статусов квартир из TrendAgent API.

Для каждой квартиры в ЖК получает из TA API:
  - status.name        → properties.status
  - status.bkgrd_color → properties.ta_status_color
  - status.border_color→ properties.ta_status_border_color
  - area_kitchen       → properties.area_kitchen
  - plan.path+file_name→ properties.floor_plan_image (если не задано)
  - room.name_short    → used for display

Использование:
    python3 scripts/enrich_apartments_status.py --complex-id 876
    python3 scripts/enrich_apartments_status.py --complex-id 876 --dry-run
"""
import os, sys, json, time, argparse, logging
import requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app, db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

AUTH_URL = "https://auth.trendagent.ru/login"
API_BASE = "https://api.trendagent.ru/v4_29"
CDN_IMG  = "https://selcdn.trendagent.ru/images/"
PHONE    = os.environ.get("TRENDAGENT_PHONE", "+79524908269")
PASSWD   = os.environ.get("TRENDAGENT_PASSWORD", "m9vDhnr")
CITY_ID  = "604b5243f9760700074ac345"


def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":     "application/json",
        "Referer":    "https://krasnodar.trendagent.ru/",
    })
    return s


def login(s):
    r = s.get(AUTH_URL, params={"phone": PHONE, "password": PASSWD}, timeout=20)
    r.raise_for_status()
    token = r.json().get("data", {}).get("token")
    if not token:
        raise RuntimeError(f"Auth failed: {r.text[:200]}")
    s.headers["Authorization"] = f"Bearer {token}"
    logger.info("✅ Авторизован в TrendAgent")
    return token


def fetch_building_apartments(s, building_mongo_id, city_id=CITY_ID, count=100):
    """Загружает все квартиры корпуса из TA API постранично."""
    apartments = []
    offset = 0
    total = None
    while True:
        r = s.get(f"{API_BASE}/apartments/search/", params={
            "building": building_mongo_id,
            "city": city_id,
            "count": count,
            "offset": offset,
            "lang": "ru",
        }, timeout=30)
        if r.status_code != 200:
            logger.warning(f"HTTP {r.status_code} for building {building_mongo_id}")
            break
        data = r.json().get("data", {})
        items = data.get("list", [])
        if total is None:
            total = data.get("apartmentsCount", 0)
        apartments.extend(items)
        offset += len(items)
        if not items or (total and offset >= total) or len(items) < count:
            break
        time.sleep(0.3)
    return apartments


def plan_url(plan: dict) -> str:
    if not plan:
        return ""
    path = plan.get("path", "")
    fname = plan.get("file_name", "")
    if path and fname:
        return f"{CDN_IMG}{path}{fname}"
    return ""


def enrich_complex(complex_id: int, dry_run: bool = False):
    s = make_session()
    login(s)

    with app.app_context():
        buildings = db.session.execute(db.text("""
            SELECT id, name, building_id
            FROM buildings
            WHERE complex_id = :cid
            ORDER BY name
        """), {"cid": complex_id}).fetchall()

        if not buildings:
            logger.error(f"Нет корпусов для complex_id={complex_id}")
            return

        logger.info(f"Корпусов: {len(buildings)}")

        total_updated = 0
        total_notfound = 0

        for bld in buildings:
            logger.info(f"  Корпус: {bld.name} (mongo_id={bld.building_id})")
            if not bld.building_id:
                logger.warning(f"    Нет building_id (MongoDB), пропускаем")
                continue

            apts = fetch_building_apartments(s, bld.building_id)
            logger.info(f"    Загружено из API: {len(apts)} квартир")

            # Build lookup: external_id (ta_apt_{_id}) → apt, and crm_id → apt
            by_external = {}
            by_crm = {}
            for apt in apts:
                mongo_id = apt.get("_id", "")
                if mongo_id:
                    by_external[f"ta_apt_{mongo_id}"] = apt
                crm = apt.get("crm_id", "")
                if crm:
                    try:
                        by_crm[int(crm)] = apt
                    except (ValueError, TypeError):
                        pass

            # Fetch our DB properties for this building
            db_props = db.session.execute(db.text("""
                SELECT id, external_id, ta_crm_id
                FROM properties
                WHERE building_id = :bid AND complex_id = :cid
            """), {"bid": bld.id, "cid": complex_id}).fetchall()

            logger.info(f"    В БД: {len(db_props)} квартир")

            updated = 0
            not_found = 0
            for prop in db_props:
                # Match by external_id first, then by crm_id
                apt = by_external.get(prop.external_id)
                if apt is None and prop.ta_crm_id:
                    apt = by_crm.get(int(prop.ta_crm_id))

                if apt is None:
                    not_found += 1
                    continue

                status_obj = apt.get("status", {})
                room_obj   = apt.get("room", {})
                plan_obj   = apt.get("plan", {})
                status_name   = status_obj.get("name", "")
                status_color  = status_obj.get("bkgrd_color", "")
                status_border = status_obj.get("border_color", "")
                kitchen_area  = apt.get("area_kitchen")
                plan_img      = plan_url(plan_obj)
                room_short    = room_obj.get("name_short", "")

                if not dry_run:
                    db.session.execute(db.text("""
                        UPDATE properties SET
                            status                 = CASE WHEN :sname != '' THEN :sname ELSE status END,
                            ta_status_color        = CASE WHEN :scolor != '' THEN :scolor ELSE ta_status_color END,
                            ta_status_border_color = CASE WHEN :sborder != '' THEN :sborder ELSE ta_status_border_color END,
                            area_kitchen           = CASE WHEN :akitch IS NOT NULL THEN :akitch ELSE area_kitchen END,
                            floor_plan_image       = CASE WHEN :planimg != '' AND (floor_plan_image IS NULL OR floor_plan_image = '') THEN :planimg ELSE floor_plan_image END,
                            property_type          = CASE WHEN :rshort != '' THEN :rshort ELSE property_type END
                        WHERE id = :pid
                    """), {
                        "sname":   status_name,
                        "scolor":  status_color,
                        "sborder": status_border,
                        "akitch":  kitchen_area,
                        "planimg": plan_img,
                        "rshort":  room_short,
                        "pid":     prop.id,
                    })
                updated += 1

            if not dry_run:
                db.session.commit()

            logger.info(f"    Обновлено: {updated}, не найдено: {not_found}")
            total_updated += updated
            total_notfound += not_found
            time.sleep(0.3)

        logger.info(f"\n✅ Итого: обновлено {total_updated}, не найдено {total_notfound}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--complex-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    enrich_complex(args.complex_id, dry_run=args.dry_run)
