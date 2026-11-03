#!/usr/bin/env python3
"""Pick one representative save state per area for BG2/backdrop captures.

Input is `tools/oracle/probe_save_area.py --json` output (save name -> `$008D`).

`$008D` is the *byte* offset into the `$81:A291` area pointer table, i.e.
`2 * area`, so the plan is keyed by `$008D / 2` (see
`tools/oracle/map_saves_to_areas.py` for the verified mapping).
The chooser prefers a settled, decorated room over transitional states:

  1. skip `before_door` / `after_door` / `just_after_crossing` (mid-transition),
  2. skip `boss_dead`, `dead`, `cutscene`, `talk`, `persecution`, `menu`,
     `map_*`, `widescreen`, `somulo_*` (scripted or effect-heavy frames),
  3. prefer `e1`/`e2` (enemies lit), then plain entrances, then anything,
  4. prefer `lvl_*` names (documented map) over `saveN` probes.

Usage:
  python3 tools/oracle/map_areas_to_saves.py \
      --areas captures/save_areas.json --json captures/area_capture_plan.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SKIP = re.compile(
    r"(before_door|after_door|just_after_crossing|boss_dead|_dead\b|cutscene|"
    r"_talk\b|persecution|menu|^map_|widescreen|somulo|initial_cutscene|"
    r"normal_ending|ending)", re.I)
PREFER = re.compile(r"(_e\d\b|entrance)", re.I)


def score(name: str) -> int:
    stem = name[:-4] if name.endswith(".sav") else name
    if SKIP.search(stem):
        return -100
    s = 0
    if PREFER.search(stem):
        s += 10
    if stem.startswith("lvl_"):
        s += 5
    if re.search(r"save\d", stem):
        s += 2
    s -= len(stem) // 40
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--areas", type=Path, default=Path("captures/save_areas.json"))
    ap.add_argument("--json", type=Path, default=Path("captures/area_capture_plan.json"))
    args = ap.parse_args()

    rows = json.loads(args.areas.read_text())
    by_area: dict[int, list[str]] = {}
    for row in rows:
        if "area" not in row:
            continue
        raw = int(row["area"])
        by_area.setdefault(raw // 2, []).append(row["save"])

    plan = {}
    for area, names in sorted(by_area.items()):
        ranked = sorted(names, key=lambda n: (-score(n), n))
        plan[area] = {"save": ranked[0], "score": score(ranked[0]),
                      "alternatives": ranked[1:4]}
        print(f"area {area:3d}: {ranked[0]:60s} score={score(ranked[0])}"
              f"  (+{len(ranked)-1} alternatives)")
    args.json.write_text(json.dumps(plan, indent=1))
    print(f"{len(plan)} areas covered by {sum(len(v) for v in by_area.values())} saves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
