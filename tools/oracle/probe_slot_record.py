#!/usr/bin/env python3
"""Dump one live object slot's record, script bytes and OAM cluster.

Unlike `dump_species_metasprite.py` this does not inject anything: it resumes a
save state, waits for the object to exist and prints the record the guest itself
wrote.  That is what is needed for boss species that only ever exist inside a
scripted fight (species `0x33`, Somulo), where injecting a fresh record does not
reproduce the boss init.

Usage:
  python3 tools/oracle/probe_slot_record.py \
      --save ../DemonsCrestSNESRecomp/build-trace/saves/somulo_fight_starts.sav \
      --slot 8 --frames 2,10,20,40
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


def sprites_of(oam: bytes) -> list[dict]:
    out = []
    for i in range(128):
        x = oam[i * 4]
        y = oam[i * 4 + 1]
        attr = oam[i * 4 + 3]
        hi = oam[0x200 + i // 4]
        x |= ((hi >> ((i % 4) * 2)) & 1) << 8
        if x >= 256:
            x -= 512
        size = 16 if ((hi >> ((i % 4) * 2 + 1)) & 1) else 8
        if y >= 224:
            continue
        out.append({"i": i, "x": x, "y": y, "size": size,
                    "tile": oam[i * 4 + 2], "attr": attr,
                    "pal": (attr >> 1) & 7,
                    "hflip": bool(attr & 0x40), "vflip": bool(attr & 0x80)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", type=Path, required=True)
    ap.add_argument("--slot", type=int, default=8)
    ap.add_argument("--frames", default="2,10,20,40")
    ap.add_argument("--port", type=int, default=4423)
    ap.add_argument("--out", type=Path, default=Path("/tmp/slotprobe"))
    ap.add_argument("--radius", type=float, default=170.0)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    resume = RECOMP / f"_dc_slotprobe_{args.port}.sav"
    shutil.copyfile(args.save, resume)
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "log.txt", "wb")
    proc = subprocess.Popen(
        [str(RECOMP / "build-trace" / "DemonsCrestSNESRecomp"), str(ROM),
         "--paused", "--resume-state", str(resume)],
        cwd=str(RECOMP), env=env, stdout=log, stderr=log)
    try:
        c = connect(args.port)
        c.run_to(c.frame() + 1)
        report = {"save": args.save.name, "slot": args.slot, "samples": []}
        for step in [int(x) for x in args.frames.split(",") if x.strip()]:
            c.run_to(c.frame() + step)
            rec = c.read(OBJ_BASE + args.slot * OBJ_STRIDE, OBJ_STRIDE)
            oam = c.dump("dump_oam")
            player = fx(c.read(0x1030, 6))
            off = player_offset(oam, player)
            sx, sy = (fx(bytes([rec[0x30], rec[0x31], rec[0x32],
                                rec[0x33], rec[0x34], rec[0x35]])))
            sx -= off[0] if off else 0.0
            sy -= off[1] if off else 0.0
            script_ptr = rec[0x14] | (rec[0x15] << 8)
            sample = {
                "frame": c.frame(),
                "record": rec.hex(),
                "species": rec[2],
                "flags": rec[0],
                "state": rec[4],
                "substate": rec[5],
                "world": list(fx(bytes([rec[0x30], rec[0x31], rec[0x32],
                                        rec[0x33], rec[0x34], rec[0x35]]))),
                "screen": [sx, sy],
                "ptrs": {f"${f:02X}": f"{(rec[f] | (rec[f + 1] << 8)):04X}"
                         for f in (0x24, 0x26, 0x28, 0x2A, 0x2C, 0x2E)},
                "script_ptr": f"${script_ptr:04X}",
                "script": c.read(script_ptr, 64).hex() if script_ptr else "",
                "near": [s for s in sprites_of(oam)
                         if abs(s["x"] - sx) < args.radius
                         and abs(s["y"] - sy) < args.radius],
            }
            (args.out / f"f{c.frame():06d}.vram.bin").write_bytes(
                c.dump("dump_vram"))
            (args.out / f"f{c.frame():06d}.cgram.bin").write_bytes(
                c.dump("dump_cgram"))
            report["samples"].append(sample)
        (args.out / "report.json").write_text(json.dumps(report, indent=1))
        for s in report["samples"]:
            print(f"frame {s['frame']} species={s['species']:02X} "
                  f"flags={s['flags']:02X} state={s['state']} "
                  f"world={s['world'][0]:.1f},{s['world'][1]:.1f} "
                  f"screen={s['screen'][0]:.1f},{s['screen'][1]:.1f} "
                  f"ptrs={s['ptrs']} script={s['script_ptr']} "
                  f"near={len(s['near'])}")
            print("  record:", s["record"])
            print("  script:", s["script"])
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
