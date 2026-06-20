---
name: Missing imports pattern
description: Recurring NameError bugs from models/stdlib symbols used without import in blueprint files
---

## The rule
`Manager`, `timedelta`, `get_districts_list`, `get_developers_list` are NOT imported at the top of every blueprint file. Always add a local or module-level import before first use.

**Why:** Blueprint files import only what they need from `app` and `models`; models aren't star-imported. `timedelta` is often imported locally inside one function but used bare in another function in the same file.

**How to apply:**
- `routes/comparison.py` — added `from models import Manager` at module level (line 22); covers all 6 usages.
- `routes/properties.py` — add `from models import Manager` as local import before isinstance check.
- `routes/manager.py` — add `from datetime import timedelta` locally in `manager_tasks_calendar` and `manager_employee_profile`; add `from app import get_districts_list, get_developers_list` locally in `manager_dashboard`.
- `routes/manager_api.py` — add `from datetime import timedelta` locally in `api_get_manager_notifications`.
- When adding a new blueprint, check that every model class and stdlib symbol used is explicitly imported.
