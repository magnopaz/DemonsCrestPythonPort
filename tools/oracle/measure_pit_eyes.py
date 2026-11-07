#!/usr/bin/env python3
"""Replay a take and dump the pit's boss slots ($69/$6B/$6C) frame by frame.

The general-purpose `trace_stage.py replay --objects` keeps only the species and
x/y of each slot, which is enough to see a room but not to port the pit of
Ovununu's eyes: `$6C` is eleven records that differ only by their flag byte
(`$00`, 0..10) and their state/substate, and the eyes' volley is driven by those
two bytes.  This tool reads the whole slot for slots 8..25 and prints the fields
the AI actually uses:

    $00 flags/active   $02 species   $05 state   $06 substate
    $30..$32 x (8.8 fx)   $33..$35 y (8.8 fx)

Usage:
  python3 tools/oracle/measure_pit_eyes.py <take dir> -o /tmp/pit.csv \\
      --from 14100 --to 25061 --step 20

The take is input-only; replay reproduces every frame, so a narrow window costs
only the frames before it.  Defaults target the pit of Ovununu window of
`docs/TAKES.md` §6.1.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECOMP = Path(os.environ.get("RECOMP_DIR", ROOT.parent / "DemonsCrestSNESRecomp"))
ROM = Path(os.environ.get("ROM", ROOT.parent / "roms" / "Demon's Crest (USA).sfc"))

PIT_SPECIES = {0x69, 0x6B, 0x6C}
FIRST_SLOT = 8
SLOT_COUNT = 18          # slots 8..25
STRIDE = 0x50
BASE = 0x1080


def find_exe(root: Path) -> Path:
    for rel in ("build-trace/DemonsCrestSNESRecomp.exe",
                "build-trace/DemonsCrestSNESRecomp",
                "build/DemonsCrestSNESRecomp.exe",
                "build/DemonsCrestSNESRecomp"):
        if (root / rel).is_file():
            return root / rel
    return root / "build-trace" / "DemonsCrestSNESRecomp.exe"


def fx24(buf: bytes, off: int) -> float:
    return (buf[off] | buf[off + 1] << 8 | buf[off + 2] << 16) / 256.0


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

    def run_to(self, target: int, timeout: float = 600.0) -> None:
        if self.frame() >= target:
            return
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + timeout
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError(f"timeout waiting for frame {target}")
            time.sleep(0.002)

    def read(self, addr: int, n: int) -> bytes:
        out = b""
        for a in range(addr, addr + n, 0x100):
            out += bytes.fromhex(
                self.cmd(f"read_ram {a:x} {min(0x100, addr + n - a)}")["hex"]
                .replace(" ", ""))
        return out[:n]


def connect(port: int, timeout: float = 90.0) -> Client:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return Client(socket.create_connection(("127.0.0.1", port), timeout=3))
        except OSError:
            time.sleep(0.1)
    raise SystemExit(f"measure_pit_eyes: no debug server on port {port}")


def build_replay(take: Path, out: Path) -> list[dict]:
    log = take / "input_log.jsonl"
    if not log.is_file():
        raise SystemExit(f"measure_pit_eyes: no input_log.jsonl under {take}")
    samples = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    rows = [json.dumps({"frame": s.get("gframe", s["frame"]),
                        "inputs": s.get("inputs", 0), "active": 3},
                       separators=(",", ":")) for s in samples]
    out.write_text("\n".join(rows) + "\n")
    return samples


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("take", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("/tmp/pit_eyes.csv"))
    ap.add_argument("--from", dest="start", type=int, default=14100)
    ap.add_argument("--to", dest="stop", type=int, default=0)
    ap.add_argument("--step", type=int, default=20)
    ap.add_argument("--port", type=int, default=4523)
    ap.add_argument("--extra", type=Path, default=None,
                    help="also dump the fight's globals and per-slot parameter "
                         "tables to this CSV ($1DD0..$1E08, $E2C0..$E300, "
                         "$E380..$E3E0)")
    ap.add_argument("--headers", action="store_true",
                    help="read only each slot's first 12 bytes ($00/$02/$05/$06/"
                         "$30..$35); much lighter for step-1 windows")
    ap.add_argument("--recomp", type=Path, default=RECOMP)
    ap.add_argument("--rom", type=Path, default=ROM)
    args = ap.parse_args()

    take = args.take if args.take.is_dir() else args.take.parent
    replay = args.out.with_suffix(".replay.jsonl")
    replay.parent.mkdir(parents=True, exist_ok=True)
    samples = build_replay(take, replay)
    last = args.stop or samples[-1].get("gframe", samples[-1]["frame"])

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
            raise SystemExit("measure_pit_eyes: replay_input loaded 0 samples")
        c.run_to(1)

        # Slots 8..25 in one contiguous read: no per-slot round trip.
        start_addr = BASE + FIRST_SLOT * STRIDE
        n_bytes = SLOT_COUNT * STRIDE
        out = ["gframe,px,py,area8d,slot,flags,species,state,sub,x,y,raw"]
        extra = None
        if args.extra:
            extra = ["gframe,rng,globals,e2,e3"]
        for g in range(1, last + 1, args.step):
            if g < args.start:
                continue
            c.run_to(g)
            area8d = c.read(0x008D, 1)[0]
            player = c.read(0x1030, 0x06)
            px = (player[0] | player[1] << 8 | player[2] << 16) / 256.0
            py = (player[3] | player[4] << 8 | player[5] << 16) / 256.0
            if args.headers:
                recs = []
                for i in range(SLOT_COUNT):
                    base = start_addr + i * STRIDE
                    head = c.read(base, 7)
                    rec = bytearray(STRIDE)
                    rec[:7] = head
                    if head[2] in PIT_SPECIES:
                        rec[0x30:0x36] = c.read(base + 0x30, 6)
                    recs.append(bytes(rec))
            else:
                pool = c.read(start_addr, n_bytes)
                recs = [pool[i * STRIDE:(i + 1) * STRIDE]
                        for i in range(SLOT_COUNT)]
            if args.extra:
                # $1DD0..$1E08: the fight's shared globals (phases, flags,
                # scroll and the eye/body anchor); $E2C0..$E300 and
                # $E380..$E3E0: the per-slot parameter tables the handlers
                # index with $03 ($E2D5 -> ...) and $1DED/$1DEE.
                blobs = (c.read(0x009C, 0x02), c.read(0x1DD0, 0x38),
                         c.read(0xE2C0, 0x40), c.read(0xE380, 0x60))
                extra.append(",".join([str(g)] + [b.hex() for b in blobs]))
            for i in range(SLOT_COUNT):
                rec = recs[i]
                if not rec[0] and not rec[2]:
                    continue
                if rec[2] not in PIT_SPECIES:
                    continue
                out.append(",".join(str(v) for v in (
                    g, round(px, 2), round(py, 2), area8d, FIRST_SLOT + i,
                    rec[0], rec[2], rec[5], rec[6],
                    round(fx24(rec, 0x30), 2), round(fx24(rec, 0x33), 2)))
                    + "," + rec.hex())
        args.out.write_text("\n".join(out) + "\n")
        print(f"measure_pit_eyes: {len(out) - 1} rows -> {args.out}")
        if extra is not None:
            args.extra.write_text("\n".join(extra) + "\n")
            print(f"measure_pit_eyes: {len(extra) - 1} global samples -> {args.extra}")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
