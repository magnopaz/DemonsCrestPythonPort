"""Authored enemy definitions (``assets/authored/enemies.json``).

The visual Enemy Editor writes one definition per species key: stats, a
movement profile, attack patterns and sound slots.  ``Object`` code uses this
module only for lookups; the generic AI itself lives in ``object.py`` so it can
reuse the pool's spawn helpers and the game's 8.8 fixed-point behaviour.

Definitions are matched on ``(species, flags)``.  Entries with no flags match
the plain enemy sheet; boss palette variants set their flags explicitly.
"""

from __future__ import annotations

import json
import os

_ready = False
by_pair: dict[tuple[int, int], dict] = {}
by_key: dict[str, dict] = {}


def _num(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load(authored_dir: str) -> None:
    """Load the authored definitions once, at asset load time."""
    global _ready
    by_pair.clear()
    by_key.clear()
    path = os.path.join(authored_dir, "enemies.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            root = json.load(fh)
    except (OSError, ValueError):
        _ready = True
        return
    entries = root.get("enemies") if isinstance(root, dict) else None
    if not isinstance(entries, dict):
        _ready = True
        return
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        entry["_key"] = str(key)
        by_key[str(key)] = entry
        species = _num(entry.get("species"), -1)
        flags = _num(entry.get("flags"), 0)
        if species >= 0:
            by_pair[(species, flags)] = entry
            by_pair.setdefault((species, 0), entry)
    _ready = True


def loaded() -> bool:
    return _ready


def get(species: int, flags: int = 0) -> dict | None:
    """Definition for an object species, or None for the native handlers."""
    entry = by_pair.get((int(species), int(flags)))
    if entry is not None:
        return entry
    return by_pair.get((int(species), 0))


def status(species: int, flags: int = 0) -> dict | None:
    entry = get(species, flags)
    return entry.get("status") if entry else None


def movement(species: int, flags: int = 0) -> dict | None:
    entry = get(species, flags)
    return entry.get("movement") if entry else None


def attacks(species: int, flags: int = 0) -> list:
    entry = get(species, flags)
    value = entry.get("attacks") if entry else None
    return value if isinstance(value, list) else []


def sounds(species: int, flags: int = 0) -> dict:
    entry = get(species, flags)
    value = entry.get("sounds") if entry else None
    return value if isinstance(value, dict) else {}


FORM_DAMAGE_KEYS = ("fire", "buster", "claw", "demon_fire", "earth_ground",
                    "earth_air", "aerial", "tidal", "legendary", "ultimate")


def forms_damage(species: int, flags: int = 0):
    """Authored per-form damage row as a :class:`BossDamage`, or None.

    Uses exactly the ten column names of ``dcpy.bosses`` so authored
    content and the documented table share one vocabulary.  Values may
    be an int, a list (per-phase) or null (N/A: the form cannot hurt
    it).
    """
    from .bosses import BossDamage
    entry = get(species, flags)
    if entry is None:
        return None
    row = entry.get("forms_damage")
    if not isinstance(row, dict) or not row:
        return None
    kwargs = {}
    for key in FORM_DAMAGE_KEYS:
        value = row.get(key)
        if isinstance(value, list):
            value = tuple(int(v) for v in value)
        elif value is not None:
            value = int(value)
        if value is not None:
            kwargs[key] = value
    try:
        return BossDamage(**kwargs)
    except TypeError:
        return None
