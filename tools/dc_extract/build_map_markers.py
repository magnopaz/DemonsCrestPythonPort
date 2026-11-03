#!/usr/bin/env python3
"""Extract overworld map markers from mode-7 saves.

On the map screen the stage icons are objects with species $94; their positions
are the map-space anchors the player can land on. Comparing saves from different
progress points shows which markers unlock over time (the map grows as the bad
ending threshold is passed).

Usage:
  python tools/dc_extract/build_map_markers.py --probes <...>/oracle_probe \
      --saves save6ee,map_new_stages,save11 --out assets/generated/map_markers.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MARKER_SPECIES = 0x94
CURSOR_SPECIES = 0x6A


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probes", type=Path, required=True)
    ap.add_argument("--saves", required=True)
    ap.add_argument("--out", type=Path,
                    default=Path("assets/generated/map_markers.json"))
    args = ap.parse_args()

    snapshots: dict[str, dict] = {}
    for name in [s.strip() for s in args.saves.split(",") if s.strip()]:
        info_path = args.probes / name / "info.json"
        if not info_path.is_file():
            print(f"skip {name}: no probe")
            continue
        info = json.loads(info_path.read_text())
        if info.get("ppu", {}).get("bgmode") != 7:
            print(f"skip {name}: not a mode-7 map save "
                  f"(area {info['area']})")
            continue
        markers = sorted(
            (round(s["x"]), round(s["y"]))
            for s in info["species"] if s["species"] == MARKER_SPECIES)
        cursor = [(round(s["x"]), round(s["y"]))
                  for s in info["species"] if s["species"] == CURSOR_SPECIES]
        snapshots[name] = {"markers": markers, "cursor": cursor,
                           "player": info.get("player")}
        print(f"{name}: {len(markers)} markers, cursor {cursor}")

    all_positions = sorted({p for snap in snapshots.values()
                            for p in snap["markers"]})
    for name, snap in snapshots.items():
        snap["only_here"] = [p for p in snap["markers"]
                             if not any(p in other["markers"]
                                        for other in snapshots.values()
                                        if other is not snap)]
    result = {"marker_species": MARKER_SPECIES, "snapshots": snapshots,
              "all_positions": all_positions}
    args.out.write_text(json.dumps(result, indent=1))
    print(f"unique positions: {len(all_positions)} -> {args.out}")
    for name, snap in snapshots.items():
        if snap["only_here"]:
            print(f"  {name} only: {snap['only_here']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
