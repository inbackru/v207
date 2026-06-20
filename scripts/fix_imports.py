#!/usr/bin/env python3
"""Fix missing module imports in app.py"""

import re

# Read app.py
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: Replace performance_search with smart_search
content = content.replace(
    'from performance_search import super_search',
    'from smart_search import super_search'
)

# Fix 2: Remove notification_settings blueprint registration (it's already wrapped in try/except, but we can clean it up)
# Actually, it's already safe since it's in try/except, so we'll leave it

# Write back
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed imports:")
print("  - Changed performance_search → smart_search")
print("  - notification_settings already wrapped in try/except, left as is")
