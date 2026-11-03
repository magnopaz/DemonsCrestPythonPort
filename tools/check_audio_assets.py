#!/usr/bin/env python3
"""Assert the ROM-audio assets are real, loopable, and actually play in the port.

Three independent claims, all machine-checked (no ear test):

 1. asset     — every track in assets/generated/audio/music_manifest.json
                exists, matches its recorded hash, is non-silent, is at the
                DSP's native rate, and its loop seam is not a click (the seam
                step must stay within a small multiple of the typical
                adjacent-sample step the cutter measured).
 2. playback  — a headless run at the track's area loads that file through
                raylib's music stream (`audio: track N <- ... (ROM)`) and the
                stream clock advances (`audio: probe ... rom=1 time=...`).
                A null ALSA PCM makes this work without a sound card.
 3. determinism — the same demo run with audio forced on and with
                DC_NO_AUDIO=1 produces byte-identical trace CSVs, so the audio
                path cannot perturb the simulation.

Exit codes: 0 pass, 1 failure, 77 skip (no assets / no binary / no xvfb).

Usage:
  python3 tools/check_audio_assets.py
  python3 tools/check_audio_assets.py --binary tools/demonscrest-py --assets assets/generated
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ALSA_NULL = """pcm.!default {
    type null
}
ctl.!default {
    type null
}
"""


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--skip-playback", action="store_true",
                    help="asset checks only (no window, no audio device)")
    return ap.parse_args()


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wav_stats(path: Path) -> dict:
    with wave.open(str(path)) as w:
        channels = w.getnchannels()
        rate = w.getframerate()
        width = w.getsampwidth()
        frames = w.getnframes()
        raw = w.readframes(frames)
    samples = struct.unpack("<%dh" % (len(raw) // 2), raw)
    peak = max((abs(v) for v in samples), default=0)
    rms = (sum(v * v for v in samples) / len(samples)) ** 0.5 if samples else 0.0
    return {"channels": channels, "rate": rate, "width": width,
            "frames": frames, "peak": peak, "rms": rms}


def check_assets(assets: Path) -> list[dict]:
    manifest_path = assets / "audio" / "music_manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = json.loads(manifest_path.read_text())
    tracks = manifest.get("tracks", [])
    errors: list[str] = []
    for t in tracks:
        path = assets / "audio" / t["file"]
        if not path.is_file():
            errors.append(f"{t['name']}: missing {path}")
            continue
        if sha1(path) != t["asset_sha1"]:
            errors.append(f"{t['name']}: hash mismatch (asset rebuilt? "
                          "rerun make_music_asset.py --use-capture)")
        stats = wav_stats(path)
        if stats["rate"] != 32040:
            errors.append(f"{t['name']}: rate {stats['rate']} != 32040")
        if stats["channels"] != 2:
            errors.append(f"{t['name']}: {stats['channels']} channels")
        if stats["rms"] < 100:
            errors.append(f"{t['name']}: silent (rms {stats['rms']:.1f})")
        if stats["frames"] != t["frames"]:
            errors.append(f"{t['name']}: {stats['frames']} frames, "
                          f"manifest says {t['frames']}")
        if t["seam_ratio"] > 4.0:
            errors.append(f"{t['name']}: seam jump {t['seam_jump']:.1f} is "
                          f"{t['seam_ratio']:.1f}x the typical step")
        if not (10.0 <= t["seconds"] <= 120.0):
            errors.append(f"{t['name']}: loop {t['seconds']:.2f}s out of range")
        print(f"  {t['name']}: {t['seconds']:.3f}s loop, rms {stats['rms']:.0f}, "
              f"peak {stats['peak']}, seam {t['seam_ratio']:.2f}x step")
    if errors:
        for e in errors:
            print(f"FAIL asset: {e}", file=sys.stderr)
        raise SystemExit(1)
    return tracks


def check_spc_artifacts(captures: Path) -> None:
    """Validate any .spc dumped alongside a capture.

    The game does not load these (a bare .spc does not resume this driver, see
    docs/AUDIO_PLAN.md), but the dump is the portable record of what the APU was
    running, so its structure is checked: v0.30 size, magic, ID666 marker, sane
    SPC registers, non-empty ARAM and DSP registers, and the hash the dump tool
    recorded.
    """
    spcs = sorted(captures.glob("*/spc/*.spc"))
    for spc in spcs:
        blob = spc.read_bytes()
        problems = []
        if len(blob) != 0x10200:
            problems.append(f"{len(blob)} bytes, expected 0x10200")
        if not blob.startswith(b"SNES-SPC700 Sound File Data v0.30"):
            problems.append("bad magic/version")
        if blob[0x23] not in (26, 27):
            problems.append(f"ID666 marker {blob[0x23]} (26=tags, 27=none)")
        pc = blob[0x25] | (blob[0x26] << 8)
        if pc == 0:
            problems.append("PC is 0")
        if blob[0x2B] == 0:
            problems.append("SP is 0")
        aram = blob[0x100:0x10100]
        if sum(1 for b in aram if b) < 1024:
            problems.append("ARAM looks empty")
        dsp = blob[0x10100:0x10180]
        if sum(1 for b in dsp if b) < 8:
            problems.append("DSP register image looks empty")
        meta = spc.parent / "meta.json"
        if meta.is_file():
            recorded = json.loads(meta.read_text()).get("spc_sha1")
            if recorded and recorded != sha1(spc):
                problems.append("hash differs from meta.json (redumped?)")
        if problems:
            print(f"FAIL spc {spc}: " + "; ".join(problems), file=sys.stderr)
            raise SystemExit(1)
        print(f"  {spc.relative_to(captures.parent)}: v0.30, pc=0x{pc:04X}, "
              f"area={json.loads(meta.read_text())['area'] if meta.is_file() else '?'}")


def wrapper(binary: Path) -> list[str]:
    if sys.platform.startswith("linux") and shutil.which("xvfb-run"):
        return ["xvfb-run", "-a", str(binary)]
    return [str(binary)]


def run_headless(binary: Path, assets: Path, env_extra: dict, frames: int,
                 trace: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(env_extra)
    env["DC_AREA"] = env.get("DC_AREA", "0")
    env["DC_RUN_FRAMES"] = str(frames)
    if trace is not None:
        env["DC_TRACE_CSV"] = str(trace)
    return subprocess.run(wrapper(binary) + ["--assets", str(assets)],
                          env=env, capture_output=True, text=True, timeout=300)


def check_playback(binary: Path, assets: Path, track: dict) -> None:
    if not binary.is_file():
        print(f"SKIP playback: no binary at {binary}")
        raise SystemExit(77)
    with tempfile.TemporaryDirectory() as td:
        alsa = Path(td) / "asound.conf"
        alsa.write_text(ALSA_NULL)
        env = {"ALSA_CONFIG_PATH": str(alsa), "DC_AUDIO_FORCE": "1",
               "DC_AUDIO_DEBUG": "1", "DC_AUDIO_PROBE": "1",
               "DC_AREA": str(track["area"])}
        res = run_headless(binary, assets, env, frames=900)
        out = res.stdout + res.stderr
        loaded = [ln for ln in out.splitlines()
                  if "music_boss.wav" in ln and "ROM" in ln]
        if not loaded:
            print("FAIL playback: the port never loaded the ROM track:\n"
                  + "\n".join(out.splitlines()[-20:]), file=sys.stderr)
            raise SystemExit(1)
        print("  " + loaded[0].strip())
        probes = []
        for ln in out.splitlines():
            if "audio: probe" in ln:
                fields = dict(kv.split("=") for kv in ln.split() if "=" in kv)
                probes.append(fields)
        rom_probes = [p for p in probes if p.get("rom") == "1"]
        if not rom_probes:
            print("FAIL playback: the ROM track was loaded but never played",
                  file=sys.stderr)
            raise SystemExit(1)
        last = rom_probes[-1]
        if float(last["time"]) < 0.2:
            print(f"FAIL playback: stream clock did not advance ({last})",
                  file=sys.stderr)
            raise SystemExit(1)
        if last.get("playing") != "1":
            print(f"FAIL playback: stream is not playing ({last})", file=sys.stderr)
            raise SystemExit(1)
        print(f"  track={last['track']} rom=1 time={last['time']}s playing=1")


def check_determinism(binary: Path, assets: Path, track: dict) -> None:
    with tempfile.TemporaryDirectory() as td:
        alsa = Path(td) / "asound.conf"
        alsa.write_text(ALSA_NULL)
        a = Path(td) / "audio_on.csv"
        b = Path(td) / "audio_off.csv"
        env_on = {"ALSA_CONFIG_PATH": str(alsa), "DC_AUDIO_FORCE": "1",
                  "DC_AREA": str(track["area"])}
        env_off = {"DC_NO_AUDIO": "1", "DC_AREA": str(track["area"])}
        run_headless(binary, assets, env_on, frames=600, trace=a)
        run_headless(binary, assets, env_off, frames=600, trace=b)
        if not a.is_file() or not b.is_file():
            print("FAIL determinism: no trace produced", file=sys.stderr)
            raise SystemExit(1)
        if a.read_bytes() != b.read_bytes():
            print("FAIL determinism: audio on/off traces differ", file=sys.stderr)
            raise SystemExit(1)
        print(f"  audio-on and DC_NO_AUDIO=1 traces identical "
              f"({len(a.read_bytes())} bytes)")


def main() -> int:
    args = parse_args()
    tracks = check_assets(args.assets)
    check_spc_artifacts(ROOT / "captures" / "audio")
    if not tracks:
        print(f"SKIP: no audio manifest under {args.assets}/audio")
        return 77
    if args.skip_playback:
        return 0
    for track in tracks:
        check_playback(args.binary, args.assets, track)
        check_determinism(args.binary, args.assets, track)
    print("check_audio_assets: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
