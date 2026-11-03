#!/usr/bin/env python3
"""Navigation report for the area graph.

Answers three questions the original-game plan cares about:

1. Which areas are reachable through **real doors** only (no gate shortcut)?
2. Which areas are reachable only because of a **post-boss gate** or a
   **stage entry** (i.e. the port still cheats)?
3. Does the graph agree with the observed save pairs (`save_lvl_I_*`)?

Exit status is non-zero only when an area is completely isolated (no door, no
gate, not a stage entry), which would mean the extraction lost it.

Usage:
  python tools/check_navigation.py --graph assets/generated/area_graph.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path

PROBE = Path(r"C:\Users\magno\OneDrive\Documentos\deepseek-harness"
              r"\default-workspace\dcbuild\oracle_probe")


def bfs(start: int, by_kind: dict[str, list[tuple[int, int]]]) -> set[int]:
    seen = {start}
    queue = deque([start])
    while queue:
        area = queue.popleft()
        for kind in ("door", "gate", "stage_entry"):
            for src, dst in by_kind.get(kind, []):
                if src == area and dst not in seen and 0 <= dst < 113:
                    seen.add(dst)
                    queue.append(dst)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--graph", type=Path,
                    default=Path("assets/generated/area_graph.json"))
    ap.add_argument("--start", type=int, default=-1,
                    help="root node (-1 = overworld)")
    args = ap.parse_args()

    graph = json.loads(args.graph.read_text())
    nodes = {int(k): v for k, v in graph["nodes"].items()}
    edges = graph["edges"]

    by_kind: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for e in edges:
        by_kind[e["kind"]].append((int(e["from"]), int(e["to"])))

    # The overworld is the real root: every stage entry is reachable from it and
    # every level returns to it, so start the BFS at the virtual node -1.
    doors_only = bfs(-1, {"door": by_kind["door"],
                          "stage_entry": by_kind["stage_entry"]})
    doors_only.discard(-1)
    with_gates = bfs(-1, {"door": by_kind["door"],
                          "stage_entry": by_kind["stage_entry"],
                          "gate": by_kind["gate"]})
    with_gates.discard(-1)
    everything = bfs(-1, {"door": by_kind["door"],
                          "gate": by_kind["gate"],
                          "stage_entry": by_kind["stage_entry"]})
    everything.discard(-1)

    total = len(nodes)
    stage_entries = set(graph.get("stage_entries", []))
    print(f"areas: {total}")
    print(f"reachable with real doors only: {len(doors_only)} "
          f"({100 * len(doors_only) // total}%)")
    print(f"  + post-boss gates:            {len(with_gates)} "
          f"({100 * len(with_gates) // total}%)")
    print(f"  + overworld stage entries:    {len(everything)} "
          f"({100 * len(everything) // total}%)")

    door_only_areas = sorted(doors_only)
    gate_dependent = sorted(with_gates - doors_only)
    entry_dependent = sorted(everything - with_gates)
    print(f"need a gate: {len(gate_dependent)} -> {gate_dependent[:12]}")
    print(f"need a stage entry: {len(entry_dependent)} -> {entry_dependent[:12]}")

    isolated = []
    for area, node in nodes.items():
        has_door = any(int(e["from"]) == area for e in edges
                       if e["kind"] in ("door", "to_map", "boss"))
        has_gate = isinstance(node.get("gate_next_area"), int) and \
            0 <= node["gate_next_area"] < 113
        if not has_door and not has_gate and area not in stage_entries:
            isolated.append(area)
    print(f"no outgoing edge and not a stage entry: {len(isolated)} "
          f"-> {isolated[:16]}")

    outside = []
    for e in edges:
        if e.get("source") != "save_observed":
            continue
        node = nodes.get(int(e["from"]))
        width = (node or {}).get("world_w") or 0
        if e.get("x") is not None and width and int(e["x"]) > int(width):
            outside.append((int(e["from"]), int(e["to"]), int(e["x"]), width))
    if outside:
        print("observed doors outside the extracted world (needs a wider room):")
        for src, dst, x, width in outside:
            print(f"  area {src} -> {dst} at x={x} (world {width})")

    # Ground truth from the level I save pairs, when present.
    observed = []
    if PROBE.is_dir():
        for info in sorted(PROBE.glob("save_lvl_I_*/info.json")):
            data = json.loads(info.read_text())
            observed.append((info.parent.name, int(data["area"])))
    if observed:
        print("level I saves observed:")
        for name, area in observed:
            print(f"  {name}: area {area}")
        seq = [area for _n, area in observed]
        missing = [(a, b) for a, b in zip(seq, seq[1:])
                   if a != b and not any(int(e["from"]) == a and
                                         int(e["to"]) == b and
                                         e["kind"] == "door" for e in edges)]
        if missing:
            print(f"  door edges missing for observed pairs: {missing}")
        else:
            print("  every observed area change has a door edge")

    return 1 if isolated else 0


if __name__ == "__main__":
    raise SystemExit(main())
