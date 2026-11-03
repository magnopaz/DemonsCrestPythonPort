#!/usr/bin/env python3
"""Apply the ROM's boss-gate table ($81:97DA) to the room documents.

`extract.py` reads the same table but treats every byte >= $F0 as "no gate".
That is wrong for the areas whose gate byte is a *special marker* rather than
the next room byte: area 3 stores $F0, which the original resolves as "return to
the world map" (the map is area 94; `world_map.sav` resumes there with
`$008D = $BC`).  Areas 8, 9, 60 and 80 store $F1 and 13, 14, 50, 51 store $F2,
etc. - all of them are special-entry markers into the same map room.

Policy:

- the low nibble of a marker is the map entry index the guest writes to $0EA6
  before it loads the map (00:BB1F: ``AND #$0F; STA $0EA6``), so it is kept as
  ``gate_marker`` and ``gate_entry``;
- only markers whose destination is *verified* are turned into a real
  ``gate_next_area``.  Right now that is $F0 -> 94, measured from
  `world_map.sav`.  Every other marker keeps ``gate_next_area = -1`` so no
  unverified room suddenly gains an exit, but the marker is still recorded;
- the tool is idempotent: it recomputes both fields from the ROM on every run.

Usage:
  python3 tools/dc_extract/apply_gate_table.py --rom ... --rooms assets/generated
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

GATE_ADDR = 0x97DA      # $81:97DA, indexed by area
AREAS = 113
MAP_AREA = 94           # world map room, confirmed by world_map.sav ($008D=$BC)

# marker -> destination area, only where the destination is measured.
VERIFIED_MARKERS = {
    0xF0: MAP_AREA,     # murkland abyss (Arma 1st) -> world map
}


def lo(bank: int, addr: int) -> int:
    return ((bank & 0x7F) << 15) + (addr - 0x8000)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", required=True, type=Path)
    ap.add_argument("--rooms", required=True, type=Path)
    ap.add_argument("--areas", type=int, default=AREAS)
    args = ap.parse_args()

    data = args.rom.read_bytes()
    table = data[lo(0x81, GATE_ADDR):lo(0x81, GATE_ADDR) + args.areas]
    if len(table) != args.areas:
        raise SystemExit("gate table is short; wrong ROM?")

    changed = 0
    specials: dict[int, int] = {}
    for area, raw in enumerate(table):
        path = args.rooms / f"room_area{area}.json"
        if not path.is_file():
            continue
        doc = json.loads(path.read_text())
        if raw >= 0xF0:
            specials.setdefault(raw, 0)
            specials[raw] += 1
            next_area = VERIFIED_MARKERS.get(raw, -1)
            marker = raw
            entry = raw & 0x0F
        else:
            next_area = raw // 2
            marker = 0
            entry = 0
        if next_area == area:
            next_area = -1
        want = {"gate_next_area": next_area, "gate_marker": marker,
                "gate_entry": entry}
        if any(doc.get(k) != v for k, v in want.items()):
            doc.update(want)
            path.write_text(json.dumps(doc, indent=1))
            changed += 1

    print(f"apply_gate_table: {changed} room(s) updated")
    for raw, count in sorted(specials.items()):
        dest = VERIFIED_MARKERS.get(raw)
        where = f"area {dest}" if dest is not None else "unverified, left closed"
        print(f"  marker ${raw:02X} x{count}: {where} (entry {raw & 0x0F})")
    print(f"  area 3 -> gate {table[3]:#04x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
