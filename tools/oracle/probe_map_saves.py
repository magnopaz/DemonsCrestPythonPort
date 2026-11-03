#!/usr/bin/env python3
"""Probe the Mode 7 map saves for the object pool, in the map-marker format.

`tools/dc_extract/build_map_markers.py` expects a probe directory
(`<name>/info.json`) with the PPU mode and the live species list.  Nothing in the
repo produced that layout any more, so this tool does: resume each map save,
settle, read the 26-slot object pool at `$1080` (stride `$50`) and write
`info.json` with `ppu.bgmode`, `species` and `player`.

Usage:
  python3 tools/oracle/probe_map_saves.py --saves save11,map_new_stages
  python3 tools/dc_extract/build_map_markers.py --probes captures/map_probes \
      --saves save11,map_new_stages --out assets/generated/map_markers.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dump_save_wram import DEFAULT_RECOMP, DEFAULT_ROM, connect, wait_visible  # noqa: E402

OBJ_BASE = 0x1080
OBJ_STRIDE = 0x50
OBJ_SLOTS = 26


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path,
                    default=Path(os.environ.get("RECOMP_DIR", DEFAULT_RECOMP)))
    ap.add_argument("--rom", type=Path, default=Path(os.environ.get("ROM", DEFAULT_ROM)))
    ap.add_argument("--saves-dir", type=Path,
                    default=Path(DEFAULT_RECOMP) / "build-trace" / "saves")
    ap.add_argument("--saves", required=True, help="comma-separated save stems")
    ap.add_argument("--out", type=Path, default=Path("captures/map_probes"))
    ap.add_argument("--port", type=int, default=5700)
    args = ap.parse_args()

    exe = args.recomp / "build-trace" / "DemonsCrestSNESRecomp"
    for i, name in enumerate(s.strip() for s in args.saves.split(",") if s.strip()):
        save = args.saves_dir / f"{name}.sav"
        if not save.is_file():
            print(f"{name}: missing {save}")
            continue
        out = args.out / name
        out.mkdir(parents=True, exist_ok=True)
        port = args.port + i
        resume = (args.recomp / f"_dc_map_{port}.sav").resolve()
        shutil.copyfile(save, resume)
        env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(port),
                   SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        log = open(out / "probe.log", "wb")
        proc = subprocess.Popen([str(exe), str(args.rom.resolve()), "--paused",
                                 "--resume-state", str(resume)],
                                cwd=str(args.recomp), env=env, stdout=log, stderr=log)
        client = None
        try:
            client = connect(port)
            wait_visible(client)
            client.run_to(client.frame() + 60)
            wram = client.read_ram(0, 0x20000)
            ppu = client.cmd("get_ppu_state")
            ppu = ppu.get("ppu", ppu)
            species = []
            for slot in range(OBJ_SLOTS):
                rec = wram[OBJ_BASE + slot * OBJ_STRIDE:OBJ_BASE + (slot + 1) * OBJ_STRIDE]
                if not (rec[0x00] & 0x80) or not rec[0x02]:
                    continue
                species.append({
                    "slot": slot,
                    "species": rec[0x02],
                    "x": int.from_bytes(rec[0x04:0x06], "little"),
                    "y": int.from_bytes(rec[0x06:0x08], "little"),
                    "flags": rec[0x01],
                })
            info = {"save": name, "frame": client.frame(), "ppu": ppu,
                    "species": species, "player": None}
            (out / "info.json").write_text(json.dumps(info, indent=1))
            print(f"{name}: bgmode={ppu.get('bgmode')} objects={len(species)}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
