"""
Universal district-phrase generator for SEO.

Converts a district name + district_type into a correct Russian prepositional phrase.

Examples:
  format_district_phrase("Железнодорожный округ", "okrug")  → "в Железнодорожном округе"
  format_district_phrase("Прикубанский", "okrug")           → "в Прикубанском"
  format_district_phrase("Лазаревское", "settlement")       → "в Лазаревском"
  format_district_phrase("Красная Поляна", "settlement")    → "в посёлке Красная Поляна"
  format_district_phrase("Адлер", "settlement")             → "в посёлке Адлер"
  format_district_phrase("Победа", "microrayon")            → "в микрорайоне Победа"
  format_district_phrase("Советский район", "rayon")        → "в Советском районе"
  format_district_phrase("Центральный", "okrug")            → "в Центральном"
"""

# ---------------------------------------------------------------------------
# Adjective suffix sets
# ---------------------------------------------------------------------------

# Masculine / Feminine adjective endings that detect adjectival names
_ADJ_SUFFIXES_M = (
    'ский', 'цкий', 'жский', 'шский',
    'дный', 'жный', 'шный',
    'ной', 'ный',
    'ый', 'ой', 'ий',
)
# Neuter adjective endings (Лазаревское, Красное, Центральное…)
_ADJ_SUFFIXES_N = ('ское', 'цкое', 'дное', 'жное', 'шное', 'ное', 'ее', 'ое')

# ---------------------------------------------------------------------------
# Type-suffix table: (nominative, prepositional)
# Order matters: check longer strings first to avoid false hits
# ---------------------------------------------------------------------------
_TYPE_SUFFIXES = [
    ('микрорайон', 'микрорайоне'),
    ('жилрайон',   'жилрайоне'),
    ('жилмассив',  'жилмассиве'),
    ('массив',     'массиве'),
    ('квартал',    'квартале'),
    ('посёлок',    'посёлке'),
    ('поселок',    'посёлке'),
    ('округ',      'округе'),
    ('район',      'районе'),   # MUST come after микрорайон
    ('мкр',        'мкр.'),
]

# district_type → prepositional prefix used when name has NO type suffix
_DIST_TYPE_PREP = {
    'microrayon':  'в микрорайоне',
    'mikrorayon':  'в микрорайоне',
    'okrug':       'в округе',
    'district':    'в районе',
    'rayon':       'в районе',
    'settlement':  'в посёлке',
    'village':     'в посёлке',
    'hamlet':      'в посёлке',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_adjective(word: str) -> bool:
    """Return True if the word looks like a Russian adjective (any gender)."""
    return (
        any(word.endswith(s) for s in _ADJ_SUFFIXES_M)
        or any(word.endswith(s) for s in _ADJ_SUFFIXES_N)
    )


def _to_prepositional(word: str) -> str:
    """
    Convert a Russian adjective (masculine or neuter) to prepositional case.
    Неточная, но достаточная эвристика для SEO.
    """
    w = word
    # Neuter → treat like masculine (replace ending)
    for n_sfx, m_sfx in [
        ('ское', 'ский'), ('цкое', 'цкий'),
        ('дное', 'дный'), ('жное', 'жный'), ('шное', 'шный'),
        ('ное', 'ный'), ('ее', 'ий'), ('ое', 'ый'),
    ]:
        if w.endswith(n_sfx):
            w = w[:-len(n_sfx)] + m_sfx
            break

    # Masculine
    if w.endswith('ский') or w.endswith('цкий'):
        return w[:-4] + 'ском'
    if w.endswith('жский') or w.endswith('шский'):
        return w[:-5] + w[-5] + 'ском'
    if w.endswith('дный') or w.endswith('жный') or w.endswith('шный'):
        return w[:-2] + 'ом'
    if w.endswith('ной') or w.endswith('ный'):
        return w[:-2] + 'ом'
    if w.endswith('ый') or w.endswith('ой'):
        return w[:-2] + 'ом'
    if w.endswith('ий'):
        return w[:-2] + 'ем'
    return w


def _adj_phrase_from_words(words: list[str], type_prep: str | None) -> str:
    """
    Build 'в <adj-part-prepositional> [type_prep]' from a list of words.
    Words that look like adjectives are put in prepositional case;
    the type-suffix word is replaced with its prepositional form (passed via type_prep).
    """
    converted = []
    for w in words:
        if _is_adjective(w):
            converted.append(_to_prepositional(w))
        elif type_prep and w.lower() in {s for s, _ in _TYPE_SUFFIXES}:
            converted.append(type_prep)
        else:
            converted.append(w)
    return 'в ' + ' '.join(converted)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def format_district_phrase(name: str, district_type: str | None = None) -> str:
    """
    Return a correct Russian prepositional phrase for the district name.

    Args:
        name: District name as stored in DB (e.g. 'Железнодорожный округ', 'Красная Поляна')
        district_type: Value from districts.district_type column
            ('okrug', 'microrayon', 'settlement', 'rayon', 'district', etc.)

    Returns:
        Full phrase like 'в Железнодорожном округе', 'в посёлке Красная Поляна', etc.
    """
    if not name:
        return ''

    nl = name.lower().strip()
    words = name.split()

    # ── Step 1: Detect compound name with known type suffix ──────────────────
    # E.g. "Железнодорожный округ", "Советский район", "мкр Победа"
    for nom, prep in _TYPE_SUFFIXES:
        if nl == nom:
            # Name IS the type word (degenerate case) — just return "в <prep>"
            return f'в {prep}'
        if nl.endswith(' ' + nom):
            # Last word is the type suffix
            base_words = words[:-1]
            if base_words and all(_is_adjective(w) for w in base_words):
                # "Железнодорожный округ" → "в Железнодорожном округе"
                return 'в ' + ' '.join(_to_prepositional(w) for w in base_words) + ' ' + prep
            # Base not purely adjective (e.g. "5-й микрорайон")
            # Put whole phrase in "в ..." with type word in prep form
            rest = ' '.join(base_words)
            return f'в {rest} {prep}'
        if nl.startswith(nom + ' '):
            # Type word is FIRST: "мкр Победа", "район Горный"
            rest = ' '.join(words[1:])
            return f'в {prep} {rest}'

    # ── Step 2: Pure adjective name (no type suffix in name) ─────────────────
    # "Прикубанский", "Хостинский", "Лазаревское"
    if len(words) == 1 and _is_adjective(name):
        return 'в ' + _to_prepositional(name)

    # Multi-word: "Красносельский", "Западный" (single adj) already handled above
    # Multi-word adjective: "Ново-Западный", etc. — all-adjective check
    if all(_is_adjective(w) for w in words):
        return 'в ' + ' '.join(_to_prepositional(w) for w in words)

    # ── Step 3: Noun / settlement name — prefix with type label ─────────────
    # "Красная Поляна", "Адлер", "Победа", "Дагомыс"
    prefix = _DIST_TYPE_PREP.get(district_type or '', 'в')
    return f'{prefix} {name}'


def format_district_chip_label(name: str, district_type: str | None = None) -> str:
    """
    Short label for filter chips: just the name, no preposition.
    If the name already contains a type word, return it as-is.
    """
    return name


def district_type_label(district_type: str | None) -> str:
    """Human-readable label for a district_type value."""
    _labels = {
        'okrug':      'Округ',
        'microrayon': 'Микрорайон',
        'mikrorayon': 'Микрорайон',
        'settlement': 'Посёлок',
        'village':    'Посёлок',
        'hamlet':     'Посёлок',
        'rayon':      'Район',
        'district':   'Район',
    }
    return _labels.get(district_type or '', 'Район')
