#!/usr/bin/env python3
"""Build the area graph from the extracted rooms.

Nodes are areas (with world size, spawn points and boss gate); edges are the
area-changing transitions, the post-boss gates and the overworld stage entries.
The graph is the source of truth for navigation tests and for deciding where the
port still needs a real door instead of the gate shortcut.

Usage:
  python tools/dc_extract/build_area_graph.py --rooms assets/generated \
      --out assets/generated/area_graph.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rooms", type=Path, default=Path("assets/generated"))
    ap.add_argument("--out", type=Path,
                    default=Path("assets/generated/area_graph.json"))
    ap.add_argument("--names", type=Path, default=None,
                    help="room_names.json: named rooms are level entries")
    ap.add_argument("--name-edges", type=Path, default=None,
                    help="room_name_edges.json from the level notes")
    ap.add_argument("--probes", type=Path, default=None,
                    help="probe root with save_lvl_* dirs; adds door edges "
                         "observed in the save pairs")
    args = ap.parse_args()

    nodes: dict[int, dict] = {}
    edges: list[dict] = []

    for path in sorted(args.rooms.glob("room_area*.json")):
        data = json.loads(path.read_text())
        area = int(data.get("area_id", path.stem.split("area")[-1]))
        world = data.get("world", {})
        node = {
            "area": area,
            "world_w": world.get("width"),
            "world_h": world.get("height"),
            "gate_next_area": data.get("gate_next_area",
                                       data.get("gate_next", -1)),
            "spawns": data.get("spawns", []),
            "spawn": data.get("spawn"),
            "transitions": len(data.get("transitions", [])),
        }
        nodes[area] = node
        for tr in data.get("transitions", []):
            nxt = tr.get("next_area")
            if nxt is None or nxt < 0:
                continue
            edges.append({
                "from": area, "to": int(nxt), "kind": "door",
                "x": tr.get("x"), "y": tr.get("y"),
                "half_w": tr.get("half_w"), "half_h": tr.get("half_h"),
                "type": tr.get("type"), "spawn_id": tr.get("spawn_id"),
            })

    # The campaign starts in area 0 (new game), which is not reachable from the
    # overworld map and therefore needs its own entry edge.
    edges.append({"from": -1, "to": 0, "kind": "stage_entry",
                  "source": "game_start"})

    campaign_path = args.rooms / "campaign.json"
    stage_entries: list[int] = []
    if campaign_path.is_file():
        campaign = json.loads(campaign_path.read_text())
        stage_entries = [int(a) for a in campaign.get("stage_entries", [])]
        for area in stage_entries:
            edges.append({"from": -1, "to": area, "kind": "stage_entry"})

    # Post-boss gates are edges too, but marked so the report can separate them.
    for area, node in nodes.items():
        gate = node["gate_next_area"]
        if isinstance(gate, int) and 0 <= gate < 113:
            edges.append({"from": area, "to": gate, "kind": "gate"})

    # Door edges observed in the user's level saves: roomN -> roomN+1, with the
    # door position taken from the "before_door" save of the source room.
    if args.probes and args.probes.is_dir():
        rooms: dict[tuple[str, int], dict] = {}
        for info in sorted(args.probes.glob("save_lvl_*/info.json")):
            stem = info.parent.name
            parts = stem.split("_")
            try:
                level = parts[2]
                room = int(parts[3][4:]) if parts[3].startswith("room") else None
            except (IndexError, ValueError):
                continue
            data = json.loads(info.read_text())
            entry = rooms.setdefault((level, room), {"area": int(data["area"]),
                                                     "door": None})
            entry["area"] = int(data["area"])
            if stem.endswith("before_door"):
                pos = data.get("player") or [0, 0]
                entry["door"] = [round(pos[0]), round(pos[1])]
        for (level, room), entry in sorted(rooms.items()):
            nxt = rooms.get((level, room + 1))
            if not nxt or nxt["area"] == entry["area"]:
                continue
            door = entry["door"] or [0, 0]
            edges.append({
                "from": entry["area"], "to": nxt["area"],
                "kind": "door", "x": door[0], "y": door[1],
                "half_w": 12, "half_h": 40, "type": -1,
                "spawn_id": 0, "source": "save_observed",
                "level": level,
            })

    # Named rooms are where their level starts, so they are entry points from
    # the overworld (the stage-entry inference misses rooms that are also door
    # targets inside their own level).
    if args.names and args.names.is_file():
        names = json.loads(args.names.read_text())
        # A named room is a level entry only when no other named room of the
        # same level leads into it (mid-level rooms are reached through doors).
        targets = {int(e["to"]) for e in edges
                   if e.get("source") == "notes" and isinstance(e.get("to"), int)
                   and int(e["to"]) > 0}
        for area_str, entry in names.items():
            area = int(area_str)
            if area in targets:
                continue
            edges.append({"from": -1, "to": area, "kind": "stage_entry",
                          "source": "name_entry", "map": entry.get("map"),
                          "level": entry.get("level")})

    # Door edges transcribed from the user's level notes (map-name table).
    if args.name_edges and args.name_edges.is_file():
        for e in json.loads(args.name_edges.read_text()):
            src = int(e["from_area"])
            dst = e.get("to_area")
            if dst is None:
                edges.append({"from": src, "to": -1, "kind": "to_map",
                              "x": e.get("x"), "y": e.get("y"),
                              "door": e.get("door"), "source": "notes"})
                continue
            if int(dst) == src:
                edges.append({"from": src, "to": src, "kind": "boss",
                              "x": e.get("x"), "y": e.get("y"),
                              "door": e.get("door"), "source": "notes"})
                continue
            edges.append({"from": src, "to": int(dst), "kind": "door",
                          "x": e.get("x"), "y": e.get("y"),
                          "half_w": 12, "half_h": 40, "type": -2,
                          "spawn_id": 0, "door": e.get("door"),
                          "source": "notes"})

    graph = {
        "nodes": nodes,
        "edges": edges,
        "stage_entries": stage_entries,
        "stats": {
            "areas": len(nodes),
            "doors": sum(1 for e in edges if e["kind"] == "door"),
            "gates": sum(1 for e in edges if e["kind"] == "gate"),
            "stage_entries": len(stage_entries),
            "areas_with_door": len({e["from"] for e in edges
                                    if e["kind"] == "door"}),
            "observed_doors": sum(1 for e in edges
                                  if e.get("source") == "save_observed"),
            "note_doors": sum(1 for e in edges
                              if e.get("source") == "notes"),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(graph, indent=1))

    with_door = {e["from"] for e in edges if e["kind"] == "door"}
    with_gate = {e["from"] for e in edges if e["kind"] == "gate"}
    no_out = [a for a in sorted(nodes) if a not in with_door and a not in with_gate]
    print(f"areas {len(nodes)}, doors {graph['stats']['doors']}, "
          f"gates {graph['stats']['gates']}, stage entries {len(stage_entries)}")
    print(f"areas with a door: {len(with_door)}; with a gate: {len(with_gate)}; "
          f"no outgoing edge: {len(no_out)}")
    print(f"observed door edges: {graph['stats']['observed_doors']}, "
          f"note edges: {graph['stats']['note_doors']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
