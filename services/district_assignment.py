"""
Automatic district assignment service.
Pipeline: CIAN parser data → district_id on RC → cascades to all properties.

Priority order:
  1. address_quarter (settlement: Красная Поляна, Адлер, Лазаревское, …)
  2. address_city_district (admin district: Адлерский, Хостинский, Карасунский, …)
  3. Coordinate-based lookup (lat/lng proximity to district centroid)
  4. Leave NULL (manual assignment later)
"""

import logging
import math
from sqlalchemy import func, or_
from app import db
from models import District, ResidentialComplex, Property

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, strip common suffixes for fuzzy matching."""
    if not text:
        return ''
    t = text.strip().lower()
    for suffix in (' округ', ' район', ' мкр', ' микрорайон', ' поселение', ' пос.', ' пос '):
        t = t.replace(suffix, '')
    return t.strip()


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Distance in km between two lat/lng points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assign_district_to_rc(rc: ResidentialComplex, commit: bool = False) -> bool:
    """
    Tries to find and set rc.district_id. Returns True if assignment was made.

    Call after setting rc.address_quarter / rc.address_city_district / rc.latitude / rc.longitude.
    """
    if rc.district_id is not None:
        return False  # already assigned

    city_id = rc.city_id
    if not city_id:
        return False

    district_id = (
        _match_by_quarter(rc.address_quarter, city_id)
        or _match_by_admin_district(rc.address_city_district, city_id)
        or _match_by_coordinates(rc.latitude, rc.longitude, city_id)
    )

    if district_id:
        rc.district_id = district_id
        logger.info(f"[district_assignment] RC {rc.id} '{rc.name}' → district_id={district_id}")
        if commit:
            db.session.commit()
        return True

    logger.debug(f"[district_assignment] RC {rc.id} '{rc.name}' — no district match found")
    return False


def cascade_rc_district_to_properties(rc: ResidentialComplex, commit: bool = False) -> int:
    """
    Propagates rc.district_id to all properties in the RC where district_id differs.
    Returns count of updated properties.
    """
    if not rc.district_id:
        return 0

    updated = (
        db.session.query(Property)
        .filter(
            Property.complex_id == rc.id,
            Property.is_active == True,
            or_(Property.district_id == None, Property.district_id != rc.district_id)
        )
        .update({'district_id': rc.district_id}, synchronize_session=False)
    )

    if updated:
        logger.info(f"[district_assignment] Cascaded district_id={rc.district_id} to {updated} properties of RC {rc.id}")
        if commit:
            db.session.commit()

    return updated


def full_pipeline(rc: ResidentialComplex, commit: bool = True) -> dict:
    """
    Full pipeline: assign district to RC + cascade to properties.
    Returns {'assigned': bool, 'updated_properties': int, 'district_id': int|None}
    """
    assigned = assign_district_to_rc(rc, commit=False)
    updated = cascade_rc_district_to_properties(rc, commit=False)

    if commit and (assigned or updated):
        db.session.commit()

    return {
        'assigned': assigned,
        'updated_properties': updated,
        'district_id': rc.district_id,
    }


def run_batch_for_city(city_id: int, overwrite: bool = False) -> dict:
    """
    Batch pipeline for all RCs in a city without a district_id (or all if overwrite=True).
    Use from admin panel or CLI after adding new districts.

    Returns {'processed': int, 'assigned': int, 'properties_updated': int}
    """
    query = db.session.query(ResidentialComplex).filter(ResidentialComplex.city_id == city_id)
    if not overwrite:
        query = query.filter(ResidentialComplex.district_id == None)

    rcs = query.all()
    total_assigned = 0
    total_props = 0

    for rc in rcs:
        if overwrite:
            rc.district_id = None  # reset so assign_district_to_rc will run

        res = full_pipeline(rc, commit=False)
        if res['assigned']:
            total_assigned += 1
        total_props += res['updated_properties']

    if rcs:
        db.session.commit()

    logger.info(
        f"[district_assignment] Batch city_id={city_id}: "
        f"{len(rcs)} RCs processed, {total_assigned} assigned, {total_props} properties updated"
    )

    return {'processed': len(rcs), 'assigned': total_assigned, 'properties_updated': total_props}


# ---------------------------------------------------------------------------
# Match strategies
# ---------------------------------------------------------------------------

def _match_by_quarter(quarter: str, city_id: int) -> int | None:
    """Match address_quarter (settlement name) against districts of type settlement/microrayon."""
    if not quarter or not quarter.strip():
        return None

    norm_q = _normalize(quarter)

    # First: exact name match (case-insensitive)
    candidates = (
        db.session.query(District)
        .filter(
            District.city_id == city_id,
            District.district_type.in_(['settlement', 'microrayon', 'district'])
        )
        .all()
    )

    best = None
    for d in candidates:
        if _normalize(d.name) == norm_q:
            return d.id  # exact match → done
        # Partial: district name contained in quarter string or vice versa
        if _normalize(d.name) in norm_q or norm_q in _normalize(d.name):
            best = d.id

    return best


def _match_by_admin_district(admin_district: str, city_id: int) -> int | None:
    """Match address_city_district (okrug/admin name) against all district types."""
    if not admin_district or not admin_district.strip():
        return None

    norm_a = _normalize(admin_district)

    candidates = (
        db.session.query(District)
        .filter(District.city_id == city_id)
        .all()
    )

    best = None
    for d in candidates:
        if _normalize(d.name) == norm_a:
            return d.id
        if _normalize(d.name) in norm_a or norm_a in _normalize(d.name):
            best = d.id

    return best


def _match_by_coordinates(lat, lon, city_id: int, max_km: float = 20.0) -> int | None:
    """Find closest district centroid within max_km radius."""
    if lat is None or lon is None:
        return None

    candidates = (
        db.session.query(District)
        .filter(
            District.city_id == city_id,
            District.latitude.isnot(None),
            District.longitude.isnot(None),
        )
        .all()
    )

    best_id = None
    best_dist = max_km

    for d in candidates:
        dist = _haversine_km(lat, lon, d.latitude, d.longitude)
        if dist < best_dist:
            best_dist = dist
            best_id = d.id

    if best_id:
        logger.debug(f"[district_assignment] Coord match: dist={best_dist:.2f}km → district_id={best_id}")

    return best_id
