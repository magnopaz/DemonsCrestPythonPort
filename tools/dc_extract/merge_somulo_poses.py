#!/usr/bin/env python3
"""Append oracle-baked Somulo poses to species 33 without disturbing the walk.

The walk cycle (frames 0-7, states 7/8/0) comes from the reference GIF and must
keep its numbering.  This tool copies the new poses to `enemy_33_<n>.png`
starting at index 8 and merges them into the existing `"33"` entry: frames are
appended, only the requested state clips are added or replaced, and every other
key is left untouched.

Usage:
  python3 tools/dc_extract/merge_somulo_poses.py \
      --pose 4=/tmp/poses/f002.png:roar \
      --pose 1=/tmp/poses/f005.png:windup \
      --pose 2=/tmp/poses/f010.png:fire
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--species", default="33")
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--pose", action="append", default=[],
                    help="STATE=PNG[:label] - append PNG and point STATE at it")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = args.assets / "species_anim.json"
    doc = json.loads(path.read_text())
    key = args.species.lower().removeprefix("0x")
    entry = doc["species"][key]
    first = len(entry["frames"])
    print(f"species {key}: {first} frames, states "
          f"{ {k: v for k, v in entry['states'].items()} }")

    for spec in args.pose:
        state, _, rest = spec.partition("=")
        png, _, label = rest.partition(":")
        src = Path(png)
        img = Image.open(src).convert("RGBA")
        idx = len(entry["frames"])
        name = f"enemy_{key}_{idx}.png"
        if not args.dry_run:
            shutil.copyfile(src, args.assets / name)
        # Feet anchoring: the art is tightly cropped, so the bottom row is the
        # ground contact and the horizontal centre keeps the body over the
        # object position.
        frame = {"texture": name, "anchor_x": img.width // 2,
                 "anchor_y": img.height, "duration": 8,
                 "width": img.width, "height": img.height}
        entry["frames"].append(frame)
        entry["states"][state] = [idx]
        print(f"  state {state} -> frame {idx} ({name}, {img.width}x"
              f"{img.height}, anchor {frame['anchor_x']},{frame['anchor_y']})"
              f" {label}")

    if not args.dry_run:
        path.write_text(json.dumps(doc, indent=1))
        again = json.loads(path.read_text())
        assert len(again["species"]) == len(doc["species"])
        print(f"wrote {path}: {len(again['species'])} species, "
              f"species {key} now {len(again['species'][key]['frames'])} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
