#!/usr/bin/env python3
"""Replay a recorded input log and dump exact reference frames.

The recomp's recorder writes ``input_log.jsonl`` with ``frame``/``gframe``
fields, while ``replay_input`` expects ``frame``/``inputs``/``active``. This
tool performs that conversion, replays from boot, and saves the same state
bundle used by ``capture_anim.py``: OAM, CGRAM, PPU registers, VRAM, low WRAM
and a PNG of the presented frame.

Usage:
  python tools/oracle/replay_capture.py \
      --recording "M:/Opencode/DemonsCrestSNESRecomp/captures/rec_20261027_151150" \
      --out captures/ref --frames 1200,2200,7002
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
RECOMP = Path(r"M:\Opencode\DemonsCrestSNESRecomp")
def find_exe(root: Path) -> Path:
    """The trace build has moved between build-trace/ and build/; take what
    exists so the tool works on either checkout and on both platforms."""
    for rel in ("build-trace/DemonsCrestSNESRecomp.exe",
                "build-trace/DemonsCrestSNESRecomp",
                "build/DemonsCrestSNESRecomp.exe",
                "build/DemonsCrestSNESRecomp"):
        path = root / rel
        if path.is_file():
            return path
    return root / "build-trace" / "DemonsCrestSNESRecomp.exe"


EXE = find_exe(RECOMP)
ROM = Path(r"M:\Opencode\roms\Demon's Crest (USA).sfc")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recording", type=Path, required=True,
                    help="recording directory or input_log.jsonl")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--frames", required=True,
                    help="comma-separated guest frame numbers")
    ap.add_argument("--recomp", type=Path, default=RECOMP)
    ap.add_argument("--rom", type=Path, default=ROM)
    ap.add_argument("--port", type=int, default=0,
                    help="0 chooses a free local port")
    ap.add_argument("--png", action="store_true",
                    help="also convert the BMP screenshot to PNG")
    return ap.parse_args()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Client:
    def __init__(self, sock: socket.socket):
        self.f = sock.makefile("rwb")

    def cmd(self, text: str) -> dict:
        self.f.write((text + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise RuntimeError(f"debug server closed after: {text}")
        return json.loads(line)

    def frame(self) -> int:
        return int(self.cmd("frame")["frame"])


def connect(port: int, timeout: float = 90.0) -> Client:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=3)
            sock.settimeout(60)
            return Client(sock)
        except OSError:
            time.sleep(0.1)
    raise SystemExit("replay_capture: no debug server")


def make_replay(recording: Path, out: Path) -> Path:
    log = recording / "input_log.jsonl" if recording.is_dir() else recording
    if not log.is_file():
        raise SystemExit(f"replay_capture: missing {log}")
    samples = [json.loads(line) for line in log.read_text().splitlines()
               if line.strip()]
    if not samples:
        raise SystemExit(f"replay_capture: empty {log}")
    first = samples[0]
    offset = first.get("gframe", first["frame"]) - first["frame"]
    lines = [
        json.dumps({"frame": f, "inputs": 0, "active": 3},
                   separators=(",", ":"))
        for f in range(offset)
    ]
    for sample in samples:
        frame = sample.get("gframe", sample["frame"])
        lines.append(json.dumps({
            "frame": frame,
            "inputs": sample.get("inputs", 0),
            "active": sample.get("active", 3),
        }, separators=(",", ":")))
    path = out / "replay.jsonl"
    path.write_text("\n".join(lines) + "\n")
    print(f"replay_capture: {len(lines)} samples -> {path}")
    return path


def run_to(client: Client, target: int) -> None:
    client.cmd(f"run_to_frame {target}")
    deadline = time.monotonic() + 600
    while client.frame() < target:
        if time.monotonic() > deadline:
            raise SystemExit(f"replay_capture: timeout at frame {target}")
        time.sleep(0.02)
    time.sleep(0.08)


def main() -> int:
    args = parse_args()
    args.out = args.out.resolve()
    args.recomp = args.recomp.resolve()
    args.rom = args.rom.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    replay = make_replay(args.recording, args.out)
    port = args.port or free_port()
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "run.log", "wb")
    proc = subprocess.Popen([str(find_exe(args.recomp)),
                             str(args.rom), "--paused"],
                            cwd=str(args.recomp), env=env,
                            stdout=log, stderr=log)
    try:
        client = connect(port)
        client.cmd(f"replay_input {replay.as_posix()}")
        for raw in args.frames.split(","):
            target = int(raw.strip(), 0)
            run_to(client, target)
            bmp = args.out / f"ref_{target}.bmp"
            client.cmd(f"screenshot {bmp.as_posix()}")
            state = {
                "frame": target,
                "ppu": client.cmd("get_ppu_state"),
                "oam": client.cmd("dump_oam")["hex"].replace(" ", ""),
                "cgram": client.cmd("dump_cgram")["hex"].replace(" ", ""),
            }
            (args.out / f"ref_{target}.json").write_text(
                json.dumps(state))
            (args.out / f"ref_{target}.vram.bin").write_bytes(
                bytes.fromhex(client.cmd("dump_vram")["hex"]
                              .replace(" ", "")))
            (args.out / f"ref_{target}.wram.bin").write_bytes(
                bytes.fromhex(client.cmd("dump_ram 0 65536")["hex"]
                              .replace(" ", "")))
            if args.png:
                from PIL import Image
                with Image.open(bmp) as image:
                    image.save(args.out / f"ref_{target}.png")
            print(f"replay_capture: frame {target} -> {bmp.name}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        (args.out / "replay_tmp.jsonl").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
