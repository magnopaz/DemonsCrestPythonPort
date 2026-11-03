#!/usr/bin/env python3
"""Analyse the campaign transition graph.

Builds area -> target edges from each room's `transitions` and boss
`gate_next_area`, then reports reachability from the six overworld stage
entries, dead ends and terminal rooms. This validates that the extracted graph
can actually carry a player through the campaign.

Usage:
  python3 tools/campaign_graph.py
  python3 tools/campaign_graph.py --json report.json --start 0,1,2,3,4,5
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--start", default="",
                    help="comma-separated entry areas (default: all rooms no "
                         "other room targets, i.e. campaign.json stage_entries)")
    ap.add_argument("--json", type=Path)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    rooms: dict[int, dict] = {}
    for path in glob.glob(str(args.assets / "room_area*.json")):
        area = int(re.search(r"room_area(\d+)", path).group(1))
        rooms[area] = json.loads(Path(path).read_text())
    if not rooms:
        print("campaign_graph: no rooms", file=sys.stderr)
        return 77

    edges: dict[int, set[int]] = {a: set() for a in rooms}
    gates: dict[int, int] = {}
    spurs: dict[int, list] = {}
    for area, doc in rooms.items():
        for tr in doc.get("transitions", []):
            target = tr.get("next_area")
            if isinstance(target, int) and target in rooms:
                edges[area].add(target)
        gate = doc.get("gate_next_area", -1)
        if isinstance(gate, int) and gate >= 0:
            gates[area] = gate
            if gate in rooms:
                edges[area].add(gate)

    if args.start.strip():
        starts = [int(s, 0) for s in args.start.split(",") if s.strip()]
    else:
        targets = {b for a in edges for b in edges[a]}
        starts = sorted(set(rooms) - targets)
    seen = set()
    order = []
    q = deque(s for s in starts if s in rooms)
    while q:
        a = q.popleft()
        if a in seen:
            continue
        seen.add(a)
        order.append(a)
        for b in sorted(edges[a]):
            if b not in seen:
                q.append(b)

    unreachable = sorted(set(rooms) - seen)
    dead_ends = sorted(a for a in rooms if not edges[a] and a not in gates)
    # Rooms whose only way out is the boss gate (no transitions).
    gate_only = sorted(a for a in rooms if not edges[a] and a in gates)

    print(f"campaign_graph: {len(rooms)} rooms, {sum(len(v) for v in edges.values())} edges")
    print(f"  reachable from {starts}: {len(seen)}")
    if unreachable:
        print(f"  unreachable ({len(unreachable)}): {unreachable[:24]}")
    if dead_ends:
        print(f"  dead ends without gate ({len(dead_ends)}): {dead_ends[:24]}")
    print(f"  boss-gate-only rooms ({len(gate_only)}): {gate_only[:24]}")
    chains = [a for a in order if gates.get(a, -1) >= 0]
    print(f"  gate rooms: {len(chains)}, sample: {chains[:12]}")

    if args.json:
        args.json.write_text(json.dumps({
            "rooms": len(rooms),
            "reachable": sorted(seen),
            "unreachable": unreachable,
            "dead_ends": dead_ends,
            "gate_only": gate_only,
            "edges": {str(k): sorted(v) for k, v in edges.items()},
            "gates": {str(k): v for k, v in gates.items()},
        }, indent=1))
        print(f"report: {args.json}")
    return 0 if not unreachable else 1


if __name__ == "__main__":
    sys.exit(main())
