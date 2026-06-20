---
name: Chat blueprint imports and comparison route bugs
description: Known import gaps in chat.py and comparison.py that cause 500 errors
---

## Rules

1. `routes/chat.py` — must import `session` from flask: `from flask import Blueprint, jsonify, request, current_app, session`. Without it, `api_chat_unread()` crashes with NameError on unauthenticated requests (guest path).

2. `routes/comparison.py` — `api_manager_generate_comparison_pdf()` used bare `app` (NameError). Fixed to `current_app`. Always use `current_app` inside blueprint routes, never `app`.

3. `routes/comparison.py` — requires `from unidecode import unidecode` (pip package `unidecode`). Must be installed separately.

4. `weasyprint` (pip package) required for PDF generation in `routes/presentations.py`. Both packages now installed.

5. Rate limit default was 200/hour — too low when multiple pages poll `/api/chat/unread`. Raised to 1000/hour in `security_config.py`.

**Why:** All these caused silent 500s visible only in browser console, not in gunicorn logs (gunicorn logs lacked HTTP access log lines for API calls).

**How to apply:** When adding new routes to comparison.py or chat.py, always check imports at the top of the file. Use `current_app` not `app` in blueprints.
