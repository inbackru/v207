---
name: Blueprint endpoint aliases in templates
description: Templates use bare endpoint names (e.g. url_for('districts')) but Flask blueprints require prefixed names (e.g. url_for('districts.districts')). Key mapping + alias system internals.
---

# Blueprint Endpoint Aliases

After a DB restore, the app threw 500s due to BuildError for unresolved endpoint names in templates. The templates were written expecting bare names but blueprints require `blueprint_name.function_name` format.

## Blueprint name mapping

| Blueprint var | Blueprint name | Example endpoint |
|---|---|---|
| `districts_bp` | `districts` | `districts.districts`, `districts.district_detail` |
| `auth` bp | `auth` | `auth.login`, `auth.profile`, `auth.logout`, `auth.upload_user_avatar` |
| `admin_bp` | `adm` | `adm.admin_dashboard`, `adm.admin_blog_manager` |
| `manager_bp` | `mgr` | `mgr.manager_collections`, `mgr.manager_analytics` |
| `blog_bp` | `blog` | `blog.blog`, `blog.blog_post` |
| `props_bp` | `props` | `props.properties` |
| `main_bp` | `main` | `main.contacts` |
| `legal` bp | `legal` | `legal.privacy_policy`, `legal.user_agreement` |
| `search_geo_bp` | `search_geo_api` | `search_geo_api.search_results` |
| `city_pages` bp | `city_pages` | `city_pages.city_home` |
| `streets_bp` | `streets` | `streets.streets`, `streets.street_detail` |
| `mortgage_bp` | `mortgage` | `mortgage.*` |
| `partner_bp` | `partner` | `partner.*` |
| `favorites` bp | `favorites` | `favorites.*` |
| `applications` bp | `applications` | `applications.*` |

## The alias system — how it works

`app.py` (~line 231) defines `_ENDPOINT_ALIASES` dict mapping bare names → `blueprint.endpoint`.

**Critical**: The alias system patches **TWO** things:
1. `app.jinja_env.globals['url_for']` — Jinja2 templates
2. `flask.url_for` and `flask.helpers.url_for` — Python code in blueprints

Both patches must be in place. The Python-level patch was added after discovering that `url_for('dashboard')` in `routes/auth.py` Python code caused BuildError (alias only covered Jinja2).

**Why it works**: blueprints are imported at app.py lines 2483+, AFTER the patch at line 348, so `from flask import url_for` in blueprints gets the already-patched function.

**To add a new alias**: add to `_ENDPOINT_ALIASES` in `app.py`. Flask reports the correct name in the BuildError: "Did you mean 'auth.upload_user_avatar' instead?"

## How to find missing aliases

When a 500 BuildError hits:
1. Read the error: "Did you mean 'blueprint.endpoint' instead?" — add exactly that mapping.
2. Proactively scan templates: `grep -roh "url_for('[^']*')\|url_for(\"[^\"]*\")" templates/ | sort -u`
3. Check which bare names are NOT in `_ENDPOINT_ALIASES` and not already registered on the app directly.

## Direct app.py routes (no prefix needed, already in alias map)
- `dashboard` → `mgr_api.dashboard`
- `index` → `public_api.index`
- `careers` → `admin_api.careers`
- `security` → `admin_api.security`
- `upload_user_avatar` → `auth.upload_user_avatar`

## Trap: double-quoted url_for inside onclick JS strings

Templates can hide bare endpoint names inside JavaScript onclick attributes using double quotes, e.g.:
```html
<a onclick="location.href='{{ url_for("manager_dashboard") }}'" ...>
```
These are **invisible** to single-quoted grep patterns. Always also grep with double-quote pattern:
`grep -rn 'url_for("manager_' templates/`
Affected files found: `deals_kanban.html`, `deals_archive.html`, `employees.html`, `tasks_calendar.html`, `employee_profile.html` — all had `url_for("manager_dashboard")` or `url_for("manager_employees")` missing `mgr.` prefix inside onclick strings.
