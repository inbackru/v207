---
name: Admin blueprint gotchas
description: Durable lessons from fixing routes/admin.py (blueprint name 'adm') and app.py
---

## Circular imports in routes/admin.py
All helpers (`_load_enrich_settings`, `_save_enrich_settings`, `_load_city_config_all`, `scheduler`, `run_*` jobs, `_nearby_is_running`, `_load_nearby_settings`) must use lazy imports inside function bodies or be defined locally. Top-level imports from app.py cause circular import errors.

**Why:** routes/admin.py is imported by app.py; importing app.py from routes/admin.py at module-level creates a cycle.

**How to apply:** Any new helper in admin blueprint that needs app-level objects → define it locally with `from app import X` inside the function body.

## is_admin attribute missing on Admin model
`Admin` model has `role = db.Column(db.String(50))` not `is_admin`. Use `isinstance(current_user._get_current_object(), Admin)` for access checks in non-`@admin_required` routes.

**Why:** `current_user.is_admin` raises AttributeError inside the blueprint, causing 500.

**How to apply:** Replace `if not current_user.is_admin:` with `from models import Admin as _Admin; if not isinstance(current_user._get_current_object(), _Admin):` for API endpoints that use `@login_required` instead of `@admin_required`.

## Missing @app.route decorator on city-based functions
Some city-slug functions in app.py were defined without a `@app.route` decorator (e.g., `map_city`), causing `werkzeug.routing.BuildError` when `redirect_to_city_based()` tried to resolve the endpoint.

**Why:** Functions were stripped of decorators during earlier migrations/edits.

**How to apply:** If a `redirect_to_city_based('X')` call raises BuildError, grep app.py for `def X(city_slug)` and check the lines above for a `@app.route` decorator. Add `@app.route('/<city_slug>/slug')` if missing.

## UserBalance model columns
`available_amount` and `pending_amount` are Python `@property` aliases for `balance` and `pending_balance` DB columns. SQLAlchemy `func.sum()` / filter comparisons fail on properties — always use real column names in queries.

## Blog pagination
Blog uses `?page=N` query param, not `/blog/page/N` path. `/blog/page/1` legitimately returns 404.

## Template url_for blueprint prefix rules
- Admin templates: `url_for('adm.endpoint_name')`
- Blog templates: `url_for('blog.endpoint_name')` 
- Manager templates: `url_for('mgr.endpoint_name')`
- App-level routes (not in any blueprint): no prefix, e.g. `url_for('residential_complexes')`
