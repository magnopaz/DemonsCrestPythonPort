#!/usr/bin/env python3
"""Turn a captured track into a looping game asset, with the loop measured.

Pipeline per track (spec in tools/audio/music_tracks.json):

  1. capture   — tools/audio/capture_music.py records the oracle's DSP output
                 for that save state (music only: object slots are neutralised);
  2. loop      — build/wav_loop finds the period by envelope correlation and
                 cuts it, snapping the cut so the seam is continuous;
  3. verify    — the cut's seam jump is compared against the typical
                 adjacent-sample step of the loop (a click would be a spike),
                 and the asset's duration/peak/RMS are recorded;
  4. manifest  — assets/generated/audio/music_manifest.json carries the source
                 save hash, the period, the seam numbers and the asset hash, so
                 the port and the regression can assert what is playing without
                 an ear.

Usage:
  python3 tools/audio/make_music_asset.py                 # every track
  python3 tools/audio/make_music_asset.py --track music_boss
  python3 tools/audio/make_music_asset.py --use-capture    # skip the oracle run

`--use-capture` re-cuts existing captures/audio/<name>/live.wav, which is what a
repeat build does when nothing in the save changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECOMP = ROOT.parent / "DemonsCrestSNESRecomp"
SPEC = ROOT / "tools" / "audio" / "music_tracks.json"


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def build_track(name: str, spec: dict, capture: Path, outdir: Path, recomp: Path,
                use_capture: bool) -> dict:
    if use_capture:
        live = capture / "live.wav"
        if not live.is_file():
            raise FileNotFoundError(f"no capture for {name}: {live}")
    else:
        cmd = [sys.executable, str(ROOT / "tools" / "audio" / "capture_music.py"),
               "--recomp", str(recomp), "--save", str(recomp / spec["save"]),
               "--out", str(capture),
               "--seconds", str(spec.get("capture_seconds", 120)),
               "--settle-frames", str(spec.get("settle_frames", 120))]
        if not spec.get("neutralise_objects", True):
            cmd.append("--keep-objects")
        run(cmd)
        live = capture / "live.wav"

    lo, hi = spec.get("loop", [4, 60])
    asset = outdir / f"{name}.wav"
    wav_loop = ROOT / "build" / "wav_loop"
    if not wav_loop.is_file() and (ROOT / "build" / "wav_loop.exe").is_file():
        wav_loop = ROOT / "build" / "wav_loop.exe"
    if not wav_loop.is_file():
        run(["gcc", "-O2", "-std=c11", "-o", str(wav_loop),
             str(ROOT / "tools" / "audio" / "wav_loop.c"), "-lm"])
    # Paths go to the C tool with forward slashes: it echoes them back inside
    # its JSON summary, and a Windows backslash would make that invalid JSON.
    res = run([str(wav_loop), str(live).replace("\\", "/"),
               "--find-loop", f"{lo},{hi}",
               "--loop-start", str(spec.get("loop_start", 0)),
               "--snap-start", str(spec.get("snap", 0.5)),
               "--loop-out", str(asset).replace("\\", "/"), "--json"])
    info = json.loads(res.stdout.strip().splitlines()[-1])
    if not info.get("loop_written"):
        # No clean period in the search window: the caller decides whether that
        # is fatal.  `make_music_asset.py` skips the track and reports it.
        raise ValueError(f"no loop found in {lo}-{hi}s "
                         f"(best {info.get('candidates', [{}])[0]})")

    # A seamless cut has a seam step of the same order as ordinary adjacent
    # samples; a click is orders of magnitude larger.
    seam_ratio = info["seam_jump"] / info["avg_step"] if info["avg_step"] else 0
    if seam_ratio > 4.0:
        raise ValueError(
            f"seam jump {info['seam_jump']:.1f} is "
            f"{seam_ratio:.1f}x the typical step {info['avg_step']:.1f}; "
            "widen --snap-start or pick another loop_start")

    entry = {
        "name": name,
        "file": asset.name,
        "area": spec.get("area"),
        "note": spec.get("note", ""),
        "source": str(spec["save"]),
        "source_capture": str(capture.relative_to(ROOT)),
        "capture_sha1": sha1(live),
        "asset_sha1": sha1(asset),
        "asset_bytes": asset.stat().st_size,
        "rate": info["rate"],
        "frames": info["loop_frames"],
        "seconds": round(info["loop_frames"] / info["rate"], 6),
        "period_seconds": round(info["period_seconds"], 6),
        "loop_start_frame": info["loop_start"],
        "seam_jump": round(info["seam_jump"], 2),
        "typical_step": round(info["avg_step"], 2),
        "seam_ratio": round(seam_ratio, 3),
        "peak": info["peak_l"],
        "rms": round(info["rms_l"], 1),
        "candidates": info.get("candidates", []),
    }
    print(f"{name}: {entry['seconds']:.3f} s loop, seam {entry['seam_jump']:.1f}"
          f" vs step {entry['typical_step']:.1f} ({seam_ratio:.2f}x),"
          f" rms {entry['rms']:.0f}")
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", type=Path, default=SPEC)
    ap.add_argument("--track", action="append", default=None,
                    help="track name (repeatable); default: all")
    ap.add_argument("--recomp", type=Path,
                    default=Path(os.environ.get("RECOMP_DIR", DEFAULT_RECOMP)))
    ap.add_argument("--outdir", type=Path,
                    default=ROOT / "assets" / "generated" / "audio")
    ap.add_argument("--captures", type=Path, default=ROOT / "captures" / "audio")
    ap.add_argument("--use-capture", action="store_true")
    args = ap.parse_args()

    spec = json.loads(args.spec.read_text())
    tracks = spec["tracks"]
    if args.track:
        wanted = set(args.track)
        tracks = [t for t in tracks if t["name"] in wanted]
        missing = wanted - {t["name"] for t in tracks}
        if missing:
            raise SystemExit(f"make_music_asset: unknown track(s): {sorted(missing)}")

    args.outdir.mkdir(parents=True, exist_ok=True)
    entries = []
    failures = []
    for t in tracks:
        try:
            entries.append(build_track(t["name"], t, args.captures / t["name"],
                                       args.outdir, args.recomp, args.use_capture))
        except (FileNotFoundError, ValueError) as exc:
            failures.append(t["name"])
            print(f"{t['name']}: skipped: {exc}", file=sys.stderr)

    manifest_path = args.outdir / "music_manifest.json"
    manifest = {"tracks": entries}
    manifest_path.write_text(json.dumps(manifest, indent=1))
    print(f"make_music_asset: {len(entries)} track(s) -> {manifest_path}")
    if failures:
        print(f"make_music_asset: {len(failures)} track(s) without a loop: "
              f"{failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
