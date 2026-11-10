#!/usr/bin/env python3
"""Replay a take and screenshot one frame every N guest frames.

Why this exists: `replay_capture.py` saves a full state bundle (VRAM + WRAM +
OAM + CGRAM) per frame, which is what sprite work needs but far too heavy for
"what does the screen look like between frame 20 000 and 40 000". The recomp's
own `SNESRECOMP_FRAME_BMP_DIR` dump does **not** fire for this title: Demon's
Crest installs its own `draw_frame`, so `RtlDrawPpuFrame` returns before
`RtlWidescreenPresent` (the only caller of the dump). The debug server's
`screenshot` command goes through the composed-frame path, so that is the one
that works.

Usage:
  python3 tools/oracle/replay_frames.py <take> --out /tmp/shots \
      --from 19500 --to 39900 --every 30

Notes:
  * `--every` is in guest frames; 30 = twice a second, enough for text pages.
  * BMPs are 256x224 32-bit; `--png` converts them with PIL.
  * The emulator is started paused and driven through the debug server; the
    usual replay pitfalls apply (compact JSON, a distinct port, `-9` a stale
    emulator) — see docs/TAKES.md §4.
"""

from __future__ import annotations

import argparse
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
                raise RuntimeError(f"timeout waiting for frame {target}")
            time.sleep(0.02)


def connect(port: int, timeout: float = 120.0) -> Client:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return Client(socket.create_connection(("127.0.0.1", port), timeout=3))
        except OSError:
            time.sleep(0.1)
    raise SystemExit(f"replay_frames: no debug server on port {port}")


def build_replay(take: Path, out: Path) -> Path:
    log = take / "input_log.jsonl" if take.is_dir() else take
    if not log.is_file():
        raise SystemExit(f"replay_frames: missing {log}")
    samples = [json.loads(line) for line in log.read_text().splitlines()
               if line.strip()]
    if not samples:
        raise SystemExit(f"replay_frames: empty {log}")
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("take", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--from", dest="start", type=int, required=True)
    ap.add_argument("--to", dest="end", type=int, required=True)
    ap.add_argument("--every", type=int, default=30)
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--port", type=int, default=4631)
    ap.add_argument("--recomp", type=Path, default=RECOMP)
    ap.add_argument("--rom", type=Path, default=ROM)
    args = ap.parse_args()

    take = args.take if args.take.is_dir() else args.take.parent
    args.out.mkdir(parents=True, exist_ok=True)
    for stale in args.out.glob("frame_*.bmp"):
        stale.unlink()
    replay = build_replay(take, args.out)

    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "run.log", "wb")
    proc = subprocess.Popen([str(find_exe(args.recomp)), str(args.rom.resolve()),
                             "--paused"],
                            cwd=str(args.recomp / "build-trace"), env=env,
                            stdout=log, stderr=log)
    written = 0
    try:
        c = connect(args.port)
        reply = c.cmd(f"replay_input {replay.as_posix()}")
        if not reply.get("samples"):
            raise SystemExit("replay_frames: replay_input loaded 0 samples")
        every = max(1, args.every)
        for g in range(args.start, args.end + 1, every):
            c.run_to(g)
            bmp = args.out / f"frame_{g:06d}.bmp"
            c.cmd(f"screenshot {bmp.as_posix()}")
            written += 1
            if args.png:
                from PIL import Image
                with Image.open(bmp) as image:
                    image.save(args.out / f"frame_{g:06d}.png")
            if written % 20 == 0:
                print(f"  {written} shots, at frame {g}", flush=True)
        print(f"replay_frames: {written} BMPs in {args.out}")
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
