#!/usr/bin/env python3
"""Bake Somulo's body / legs / head parts (species 0x33) from the component atlas.

The boss is drawn by the hardware as separate parts: one torso, one leg sprite
that carries the walk cycle, and a head+neck sprite that is swapped per state.
The atlas (`docs/sprites/SNES - Demon's Crest - Enemies & Bosses - Somulo.gif`)
is that component sheet at 2x, but it stores the parts on a grid with no
alignment marks, so every offset used here is *measured*, never guessed:

* The body and the neutral head are located inside the reference walk capture
  (`docs/reference/somulo_walk.gif`, also 2x) by mask fitting.  The fit is
  pixel-exact (30 stray pixels of 9 868 for the body, 14 of 3 008 for the
  head), which fixes the body's neck socket and the head's joint.
* The other head poses are placed by their *neck cut*: each atlas head is
  cropped at the point where the neck was severed (the long straight run on
  the bottom or left edge of its bounding box).  Putting that cut's centre on
  the same socket is what makes the neck continuous; `--verify` renders every
  pose and reports the overlap at the joint.
* The legs are the reference frame minus the body and the neutral head, i.e.
  exactly the leg pixels the game drew under that body.  Taking them from the
  atlas grid instead would need a second leg sprite for the far side and the
  grid fit leaves ~4% of the frame unexplained; the reference frame does not.

Output: `somulo_body.png`, `somulo_legs.png`, `somulo_body_defeated.png`,
`somulo_head_{neutral,windup,fire,roar}.png` and a `parts` block inside the
species `33` entry of `species_anim.json`.  States that are not listed in that
block keep the baked single-image frames (the walk cycle), which is the
documented fallback.

Usage:
  python3 tools/dc_extract/bake_somulo_parts.py
  python3 tools/dc_extract/bake_somulo_parts.py --dry-run --verify /tmp/parts
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SHEET = ROOT / "docs" / "sprites" / "SNES - Demon's Crest - Enemies & Bosses - Somulo.gif"
GIF = ROOT / "docs" / "reference" / "somulo_walk.gif"

# --- measured on the atlas (y, x, w, h at 2x) -------------------------------
BODY = (442, 458, 195, 120)             # "Body": torso + tail, neck socket right
DEFEATED = (446, 291, 119, 89)          # "Hurt / Defeated": collapsed, complete
HEADS = {
    "neutral": (42, 44, 71, 103),       # Introduction Roar #1: head up, closed
    "windup": (71, 306, 95, 74),        # head lowered, jaws open
    "fire": (71, 411, 98, 74),          # head lowered, wider
    "roar": (71, 519, 106, 74),         # widest open, head thrust forward
}
# where the fitted parts sit in the 2x reference frame (mask fit, see docstring)
BODY_AT = (0, 39)
HEAD_AT = {"neutral": (161, 1)}
# heads placed by their neck cut: (cut centre in crop coords)
NECK_CUT = {"windup": (0, 16), "fire": (0, 15), "roar": (0, 15)}
SOCKET = (161 + 27.5, 1 + 102)          # body neck socket in the 2x frame

ANCHOR_X, ANCHOR_Y = 60, 91             # native feet anchor of the walk frames
FRAME_2X_X, FRAME_2X_Y = 2 * ANCHOR_X - 4, 2 * ANCHOR_Y - 3
SPECIES_KEY = "33"
MAX_PARTS = 8


def load_sheet() -> tuple[Image.Image, np.ndarray]:
    img = Image.open(SHEET).convert("RGB")
    arr = np.array(img).astype(int)
    mask = arr.sum(axis=2) > 45
    rgba = img.copy()
    rgba.putalpha(Image.fromarray((mask * 255).astype("uint8")))
    return rgba, mask


def native(rgba: Image.Image, box: tuple[int, int, int, int],
           at: tuple[int, int]) -> tuple[Image.Image, int, int]:
    """Crop a 2x part at an even origin, halve it, return offset from anchor."""
    y, x, w, h = box
    sx, sy = x - (x % 2), y - (y % 2)
    w2, h2 = w + (w % 2), h + (h % 2)
    img = rgba.crop((sx, sy, sx + w2, sy + h2)).resize((w2 // 2, h2 // 2),
                                                       Image.NEAREST)
    fx = at[0] - (x - sx)
    fy = at[1] - (y - sy)
    return img, int(round((fx - FRAME_2X_X) / 2)), int(round((fy - FRAME_2X_Y) / 2))


def place(m: np.ndarray, ox: int, oy: int, shape) -> np.ndarray:
    out = np.zeros(shape, bool)
    h, w = m.shape
    out[oy:oy + h, ox:ox + w] = m[:shape[0] - oy, :shape[1] - ox]
    return out


def reference_frame() -> np.ndarray:
    gif = Image.open(GIF)
    gif.seek(0)
    return np.array(gif.convert("RGB")).astype(int).sum(axis=2) > 45


def build_parts(out_dir: Path) -> tuple[dict, dict]:
    rgba, mask = load_sheet()
    parts: dict[str, dict] = {}
    images: dict[str, Image.Image] = {}

    def add(name: str, box, at) -> None:
        img, dx, dy = native(rgba, box, at)
        images[name] = img
        parts[name] = {"texture": f"somulo_{name}.png", "dx": dx, "dy": dy}

    add("body", BODY, BODY_AT)
    for name, box in HEADS.items():
        at = HEAD_AT.get(name)
        if at is None:
            cut = NECK_CUT[name]
            at = (int(round(SOCKET[0] - cut[0])), int(round(SOCKET[1] - cut[1])))
        add(f"head_{name}", box, at)

    # defeated body: a complete collapsed creature, anchored on the floor
    img, _, _ = native(rgba, DEFEATED, (0, 0))
    art = np.array(img)[..., 3] > 0
    ys, xs = np.nonzero(art)
    images["body_defeated"] = img
    parts["body_defeated"] = {
        "texture": "somulo_body_defeated.png",
        "dx": -int((xs.min() + xs.max() + 1) // 2),
        "dy": -int(ys.max() + 1),
    }

    # legs: reference frame minus body minus neutral head
    frame = reference_frame()
    body = mask[BODY[0]:BODY[0] + BODY[3], BODY[1]:BODY[1] + BODY[2]]
    head = mask[HEADS["neutral"][0]:HEADS["neutral"][0] + HEADS["neutral"][3],
                HEADS["neutral"][1]:HEADS["neutral"][1] + HEADS["neutral"][2]]
    covered = place(body, *BODY_AT, frame.shape) | \
        place(head, *HEAD_AT["neutral"], frame.shape)
    legs = frame & ~covered
    legs[:112] = False
    ys, xs = np.nonzero(legs)
    leg_box = (int(ys.min()), int(xs.min()),
               int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    img, dx, dy = native(rgba, leg_box, (int(xs.min()), int(ys.min())))
    images["legs"] = img
    parts["legs"] = {"texture": "somulo_legs.png", "dx": dx, "dy": dy}

    stats = {
        "body_stray": int((place(body, *BODY_AT, frame.shape) & ~frame).sum()),
        "head_stray": int((place(head, *HEAD_AT["neutral"], frame.shape) & ~frame).sum()),
        "legs_missing": int((frame & ~covered & ~legs).sum()),
        "legs_extra": int((legs & ~frame).sum()),
        "legs_px": int(legs.sum()),
    }
    for name, im in images.items():
        im.save(out_dir / f"somulo_{name}.png")
    return parts, stats


def parts_block(parts: dict) -> dict:
    states = {
        # head lowered to breathe fire, then the shot itself
        "1": {"head": "head_windup"},
        "2": {"head": "head_fire"},
        # the roar: widest jaw, head thrust forward
        "4": {"head": "head_roar"},
        # fainted / dying: the collapsed creature, no standing legs
        "5": {"body": "body_defeated", "legs": False, "head": None},
        "6": {"body": "body_defeated", "legs": False, "head": None},
    }
    block = dict(parts)
    block["states"] = states
    block["source"] = (
        "component atlas (SNES - Demon's Crest - Enemies & Bosses - Somulo.gif, "
        "2x) fitted against docs/reference/somulo_walk.gif; offsets are measured "
        "from the body/head mask fit and each head's neck cut, legs are the "
        "reference frame's own leg pixels; states not listed keep the baked "
        "walk frames")
    return block


def merge(block: dict, assets: Path) -> None:
    path = assets / "species_anim.json"
    doc = json.loads(path.read_text())
    entry = doc["species"].get(SPECIES_KEY)
    if entry is None:
        raise SystemExit(f"species {SPECIES_KEY} missing from {path}")
    entry["parts"] = block
    path.write_text(json.dumps(doc, indent=1))
    print(f"{path}: species {SPECIES_KEY} now carries "
          f"{len(block) - 2} part(s), {len(block['states'])} state override(s)")


def components(mask: np.ndarray) -> int:
    """Number of 8-connected blobs (1 means every part touches another)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    n = 0
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or seen[y, x]:
                continue
            n += 1
            stack = [(y, x)]
            seen[y, x] = True
            while stack:
                cy, cx = stack.pop()
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] \
                                and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
    return n


