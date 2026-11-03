#!/usr/bin/env python3
"""Assert that every retail object placement survives extraction.

The extractor used to type only the species listed in ``SPECIES_KIND_MAP`` and
silently drop the rest: 591 of the ROM's 853 object records never reached a room
JSON, so most rooms were empty inside while looking complete.  This gate makes
that class of loss impossible to reintroduce:

  * per area, the species multiset of the ``source="rom"`` objects equals the
    ROM's object list (a dropped, duplicated or invented record fails here);
  * the total is the ROM's 853 records;
  * every object carries a type the port knows, species with a handler are
    typed as that kind, and species without one are ``"unknown"`` (kept, never
    dropped);
  * a room full of unknown species boots and issues placeholder draws
    (``DC_TRACE_PLACEHOLDERS`` prints what the renderer actually drew).

Exit 77 when the binary or the assets are missing.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))

import extract as E  # noqa: E402
from dcpy.consts import LEVEL_OBJECT_TYPE_NAMES  # noqa: E402

# Areas where the retail object list ships a placeholder boss the verified boss
# table supersedes (apply_boss_table retypes it instead of deleting the record,
# so the placement survives as a placeholder).  Kept in sync with that tool.
STALE_BOSS_PLACEHOLDERS = {(52, 0x96), (54, 0x96)}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path,
                    default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    ap.add_argument("--rom", type=Path,
                    default=ROOT.parent / "roms" / "Demon's Crest (USA).sfc")
    ap.add_argument("--tmp", type=Path, default=None)
    return ap.parse_args()


def load_rooms(assets: Path) -> dict[int, dict]:
    rooms = {}
    for path in sorted(assets.glob("room_area*.json")):
        doc = json.loads(path.read_text())
        rooms[int(doc.get("area_id", -1))] = doc
    return rooms


def check_placement(assets: Path, rom: E.Rom):
    errors: list[str] = []
    rooms = load_rooms(assets)
    totals = collections.Counter()
    sources = collections.Counter()
    rom_total = 0
    unknown_by_area: dict[int, list[dict]] = {}

    for area in range(113):
        try:
            recs = rom.object_list(area)
        except Exception:
            recs = []
        rom_total += len(recs)
        doc = rooms.get(area)
        if doc is None:
            if recs:
                errors.append(f"area {area}: no room JSON for {len(recs)} "
                              f"ROM object record(s)")
            continue
        objects = doc.get("objects") or []
        rom_objects = [o for o in objects if o.get("source", "rom") == "rom"]
        have = collections.Counter(int(o.get("species", 0))
                                   for o in rom_objects)
        want = collections.Counter(int(r["species"]) for r in recs)
        if have != want:
            missing = want - have
            extra = have - want
            detail = []
            if missing:
                detail.append("missing " + ", ".join(
                    f"${s:02X}x{n}" for s, n in sorted(missing.items())))
            if extra:
                detail.append("unexpected " + ", ".join(
                    f"${s:02X}x{n}" for s, n in sorted(extra.items())))
            errors.append(f"area {area}: ROM records do not match the room "
                          f"({'; '.join(detail)})")
        for o in objects:
            species = int(o.get("species", 0))
            kind = o.get("type")
            source = o.get("source", "rom")
            totals[kind] += 1
            sources[source] += 1
            if kind not in LEVEL_OBJECT_TYPE_NAMES:
                errors.append(f"area {area}: species ${species:02X} has "
                              f"unloadable type {kind!r}")
                continue
            want_kind = E.SPECIES_KIND_MAP.get(species, "unknown")
            if source != "rom":
                # Objects injected by a verified table (boss/NPC) are typed by
                # that table, not by the species map: Scula ($7B/$7C) and the
                # other programmatic bosses have no SPECIES_KIND_MAP entry.
                pass
            elif (kind == "unknown" and want_kind != "unknown" and
                    (area, species) in STALE_BOSS_PLACEHOLDERS):
                pass  # documented: the retail placeholder boss, kept as art
            elif kind != want_kind:
                errors.append(f"area {area}: species ${species:02X} is typed "
                              f"{kind!r}, expected {want_kind!r}")
            if kind == "unknown":
                unknown_by_area.setdefault(area, []).append(o)

    if rom_total != 853:
        errors.append(f"ROM object table lists {rom_total} records, "
                      f"expected 853")
    if sources.get("rom", 0) != rom_total:
        errors.append(f"{sources.get('rom', 0)} ROM-sourced objects placed, "
                      f"expected {rom_total}")

    report = {
        "rom_total": rom_total,
        "types": dict(totals),
        "sources": dict(sources),
        "unknown_records": sum(len(v) for v in unknown_by_area.values()),
        "unknown_areas": len(unknown_by_area),
    }
    return errors, report, unknown_by_area, rooms


def run_placeholder(area: int, doc: dict, binary: Path, assets: Path,
                    tmp: Path) -> tuple[int, int, str]:
    """Boot ``area`` and return (drawn, visible, log) from the renderer."""
    player = tmp / f"player_area{area}.csv"
    env = dict(os.environ,
               DC_AREA=str(area),
               DC_RUN_FRAMES="4",
               DC_NO_AUDIO="1",
               DC_NO_SAVE="1",
               DC_TRACE_PLACEHOLDERS="1",
               DC_TRACE_CSV=str(player))
    for key in ("DC_DEMO", "DC_STATE", "DC_TITLE", "DC_CAMPAIGN",
                "DC_START_X", "DC_START_Y", "DC_BOSS_HP"):
        env.pop(key, None)
    proc = subprocess.run([str(binary), "--assets", str(assets)], cwd=ROOT,
                          env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=120)
    log = proc.stdout
    if proc.returncode != 0:
        raise RuntimeError(f"area {area}: binary exited {proc.returncode}\n"
                           + log[-1200:])
    drawn = visible = -1
    for field in ("placeholders_drawn", "placeholders_visible"):
        for line in log.splitlines():
            if field in line:
                for part in line.split():
                    if part.startswith(field + "="):
                        value = int(part.split("=", 1)[1])
                        if field == "placeholders_drawn":
                            drawn = value
                        else:
                            visible = value
    if drawn < 0 or visible < 0:
        raise RuntimeError(f"area {area}: no placeholder trace in:\n"
                           + log[-1200:])
    return drawn, visible, log


def main() -> int:
    args = parse_args()
    if not args.assets.is_dir():
        print("objects: skip (no assets)")
        return 77
    if not args.rom.is_file():
        print("objects: skip (no ROM)")
        return 77

    rom = E.Rom(args.rom)
    errors, report, unknown_by_area, rooms = check_placement(args.assets, rom)

    print(f"objects: {report['rom_total']} ROM records across 113 area lists")
    print(f"objects: placed by type " + ", ".join(
        f"{k}={v}" for k, v in sorted(
            (k, v) for k, v in report["types"].items() if k is not None)))
    print(f"objects: {report['unknown_records']} unknown-species placeholder "
          f"records in {report['unknown_areas']} rooms")

    if not args.binary.is_file():
        print("objects: skip runtime (no binary)")
        return 77 if not errors else 1

    with tempfile.TemporaryDirectory(prefix="dc-objects-") as td:
        tmp = Path(td)
        # Prefer a room where an unknown record sits inside the JSON's initial
        # camera box, so the placeholder is provably on screen; otherwise any
        # room with unknowns still proves the draw path.
        best = None
        for area, objs in unknown_by_area.items():
            doc = rooms.get(area) or {}
            cam = doc.get("camera", {})
            cx, cy = float(cam.get("x", 0)), float(cam.get("y", 0))
            for o in objs:
                ox, oy = float(o.get("x", 0)), float(o.get("y", 0))
                if not (0 <= ox < float(doc.get("world", {}).get("width", 0))):
                    continue
                on_screen = (cx <= ox < cx + 256 and cy <= oy < cy + 224)
                score = (0 if on_screen else 1,
                         abs(ox - cx) + abs(oy - cy))
                if best is None or score < best[0]:
                    best = (score, area, o)
        if best is None:
            errors.append("no room has an unknown-species record to draw")
        else:
            _score, area, obj = best
            try:
                drawn, visible, _log = run_placeholder(area, rooms[area],
                                                       args.binary, args.assets,
                                                       tmp)
            except RuntimeError as exc:
                errors.append(str(exc))
            else:
                print(f"objects: area {area} drew {drawn} placeholder(s), "
                      f"{visible} inside the viewport "
                      f"(species ${int(obj.get('species', 0)):02X})")
                if drawn <= 0:
                    errors.append(f"area {area}: the renderer drew no "
                                  f"placeholder for its unknown species")
                if visible <= 0:
                    errors.append(f"area {area}: no placeholder was inside "
                                  f"the viewport")

    if errors:
        print("objects: FAIL")
        for message in errors[:20]:
            print(f"  - {message}")
        if len(errors) > 20:
            print(f"  ... {len(errors) - 20} more")
        return 1
    print("objects: PASS (all 853 ROM records placed; unknown species "
          "drawn as placeholders)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
