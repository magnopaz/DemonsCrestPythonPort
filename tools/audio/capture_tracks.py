#!/usr/bin/env python3
"""Record every track's audio from the oracle (resumable).

`make_music_asset.py` does capture + loop + manifest in one go and stops on the
first failure; this driver only captures, so the slow part can run once and be
retried per track.  It reuses `capture_music.py` unchanged, which means the
provenance (save hash, area byte, produced samples, wav hash) still lands in
each `<track>/meta.json`.

Usage:
  python3 tools/audio/capture_tracks.py                 # every track
  python3 tools/audio/capture_tracks.py --only music_boss,music_town
  python3 tools/audio/capture_tracks.py --force         # recapture
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "tools" / "audio" / "music_tracks.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", type=Path, default=SPEC)
    ap.add_argument("--recomp", type=Path, default=None)
    ap.add_argument("--captures", type=Path, default=ROOT / "captures" / "audio")
    ap.add_argument("--only", default="")
    ap.add_argument("--port", type=int, default=4530)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    spec = json.loads(args.spec.read_text())
    tracks = spec["tracks"]
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        tracks = [t for t in tracks if t["name"] in wanted]
        if not tracks:
            raise SystemExit(f"capture_tracks: no such track in {args.spec}")

    recomp = args.recomp or (ROOT.parent / "DemonsCrestSNESRecomp")
    failures = []
    for i, t in enumerate(tracks):
        out = args.captures / t["name"]
        live = out / "live.wav"
        if live.is_file() and not args.force:
            print(f"{t['name']}: already captured ({live.stat().st_size} bytes)")
            continue
        cmd = [sys.executable, str(ROOT / "tools" / "audio" / "capture_music.py"),
               "--recomp", str(recomp),
               "--save", str(recomp / t["save"]),
               "--out", str(out),
               "--seconds", str(t.get("capture_seconds", 120)),
               "--settle-frames", str(t.get("settle_frames", 120)),
               "--port", str(args.port + i)]
        if not t.get("neutralise_objects", True):
            cmd.append("--keep-objects")
        print(f"{t['name']}: capturing {t.get('capture_seconds', 120)} s ...",
              flush=True)
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            failures.append(t["name"])
            print(f"{t['name']}: FAILED\n{res.stdout[-1500:]}\n{res.stderr[-1500:]}")
            continue
        print(f"{t['name']}: ok ({live.stat().st_size} bytes)")
    if failures:
        print(f"capture_tracks: {len(failures)} failed: {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
