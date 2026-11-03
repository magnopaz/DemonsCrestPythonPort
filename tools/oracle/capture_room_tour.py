#!/usr/bin/env python3
"""Walk the guest across a room and dump a frame every few steps.

A single capture only covers the 32/64-column window the camera sees, so a wide
room's BG1 stays mostly empty (`tools/oracle/merge_capture_bg1.py` cannot fill
what no frame ever showed).  This tool resumes a save, holds a direction, and
writes one `fNNNNNN.json` + `.vram.bin` every `--every` frames, so the merge
tool gets overlapping windows across the whole room.

Usage:
  python3 tools/oracle/capture_room_tour.py \
      --save ../DemonsCrestSNESRecomp/build-trace/saves/lvl_VII_phalanxs-fortress-demon-realm.sav \
      --out captures/tour_area43 --steps 12 --every 40 --direction right

Pairs with:
  python3 tools/oracle/merge_capture_bg1.py --area 43 --capture captures/tour_area43
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dump_save_wram import DEFAULT_RECOMP, DEFAULT_ROM, connect, wait_visible  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path,
                    default=Path(os.environ.get("RECOMP_DIR", DEFAULT_RECOMP)))
    ap.add_argument("--rom", type=Path, default=Path(os.environ.get("ROM", DEFAULT_ROM)))
    ap.add_argument("--save", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--direction", choices=("right", "left"), default="right")
    ap.add_argument("--steps", type=int, default=12)
    ap.add_argument("--every", type=int, default=40,
                    help="frames to hold the direction between captures")
    ap.add_argument("--settle", type=int, default=60)
    ap.add_argument("--port", type=int, default=5400)
    args = ap.parse_args()

    exe = args.recomp / "build-trace" / "DemonsCrestSNESRecomp"
    if not exe.is_file():
        raise SystemExit(f"missing trace build: {exe}")
    args.out.mkdir(parents=True, exist_ok=True)
    for old in list(args.out.glob("f*.json")) + list(args.out.glob("f*.vram.bin")):
        old.unlink()

    resume = (args.recomp / f"_dc_tour_{args.port}.sav").resolve()
    shutil.copyfile(args.save.resolve(), resume)
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "capture.log", "wb")
    proc = subprocess.Popen([str(exe), str(args.rom.resolve()), "--paused",
                             "--resume-state", str(resume)],
                            cwd=str(args.recomp), env=env, stdout=log, stderr=log)
    client = None
    written = []
    try:
        client = connect(args.port)
        wait_visible(client)
        client.run_to(client.frame() + args.settle)
        for step in range(args.steps):
            client.cmd(f"set_controller {args.direction}")
            client.run_to(client.frame() + args.every)
            client.cmd("set_controller 0")
            client.run_to(client.frame() + 2)
            n = max(0, client.frame() - 1)
            state = client.cmd(f"get_frame_extended {n}")
            vram = client.cmd(f"dump_frame_vram {n}")
            (args.out / f"f{n:06d}.json").write_text(json.dumps(state, indent=1))
            (args.out / f"f{n:06d}.vram.bin").write_bytes(
                bytes.fromhex(vram["hex"].replace(" ", "")))
            written.append(n)
            print(f"tour step {step + 1}/{args.steps}: frame {n}")
        (args.out / "capture.json").write_text(
            json.dumps({"save": str(args.save), "frames": written}, indent=1))
        print(f"{args.save.name}: {len(written)} frames -> {args.out}")
        return 0
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


if __name__ == "__main__":
    raise SystemExit(main())
