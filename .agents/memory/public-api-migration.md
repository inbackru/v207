---
name: public_api blueprint migration
description: Patterns and gotchas when migrating routes from monolithic app.py to the public_api Blueprint
---

# public_api Blueprint Migration Lessons

## Module-level imports required
When `public_api.py` uses `PropertyRepository`, `ResidentialComplexRepository`, or `text` (SQLAlchemy), these must be imported at **module level** (top of file), not lazily inside every function.

```python
from repositories.property_repository import PropertyRepository, ResidentialComplexRepository
from sqlalchemy import text
```

**Why:** The original monolithic app.py had these at module scope. When extracted to a blueprint the functions inherited them from the global namespace; after extraction, there is no implicit global scope to inherit from.

## app.logger → current_app.logger
Any usage of `app.logger` (bare `app` object) inside a blueprint raises `NameError: name 'app' is not defined`. Replace with `current_app.logger` or the module-level `logger = logging.getLogger(__name__)`.

**How to apply:** `sed -i 's/\bapp\.logger\b/current_app.logger/g' routes/public_api.py`

## url_for endpoint aliases
After moving routes to blueprints, templates call `url_for('index')` but the endpoint is now `url_for('public_api.index')`. The fix is the `_ENDPOINT_ALIASES` dict in `app.py` fed into a custom `_aliased_url_for` Jinja2 global. All 35+ public_api endpoints are mapped there.

**Why:** 64+ template references use bare `'index'`; changing all templates is riskier than one alias dict.

## city_id_filter pattern
Several functions (e.g., `api_residential_complexes_full`) used `city_id_filter` as if it were a parameter but never initialized it from `request.args`. Always initialize at the top of the function:
```python
city_id_filter = request.args.get('city_id', type=int)
city_context = resolve_city_context(city_id=city_id_filter)
```

## 404 for missing DB records is correct
`/api/complex/<id>` returns 404 when the complex doesn't exist. The first active complex in production DB starts at id=32, not id=1.
