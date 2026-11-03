#!/usr/bin/env python3
"""Map recomp save states to the port's extracted rooms (`room_area<N>.json`).

Two independent signals are combined:

1. **WRAM `$008D`** — the room loader reads the area pointer table with an
   indexed load, `LDA $A291,Y`, and the guest keeps that same `Y` in `$008D`.
   The table entries are 2 bytes, so `$008D` is the *byte* offset: `area =
   $008D / 2`.  Every one of the 54 distinct values observed across the save
   set is even, and the division reproduces every room that BG1 can identify.
   (The older note in `docs/PROJECT_STATE.md` that called `$008D` a "stage id"
   was reading the raw byte as if it were the area index — hence the "save7=48,
   save8=74, save9=58" guesses, which are exactly 2x the real areas 24/37/29.)

2. **BG1/BG2 tilemap** — `room_match` matches the live BG layer against the
   ROM's 256-screen table and reports which areas contain that screen.  This is
   the verification signal: a correct mapping scores 1.000 (32/32 tile rows),
   or a lower value when the camera has split a screen across the VRAM window.

Areas that share an info block *and* a grid block in `$81:A291`/`$81:A6D8` are
byte-identical rooms in the ROM (e.g. 1/73, 0/72, 30/71); BG1 cannot separate
them and neither can the port's JSONs, so the tie is reported explicitly and the
lowest id is chosen as the canonical representative.

Usage:
  python3 tools/oracle/map_saves_to_areas.py                # probe + match all
  python3 tools/oracle/map_saves_to_areas.py --no-probe      # reuse captures/rooms
  python3 tools/oracle/map_saves_to_areas.py --save <one.sav> --probe
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "oracle"))
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))

import room_match  # noqa: E402
from probe_save_room import DEFAULT_RECOMP, DEFAULT_ROM, STAGE_ID, probe  # noqa: E402

DEFAULT_SAVES = DEFAULT_RECOMP / "build-trace" / "saves"
EXACT = 0.999
GOOD = 0.60


OBJ_BASE, OBJ_STRIDE, OBJ_SLOTS = 0x1080, 0x50, 26


def live_species(wram: bytes) -> list[int]:
    """Species bytes of the 26 live object-pool slots ($1080, stride $50)."""
    out = []
    for slot in range(OBJ_SLOTS):
        rec = wram[OBJ_BASE + slot * OBJ_STRIDE:OBJ_BASE + (slot + 1) * OBJ_STRIDE]
        if len(rec) < 0x36 or not (rec[0] & 0x80):
            continue
        if rec[2]:
            out.append(rec[2])
    return out


def object_check(probe_dir: Path, area: int, rom,
                 cache: dict[int, collections.Counter]) -> dict:
    """Third, independent signal: live object species vs each area's object list."""
    wram_path = probe_dir / "wram.bin"
    if not wram_path.is_file():
        return {}
    live = collections.Counter(live_species(wram_path.read_bytes()))
    if not live:
        return {"object_species": []}

    def overlap(a: int) -> int:
        if a not in cache:
            cache[a] = collections.Counter(r["species"] for r in rom.object_list(a))
        return sum((live & cache[a]).values())

    scores = {a: overlap(a) for a in range(113)}
    best = max(scores.values())
    best_areas = [a for a, s in scores.items() if s == best and best > 0]
    return {"object_species": sorted(live),
            "object_overlap": scores.get(area, 0),
            "object_best_areas": best_areas[:8],
            "object_best": bool(best and best_areas and area in best_areas),
            "object_unique": bool(best and best_areas == [area])}


def tie_classes(rom) -> dict[int, int]:
    """area -> canonical area for byte-identical ROM entries (same info+grid)."""
    seen: dict[tuple[int, int], int] = {}
    canon: dict[int, int] = {}
    for area in range(113):
        p = rom.u16(0x81, 0xA291 + area * 2)
        q = rom.u16(0x81, 0xA6D8 + area * 2)
        canon[area] = seen.setdefault((p, q), area)
    return canon


def probe_all(saves: list[Path], out_root: Path, jobs: int) -> None:
    from concurrent.futures import ThreadPoolExecutor

    def run(job):
        i, save = job
        outdir = out_root / save.stem
        if (outdir / "meta.json").is_file() and list(outdir.glob("f*.vram.bin")):
            return {"save": save.name, "cached": True}
        last = None
        for attempt in range(2):
            try:
                return probe(save, outdir, DEFAULT_RECOMP, DEFAULT_ROM,
                             4820 + i * 2 + attempt)
            except BaseException as exc:  # noqa: BLE001 - SystemExit on load fail
                last = str(exc)
        return {"save": save.name, "error": last}

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for r in pool.map(run, [(i, s) for i, s in enumerate(saves)]):
            print(json.dumps(r), flush=True)


