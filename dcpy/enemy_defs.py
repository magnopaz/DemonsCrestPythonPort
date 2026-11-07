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
