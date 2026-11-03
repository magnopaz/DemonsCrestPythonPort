#!/usr/bin/env python3
"""Insert the known boss objects into the generated room documents.

`check_bosses.py` already carries the authoritative area -> (name, species,
flags, x, y) table (recovered from save states and probes).  A clean
`extract.py` run does not produce those objects, because the retail object
lists in the ROM do not include the boss entries for every room.  This tool
applies the table so a fresh extraction reaches the documented state:

  python tools/dc_extract/apply_boss_table.py --rooms assets/generated

It is idempotent: an existing boss with the same species is replaced in place,
anything else is appended.  Run it after `extract.py` and before the regression.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from check_bosses import BOSSES  # noqa: E402

# Bosses the checker does not assert (it covers the mid/end-game set).  Area 0's
# Somulo comes from the ROM object list at (32, 88), which is behind the player
# and outside the camera, so the colosseum duel never starts: shots fly right
# into empty air and the six-hit check only lands one.  The arena's own save
# (`lvl_0_murkland-colosseum`) puts the fight in the right half of the 768 px
# room; 380 keeps him in view of the spawn at x=128.
EXTRA: dict[int, list[tuple[str, int, int | None, int, int]]] = {
    0: [("Somulo", 0x33, 128, 380, 170)],
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rooms", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    changed = 0
    table = {**BOSSES, **EXTRA}
    for area, entries in sorted(table.items()):
        path = args.rooms / f"room_area{area}.json"
        if not path.is_file():
            print(f"area {area}: missing {path.name}, skipped")
            continue
        doc = json.loads(path.read_text())
        objects = doc.setdefault("objects", [])
        expected = {species for _n, species, _f, _x, _y in entries}
        # Areas 52/54 shipped a placeholder boss ($96) at the real boss position.
        # Any boss species the table does not list for this area is a stale
        # placeholder: retype it instead of deleting it, so the retail record
        # stays in the room (it draws as an unknown-species placeholder) and the
        # real boss can still be spawned next to it.
        stale = [i for i, obj in enumerate(objects)
                 if obj.get("type") == "boss" and obj.get("species") not in expected]
        for i in stale:
            print(f"area {area}: stale boss {objects[i].get('species'):#04x} "
                  f"kept as an unknown placeholder")
            objects[i]["type"] = "unknown"
        for name, species, flags, x, y in entries:
            entry = {"type": "boss", "species": species,
                     "flags": 0 if flags is None else flags, "x": x, "y": y,
                     "source": "boss_table"}
            replaced = False
            for i, obj in enumerate(objects):
                if obj.get("type") == "boss" and obj.get("species") == species:
                    if flags is None:
                        entry["flags"] = obj.get("flags", 0)
                    # A replacement keeps the ROM's provenance: the position is
                    # the object list's, not the table's.
                    entry["source"] = obj.get("source", "rom")
                    objects[i] = entry
                    replaced = True
                    break
            if not replaced:
                objects.append(entry)
            print(f"area {area} ({name}): species {species:#04x} at {x},{y} "
                  f"flags={entry['flags']} ({'replaced' if replaced else 'added'})")
            changed += 1
        if not args.dry_run:
            path.write_text(json.dumps(doc, indent=1))
    print(f"{changed} boss entries applied to {len(BOSSES)} areas"
          f"{' (dry run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
