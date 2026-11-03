#!/usr/bin/env python3
"""Sample live WRAM from the trace build: a save state, or a replayed take.

Two modes, both writing the same CSV (`gframe,area8d,area,state,sub,x,y,species`):

  save <file.sav> [--frames N]
      Resume a save paused, run N frames, and dump the area byte ($008D), the
      player task ($1000..$1035) and the 26 object slots ($1080, stride $50).

  replay <take dir> [--step N] [--limit G]
      Replay an input-only take recorded with SNESREC_AUTORECORD=1 (the log must
      start at guest frame 1) and sample every N frames. Takes recorded
      mid-session do not replay: the log has no boot prefix.

Requires the trace build (`-DSNESRECOMP_ENABLE_TRACE=ON`, `build-trace/`) and
the debug server it opens. Use `--rom`, or set SNESRECOMP_ROM.

Usage:
  python3 tools/oracle/trace_stage.py save build/saves/arma_boss.sav
  python3 tools/oracle/trace_stage.py replay build-trace/captures/rec_x -o /tmp/t.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECOMP = Path(os.environ.get("RECOMP_DIR", ROOT.parent / "DemonsCrestSNESRecomp"))


def find_exe(root: Path) -> Path:
    for rel in ("build-trace/DemonsCrestSNESRecomp.exe",
                "build-trace/DemonsCrestSNESRecomp",
                "build/DemonsCrestSNESRecomp.exe",
                "build/DemonsCrestSNESRecomp"):
        if (root / rel).is_file():
            return root / rel
    return root / "build-trace" / "DemonsCrestSNESRecomp.exe"


def find_rom(explicit: str) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("SNESRECOMP_ROM")
    if env:
        return Path(env)
    for cand in (ROOT.parent / "roms" / "Demon's Crest (USA).sfc",
                 RECOMP / "rom" / "Demon's Crest (USA).sfc"):
        if cand.is_file():
            return cand
    raise SystemExit("trace_stage: pass --rom or set SNESRECOMP_ROM")


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

    def run_to(self, target):
        if target <= self.frame():
            return
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + 120
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError(f"timeout waiting for frame {target}")
            time.sleep(0.01)
        time.sleep(0.02)

    def read(self, addr, n):
        return bytes.fromhex(self.cmd(f"read_ram {addr:x} {n}")["hex"]
                             .replace(" ", ""))


def connect(port: int, timeout: float = 60.0) -> Client:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return Client(socket.create_connection(("127.0.0.1", port), timeout=1))
        except OSError:
            time.sleep(0.2)
    raise SystemExit("trace_stage: no debug server")


def launch(exe: Path, rom: Path, port: int, extra: list[str]) -> subprocess.Popen:
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    return subprocess.Popen([str(exe), str(rom), "--paused", *extra],
                            cwd=str(exe.parent.parent), env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def sample(c: Client, gframe: int) -> dict:
    area8d = c.read(0x008D, 1)[0]
    win = c.read(0x1000, 0x0D50)   # player task + object pool in one read
    x = (win[0x30] | win[0x31] << 8 | win[0x32] << 16) / 256.0
    y = (win[0x33] | win[0x34] << 8 | win[0x35] << 16) / 256.0
    pool = win[0x80:]
    species = [pool[i * 0x50 + 2] for i in range(26)
               if any(pool[i * 0x50:(i + 1) * 0x50])]
    return dict(gframe=gframe, area8d=area8d, area=area8d // 2,
                state=win[5], sub=win[6], x=round(x, 1), y=round(y, 1),
                species=";".join(str(s) for s in sorted(set(species))))


def write_csv(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"trace_stage: {len(rows)} rows -> {out}")


def mode_save(args) -> int:
    save = Path(args.target)
    if not save.is_file():
        raise SystemExit(f"trace_stage: no save at {save}")
    tmp = Path("/tmp") / f"trace_stage_{save.stem}.sav"
    shutil.copyfile(save, tmp)   # --resume-state consumes the file
    proc = launch(args.exe, args.rom, args.port, ["--resume-state", str(tmp)])
    try:
        c = connect(args.port)
        start = c.frame()
        c.run_to(start + args.frames)
        rows = [sample(c, start + args.frames)]
        write_csv(rows, Path(args.out))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


def mode_replay(args) -> int:
    take = Path(args.target)
    if take.is_file():
        take = take.parent
    log = take / "input_log.jsonl"
    if not log.is_file():
        # The recorder nests one `rec_<timestamp>/` dir inside RECORD_DIR.
        nested = sorted(p / "input_log.jsonl" for p in take.glob("rec_*")
                        if (p / "input_log.jsonl").is_file())
        if not nested:
            raise SystemExit(f"trace_stage: no input_log.jsonl under {take}")
        log = nested[-1]
    samples = []
    for line in log.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        samples.append({"frame": int(rec["frame"]),
                        "inputs": int(rec["inputs"]),
                        "active": 1})
    if samples and samples[0]["frame"] > 1:
        print("trace_stage: WARNING the log does not start at boot; replay "
              "will not line up (record with SNESREC_AUTORECORD=1)")
    replay = Path(args.out).with_suffix(".replay.jsonl")
    replay.parent.mkdir(parents=True, exist_ok=True)
    replay.write_text("\n".join(json.dumps(s) for s in samples) + "\n")

    proc = launch(args.exe, args.rom, args.port, [])
    try:
        c = connect(args.port)
        c.cmd(f"replay_input {replay.as_posix()}")
        last = args.limit or samples[-1]["frame"]
        rows = []
        for g in range(1, last + 1, args.step):
            c.run_to(g)
            rows.append(sample(c, g))
        write_csv(rows, Path(args.out))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("save", "replay"))
    ap.add_argument("target", help="save file or take directory")
    ap.add_argument("-o", "--out", default="/tmp/trace_stage.csv")
    ap.add_argument("--frames", type=int, default=90,
                    help="save mode: frames to run after resuming (default 90)")
    ap.add_argument("--step", type=int, default=20,
                    help="replay mode: sample every N frames (default 20)")
    ap.add_argument("--limit", type=int, default=0,
                    help="replay mode: stop at this guest frame")
    ap.add_argument("--port", type=int, default=4478)
    ap.add_argument("--rom", default="")
    ap.add_argument("--exe", type=Path, default=None)
    args = ap.parse_args()
    args.rom = find_rom(args.rom)
    args.exe = args.exe or find_exe(RECOMP)
    if not args.exe.is_file():
        raise SystemExit(f"trace_stage: no trace build at {args.exe}")
    return mode_save(args) if args.mode == "save" else mode_replay(args)


if __name__ == "__main__":
    sys.exit(main())
