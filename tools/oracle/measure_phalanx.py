#!/usr/bin/env python3
"""Dump Phalanx's object slots while replaying a take.

The chamber fight (area 42) is the one scene the bad-ending take actually shows
(docs/TAKES.md §7.1), and the port's `$86` AI is still a guess (drift + orb).
This tool replays the input and, per sample, prints every object slot whose
species byte is the boss's (and the player's position, for the camera), with the
raw record so state/sub-state can be decoded afterwards.

Record layout (same one trace_stage.py reads; 0x50 bytes per slot at $1080+X*$50):
    $00 flags?  $01 ?  $02 species  $03 flags  $30..$32 x (24-bit)  $33..$35 y

Usage:
  python3 tools/oracle/measure_phalanx.py <take> -o /tmp/phalanx.csv \
      --from 3700 --to 8100 --step 10 [--species 86,8d,88]

Exit: 0 ok, 2 no debug server / no samples.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECOMP = Path(os.environ.get("RECOMP_DIR", ROOT.parent / "DemonsCrestSNESRecomp"))
ROM = Path(os.environ.get("ROM", ROOT.parent / "roms" / "Demon's Crest (USA).sfc"))
POOL = 0x1080
SLOTS = 26
STRIDE = 0x50


def find_exe(root: Path) -> Path:
    for rel in ("build-trace/DemonsCrestSNESRecomp.exe",
                "build-trace/DemonsCrestSNESRecomp",
                "build/DemonsCrestSNESRecomp.exe",
                "build/DemonsCrestSNESRecomp"):
        if (root / rel).is_file():
            return root / rel
    return root / "build-trace" / "DemonsCrestSNESRecomp.exe"


class Client:
    def __init__(self, sock: socket.socket):
        self.f = sock.makefile("rwb")

    def cmd(self, text: str) -> dict:
        self.f.write((text + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise RuntimeError(f"debug server closed after {text!r}")
        msg = json.loads(line)
        if "error" in msg:
            raise RuntimeError(f"{text!r}: {msg['error']}")
        return msg

    def frame(self) -> int:
        return int(self.cmd("frame")["frame"])

    def run_to(self, target: int, timeout: float = 1800.0) -> None:
        if self.frame() >= target:
            return
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + timeout
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError(f"timeout at frame {target}")
            time.sleep(0.02)

    def read(self, addr: int, n: int) -> bytes:
        out = b""
        for a in range(addr, addr + n, 0x100):
            out += bytes.fromhex(
                self.cmd(f"read_ram {a:x} {min(0x100, addr + n - a)}")["hex"]
                .replace(" ", ""))
        return out[:n]


def connect(port: int, timeout: float = 120.0) -> Client:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return Client(socket.create_connection(("127.0.0.1", port), timeout=3))
        except OSError:
            time.sleep(0.1)
    raise SystemExit(f"measure_phalanx: no debug server on port {port}")


def build_replay(take: Path, out: Path) -> Path:
    log = take / "input_log.jsonl" if take.is_dir() else take
    if not log.is_file():
        raise SystemExit(f"measure_phalanx: missing {log}")
    samples = [json.loads(line) for line in log.read_text().splitlines()
               if line.strip()]
    first = samples[0]
    offset = first.get("gframe", first["frame"]) - first["frame"]
    rows = [json.dumps({"frame": f, "inputs": 0, "active": 3},
                       separators=(",", ":")) for f in range(offset)]
    for s in samples:
        rows.append(json.dumps({"frame": s.get("gframe", s["frame"]),
                                "inputs": s.get("inputs", 0),
                                "active": s.get("active", 3)},
                               separators=(",", ":")))
    path = out / "replay.jsonl"
    path.write_text("\n".join(rows) + "\n")
    return path


def fx24(buf: bytes, off: int) -> float:
    return (buf[off] | buf[off + 1] << 8 | buf[off + 2] << 16) / 256.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("take", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("/tmp/phalanx.csv"))
    ap.add_argument("--from", dest="start", type=int, required=True)
    ap.add_argument("--to", dest="end", type=int, required=True)
    ap.add_argument("--step", type=int, default=10)
    ap.add_argument("--species", default="86,8d,88",
                    help="comma-separated species bytes to dump (hex)")
    ap.add_argument("--port", type=int, default=4641)
    ap.add_argument("--recomp", type=Path, default=RECOMP)
    ap.add_argument("--rom", type=Path, default=ROM)
    args = ap.parse_args()

    want = {int(s, 16) for s in args.species.split(",") if s.strip()}
    take = args.take if args.take.is_dir() else args.take.parent
    args.out.parent.mkdir(parents=True, exist_ok=True)
    replay = build_replay(take, args.out.parent)

    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out.with_suffix(".log"), "wb")
    proc = subprocess.Popen([str(find_exe(args.recomp)), str(args.rom.resolve()),
                             "--paused"],
                            cwd=str(args.recomp / "build-trace"), env=env,
                            stdout=log, stderr=log)
    try:
        c = connect(args.port)
        reply = c.cmd(f"replay_input {replay.as_posix()}")
        if not reply.get("samples"):
            raise SystemExit("measure_phalanx: replay_input loaded 0 samples")
        c.run_to(1)
        rows = []
        for g in range(args.start, args.end + 1, args.step):
            c.run_to(g)
            area8d = c.read(0x008D, 1)[0]
            task = c.read(0x1000, 0x80)
            pool = c.read(POOL, SLOTS * STRIDE)
            base = dict(gframe=g, area=area8d // 2, pstate=task[5], psub=task[6],
                        px=round(fx24(task, 0x30), 1), py=round(fx24(task, 0x33), 1))
            found = False
            for i in range(SLOTS):
                rec = pool[i * STRIDE:(i + 1) * STRIDE]
                if not any(rec) or rec[2] not in want:
                    continue
                found = True
                rows.append(dict(base, slot=i, species=rec[2],
                                 flags=rec[3], raw=rec[:0x10].hex(),
                                 x=round(fx24(rec, 0x30), 1),
                                 y=round(fx24(rec, 0x33), 1)))
            if not found:
                rows.append(dict(base, slot=-1, species=-1, flags=-1, raw="",
                                 x=0.0, y=0.0))
            if (g - args.start) % (args.step * 40) == 0:
                print(f"  frame {g}: {len(rows)} rows", flush=True)
        with open(args.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"measure_phalanx: {len(rows)} rows -> {args.out}")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


if __name__ == "__main__":
    sys.exit(main())
