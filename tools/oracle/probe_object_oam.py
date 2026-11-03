#!/usr/bin/env python3
"""List live objects of a save state together with the OAM they render.

For every active object slot this prints species, world position, the $8B-bank
pointer fields ($28/$2A/$2E) and how many OAM entries sit near the object's
projected screen position. That distinguishes "species init ran" from "species
is actually drawn", which is what sprite baking needs.

Usage:
  python3 tools/oracle/probe_object_oam.py --save <sav> [--frames 30,60,90]
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
RECOMP = ROOT.parent / "DemonsCrestSNESRecomp"
ROM = ROOT.parent / "roms" / "Demon's Crest (USA).sfc"
OBJ_BASE, OBJ_STRIDE, OBJ_SLOTS = 0x1080, 0x50, 26


class Client:
    def __init__(self, sock):
        self.f = sock.makefile("rwb")

    def cmd(self, text):
        self.f.write((text + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise RuntimeError("debug server closed")
        msg = json.loads(line)
        if "error" in msg:
            raise RuntimeError(f"{text!r}: {msg['error']}")
        return msg

    def frame(self):
        return int(self.cmd("frame")["frame"])

    def run_to(self, t):
        if self.frame() >= t:
            return
        self.cmd(f"run_to_frame {t}")
        deadline = time.monotonic() + 300
        while self.frame() < t:
            if time.monotonic() > deadline:
                raise RuntimeError("timeout")
            time.sleep(0.005)

    def read(self, addr, n):
        return bytes.fromhex(self.cmd(f"read_ram {addr:x} {n}")["hex"].replace(" ", ""))

    def dump(self, cmd):
        return bytes.fromhex(self.cmd(cmd)["hex"].replace(" ", ""))


def connect(port, timeout=120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return Client(socket.create_connection(("127.0.0.1", port), timeout=3))
        except OSError:
            time.sleep(0.1)
    raise SystemExit("no debug server")


def fx(raw):
    return ((raw[0] | (raw[1] << 8) | (raw[2] << 16)) / 256.0,
            (raw[3] | (raw[4] << 8) | (raw[5] << 16)) / 256.0)


def player_offset(oam, player):
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
    fx_ = (min(x for x, _y, _s in best) + max(x + s for x, _y, s in best)) / 2.0
    fy = max(y + s for _x, y, s in best)
    return player[0] - fx_, player[1] - fy


def probe(save, port, frames):
    out = Path("/tmp/objprobe") / save.stem
    out.mkdir(parents=True, exist_ok=True)
    resume = RECOMP / f"_dc_objprobe_{port}.sav"
    shutil.copyfile(save, resume)
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(out / "log.txt", "wb")
    proc = subprocess.Popen([str(RECOMP / "build-trace" / "DemonsCrestSNESRecomp"),
                             str(ROM), "--paused", "--resume-state", str(resume)],
                            cwd=str(RECOMP), env=env, stdout=log, stderr=log)
    try:
        c = connect(port)
        c.run_to(c.frame() + frames[0])
        report = {"save": save.name, "samples": []}
        for extra in frames:
            c.run_to(c.frame() + extra)
            pool = c.read(OBJ_BASE, OBJ_STRIDE * OBJ_SLOTS)
            oam = c.dump("dump_oam")
            player = fx(c.read(0x1030, 6))
            off = player_offset(oam, player)
            sprites = []
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
                sprites.append({"i": i, "x": x, "y": y, "size": size,
                                "tile": oam[i * 4 + 2],
                                "pal": (oam[i * 4 + 3] >> 1) & 7})
            objs = []
            for slot in range(OBJ_SLOTS):
                r = pool[slot * OBJ_STRIDE:(slot + 1) * OBJ_STRIDE]
                if r[0] == 0 or r[2] == 0:
                    continue
                wx, wy = fx(bytes([r[0x30], r[0x31], r[0x32],
                                   r[0x33], r[0x34], r[0x35]]))
                sx = wx - off[0] if off else wx
                sy = wy - off[1] if off else wy
                near = [s for s in sprites
                        if abs(s["x"] - sx) < 48 and abs(s["y"] - sy) < 64]
                objs.append({
                    "slot": slot, "species": r[2], "flags": r[0],
                    "world": [wx, wy], "screen": [sx, sy],
                    "ptr28": f"{r[0x28] | (r[0x29] << 8):04x}",
                    "ptr2a": f"{r[0x2a] | (r[0x2b] << 8):04x}",
                    "ptr2e": f"{r[0x2e] | (r[0x2f] << 8):04x}",
                    "near_oam": near[:12], "near_count": len(near),
                })
            report["samples"].append({"frame": c.frame(),
                                      "player": list(player),
                                      "offset": list(off) if off else None,
                                      "objects": objs})
        (out / "report.json").write_text(json.dumps(report, indent=1))
        return report
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        resume.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", type=Path, required=True)
    ap.add_argument("--port", type=int, default=4418)
    ap.add_argument("--frames", default="30,60")
    args = ap.parse_args()
    frames = [int(x) for x in args.frames.split(",") if x.strip()]
    rep = probe(args.save.resolve(), args.port, frames)
    for s in rep["samples"]:
        print(f"frame {s['frame']} offset={s['offset']}")
        for o in s["objects"]:
            print(f"  slot {o['slot']:2d} sp={o['species']:02X} flags={o['flags']:02X} "
                  f"world={o['world'][0]:.0f},{o['world'][1]:.0f} "
                  f"ptrs={o['ptr28']}/{o['ptr2a']}/{o['ptr2e']} "
                  f"near_oam={o['near_count']}")


if __name__ == "__main__":
    raise SystemExit(main())
