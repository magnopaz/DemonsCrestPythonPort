#!/usr/bin/env python3
"""Bake Firebrand animation frames from a capture_anim.py dump.

Input is the directory produced by `tools/oracle/capture_anim.py`: one JSON
state snapshot plus one VRAM image per guest frame, and `segments.json`
labelling the controller phases. Output is a set of PNGs and
`player_anim.json` consumed by the native engine.

The player is composed exactly like the static idle sprite in extract.py:
the palette-7 OAM group, on-screen sprites only, OBJ tiles from the OAM
palette. Frames are canonicalized to face right; the renderer mirrors them
for left-facing movement. Each frame records an anchor measured from the
player object's 24-bit X, so wings and projectiles do not shift the body
between poses.

The Y-shot pass also finds the moving fireball object in the first seven
$1080 slots and bakes its separate palette-6 OAM group as fireball_0..n.png
plus fireball_anim.json. The object-position window keeps the projectile out
of Firebrand's bbox even if a capture reuses the player palette.

Example:

  python3 tools/dc_extract/extract_anim.py \
    --dump captures/anim --out assets/generated
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract as dc  # noqa: E402

CLIP_NAMES = ["idle", "walk", "jump", "hover", "fall", "land", "attack",
              "spell"]

# Player projectile slots ($1080..$1260, stride $50, first 7 slots).
OBJECT_BASE = 0x1080
OBJECT_STRIDE = 0x50
OBJECT_SLOTS = 7
FIREBALL_SPECIES = 0x0040


class Pose:
    __slots__ = ("image", "hash", "anchor_x", "anchor_y", "parts",
                 "start", "duration")

    def __init__(self, image, digest, anchor_x, anchor_y, parts,
                 start, duration=1):
        self.image = image
        self.hash = digest
        self.anchor_x = anchor_x
        self.anchor_y = anchor_y
        self.parts = parts
        self.start = start
        self.duration = duration


def cgram_from_hex(text: str):
    raw = bytes.fromhex(text)
    if len(raw) != 0x200:
        raise SystemExit(f"expected 512-byte CGRAM, got {len(raw)}")
    words = struct.unpack("<256H", raw)
    return [((c & 31) * 8, ((c >> 5) & 31) * 8, ((c >> 10) & 31) * 8)
            for c in words]


def frame_paths(dump: Path, frame: int):
    stem = dump / f"f{frame:06d}"
    return stem.with_suffix(".json"), stem.with_suffix(".vram.bin")


def build_hud(dump: Path, meta: dict, out: Path):
    """Bake the BG3 status bar elements from the first idle capture frame.

    BG3 is 2bpp: map base from bgXsc[2], character base $5000, CGRAM palette
    groups of four colours. The full BG3 plane has a repeating brown backdrop;
    only the health bar and crest-slot group are emitted.
    """
    if not has_segment(meta, "idle"):
        return
    idle = segment_frames(meta, "idle")
    frame = idle[0]
    state = read_frame_state(dump, frame)
    if state is None:
        return
    _json_path, vram_path = frame_paths(dump, frame)
    if not vram_path.exists():
        return
    vram = dc.read_vram(vram_path)
    raw = struct.pack("<32768H", *vram)
    cgram = cgram_from_hex(state["cgram"])
    bgsc = int(state["ppu"]["bgXsc"][2], 16)
    map_base = (bgsc & 0xFC) << 8
    char_base = 0x5000

    image = Image.new("RGBA", (256, 224), (0, 0, 0, 0))
    px = image.load()
    for ty in range(28):
        for tx in range(32):
            word = vram[(map_base + ty * 32 + tx) & 0x7FFF]
            tile = word & 0x3FF
            pal = (word >> 10) & 7
            hf = bool(word & 0x4000)
            vf = bool(word & 0x8000)
            tile_word = char_base // 2 + tile * 8
            for y in range(8):
                b0 = raw[(tile_word + y) * 2]
                b1 = raw[(tile_word + y) * 2 + 1]
                for x in range(8):
                    p = ((b0 >> (7 - x)) & 1) | (((b1 >> (7 - x)) & 1) << 1)
                    if p == 0:
                        continue
                    sx = 7 - x if hf else x
                    sy = 7 - y if vf else y
                    px[tx * 8 + sx, ty * 8 + sy] = (*cgram[pal * 4 + p], 255)

    # save0 HUD geometry: six 8x8 health tiles at tile column 3, row 2;
    # three 2x2 crest slots at columns 18..29, rows 1..2.
    image.crop((24, 16, 72, 24)).save(out / "hud_bar.png")
    slots = image.crop((144, 8, 240, 24))
    sp = slots.load()
    for y in range(slots.height):
        for x in range(slots.width):
            r, g, b, a = sp[x, y]
            if a and r > 80 and g < r * 0.8 and b < g * 0.8:
                sp[x, y] = (0, 0, 0, 0)
    slots.save(out / "hud_slots.png")


def compose_player(dump: Path, frame: int, palette: int) -> Pose:
    json_path, vram_path = frame_paths(dump, frame)
    if not json_path.exists() or not vram_path.exists():
        raise FileNotFoundError(frame)
    state = json.loads(json_path.read_text())
    vram = dc.read_vram(vram_path)
    cgram = cgram_from_hex(state["cgram"])
    oam = bytes.fromhex(state["oam"]) + bytes.fromhex(state["highOam"])
    obsel = int(state["ppu"]["obsel"], 16)

    sprites = [s for s in dc.parse_oam(oam, obsel)
               if s.palette == 7 and s.y < 224]
    if not sprites:
        raise SystemExit(f"frame {frame}: no palette-7 player sprites")

    obj_base = (obsel & 7) << 13
    obj_vram = vram[obj_base:obj_base + 0x2000]
    index_img, ox, oy = dc.compose_oam_indices(obj_vram, sprites)
    colors = [cgram[0x80 + palette * 16 + i] for i in range(16)]
    image = dc.colorize(index_img, colors)
    image, ox, oy, bw, bh = dc.crop_sprite(image, ox, oy)

    # Canonical facing: the reference save starts facing right (OAM hflip
    # set). Mirror left-facing poses so one PNG works in both directions.
    hflipped = sum(1 for s in sprites if s.hflip) > len(sprites) / 2
    wram = bytes.fromhex(state["wram_1000"])
    object_x = (wram[0x30] | (wram[0x31] << 8) | (wram[0x32] << 16)) / 256.0
    body_screen_x = object_x - state["ppu"]["hScroll"][0]
    if hflipped:
        anchor_x = round(body_screen_x - ox)
        digest = hashlib.sha1(image.tobytes()).hexdigest()
    else:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        anchor_x = round(bw - (body_screen_x - ox))
        digest = hashlib.sha1(image.tobytes()).hexdigest()

    return Pose(image, digest, anchor_x, bh, len(sprites), frame)


def read_frame_state(dump: Path, frame: int):
    json_path, _vram_path = frame_paths(dump, frame)
    if not json_path.exists():
        return None
    return json.loads(json_path.read_text())


def wram_u16(wram: bytes, addr: int) -> int:
    off = addr - 0x1000
    return wram[off] | (wram[off + 1] << 8)


def wram_u24(wram: bytes, addr: int) -> int:
    off = addr - 0x1000
    return wram[off] | (wram[off + 1] << 8) | (wram[off + 2] << 16)


def projectile_slot(state: dict):
    """Return (world_x, world_y, vx) for the moving player fireball slot.

    The fireball is the active slot in $1080..$1260 with a non-zero
    horizontal velocity. Its sprite palette is separate from the player's
    (palette 6 vs 7 in save0), which keeps it out of the player bbox.
    """
    wram = bytes.fromhex(state["wram_1000"])
    player_x = wram_u24(wram, 0x1030) / 256.0
    player_y = wram_u24(wram, 0x1033) / 256.0
    fallback = None
    for i in range(OBJECT_SLOTS):
        base = OBJECT_BASE + i * OBJECT_STRIDE
        if wram_u16(wram, base) == 0:
            continue
        vx = wram_u16(wram, base + 0x20)
        if vx == 0:
            continue
        x = wram_u24(wram, base + 0x30) / 256.0
        y = wram_u24(wram, base + 0x33) / 256.0
        if abs(x - player_x) >= 64 or abs(y - player_y) >= 32:
            continue
        species = wram_u16(wram, base + 0x02)
        result = (x, y, vx, species)
        if species == FIREBALL_SPECIES:
            return result
        if fallback is None:
            fallback = result
    return fallback


def compose_projectile(dump: Path, frame: int, slot,
                       player_palette: int) -> Pose | None:
    """Compose the projectile OAM group around the fireball object position."""
    state = read_frame_state(dump, frame)
    if state is None:
        return None
    _json_path, vram_path = frame_paths(dump, frame)
    if not vram_path.exists():
        return None
    vram = dc.read_vram(vram_path)
    cgram = cgram_from_hex(state["cgram"])
    oam = bytes.fromhex(state["oam"]) + bytes.fromhex(state["highOam"])
    obsel = int(state["ppu"]["obsel"], 16)

    world_x, world_y, vx, _species = slot
    scroll_x = state["ppu"]["hScroll"][0]
    scroll_y = state["ppu"]["vScroll"][0]
    screen_x = world_x - scroll_x
    screen_y = world_y - scroll_y

    all_sprites = [s for s in dc.parse_oam(oam, obsel) if s.y < 224]
    # The stream extends mostly behind the head: ~25 px left and 5 px right
    # for a right-facing shot. Restrict to a 48x40 window around the object.
    near = [s for s in all_sprites
            if s.x < screen_x + 24 and s.x + s.size > screen_x - 40
            and s.y < screen_y + 20 and s.y + s.size > screen_y - 20]
    if not near:
        return None

    palettes = {}
    for s in near:
        if s.palette == player_palette:
            continue
        palettes[s.palette] = palettes.get(s.palette, 0) + 1
    if not palettes:
        return None
    palette = max(palettes, key=palettes.get)
    sprites = [s for s in near if s.palette == palette]
    if not sprites:
        return None

    obj_base = (obsel & 7) << 13
    obj_vram = vram[obj_base:obj_base + 0x2000]
    index_img, ox, oy = dc.compose_oam_indices(obj_vram, sprites)
    colors = [cgram[0x80 + palette * 16 + i] for i in range(16)]
    image = dc.colorize(index_img, colors)
    image, ox, oy, bw, _bh = dc.crop_sprite(image, ox, oy)

    anchor_x = round(screen_x - ox)
    anchor_y = round(screen_y - oy)
    hflipped = sum(1 for s in sprites if s.hflip) > len(sprites) / 2
    if not hflipped:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        anchor_x = round(bw - (screen_x - ox))
    digest = hashlib.sha1(image.tobytes()).hexdigest()
    return Pose(image, digest, anchor_x, anchor_y, len(sprites), frame)


def segment_frames(meta: dict, name: str):
    for seg in meta["segments"]:
        if seg["name"] == name:
            return range(seg["start"] + 1, seg["end"] + 1)
    raise SystemExit(f"capture has no segment named '{name}'")


def has_segment(meta: dict, name: str) -> bool:
    return any(seg["name"] == name for seg in meta["segments"])


def all_segment_frames(meta: dict, name: str):
    """Inclusive segment range; the press frame sits on the boundary."""
    for seg in meta["segments"]:
        if seg["name"] == name:
            return range(seg["start"], seg["end"] + 1)
    raise SystemExit(f"capture has no segment named '{name}'")


def build_shot_clip(meta: dict, dump: Path, palette: int,
                    idle_pose: Pose) -> list[Pose] | None:
    """Group the Y-shot player poses from the first spawned projectile.

    The press frame still shows the idle pose; the shot pose starts on the
    next guest frame and runs until the idle hash returns.
    """
    if not has_segment(meta, "shoot"):
        return None
    frames = list(all_segment_frames(meta, "shoot"))
    press = None
    for frame in frames:
        state = read_frame_state(dump, frame)
        if state is not None and projectile_slot(state):
            press = frame
            break
    if press is None:
        return None

    runs: list[Pose] = []
    for frame in range(press, frames[-1] + 1):
        try:
            pose = compose_player(dump, frame, palette)
        except FileNotFoundError:
            continue
        if frame > press and pose.hash == idle_pose.hash:
            break
        if runs and runs[-1].hash == pose.hash:
            runs[-1].duration += 1
        else:
            runs.append(pose)
    return runs or None


def build_projectile_poses(meta: dict, dump: Path,
                           player_palette: int) -> list[Pose]:
    """Compose every visible fireball frame at one step per guest frame."""
    if not has_segment(meta, "shoot"):
        return []
    poses: list[Pose] = []
    for frame in all_segment_frames(meta, "shoot"):
        state = read_frame_state(dump, frame)
        if state is None:
            continue
        slot = projectile_slot(state)
        if slot is None:
            continue
        pose = compose_projectile(dump, frame, slot, player_palette)
        if pose is not None:
            poses.append(pose)
    return poses


def pose_runs(meta: dict, dump: Path, name: str, palette: int) -> list[Pose]:
    runs: list[Pose] = []
    for frame in segment_frames(meta, name):
        try:
            pose = compose_player(dump, frame, palette)
        except FileNotFoundError:
            continue
        if runs and runs[-1].hash == pose.hash:
            runs[-1].duration += 1
        else:
            runs.append(pose)
    if not runs:
        raise SystemExit(f"segment '{name}' produced no player frames")
    return runs


def find_cycle(runs: list[Pose]):
    """Split a walk sequence into (pose cycle, steady-state timings).

    The first pose after starting to walk is an acceleration pose, and the
    final pose can be cut short by the stop segment. Look for two identical
    hash sequences and use the second one's durations.
    """
    for start in range(len(runs)):
        for length in range(3, min(9, (len(runs) - start) // 2 + 1)):
            a = [r.hash for r in runs[start:start + length]]
            b = [r.hash for r in runs[start + length:start + 2 * length]]
            if a == b:
                cycle = runs[start:start + length]
                timing = runs[start + length:start + 2 * length]
                return cycle, timing
    # Short walk: drop the acceleration pose and use what is left.
    return runs[1:], runs[1:]


def pick_clip(runs: list[Pose], count: int | None = None,
              offset: int = 0) -> list[Pose]:
    picked = runs[offset:offset + count] if count else runs[offset:]
    return picked or runs[:1]


def load_layout(path: Path | None):
    if path is None:
        return None
    return json.loads(path.read_text())


def build_clips(meta: dict, dump: Path, palette: int, layout: dict | None):
    if layout:
        # Optional override: {clip: {"segment": ..., "offset": ..., "count": ...,
        # "loop": ..., "max_parts": ..., "cycle": ...}}
        clips = {}
        for name in layout:
            spec = layout[name]
            runs = pose_runs(meta, dump, spec["segment"], palette)
            if spec.get("cycle"):
                cycle, timing = find_cycle(runs)
                for pose, timed in zip(cycle, timing):
                    pose.duration = timed.duration
                poses = cycle
            elif spec.get("max_parts"):
                poses = [max(runs, key=lambda p: p.parts)]
            else:
                poses = pick_clip(runs, spec.get("count"),
                                  spec.get("offset", 0))
            clips[name] = {"loop": bool(spec.get("loop", False)),
                           "poses": poses}
        return clips

    walk_runs = pose_runs(meta, dump, "walk_right", palette)
    walk_cycle, walk_timing = find_cycle(walk_runs)
    for pose, timed in zip(walk_cycle, walk_timing):
        pose.duration = timed.duration

    jump_runs = pose_runs(meta, dump, "jump_hold", palette)
    jump = pick_clip(jump_runs, 3)
    # The rise pose holds until the apex; the state machine switches to
    # hover/fall, so a short last-step duration is enough.
    if len(jump) >= 3:
        jump[0].duration = max(1, jump[0].duration)
        jump[1].duration = max(1, jump[1].duration)
        jump[2].duration = 1

    air_runs = pose_runs(meta, dump, "tap_air", palette)
    hover_pose = max(air_runs, key=lambda p: p.parts)
    hover_pose.duration = 1

    release_runs = pose_runs(meta, dump, "hover_release", palette)
    fall = pick_clip(release_runs, 2)
    land = pick_clip(release_runs, 2, offset=2) if len(release_runs) >= 4 \
        else release_runs[-1:]

    idle_runs = pose_runs(meta, dump, "idle", palette)
    idle = idle_runs[:1]
    idle[0].duration = 1

    spell_runs = None
    if has_segment(meta, "attack"):
        spell_runs = pose_runs(meta, dump, "attack", palette)

    shot_runs = build_shot_clip(meta, dump, palette, idle[0])

    clips = {
        "idle": {"loop": True, "poses": idle},
        "walk": {"loop": True, "poses": walk_cycle},
        "jump": {"loop": False, "poses": jump},
        "hover": {"loop": True, "poses": [hover_pose]},
        "fall": {"loop": False, "poses": fall},
        "land": {"loop": False, "poses": land},
    }
    if shot_runs:
        clips["attack"] = {"loop": False, "poses": shot_runs}
        if spell_runs:
            clips["spell"] = {"loop": False, "poses": spell_runs}
    elif spell_runs:
        # Older captures only have the A-button clip; keep it as attack.
        clips["attack"] = {"loop": False, "poses": spell_runs}
    return clips


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump", required=True, type=Path,
                    help="capture directory from capture_anim.py")
    ap.add_argument("--out", required=True, type=Path,
                    help="asset output directory (e.g. assets/generated)")
    ap.add_argument("--palette", type=int, default=7,
                    help="OBJ palette used by the player in this save (default 7)")
    ap.add_argument("--layout", type=Path,
                    help="optional JSON clip layout override")
    ap.add_argument("--clean", action="store_true",
                    help="remove existing player_* animation PNGs first")
    args = ap.parse_args()

    meta_path = args.dump / "segments.json"
    if not meta_path.exists():
        raise SystemExit(f"{meta_path} missing; run capture_anim.py first")
    meta = json.loads(meta_path.read_text())
    layout = load_layout(args.layout)
    clips = build_clips(meta, args.dump, args.palette, layout)

    args.out.mkdir(parents=True, exist_ok=True)
    if args.clean:
        for old in args.out.glob("player_*.png"):
            if old.name != "player_idle.png":
                old.unlink()
        for old in args.out.glob("fireball_*.png"):
            old.unlink()
        (args.out / "fireball_anim.json").unlink(missing_ok=True)
        for name in ("hud_bar.png", "hud_slots.png"):
            (args.out / name).unlink(missing_ok=True)

    document = {
        "source": "capture_anim.py",
        "capture_start": meta.get("start"),
        "capture_end": meta.get("end"),
        "palette": args.palette,
        "generated_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "clips": {},
    }
    total = 0
    for name in CLIP_NAMES:
        clip = clips.get(name)
        if not clip:
            continue
        steps = []
        for index, pose in enumerate(clip["poses"]):
            filename = f"player_{name}_{index}.png"
            pose.image.save(args.out / filename)
            steps.append({
                "texture": filename,
                "anchor_x": pose.anchor_x,
                "anchor_y": pose.anchor_y,
                "duration": max(1, pose.duration),
            })
        document["clips"][name] = {
            "loop": clip["loop"],
            "steps": steps,
        }
        durations = ", ".join(f'{s["duration"]}' for s in steps)
        print(f"{name:7s} {len(steps)} step(s)  durations [{durations}]")
        total += len(steps)

    (args.out / "player_anim.json").write_text(json.dumps(document, indent=1))
    print(f"wrote {args.out / 'player_anim.json'} ({total} steps)")

    projectile_poses = build_projectile_poses(meta, args.dump, args.palette)
    if projectile_poses:
        steps = []
        for index, pose in enumerate(projectile_poses):
            filename = f"fireball_{index}.png"
            pose.image.save(args.out / filename)
            steps.append({
                "texture": filename,
                "anchor_x": pose.anchor_x,
                "anchor_y": pose.anchor_y,
                "duration": 1,
            })
        projectile_doc = {
            "source": "capture_anim.py",
            "capture_start": meta.get("start"),
            "capture_end": meta.get("end"),
            "generated_utc": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "loop": True,
            "steps": steps,
        }
        (args.out / "fireball_anim.json").write_text(
            json.dumps(projectile_doc, indent=1))
        print(f"wrote {args.out / 'fireball_anim.json'} "
              f"({len(steps)} steps)")
    else:
        print("fireball: no projectile OAM found in the shoot segment")

    build_hud(args.dump, meta, args.out)
    if (args.out / "hud_bar.png").exists():
        print(f"wrote {args.out / 'hud_bar.png'} + hud_slots.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
