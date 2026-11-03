#!/usr/bin/env python3
"""Bake Firebrand's six form sheets into per-form player animations.

The earlier version split each band on empty columns. That produced captions,
merged touching poses and half-sprites. This version uses the sheet's
connected components instead: every pose is one connected body, so a component
whose bounding box lives inside a measured clip region is a frame. The clip
regions are per sheet because their layouts differ.

The resulting frames are keyed to transparency, foot-centred with the opaque
pixels in the lower part of the pose, and written as
``fb_<form>_<clip>_<i>.png`` + ``player_forms.json``.
"""

from __future__ import annotations

import json
from collections import Counter, deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SPRITES = ROOT / "docs/sprites"
GEN = ROOT / "assets/generated"

# (x0, x1, y0, y1), exclusive. The ranges isolate one clip; the frame splitter
# then takes the connected pose components inside the range.
NORMAL = {
    "idle": (0, 125, 20, 64),
    "walk": (125, 320, 20, 64),
    "attack": (320, 395, 20, 64),
    "jump": (0, 165, 95, 151),
    "fall": (165, 325, 95, 151),
    "land": (325, 390, 95, 151),
    "hover": (0, 195, 184, 246),
    "flying": (195, 555, 184, 246),
    "hurt": (130, 220, 286, 329),
    "death": (180, 490, 286, 329),
}
GROUND = {
    "idle": (0, 125, 40, 80),
    "walk": (125, 305, 40, 80),
    "attack": (305, 395, 40, 80),
    "jump": (0, 120, 114, 169),
    "fall": (120, 270, 114, 169),
    "land": (270, 320, 114, 169),
    "hurt": (0, 90, 182, 246),
    "death": (100, 360, 182, 246),
}
AERIAL = {
    "idle": (0, 145, 20, 75),
    "walk": (145, 400, 20, 75),
    "attack": (400, 515, 20, 75),
    "jump": (0, 170, 124, 178),
    "fall": (240, 515, 124, 178),
    "land": (180, 240, 124, 178),
    "hover": (240, 515, 124, 178),
    "flying": (20, 365, 208, 295),
    "hurt": (0, 100, 320, 368),
    "death": (110, 380, 320, 368),
}
TIDAL = {
    "idle": (0, 120, 29, 72),
    "walk": (120, 300, 29, 72),
    "attack": (300, 340, 29, 72),
    "jump": (0, 145, 108, 160),
    "fall": (145, 252, 108, 160),
    "land": (252, 340, 108, 160),
    "hover": (0, 195, 194, 244),
    "flying": (195, 250, 194, 244),
    "hurt": (0, 90, 275, 317),
    "death": (95, 350, 275, 317),
}
LEGENDARY = {
    "idle": (0, 130, 26, 73),
    "walk": (130, 325, 26, 73),
    "attack": (325, 405, 26, 73),
    "jump": (0, 185, 107, 158),
    "fall": (185, 350, 107, 158),
    "land": (350, 390, 107, 158),
    "hover": (0, 220, 191, 253),
    "flying": (220, 540, 191, 253),
    "hurt": (0, 110, 297, 342),
    "death": (110, 445, 297, 342),
}
ULTIMATE = {
    "idle": (0, 130, 22, 67),
    "walk": (130, 330, 22, 67),
    "attack": (330, 405, 22, 67),
    "jump": (0, 185, 105, 156),
    "fall": (185, 345, 105, 156),
    "land": (345, 390, 105, 156),
    "hover": (0, 220, 189, 251),
    "flying": (220, 540, 189, 251),
    "hurt": (160, 250, 293, 339),
    "death": (275, 585, 293, 339),
}
SHEETS = [
    (0, "normal", "Playable Characters - Firebrand.gif", NORMAL),
    (1, "ground", "Playable Characters - Firebrand (Ground).gif", GROUND),
    (2, "aerial", "Playable Characters - Firebrand (Aerial).gif", AERIAL),
    (3, "tidal", "Playable Characters - Firebrand (Tidal).gif", TIDAL),
    (4, "legendary", "Playable Characters - Firebrand (Legendary).gif",
     LEGENDARY),
    (5, "ultimate", "Playable Characters - Firebrand (Ultimate).gif",
     ULTIMATE),
]


