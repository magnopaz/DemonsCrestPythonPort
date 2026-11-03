#!/usr/bin/env python3
"""Assemble pixelized frames into a species entry the engine can load.

This is the last stop of Pipeline C (``docs/AI_CHARACTER_PIPELINE.md`` Stage 6),
and the only place that decides what a new enemy *is*: one species id, at most
``DC_SPECIES_FRAMES`` (8) textures, ``states`` mapping the engine's object states
to frame lists of at most ``DC_STATE_FRAMES`` (8) entries, plus optional
``hurt`` and ``default`` frames.

It re-checks every hard constraint itself instead of trusting whatever produced
the PNGs -- a sprite that is 65 px wide, carries 17 colours or has soft alpha
cannot enter the game through this tool either. The output is:

* ``spr_<species>_<clip>_<i>.png`` copies, named deterministically;
* ``species_entries.json`` next to them, which is the merge payload for
  ``assets/generated/species_anim.json``. That file is an **object keyed by the
  species id in lowercase hex** (``{"species": {"2c": {...}}}``), the same shape
  ``bake_enemy_sheets.py`` writes and the audit reads; an array is rejected with
  "no 'species' object".

Usage:
  python3 tools/gen/compose_species.py --spec imp.json --out assets/authored
  cat imp.json | python3 tools/gen/compose_species.py --spec - --out /tmp/x
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

MAX_FRAMES = 8        # DC_SPECIES_FRAMES
MAX_STATE = 8         # DC_STATE_FRAMES
MAX_SIZE = 64
MAX_COLORS = 15
BINARY_ALPHA = 128


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True,
                    help="JSON spec (path or '-') with species, frames, states, "
                         "hurt, default")
    ap.add_argument("--out", type=Path, required=True,
                    help="directory for the PNGs and species_entries.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate and print, write nothing")
    return ap.parse_args()


def check_png(path: Path) -> tuple[list[str], dict]:
    errors = []
    if not path.is_file():
        return [f"missing file {path}"], {}
    im = Image.open(path).convert("RGBA")
    if im.width > MAX_SIZE or im.height > MAX_SIZE:
        errors.append(f"{path.name}: {im.width}x{im.height} exceeds {MAX_SIZE}px")
    colours = [c for count, c in (im.getcolors(maxcolors=1 << 20) or [])
               if c[3] >= BINARY_ALPHA]
    if len(colours) > MAX_COLORS:
        errors.append(f"{path.name}: {len(colours)} opaque colours > {MAX_COLORS}")
    hist = im.getchannel("A").histogram()
    levels = {value for value, count in enumerate(hist) if count}
    if not levels <= {0, 255}:
        errors.append(f"{path.name}: alpha levels {sorted(levels)} are not binary")
    if im.getbbox() is None:
        errors.append(f"{path.name}: fully transparent")
    return errors, {"width": im.width, "height": im.height,
                    "colors": len(colours)}


def main() -> int:
    args = parse_args()
    text = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text()
    spec = json.loads(text)

    species = spec.get("species")
    frames = spec.get("frames") or []
    if not isinstance(species, int):
        print("compose_species: spec needs an integer 'species'", file=sys.stderr)
        return 2
    if not 0 <= species <= 0xFFFF:
        print("compose_species: species out of range", file=sys.stderr)
        return 2
    if len(frames) > MAX_FRAMES:
        print(f"compose_species: {len(frames)} frames > DC_SPECIES_FRAMES "
              f"{MAX_FRAMES}; the engine would drop the rest", file=sys.stderr)
        return 1

    errors: list[str] = []
    out_frames = []
    base = Path(args.spec).parent if args.spec != "-" else Path(".")
    for index, item in enumerate(frames):
        src = Path(item["src"])
        if not src.is_absolute():
            src = (base / src).resolve()
        png_errors, info = check_png(src)
        errors.extend(png_errors)
        clip = item.get("clip", "frame")
        tex = f"spr_{species:03x}_{clip}_{index:02d}.png"
        out_frames.append({
            "texture": tex,
            "anchor_x": int(item.get("anchor_x", info.get("width", 0) // 2)),
            "anchor_y": int(item.get("anchor_y", info.get("height", 0))),
            "duration": max(1, int(item.get("duration", 7))),
            "width": info.get("width", 0),
            "height": info.get("height", 0),
            "_src": item["src"],
            "_info": info,
        })

    states = {}
    for key, indices in (spec.get("states") or {}).items():
        state = int(key)
        if not 0 <= state < 32:
            errors.append(f"state {state} out of range")
            continue
        if len(indices) > MAX_STATE:
            errors.append(f"state {state} has {len(indices)} frames > "
                          f"DC_STATE_FRAMES {MAX_STATE}")
        bad = [i for i in indices if not 0 <= i < len(out_frames)]
        if bad:
            errors.append(f"state {state} references missing frames {bad}")
        else:
            states[str(state)] = list(indices)

    entry = {"species": species, "boss": bool(spec.get("boss", False)),
             "frames": [{k: v for k, v in f.items() if not k.startswith("_")}
                        for f in out_frames],
             "states": states,
             "source": spec.get("source", "Pipeline C (docs/AI_CHARACTER_PIPELINE.md)")}
    for key in ("hurt", "default"):
        if key in spec:
            value = int(spec[key])
            if not 0 <= value < len(out_frames):
                errors.append(f"{key} frame {value} out of range")
            else:
                entry[key] = value
    if not states and "default" not in entry:
        errors.append("entry has neither states nor default: it would render "
                      "nothing")

    if errors:
        for err in errors:
            print(f"compose_species: {err}", file=sys.stderr)
        return 1

    # species_anim.json is an object keyed by lowercase hex, like the bakers write
    payload = {"species": {f"{species:x}": entry}}
    print(f"species 0x{species:03x} ({species}): {len(out_frames)} frames, "
          f"states {sorted(states)}, hurt={entry.get('hurt')}, "
          f"default={entry.get('default')}")
    for frame in out_frames:
        info = frame["_info"]
        print(f"  {frame['texture']:28s} {info['width']}x{info['height']} "
              f"{info['colors']} colours  anchor=({frame['anchor_x']},"
              f"{frame['anchor_y']}) dur={frame['duration']}")

    if args.dry_run:
        print("compose_species: dry run, nothing written")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    for frame in out_frames:
        shutil.copyfile(frame["_src"], args.out / frame["texture"])
    target = args.out / "species_entries.json"
    target.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"compose_species: wrote {len(out_frames)} PNGs + {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
