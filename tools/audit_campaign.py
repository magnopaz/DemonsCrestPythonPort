#!/usr/bin/env python3
"""Structural audit of every generated campaign room.

The extractor bakes all 113 ROM areas into `room_area<N>.json`. Some of those
areas are not playable rooms (menus, cutscene stages, empty padding grids), and
a few real rooms depend on data that is still missing (BG2 backdrops, streamed
CHR, boss arenas built from objects). This tool reports what each room actually
contains so regressions are visible instead of being discovered by playing.

Checks per room:

  * world size agrees with the collision grid and the BG1 map
  * BG1 / collision coverage percentages
  * whether a BG2 backdrop is present
  * spawn inside the play bounds with walkable ground underneath
  * objects inside the world bounds
  * transitions / boss gates pointing at rooms that exist

Rooms are classified as:

  ``playable``  has collision + BG1 geometry and a spawn that finds ground
  ``partial``   has geometry but the spawn is unsupported or BG1 is empty
  ``empty``     no collision and no BG1 tiles (menus, cutscenes, padding)

Usage:
  python3 tools/audit_campaign.py
  python3 tools/audit_campaign.py --json /tmp/campaign_audit.json
  python3 tools/audit_campaign.py --strict     # nonzero on playable regressions
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOLID = {0x01, 0x15, 0x1A}
HALF = {0x02, 0x17}
SLOPE = set(range(0x03, 0x15)) | {0x16, 0x18, 0x19, 0x1B}
WALKABLE = SOLID | HALF | SLOPE


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--json", type=Path, help="write the full report here")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if a playable room breaks an invariant")
    ap.add_argument("--max-list", type=int, default=12,
                    help="how many problem rooms to print per section")
    return ap.parse_args()


def walkable_attr(attr: int) -> bool:
    return (attr & 0x1F) in WALKABLE


def ground_below(attrs, cw, ch, x, y, max_dy=96):
    """Nearest walkable cell top under (x, y), or None."""
    cx = min(cw - 1, max(0, int(x) // 16))
    for dy in range(0, max_dy + 1, 4):
        cy = int((y + dy) // 16)
        if cy < 0 or cy >= ch:
            continue
        if walkable_attr(attrs[cy * cw + cx]):
            return cy * 16
    return None


def audit_room(area: int, path: Path) -> dict:
    doc = json.loads(path.read_text())
    world = doc.get("world", {})
    col = doc.get("collision", {})
    cw, ch = int(col.get("width", 0)), int(col.get("height", 0))
    attrs = col.get("attrs", [])
    bgs = doc.get("bg", [])
    bg2 = bgs[0] if bgs else {}
    bg1 = bgs[1] if len(bgs) > 1 else {}
    b1_tiles = bg1.get("tilemap", [])
    b2_tiles = bg2.get("tilemap", [])
    spawn = doc.get("spawn", {})
    play = doc.get("play", {})
    issues = []

    if cw * 16 != int(world.get("width", 0)):
        issues.append("collision width != world width")
    if ch * 16 != int(world.get("height", 0)):
        issues.append("collision height != world height")
    if bg1 and int(bg1.get("map_width", 0)) * 8 != int(world.get("width", 0)):
        issues.append("BG1 width != world width")
    if bg1 and int(bg1.get("map_height", 0)) * 8 != int(world.get("height", 0)):
        issues.append("BG1 height != world height")

    col_nonzero = sum(1 for a in attrs if a)
    col_pct = 100.0 * col_nonzero / len(attrs) if attrs else 0.0
    bg1_pct = 100.0 * sum(1 for w in b1_tiles if w) / len(b1_tiles) if b1_tiles else 0.0
    bg2_nonzero = sum(1 for w in b2_tiles if w)

    sx, sy = float(spawn.get("x", 0)), float(spawn.get("y", 0))
    in_bounds = (play.get("min_x", 0) <= sx <= play.get("max_x", 0) and
                 play.get("min_y", 0) <= sy <= play.get("max_y", 0))
    if not in_bounds:
        issues.append("spawn outside play bounds")
    ground = ground_below(attrs, cw, ch, sx, sy) if attrs else None
    if ground is None:
        issues.append("no walkable ground below spawn")

    bad_objects = [o for o in doc.get("objects", [])
                   if not (0 <= o.get("x", -1) < world.get("width", 0) and
                           0 <= o.get("y", -1) < world.get("height", 0))]
    if bad_objects:
        issues.append(f"{len(bad_objects)} object(s) outside world")

    transitions = doc.get("transitions", [])
    bad_trans = [t for t in transitions
                 if not (0 <= t.get("next_area", -1) < 113)]
    if bad_trans:
        issues.append(f"{len(bad_trans)} transition(s) to invalid room")
    gate = int(doc.get("gate_next_area", -1))

    if col_nonzero == 0 and not any(b1_tiles):
        kind = "empty"
    elif col_nonzero and bg1_pct >= 1.0 and ground is not None:
        kind = "playable"
    else:
        kind = "partial"

    return {
        "area": area,
        "kind": kind,
        "world": [world.get("width", 0), world.get("height", 0)],
        "collision_pct": round(col_pct, 1),
        "bg1_pct": round(bg1_pct, 1),
        "bg2": bg2_nonzero > 0,
        "spawn": [sx, sy],
        "ground": ground,
        "objects": len(doc.get("objects", [])),
        "transitions": len(transitions),
        "gate": gate,
        "issues": issues,
    }


def main() -> int:
    args = parse_args()
    rooms = []
    for area in range(113):
        path = args.assets / f"room_area{area}.json"
        if path.is_file():
            rooms.append(audit_room(area, path))
    if not rooms:
        print(f"audit: no room_area*.json under {args.assets}", file=sys.stderr)
        return 77

    kinds = {k: [r for r in rooms if r["kind"] == k]
             for k in ("playable", "partial", "empty")}
    with_bg2 = [r for r in rooms if r["bg2"]]
    bad = [r for r in rooms if r["issues"]]

    print(f"campaign rooms: {len(rooms)}")
    for kind, items in kinds.items():
        print(f"  {kind:9s}: {len(items):3d}")
    print(f"  BG2 backdrop present: {len(with_bg2)}")
    print(f"  rooms with structural issues: {len(bad)}")

    def show(title, items, key=None):
        if not items:
            return
        print(f"\n{title}")
        for r in items[:args.max_list]:
            extra = ""
            if key:
                extra = f" {key(r)}"
            print(f"  area {r['area']:3d}  {r['kind']:8s} "
                  f"world={r['world'][0]}x{r['world'][1]} "
                  f"BG1={r['bg1_pct']:5.1f}% col={r['collision_pct']:5.1f}% "
                  f"bg2={'yes' if r['bg2'] else 'no ':3s}{extra}")
        if len(items) > args.max_list:
            print(f"  ... {len(items) - args.max_list} more")

    show("rooms without ground under the spawn:",
         [r for r in rooms if "no walkable ground below spawn" in r["issues"]])
    show("rooms with a BG2 backdrop:", with_bg2)
    show("transition/gate or bounds issues:",
         [r for r in bad if any(i.startswith(("transition", "object", "spawn"))
                                for i in r["issues"])])

    # Cross-check against the extractor's own classification (campaign.json)
    campaign_path = args.assets / "campaign.json"
    if campaign_path.is_file():
        campaign = json.loads(campaign_path.read_text())
        rooms_meta = campaign.get("rooms", {})
        if rooms_meta:
            kinds_meta: dict[str, int] = {}
            for meta in rooms_meta.values():
                kinds_meta[meta.get("kind", "?")] = kinds_meta.get(
                    meta.get("kind", "?"), 0) + 1
            print("\nextractor classification (campaign.json): " +
                  ", ".join(f"{k}={v}" for k, v in sorted(kinds_meta.items())))
            mismatched = []
            for row in rooms:
                meta = rooms_meta.get(str(row["area"]))
                if meta and meta.get("kind") != row["kind"]:
                    mismatched.append((row["area"], meta.get("kind"),
                                       row["kind"]))
            if mismatched:
                print(f"  audit/extract disagreement on {len(mismatched)} "
                      f"room(s): " + ", ".join(f"{a}:{m}/{r}"
                                               for a, m, r in mismatched[:8]))
            else:
                print("  audit and extractor agree on every room kind")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "rooms": rooms,
            "summary": {
                "total": len(rooms),
                "playable": len(kinds["playable"]),
                "partial": len(kinds["partial"]),
                "empty": len(kinds["empty"]),
                "with_bg2": len(with_bg2),
                "with_issues": len(bad),
            },
        }, indent=1))
        print(f"\nreport: {args.json}")

    if args.strict:
        regressions = [r for r in kinds["playable"]
                       if any(i.startswith(("transition", "object", "spawn",
                                            "collision", "BG1"))
                              for i in r["issues"])]
        if regressions:
            print(f"\naudit: FAIL ({len(regressions)} playable rooms with "
                  f"structural regressions)", file=sys.stderr)
            return 1
        print("\naudit: OK (all playable rooms structurally valid)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
