#!/usr/bin/env python3
"""Bake the bad ending's backdrops and page timing from a frame capture.

The take `captures/badend` (2026-11-10) is the first recording that carries the
ending itself: 9 570 BMPs from Phalanx's death to past the epilogue.  The
narration is five pages over a Mode 7 flight scene, then the epilogue over
Firebrand's portrait and a strip of flames (docs/ENDINGS.md).

This tool picks the two frames that hold only art (no text) and writes them next
to a JSON with the measured page windows, so `dcpy` can stage the sequence the
way the console does instead of approximating it.

Usage:
  python3 tools/dc_extract/bake_ending_capture.py \
      --capture ../DemonsCrestSNESRecomp/build-trace/captures/badend \
      --out assets/generated

Frame choice (verified by eye, both text-free):
  3000  flight scene over the demon realm (castle/islands, Firebrand flying)
  8202  epilogue portrait: Firebrand silhouette over the flame strip
Page windows come from the text-presence scan (bright pixels, 10-frame steps).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FLIGHT_FRAME = 3000
PORTRAIT_FRAME = 8202

# Narration pages: (first frame, last frame) of the text on screen, measured on
# the capture.  The gaps between them are the page fades.
PAGES = [(4430, 5040), (5180, 5610), (5750, 6200), (6300, 6900), (6930, 7420)]
EPILOGUE = (8240, 13900)


def frame_path(capture: Path, n: int) -> Path:
    for candidate in (capture / "frames" / f"frame_{n:06d}.bmp",
                      capture / f"frame_{n:06d}.bmp"):
        if candidate.is_file():
            return candidate
    raise SystemExit(f"bake_ending_capture: no frame {n} under {capture}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--capture", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "generated")
    args = ap.parse_args()

    from PIL import Image

    capture = args.capture if args.capture.is_dir() else args.capture.parent
    args.out.mkdir(parents=True, exist_ok=True)
    made = []
    for frame, name in ((FLIGHT_FRAME, "ending_bad_flight.png"),
                        (PORTRAIT_FRAME, "ending_bad_portrait.png")):
        src = frame_path(capture, frame)
        with Image.open(src) as image:
            image.convert("RGB").save(args.out / name)
        made.append(name)

    timing = {
        "source": str(capture),
        "flight_frame": FLIGHT_FRAME,
        "portrait_frame": PORTRAIT_FRAME,
        "pages": [{"first": a, "last": b} for a, b in PAGES],
        "epilogue": {"first": EPILOGUE[0], "last": EPILOGUE[1]},
    }
    (args.out / "endings_timing.json").write_text(json.dumps(timing, indent=1))
    print(f"bake_ending_capture: {', '.join(made)} + endings_timing.json "
          f"({len(PAGES)} pages, epilogue {EPILOGUE[1] - EPILOGUE[0]} frames)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
