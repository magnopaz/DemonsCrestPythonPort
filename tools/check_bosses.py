#!/usr/bin/env python3
"""Validate the data contract and runtime presence of the ported bosses.

The physics demos do not notice when a boss points at the wrong species, uses
the wrong Arma palette, or is placed outside the room/camera. This checker does
two cheap passes:

1. static: every expected room boss has the right species/flags/position and a
   non-empty texture; the second Phalanx body and the Arma palette variants are
   present in ``species_anim.json``;
2. runtime: each boss room is booted briefly with ``DC_BOSS_NO_ATTACK=1`` and
   the object trace must contain the expected active boss species.

Usage:
  python tools/check_bosses.py --assets assets/generated
  python tools/check_bosses.py --binary tools/demonscrest-py --runtime

Exit codes: 0 = pass, 1 = contract failure, 77 = binary/assets missing.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# area -> (name, species, expected flags or None, x, y)
BOSSES = {
    1: [("Hippogriff", 0x09, 0, 1920, 168)],
    # Area 3's live Arma is at (856, 151) in arma_boss.sav ($008D = 6, camera
    # y = 0).  The old (856, 1180) came from the object list's row-offset
    # encoding and put the boss 1024 px below the fight, inside solid rock.
    3: [("Arma", 0xA5, 0, 856, 151)],
    23: [("Arma", 0xA5, 2, 640, 1932)],
    26: [("Scula", 0x7B, 0, 1320, 154),
         ("Scula", 0x7C, 0, 1380, 154)],
    36: [("Arma", 0xA5, 4, 304, 140)],
    52: [("Holothurion", 0x6F, None, 216, 183)],
    54: [("Ovnunu", 0x16, None, 216, 183)],
    67: [("Arma", 0xA5, 4, 272, 140)],
    68: [("Crawler", 0x82, 0, 1808, 160)],
    84: [("Phalanx first form", 0x86, 0, 198, 173)],
    86: [("Flame Lord", 0x58, 0, 128, 120)],
    90: [("Dark Demon", 0xBC, 0, 128, 120)],
}

# Species that must have regular (non-boss) art.
BASE_SPECIES = {0x7B, 0x7C, 0x6F, 0x16, 0x58, 0xBC, 0x82, 0x86, 0xA5}

# (species, flags) boss-sheet variants selected by object flags.
VARIANTS = [(0x8D, 0), (0xA5, 2), (0xA5, 4)]

VIEWPORT_H = 224


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path,
                    default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    ap.add_argument("--runtime", action="store_true",
                    help="boot each boss room and inspect the object trace")
    ap.add_argument("--tmp", type=Path, help="scratch dir for trace CSVs")
    ap.add_argument("--json", type=Path)
    return ap.parse_args()


def entries_for(species_anim: dict, species: int, boss: bool | None) -> list:
    out = []
    for key, entry in species_anim.get("species", {}).items():
        if not isinstance(entry, dict) or entry.get("species") != species:
            continue
        is_boss = entry.get("variant") == "boss"
        if boss is not None and is_boss != boss:
            continue
        out.append((key, entry))
    return out


def frame_textures(entry: dict) -> list[str]:
    return [f.get("texture", "") for f in entry.get("frames", [])
            if isinstance(f, dict)]


def check_art(assets: Path, errors: list[str], report: dict) -> None:
    path = assets / "species_anim.json"
    if not path.is_file():
        errors.append("species_anim.json is missing")
        return
    try:
        anim = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        errors.append(f"species_anim.json is invalid: {exc}")
        return

    for species in sorted(BASE_SPECIES):
        matches = entries_for(anim, species, boss=False)
        if not matches:
            errors.append(f"species {species:02x}: no regular art entry")
            continue
        frames = [tex for _, entry in matches for tex in frame_textures(entry)]
        if not frames:
            errors.append(f"species {species:02x}: art entry has no frames")
            continue
        for tex in frames:
            if not (assets / tex).is_file():
                errors.append(f"species {species:02x}: missing {tex}")
        report["base"].append({"species": species, "frames": len(frames)})

    seen_variants: set[tuple[int, int]] = set()
    for species, flags in VARIANTS:
        matches = [(key, entry) for key, entry in entries_for(anim, species, True)
                   if int(entry.get("flags", 0)) == flags]
        if not matches:
            errors.append(f"species {species:02x}: missing boss variant flags={flags}")
            continue
        key, entry = matches[0]
        if (species, flags) in seen_variants:
            errors.append(f"species {species:02x}: duplicate variant flags={flags}")
        seen_variants.add((species, flags))
        frames = frame_textures(entry)
        if not frames:
            errors.append(f"species {species:02x} flags={flags}: no frames")
        for tex in frames:
            if not (assets / tex).is_file():
                errors.append(
                    f"species {species:02x} flags={flags}: missing {tex}")
        report["variants"].append(
            {"species": species, "flags": flags, "key": key,
             "frames": len(frames)})


def check_rooms(assets: Path, errors: list[str], report: dict) -> None:
    for area, expected in BOSSES.items():
        path = assets / f"room_area{area}.json"
        if not path.is_file():
            errors.append(f"area {area}: room JSON is missing")
            continue
        room = json.loads(path.read_text())
        objects = [o for o in room.get("objects", [])
                   if o.get("type") == "boss"]
        camera = room.get("camera", {})
        world = room.get("world", {})
        world_w = float(world.get("width", 0))
        world_h = float(world.get("height", 0))
        cam_y = float(camera.get("y", 0))
        if not objects:
            errors.append(f"area {area}: no boss object")
            continue
        if len(objects) != len(expected):
            errors.append(
                f"area {area}: {len(objects)} boss objects, "
                f"expected {len(expected)}")
        for name, species, flags, x, y in expected:
            found = [o for o in objects
                     if o.get("species") == species
                     and (flags is None or o.get("flags") == flags)]
            if not found:
                errors.append(
                    f"area {area} ({name}): missing species {species:02x} "
                    f"flags={flags}")
                continue
            obj = found[0]
            ox, oy = float(obj.get("x", 0)), float(obj.get("y", 0))
            if not (0.0 <= ox <= world_w and 0.0 <= oy <= world_h):
                errors.append(
                    f"area {area} ({name}): position {ox},{oy} outside "
                    f"world {world_w}x{world_h}")
            # Tall rooms (area 3 is 1280 px) are fought over several screens, so
            # the initial camera rect is not a bound: the boss only has to sit
            # inside the room's play box.
            play = room.get("play", {})
            if world_h <= VIEWPORT_H * 1.5:
                if not (cam_y <= oy <= cam_y + VIEWPORT_H):
                    errors.append(
                        f"area {area} ({name}): y={oy} outside camera band "
                        f"{cam_y}..{cam_y + VIEWPORT_H}")
            else:
                lo = float(play.get("min_y", 0.0))
                hi = float(play.get("max_y", world_h))
                if not (lo <= oy <= hi):
                    errors.append(
                        f"area {area} ({name}): y={oy} outside play band "
                        f"{lo}..{hi}")
            if not (0.0 < oy < world_h):
                errors.append(f"area {area} ({name}): degenerate boss y={oy}")
            report["rooms"].append(
                {"area": area, "name": name, "species": species,
                 "flags": obj.get("flags"), "x": ox, "y": oy})


def check_runtime(binary: Path, assets: Path, tmp: Path | None,
                  errors: list[str], report: dict) -> None:
    if not binary.is_file():
        errors.append(f"runtime: missing binary {binary}")
        return

    def run_case(area: int, suffix: str, expected: list,
                 extra_env: dict[str, str] | None = None) -> None:
        trace = Path(td) / f"area{area}{suffix}.csv"
        env = dict(os.environ)
        env.update({
            "DC_AREA": str(area),
            "DC_RUN_FRAMES": "30",
            "DC_NO_AUDIO": "1",
            "DC_NO_SAVE": "1",
            "DC_BOSS_NO_ATTACK": "1",
            "DC_BOSS_INTRO": "0",
            "DC_NO_STORY": "1",
            "DC_TRACE_OBJECTS": str(trace),
        })
        if extra_env:
            env.update(extra_env)
        for key in ("DC_BOSS_DEFEATED", "DC_BOSS_CLEAR", "DC_STATE",
                    "DC_DEMO", "DC_START_X", "DC_START_Y", "DC_RESUME",
                    "DC_STAGE_SELECT", "DC_BOSS_PHASE"):
            env.pop(key, None)
        if extra_env:
            env.update(extra_env)
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
        rows = list(csv.DictReader(trace.open(newline="")))
        bosses = [r for r in rows if r.get("type") == "6"]
        active = {int(r.get("species", -1)): r for r in bosses}
        for name, species, flags, *_pos in expected:
            if species not in active:
                errors.append(
                    f"runtime area {area}{suffix} ({name}): species "
                    f"{species:02x} did not spawn")
                continue
            row = active[species]
            if flags is not None and int(row.get("flags", 0)) != flags:
                errors.append(
                    f"runtime area {area}{suffix} ({name}): flags "
                    f"{row.get('flags')} != {flags}")
        report["runtime"].append(
            {"area": area, "case": suffix or "default",
             "species": sorted(active), "rows": len(rows)})

    tmp_parent = str(tmp) if tmp else None
    with tempfile.TemporaryDirectory(prefix="dc-boss-runtime-", dir=tmp_parent) as td:
        for area in sorted(BOSSES):
            run_case(area, "", BOSSES[area])
        # Second Phalanx form: test hook bypasses the first-form death only for
        # this smoke run; the normal $86 path is covered above.
        run_case(84, "_phase2",
                 [("Phalanx second form", 0x8D, 0, 198, 173)],
                 {"DC_BOSS_PHASE": "2"})


def main() -> int:
    args = parse_args()
    assets = args.assets.resolve()
    report = {"base": [], "variants": [], "rooms": [], "runtime": []}
    errors: list[str] = []
    check_art(assets, errors, report)
    check_rooms(assets, errors, report)
    if args.runtime:
        check_runtime(args.binary.resolve(), assets, args.tmp, errors, report)

    print(f"bosses: {len(BASE_SPECIES)} art species, "
          f"{len(VARIANTS)} variants, {len(BOSSES)} rooms, "
          f"{len(report['runtime'])} runtime runs, {len(errors)} error(s)")
    for error in errors:
        print(f"  ERROR {error}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=1))
        print(f"boss report: {args.json}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
