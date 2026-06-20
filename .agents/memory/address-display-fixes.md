---
name: RC address display bugs
description: Address display logic in residential_complexes.html — known pitfalls, demotions, suppression rules
---

## Rule 1: address_city_district with мкр/квартал → demote to quarter
If `address_city_district` contains "мкр", "микрорайон", "кв-л", "квартал" it was extracted at microrayon level (not city-district level). Demote it to `_c_quarter`/`_locQuarter` and use `district` (FK name string) for the city okrug level instead.

**Why:** CIAN parse sometimes puts the мкр value in address_city_district. The PIP-assigned `district_id` → `district` string in complex_dict is the correct okrug.

**How to apply:** All three rendering blocks in residential_complexes.html: Jinja2 (~line 1788), JS card builder (~line 2017), JS list builder (~line 3164). Pattern:
```js
const acdIsMkr = /мкр|микрорайон|кв-л|квартал/i.test(acdRaw);
const distRaw = acdIsMkr ? (c.district || '') : (acdRaw || c.district || '');
// quarter: prefer address_quarter; else use demoted acdRaw
```

## Rule 2: strip region+city prefix from raw address before using as street
`complex.address` (CIAN fullAddress) starts with "Oblast, City, ..." for non-Krasnodar cities. The raw address stripping must strip `addr_region + ", "` FIRST, then city, then optionally quarter prefix.

**Why:** Krasnodar addresses start with city (no region prefix in CIAN), but Kursk/Belgorod addresses start with region. Original code only stripped city prefix starting at position 0.

## Rule 3: /тракт/ regex false-positive on "тракторных"
The ЖК-suppression regex checked for street keywords including `тракт` to avoid suppressing roads named "Симферопольский тракт". But "тракторных" (tractors) also matches. Fix: `тракт(?![а-яёА-ЯЁ])` — negative lookahead for Cyrillic.

## Rule 4: complex.district in template is a STRING, not ORM object
In complex_dict (routes/complexes.py), `'district': model.district.name if model.district else ''` stores the district NAME as a plain string. In Jinja2, `complex.district.name` returns Undefined (silent). Use `complex.district` directly.

## Data fixes (June 2026)
- `properties.developer_id` was out of sync with parent `rc.developer_id` for 1956 properties. Fix: propagate RC→property with `UPDATE properties SET developer_id = rc.developer_id FROM residential_complexes rc WHERE p.complex_id = rc.id AND rc.developer_id IS NOT NULL AND p.developer_id IS DISTINCT FROM rc.developer_id`.
- "Циан" (dev_id=151) was set as developer on 5 RCs and 543 properties — cleared to NULL (Циан is a portal, not a developer).
- Region id=3 had name "Россия" → corrected to "Курская область".
