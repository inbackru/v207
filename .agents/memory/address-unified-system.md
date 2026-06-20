---
name: Unified address system for RC and properties
description: Architecture for filling, propagating, and searching RC/property addresses across all cities
---

# Unified Address System

## Address fields per entity

**ResidentialComplex:**
- `address` — raw full address string
- `addr_region`, `addr_city`, `address_city_district` (okrug/жилрайон), `address_quarter` (мкр), `addr_street`, `addr_house`
- Filled by: `fix_jk_bulk.py` (CIAN typed JSON, authoritative) → `parse_cian_addresses.py` (raw string fallback)

**Property:**
- `address` — raw string
- `parsed_city`, `parsed_area` (okrug), `parsed_settlement` (мкр), `parsed_street`, `parsed_house`, `parsed_block`
- FK: `complex_id` → `residential_complexes.id` (NOT `residential_complex_id`)
- FK: `district_id` → `districts.id`
- Filled by: geocoding scripts OR **propagation from parent RC** (see below)

## Propagation pipeline

RC address → Property propagation:
```
fix_jk_bulk.py (CIAN) → parse_cian_addresses.py → propagate_rc_address.py
```
- `scripts/propagate_rc_address.py` copies `rc.address_city_district` → `p.parsed_area`, `rc.address_quarter` → `p.parsed_settlement`, `rc.addr_street` → `p.parsed_street`, `rc.addr_city` → `p.parsed_city`
- Runs automatically in admin auto-pipeline (after parse_cian_addresses)
- Admin button at `/admin/enrichment` → POST `/admin/enrichment/propagate-address`

**Why:** Properties don't have their own okrug/quarter source; they must inherit from parent RC. Without propagation, district search misses 90%+ of properties.

## COALESCE order in parse_cian_addresses.py

`COALESCE(existing, parsed_new)` — existing values (from fix_jk_bulk.py typed JSON) are preserved; parse only fills NULLs.

**Why:** fix_jk_bulk.py uses CIAN typed JSON (most authoritative); parse_cian_addresses uses heuristic string parsing (fallback). Old order was reversed and overwrote authoritative data.

## fix_jk_bulk.py _extract_address() region filter

Removed Krasnodar-only filter (`re.search(r'краснода|сочи|адыге', addr)`). The `fullAddress` field on CIAN pages is always the current RC's address — filtering by region blocked Kursk/Belgorod addresses.

## PropertyRepository district filter

All district OR conditions include:
- `ResidentialComplex.address_city_district.ilike(f'%{name}%')`
- `ResidentialComplex.address_quarter.ilike(f'%{name}%')`

This finds properties whose RC has the district but where `parsed_area` is still NULL (before propagation runs).

## Search suggestions

`/api/search/suggestions` now queries RC address fields before the districts table:
- `address_city_district` → type=district suggestions with property counts
- `address_quarter` → type=district (Микрорайон) suggestions
- `addr_street` → type=address suggestions

The districts table has low-quality data (many ЖК names as districts); RC fields are from CIAN typed JSON = better.

## Current coverage (as of June 2026)

RC fill rates: Krasnodar 7% okrug, Sochi 12%, Kursk 12%, Maykop 0%
Property fill rates after propagation: Krasnodar 96% street, 6% okrug; Kursk 68% okrug; Sochi 92% street

Low okrug fill means user needs to run force CIAN enrichment for all cities to get more `address_city_district` values, then propagate.
