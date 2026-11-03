#!/usr/bin/env python3
"""Drive a recomp savestate with synthetic input and capture the result.

The debug server accepts `set_controller p1=<names|hex>` (e.g. `right+a`), so a
single savestate plus a button sequence can reproduce any later moment: walk
into a trigger, jump, press A, wait out a cutscene, then dump RAM/VRAM/OAM and a
screenshot.

Usage:
  python drive_save.py --save 1a --hold right --frames 180 \
      --out captures/drive/save1a_right --shot drive.bmp
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

RECOMP = Path(r"M:\Opencode\DemonsCrestSNESRecomp")
EXE = RECOMP / "build-trace" / "DemonsCrestSNESRecomp.exe"
ROM = Path(r"M:\Opencode\roms\Demon's Crest (USA).sfc")
SAVES = RECOMP / "build-trace" / "saves"

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
        out = b""
        for a in range(addr, addr + n, 0x100):
            out += bytes.fromhex(
                self.cmd(f"read_ram {a:x} 256")["hex"].replace(" ", ""))
        return out[:n]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def connect(port: int, timeout: float = 90) -> Client:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return Client(socket.create_connection(("127.0.0.1", port), timeout=2))
        except OSError:
            time.sleep(0.1)
    raise SystemExit("no debug server")


def fx24(data: bytes, off: int) -> float:
    return (data[off] | (data[off + 1] << 8) | (data[off + 2] << 16)) / 256.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", required=True, help="suffix, e.g. 1a")
    ap.add_argument("--hold", default="", help="buttons held, e.g. right+a")
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--warmup", type=int, default=30)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--shot", default="", help="screenshot path (bmp)")
    ap.add_argument("--after-frames", type=int, default=0,
                    help="release the buttons and run this many more frames")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    tmp = args.out / "resume.sav"
    candidates = [args.save, f"save{args.save}", f"save_{args.save}"]
    src = next((SAVES / f"{c}.sav" for c in candidates
                if (SAVES / f"{c}.sav").is_file()), None)
    if src is None:
        raise SystemExit(f"save not found: {args.save}")
    shutil.copyfile(src, tmp)
    port = free_port()
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "drive.log", "wb")
    proc = subprocess.Popen([str(EXE), str(ROM), "--paused",
                             "--resume-state", str(tmp)],
                            cwd=str(RECOMP), env=env, stdout=log, stderr=log)
    try:
        c = connect(port)

        def freeze_at(target: int) -> int:
            """Poll until the sim reaches `target`, then freeze on that frame."""
            while c.frame() < target:
                pass
            c.cmd("freeze_now")
            return c.frame()

        c.run_to(c.frame() + args.warmup)
        if args.hold:
            r = c.cmd(f"set_controller p1={args.hold}")
            if not r.get("ok", True):
                print("set_controller:", r)
        c.run_to(c.frame() + args.frames)
        if args.after_frames:
            c.cmd("set_controller p1=none")
            c.run_to(c.frame() + args.after_frames)
        # Wait for a visible frame: resuming often lands in a fade/transition.
        for _ in range(300):
            ppu_now = c.cmd("get_ppu_state")
            disp = int(str(ppu_now.get("inidisp", "0x80")), 16)
            if (disp & 0x0F) >= 0x0C:
                break
            c.run_to(c.frame() + 1)
        frozen_frame = freeze_at(c.frame() + 1)
        pool = c.read(OBJ_BASE, OBJ_STRIDE * OBJ_SLOTS)
        area = c.read(0x008D, 2)[0]
        pos = c.read(0x1030, 6)
        species = []
        for slot in range(OBJ_SLOTS):
            rec = pool[slot * OBJ_STRIDE:(slot + 1) * OBJ_STRIDE]
            if len(rec) < 0x36 or rec[0] == 0 or rec[2] == 0:
                continue
            species.append({"slot": slot, "flags": rec[0],
                            "species": rec[2],
                            "x": round(fx24(rec, 0x30), 1),
                            "y": round(fx24(rec, 0x33), 1)})
        c.cmd("set_controller p1=none")
        info = {"save": args.save, "hold": args.hold,
                "frozen_frame": frozen_frame,
                "frames": args.frames, "area": area,
                "player": [round(fx24(pos, 0), 1), round(fx24(pos, 3), 1)],
                "species": species}
        ppu = c.cmd("get_ppu_state")
        info["ppu"] = {k: ppu.get(k) for k in ("bgmode", "inidisp")}
        (args.out / "vram.bin").write_bytes(
            bytes.fromhex(c.cmd("dump_vram")["hex"].replace(" ", "")))
        (args.out / "cgram.bin").write_bytes(
            bytes.fromhex(c.cmd("dump_cgram")["hex"].replace(" ", "")))
        (args.out / "oam.bin").write_bytes(
            bytes.fromhex(c.cmd("dump_oam")["hex"].replace(" ", "")))
        (args.out / "info.json").write_text(json.dumps(info, indent=1))
        if args.shot:
            shot = (args.out / args.shot).resolve().as_posix()
            print("screenshot:", c.cmd(f"screenshot {shot}"))
            c.cmd("unfreeze")
        sp = ", ".join(f"{s['species']:02X}@{s['x']:.0f},{s['y']:.0f}"
                       for s in species)
        print(f"save{args.save} +{args.frames}f hold='{args.hold}': "
              f"area {area} player {info['player']} species [{sp}]")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
