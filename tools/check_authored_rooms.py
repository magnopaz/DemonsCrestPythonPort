#!/usr/bin/env python3
"""Keep the authored-room overlay from silently reverting engine fixes.

``dcpy/level.py::_load_room_with_override`` reads ``assets/authored/rooms``
before the generated tree, so an authored room wins at runtime.  That is the
editor's save format, but it also means a stale or hand-edited authored room
can quietly undo verified geometry: commit 8ec5e85 shipped authored rooms 0
and 4 whose Somulo stood on the player's spawn and whose door table replaced
the after-boss gate with four duplicates -- the Somulo demos went red and
nothing pointed at the overlay (docs/SOMULO_ROOM_FIX.md).

This checker compares every authored room with its generated base on the
fields the engine's checks are calibrated against:

* boss records (species/flags/position -- the fight geometry),
* the transition/door table,
* the spawn records,
* ``gate_next_area``,
* the arena bounds (``world``/``camera``/``play``).

Any difference is a failure unless the area is whitelisted below with a
reason.  Editing a room in the editor is fine; changing one of these fields
is a regression until the whitelist says otherwise.  Everything else
(backdrops, collision tweaks, decor objects) is reported as a note, not an
error -- the cemetery BG1 fix lives there.

Usage:
  python3 tools/check_authored_rooms.py [--assets assets/generated]

Exit codes: 0 = pass, 1 = contract failure, 77 = assets missing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# area -> {field: reason}.  Add an entry only with a measured justification;
# the checker exists so this list stays short.
WHITELIST: dict[int, dict[str, str]] = {}

# Fields whose authored value must equal the generated one.
CRITICAL = ("bosses", "transitions", "spawn", "spawns", "gate_next_area",
            "world", "camera", "play")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    return ap.parse_args()


def critical_view(room: dict) -> dict:
    """The engine-critical slice of a room document."""
    objects = room.get("objects") or []
    bosses = sorted(
        json.dumps({"species": o.get("species"), "flags": o.get("flags"),
                    "x": o.get("x"), "y": o.get("y")}, sort_keys=True)
        for o in objects if o.get("type") == "boss")
    transitions = sorted(json.dumps(t, sort_keys=True)
                          for t in (room.get("transitions") or []))
    return {
        "bosses": bosses,
        "transitions": transitions,
        "spawn": room.get("spawn"),
        "spawns": room.get("spawns"),
        "gate_next_area": room.get("gate_next_area"),
        "world": room.get("world"),
        "camera": room.get("camera"),
        "play": room.get("play"),
    }


def main() -> int:
    args = parse_args()
    assets = args.assets.resolve()
    authored_dir = assets.parent / "authored" / "rooms"
    if not assets.is_dir():
        print(f"authored rooms: missing assets dir {assets}")
        return 77

    errors: list[str] = []
    checked = 0
    notes: list[str] = []
    for path in sorted(authored_dir.glob("room_area*.json")):
        try:
            area = int(path.stem.replace("room_area", ""))
        except ValueError:
            continue
        generated = assets / path.name
        if not generated.is_file():
            errors.append(f"area {area}: authored room has no generated base")
            continue
        try:
            authored = json.loads(path.read_text())
            base = json.loads(generated.read_text())
        except json.JSONDecodeError as exc:
            errors.append(f"area {area}: invalid JSON ({exc})")
            continue
        checked += 1
        allowed = WHITELIST.get(area, {})
        view_a = critical_view(authored)
        view_b = critical_view(base)
        for field in CRITICAL:
            if view_a[field] == view_b[field]:
                continue
            if field in allowed:
                notes.append(f"area {area}: {field} differs (whitelisted: "
                             f"{allowed[field]})")
                continue
            errors.append(f"area {area}: {field} differs from the generated "
                           f"room")
        # Informational: how far the authored copy drifted overall.
        drift = [key for key in set(authored) | set(base)
                 if authored.get(key) != base.get(key)]
        if drift:
            notes.append(f"area {area}: {len(drift)} top-level key(s) differ "
                         f"overall: {', '.join(sorted(drift))}")

    print(f"authored rooms: {checked} overlay(s) checked, "
          f"{len(errors)} error(s)")
    for note in notes:
        print(f"  note: {note}")
    for error in errors:
        print(f"  ERROR {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
