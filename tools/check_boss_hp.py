#!/usr/bin/env python3
"""Check the boss HP table against docs/boss_hp.txt and the running rooms.

Three passes:

1. **document**: re-read ``docs/boss_hp.txt`` and assert every documented
   entry in ``dcpy/bosses.py`` names a boss from the file, uses one of the HP
   values listed for it, and copies all ten damage columns exactly ("N/A" ->
   None, "2/1" -> (2, 1)).  This catches a typo in either side;
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
from dcpy.consts import (  # noqa: E402
    CREST_AIR, CREST_BASE, CREST_EARTH, CREST_TIME, CREST_ULTIMATE)

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


# The document's column names -> dcpy/bosses.py field names.
COLUMNS = {
    "Fire": "fire",
    "Buster": "buster",
    "Claw": "claw",
    "Demon Fire": "demon_fire",
    "Earth (Ground)": "earth_ground",
    "Earth (Air)": "earth_air",
    "Aerial": "aerial",
    "Tidal": "tidal",
    "Legendary": "legendary",
    "Ultimate": "ultimate",
}

_COLUMN_RE = re.compile(
    r"^(Fire|Buster|Claw|Demon Fire|Earth \(Ground\)|Earth \(Air\)|Aerial|"
    r"Tidal|Legendary|Ultimate): (.+)$")


def parse_doc(path: Path) -> dict[str, dict]:
    """boss name -> {"hp": [ints], "fire": value, ...} from its block."""
    doc: dict[str, dict] = {}
    name: str | None = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("HP:"):
            if name is None:
                raise ValueError(f"{path}: HP line before a boss name")
            # "3 (eyes); 10 (main body)" -> both numbers are valid HP values.
            doc[name]["hp"] = [int(n) for n in re.findall(r"\d+", line)]
            continue
        column = _COLUMN_RE.match(line)
        if column:
            if name is None:
                raise ValueError(f"{path}: column before a boss name")
            doc[name][COLUMNS[column.group(1)]] = column.group(2).strip()
            continue
        name = line
        doc[name] = {}
    return doc


def check_doc(doc: dict[str, dict], errors: list[str],
              report: dict) -> None:
    seen: set[str] = set()
    for species, flags, entry in bosses.documented_entries():
        label = f"{entry.name} ({species:#04x}"
        label += f"/{flags:#04x})" if flags is not None else f")"
        if entry.name not in doc:
            errors.append(f"{label}: not in {bosses.DOC}")
            continue
        hp_values = doc[entry.name].get("hp", [])
        if entry.hp not in hp_values:
            errors.append(
                f"{label}: hp {entry.hp} not in {hp_values} "
                f"for {entry.name}")
            continue
        seen.add(entry.name)
        report["doc"].append({"species": species, "flags": flags,
                              "name": entry.name, "hp": entry.hp})
    missing = sorted(set(doc) - seen)
    report["doc_missing"] = missing


def doc_value(text: str):
    """'N/A' -> None, '1' -> 1, '2/1' -> (2, 1)."""
    if text == "N/A":
        return None
    numbers = tuple(int(part) for part in text.split("/"))
    return numbers[0] if len(numbers) == 1 else numbers


def check_damage(doc: dict[str, dict], errors: list[str],
                 report: dict) -> None:
    """Every damage row must match the document's ten columns."""
    for species, flags, row in bosses.damage_entries():
        name = bosses.boss_name(species, flags or 0)
        label = f"{name} ({species:#04x}"
        label += f"/{flags:#04x})" if flags is not None else f")"
        if name not in doc:
            errors.append(f"{label}: damage row but no {bosses.DOC} block")
            continue
        for column, field in COLUMNS.items():
            if field not in doc[name]:
                errors.append(f"{label}: {bosses.DOC} has no {column} line")
                continue
            want = doc_value(doc[name][field])
            got = getattr(row, field)
            if want != got:
                errors.append(f"{label} {column}: table {got} != doc {want}")
                continue
        report["damage"].append({"species": species, "flags": flags,
                                 "name": name})


def check_form_damage(errors: list[str], report: dict) -> None:
    """The form->column mapping, on a few rows the document pins down."""
    cases = [
        (0x09, 0x00, CREST_AIR, True, 0, 4, "Hippogriff 1 Aerial"),
        (0x09, 0x00, CREST_BASE, True, 0, 1, "Hippogriff 1 Fire"),
        (0xA5, 0x00, CREST_ULTIMATE, True, 0, 5, "Arma 1 Ultimate"),
        (0xA5, 0x04, CREST_TIME, True, 0, 10, "Arma 3 Legendary"),
        (0x68, 132, CREST_EARTH, True, 0, 3, "Belth Earth (ground)"),
        (0x68, 132, CREST_EARTH, False, 0, 1, "Belth Earth (air)"),
        (0x82, 0x00, CREST_EARTH, True, 0, 0, "Crawler Earth (N/A)"),
        (0x58, 0x00, CREST_BASE, True, 0, 0, "Flame Lord Fire (N/A)"),
        (0xBC, 0x00, CREST_BASE, True, 0, 2, "Dark Demon Fire form 1"),
        (0xBC, 0x00, CREST_BASE, True, 1, 1, "Dark Demon Fire form 2"),
        (0xBC, 0x00, CREST_ULTIMATE, True, 1, 2, "Dark Demon Ultimate 2"),
    ]
    for species, flags, form, grounded, phase, want, label in cases:
        got = bosses.boss_damage(species, flags, form, grounded, phase)
        if got != want:
            errors.append(f"form damage {label}: {got} != {want}")
            continue
        report["form_damage"].append({"species": species, "flags": flags,
                                      "form": form, "damage": got})
    if bosses.boss_damage(0x33, 128, CREST_BASE) is not None:
        errors.append("Somulo should have no damage row (scripted fight)")


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
    report: dict = {"doc": [], "doc_missing": [], "damage": [],
                    "form_damage": [], "rooms": [], "runtime": []}
    errors: list[str] = []

    if not doc_path.is_file():
        errors.append(f"missing {doc_path}")
    else:
        doc = parse_doc(doc_path)
        check_doc(doc, errors, report)
        check_damage(doc, errors, report)
        check_form_damage(errors, report)

    if not assets.is_dir():
        errors.append(f"missing assets dir {assets}")
        return 77
    records = boss_records(assets)
    check_rooms(records, errors, report)
    if not args.no_runtime:
        check_runtime(args.binary.resolve(), assets, records, args.tmp,
                      errors, report)

    print(f"boss hp: {len(report['doc'])} HP rows, {len(report['damage'])} "
          f"damage rows, {len(report['form_damage'])} form checks, "
          f"{len(records)} boss rooms, "
          f"{len(report['runtime'])} runtime boss checks, "
          f"{len(errors)} error(s)")
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
