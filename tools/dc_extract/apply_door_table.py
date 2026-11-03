#!/usr/bin/env python3
"""Apply the save-observed door table to the generated room documents.

`extract.py` emits the ROM's own transition table, but for several rooms that
table is incomplete or points at a different chunk than the save recorded. The
regression suite's door checks spawn the player on the coordinate stored in the
level saves, so those rooms need the observed door as well.

Policy:

- extracted transitions are never modified or removed;
- an observed door is inserted at the **front** of ``transitions`` because
  ``Game_CheckTransitions()`` takes the first matching box, and the save is
  ground truth when it overlaps an extracted door;
- the trigger rectangle is derived from the source room document: the box is
  centred on the save coordinate and on the position ``Player_Init()`` actually
  moves the spawn to (it snaps the player out of solid tiles and onto the floor
  below), then padded, so a spawn exactly on the recorded point is inside it;
- doors written by this tool carry ``"source": "door_table"`` and are replaced
  on every run, which makes the tool idempotent and safe to re-run after a
  fresh ``extract.py``.

Usage:
  python3 tools/dc_extract/apply_door_table.py --rooms assets/generated
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

# (source area, saved player x, saved player y, destination area, provenance)
#
# The coordinates are the positions recorded in the level saves right before
# crossing the door; the destination is the area the save pair shows on the
# other side. The regression door checks assert these exact hops.
DOORS: tuple[tuple[int, float, float, int, str], ...] = (
    (2, 1706, 300, 4, "murkland cemetery before_door (save_lvl_I_room0)"),
    (0, 740, 190, 34, "murkland colosseum after-boss save; second arena chunk"),
    (8, 32, 664, 10, "ruined city dark avenue before_door"),
    (10, 1264, 104, 18, "ruined city reservoir before_door"),
    (20, 440, 144, 22, "dark forest thorn grove before_door"),
    (76, 226, 141, 78, "phalanx fortress western bell tower before_door"),
    (58, 224, 128, 60, "mountains ice crevasse before_door -> Grewon valley"),
)

PLAYER_HALF_W = 6.0
PLAYER_HEIGHT = 22.0


def surface_offset(attr: int, local_x: int) -> int:
    """Mirror of Level_SurfaceOffset ($80:962B) from src/level.c."""
    shape = attr & 0x1F
    lx = local_x & 15
    if shape in (0x01, 0x15, 0x16, 0x18, 0x19, 0x1A, 0x1B):
        return 0
    if shape in (0x02, 0x17):
        return 8
    slopes = {
        0x03: lambda: ((15 - lx) >> 1) + 8,
        0x04: lambda: (15 - lx) >> 1,
        0x05: lambda: lx >> 1,
        0x06: lambda: (lx >> 1) + 8,
        0x07: lambda: ((15 - lx) >> 2) + 12,
        0x08: lambda: ((15 - lx) >> 2) + 8,
        0x09: lambda: ((15 - lx) >> 2) + 4,
        0x0A: lambda: (15 - lx) >> 2,
        0x0B: lambda: lx >> 2,
        0x0C: lambda: (lx >> 2) + 4,
        0x0D: lambda: (lx >> 2) + 8,
        0x0E: lambda: (lx >> 2) + 12,
        0x0F: lambda: 15 - lx,
        0x10: lambda: lx,
        0x11: lambda: lx >> 1,
        0x12: lambda: (lx >> 1) + 8,
        0x13: lambda: (15 - lx) >> 1,
        0x14: lambda: ((15 - lx) >> 1) + 8,
    }
    fn = slopes.get(shape)
    return -1 if fn is None else fn()


class Room:
    """The collision queries Player_Init() needs, read from a room document."""

    def __init__(self, data: dict):
        col = data.get("collision") or {}
        self.data = data
        self.cell = int(col.get("cell") or 16)
        self.width = int(col.get("width") or 0)
        self.height = int(col.get("height") or 0)
        self.attrs = list(col.get("attrs") or [])
        self.world_w = int((data.get("world") or {}).get("width") or 256)
        self.world_h = int((data.get("world") or {}).get("height") or 256)
        play = data.get("play") or {}
        self.play_min_x = float(play.get("min_x", 6.0))
        self.play_max_x = float(play.get("max_x", self.world_w - 6.0))

    def attr_at(self, x: float, y: float) -> int:
        cx = math.floor(x / self.cell)
        cy = math.floor(y / self.cell)
        if cx < 0 or cy < 0 or cx >= self.width or cy >= self.height:
            return 0
        return self.attrs[cy * self.width + cx]

    def is_wall_at(self, x: float, y: float) -> bool:
        shape = self.attr_at(x, y) & 0x1F
        return shape in (0x01, 0x15, 0x1A, 0x02, 0x17)

    def collides(self, x: float, y: float) -> bool:
        left, right = x - PLAYER_HALF_W, x + PLAYER_HALF_W
        low = y - 3.0
        mid = y - PLAYER_HEIGHT * 0.5
        top = y - PLAYER_HEIGHT + 1.0
        return (self.is_wall_at(left, low) or self.is_wall_at(right, low) or
                self.is_wall_at(left, mid) or self.is_wall_at(right, mid) or
                self.is_wall_at(left, top) or self.is_wall_at(right, top))

    def floor_at(self, x: float, feet_y: float) -> float | None:
        cx = math.floor(x / self.cell)
        cy = math.floor(feet_y / self.cell)
        if cx < 0 or cy < 0 or cx >= self.width or cy >= self.height:
            return None
        offset = surface_offset(self.attrs[cy * self.width + cx],
                                math.floor(x) & (self.cell - 1))
        if offset < 0:
            return None
        return float(cy * self.cell + offset)

    def place_spawn(self, x: float, y: float) -> tuple[float, float]:
        """Mirror of the robust placement in Player_Init() (src/player.c)."""
        if x < self.play_min_x + 8.0:
            x = self.play_min_x + 8.0
        if x > self.play_max_x - 8.0:
            x = self.play_max_x - 8.0
        offsets = (0.0, 16.0, -16.0, 32.0, -32.0, 48.0, -48.0)
        found = False
        for attempt in range(12):
            base_x = x
            base_y = y - (attempt // 2) * 16.0
            nx = base_x + offsets[attempt % 7]
            if nx < self.play_min_x + 6.0 or nx > self.play_max_x - 6.0:
                continue
            if self.collides(nx, base_y):
                continue
            x, y = nx, base_y
            found = True
            break
        if not found and self.collides(x, y):
            y = math.floor(y / self.cell) * self.cell
        top = self.floor_at(x, y)
        if top is not None and top - 24.0 <= y <= top + 24.0:
            y = top
        else:
            for dy in range(4, 97, 4):
                probe = y + dy
                if x < self.play_min_x or x > self.play_max_x:
                    break
                top = self.floor_at(x, probe)
                if top is not None and y - 8.0 <= top <= probe + 4.0:
                    y = top
                    break
        return x, y


def trigger_box(room: Room, x: float, y: float) -> tuple[float, float, float, float]:
    """Return (cx, cy, half_w, half_h) covering the save point and the spawn.

    Player_Init() may move the spawn out of a solid tile and snap it to the
    floor, so the box has to cover both positions or the frame-1 check misses.
    """
    px, py = room.place_spawn(x, y)
    lo_x, hi_x = min(x, px), max(x, px)
    lo_y, hi_y = min(y, py), max(y, py)
    cx = (lo_x + hi_x) / 2.0
    cy = (lo_y + hi_y) / 2.0
    half_w = max(12.0, (hi_x - lo_x) / 2.0 + 12.0)
    half_h = max(40.0, (hi_y - lo_y) / 2.0 + 16.0)
    # Keep the rectangle inside the world; a door in a corner shrinks instead
    # of moving away from the saved point.
    half_w = min(half_w, max(1.0, min(cx, room.world_w - cx)))
    half_h = min(half_h, max(1.0, min(cy, room.world_h - cy)))
    return cx, cy, half_w, half_h


def apply(rooms: Path, dry_run: bool = False) -> int:
    applied = 0
    for src, x, y, dst, provenance in DOORS:
        path = rooms / f"room_area{src}.json"
        if not path.is_file():
            print(f"skip {src}->{dst}: {path} missing")
            continue
        data = json.loads(path.read_text())
        transitions = [tr for tr in data.get("transitions", [])
                       if tr.get("source") != "door_table"]
        room = Room(data)
        cx, cy, half_w, half_h = trigger_box(room, x, y)
        px, py = room.place_spawn(x, y)
        inside = (cx - half_w <= px <= cx + half_w and
                  cy - half_h <= py <= cy + half_h and
                  cx - half_w <= x <= cx + half_w and
                  cy - half_h <= y <= cy + half_h)
        if not inside:
            raise SystemExit(
                f"{src}->{dst}: trigger ({cx},{cy} +/- {half_w},{half_h}) "
                f"misses saved ({x},{y}) or placed ({px},{py})")
        if not (rooms / f"room_area{dst}.json").is_file():
            raise SystemExit(f"{src}->{dst}: destination room missing")
        transitions.insert(0, {
            "next_area": dst,
            "spawn_id": 0,
            "pad_mask": 255,
            "x": cx,
            "y": cy,
            "half_w": half_w,
            "half_h": half_h,
            "type": -2,
            "source": "door_table",
            "door": provenance,
        })
        data["transitions"] = transitions
        print(f"{src}->{dst}: saved ({x:g},{y:g}) placed ({px:g},{py:g}) "
              f"trigger c=({cx:g},{cy:g}) half=({half_w:g},{half_h:g})")
        if not dry_run:
            path.write_text(json.dumps(data))
        applied += 1
    print(f"door_table: {applied} observed door(s) "
          f"{'checked' if dry_run else 'written'}")
    return applied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rooms", type=Path, default=Path("assets/generated"))
    ap.add_argument("--dry-run", action="store_true",
                    help="report the doors without writing the room JSONs")
    args = ap.parse_args()
    apply(args.rooms, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
