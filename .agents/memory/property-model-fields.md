---
name: Property model field names
description: Non-obvious column names on the Property ORM model
---

# Property Model: Non-obvious Field Names

## Key fields
- **Area**: `p.area` (NOT `total_area` — `total_area` does not exist)
- **Coordinates**: `p.latitude`, `p.longitude` (Float, nullable)
- **District link**: `p.district_id` (FK to districts.id, was NULL for all properties until bulk assignment)
- **Street text**: `p.parsed_street` (text field, not a FK)
- **District text**: `p.parsed_district` (text field, often empty)

**Why:** Caused a silent `AttributeError` in district property listing — `except Exception: district_properties = []` swallowed it, template showed 0 properties despite 17K in DB.
