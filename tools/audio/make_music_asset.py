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
               "--recomp", str(recomp), "--out", str(capture),
               "--seconds", str(spec.get("capture_seconds", 120)),
               "--settle-frames", str(spec.get("settle_frames", 120))]
        if spec.get("cold_boot"):
            cmd += ["--start-frame", str(spec.get("start_frame", 900))]
        else:
            cmd += ["--save", str(recomp / spec["save"])]
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
    loop_start = spec.get("loop_start", 0)
    snap = spec.get("snap", 0.5)

    def cut_at(period_lo: float, period_hi: float, out: Path) -> dict:
        # Paths go to the C tool with forward slashes: it echoes them back
        # inside its JSON summary, and a Windows backslash would break it.
        res = run([str(wav_loop), str(live).replace("\\", "/"),
                   "--find-loop", f"{period_lo},{period_hi}",
                   "--loop-start", str(loop_start),
                   "--snap-start", str(snap),
                   "--loop-out", str(out).replace("\\", "/"), "--json"])
        return json.loads(res.stdout.strip().splitlines()[-1])

    info = cut_at(lo, hi, asset)
    if not info.get("loop_written"):
        # No clean period in the search window: the caller decides whether that
        # is fatal.  `make_music_asset.py` skips the track and reports it.
        raise ValueError(f"no loop found in {lo}-{hi}s "
                         f"(best {info.get('candidates', [{}])[0]})")

    # A short period is often one bar, and the piece repeats every two or four.
    # Looping a bar is valid but musically wrong, so try the multiples of the
    # measured period and keep the longest that still correlates nearly as well.
    # The probes write to a scratch file: only the accepted period may own the
    # real asset, or the last probe (which may have found nothing) wins.
    base_corr = (info.get("candidates") or [{"corr": 0}])[0].get("corr", 0)
    period = info["period_seconds"]
    capture_seconds = info["seconds"]
    chosen_range = (lo, hi)
    scratch = outdir / f".{name}.probe.wav"
    for k in (2, 3, 4):
        target = period * k
        if target + loop_start + 2.0 >= capture_seconds or target > hi * 2:
            break
        wider = cut_at(target - 0.4, target + 0.4, scratch)
        if not wider.get("loop_written"):
            continue
        corr = (wider.get("candidates") or [{"corr": 0}])[0].get("corr", 0)
        if corr >= base_corr * 0.85:
            chosen_range = (target - 0.4, target + 0.4)
    if chosen_range != (lo, hi):
        info = cut_at(chosen_range[0], chosen_range[1], asset)
        if not info.get("loop_written"):
            raise ValueError(f"no loop at the accepted period {chosen_range}")
    try:
        scratch.unlink()
    except FileNotFoundError:
        pass

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
        "state": spec.get("state"),
        "note": spec.get("note", ""),
        "source": str(spec.get("save", "(cold boot)")),
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
    manifest_path = args.outdir / "music_manifest.json"
    # Merge into the existing manifest: a `--track` run must not drop the other
    # entries (a partial build used to replace the whole file).
    previous: list[dict] = []
    if manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text()).get("tracks", [])
        except ValueError:
            previous = []
    entries = [e for e in previous
               if e.get("name") not in {t["name"] for t in tracks}]
    failures = []
    for t in tracks:
        try:
            entries.append(build_track(t["name"], t, args.captures / t["name"],
                                       args.outdir, args.recomp, args.use_capture))
        except (FileNotFoundError, ValueError) as exc:
            failures.append(t["name"])
            print(f"{t['name']}: skipped: {exc}", file=sys.stderr)

    order = {}
    for i, t in enumerate(spec["tracks"]):
        order[t["name"]] = i
    entries.sort(key=lambda e: order.get(e.get("name"), 999))
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
