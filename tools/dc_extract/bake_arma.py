#!/usr/bin/env python3
"""Bake Arma's three encounter palettes from the labelled sheets.

Arma is species $A5 in areas 3/23/36/67. The ROM object flags differ per
encounter (0, 2, 4, 4); the sheets expose the matching first-fight bronze,
second-fight green and Ultimate Arma palettes. The base ``a5`` entry stays the
normal species art; the flags-2/flags-4 entries are boss variants selected by
``Assets_BossSheet(..., flags)``.

The previous version cropped whole sheet rows (0..148, 158..252, 283..402),
which also captured the row captions and two or three Arma poses in one PNG.
Those boxes are replaced by individual, measured frame boxes.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs/sprites/SNES - Demon's Crest - Enemies & Bosses - Arma.gif"
ULTIMATE = (ROOT / "docs/sprites/SNES - Demon's Crest - Enemies & Bosses - "
            "Ultimate Arma.gif")
GEN = ROOT / "assets" / "generated"

# Individual poses of the first fight. (x0, y0, x1, y1), exclusive x1/y1.
BASE_BANDS: dict[str, list[tuple[int, int, int, int]]] = {
    "idle": [
        (18, 57, 52, 113),
        (65, 57, 99, 113),
        (103, 57, 137, 113),
    ],
    "breath": [
        (9, 268, 67, 318),
        (71, 267, 133, 318),
        (137, 268, 195, 318),
    ],
    "dive": [
        (254, 265, 303, 310),
    ],
    "hurt": [
        (365, 264, 399, 320),
    ],
}

# Same poses in the green second fight (the sheet repeats the layout).
SECOND_BANDS: dict[str, list[tuple[int, int, int, int]]] = {
    "idle": [
        (20, 437, 53, 493),
        (67, 437, 100, 493),
        (105, 437, 138, 493),
    ],
    "breath": [
        (11, 648, 68, 698),
        (73, 647, 134, 697),
        (139, 648, 196, 698),
    ],
    "dive": [
        (256, 645, 304, 690),
    ],
    "hurt": [
        (367, 644, 400, 700),
    ],
}

# Ultimate Arma has a separate sheet/layout.
ULTIMATE_BANDS: dict[str, list[tuple[int, int, int, int]]] = {
    "idle": [
        (10, 26, 42, 84),
        (58, 26, 91, 84),
        (95, 27, 128, 84),
    ],
    "breath": [
        (6, 239, 64, 289),
        (68, 237, 130, 288),
        (134, 239, 192, 289),
    ],
    "dive": [
        (247, 236, 300, 280),
    ],
    "hurt": [
        (316, 244, 358, 291),
    ],
}


def bake(im: Image.Image, bg: tuple[int, int, int], bands: dict, prefix: str):
    frames: list[dict] = []
    clips: dict[str, list[int]] = {}
    for clip, boxes in bands.items():
        clips[clip] = []
        for x0, y0, x1, y1 in boxes:
            crop = im.crop((x0, y0, x1, y1)).convert("RGBA")
            px = crop.load()
            for y in range(crop.height):
                for x in range(crop.width):
                    r, g, b, _a = px[x, y]
                    if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) <= 30:
                        px[x, y] = (0, 0, 0, 0)
            bbox = crop.getbbox()
            if bbox is None:
                print(f"  {clip} {x0},{y0}: empty after keying")
                continue
            crop = crop.crop(bbox)
            index = len(frames)
            tex = f"{prefix}{index}.png"
            crop.save(GEN / tex)
            frames.append({
                "texture": tex,
                "anchor_x": crop.width // 2,
                "anchor_y": crop.height,
                "duration": 8,
                "width": crop.width,
                "height": crop.height,
            })
            clips[clip].append(index)
            print(f"  {clip}[{len(clips[clip]) - 1}] {crop.size}")
    return frames, clips


def entry(frames: list[dict], clips: dict[str, list[int]], source: str,
          flags: int | None = None) -> dict:
    states: dict[str, list[int]] = {}
    if clips.get("idle"):
        states["0"] = clips["idle"]
    if clips.get("breath"):
        states["1"] = clips["breath"]
    if clips.get("dive"):
        states["2"] = clips["dive"]
        states["3"] = clips["dive"]
    hurt = clips.get("hurt", [])
    if hurt:
        states["4"] = hurt
    data = {
        "species": 0xA5,
        "frames": frames,
        "source": source,
        "states": states,
        "hurt": hurt[0] if hurt else 0,
        "default": clips["idle"][0] if clips.get("idle") else 0,
    }
    if flags is not None:
        data["variant"] = "boss"
        data["flags"] = flags
    return data


def background(im: Image.Image) -> tuple[int, int, int]:
    small = im.resize((max(1, im.width // 4), max(1, im.height // 4)))
    return Counter(small.getdata()).most_common(1)[0][0]


def main() -> int:
    im = Image.open(SRC).convert("RGB")
    ultimate = Image.open(ULTIMATE).convert("RGB")
    bg = background(im)

    # Only replace the base files; keeps the palette variants intact.
    for stale in GEN.glob("enemy_a5_[0-9]*.png"):
        stale.unlink()

    base_frames, base_clips = bake(im, bg, BASE_BANDS, "enemy_a5_")
    second_frames, second_clips = bake(im, bg, SECOND_BANDS, "enemy_a5b_")
    ultimate_frames, ultimate_clips = bake(ultimate, background(ultimate),
                                           ULTIMATE_BANDS, "enemy_a5u_")

    anim_path = GEN / "species_anim.json"
    anim = json.loads(anim_path.read_text()) if anim_path.is_file() else {
        "species": {}}
    species = anim.setdefault("species", {})
    species["a5"] = entry(
        base_frames, base_clips,
        "user sprite sheet Arma.gif first fight (Spriters Resource)")
    species["a5_f2"] = entry(
        second_frames, second_clips,
        "user sprite sheet Arma.gif second fight palette",
        flags=2)
    species["a5_f4"] = entry(
        ultimate_frames, ultimate_clips,
        "user sprite sheet Ultimate Arma.gif",
        flags=4)
    anim_path.write_text(json.dumps(anim, indent=1))
    print(f"Arma: {len(base_frames)} base, {len(second_frames)} green, "
          f"{len(ultimate_frames)} ultimate frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
