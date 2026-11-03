#!/usr/bin/env python3
"""Probe many save states in parallel into captures/rooms/<stem>/."""
from __future__ import annotations
import argparse, json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "oracle"))
from probe_save_room import probe, DEFAULT_RECOMP, DEFAULT_ROM  # noqa


def run(job):
    i, save, outdir, settle, offsets = job
    last = None
    for attempt in range(2):
        try:
            return probe(save, outdir, DEFAULT_RECOMP, DEFAULT_ROM,
                         4620 + i * 2 + attempt, settle, offsets)
        except BaseException as exc:  # noqa: BLE001 - SystemExit on load failure
            last = str(exc)
    return {"save": save.name, "error": last}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--saves", type=Path, required=True, help="dir with *.sav")
    ap.add_argument("--out", type=Path, default=ROOT / "captures" / "rooms")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--names", help="comma-separated save stems")
    ap.add_argument("--settle", type=int, default=40)
    ap.add_argument("--offsets", default="10,25,45")
    args = ap.parse_args()
    if args.names:
        saves = [args.saves / f"{n}.sav" for n in args.names.split(",")]
    else:
        saves = sorted(p for p in args.saves.glob("*.sav") if not p.name.endswith(".thumb"))
    if args.limit:
        saves = saves[:args.limit]
    offsets = [int(x) for x in args.offsets.split(",") if x.strip()]
    jobs = [(i, s, args.out / s.stem, args.settle, offsets)
            for i, s in enumerate(saves)]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for r in pool.map(run, jobs):
            print(json.dumps(r))


if __name__ == "__main__":
    main()
