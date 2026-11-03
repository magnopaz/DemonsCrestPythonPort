#!/usr/bin/env python3
"""Add or replace boss objects in a generated room from a save/probe mapping.

Usage:
  python tools/dc_extract/add_room_boss.py --room assets/generated/room_area26.json \
    --bosses "123:1320:154,124:1380:154"

  # Optional fourth field preserves/sets the object flags (palette variant).
  python tools/dc_extract/add_room_boss.py --room assets/generated/room_area23.json \
    --bosses "165:640:1932:2"

Each spec is species:x:y[:flags]. Existing boss entries with the same species
are replaced in place; otherwise the entry is appended. If flags are omitted
on a replacement, the existing flags are kept.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--room", type=Path, required=True)
    ap.add_argument("--bosses", required=True)
    args = ap.parse_args()
    data = json.loads(args.room.read_text())
    objects = data.setdefault("objects", [])
    for spec in [s for s in args.bosses.split(",") if s.strip()]:
        fields = [int(v, 0) for v in spec.split(":")]
        species, x, y = fields[:3]
        requested_flags = fields[3] if len(fields) > 3 else None
        entry = {"type": "boss", "species": species, "flags": 0,
                 "x": x, "y": y}
        replaced = False
        for i, obj in enumerate(objects):
            if obj.get("type") == "boss" and obj.get("species") == species:
                if requested_flags is not None:
                    entry["flags"] = requested_flags
                else:
                    entry["flags"] = obj.get("flags", 0)
                objects[i] = entry
                replaced = True
                break
        if not replaced:
            entry["flags"] = requested_flags or 0
            objects.append(entry)
        print(f"boss {species:#04x} at {x},{y} flags={entry['flags']} "
              f"({'replaced' if replaced else 'added'})")
    args.room.write_text(json.dumps(data, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
