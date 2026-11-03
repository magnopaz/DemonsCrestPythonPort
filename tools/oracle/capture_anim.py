#!/usr/bin/env python3
"""Capture per-frame player animation states from the recomp debug server.

The recompilation build keeps a ring of per-frame PPU/WRAM snapshots. This
tool drives that build through its TCP debug server, holds controller buttons
for known frame ranges, and then saves the snapshots the extractor needs.

It is deliberately deterministic: the tool starts the recomp paused, loads a
normal-gameplay save state, moves the guest to an absolute frame, and queries
the ring afterwards. No wall-clock timing or live screenshots are involved.

Example (from the native-port repository root):

  python3 tools/oracle/capture_anim.py \
    --recomp ../DemonsCrestSNESRecomp \
    --rom "../roms/Demon's Crest (USA).sfc" \
    --save ../DemonsCrestSNESRecomp/saves/save0.sav \
    --out captures/anim

The save state is copied first because --resume-state consumes the file.
Output is ROM-derived and git-ignored.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

# (name, buttons, frames). The sequence is chosen for save0 (normal graveyard
# gameplay): enough room to walk left and right, then jump from the starting
# ledge. Button names use the debug server spelling shown by set_controller.
DEFAULT_SEGMENTS = [
    ("idle", "", 30),
    ("walk_left", "left", 120),
    ("stop_left", "", 20),
    ("walk_right", "right", 120),
    ("stop_right", "", 20),
    ("jump_tap", "b", 1),
    ("tap_air", "", 25),
    ("idle_2", "", 15),
    ("jump_hold", "b", 45),
    ("hover_release", "", 40),
    ("idle_3", "", 15),
    ("attack", "a", 30),
    ("settle", "", 15),
    ("shoot", "y", 35),
    ("settle2", "", 15),
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    default_recomp = os.environ.get(
        "RECOMP_DIR",
        str(Path(__file__).resolve().parents[2] / "DemonsCrestSNESRecomp"))
    ap.add_argument("--recomp", default=default_recomp,
                    help="recompilation project root (default: sibling checkout)")
    ap.add_argument("--rom", default=os.environ.get("ROM", ""),
                    help="Demon's Crest (USA) ROM path")
    ap.add_argument("--save", default="",
                    help="save state to resume (default: <recomp>/saves/save0.sav)")
    ap.add_argument("--out", default="captures/anim",
                    help="output directory (default: captures/anim)")
    ap.add_argument("--port", type=int, default=4392,
                    help="debug server TCP port (default: 4392)")
    ap.add_argument("--segments", type=Path,
                    help="JSON file with [[name, buttons, frames], ...]")
    ap.add_argument("--timeout", type=float, default=120.0,
                    help="seconds to wait for the debug server (default: 120)")
    return ap.parse_args()


def load_segments(path: Path | None) -> list[tuple[str, str, int]]:
    if path is None:
        return DEFAULT_SEGMENTS
    raw = json.loads(path.read_text())
    out = []
    for item in raw:
        if len(item) != 3:
            raise SystemExit(f"{path}: each segment needs name, buttons, frames")
        out.append((str(item[0]), str(item[1]), int(item[2])))
    return out


class DebugClient:
    def __init__(self, sock: socket.socket):
        self._file = sock.makefile("rwb")

    def cmd(self, text: str) -> dict:
        self._file.write((text + "\n").encode())
        self._file.flush()
        line = self._file.readline()
        if not line:
            raise RuntimeError("debug server closed the connection")
        result = json.loads(line)
        if "error" in result:
            raise RuntimeError(f"{text}: {result['error']}")
        return result

    def frame(self) -> int:
        return int(self.cmd("frame")["frame"])

    def run_to(self, target: int) -> int:
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + 120.0
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError(f"timeout waiting for frame {target}")
            time.sleep(0.005)
        time.sleep(0.03)
        return self.frame()

    def close(self) -> None:
        try:
            self._file.close()
        except Exception:
            pass


def connect(port: int, timeout: float) -> socket.socket:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=2)
        except OSError:
            time.sleep(0.1)
    raise SystemExit(f"capture: no debug server on port {port}")


def main() -> int:
    args = parse_args()
    recomp = Path(args.recomp).resolve()
    binary = recomp / "build-trace" / "DemonsCrestSNESRecomp"
    if not binary.is_file():
        raise SystemExit(
            f"capture: missing trace build: {binary}\n"
            "  cmake -S . -B build-trace -DSNESRECOMP_ENABLE_TRACE=ON ...")
    if not args.rom:
        raise SystemExit("capture: pass --rom or set ROM")
    rom = Path(args.rom).resolve()
    if not rom.is_file():
        raise SystemExit(f"capture: missing ROM: {rom}")
    save = Path(args.save).resolve() if args.save else None
    if save is None:
        candidates = [
            recomp / "saves" / "save0.sav",
            recomp / "build-trace" / "saves" / "save0.sav",
            recomp.parent / "saves" / "save0.sav",
        ]
        save = next((p for p in candidates if p.is_file()), candidates[0])
    if not save.is_file():
        raise SystemExit(f"capture: missing save state: {save}")
    segments = load_segments(args.segments)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("f*.json"):
        old.unlink()
    for old in out.glob("f*.vram.bin"):
        old.unlink()
    (out / "segments.json").unlink(missing_ok=True)

    temp_save = out / "resume.sav"
    shutil.copyfile(save, temp_save)

    env = dict(os.environ,
               SDL_VIDEODRIVER="dummy",
               SDL_AUDIODRIVER="dummy",
               SNESRECOMP_DEBUG_PORT=str(args.port))
    log_path = out / "capture.log"
    log = open(log_path, "wb")
    proc = subprocess.Popen([str(binary), str(rom), "--paused",
                             "--resume-state", str(temp_save)],
                            cwd=recomp, env=env, stdout=log, stderr=log)
    client = None
    try:
        sock = connect(args.port, args.timeout)
        client = DebugClient(sock)
        start = client.frame()
        print(f"capture: start frame {start}, debug port {args.port}")

        captured = []
        current = start
        for name, buttons, frames in segments:
            client.cmd(f"set_controller {buttons if buttons else '0'}")
            end = client.run_to(current + frames)
            captured.append({"name": name, "buttons": buttons,
                             "start": current, "end": end})
            print(f"capture: {name:14s} {current} -> {end}")
            current = end
        client.cmd("set_controller 0")

        meta = {"start": start, "end": current, "segments": captured,
                "save": str(save), "rom": str(rom)}
        (out / "segments.json").write_text(json.dumps(meta, indent=1))

        # The ring records a frame when it completes. The newest frame in the
        # counter may not be present yet, so tolerate a missing tail.
        saved = 0
        for n in range(start + 1, current + 1):
            try:
                state = client.cmd(f"get_frame_extended {n}")
                vram = client.cmd(f"dump_frame_vram {n}")
            except RuntimeError as exc:
                print(f"capture: skip frame {n}: {exc}")
                continue
            (out / f"f{n:06d}.json").write_text(json.dumps(state))
            (out / f"f{n:06d}.vram.bin").write_bytes(
                bytes.fromhex(vram["hex"]))
            saved += 1
        client.close()
        client = None
        print(f"capture: wrote {saved} frames to {out}")
        return 0
    finally:
        if client is not None:
            client.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        temp_save.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
