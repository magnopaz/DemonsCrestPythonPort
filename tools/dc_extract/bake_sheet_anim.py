#!/usr/bin/env python3
"""Bake labelled sprite-sheet animations into the authored overlay.

One spec per target (see ``SPECS`` below).  A spec names the sheet, the
species/form the entry belongs to, and the animation bands.  A band is either
measured by the library (a y range plus an optional x window, split on
background columns, one frame per drawing) or a list of manual boxes for rows
where a weapon arc or fire trail joins two poses.

Output layout::

    assets/authored/sprites/<target>/<target>_<index:02d>_<animation>.png

Every extraction gets its own subfolder, so a target can be cleared or
re-baked without touching another one.  Textures are stored relative to
``assets/authored`` as ``sprites/<target>/<file>.png`` and resolve through the
runtime's authored overlay (``dcpy/assets.py`` tries ``authored/<texture>``).

Enemy/boss specs merge into ``assets/authored/species_anim.json``; player
specs write one entry of ``player_forms.json`` (``form`` >= 1) or the base
``player_anim.json`` (``form`` 0).  Other entries are preserved.

Usage::

  python tools/dc_extract/bake_sheet_anim.py --list
  python tools/dc_extract/bake_sheet_anim.py --only belth
  python tools/dc_extract/bake_sheet_anim.py --only arma --contact
  python tools/dc_extract/bake_sheet_anim.py --all --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))

from sheet_lib import (analyse, contact_sheet, extract_pose,  # noqa: E402
                       largest_component_anchor)

AUTHORED = ROOT / "assets" / "authored"
SPRITES = AUTHORED / "sprites"
CAPTURES = ROOT / "captures"

MAX_FRAMES = 64
MAX_STATES = 16
MAX_STATE_FRAMES = 8
PLAYER_CLIPS = ("idle", "walk", "jump", "hover", "fall", "land", "attack",
                "spell", "flying", "hurt", "death")
LOOPING_CLIPS = {"idle", "walk", "hover", "flying"}

# ---------------------------------------------------------------------------
# Specs.  ``bands`` entries:
#   name        animation/state name
#   y           (y0, y1) row band, y1 exclusive
#   x           optional (x0, x1) window, x1 exclusive
#   boxes       optional explicit [(x0, y0, x1, y1), ...] instead of y/x
#   duration    ticks per frame (60 Hz); defaults by name
#   expect      optional exact frame count for the bake to self-check
# ---------------------------------------------------------------------------
SPECS: dict[str, dict] = {}


def _boss(target: str, sheet: str, key: str, species: int, bands: list,
          source: str, *, flags: int | None = None,
          variant: str | None = None) -> dict:
    return {"kind": "boss", "target": target, "sheet": sheet, "key": key,
            "species": species, "bands": bands, "source": source,
            "flags": flags, "variant": variant}


# -- Belth ($68), the completed reference case ------------------------------
SPECS["belth"] = _boss(
    "belth", "Belth", "68", 0x68,
    [
        {"name": "idle", "y": (25, 95), "x": (10, 228), "duration": 10,
         "expect": 3},
        {"name": "taunt", "y": (25, 95), "x": (225, 460), "duration": 10,
         "expect": 3},
        {"name": "walk", "y": (25, 95), "x": (475, 805), "duration": 8,
         "expect": 4},
        {"name": "attack", "y": (118, 228), "x": (0, 540), "duration": 8,
         "expect": 7},
        {"name": "jump", "y": (150, 228), "x": (545, 860), "duration": 8,
         "expect": 4},
        {"name": "charge", "duration": 8, "expect": 4, "boxes": [
            (23, 252, 113, 334), (118, 261, 208, 334),
            (214, 257, 283, 334), (289, 277, 406, 334)]},
        {"name": "turn", "y": (270, 348), "x": (530, 860), "duration": 8,
         "expect": 5},
        {"name": "hurt", "y": (350, 425), "x": (40, 140), "duration": 6,
         "expect": 1},
        {"name": "death", "duration": 10, "expect": 1,
         "boxes": [(660, 398, 725, 425)]},
    ],
    "Belth.gif: idle, taunt, walk, attack, jump, charge, turn, hurt, death "
    "rows (state names from the sheet captions)")


# -- Player sheets ----------------------------------------------------------
# The clip regions are the measured ones from ``bake_player_forms.py`` (they
# were verified against the captured base timing); import them so the numbers
# live in one place.  Player poses are split by connected component, not by
# empty columns, because wing tips touch across poses.
from bake_player_forms import (AERIAL, GROUND, LEGENDARY, NORMAL,  # noqa: E402
                               TIDAL, ULTIMATE)

# Form 0 (the base) is deliberately absent: ``player_anim.json`` is the
# ROM-captured sheet with the game's real cadence, and the labelled base sheet
# repeats it with extra effect drawings.  Re-baking it from the sheet would
# replace verified timing with guesses.
PLAYER_SHEETS = [
    ("player_ground", 1, "ground", "Firebrand (Ground)", GROUND),
    ("player_aerial", 2, "aerial", "Firebrand (Aerial)", AERIAL),
    ("player_tidal", 3, "tidal", "Firebrand (Tidal)", TIDAL),
    ("player_legendary", 4, "legendary", "Firebrand (Legendary)", LEGENDARY),
    ("player_ultimate", 5, "ultimate", "Firebrand (Ultimate)", ULTIMATE),
]


def _player_spec(target, form, name, sheet, regions) -> dict:
    bands = [{"name": clip, "x": (x0, x1), "y": (y0, y1),
              "split": "components"}
             for clip, (x0, x1, y0, y1) in regions.items()]
    return {"kind": "player", "target": target, "sheet": sheet, "form": form,
            "name": name, "bands": bands,
            "source": f"{sheet}.gif: measured per-clip regions "
                      f"(bake_player_forms.py), {len(bands)} clips"}


for _target, _form, _name, _sheet, _regions in PLAYER_SHEETS:
    SPECS[_target] = _player_spec(_target, _form, _name, _sheet, _regions)


# -- Arma ($A5) -------------------------------------------------------------
# The sheet labels the two fight sections with the same rows: Idle, Laughing,
# Intro in the first band; Flying; then Breath Attack / Divebomb; the rest of
# the sections are effects (projectiles, crests) and are not body frames.
_ARMA_BANDS = [
    {"name": "idle", "y": (57, 113), "x": (10, 145), "duration": 10},
    {"name": "laughing", "y": (57, 113), "x": (145, 258), "duration": 10},
    {"name": "intro", "y": (57, 113), "x": (258, 424), "duration": 8},
    {"name": "flying", "y": (126, 222), "x": (0, 424), "duration": 8},
    {"name": "breath", "duration": 8, "boxes": [
        (9, 268, 67, 318), (71, 267, 133, 318), (137, 268, 195, 318)]},
    {"name": "divebomb", "duration": 8, "boxes": [(254, 265, 304, 311)]},
]
_ARMA_F2_BANDS = [
    {"name": "idle", "y": (437, 493), "x": (10, 147), "duration": 10},
    {"name": "laughing", "y": (437, 493), "x": (147, 260), "duration": 10},
    {"name": "intro", "y": (437, 493), "x": (260, 424), "duration": 8},
    {"name": "flying", "y": (506, 602), "x": (0, 424), "duration": 8},
    {"name": "breath", "duration": 8, "boxes": [
        (11, 648, 68, 698), (73, 647, 134, 697), (139, 648, 196, 698)]},
    {"name": "divebomb", "duration": 8, "boxes": [(256, 645, 304, 690)]},
]
SPECS["arma"] = _boss(
    "arma", "Arma", "a5", 0xA5, _ARMA_BANDS,
    "Arma.gif first fight: Idle, Laughing, Intro, Flying, Breath Attack, "
    "Divebomb (captions on the sheet); effects/projectile rows skipped",
    variant="boss")
SPECS["arma_f2"] = _boss(
    "arma_f2", "Arma", "a5_f2", 0xA5, _ARMA_F2_BANDS,
    "Arma.gif second fight (green palette): same rows as the first fight",
    flags=2, variant="boss")
SPECS["arma_f4"] = _boss(
    "arma_f4", "Ultimate Arma", "a5_f4", 0xA5,
    [
        {"name": "idle", "y": (12, 84), "x": (10, 132), "duration": 10},
        {"name": "laughing", "y": (12, 84), "x": (132, 215), "duration": 10},
        {"name": "intro", "y": (12, 84), "x": (215, 419), "duration": 8},
        {"name": "flying", "y": (96, 192), "x": (0, 419), "duration": 8},
        {"name": "breath", "duration": 8, "boxes": [
            (6, 239, 64, 289), (68, 237, 130, 288), (134, 239, 192, 289)]},
        {"name": "divebomb", "duration": 8, "boxes": [(247, 236, 300, 280)]},
        {"name": "hurricane", "y": (305, 375), "x": (60, 360), "duration": 8},
        {"name": "demon_fire", "y": (395, 490), "x": (70, 380), "duration": 8},
    ],
    "Ultimate Arma.gif: Idle, Laughing, Intro, Flying, Breath Attack, "
    "Divebomb, Hurricane, Demon Fire (captions on the sheet)",
    flags=4, variant="boss")

# -- Crawler ($82) ----------------------------------------------------------
# The body is the whole creature in the "Moving" row; the head/claw parts have
# their own species ($83-$85) and are not baked here.
SPECS["crawler"] = _boss(
    "crawler", "Crawler", "82", 0x82,
    [{"name": "move", "y": (139, 229), "x": (0, 795), "duration": 8}],
    "Crawler.gif 'Moving' row, seven measured body poses")

# -- Dark Demon ($BC) -------------------------------------------------------
SPECS["dark_demon"] = _boss(
    "dark_demon", "Dark Demon", "bc", 0xBC,
    [{"name": "idle", "y": (44, 149), "x": (0, 410), "duration": 10},
     {"name": "attack", "y": (44, 149), "x": (410, 659), "duration": 8},
     {"name": "fallen_angel", "y": (196, 336), "x": (0, 659), "duration": 8}],
    "Dark Demon.gif: captions read Idle and Charge/Attack + Sin Rain over the "
    "top row, Fallen Angel Form over the second; the $8A effect rows and the "
    "credit block are skipped")

# -- Flame Lord ($58) -------------------------------------------------------
SPECS["flame_lord"] = _boss(
    "flame_lord", "Flame Lord", "58", 0x58,
    [{"name": "idle", "duration": 10, "boxes": [
        (329, 29, 377, 111), (382, 29, 427, 111),
        (432, 29, 476, 111), (482, 29, 528, 111)]}],
    "Flame Lord.gif 'Idle' group; the left of the row is the teleport flame, "
    "not the boss")

# -- Phalanx ($86) ----------------------------------------------------------
# First form: the idle/gesturing band.  The part rows (head, arms, serpent)
# are not whole poses and stay with their own entries.
SPECS["phalanx"] = _boss(
    "phalanx", "Phalanx", "86", 0x86,
    [{"name": "idle", "y": (211, 339), "x": (0, 687), "duration": 10}],
    "Phalanx.gif first form, 'Idle / Gesturing' band (measured body poses)")

# -- Ultimate Phalanx ($8D) -------------------------------------------------
SPECS["ultimate_phalanx"] = _boss(
    "ultimate_phalanx", "Ultimate Phalanx", "8d", 0x8D,
    [{"name": "idle", "duration": 10, "boxes": [
        (194, 429, 322, 628), (332, 429, 492, 628), (510, 429, 625, 628)]},
     {"name": "attack", "y": (429, 631), "x": (0, 160), "duration": 8}],
    "Ultimate Phalanx.gif 'Examples' assembled second form, plus the body "
    "pose row",
    flags=0, variant="boss")

# -- Grewon ($13) -----------------------------------------------------------
# Two identical palettes (green invincible variant is the same drawings).
SPECS["grewon"] = _boss(
    "grewon", "Grewon", "13", 0x13,
    [
        {"name": "idle", "y": (55, 100), "x": (0, 476), "duration": 10},
        {"name": "running", "y": (136, 193), "x": (0, 476), "duration": 8},
        {"name": "jump", "y": (217, 301), "x": (0, 476), "duration": 8,
         "min_w": 30, "max_w": 120},
        {"name": "breath", "y": (349, 394), "x": (0, 476), "duration": 8,
         "min_w": 40},
        {"name": "hurt", "y": (420, 484), "x": (0, 476), "duration": 6},
    ],
    "Grewon.gif first palette, captions: Intro/Idle, Running, Wall Jump / "
    "Jump / Turning Around, Breath Attack, Hit / Hurt + Defeated (the sheet "
    "repeats every row for the second palette)")

# -- Hipogriff ($09) --------------------------------------------------------
SPECS["hipogriff"] = _boss(
    "hipogriff", "Hipogriff", "09", 0x09,
    [
        {"name": "flying", "y": (103, 204), "x": (0, 785), "duration": 10,
         "max_w": 100, "min_w": 30, "min_h": 30},
        {"name": "flying_b", "y": (222, 323), "x": (0, 785), "duration": 8,
         "max_w": 100, "min_w": 30, "min_h": 30},
        {"name": "charge", "y": (339, 440), "x": (0, 785), "duration": 8,
         "max_w": 100, "min_w": 30, "min_h": 30},
    ],
    "Hipogriff.gif: caption says Flying over the first row and Charge / "
    "Feather Attack / Hurt Palate over the third; the middle row is the second "
    "palette set of the flight art. Statue pose and credits skipped.")


# -- Ovnunu ($16) -----------------------------------------------------------
# $16 is the eye.  The top row is the eye cycle (32x32 poses); the three
# full eyeball/tentacle drawings on the y=295 row are the whole-body examples
# that were the only art before.
SPECS["ovnunu"] = _boss(
    "ovnunu", "Ovnunu", "16", 0x16,
    [{"name": "eye", "y": (26, 59), "x": (30, 300), "duration": 10,
      "min_w": 28, "min_h": 28, "max_w": 40},
     {"name": "body", "duration": 10, "boxes": [
         (25, 295, 61, 361), (65, 294, 100, 361), (105, 295, 142, 361)]}],
    "Ovnunu.gif: top eye cycle (32x32) plus the full eyeball examples")

# -- Scula ($7B / $7C) ------------------------------------------------------
# Two objects at the same arena position.  $7B uses the walking row, $7C the
# hovering row; both rows are clean full bodies, unlike the part rows.
SPECS["scula_7b"] = _boss(
    "scula_7b", "Scula", "7b", 0x7B,
    [{"name": "walk", "duration": 8, "boxes": [
        (126, 267, 214, 337), (220, 268, 308, 337), (312, 267, 400, 337),
        (406, 265, 494, 337), (500, 269, 588, 337)]}],
    "Scula.gif walking row (y=265) full bodies")
SPECS["scula_7c"] = _boss(
    "scula_7c", "Scula", "7c", 0x7C,
    [{"name": "hover", "duration": 8, "boxes": [
        (12, 154, 100, 226), (106, 154, 183, 226), (189, 155, 270, 226),
        (370, 152, 451, 225), (457, 154, 544, 226)]}],
    "Scula.gif hovering row (y=154) full bodies")


def default_duration(name: str) -> int:
    if name in ("idle", "taunt", "hover", "flying", "fly"):
        return 10
    if name in ("hurt", "death"):
        return 6
    return 8


def poses_for(info, band: dict) -> list[tuple[int, int, int, int]]:
    """Measured pose boxes for a band (manual boxes win)."""
    if band.get("boxes"):
        return [tuple(int(v) for v in box) for box in band["boxes"]]
    y0, y1 = band["y"]
    x0, x1 = band.get("x", (0, info.image.width))
    if band.get("split") == "components":
        boxes = _component_boxes(info, x0, x1, y0, y1)
    else:
        boxes = [p.box for p in _band_poses(info, y0, y1, x0, x1)]
    # Specks (sparks, dust, caption debris) are not poses; neither are the
    # over-wide boxes produced where two drawings touch.
    min_w = band.get("min_w", 12)
    min_h = band.get("min_h", 12)
    max_w = band.get("max_w", 10 ** 4)
    return [b for b in boxes
            if b[2] - b[0] >= min_w and b[3] - b[1] >= min_h
            and b[2] - b[0] <= max_w]


def _component_boxes(info, x0: int, x1: int, y0: int, y1: int):
    """Pose boxes from connected components inside a region.

    Player sheets pack the drawings of one clip closely and some poses touch
    their neighbour's wing tip, so a column split merges them; one body per
    connected component is the rule the previous player baker proved.
    """
    boxes = []
    for c in info.components:
        if c.area < 40 or c.height < 16:
            continue
        if c.x0 < x0 - 2 or c.x1 + 1 > x1 + 2:
            continue
        if c.y0 < y0 - 2 or c.y1 + 1 > y1 + 2:
            continue
        boxes.append(c.box)
    boxes.sort(key=lambda b: (b[0], b[1]))
    return boxes


def foot_anchor_x(img: Image.Image) -> int:
    """Feet centre from the opaque pixels in the lower part of the pose."""
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


def clip_durations(clip: str, count: int) -> list[int]:
    """Frame cadence per clip, following the captured base sheet timing."""
    patterns = {
        "walk": [7, 7, 9, 7, 7, 9],
        "jump": [1, 2, 2, 1],
        "fall": [3, 2, 3, 2],
        "land": [3, 5],
        "attack": [1, 6, 10],
    }
    pattern = patterns.get(clip, [8])
    if count <= 0:
        return []
    return [pattern[i % len(pattern)] for i in range(count)]


def _band_poses(info, y0: int, y1: int, x0: int, x1: int):
    """:class:`sheet_lib.Pose` list for a y/x window, reusing the library."""
    from sheet_lib import Pose, _column_runs, is_bg
    im, bg = info.image, info.bg
    poses = []
    for rx0, rx1 in _column_runs(im, bg, y0, y1, x0, x1 - 1):
        ys = [y for y in range(y0, y1)
              if any(not is_bg(im.getpixel((x, y)), bg)
                     for x in range(rx0, rx1 + 1))]
        if ys:
            poses.append(Pose(rx0, rx1, min(ys), max(ys)))
    return poses


def bake_target(spec: dict, *, dry_run: bool = False,
                contact: bool = False, sheet_override: Path | None = None
                ) -> dict:
    info = analyse(sheet_override or spec["sheet"])
    target = spec["target"]
    out_dir = SPRITES / target
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        for stale in out_dir.glob(f"{target}_*.png"):
            stale.unlink()

    frames: list[dict] = []
    states: dict[str, list[int]] = {}
    names: dict[str, str] = {}
    problems: list[str] = []
    for band in spec["bands"]:
        name = band["name"]
        boxes = poses_for(info, band)
        indices: list[int] = []
        # Dedupe inside a band only: some sheets repeat a pose across rows on
        # purpose (a cycle returning to its rest pose), and dropping it would
        # shorten the animation.
        seen: dict[bytes, int] = {}
        for box in boxes:
            crop = extract_pose(info, box)
            if crop is None:
                problems.append(f"{name}: empty crop at {box}")
                continue
            key = crop.tobytes()
            if key in seen and not band.get("allow_duplicate"):
                problems.append(f"{name}: duplicate of frame {seen[key]} at "
                                f"{box}")
                continue
            if len(frames) >= MAX_FRAMES:
                problems.append(f"{name}: frame cap {MAX_FRAMES} reached")
                break
            seen[key] = len(frames)
            if spec["kind"] == "player":
                ax, ay = foot_anchor_x(crop), crop.height
            else:
                ax, ay = largest_component_anchor(crop)
            index = len(frames)
            tex = f"{target}_{index:02d}_{name}.png"
            if not dry_run:
                crop.save(out_dir / tex)
            frames.append({
                "texture": f"sprites/{target}/{tex}",
                "anchor_x": ax,
                "anchor_y": ay,
                "duration": band.get("duration", default_duration(name)),
                "width": crop.width,
                "height": crop.height,
            })
            indices.append(index)
        if band.get("expect") is not None and len(indices) != band["expect"]:
            problems.append(f"{name}: expected {band['expect']} frames, "
                            f"got {len(indices)}")
        if not indices:
            continue
        if len(indices) > MAX_STATE_FRAMES:
            problems.append(f"{name}: {len(indices)} frames > "
                            f"{MAX_STATE_FRAMES}/state, truncated")
            indices = indices[:MAX_STATE_FRAMES]
        states[str(len(states))] = indices
        names[str(len(states) - 1)] = name
        print(f"  {name:10s} {len(indices):2d} frames "
              f"[{indices[0]}..{indices[-1]}]")

    if dry_run:
        return {"frames": len(frames), "problems": problems, "states": states}

    if spec["kind"] == "boss":
        entry = {
            "species": spec["species"],
            "frames": frames,
            "states": states,
            "state_names": names,
            "hurt": next((i for n, i in ((nm, ind[0]) for nm, ind in
                                         zip(names.values(), states.values()))
                          if n == "hurt"), 0),
            "default": 0,
            "source": spec["source"],
        }
        if spec.get("flags") is not None:
            entry["flags"] = spec["flags"]
        if spec.get("variant"):
            entry["variant"] = spec["variant"]
        path = AUTHORED / "species_anim.json"
        root = json.loads(path.read_text()) if path.is_file() else {
            "species": {}}
        root.setdefault("species", {})[spec["key"]] = entry
        path.write_text(json.dumps(root, indent=1) + "\n")
    else:
        clips = {}
        for state_index, indices in states.items():
            name = names[state_index]
            durations = clip_durations(name, len(indices))
            steps = []
            for step, index in enumerate(indices):
                frame = frames[index]
                duration = durations[step] if step < len(durations) else \
                    default_duration(name)
                steps.append({"texture": frame["texture"],
                              "anchor_x": frame["anchor_x"],
                              "anchor_y": frame["anchor_y"],
                              "duration": max(1, duration)})
            clips[name] = {"loop": name in LOOPING_CLIPS, "steps": steps}
        if spec.get("form"):
            entry = {"form": spec["form"], "name": spec["name"],
                     "clips": clips, "source": spec["source"]}
            path = AUTHORED / "player_forms.json"
            root = json.loads(path.read_text()) if path.is_file() else {
                "forms": []}
            root["forms"] = [f for f in root.get("forms", [])
                             if f.get("form") != spec["form"]]
            root["forms"].append(entry)
            root["forms"].sort(key=lambda f: f.get("form", 0))
            path.write_text(json.dumps(root, indent=1) + "\n")
        else:
            path = AUTHORED / "player_anim.json"
            root = json.loads(path.read_text()) if path.is_file() else {}
            root["clips"] = clips
            root["source"] = spec["source"]
            path.write_text(json.dumps(root, indent=1) + "\n")

    files = sorted(out_dir.glob(f"{target}_*.png"))
    if contact and files:
        out = contact_sheet(files, CAPTURES / f"{target}_contact.png", cols=8)
        print(f"  contact sheet -> {out.relative_to(ROOT)}")
    return {"frames": len(frames), "problems": problems, "states": states,
            "files": files}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", action="append", default=None,
                    help="target name (repeatable)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--contact", action="store_true")
    ap.add_argument("--sheet", type=Path, default=None,
                    help="override the sheet path (single target only)")
    args = ap.parse_args()
    if args.list:
        for key, spec in sorted(SPECS.items()):
            print(f"{key:20s} {spec['kind']:6s} "
                  f"{len(spec['bands']):2d} bands  {spec['sheet']}")
        return 0
    targets = args.only or (sorted(SPECS) if args.all else [])
    if not targets:
        ap.error("pass --only <target>, --all or --list")
    if args.sheet and len(targets) != 1:
        ap.error("--sheet needs exactly one --only target")
    failed = 0
    for key in targets:
        spec = SPECS.get(key)
        if spec is None:
            print(f"bake_sheet_anim: unknown target {key!r}", file=sys.stderr)
            failed += 1
            continue
        print(f"== {key}: {spec['sheet']}")
        result = bake_target(spec, dry_run=args.dry_run,
                             contact=args.contact, sheet_override=args.sheet)
        print(f"   {result['frames']} frames, "
              f"{len(result['states'])} states")
        for problem in result["problems"]:
            print(f"   ! {problem}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
