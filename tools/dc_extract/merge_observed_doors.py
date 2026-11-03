#!/usr/bin/env python3
"""Merge door edges (save-observed and from the level notes) into the room JSONs.

Policy (settled after several regressions):

- extracted transitions are **never modified or removed** — they are the ROM's
  own doors, and deleting one can lose a whole branch;
- a note/save door is **inserted at the front** of the room's transition list, so
  when two triggers overlap in the runtime check the note door wins;
- a door whose save-space position lies outside the chunk world is clamped into
  it (the saves use level-space coordinates);
- duplicates (same destination from the same source kind) are skipped.

Usage:
  python tools/dc_extract/merge_observed_doors.py \
      --graph assets/generated/area_graph.json --rooms assets/generated \
      --sources save_observed,notes
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--graph", type=Path,
                    default=Path("assets/generated/area_graph.json"))
    ap.add_argument("--rooms", type=Path, default=Path("assets/generated"))
    ap.add_argument("--sources", default="save_observed,notes",
                    help="comma separated edge sources to merge")
    ap.add_argument("--trust-notes", action="store_true",
                    help="accepted for compatibility; keeps ROM doors intact")
    args = ap.parse_args()

    graph = json.loads(args.graph.read_text())
    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    added = 0
    for edge in graph["edges"]:
        if edge.get("source") not in sources:
            continue
        dst = edge.get("to")
        if dst is None:
            continue
        dst = int(dst)
        if dst < 0:
            continue
        src = int(edge["from"])
        if dst == src:
            continue  # a door that leads to the same room is not a transition
        path = args.rooms / f"room_area{src}.json"
        if not path.is_file():
            continue
        data = json.loads(path.read_text())
        transitions = data.setdefault("transitions", [])
        world = data.get("world", {})
        w = int(world.get("width") or 256)
        h = int(world.get("height") or 256)
        if edge.get("x") is None or edge.get("y") is None:
            cx, cy = w - 32, h // 2
        else:
            cx = int(edge["x"])
            cy = int(edge["y"])
            if not (0 <= cx < w and 0 <= cy < h):
                cx = min(max(cx, 16), w - 16)
                cy = min(max(cy, 16), h - 16)
        marker = "notes" if edge.get("source") == "notes" else "save_observed"
        if any(int(tr.get("next_area", -1)) == dst and
               str(tr.get("source", "")).startswith(marker)
               for tr in transitions):
            continue
        transitions.insert(0, {
            "next_area": dst,
            "spawn_id": int(edge.get("spawn_id") or 0),
            "pad_mask": 255,
            "x": cx,
            "y": cy,
            "half_w": 12,
            "half_h": 40,
            "type": -3 if marker == "notes" else -2,
            "source": marker,
        })
        path.write_text(json.dumps(data))
        added += 1
        print(f"{src}->{dst}: {marker} door at ({cx},{cy})")
    print(f"doors added: {added} (sources: {sorted(sources)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
