#!/usr/bin/env python3
"""Locate the ROM's player-projectile array by differentiating WRAM.

The player's fireballs do not live in the 26-slot object pool (the
rec_kill_enemies replay shows no slot moving at shot speed while the
user fires).  This tool replays a take to a shot-dense stretch, reads
low WRAM on consecutive frames and reports every 16-bit word whose
value steps by ~0x300 fx units (3 px/frame, PLAYER_FIREBALL_VX_FX)
for several frames -- the signature of a projectile coordinate.

Usage:
  python tools/oracle/find_projectiles.py <take> [--frames gSTART:gEND]
      [--step 1] [--port N]

Writes nothing; prints the candidate addresses and their trajectories.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_stage as ts  # noqa: E402  (reuse Client/launch/connect)

FX_STEP = 0x300        # 3 px/frame in 8.8, the fireball speed
LO = 0x0000            # low WRAM window (DP vars, tasks, pools)
HI = 0x8000            # the array may sit past the object pool


def words(buf: bytes):
    return [buf[i] | (buf[i + 1] << 8) for i in range(0, len(buf) - 1, 2)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("take", type=Path)
    ap.add_argument("--frames", default="10420:10560",
                    help="guest-frame window with shots in flight")
    ap.add_argument("--quiet", default="9300:9440",
                    help="baseline window without shots")
    ap.add_argument("--lo", default="0000",
                    help="scan window start (16-bit hex)")
    ap.add_argument("--hi", default="8000",
                    help="scan window end (16-bit hex)")
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--port", type=int, default=8261)
    args = ap.parse_args()

    log = args.take / "input_log.jsonl"
    samples = []
    with open(log) as f:
        for line in f:
            d = json.loads(line)
            samples.append({"frame": d["frame"], "inputs": d["inputs"],
                            "active": d.get("active", 1)})
    replay = Path("/tmp/find_proj_replay.jsonl")
    replay.write_text("\n".join(
        json.dumps(s, separators=(",", ":")) for s in samples) + "\n")

    rom = ts.find_rom(os.environ.get("SNESRECOMP_ROM", ""))
    exe = ts.find_exe(ts.RECOMP)
    if not exe.is_file():
        raise SystemExit("find_projectiles: no oracle exe; run from the repo")
    proc = ts.launch(exe, rom, args.port, [])
    try:
        c = ts.connect(args.port)
        reply = c.cmd(f"replay_input {replay.as_posix()}")
        if not reply.get("samples"):
            raise SystemExit("replay_input loaded 0 samples")

        lo = int(args.lo, 16)
        hi = int(args.hi, 16)
        g0, g1 = (int(x) for x in args.frames.split(":"))
        q0, q1 = (int(x) for x in args.quiet.split(":"))
        # advance in chunks: run_to's wait deadline is 120 s and the
        # emulator covers ~20 fps, so one giant jump times out
        here = c.frame()
        first = min(g0, q0)
        for g in range(here + 400, first, 400):
            c.run_to(g)
        c.run_to(first)

        def collect(a, b):
            snaps = {}
            g = a
            while g <= b:
                c.run_to(g)
                snaps[g] = bytes(c.read(lo, hi - lo))
                g += args.step
            return snaps

        quiet = collect(q0, q1) if q0 < g0 else {}
        snaps = collect(g0, g1)
        gs = sorted(snaps)

        # any word that MOVES consistently while shots fly and is quiet
        # in the baseline: the projectile speed is unknown a priori.
        series = {}
        for i in range(1, len(gs)):
            a, b = gs[i - 1], gs[i]
            wa, wb = words(snaps[a]), words(snaps[b])
            for j in range(len(wa)):
                d = wb[j] - wa[j]
                if d == 0:
                    continue
                if d > 0x8000:
                    d -= 0x10000
                per = abs(d) / args.step
                # the coordinate may be 8.8 fx (0x300/frame), plain
                # pixels (3/frame), or an age/life counter (+1/frame)
                if 1 <= per <= 0x800:
                    series.setdefault(j, []).append((a, wa[j], d))
        stable = set()
        if quiet:
            qs = sorted(quiet)
            for j in range(len(words(quiet[qs[0]]))):
                vals = {words(quiet[g])[j] for g in qs}
                if len(vals) <= 2:
                    stable.add(j)
        strong = {}
        for j, hits in series.items():
            if len(hits) < 4:
                continue
            if quiet and j not in stable:
                continue
            # consistent sign within 2x magnitude spread
            ds = [d for _, _, d in hits]
            if max(ds) * min(ds) <= 0:
                continue
            strong[lo + j * 2] = hits
        print(f"janela g{g0}-{g1} (baseline g{q0}-{q1}) "
              f"${args.lo}-${args.hi}: "
              f"{len(strong)} palavras em movimento consistente")
        for addr, hits in sorted(strong.items())[:24]:
            traj = " ".join(f"g{g}:{d:+d}" for g, v, d in hits[:5])
            vals = " ".join(f"{v:04X}" for g, v, d in hits[:5])
            print(f"  ${addr:04X}: deltas {traj} | {vals}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
