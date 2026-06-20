"""
Property utility functions for InBack platform.
Shared helpers used across scraping scripts and app routes.
"""

import re

_ROOM_LABELS = {
    0: 'Студия',
    1: '1-комн',
    2: '2-комн',
    3: '3-комн',
    4: '4-комн',
    5: '5-комн',
    6: '6-комн+',
}

_BAD_TITLE_RE = re.compile(r'^(None|null|undefined)', re.IGNORECASE)


def rooms_label(rooms) -> str:
    """
    Return a human-readable room label for the given rooms count.
    Safely handles None/invalid values — always returns a valid string.

    Examples:
        rooms_label(0)    -> 'Студия'
        rooms_label(None) -> 'Студия'
        rooms_label(2)    -> '2-комн'
        rooms_label(7)    -> '7-комн'
    """
    try:
        r = int(rooms) if rooms is not None else 0
    except (ValueError, TypeError):
        r = 0
    return _ROOM_LABELS.get(r, f'{r}-комн')


def sanitize_property_title(title, rooms=None, area=None, floor=None, total_floors=None) -> str:
    """
    Sanitize a property title, fixing common scraping artefacts.

    Problems fixed:
    - "Noneк, 26.8 м², 1/16 эт."  → "Студия, 26.8 м², 1/16 эт."
    - "Nullк, ..."                  → rebuilt from rooms/area/floor
    - Empty / None                  → rebuilt from available fields

    Args:
        title       : raw title string (may be None or malformed)
        rooms       : int or None — number of rooms (0 = studio)
        area        : float or None — area in m²
        floor       : int or None — floor number
        total_floors: int or None — total floors in building

    Returns:
        Cleaned title string, never None, never empty.
    """
    if title and not _BAD_TITLE_RE.match(str(title).strip()):
        return str(title).strip()

    label = rooms_label(rooms)

    if area and floor and total_floors:
        return f'{label}, {area} м², {floor}/{total_floors} эт.'
    if area:
        return f'{label}, {area} м²'
    return label
