#!/usr/bin/env python3
"""Bake Somulo's full-body frames from the labelled sprite atlas.

The atlas (`docs/sprites/...Somulo.gif`) is a *component* sheet: heads, a
torso and leg grids are drawn separately, so cropping "a Somulo" out of it does
not work.  The completed walk is in `docs/reference/somulo_walk.gif` (a clean
2x rip of the same art).  This tool:

* writes the 16 full-body walk frames from that reference;
* takes the windup / fire / roar heads from the atlas and overlays them on a
  clean reference body for states 1, 2, 4 and 5;
* takes the collapsed body from the atlas for state 6/8;
* writes an authored 22-frame `species_anim.json` entry (no `parts` block), so
  the Enemy Editor can see and edit every frame.

The old generated entry used gameplay cuts with gate bars and the arena ground
baked in; this one is transparent and uses only sheet/reference pixels.

Usage:
  python tools/dc_extract/bake_somulo_frames.py
  python tools/dc_extract/bake_somulo_frames.py --out captures/somulo_frames_test
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SHEET = ROOT / "docs" / "sprites" / \
    "SNES - Demon's Crest - Enemies & Bosses - Somulo.gif"
REFERENCE = ROOT / "docs" / "reference" / "somulo_walk.gif"
SPECIES = 0x33
SPECIES_KEY = "33"
ANCHOR_X, ANCHOR_Y = 60, 90       # 1x feet anchor in the 241x181 reference

# Atlas boxes are (y, x, w, h) at 2x, matching bake_somulo_parts.py.
HEADS = {
    "windup": (71, 306, 95, 74),
    "fire": (71, 411, 98, 74),
    "roar": (71, 519, 106, 74),
}
DEFEATED = (446, 291, 119, 89)
SOCKET = (161 + 27.5, 1 + 102)
NECK_CUT = {"windup": (0, 16), "fire": (0, 15), "roar": (0, 15)}
HEAD_BOX = (1, 161, 71, 103)      # neutral head in the reference, 2x


def sheet_rgba() -> Image.Image:
    img = Image.open(SHEET).convert("RGB")
    arr = np.asarray(img).astype(int)
    alpha = (arr.sum(axis=2) > 45).astype("uint8") * 255
    out = img.convert("RGBA")
    out.putalpha(Image.fromarray(alpha))
    return out


def crop_alpha(img: Image.Image, box) -> Image.Image:
    y, x, w, h = box
    return img.crop((x, y, x + w, y + h))


def to_1x(img: Image.Image, box: tuple[int, int, int, int],
          frame_anchor: tuple[float, float]) -> tuple[Image.Image, int, int]:
    """Crop a 2x frame, halve it, and return the anchor relative to the crop."""
    x0, y0, x1, y1 = box
    crop = img.crop((x0, y0, x1, y1))
    w = max(1, round(crop.width / 2))
    h = max(1, round(crop.height / 2))
    crop = crop.resize((w, h), Image.NEAREST)
    ax = round(frame_anchor[0] - x0 / 2.0)
    ay = round(frame_anchor[1] - y0 / 2.0)
    return crop, ax, ay


def reference_frames() -> list[Image.Image]:
    gif = Image.open(REFERENCE)
    frames = []
    for i in range(gif.n_frames):
        gif.seek(i)
        frames.append(gif.convert("RGBA"))
    return frames


def frame_bbox(img: Image.Image) -> tuple[int, int, int, int]:
    box = img.getbbox()
    if box is None:
        raise SystemExit("bake_somulo_frames: empty frame")
    return box


def bake_walk(reference: list[Image.Image], out: Path) -> list[dict]:
    frames = []
    for i, src in enumerate(reference):
        box = frame_bbox(src)
        crop, ax, ay = to_1x(src, box, (ANCHOR_X, ANCHOR_Y))
        name = f"somulo_walk_{i:02d}.png"
        crop.save(out / name)
        frames.append({
            "texture": f"sprites/somulo/{name}",
            "anchor_x": ax, "anchor_y": ay,
            "duration": 7, "width": crop.width, "height": crop.height,
        })
    return frames


def head_crop(sheet: Image.Image, name: str) -> tuple[Image.Image, tuple[int, int]]:
    box = HEADS[name]
    cut = NECK_CUT[name]
    at = (int(round(SOCKET[0] - cut[0])), int(round(SOCKET[1] - cut[1])))
    return crop_alpha(sheet, box), at


def bake_pose(reference: Image.Image, sheet: Image.Image, head_name: str,
              out: Path) -> dict:
    # The reference already contains the neutral head; clear that box and put
    # the requested atlas head on the same socket.
    y, x, w, h = HEAD_BOX
    body = reference.copy()
    body.paste((0, 0, 0, 0), (x, y, x + w, y + h))
    head, at = head_crop(sheet, head_name)
    canvas = Image.new("RGBA", (360, 220), (0, 0, 0, 0))
    canvas.alpha_composite(body, (0, 0))
    canvas.alpha_composite(head, at)
    box = frame_bbox(canvas)
    crop, ax, ay = to_1x(canvas, box, (ANCHOR_X, ANCHOR_Y))
    name = f"somulo_{head_name}.png"
    crop.save(out / name)
    return {
        "texture": f"sprites/somulo/{name}",
        "anchor_x": ax, "anchor_y": ay,
        "duration": 10, "width": crop.width, "height": crop.height,
    }


def bake_defeated(sheet: Image.Image, out: Path) -> dict:
    y, x, w, h = DEFEATED
    crop = crop_alpha(sheet, (y, x, w, h))
    # The atlas crop is 2x; halve it and put the feet at the anchor.
    crop = crop.resize((round(w / 2), round(h / 2)), Image.NEAREST)
    bbox = crop.getbbox()
    if bbox is None:
        raise SystemExit("bake_somulo_frames: empty defeated body")
    crop = crop.crop(bbox)
    name = "somulo_defeated.png"
    crop.save(out / name)
    return {
        "texture": f"sprites/somulo/{name}",
        "anchor_x": crop.width // 2, "anchor_y": crop.height,
        "duration": 8, "width": crop.width, "height": crop.height,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "authored")
    args = ap.parse_args()
    out = args.out / "sprites" / "somulo"
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("somulo_*.png"):
        stale.unlink()

    reference = reference_frames()
    sheet = sheet_rgba()
    frames = bake_walk(reference, out)
    pose_index = {}
    for name in ("windup", "fire", "roar"):
        pose_index[name] = len(frames)
        frames.append(bake_pose(reference[0], sheet, name, out))
    neutral = len(frames)
    name = "somulo_neutral.png"
    box = frame_bbox(reference[0])
    crop, ax, ay = to_1x(reference[0], box, (ANCHOR_X, ANCHOR_Y))
    crop.save(out / name)
    frames.append({
        "texture": f"sprites/somulo/{name}",
        "anchor_x": ax, "anchor_y": ay,
        "duration": 10, "width": crop.width, "height": crop.height,
    })
    defeated = len(frames)
    frames.append(bake_defeated(sheet, out))

    states = {
        # The reference has 16 walk frames; the state loader keeps 8 per
        # state, so the playable cycle samples every other frame.  The full
        # 16 stay in `frames` for future use/editing.
        "0": list(range(0, 16, 2)),
        "7": list(range(0, 16, 2)),
        "1": [pose_index["windup"]],
        "2": [pose_index["fire"]],
        "3": [neutral],
        "4": [pose_index["windup"]],  # stagger
        "5": [pose_index["roar"]],    # airborne/high attack
        "6": [defeated],
        "8": [defeated],
    }
    entry = {
        "species": SPECIES,
        "frames": frames,
        "states": states,
        "state_names": {
            "0": "walk", "7": "blind walk", "1": "windup", "2": "fire",
            "3": "recover", "4": "stagger", "5": "attack (high)",
            "6": "defeated", "8": "defeated",
        },
        "hurt": pose_index["windup"],
        "default": 0,
        "source": ("Somulo.gif heads/defeated + docs/reference/somulo_walk.gif "
                   "body walk; component atlas extraction"),
    }
    path = args.out / "species_anim.json"
    root = {"species": {}}
    if path.is_file():
        root = json.loads(path.read_text())
    root.setdefault("species", {})[SPECIES_KEY] = entry
    path.write_text(json.dumps(root, indent=1) + "\n")
    print(f"{len(frames)} frames -> {out}")
    print(f"states {states}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
