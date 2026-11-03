#!/usr/bin/env python3
"""Read the room-loader id out of a recomp save state, fast.

WRAM `$008D` holds the `Y` of the room loader's `LDA $81:A291,Y`, i.e. the
*byte* offset into the area pointer table: **area = $008D / 2**.  The values are
therefore always even (0, 2, 4, ... 192 across the save set).  Reading it as an
area number is what produced the old "save7=48, save8=74, save9=58" mapping —
those are 2x the real areas 24/37/29.

Use `tools/oracle/map_saves_to_areas.py` for the verified save -> area map
(it cross-checks this id against BG1/BG2 tilemap matching).

Usage:
  python3 tools/oracle/probe_save_area.py --save <state.sav> [...]
  python3 tools/oracle/probe_save_area.py --dir <saves dir> --jobs 3 --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dump_save_wram import DEFAULT_RECOMP, DEFAULT_ROM, connect, wait_visible  # noqa: E402

AREA_ADDR = 0x008D


def probe(save: Path, recomp: Path, rom: Path, port: int, settle: int) -> dict:
    exe = recomp / "build-trace" / "DemonsCrestSNESRecomp"
    resume = (recomp / f"_dc_probe_{port}.sav").resolve()
    shutil.copyfile(save.resolve(), resume)
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log_path = Path("/tmp") / f"dc_probe_{port}.log"
    log = open(log_path, "wb")
    proc = subprocess.Popen([str(exe), str(rom.resolve()), "--paused",
                             "--resume-state", str(resume)],
                            cwd=str(recomp), env=env, stdout=log, stderr=log)
    client = None
    try:
        client = connect(port, timeout=60)
        visible = wait_visible(client)
        client.run_to(client.frame() + settle)
        raw = client.read_ram(AREA_ADDR, 1)[0]
        return {"save": save.name, "area": raw, "area_hint": raw // 2,
                "visible": visible, "frame": client.frame()}
    except Exception as exc:  # noqa: BLE001 - report, keep the batch going
        return {"save": save.name, "error": str(exc)}
    finally:
        if client is not None:
            client.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        try:
            resume.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path, default=Path(os.environ.get("RECOMP_DIR", DEFAULT_RECOMP)))
    ap.add_argument("--rom", type=Path, default=Path(os.environ.get("ROM", DEFAULT_ROM)))
    ap.add_argument("--save", type=Path, action="append", default=[])
    ap.add_argument("--dir", type=Path,
                    help="probe every *.sav in this directory (skips .thumb files)")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--settle", type=int, default=45)
    ap.add_argument("--port", type=int, default=4800)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    saves = list(args.save)
    if args.dir:
        saves += sorted(p for p in args.dir.glob("*.sav") if not p.name.endswith(".thumb"))
    if not saves:
        raise SystemExit("pass --save or --dir")

    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(probe, s, args.recomp, args.rom, args.port + i, args.settle)
                   for i, s in enumerate(saves)]
        for fut in futures:
            r = fut.result()
            results.append(r)
            print(f"{r['save']:60s} area={r.get('area', '?')}"
                  f"{' ERROR ' + r['error'] if 'error' in r else ''}")
    if args.json:
        args.json.write_text(json.dumps(results, indent=1))
    ok = [r for r in results if "area" in r]
    print(f"{len(ok)}/{len(results)} probed")
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
