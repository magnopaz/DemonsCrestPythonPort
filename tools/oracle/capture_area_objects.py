#!/usr/bin/env python3
"""Capture per-species sprite data from a real save state.

Resumes a recomp save, waits for a fully lit frame, then dumps OAM/CGRAM/VRAM
plus the object pool, writing one `s<species>/f<frame>.json` record per live
species in the extractor's `extract_species.py` format. That lets sprites for
enemies and bosses be baked from actual gameplay instead of an injected test
object.

Usage:
  python tools/oracle/capture_area_objects.py --save 7 --out captures/obj_save7 \
      --frames 0,30,60,90
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

RECOMP = Path(r"M:\Opencode\DemonsCrestSNESRecomp")
EXE = RECOMP / "build-trace" / "DemonsCrestSNESRecomp.exe"
ROM = Path(r"M:\Opencode\roms\Demon's Crest (USA).sfc")
SAVES = RECOMP / "build-trace" / "saves"
def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()

OBJ_BASE = 0x1080
OBJ_STRIDE = 0x50
OBJ_SLOTS = 26


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

    def read(self, addr, n):
        return bytes.fromhex(self.cmd(f"read_ram {addr:x} {n}")["hex"].replace(" ", ""))


def connect(timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(("127.0.0.1", PORT), timeout=2)
        except OSError:
            time.sleep(0.1)
    raise SystemExit("no debug server")


def fx24(data: bytes, off: int) -> float:
    return (data[off] | (data[off + 1] << 8) | (data[off + 2] << 16)) / 256.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--frames", default="0,30,60,90")
    ap.add_argument("--warmup", type=int, default=60)
    args = ap.parse_args()

    offsets = [int(x) for x in args.frames.split(",") if x.strip()]
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
        if os.environ.get("DC_CAP_DEBUG"):
            print("  [dbg] connected, raw frame:", c.cmd("frame"))

        def visible_ppu():
            for _ in range(240):
                time.sleep(0.03)
                raw = c.cmd("get_ppu_state")
                ppu = raw.get("ppu", raw)
                try:
                    disp = int(str(ppu.get("inidisp", "0x80")), 16)
                except ValueError:
                    disp = 0x80
                if (disp & 0x0F) >= 0x0C:
                    return ppu
                c.run_to(c.frame() + 1)
            return ppu

        c.run_to(c.frame() + args.warmup)
        start = c.frame()
        written = {}
        prev = 0
        for off in offsets:
            # Advance by the delta: visible_ppu() can move past `start + off`, and
            # run_to_frame only ever moves forward.
            c.run_to(c.frame() + max(0, off - prev))
            prev = off
            ppu = visible_ppu()
            frame = c.frame()
            if os.environ.get("DC_CAP_DEBUG"):
                print(f"  [dbg] after run_to frame={frame} inidisp={ppu.get('inidisp')}")
            cgram = c.cmd("dump_cgram")["hex"].replace(" ", "")
            oam = c.cmd("dump_oam")["hex"].replace(" ", "")
            vram = bytes.fromhex(c.cmd("dump_vram")["hex"].replace(" ", ""))
            # The debug server truncates long reads, so pull the pool in chunks.
            pool = b""
            chunk = 0x100
            for start_addr in range(OBJ_BASE, OBJ_BASE + OBJ_STRIDE * OBJ_SLOTS,
                                    chunk):
                pool += c.read(start_addr, chunk)
            player = c.read(0x1030, 6)
            player_world = [fx24(player, 0), fx24(player, 3)]
            species_seen = set()
            for slot in range(OBJ_SLOTS):
                rec = pool[slot * OBJ_STRIDE:(slot + 1) * OBJ_STRIDE]
                if len(rec) < 0x36 or not (rec[0x00] & 0x80):
                    continue
                species = rec[0x02]
                if species == 0 or species in species_seen:
                    continue
                species_seen.add(species)
                state = {
                    "frame": frame,
                    "ppu": ppu,
                    "cgram": cgram,
                    "oam": oam,
                    "object_world": [fx24(rec, 0x30), fx24(rec, 0x33)],
                    "player_world": player_world,
                }
                sp_dir = args.out / f"s{species:02x}"
                sp_dir.mkdir(exist_ok=True)
                (sp_dir / f"f{frame:06d}.json").write_text(json.dumps(state))
                (sp_dir / f"f{frame:06d}.vram.bin").write_bytes(vram)
                written.setdefault(species, 0)
                written[species] += 1
            print(f"frame {frame}: species {sorted(hex(s) for s in species_seen)}")
        print("captures per species:", {hex(k): v for k, v in written.items()})
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
