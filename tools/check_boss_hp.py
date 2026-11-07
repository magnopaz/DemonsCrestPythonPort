#!/usr/bin/env python3
"""Check the boss HP table against docs/boss_hp.txt and the running rooms.

Three passes:

1. **document**: re-read ``docs/boss_hp.txt`` and assert every documented
   entry in ``dcpy/bosses.py`` names a boss from the file and uses one of the
   HP values listed for it.  This catches a typo in either side;
2. **rooms**: every boss record in ``room_area*.json`` (species ``$96`` is the
   arena controller, not a boss) must resolve through ``boss_hp`` without the
   fallback — a missing species would silently fight with 8 HP;
3. **runtime**: boot each boss room and read the object trace; the spawned
   boss's ``hp`` must equal the table.  The second Phalanx form is booted with
   ``DC_BOSS_PHASE=2`` (127).

Usage:
  python tools/check_boss_hp.py --binary tools/demonscrest-py
  python tools/check_boss_hp.py --assets assets/generated --no-runtime

Exit codes: 0 = pass, 1 = contract failure, 77 = binary/assets missing.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dcpy import bosses  # noqa: E402

# A boss record whose species is the arena controller is not a boss.
CONTROLLER_SPECIES = 0x96


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path,
                    default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    ap.add_argument("--doc", type=Path, default=ROOT / bosses.DOC)
    ap.add_argument("--no-runtime", action="store_true")
    ap.add_argument("--tmp", type=Path, help="scratch dir for trace CSVs")
    ap.add_argument("--json", type=Path)
    return ap.parse_args()


def parse_doc(path: Path) -> dict[str, list[int]]:
    """boss name -> the integers on its HP line ("3 (eyes); 10 (body)")."""
    doc: dict[str, list[int]] = {}
    name: str | None = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("HP:"):
            if name is None:
                raise ValueError(f"{path}: HP line before a boss name")
            doc[name] = [int(n) for n in re.findall(r"\d+", line)]
        else:
            name = line
    return doc


def check_doc(doc: dict[str, list[int]], errors: list[str],
              report: dict) -> None:
    seen: set[str] = set()
    for species, flags, entry in bosses.documented_entries():
        label = f"{entry.name} ({species:#04x}"
        label += f"/{flags:#04x})" if flags is not None else f")"
        if entry.name not in doc:
            errors.append(f"{label}: not in {bosses.DOC}")
            continue
        if entry.hp not in doc[entry.name]:
            errors.append(
                f"{label}: hp {entry.hp} not in {doc[entry.name]} "
                f"for {entry.name}")
            continue
        seen.add(entry.name)
        report["doc"].append({"species": species, "flags": flags,
                              "name": entry.name, "hp": entry.hp})
    missing = sorted(set(doc) - seen)
    report["doc_missing"] = missing


def boss_records(assets: Path) -> dict[int, list[tuple[int, int]]]:
    """area -> [(species, flags)] for every real boss record."""
    out: dict[int, list[tuple[int, int]]] = {}
    for path in sorted(assets.glob("room_area*.json")):
        try:
            area = int(path.stem.replace("room_area", ""))
        except ValueError:
            continue
        room = json.loads(path.read_text())
        rows = []
        for obj in room.get("objects", []):
            if obj.get("type") != "boss":
                continue
            species = int(obj.get("species", 0)) & 0xFF
            if species == CONTROLLER_SPECIES:
                continue
            rows.append((species, int(obj.get("flags", 0)) & 0xFF))
        if rows:
            out[area] = rows
    return out


def check_rooms(records: dict[int, list[tuple[int, int]]],
                errors: list[str], report: dict) -> None:
    for area, rows in sorted(records.items()):
        for species, flags in rows:
            entry = bosses._lookup(species, flags)
            if entry is None:
                errors.append(
                    f"area {area}: boss species {species:#04x} flags "
                    f"{flags:#04x} has no HP entry (would fall back to "
                    f"{bosses.DEFAULT_BOSS_HP})")
                continue
            report["rooms"].append({"area": area, "species": species,
                                    "flags": flags, "hp": entry.hp,
                                    "name": entry.name})


def check_runtime(binary: Path, assets: Path, records: dict[int, list],
                  tmp: Path | None, errors: list[str], report: dict) -> None:
    if not binary.is_file():
        errors.append(f"runtime: missing binary {binary}")
        return

    def run_case(area: int, expected: list[tuple[int, int]], suffix: str,
                 extra: dict[str, str] | None = None) -> None:
        trace = Path(td) / f"area{area}{suffix}.csv"
        env = dict(os.environ)
        env.update({
            "DC_AREA": str(area),
            "DC_RUN_FRAMES": "20",
            "DC_NO_AUDIO": "1",
            "DC_NO_SAVE": "1",
            "DC_NO_STORY": "1",
            "DC_BOSS_NO_ATTACK": "1",
            "DC_BOSS_INTRO": "0",
            "DC_TRACE_OBJECTS": str(trace),
        })
        for key in ("DC_BOSS_DEFEATED", "DC_BOSS_CLEAR", "DC_STATE",
                    "DC_DEMO", "DC_START_X", "DC_START_Y", "DC_RESUME",
                    "DC_STAGE_SELECT", "DC_BOSS_PHASE", "DC_BOSS_HP"):
            env.pop(key, None)
        if extra:
            env.update(extra)
        try:
            proc = subprocess.run(
                [str(binary), "--assets", str(assets)],
                cwd=ROOT, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            errors.append(f"runtime area {area}{suffix}: timeout")
            return
        if proc.returncode != 0:
            errors.append(
                f"runtime area {area}{suffix}: exit {proc.returncode} "
                f"{proc.stdout.strip()[-80:]}")
            return
        if not trace.is_file():
            errors.append(f"runtime area {area}{suffix}: no object trace")
            return
        rows = [r for r in csv.DictReader(trace.open(newline=""))
                if r.get("type") == "6"]
        active = {(int(r.get("species", -1)), int(r.get("flags", 0))): r
                  for r in rows}
        for species, flags in expected:
            if (species, flags) not in active:
                errors.append(
                    f"runtime area {area}{suffix}: species {species:#04x} "
                    f"flags {flags:#04x} did not spawn")
                continue
            row = active[(species, flags)]
            got = int(row.get("hp", -1))
            want = bosses.boss_hp(species, flags)
            if got != want:
                errors.append(
                    f"runtime area {area}{suffix}: {bosses.boss_name(species, flags)}"
                    f" hp {got} != {want}")
                continue
            report["runtime"].append(
                {"area": area, "species": species, "flags": flags,
                 "hp": got, "name": bosses.boss_name(species, flags)})

    with tempfile.TemporaryDirectory(prefix="dc-boss-hp-", dir=tmp) as td:
        for area, expected in sorted(records.items()):
            run_case(area, expected, "")
        # Second Phalanx form: the $86 record is retyped to $8D by the hook.
        run_case(84, [(0x8D, 0x00)], "_phase2", {"DC_BOSS_PHASE": "2"})


def main() -> int:
    args = parse_args()
    assets = args.assets.resolve()
    doc_path = args.doc.resolve()
    report: dict = {"doc": [], "doc_missing": [], "rooms": [], "runtime": []}
    errors: list[str] = []

    if not doc_path.is_file():
        errors.append(f"missing {doc_path}")
    else:
        check_doc(parse_doc(doc_path), errors, report)

    if not assets.is_dir():
        errors.append(f"missing assets dir {assets}")
        return 77
    records = boss_records(assets)
    check_rooms(records, errors, report)
    if not args.no_runtime:
        check_runtime(args.binary.resolve(), assets, records, args.tmp,
                      errors, report)

    print(f"boss hp: {len(report['doc'])} documented entries, "
          f"{len(records)} boss rooms, {len(report['runtime'])} runtime boss "
          f"checks, {len(errors)} error(s)")
    if report.get("doc_missing"):
        print(f"  note: in the doc but not modelled: {', '.join(report['doc_missing'])}")
    for error in errors:
        print(f"  ERROR {error}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=1))
        print(f"boss hp report: {args.json}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
