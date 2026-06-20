# InBack — Real Estate Platform (Krasnodar Region)

A comprehensive real-estate platform for the Krasnodar region of Russia. Connects buyers with new-build properties, offers a cashback system (up to 500,000₽), interactive maps, and deep regional data integration.

## Run & Operate

- **Start app:** workflow `Start application` runs `gunicorn --bind 0.0.0.0:5000 --reuse-port --reload main:app`
- **Required env vars:** `DATABASE_URL` (PostgreSQL), `SESSION_SECRET` (Flask sessions)
- **Optional env vars:** see `SECRETS_AND_ENV.md` for the full list (Telegram, SendGrid, DaData, Yandex Maps, OAuth, OpenAI, SMS, etc.)
- **Background jobs:** set `ENABLE_SCHEDULER=true` to activate APScheduler tasks (price monitoring, alerts, geocoding, etc.)

## Stack

- **Backend:** Python 3.11, Flask 3, Flask-SQLAlchemy, Flask-Login, Flask-WTF, APScheduler, Gunicorn
- **Database:** PostgreSQL (36+ tables), SQLAlchemy ORM; falls back to SQLite in dev if no `DATABASE_URL`
- **Frontend:** Vanilla JS (ES6+), Tailwind CSS (CDN), Leaflet.js for maps, PWA support
- **Key services:** DaData (address normalization), Telegram bot (notifications), SendGrid (email), RedSMS (SMS), OpenAI (AI features), Yandex Maps

## Where things live

- `app.py` — main Flask application (routes, config, startup logic)
- `models.py` — SQLAlchemy models (User, Manager, Property, ResidentialComplex, Developer, etc.)
- `smart_search.py` — intelligent property search
- `services/` — geocoding, DaData client, alert service
- `templates/` — Jinja2 templates organized by role (admin, manager, partner, user)
- `static/` — JS, CSS, uploaded media
- `email_service.py`, `sms_service.py`, `telegram_bot.py` — notification services
- `social_auth.py` — OAuth via Google, VK, Mail.ru, Telegram
- `SECRETS_AND_ENV.md` — full guide to all required/optional secrets

## Architecture decisions

- Auth is custom Flask-Login + social OAuth (Google, VK, Mail.ru, Telegram Login Widget) — not Replit Auth, as it targets Russian social networks
- External integrations (Telegram, SendGrid, DaData, etc.) use API keys stored as Replit Secrets — no Replit-native integrations replace them since these are Russia-specific services
- APScheduler runs in-process for background jobs; controlled via `ENABLE_SCHEDULER` env var to avoid double-running in dev

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- Without `DATABASE_URL` set, the app falls back to SQLite (`properties.db`) — data will be empty
- Telegram notifications are silently skipped if `TELEGRAM_BOT_TOKEN` is not set
- `ENABLE_SCHEDULER=true` is set in the workflow command to activate background jobs
