#!/usr/bin/env python3
"""Capture one of the game's tracks from the oracle's own DSP output.

Why this and not the .spc
-------------------------
The music is an SPC700 program plus BRR samples, so the honest source is the
console's APU.  `dump_spc.py` produces the standard `.spc` snapshot of that APU,
but a bare `.spc` resumed offline does not survive this game's driver: it keeps
running for a couple of seconds and then executes data (verified by tracing the
SPC's PC stream).  The recomp, with the CPU driving the APU exactly as the
console did, plays the track indefinitely.  Its debug server therefore exposes
the DSP's native output ring (`audio_wav`), and that ring is what this tool
records — the same samples the emulated console produced, not a re-synthesis.

Getting music only
------------------
Area 0's save is mid-boss-fight, so a naive capture is full of roars and hits.
The port's own object pool documents the layout ($1080, stride $50, 26 slots):
zeroing the active byte of every slot removes the enemies that trigger those
sounds while leaving the game's sound engine and the music alone.  The capture
is quiet then, which is what a loop needs.

Usage:
  python3 tools/audio/capture_music.py \
      --save ../DemonsCrestSNESRecomp/build-trace/saves/somulo_player_control.sav \
      --out captures/audio/music_boss --seconds 120

Writes <out>/live.wav (32 kHz stereo, the DSP's native rate) and meta.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECOMP = ROOT.parent / "DemonsCrestSNESRecomp"
DEFAULT_ROM = ROOT.parent / "roms" / "Demon's Crest (USA).sfc"
NATIVE_RATE = 32040
OBJ_BASE, OBJ_STRIDE, OBJ_SLOTS = 0x1080, 0x50, 26


class Client:
    def __init__(self, sock):
        self.f = sock.makefile("rwb")
        self.sock = sock

    def cmd(self, text):
        self.f.write((text + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise RuntimeError(f"no response to {text!r}")
        msg = json.loads(line)
        if "error" in msg:
            raise RuntimeError(f"{text!r}: {msg['error']}")
        return msg

    def frame(self):
        return int(self.cmd("frame")["frame"])

    def read(self, addr, n):
        return bytes.fromhex(self.cmd(f"read_ram {addr:x} {n}")["hex"].replace(" ", ""))

    def write(self, addr, data):
        self.cmd(f"write_ram {addr:x} {data.hex()}")

    def run_to(self, target, timeout=600.0):
        if self.frame() >= target:
            return self.frame()
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + timeout
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError(f"timeout waiting for frame {target}")
            time.sleep(0.01)
        return self.frame()

    def close(self):
        try:
            self.f.close()
        finally:
            self.sock.close()


def connect(port, timeout=90.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return Client(socket.create_connection(("127.0.0.1", port), timeout=3))
        except OSError:
            time.sleep(0.1)
    raise SystemExit("capture_music: no debug server appeared")


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path,
                    default=Path(os.environ.get("RECOMP_DIR", DEFAULT_RECOMP)))
    ap.add_argument("--rom", type=Path,
                    default=Path(os.environ.get("ROM", DEFAULT_ROM)))
    ap.add_argument("--save", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--settle-frames", type=int, default=120,
                    help="frames to run before the capture starts")
    ap.add_argument("--keep-objects", action="store_true",
                    help="do not neutralise object slots (captures SFX too)")
    ap.add_argument("--port", type=int, default=4402)
    args = ap.parse_args()

    exe = args.recomp / "build-trace" / "DemonsCrestSNESRecomp"
    if not exe.is_file():
        # Windows builds carry the .exe suffix; pick whichever exists.
        for rel in ("build-trace", "build"):
            for name in ("DemonsCrestSNESRecomp.exe", "DemonsCrestSNESRecomp"):
                cand = args.recomp / rel / name
                if cand.is_file():
                    exe = cand
                    break
            if exe.is_file():
                break
    if not exe.is_file():
        raise SystemExit(f"capture_music: missing trace build: {exe}")
    if not args.save.is_file():
        raise SystemExit(f"capture_music: missing save state: {args.save}")

    args.out.mkdir(parents=True, exist_ok=True)
    # Path arguments are rewritten relative to the game directory, so the
    # one-shot resume state has to live inside the recomp tree.
    resume = args.recomp / f"_dc_music_resume_{args.port}.sav"
    shutil.copyfile(args.save, resume)
    wav = (args.out / "live.wav").resolve()

    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "capture.log", "wb")
    proc = subprocess.Popen([str(exe), str(args.rom), "--paused",
                             "--resume-state", str(resume)],
                            cwd=str(args.recomp), env=env,
                            stdout=log, stderr=log)
    client = None
    try:
        client = connect(args.port)
        start = client.frame()
        client.run_to(start + args.settle_frames)
        area_byte = client.read(0x008D, 1)[0]

        active = []
        if not args.keep_objects:
            pool = client.read(OBJ_BASE, OBJ_STRIDE * OBJ_SLOTS)
            for k in range(OBJ_SLOTS):
                if pool[k * OBJ_STRIDE]:
                    active.append([k, pool[k * OBJ_STRIDE]])
                    client.write(OBJ_BASE + k * OBJ_STRIDE, b"\x00")
            client.run_to(client.frame() + 2)

        frames = int(args.seconds * 60)
        client.run_to(client.frame() + frames)
        time.sleep(0.4)  # let the ring catch up with the last simulated frames
        stats = client.cmd("audio_stats")
        produced = int(stats["produced"])
        count = int(args.seconds * NATIVE_RATE)
        begin = max(0, produced - count)
        # The server echoes the path back inside a JSON string, so a Windows
        # path's backslashes would break the reply: send forward slashes.
        res = client.cmd(f"audio_wav {wav.as_posix()} {begin} {count}")
        end_frame = client.frame()

        meta = {
            "save": str(args.save),
            "save_sha1": sha1(args.save),
            "rom_sha1": sha1(args.rom),
            # $008D is the room area id the port loads (room_area<N>.json);
            # the world map stores its own marker ($BC = 188) for area 94.
            "area": area_byte,
            "area_byte": area_byte,
            "start_frame": start,
            "end_frame": end_frame,
            "frames_captured": frames,
            "neutralised_objects": not args.keep_objects,
            "objects_removed": active,
            "wav": "live.wav",
            "wav_sha1": sha1(wav),
            "wav_start": res.get("start"),
            "wav_frames": res.get("count"),
            "rate": NATIVE_RATE,
            "produced_total": produced,
            "audio_stats": {k: stats.get(k) for k in
                            ("produced", "dropped", "dropped_audible",
                             "cpu_port_writes", "kon_writes")},
        }
        (args.out / "meta.json").write_text(json.dumps(meta, indent=1))
        print(json.dumps({k: meta[k] for k in
                          ("area", "start_frame", "end_frame", "wav_frames",
                           "wav_sha1", "objects_removed")}, indent=1))
        return 0
    finally:
        if client is not None:
            client.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        try:
            resume.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    sys.exit(main())
