---
name: SEO seo_city.py dict structure
description: Two-dict SEO architecture in routes/seo_city.py, fallback lookup pattern, and the intro-text isinstance bug.
---

## Structure

`routes/seo_city.py` has two top-level dicts:

1. **`_SEO_NOVOSTROJKI_SLUGS`** (line 27 → ~line 3794):
   - Primary source of slug configs: `{title, h1, description, keywords, rooms, price_max, price_min, …}`
   - Handler `properties_city_seo` does `_SEO_NOVOSTROJKI_SLUGS.get(filter_slug)` first.

2. **`_SEO_INTRO_TEXTS`** (line 3799 → ~line 6223):
   - Mixed dict: most values are `str` or `tuple` of HTML paragraphs (intro text).
   - Some entries are full dict-style slug configs (title/h1/description/etc.) that ended up here instead of `_SEO_NOVOSTROJKI_SLUGS` — this happens when new slugs are added near the closing `}` of `_SEO_INTRO_TEXTS`.

## Fallback added to handler (properties_city_seo)

```python
seo_config = _SEO_NOVOSTROJKI_SLUGS.get(filter_slug)
if not seo_config:
    _intro_entry = _SEO_INTRO_TEXTS.get(filter_slug)
    if isinstance(_intro_entry, dict) and 'h1' in _intro_entry:
        seo_config = _intro_entry
    else:
        return redirect(...)
```

## Intro text isinstance fix

When `seo_config` comes from `_SEO_INTRO_TEXTS` (a dict), the same dict is also returned by `_SEO_INTRO_TEXTS.get(filter_slug)` for the intro text. Without the isinstance guard, calling `.replace()` on a dict raises AttributeError → 500.

Fixed at the `seo_intro` assignment:
```python
_intro_raw = _SEO_INTRO_TEXTS.get(filter_slug, '')
if isinstance(_intro_raw, dict):
    seo_intro = ''           # dict-style entry: no intro text
elif isinstance(_intro_raw, tuple):
    seo_intro = ''.join(_intro_raw).replace(...)
elif _intro_raw:
    seo_intro = _intro_raw.replace(...)
else:
    seo_intro = ''
```

**Why:** New slug entries added to `_SEO_INTRO_TEXTS` block instead of `_SEO_NOVOSTROJKI_SLUGS` block — this is easy to do when editing near the closing `}` of the wrong dict. Always verify which dict a closing `}` belongs to before editing.

**How to apply:** When adding new SEO slug dict entries, confirm they land inside `_SEO_NOVOSTROJKI_SLUGS` (ends ~line 3794). Run the brace-matching script to verify: `python3 -c "...find matching } for _SEO_NOVOSTROJKI_SLUGS..."`.
