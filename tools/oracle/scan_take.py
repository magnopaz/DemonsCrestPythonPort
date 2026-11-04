#!/usr/bin/env python3
"""Fast scan of a recorded take: loader area, player and camera per sample.

`trace_stage.py replay` reads the whole object pool on every sample, which is
what you want for object work but slow over a 25 000-frame take.  This tool
does two reads per sample, so a full take (~7 min of gameplay) scans in the
same wall time plus a few seconds, and prints every area change as it happens.

CSV columns:

    gframe,area8d,area,hp,state,sub,x,y,cam_x,cam_y

`area8d` is WRAM ``$008D``; `area` is ``area8d // 2``, the id the room loader
uses (see docs/TAKES.md).  `hp` is ``$0062`` — it is what tells a death (0) from
a knockback, and where a take respawns.  `state`/`sub` are the player task's
``$1005`` and ``$1006``; x/y are 24-bit fixed point.

Usage:
  python3 tools/oracle/scan_take.py <take> -o /tmp/take.csv --step 20
  python3 tools/oracle/scan_take.py <take> --step 5 --limit 5000

Pitfalls (all measured, all cost time):
  * ``read_ram <addr_hex> <len_decimal>`` — the length is decimal, not hex.
    ``read_ram 1000 40`` returns 40 bytes (0x28), not 0x40.
  * Reading WRAM before the first guest frame returns ``out of range, max 0x0``;
    run to frame 1 first.
  * ``replay_input`` parses each line with sscanf and does not accept spaces, so
    the replay file must be compact JSON — otherwise it silently loads 0
    samples.
  * If an older emulator still holds the debug port, the new one logs
    "Debug server failed to bind port" and the client talks to the stale
    process. Kill with -9 and use a distinct --port per run.
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

    def run_to(self, target: int, timeout: float = 300.0) -> None:
        if self.frame() >= target:
            return
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + timeout
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError(f"timeout waiting for frame {target}")
            time.sleep(0.002)

    def read(self, addr: int, n: int) -> bytes:
        # Length is decimal in the protocol; chunk to 0x100 so nothing truncates.
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
    raise SystemExit(f"scan_take: no debug server on port {port}")


def build_replay(take: Path, out: Path) -> list[dict]:
    log = take / "input_log.jsonl"
    if not log.is_file():
        raise SystemExit(f"scan_take: no input_log.jsonl under {take}")
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
    ap.add_argument("-o", "--out", type=Path, default=Path("/tmp/take_scan.csv"))
    ap.add_argument("--step", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--port", type=int, default=4519)
    ap.add_argument("--recomp", type=Path, default=RECOMP)
    ap.add_argument("--rom", type=Path, default=ROM)
    args = ap.parse_args()

    take = args.take if args.take.is_dir() else args.take.parent
    replay = args.out.with_suffix(".replay.jsonl")
    replay.parent.mkdir(parents=True, exist_ok=True)
    samples = build_replay(take, replay)
    last = args.limit or samples[-1].get("gframe", samples[-1]["frame"])

    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out.with_suffix(".log"), "wb")
    proc = subprocess.Popen([str(find_exe(args.recomp)), str(args.rom.resolve()), "--paused"],
                            cwd=str(args.recomp / "build-trace"), env=env,
                            stdout=log, stderr=log)
    try:
        c = connect(args.port)
        reply = c.cmd(f"replay_input {replay.as_posix()}")
        if not reply.get("samples"):
            raise SystemExit("scan_take: replay_input loaded 0 samples")
        c.run_to(1)   # WRAM does not exist before the first guest frame
        out = ["gframe,area8d,area,hp,state,sub,x,y,cam_x,cam_y"]
        prev = None
        for g in range(1, last + 1, args.step):
            c.run_to(g)
            head = c.read(0x0060, 0x100)   # HP at $0062, area at $008D, camera
            task = c.read(0x1000, 0x40)
            area8d = head[0x8D - 0x60]
            out.append(",".join(str(v) for v in (
                g, area8d, area8d // 2, head[0x62 - 0x60], task[5], task[6],
                round(fx24(task, 0x30), 1), round(fx24(task, 0x33), 1),
                int.from_bytes(head[0x8A - 0x60:0x8C - 0x60], "little"),
                head[0x8C - 0x60])))
            if area8d != prev:
                print(f"area {prev} -> {area8d} (area {area8d // 2}) at {g} "
                      f"({fx24(task, 0x30):.0f},{fx24(task, 0x33):.0f})", flush=True)
                prev = area8d
        args.out.write_text("\n".join(out) + "\n")
        print(f"scan_take: {len(out) - 1} samples -> {args.out}")
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
