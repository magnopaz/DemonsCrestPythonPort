#!/usr/bin/env python3
"""Capture frames from a recomp save state into the extractor's capture format.

Loads a `save<N>.sav`, runs it to a set of frame offsets and writes
`fNNNNNN.json` + `fNNNNNN.vram.bin` (the same format `capture_anim.py`
produces), so the extractor can bake BG2 backdrops and atlases from real
gameplay areas that the default save0 cannot reach.

Usage:
  python capture_save_frames.py --save 10 --out captures/save10 \
      --frames 0,20,40,60,80,100,120,140
  python capture_save_frames.py --save 10 --out captures/save10 --spacing 15 --count 8
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

RECOMP = Path(r"M:\Opencode\DemonsCrestSNESRecomp")
EXE = RECOMP / "build-trace" / "DemonsCrestSNESRecomp.exe"
ROM = Path(r"M:\Opencode\roms\Demon's Crest (USA).sfc")
SAVES = RECOMP / "build-trace" / "saves"
PORT = 4415


class Client:
    def __init__(self, sock):
        self.f = sock.makefile("rwb")

    def cmd(self, text):
        self.f.write((text + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        return json.loads(line) if line else {}

    def frame(self):
        return int(self.cmd("frame")["frame"])

    def run_to(self, target):
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + 180
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError("timeout")
            time.sleep(0.01)
        time.sleep(0.05)


def connect(timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(("127.0.0.1", PORT), timeout=2)
        except OSError:
            time.sleep(0.1)
    raise SystemExit("no debug server")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--frames", default="")
    ap.add_argument("--spacing", type=int, default=15)
    ap.add_argument("--count", type=int, default=8)
    ap.add_argument("--warmup", type=int, default=60,
                    help="frames to run before the first capture (the "
                         "game resumes in forced blank)")
    ap.add_argument("--no-run", action="store_true",
                    help="dump immediately after resume: the restored VRAM "
                         "stays intact, while running frames can reload it "
                         "(use for Mode 7 map baking)")
    args = ap.parse_args()

    offsets = ([int(x) for x in args.frames.split(",") if x.strip()]
               if args.frames else [i * args.spacing for i in range(args.count)])
    if args.no_run:
        offsets = offsets[:1]
    args.out.mkdir(parents=True, exist_ok=True)
    tmp = args.out / "resume.sav"
    shutil.copyfile(SAVES / f"save{args.save}.sav", tmp)
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(PORT),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "capture.log", "wb")
    proc = subprocess.Popen([str(EXE), str(ROM), "--paused",
                             "--resume-state", str(tmp)],
                            cwd=str(RECOMP), env=env, stdout=log, stderr=log)
    try:
        c = Client(connect())

        def visible_ppu(client):
            """Advance until the PPU is not in forced blank; return its state."""
            ppu_state = {}
            for _ in range(240):
                time.sleep(0.03)
                raw = client.cmd("get_ppu_state")
                ppu_state = raw.get("ppu", raw)
                try:
                    disp = int(str(ppu_state.get("inidisp", "0x80")), 16)
                except ValueError:
                    disp = 0x80
                # Require a fully lit frame: 0x80/0x01 samples happen while the
                # game blanks mid-frame, and baking those gives black atlases.
                if (disp & 0x0F) >= 0x0C:
                    return ppu_state
                client.run_to(client.frame() + 1)
            return ppu_state

        # The resume state starts in forced blank; let the game fade in first,
        # unless only the restored VRAM is needed (map baking): running frames
        # can make the game re-upload and replace it.
        if not args.no_run:
            c.run_to(c.frame() + args.warmup)
        start = c.frame()
        for off in offsets:
            if not args.no_run:
                c.run_to(start + off)
            ppu_body = (c.cmd("get_ppu_state") if args.no_run
                        else visible_ppu(c))
            ppu = {"ppu": ppu_body.get("ppu", ppu_body) if args.no_run
                       else ppu_body}
            cgram = c.cmd("dump_cgram")["hex"].replace(" ", "")
            oam = c.cmd("dump_oam")["hex"].replace(" ", "")
            vram = bytes.fromhex(c.cmd("dump_vram")["hex"].replace(" ", ""))
            wram = bytes.fromhex(c.cmd("dump_ram 0 65536")["hex"].replace(" ", ""))
            dp = bytes.fromhex(c.cmd("read_ram 0 256")["hex"].replace(" ", ""))
            frame = start + off
            state = {
                "frame": frame,
                "ppu": ppu.get("ppu", ppu),
                "cgram": cgram,
                "oam": oam,
                "wram_1000": wram[0x1000:0x2000].hex(),
                "zeropage": dp.hex(),
            }
            (args.out / f"f{frame:06d}.json").write_text(json.dumps(state))
            (args.out / f"f{frame:06d}.vram.bin").write_bytes(vram)
            inidisp = state["ppu"].get("inidisp", "?")
            print(f"captured frame {frame} (offset {off}) inidisp={inidisp}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        tmp.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
