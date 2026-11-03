#!/usr/bin/env python3
"""Print how much of the ROM's campaign data actually reaches the port.

The number that matters for "finish the game" is not how many rooms exist, but
how many *placed objects* the port can show.  `extract.py` types only the
species listed in `SPECIES_KIND_MAP` and silently drops the rest, so a room can
look complete while two thirds of its contents never shipped.

Usage:
  python3 tools/report_coverage.py [--rom ...] [--assets ...]

Exit status is always 0: this is a report, not a gate.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))

import extract as E  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path,
                    default=ROOT.parent / "roms" / "Demon's Crest (USA).sfc")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if not args.rom.is_file():
        raise SystemExit(f"report_coverage: no ROM at {args.rom}")

    rom = E.Rom(args.rom)
    rooms = sorted(args.assets.glob("room_area*.json"))
    placed = collections.Counter()
    placed_rooms = 0
    for path in rooms:
        doc = json.loads(path.read_text())
        objs = doc.get("objects", [])
        if objs:
            placed_rooms += 1
        for o in objs:
            placed[int(o.get("species", 0))] += 1

    rom_species = collections.Counter()
    rom_total = 0
    areas_with_objects = 0
    for area in range(113):
        try:
            recs = rom.object_list(area)
        except Exception:
            continue
        if not recs:
            continue
        areas_with_objects += 1
        rom_total += len(recs)
        for rec in recs:
            rom_species[rec["species"]] += 1

    typed = sum(n for s, n in rom_species.items() if s in E.SPECIES_KIND_MAP)
    dropped = rom_total - typed
    missing = {s: n for s, n in rom_species.items()
               if s not in E.SPECIES_KIND_MAP}
    top20 = sum(n for _s, n in collections.Counter(missing).most_common(20))

    campaign = args.assets / "campaign.json"
    kinds = {}
    if campaign.is_file():
        doc = json.loads(campaign.read_text())
        kinds = {str(k): int(v) for k, v in
                 (doc.get("room_kinds") or {}).items()}

    bg2 = 0
    for path in rooms:
        doc = json.loads(path.read_text())
        for layer in doc.get("bg", []):
            if layer.get("name") == "bg2" and any(layer.get("tilemap") or []):
                bg2 += 1
                break

    sheets = {p.name.split("_")[1] for p in
              args.assets.glob("enemy_*.png") if "_" in p.name}
    music = list((args.assets / "audio").glob("*.wav")) \
        if (args.assets / "audio").is_dir() else []

    print(f"rooms extracted ............ {len(rooms)}  {kinds or ''}")
    print(f"rooms with objects ......... {placed_rooms}")
    print(f"objects placed in JSON ..... {sum(placed.values())}"
          f"  ({len(placed)} species)")
    print(f"objects listed in the ROM .. {rom_total}"
          f"  ({len(rom_species)} species, {areas_with_objects} areas)")
    print(f"typed by the extractor ..... {typed}"
          f"  ({len(E.SPECIES_KIND_MAP)} species)")
    print(f"DROPPED .................... {dropped}"
          f"  ({len(missing)} species)")
    print(f"  top 20 of those cover .... {top20} records"
          f" ({100.0 * top20 / max(1, dropped):.0f}% of the gap)")
    print(f"  most common dropped ...... " +
          ", ".join(f"${s:02X}x{n}" for s, n in
                    collections.Counter(missing).most_common(10)))
    print(f"rooms with a BG2 tilemap ... {bg2}/{len(rooms)}")
    print(f"species sprite sheets ...... {len(sheets)}")
    print(f"music tracks ............... {len(music)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
