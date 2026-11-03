#!/usr/bin/env python3
"""Build the room name table from the map-named level saves.

The user's saves are named `lvl_<level>_<map-name>[_role]`, where `<map-name>`
matches a file in docs/FullMaps/images. Reading the area id out of each save's
probe gives the name -> area mapping (and with it the level grouping), which the
area graph and the map-size checks need.

Roles: (none) = entrance, `before_door`, `e1`/`e2` = enemies in the room,
`boss`, `boss_dead`.

Usage:
  python tools/dc_extract/build_room_names.py \
      --probes <...>/oracle_probe --maps docs/FullMaps/images \
      --out assets/generated/room_names.json
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path

# The map names never contain underscores, so the first underscore after the
# level prefix starts the role (before_door, e1, inside_door_before_boss, ...).
# Roles are a closed set of suffixes; names may themselves contain underscores
# ("wise_man", "black_lotus"), so the role is matched from the END and only when
# it is a known role.
ROLE_RE = re.compile(
    r"^(?P<name>.+?)(?:_(?P<role>"
    r"before_door(?:_.+)?|after_door|inside_door(?:_.+)?|boss(?:_?\d)?"
    r"(?:_.+)?|e\d+|entrance|passage|persecution(?:_trigged)?|dead|item\d+"
    r"|final_boss_second|on_the_righ\w*"
    r"))?$")

PATTERN = re.compile(r"^(?:save_)?lvl_(?P<level>[0IVX]+)_(?P<rest>.+)$")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probes", type=Path,
                    default=None,
                    help="oracle_probe directory (omit when --areas is given)")
    ap.add_argument("--areas", type=Path, default=None,
                    help="JSON from tools/oracle/probe_save_area.py "
                         "(save name -> area), instead of per-save probes")
    ap.add_argument("--maps", type=Path,
                    default=Path("docs/FullMaps/images"))
    ap.add_argument("--out", type=Path,
                    default=Path("assets/generated/room_names.json"))
    ap.add_argument("--notes", type=Path, default=None,
                    help="docs/LEVEL_TRANSITIONS.md with name-based door rows")
    ap.add_argument("--edges-out", type=Path,
                    default=None,
                    help="where to write the name-resolved edges JSON")
    args = ap.parse_args()

    map_names = [p.stem.replace("demons-crest-", "").replace("-snes-map", "")
                 for p in sorted(args.maps.glob("*.webp"))]
    table: dict[str, dict] = {}
    unmatched: list[str] = []

    infos = sorted(set(args.probes.glob("save_lvl_*/info.json")) |
                   set(args.probes.glob("lvl_*/info.json"))) if args.probes else []
    # A probe directory is only needed when no area map is supplied. The area
    # id in WRAM $008D can be read directly from every save
    # (tools/oracle/probe_save_area.py), which makes this step independent of
    # the old oracle_probe captures.
    sources: list[tuple[str, int]] = []
    if args.areas:
        for row in json.loads(args.areas.read_text()):
            if "area" not in row:
                continue
            stem = row["save"][:-4] if row["save"].endswith(".sav") else row["save"]
            sources.append((stem, int(row["area"])))
    else:
        for info in infos:
            data = json.loads(info.read_text())
            sources.append((info.parent.name, int(data["area"])))
    for stem, area in sorted(sources):
        m = PATTERN.match(stem)
        if not m:
            continue
        level = m.group("level")
        rm = ROLE_RE.match(m.group("rest"))
        if not rm:
            continue
        raw = rm.group("name")
        role = rm.group("role") or "entrance"
        match = difflib.get_close_matches(raw, map_names, n=1, cutoff=0.8)
        if match:
            map_name = match[0]
            in_maps = True
        else:
            # Interiors (library, black lotus, wise man) have no community map
            # but are still named rooms; keep the save's own name.
            map_name = raw
            in_maps = False
        if area > 112:
            print(f"skip {stem}: area {area} is outside the extracted set")
            continue
        entry = table.setdefault(str(area), {
            "area": area, "level": level, "map": map_name,
            "in_maps": in_maps, "roles": {}, "saves": [],
        })
        entry["roles"].setdefault(role, []).append(stem)
        entry["saves"].append(stem)

    args.out.write_text(json.dumps(table, indent=1))

    if args.notes and args.notes.is_file() and args.edges_out:
        # Several areas can share a map name (chunks of the same room): prefer
        # the one saved as an entrance, else the lowest area id.
        by_map: dict[str, dict] = {}
        for entry in sorted(table.values(), key=lambda e: e["area"]):
            current = by_map.get(entry["map"])
            if current is None:
                by_map[entry["map"]] = entry
                continue
            if ("entrance" in entry["roles"]
                    and "entrance" not in current["roles"]):
                by_map[entry["map"]] = entry
        if len({e["map"] for e in table.values()}) != len(table):
            shared = {}
            for entry in table.values():
                shared.setdefault(entry["map"], []).append(entry["area"])
            for name, areas in shared.items():
                if len(areas) > 1 and all(
                        e.get("in_maps") for e in table.values()
                        if e["map"] == name):
                    print(f"notes: map '{name}' spans areas {sorted(areas)}; "
                          f"using {by_map[name]['area']} for name lookups")
        edges = []
        for line in args.notes.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 3 or cells[0] in ("from", "---") or \
                    set(cells[0]) <= {"-", " "}:
                continue
            src_name, door, dst_name = cells[0], cells[1], cells[2]
            src = by_map.get(src_name)
            if src is None and src_name.startswith("area:"):
                try:
                    src = {"area": int(src_name.split(":", 1)[1]), "saves": []}
                except ValueError:
                    src = None
            if src is None:
                if " " not in src_name:
                    print(f"notes: unknown source map '{src_name}'")
                continue
            dst = by_map.get(dst_name) if dst_name != "boss" else src
            direct_area = None
            if dst_name.startswith("area:"):
                try:
                    direct_area = int(dst_name.split(":", 1)[1])
                except ValueError:
                    print(f"notes: bad area spec '{dst_name}'")
                    continue
                dst = {"area": direct_area}
            if dst is None and dst_name != "map":
                print(f"notes: unknown destination map '{dst_name}'")
                continue
            before = [s for s in src["saves"] if s.endswith("_before_door")]
            pos = None
            probe = args.probes / before[0] / "info.json" if before else None
            if probe and probe.is_file():
                pos = json.loads(probe.read_text()).get("player")
            edges.append({
                "from_area": src["area"],
                "to_area": None if dst_name == "map" else dst["area"],
                "to_map_name": dst_name,
                "door": door,
                "x": round(pos[0]) if pos else None,
                "y": round(pos[1]) if pos else None,
                "source": "notes",
            })
        args.edges_out.write_text(json.dumps(edges, indent=1))
        print(f"name edges: {len(edges)} -> {args.edges_out}")
        for e in edges:
            print(f"  area {e['from_area']} -> {e['to_area']} "
                  f"({e['door']}) at ({e['x']},{e['y']})")
    print(f"named areas: {len(table)}")
    for area, e in sorted(table.items(), key=lambda kv: int(kv[0])):
        roles = ", ".join(sorted(e["roles"]))
        print(f"  area {int(area):3d}  {e['level']:<4s} {e['map']:<44s} [{roles}]")
    if unmatched:
        print("unmatched save names:")
        for name in unmatched:
            print("  ", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
