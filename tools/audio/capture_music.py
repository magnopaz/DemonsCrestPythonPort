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
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle import DEFAULT_RECOMP, DEFAULT_ROM, NATIVE_RATE, Session  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OBJ_BASE, OBJ_STRIDE, OBJ_SLOTS = 0x1080, 0x50, 26


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
    ap.add_argument("--save", type=Path, default=None,
                    help="save state to resume; omit for a cold boot")
    ap.add_argument("--start-frame", type=int, default=0,
                    help="on a cold boot, frames to run before the capture "
                         "(the title screen starts its music around frame 360)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--settle-frames", type=int, default=120,
                    help="frames to run before the capture starts")
    ap.add_argument("--keep-objects", action="store_true",
                    help="do not neutralise object slots (captures SFX too)")
    ap.add_argument("--port", type=int, default=4402)
    args = ap.parse_args()

    if args.save is not None and not args.save.is_file():
        raise SystemExit(f"capture_music: missing save state: {args.save}")
    args.out.mkdir(parents=True, exist_ok=True)
    wav = (args.out / "live.wav").resolve()

    with Session(save=args.save, rom=args.rom, recomp=args.recomp,
                 port=args.port) as session:
        client = session.client
        if args.start_frame:
            client.run_to(args.start_frame)
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
            "save": str(args.save) if args.save else "(cold boot)",
            "save_sha1": sha1(args.save) if args.save else "",
            "rom_sha1": sha1(args.rom),
            "start_frame_requested": args.start_frame,
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


if __name__ == "__main__":
    sys.exit(main())
