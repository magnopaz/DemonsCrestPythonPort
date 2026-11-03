#!/usr/bin/env python3
"""Dump the live APU of a recomp save state as a standard .spc file.

The ROM's music is an SPC700 program plus BRR samples, so "extracting the
soundtrack" means capturing the APU, not reading sample data.  The recomp
already emulates the APU, and its debug server exposes `spc_dump` (64 KB ARAM +
128 DSP registers + SPC700 registers + synthesized $F0-$FF IO) — this tool just
drives that deterministically: resume a save paused, run a fixed number of
frames, snapshot the APU, and record enough provenance to reproduce the dump.

It also records the live DSP output for the same window (`audio_wav`), which is
the ground truth the offline render can be compared against, and the guest's
area byte ($008D) so a dump cannot be silently attributed to the wrong room.

Usage:
  python3 tools/audio/dump_spc.py \
      --save ../DemonsCrestSNESRecomp/build-trace/saves/somulo_player_control.sav \
      --out captures/audio/colosseum --run 300

Output: <out>/music.spc, meta.json, and (with --live-wav) live.wav.
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
AREA_PTR = 0x008D  # WRAM byte offset into $81:A291, area = value / 2


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

    def run_to(self, target, timeout=300.0):
        if self.frame() >= target:
            return self.frame()
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + timeout
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError(f"timeout waiting for frame {target}")
            time.sleep(0.005)
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
            sock = socket.create_connection(("127.0.0.1", port), timeout=3)
            return Client(sock)
        except OSError:
            time.sleep(0.1)
    raise SystemExit("dump_spc: no debug server appeared")


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
    ap.add_argument("--save", type=Path,
                    help="save state to resume (paused); omit with --boot")
    ap.add_argument("--boot", action="store_true",
                    help="cold-boot the game instead of resuming a save")
    ap.add_argument("--out", type=Path, required=True, help="output directory")
    ap.add_argument("--run", type=int, default=240,
                    help="frames to run after the resume before the snapshot")
    ap.add_argument("--port", type=int, default=4393)
    ap.add_argument("--live-wav", type=float, default=0.0,
                    help="also dump this many seconds of live DSP output")
    ap.add_argument("--after", type=float, default=0.0,
                    help="keep running this many seconds after the snapshot and"
                         " record the CPU->APU commands the game sends; a"
                         " replayed driver needs the traffic that follows the"
                         " snapshot, not the traffic before it")
    ap.add_argument("--name", default="music.spc")
    args = ap.parse_args()

    exe = args.recomp / "build-trace" / "DemonsCrestSNESRecomp"
    if not exe.is_file():
        raise SystemExit(f"dump_spc: missing trace build: {exe}")
    if not args.boot and (not args.save or not args.save.is_file()):
        raise SystemExit("dump_spc: pass --save <state> or --boot")

    args.out.mkdir(parents=True, exist_ok=True)
    # The host rewrites path arguments relative to the game directory, so the
    # one-shot resume state must live inside the recomp tree.
    resume = args.recomp / f"_dc_audio_resume_{args.port}.sav"
    if args.boot:
        resume = None
    else:
        shutil.copyfile(args.save, resume)
    spc_path = (args.out / args.name).resolve()

    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "capture.log", "wb")
    argv = [str(exe), str(args.rom), "--paused"]
    if resume is not None:
        argv += ["--resume-state", str(resume)]
    proc = subprocess.Popen(argv, cwd=str(args.recomp), env=env,
                            stdout=log, stderr=log)
    client = None
    try:
        client = connect(args.port)
        start = client.frame()
        client.run_to(start + args.run)
        frame = client.frame()
        area_byte = client.cmd(f"read_ram {AREA_PTR:x} 1")["hex"].split()[0]
        stats = client.cmd("audio_stats")
        dumped = client.cmd(f"spc_dump {spc_path}")
        apu = client.cmd("get_apu_state")

        if args.after > 0:
            client.run_to(client.frame() + int(args.after * 60))
            time.sleep(0.3)

        # CPU->APU port traffic since the process started. A .spc carries no CPU,
        # so the offline render can only stay on the driver's rails if the
        # game's command bytes are replayed at their live sample times.
        events = client.cmd("audio_events 0 8000 2")["events"]
        port_lines = []
        for ev in events:
            if ev["t"] in ("cpu_wr", "cpu_ap"):
                port_lines.append(
                    f'{int(ev["s"])} {int(ev["adr"], 16)} {int(ev["val"], 16)}')
        (args.out / "ports.txt").write_text("\n".join(port_lines) + "\n")
        port_streams = sum(1 for ev in events if ev["t"] == "cpu_wr")

        live = None
        if args.live_wav > 0:
            produced = int(dumped.get("produced", 0))
            count = int(args.live_wav * 32040)
            # The ring keeps the last 2^22 samples; start right where the .spc
            # was taken so the two can be compared over the same window.
            start_idx = max(0, produced - 4096)
            live_path = (args.out / "live.wav").resolve()
            res = client.cmd(f"audio_wav {live_path} {start_idx} {count}")
            live = {"path": "live.wav", "start_idx": res.get("start"),
                    "samples": res.get("count"),
                    "produced_at_dump": produced}

        meta = {
            "save": str(args.save) if args.save else "(cold boot)",
            "save_sha1": sha1(args.save) if args.save else "(cold boot)",
            "rom_sha1": sha1(args.rom),
            "start_frame": start,
            "frame": frame,
            "frames_run": frame - start,
            "area": int(area_byte, 16) // 2,
            "area_byte": area_byte,
            "spc": args.name,
            "spc_sha1": sha1(spc_path),
            "spc_bytes": spc_path.stat().st_size,
            "spc_pc": dumped.get("pc"),
            "produced_samples": dumped.get("produced"),
            "port_events": len(port_lines),
            "port_offset": dumped.get("produced"),
            "after_seconds": args.after,
            "cpu_port_streams": port_streams,
            "ports_file": "ports.txt",
            "audio_produced_cpu": stats.get("produced_cpu"),
            "apu": apu,
        }
        if live:
            meta["live"] = live
        (args.out / "meta.json").write_text(json.dumps(meta, indent=1))
        print(json.dumps({k: meta[k] for k in
                          ("area", "frame", "spc", "spc_sha1", "spc_bytes",
                           "spc_pc", "produced_samples")}, indent=1))
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
        if resume is not None:
            try:
                resume.unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    sys.exit(main())
