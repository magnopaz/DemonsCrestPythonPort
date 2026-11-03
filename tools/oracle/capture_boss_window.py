#!/usr/bin/env python3
"""Capture a boss object's OAM over a frame window of a save state.

`capture_boss_poses` restarts the save for every sample and hides the other
object slots before the first sample, which freezes scripted sequences.  This
tool runs one continuous take instead: it advances the resumed state to
`--start`, then samples every `--step` frames up to `--end`, keeping the whole
OAM so poses can be attributed to the boss by geometry.

With `--isolate` the other object slots are hidden *after* the take reaches
`--isolate-frame` (default: the first sample), then one frame is run and the
sample is retaken.  The boss keeps drawing from its own record, but the room
relief and the player are gone, so the OAM of that sample contains only the
boss - which is what a baker needs.

Output per sample: `fNNN.oam.bin`, `.cgram.bin`, `.vram.bin`, `shot.png`
and a `meta.json` with the object record, world/screen position, PPU state and
the frame number.  The format mirrors `captures/rooms/fNNNNNN.json` closely
enough for the existing matcher (`oam`, `highOam`, `wram_1000`, `ppu`).

Usage:
  python3 tools/oracle/capture_boss_window.py \
      --save ../DemonsCrestSNESRecomp/build-trace/saves/somulo_player_control.sav \
      --species 0x33 --start 3400 --end 3560 --step 20 --out /tmp/somulo_window
  python3 tools/oracle/capture_boss_window.py --save ... --species 0x33 \
      --start 3480 --end 3480 --isolate --out /tmp/somulo_head_down
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
            time.sleep(0.004)

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", type=Path, required=True)
    ap.add_argument("--species", default="0x33")
    ap.add_argument("--slot", type=int, default=-1)
    ap.add_argument("--start", type=int, default=0,
                    help="frames after the resumed state to start sampling")
    ap.add_argument("--end", type=int, default=None,
                    help="last frame after resume (default: start)")
    ap.add_argument("--step", type=int, default=20)
    ap.add_argument("--isolate", action="store_true",
                    help="hide other object slots and retake the sample")
    ap.add_argument("--isolate-frame", type=int, default=None,
                    help="frame after resume at which to isolate "
                         "(default: the first sample)")
    ap.add_argument("--settle", type=int, default=30,
                    help="frames to run before reading the object pool")
    ap.add_argument("--port", type=int, default=4433)
    ap.add_argument("--out", type=Path, default=Path("/tmp/boss_window"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    species = int(args.species, 0)
    end = args.start if args.end is None else args.end
    iso_at = args.start if args.isolate_frame is None else args.isolate_frame

    resume = RECOMP / f"_dc_boss_window_{args.port}.sav"
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
        base = c.frame()
        c.run_to(base + args.settle)
        pool = c.read(OBJ_BASE, OBJ_STRIDE * OBJ_SLOTS)
        slot = args.slot
        if slot < 0:
            slot = next((i for i in range(OBJ_SLOTS)
                         if pool[i * OBJ_STRIDE] and
                         pool[i * OBJ_STRIDE + 2] == species), -1)
        if slot < 0:
            raise SystemExit(f"species {species:02X} not in the object pool")
        print(f"species {species:02X} in slot {slot}, resume frame {base}")

        meta = {"save": args.save.name, "species": species, "slot": slot,
                "start": args.start, "end": end, "step": args.step,
                "samples": []}
        frames = list(range(args.start, end + 1, args.step))
        if frames[-1] != end:
            frames.append(end)
        hidden = False
        for i, off in enumerate(frames):
            c.run_to(base + off)
            if args.isolate and not hidden and off >= iso_at:
                for k in range(OBJ_SLOTS):
                    if k == slot:
                        continue
                    addr = OBJ_BASE + k * OBJ_STRIDE
                    if c.read(addr, 1)[0]:
                        c.write(addr, b"\x00")
                c.run_to(c.frame() + 1)
                hidden = True
            rec = c.read(OBJ_BASE + slot * OBJ_STRIDE, OBJ_STRIDE)
            pool = c.read(OBJ_BASE, OBJ_STRIDE * OBJ_SLOTS)
            oam = c.dump("dump_oam")
            cgram = c.dump("dump_cgram")
            vram = c.dump("dump_vram")
            ppu = c.cmd("get_ppu_state")
            player = fx(c.read(0x1030, 6))
            off_px = player_offset(oam, player)
            world = fx(bytes([rec[0x30], rec[0x31], rec[0x32],
                              rec[0x33], rec[0x34], rec[0x35]]))
            name = f"f{i:03d}"
            (args.out / f"{name}.oam.bin").write_bytes(oam)
            (args.out / f"{name}.cgram.bin").write_bytes(cgram)
            (args.out / f"{name}.vram.bin").write_bytes(vram)
            (args.out / f"{name}.pool.bin").write_bytes(pool)
            shot = (args.out / f"{name}.png").resolve()
            try:
                c.cmd(f"screenshot {shot}")
            except RuntimeError:
                pass
            meta["samples"].append({
                "name": name, "frame": c.frame(), "offset": off,
                "record": rec.hex(), "species": rec[2], "state": rec[4],
                "counter": rec[0x2C] | (rec[0x2D] << 8),
                "world": list(world),
                "screen": [world[0] - off_px[0], world[1] - off_px[1]]
                          if off_px else list(world),
                "ppu": ppu.get("ppu", ppu), "isolated": hidden,
            })
            print(f"  {name} frame={c.frame()} off={off} state={rec[4]} "
                  f"counter={rec[0x2C] | (rec[0x2D] << 8)} "
                  f"world={world[0]:.1f},{world[1]:.1f} isolated={hidden}")
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