def background_colour(im: Image.Image) -> tuple[int, int, int]:
    small = im.resize((max(1, im.width // 4), max(1, im.height // 4)))
    return Counter(small.getdata()).most_common(1)[0][0]


def is_bg(pixel, bg) -> bool:
    return abs(pixel[0] - bg[0]) + abs(pixel[1] - bg[1]) + \
        abs(pixel[2] - bg[2]) <= 30


def connected_boxes(im: Image.Image, bg) -> list[tuple[int, int, int, int, int]]:
    w, h = im.size
    px = im.load()
    seen = bytearray(w * h)
    boxes = []
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if seen[i] or is_bg(px[x, y], bg):
                continue
            q = deque([(x, y)])
            seen[i] = 1
            minx = maxx = x
            miny = maxy = y
            area = 0
            while q:
                cx, cy = q.popleft()
                area += 1
                minx = min(minx, cx)
                maxx = max(maxx, cx)
                miny = min(miny, cy)
                maxy = max(maxy, cy)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h:
                            j = ny * w + nx
                            if not seen[j] and not is_bg(px[nx, ny], bg):
                                seen[j] = 1
                                q.append((nx, ny))
            if area >= 40 and maxy - miny + 1 >= 16:
                boxes.append((minx, miny, maxx + 1, maxy + 1, area))
    return boxes


def frame_from_box(im: Image.Image, box, bg) -> Image.Image | None:
    x0, y0, x1, y1, _area = box
    crop = im.crop((x0, y0, x1, y1)).convert("RGBA")
    px = crop.load()
    for y in range(crop.height):
        for x in range(crop.width):
            r, g, b, _a = px[x, y]
            if is_bg((r, g, b), bg):
                px[x, y] = (0, 0, 0, 0)
    bbox = crop.getbbox()
    if bbox is None:
        return None
    return crop.crop(bbox)


def pose_brightness(img: Image.Image) -> float:
    """Mean brightness of opaque pixels; used to pick the white hurt palette."""
    px = img.load()
    total = 0
    bright = 0
    for y in range(img.height):
        for x in range(img.width):
            value = px[x, y]
            if len(value) == 4:
                r, g, b, a = value
            else:
                r, g, b = value
                a = 255
            if a:
                total += 1
                bright += (r + g + b) / 3.0
    return bright / total if total else 0.0


def clip_durations(clip: str, count: int) -> list[int]:
    """Frame cadence for a form clip.

    The captured base sheet is the timing reference (walk 7/7/9/7/7/9,
    jump/fall/land/attack from save0). Form sheets have fewer or more poses, so
    sample that pattern as closely as possible instead of showing every pose
    for the same arbitrary 8 frames.
    """
    patterns = {
        "walk": [7, 7, 9, 7, 7, 9],
        "jump": [1, 2, 2, 1],
        "fall": [3, 2, 3, 2],
        "land": [3, 5],
        "attack": [1, 6, 10],
        "hurt": [8],
        "death": [8],
        "idle": [8],
        "hover": [8],
        "flying": [8],
    }
    pattern = patterns.get(clip, [8])
    if count <= 0:
        return []
    if clip == "attack" and count == 2:
        return [1, 16]
    if clip == "attack" and count == 1:
        return [17]
    if clip == "land" and count == 1:
        return [pattern[-1]]
    return [pattern[i % len(pattern)] for i in range(count)]


def foot_anchor_x(img: Image.Image) -> int:
    """Body/feet centre from the opaque pixels in the lower part of the pose."""
    px = img.load()
    w, h = img.size
    start = max(0, int(h * 0.55))
    total = 0
    weighted = 0
    for y in range(start, h):
        for x in range(w):
            if px[x, y][3]:
                total += 1
                weighted += x
    if total == 0:
        return w // 2
    return max(0, min(w, round(weighted / total)))


def main() -> int:
    for stale in GEN.glob("fb_*.png"):
        stale.unlink()
    forms = []
    for form, name, sheet, bands in SHEETS:
        im = Image.open(SPRITES / f"SNES - Demon's Crest - {sheet}").convert(
            "RGB")
        bg = background_colour(im)
        boxes = connected_boxes(im, bg)
        clips = {}
        for clip, (x0, x1, y0, y1) in bands.items():
            selected = [
                box for box in boxes
                if box[0] >= x0 - 2 and box[2] <= x1 + 2 and
                box[1] >= y0 - 2 and box[3] <= y1 + 2
            ]
            selected.sort(key=lambda box: (box[0], box[1]))
            if clip == "hurt" and selected:
                # The hurt row also contains a palette swatch/dark body. The
                # real hurt palette is the bright white/gold pose.
                selected = [max(
                    selected,
                    key=lambda box: pose_brightness(
                        im.crop((box[0], box[1], box[2], box[3])))
                )]
            steps = []
            for box in selected:
                crop = frame_from_box(im, box, bg)
                if crop is None or crop.width < 8 or crop.height < 16:
                    continue
                tex = f"fb_{name}_{clip}_{len(steps)}.png"
                crop.save(GEN / tex)
                steps.append({
                    "texture": tex,
                    "anchor_x": foot_anchor_x(crop),
                    "anchor_y": crop.height,
                    "duration": 8,  # replaced below with clip cadence
                })
            durations = clip_durations(clip, len(steps))
            for step, duration in zip(steps, durations):
                step["duration"] = max(1, duration)
            if not steps:
                print(f"  {name}/{clip}: no frames")
                continue
            loop = clip not in ("attack", "land", "hurt", "death", "jump",
                                "fall")
            clips[clip] = {"loop": loop, "steps": steps}
        forms.append({"form": form, "name": name, "clips": clips})
        print(f"{name}: { {k: len(v['steps']) for k, v in clips.items()} }")
    (GEN / "player_forms.json").write_text(json.dumps({"forms": forms},
                                                      indent=1))
    print("wrote player_forms.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
