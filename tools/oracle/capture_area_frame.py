#!/usr/bin/env python3
"""Capture one or more oracle frames from any recomp save state.

This is the cross-platform, named-save counterpart of `capture_save_frames.py`
(which hard-codes the Windows `M:\\Opencode` paths and integer save names).  It
writes the same on-disk format the extractor consumes:

    <out>/fNNNNNN.json      get_frame_extended() state (CPU/PPU/CGRAM/OAM)
    <out>/fNNNNNN.vram.bin  64 KiB VRAM for that frame

Usage:
  python3 tools/oracle/capture_area_frame.py \
      --save build-trace/saves/lvl_I_murkland-cemetery.sav \
      --out captures/lvl_I_murkland-cemetery --offsets 60,90

The area id is not stored in the save file; the caller maps a capture to an
area in tools/dc_extract/bg2_captures.json.  Use --identify to print a
candidate list based on the room's object species (best effort).
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

OBJ_BASE = 0x1080
OBJ_STRIDE = 0x50
OBJ_SLOTS = 26


def parse_offsets(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x.strip()]


def pool_objects(wram: bytes) -> list[dict]:
    out = []
    for slot in range(OBJ_SLOTS):
        rec = wram[OBJ_BASE + slot * OBJ_STRIDE:OBJ_BASE + (slot + 1) * OBJ_STRIDE]
        if len(rec) < 0x36 or not (rec[0x00] & 0x80):
            continue
        species = rec[0x02]
        if not species:
            continue
        out.append({
            "slot": slot,
            "species": species,
            "x": int.from_bytes(rec[0x04:0x06], "little"),
            "y": int.from_bytes(rec[0x06:0x08], "little"),
            "flags": rec[0x01],
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path, default=Path(os.environ.get("RECOMP_DIR", DEFAULT_RECOMP)))
    ap.add_argument("--rom", type=Path, default=Path(os.environ.get("ROM", DEFAULT_ROM)))
    ap.add_argument("--save", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--offsets", default="60",
                    help="comma-separated frames after the first lit frame (default 60)")
    ap.add_argument("--settle", type=int, default=90,
                    help="frames to run before the first offset (default 90)")
    ap.add_argument("--port", type=int, default=4530)
    ap.add_argument("--identify", action="store_true",
                    help="print live object species to help map the capture to an area")
    args = ap.parse_args()

    exe = args.recomp / "build-trace" / "DemonsCrestSNESRecomp"
    if not exe.is_file():
        raise SystemExit(f"missing trace build: {exe}")
    args.out.mkdir(parents=True, exist_ok=True)
    for old in list(args.out.glob("f*.json")) + list(args.out.glob("f*.vram.bin")):
        old.unlink()

    # Paths handed to the host must be absolute: a relative --resume-state is
    # resolved against the recomp's working directory, which silently fails.
    resume = (args.recomp / f"_dc_area_{args.port}.sav").resolve()
    shutil.copyfile(args.save.resolve(), resume)

    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "capture.log", "wb")
    proc = subprocess.Popen([str(exe), str(args.rom.resolve()), "--paused",
                             "--resume-state", str(resume)],
                            cwd=str(args.recomp), env=env, stdout=log, stderr=log)
    client = None
    try:
        client = connect(args.port)
        visible = wait_visible(client)
        client.run_to(client.frame() + args.settle)
        start = client.frame()
        written = []
        for offset in parse_offsets(args.offsets):
            target = start + offset
            client.run_to(target)
            client.run_to(client.frame() + 2)
            n = max(0, client.frame() - 1)  # newest completed ring frame
            state = client.cmd(f"get_frame_extended {n}")
            vram = client.cmd(f"dump_frame_vram {n}")
            (args.out / f"f{n:06d}.json").write_text(json.dumps(state, indent=1))
            (args.out / f"f{n:06d}.vram.bin").write_bytes(
                bytes.fromhex(vram["hex"].replace(" ", "")))
            written.append(n)
        meta = {"save": str(args.save), "frames": written, "visible": visible}
        if args.identify:
            wram = client.read_ram(0, 0x20000)
            meta["objects"] = pool_objects(wram)
            if meta["objects"]:
                print("objects:", ", ".join(
                    f"{o['species']:02x}@({o['x']},{o['y']})" for o in meta["objects"]))
        (args.out / "capture.json").write_text(json.dumps(meta, indent=1))
        print(f"{args.save.name}: frames {written} visible={visible}")
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
