#!/usr/bin/env python3
"""Merge object placements observed in probe saves into the room JSONs.

The room extractor only reads each area's object-list entry, so scripted or
chunk-streamed objects are missing. The probes contain the live pool (slot,
species, x, y), which is exactly those placements.

Only species with a known object type are merged (see SPECIES_KIND); unknown
species are reported per area so they can be classified deliberately instead of
spawning junk. Duplicates are deduplicated on a 16x16 grid per species.

Usage:
  python tools/dc_extract/merge_probe_placements.py --probes <...>/oracle_probe \
      --rooms assets/generated [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

# Species we know how to place. 0x96 is handled by merge_npc_objects (NPC).
SPECIES_KIND = {
    0x57: "urn",
    0x67: "enemy", 0x2C: "enemy", 0x07: "enemy", 0x26: "enemy",
    0x81: "enemy", 0x10: "enemy", 0x08: "enemy",
    0x01: "platform",
    0x49: "pickup_crest", 0x24: "pickup_crest", 0x2D: "pickup_crest",
    0x2E: "pickup_crest",
    0x33: "boss", 0xA5: "boss",
    0x09: "exit",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probes", type=Path, required=True)
    ap.add_argument("--rooms", type=Path, default=Path("assets/generated"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # area -> {(species, cell_x, cell_y): (x, y)}
    found: dict[int, dict[tuple[int, int, int], tuple[int, int]]] = \
        defaultdict(dict)
    unknown: Counter = Counter()
    for info_path in sorted(args.probes.glob("*/info.json")):
        info = json.loads(info_path.read_text())
        area = int(info["area"])
        for entry in info.get("species", []):
            species = int(entry["species"])
            if species not in SPECIES_KIND:
                unknown[species] += 1
                continue
            x = int(round(entry["x"]))
            y = int(round(entry["y"]))
            key = (species, x // 16, y // 16)
            found[area].setdefault(key, (x, y))

    added_total = 0
    for area, placements in sorted(found.items()):
        room_path = args.rooms / f"room_area{area}.json"
        if not room_path.is_file():
            print(f"area {area}: no room json, {len(placements)} placements skipped")
            continue
        room = json.loads(room_path.read_text())
        world = room.get("world", {})
        width = int(world.get("width") or 0)
        height = int(world.get("height") or 0)
        objects = room.setdefault("objects", [])
        existing = {(o.get("type"), int(o.get("species", 0)),
                     int(o.get("x", 0)) // 16, int(o.get("y", 0)) // 16)
                    for o in objects}
        added = 0
        outside = 0
        for (species, cx, cy), (x, y) in sorted(placements.items()):
            if width and (x < 0 or x >= width or y < 0 or y >= height):
                outside += 1
                continue
            kind = SPECIES_KIND[species]
            key = (kind, species, cx, cy)
            if key in existing:
                continue
            objects.append({"type": kind, "species": species, "flags": 0,
                            "x": x, "y": y, "source": "probe"})
            existing.add(key)
            added += 1
        if added and not args.dry_run:
            room_path.write_text(json.dumps(room))
        added_total += added
        print(f"area {area:3d}: +{added:2d} placements "
              f"({len(placements)} seen, {outside} outside world)")

    print(f"\ntotal placements added: {added_total}"
          f"{' (dry run)' if args.dry_run else ''}")
    if unknown:
        top = ", ".join(f"{s:02X}x{n}" for s, n in unknown.most_common(20))
        print(f"unknown species seen (not merged): {top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