def verify(block: dict, out_dir: Path) -> int:
    """Render every composed state and check the parts actually join."""
    images = {k: Image.open(out_dir / v["texture"]).convert("RGBA")
              for k, v in block.items() if isinstance(v, dict) and "texture" in v}
    ok = True
    for state, sel in block["states"].items():
        body = sel.get("body", "body")
        canvas = Image.new("RGBA", (220, 110), (0, 0, 0, 0))
        drawn = []
        if sel.get("legs", True):
            drawn.append("legs")
        drawn.append(body)
        if sel.get("head"):
            drawn.append(sel["head"])
        masks = {}
        for name in drawn:
            im = images[name]
            at = (ANCHOR_X + block[name]["dx"], ANCHOR_Y + block[name]["dy"])
            canvas.alpha_composite(im, at)
            m = np.zeros((110, 220), bool)
            a = np.array(im)[..., 3] > 0
            h = min(a.shape[0], 110 - at[1])
            w = min(a.shape[1], 220 - at[0])
            m[at[1]:at[1] + h, at[0]:at[0] + w] = a[:h, :w]
            masks[name] = m
        canvas.save(out_dir / f"state_{state}.png")
        mask = np.array(canvas)[..., 3] > 0
        ys, xs = np.nonzero(mask)
        joints = {n: int((masks[n] & masks[body]).sum())
                  for n in drawn if n != body}
        print(f"  state {state}: {' + '.join(drawn)} bbox y {ys.min()}..{ys.max()} "
              f"x {xs.min()}..{xs.max()} (anchor {ANCHOR_X},{ANCHOR_Y}) "
              f"joint overlap {joints}")
        for name, px in joints.items():
            if px < 8:
                print(f"  FAIL: state {state}: {name} only overlaps the body "
                      f"by {px} px")
                ok = False
        if ys.max() != ANCHOR_Y - 1:
            print(f"  note: state {state} bottom row {ys.max()} "
                  f"(feet anchor is {ANCHOR_Y})")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--dry-run", action="store_true",
                    help="write the PNGs to --verify instead of the assets dir")
    ap.add_argument("--verify", type=Path, default=None,
                    help="render every composed state into this directory")
    args = ap.parse_args()

    out_dir = args.assets
    if args.dry_run:
        if not args.verify:
            print("--dry-run needs --verify DIR (where the PNGs go)",
                  file=sys.stderr)
            return 2
        out_dir = args.verify
    out_dir.mkdir(parents=True, exist_ok=True)

    parts, stats = build_parts(out_dir)
    for name, p in parts.items():
        print(f"  {p['texture']:28s} dx={p['dx']:4d} dy={p['dy']:4d}")
    print(f"  body fit: {stats['body_stray']} stray px, "
          f"head fit: {stats['head_stray']} stray px, "
          f"legs {stats['legs_px']} px (missing {stats['legs_missing']}, "
          f"extra {stats['legs_extra']})")

    block = parts_block(parts)
    if args.dry_run:
        print(json.dumps(block["states"], indent=1))
    else:
        merge(block, args.assets)
    if args.verify:
        return verify(block, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