def decide(meta: dict, match: dict, canon: dict[int, int],
           screen_areas: dict | None = None) -> dict:
    """Combine the loader id ($008D/2) with the BG1/BG2 evidence."""
    ranked = match["ranked"]
    top_score, top_area, top_detail = ranked[0] if ranked else (0.0, None, {})
    by_area = {a: v for _, a, v in ranked}
    stage_id = meta.get("stage_id_8d")
    hint = stage_id // 2 if isinstance(stage_id, int) and stage_id % 2 == 0 else None
    row = {"save": meta.get("save"), "raw_id": stage_id, "area": None,
           "score": 0.0, "method": None, "tied_areas": [], "screen": None,
           "layer": None, "frame": None}
    if hint is not None:
        detail = by_area.get(hint)
        hint_score = detail["score"] if detail else 0.0
        row.update(area=hint, score=round(hint_score, 3))
        if detail:
            row.update(screen=list(detail["screen"]), layer=detail["layer"],
                       frame=detail["frame"])
        if detail and hint_score >= EXACT:
            row["method"] = "stage_id+bg1"
        elif top_score >= EXACT and top_area != hint:
            # BG1 sees a whole screen that belongs to another area: real conflict.
            row["method"] = "stage_id+bg1-conflict"
            row["bg1_top"] = top_area
            row["bg1_top_score"] = round(top_score, 3)
        elif detail and hint_score >= GOOD:
            row["method"] = "stage_id+bg1-partial"
        else:
            row["method"] = "stage_id"
            if ranked:
                row["bg1_top"] = top_area
                row["bg1_top_score"] = round(top_score, 3)
    elif ranked:
        row.update(area=top_area, score=round(top_score, 3), method="bg1",
                   screen=list(top_detail["screen"]), layer=top_detail["layer"],
                   frame=top_detail["frame"])
    if row["area"] is not None:
        if screen_areas and row.get("screen"):
            sa = sorted({a for a, _ in screen_areas.get(tuple(row["screen"]), [])})
            row["screen_areas"] = sa
            if row["score"] >= GOOD and row["area"] in sa:
                row["verified"] = "screen-unique" if sa == [row["area"]] else "screen-dup-class"
                row["tied_areas"] = sa
            else:
                row["verified"] = "loader-only"
        else:
            row["verified"] = "loader-only"
        area_score = by_area.get(row["area"], {}).get("score")
        if area_score is not None and area_score >= 0.90:
            row["tied_areas"] = sorted(a for _, a, v in ranked
                                       if abs(v["score"] - area_score) < 1e-9)
        row["canonical_area"] = canon.get(row["area"], row["area"])
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--saves", type=Path, default=DEFAULT_SAVES)
    ap.add_argument("--probes", type=Path, default=ROOT / "captures" / "rooms")
    ap.add_argument("--out", type=Path, default=ROOT / "captures" / "save_to_area.json")
    ap.add_argument("--save", type=Path, action="append", default=[])
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--no-probe", action="store_true",
                    help="do not run the oracle; only use existing probe dirs")
    ap.add_argument("--cache", type=Path, default=ROOT / "captures" / "room_matches.json",
                    help="per-save match cache (avoids re-scoring 219 probe dirs)")
    ap.add_argument("--use-cache", action="store_true",
                    help="reuse --cache instead of re-scoring the probe dirs")
    args = ap.parse_args()

    saves = list(args.save)
    if not saves:
        saves = sorted(p for p in args.saves.glob("*.sav")
                       if not p.name.endswith(".thumb"))
    if not saves:
        raise SystemExit("no saves found")

    if not args.no_probe:
        probe_all(saves, args.probes, args.jobs)

    rom = room_match.load_rom()
    rows_index = room_match.build_screen_rows(rom)
    screen_areas = room_match.build_screen_to_areas(rom)
    canon = tie_classes(rom)

    obj_cache: dict[int, collections.Counter] = {}
    cache: dict[str, dict] = {}
    if args.use_cache and args.cache.is_file():
        cache = json.loads(args.cache.read_text())
    out = []
    for save in saves:
        d = args.probes / save.stem
        meta_path = d / "meta.json"
        if not meta_path.is_file():
            out.append({"save": save.name, "error": "no probe"})
            continue
        meta = json.loads(meta_path.read_text())
        meta.setdefault("save", save.name)
        if save.stem in cache:
            match = cache[save.stem]
        else:
            match = room_match.identify_dir(d, rom, rows_index, screen_areas)
            cache[save.stem] = match
        row = decide(meta, match, canon, screen_areas)
        row.update(object_check(d, row["area"], rom, obj_cache) if row["area"] is not None else {})
        out.append(row)
        print(f"{save.name:58s} raw_id={row['raw_id']!s:>4} area={row['area']!s:>4} "
              f"score={row['score']:<5} method={row['method']} "
              f"ties={row['tied_areas'][:6]}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1))
    if cache:
        args.cache.write_text(json.dumps(cache))
    ok = [r for r in out if r.get("area") is not None]
    exact = [r for r in ok if r["method"] == "stage_id+bg1"]
    partial = [r for r in ok if r["method"] == "stage_id+bg1-partial"]
    conflict = [r for r in ok if r["method"] == "stage_id+bg1-conflict"]
    unverified = [r for r in ok if r["method"] == "stage_id"]
    print(f"\n{len(ok)}/{len(out)} saves mapped -> {args.out}")
    print(f"  BG1 exact (1.000): {len(exact)}")
    print(f"  BG1 partial:       {len(partial)}")
    print(f"  stage_id only:     {len(unverified)}")
    print(f"  conflicts:         {len(conflict)}")
    ver = {}
    for r in ok:
        ver[r.get("verified")] = ver.get(r.get("verified"), 0) + 1
    print(f"  verification:      {ver}")
    with_obj = [r for r in ok if r.get("object_species")]
    obj_ok = [r for r in with_obj if r.get("object_overlap")]
    obj_best = [r for r in with_obj if r.get("object_best")]
    obj_uniq = [r for r in with_obj if r.get("object_unique")]
    print(f"  object pool:       {len(obj_ok)}/{len(with_obj)} share a species with the "
          f"mapped area ({len(obj_best)} best, {len(obj_uniq)} uniquely best)")
    for r in conflict:
        print(f"    ! {r['save']}: loader area {r['area']} but BG1 area "
              f"{r['bg1_top']} scores {r['bg1_top_score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())