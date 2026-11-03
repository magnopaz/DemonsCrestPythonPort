#!/usr/bin/env python3
"""Force-load every area that has no capture yet and record the ones that work.

`tools/oracle/load_area.py` loads a single arbitrary area by retargeting an
in-flight room transition.  This driver walks the missing set, calls it once per
area, keeps the captures whose BG1 verification score clears `--min-score`, and
adds them to `tools/dc_extract/bg2_captures.json` so `extract.py` bakes their
backdrop.

Resumable: an area that already has a capture with a good score is skipped, so
the sweep can be interrupted and restarted.  Failures are reported, not hidden —
some rooms genuinely cannot be matched (sparse BG1, wide rooms whose window is
only partly rewritten, and the 72/74 loader stall).

Usage:
  python3 tools/oracle/sweep_missing_areas.py --min-score 0.9
  python3 tools/oracle/sweep_missing_areas.py --areas 14,28,36 --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tools" / "dc_extract" / "bg2_captures.json"
ALL_AREAS = 113


def capture_score(capture_dir: Path) -> float | None:
    meta = capture_dir / "capture.json"
    if not meta.is_file():
        return None
    try:
        return float(json.loads(meta.read_text()).get("score", 0.0))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--areas", default="",
                    help="comma-separated area ids; default is every missing area")
    ap.add_argument("--min-score", type=float, default=0.9)
    ap.add_argument("--port", type=int, default=5600)
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    areas = manifest.setdefault("areas", {})
    have = {int(a) for a in areas}
    wanted = ([int(a) for a in args.areas.split(",") if a.strip()]
              if args.areas else [a for a in range(ALL_AREAS) if a not in have])

    ok, failed, skipped = [], [], []
    for i, area in enumerate(wanted):
        out = ROOT / "captures" / f"area{area}"
        score = capture_score(out)
        if score is not None and score >= args.min_score:
            skipped.append(area)
            continue
        print(f"[{i + 1}/{len(wanted)}] area {area} ...", flush=True)
        if args.dry_run:
            continue
        try:
            proc = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "oracle" / "load_area.py"),
                 "--area", str(area), "--port", str(args.port + i)],
                cwd=str(ROOT), capture_output=True, text=True, timeout=args.timeout)
            tail_lines = (proc.stdout or proc.stderr or "").strip().splitlines()
        except subprocess.TimeoutExpired:
            failed.append((area, None))
            print(f"    timed out after {args.timeout}s", flush=True)
            continue
        score = capture_score(out)
        if score is not None and score >= args.min_score:
            frames = json.loads((out / "capture.json").read_text())["frames"]
            areas[str(area)] = {
                "dir": f"captures/area{area}",
                "frame": frames[-1],
                "note": f"auto: load_area.py (score {score:.3f})",
            }
            MANIFEST.write_text(json.dumps(manifest, indent=1))
            ok.append((area, score))
            print(f"    ok score={score:.3f}", flush=True)
        else:
            failed.append((area, score))
            tail = tail_lines[-2:]
            print(f"    failed score={score} :: {' | '.join(tail)}", flush=True)

    print(f"\nsweep: ok={len(ok)} failed={len(failed)} skipped={len(skipped)}")
    if failed:
        print("failed areas:", [a for a, _ in failed])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
