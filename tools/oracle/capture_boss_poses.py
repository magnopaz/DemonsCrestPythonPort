#!/usr/bin/env python3
"""Capture a boss object's own OAM frames, isolated from room scenery.

The colosseum's dragon relief is a set of static objects drawn with the same
palette as Somulo's head, so an OAM crop by palette alone picks up scenery.  This
tool hides every object slot except the boss (writing a zero to the slot's
active flag), then dumps OAM/VRAM/CGRAM for a series of frames, together with the
boss record (world position, pointers, animation counter) so a baker can measure
the anchor from the guest's own numbers.

`--poke FIELD=VALUE` writes a byte into the boss record before each sample, which
is how the pose counter ($2C) and the frame pointers ($28/$2A/$2E) are walked to
enumerate the animation without scripting a whole fight.

Usage:
  python3 tools/oracle/capture_boss_poses.py \
      --save ../DemonsCrestSNESRecomp/build-trace/saves/somulo_fight_starts.sav \
      --species 0x33 --frames 4,8,12,16 --out captures/boss_somulo
  python3 tools/oracle/capture_boss_poses.py --save ... --species 0x33 \
      --poke 2c=0,2c=1,2c=2,2c=3 --out captures/boss_somulo_poke
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

ROOT = Path(__file__).resolve().parents[2]
RECOMP = Path(os.environ.get("RECOMP_DIR", ROOT.parent / "DemonsCrestSNESRecomp"))
ROM = Path(os.environ.get("ROM", ROOT.parent / "roms" / "Demon's Crest (USA).sfc"))
OBJ_BASE, OBJ_STRIDE, OBJ_SLOTS = 0x1080, 0x50, 26


class Client:
    def __init__(self, sock: socket.socket):
        self.f = sock.makefile("rwb")

    def cmd(self, text: str) -> dict:
        self.f.write((text + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise RuntimeError("debug server closed")
        msg = json.loads(line)
        if "error" in msg:
            raise RuntimeError(f"{text!r}: {msg['error']}")
        return msg

    def frame(self) -> int:
        return int(self.cmd("frame")["frame"])

    def run_to(self, target: int) -> None:
        if self.frame() >= target:
            return
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + 300
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError(f"timeout waiting for frame {target}")
            time.sleep(0.005)

    def read(self, addr: int, n: int) -> bytes:
        return bytes.fromhex(
            self.cmd(f"read_ram {addr:x} {n}")["hex"].replace(" ", ""))

    def write(self, addr: int, data: bytes) -> None:
        self.cmd(f"write_ram {addr:x} {data.hex()}")

    def dump(self, command: str) -> bytes:
        return bytes.fromhex(self.cmd(command)["hex"].replace(" ", ""))


def connect(port: int, timeout: float = 120.0) -> Client:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return Client(socket.create_connection(("127.0.0.1", port),
                                                   timeout=3))
        except OSError:
            time.sleep(0.1)
    raise SystemExit(f"no debug server on port {port}")


def fx(raw: bytes) -> tuple[float, float]:
    return ((raw[0] | (raw[1] << 8) | (raw[2] << 16)) / 256.0,
            (raw[3] | (raw[4] << 8) | (raw[5] << 16)) / 256.0)


def player_offset(oam: bytes, player) -> tuple[float, float] | None:
    groups = []
    for i in range(128):
        x = oam[i * 4]
        y = oam[i * 4 + 1]
        attr = oam[i * 4 + 3]
        hi = oam[0x200 + i // 4]
        x |= ((hi >> ((i % 4) * 2)) & 1) << 8
        if x >= 256:
            x -= 512
        size = 16 if ((hi >> ((i % 4) * 2 + 1)) & 1) else 8
        if y >= 224 or ((attr >> 1) & 7) != 7:
            continue
        for g in groups:
            if any(abs(x - gx) < 40 and abs(y - gy) < 64 for gx, gy, _s in g):
                g.append((x, y, size))
                break
        else:
            groups.append([(x, y, size)])
    if not groups:
        return None
    best = max(groups, key=len)
    cx = (min(x for x, _y, _s in best) + max(x + s for x, _y, s in best)) / 2.0
    fy = max(y + s for _x, y, s in best)
    return player[0] - cx, player[1] - fy


def parse_pokes(items: list[str]) -> list[tuple[int, int, int]]:
    """`2c=0` -> (offset, low_byte, high_byte); `28=D93D` -> 16-bit write."""
    out = []
    for item in items:
        field, _, value = item.partition("=")
        off = int(field, 16)
        val = int(value, 16)
        if val > 0xFF:
            out.append((off, val & 0xFF, (val >> 8) & 0xFF))
        else:
            out.append((off, val, None))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", type=Path, required=True)
    ap.add_argument("--species", default="0x33")
    ap.add_argument("--slot", type=int, default=-1,
                    help="object slot; -1 finds the first matching species")
    ap.add_argument("--frames", default="4,8,12,16",
                    help="frame steps to advance between samples")
    ap.add_argument("--poke", default="",
                    help="comma separated FIELD=HEX pokes applied per sample")
    ap.add_argument("--keep-others", action="store_true",
                    help="do not hide the other object slots")
    ap.add_argument("--port", type=int, default=4425)
    ap.add_argument("--settle", type=int, default=30)
    ap.add_argument("--out", type=Path, default=Path("/tmp/bosscap"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    species = int(args.species, 0)
    pokes = parse_pokes([p for p in args.poke.split(",") if p.strip()])
    steps = [int(x) for x in args.frames.split(",") if x.strip()]

    resume = RECOMP / f"_dc_bosscap_{args.port}.sav"
    shutil.copyfile(args.save, resume)
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "capture.log", "wb")
    proc = subprocess.Popen(
        [str(RECOMP / "build-trace" / "DemonsCrestSNESRecomp"), str(ROM),
         "--paused", "--resume-state", str(resume)],
        cwd=str(RECOMP), env=env, stdout=log, stderr=log)
    try:
        c = connect(args.port)
        c.run_to(c.frame() + args.settle)
        pool = c.read(OBJ_BASE, OBJ_STRIDE * OBJ_SLOTS)
        slot = args.slot
        if slot < 0:
            slot = next((i for i in range(OBJ_SLOTS)
                         if pool[i * OBJ_STRIDE] and
                         pool[i * OBJ_STRIDE + 2] == species), -1)
        if slot < 0:
            raise SystemExit(f"species {species:02X} not in the object pool")
        print(f"species {species:02X} in slot {slot}")

        if not args.keep_others:
            for i in range(OBJ_SLOTS):
                if i == slot:
                    continue
                addr = OBJ_BASE + i * OBJ_STRIDE
                if c.read(addr, 1)[0]:
                    c.write(addr, b"\x00")
            c.run_to(c.frame() + 1)

        meta = {"save": args.save.name, "species": species, "slot": slot,
                "pokes": [[o, lo, hi] for o, lo, hi in pokes], "samples": []}
        idx = 0
        for step in steps:
            c.run_to(c.frame() + step)
            for off, lo, hi in pokes:
                addr = OBJ_BASE + slot * OBJ_STRIDE + off
                c.write(addr, bytes([lo]) if hi is None else bytes([lo, hi]))
            if pokes:
                c.run_to(c.frame() + 1)
            rec = c.read(OBJ_BASE + slot * OBJ_STRIDE, OBJ_STRIDE)
            oam = c.dump("dump_oam")
            cgram = c.dump("dump_cgram")
            vram = c.dump("dump_vram")
            player = fx(c.read(0x1030, 6))
            off = player_offset(oam, player)
            world = fx(bytes([rec[0x30], rec[0x31], rec[0x32],
                              rec[0x33], rec[0x34], rec[0x35]]))
            name = f"f{idx:03d}"
            (args.out / f"{name}.oam.bin").write_bytes(oam)
            (args.out / f"{name}.cgram.bin").write_bytes(cgram)
            (args.out / f"{name}.vram.bin").write_bytes(vram)
            ppu = c.cmd("get_ppu_state")
            meta["samples"].append({
                "name": name, "frame": c.frame(), "record": rec.hex(),
                "species": rec[2], "state": rec[4], "flags": rec[0],
                "counter": rec[0x2C] | (rec[0x2D] << 8),
                "ptrs": [f"{(rec[o] | (rec[o + 1] << 8)):04X}"
                         for o in (0x28, 0x2A, 0x2E)],
                "world": list(world),
                "screen": [world[0] - off[0], world[1] - off[1]] if off else
                          list(world),
                "ppu": ppu.get("ppu", ppu),
            })
            print(f"  {name} frame={c.frame()} state={rec[4]} "
                  f"counter={rec[0x2C] | (rec[0x2D] << 8)} "
                  f"world={world[0]:.1f},{world[1]:.1f}")
            idx += 1
        (args.out / "meta.json").write_text(json.dumps(meta, indent=1))
        print("wrote", args.out / "meta.json")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        resume.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
