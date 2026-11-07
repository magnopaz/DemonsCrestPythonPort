"""Room JSON loading and tile collision (port of level.c)."""

from __future__ import annotations

import math
import os

from . import rl
from .consts import LEVEL_OBJECT_TYPE_NAMES
from .util import eprint, as_float, as_int, env_int, file_exists, read_json

DC_MAX_LEVEL_OBJECTS = 64
DC_MAX_LEVEL_SPAWNS = 8
DC_MAX_LEVEL_TRANSITIONS = 16


class HdmaBand:
    __slots__ = ("lines", "factor")

    def __init__(self, lines=0, factor=1.0):
        self.lines = lines
        self.factor = factor


class BgLayer:
    __slots__ = ("name", "map_w", "map_h", "scroll_x", "scroll_y",
                 "hdma_bands", "tiles")

    def __init__(self):
        self.name = ""
        self.map_w = 0
        self.map_h = 0
        self.scroll_x = 0
        self.scroll_y = 0
        self.hdma_bands: list[HdmaBand] = []
        self.tiles: list[int] = []


class Collision:
    __slots__ = ("cell", "width", "height", "attrs")

    def __init__(self):
        self.cell = 16
        self.width = 0
        self.height = 0
        self.attrs = bytearray()


class StaticSprite:
    __slots__ = ("texture", "x", "y")

    def __init__(self):
        self.texture = rl.Texture2D()
        self.x = 0.0
        self.y = 0.0


class LevelObject:
    __slots__ = ("type", "species", "flags", "x", "y")

    def __init__(self):
        self.type = 0
        self.species = 0
        self.flags = 0
        self.x = 0.0
        self.y = 0.0


class LevelSpawn:
    __slots__ = ("x", "y", "flags")

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.flags = 0


class LevelTransition:
    __slots__ = ("next_area", "spawn_id", "pad_mask", "x", "y", "half_w",
                 "half_h", "type")

    def __init__(self):
        self.next_area = -1
        self.spawn_id = 0
        self.pad_mask = 0
        self.x = 0.0
        self.y = 0.0
        self.half_w = 12.0
        self.half_h = 24.0
        self.type = 0


class Level:
    def __init__(self):
        self.name = ""
        self.area_id = 1
        self.gate_next_area = -1
        self.gate_marker = 0
        self.gate_entry = 0
        self.music = -1
        self.bg_atlas_area = -1
        self.world_w = 0
        self.world_h = 0
        self.backdrop = rl.rgb(8, 8, 16)
        self.backdrop_parallax = 0.5
        self.backdrop_y = 0
        self.bg = [BgLayer(), BgLayer()]
        self.bg_count = 0
        self.collision = Collision()
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.camera_min_x = 0.0
        self.camera_max_x = 0.0
        self.camera_min_y = 0.0
        self.camera_max_y = 0.0
        self.spawn_x = 0.0
        self.spawn_y = 0.0
        self.spawns: list[LevelSpawn] = []
        self.transitions: list[LevelTransition] = []
        self.play_min_x = 0.0
        self.play_max_x = 0.0
        self.play_min_y = 0.0
        self.play_max_y = 0.0
        self.player_texture = rl.Texture2D()
        self.player_feet_x = 0.0
        self.player_feet_y = 0.0
        self.sprites: list[StaticSprite] = []
        self.objects: list[LevelObject] = []


def _read_bg_layer(layer: BgLayer, obj: dict) -> bool:
    name = obj.get("name")
    if isinstance(name, str):
        layer.name = name
    layer.map_w = as_int(obj.get("map_width"), -1)
    layer.map_h = as_int(obj.get("map_height"), -1)
    layer.scroll_x = as_int(obj.get("scroll_x"), 0)
    layer.scroll_y = as_int(obj.get("scroll_y"), 0)
    if layer.map_w < 0 or layer.map_h < 0:
        return False
    for band in (obj.get("hdma_bands") or [])[:8]:
        lines = as_int(band.get("lines"), 0) if isinstance(band, dict) else 0
        factor = as_float(band.get("factor"), 1.0) if isinstance(band, dict) else 1.0
        if lines > 0:
            layer.hdma_bands.append(HdmaBand(lines, factor))
    tiles = obj.get("tilemap")
    if not isinstance(tiles, list) or len(tiles) != layer.map_w * layer.map_h:
        eprint(f"level: {layer.name} tilemap size "
              f"{len(tiles) if isinstance(tiles, list) else 0} != "
              f"{layer.map_w * layer.map_h}", flush=True)
        return False
    layer.tiles = [int(v) for v in tiles]
    return True


def _read_collision(col: Collision, obj: dict) -> bool:
    col.cell = as_int(obj.get("cell"), -1)
    col.width = as_int(obj.get("width"), -1)
    col.height = as_int(obj.get("height"), -1)
    attrs = obj.get("attrs")
    if col.cell < 0 or col.width < 0 or col.height < 0:
        return False
    if not isinstance(attrs, list) or len(attrs) != col.width * col.height:
        eprint(f"level: collision size "
              f"{len(attrs) if isinstance(attrs, list) else 0} != "
              f"{col.width * col.height}", flush=True)
        return False
    col.attrs = bytearray(int(v) & 0xFF for v in attrs)
    return True


def _level_load_file(level: Level, assets, path: str) -> bool:
    # C's Level_LoadFile starts with memset(level, 0); without it a room change
    # appends the new room's objects/spawns/transitions to the old ones.
    level_unload(level)
    if not file_exists(path):
        eprint(f"level: cannot open {path}", flush=True)
        return False
    try:
        root = read_json(path)
    except (OSError, ValueError):
        eprint(f"level: {path} is not valid JSON", flush=True)
        return False

    world = root.get("world")
    camera = root.get("camera")
    spawn = root.get("spawn")
    player = root.get("player")
    collision = root.get("collision")
    bg = root.get("bg")
    play = root.get("play")
    if not all(isinstance(v, dict) for v in
               (world, camera, spawn, player, collision, play)) or \
            not isinstance(bg, list):
        eprint(f"level: failed to load {path}", flush=True)
        return False

    name = root.get("name")
    if isinstance(name, str):
        level.name = name
    level.area_id = as_int(root.get("area_id"), 1)
    level.gate_next_area = as_int(root.get("gate_next_area"), -1)
    level.gate_marker = as_int(root.get("gate_marker"), 0)
    level.gate_entry = as_int(root.get("gate_entry"), 0)
    # Authored fields (all optional): a room may override the track it plays
    # and may borrow another area's BG atlas when it is a new map.
    level.music = as_int(root.get("music"), -1)
    level.bg_atlas_area = as_int(root.get("bg_atlas_area"), level.area_id)
    backdrop = root.get("backdrop")
    if isinstance(backdrop, list) and len(backdrop) >= 3:
        rgb = [as_int(v, (8, 8, 16)[i]) for i, v in enumerate(backdrop[:3])]
        level.backdrop = rl.rgb(rgb[0], rgb[1], rgb[2])
    level.backdrop_parallax = max(0.0, as_float(root.get("backdrop_parallax"), 0.5))
    level.backdrop_y = as_int(root.get("backdrop_y"), 0)

    level.world_w = as_int(world.get("width"), -1)
    level.world_h = as_int(world.get("height"), -1)
    level.camera_x = as_float(camera.get("x"), 0.0)
    level.camera_y = as_float(camera.get("y"), 0.0)
    level.spawn_x = as_float(spawn.get("x"), 0.0)
    level.spawn_y = as_float(spawn.get("y"), 0.0)
    if level.world_w < 0 or level.world_h < 0:
        eprint(f"level: failed to load {path}", flush=True)
        return False

    for sp in (root.get("spawns") or [])[:DC_MAX_LEVEL_SPAWNS]:
        dst = LevelSpawn()
        if not isinstance(sp, dict) or "x" not in sp or "y" not in sp:
            continue
        dst.x = as_float(sp.get("x"))
        dst.y = as_float(sp.get("y"))
        dst.flags = as_int(sp.get("flags"), 0)
        level.spawns.append(dst)

    for tr in (root.get("transitions") or [])[:DC_MAX_LEVEL_TRANSITIONS]:
        dst = LevelTransition()
        if not isinstance(tr, dict):
            continue
        dst.next_area = as_int(tr.get("next_area"), -1)
        dst.spawn_id = as_int(tr.get("spawn_id"), 0)
        dst.pad_mask = as_int(tr.get("pad_mask"), 0)
        dst.x = as_float(tr.get("x"), 0.0)
        dst.y = as_float(tr.get("y"), 0.0)
        dst.half_w = as_float(tr.get("half_w"), 12.0)
        dst.half_h = as_float(tr.get("half_h"), 24.0)
        dst.type = as_int(tr.get("type"), 0)
        level.transitions.append(dst)

    max_cam_x = max(0.0, float(level.world_w) - 256.0)
    max_cam_y = max(0.0, float(level.world_h) - 224.0)
    level.camera_min_x = as_float(camera.get("min_x"), 0.0)
    level.camera_max_x = as_float(camera.get("max_x"), max_cam_x)
    level.camera_min_y = as_float(camera.get("min_y"), 0.0)
    level.camera_max_y = as_float(camera.get("max_y"), max_cam_y)

    level.play_min_x = as_float(play.get("min_x"), 6.0)
    level.play_max_x = as_float(play.get("max_x"), float(level.world_w) - 6.0)
    level.play_min_y = as_float(play.get("min_y"), 22.0)
    level.play_max_y = as_float(play.get("max_y"), float(level.world_h))

    level.player_texture = assets.player
    level.player_feet_x = as_float(player.get("feet_x"), -1.0)
    level.player_feet_y = as_float(player.get("feet_y"), -1.0)

    if not _read_collision(level.collision, collision):
        eprint(f"level: failed to load {path}", flush=True)
        return False

    if len(bg) != 2:
        eprint(f"level: expected 2 BG layers, got {len(bg)}", flush=True)
        eprint(f"level: failed to load {path}", flush=True)
        return False
    for i in range(2):
        if not _read_bg_layer(level.bg[i], bg[i]):
            eprint(f"level: failed to load {path}", flush=True)
            return False
    level.bg_count = 2

    for s in (root.get("sprites") or [])[:16]:
        if not isinstance(s, dict) or not isinstance(s.get("texture"), str):
            continue
        dst = StaticSprite()
        dst.texture = assets.item if "item" in s["texture"] else assets.player
        if "x" not in s or "y" not in s:
            continue
        dst.x = as_float(s.get("x"))
        dst.y = as_float(s.get("y"))
        level.sprites.append(dst)

    for o in (root.get("objects") or [])[:DC_MAX_LEVEL_OBJECTS]:
        if not isinstance(o, dict) or not isinstance(o.get("type"), str):
            continue
        kind = LEVEL_OBJECT_TYPE_NAMES.get(o["type"])
        if kind is None:
            continue
        dst = LevelObject()
        dst.type = kind
        if "x" not in o or "y" not in o:
            continue
        dst.x = as_float(o.get("x"))
        dst.y = as_float(o.get("y"))
        dst.species = as_int(o.get("species"), 0)
        dst.flags = as_int(o.get("flags"), 0)
        if "DC_DEBUG_OBJ" in os.environ:
            eprint(f"level: object {len(level.objects)} type {dst.type} "
                  f"species {dst.species} at {dst.x:.0f},{dst.y:.0f}",
                  flush=True)
        level.objects.append(dst)
    return True


def _authored_rooms_dir(directory: str) -> str:
    override = os.environ.get("DC_AUTHORED_ROOMS")
    if override:
        return override
    authored = os.environ.get("DC_AUTHORED_DIR")
    if authored:
        return os.path.join(authored, "rooms")
    return os.path.join(os.path.dirname(os.path.abspath(directory)),
                        "authored", "rooms")


def _load_room_with_override(level: Level, assets, directory: str,
                             name: str) -> bool:
    """Load ``name`` from the authored overlay first, then the ROM tree.

    The editor writes its rooms to ``assets/authored/rooms``; checking that
    directory here makes the game read the edited room without touching the
    generated tree.  A malformed authored file falls back to the generated one
    instead of leaving the level half-loaded.
    """
    authored = os.path.join(_authored_rooms_dir(directory), name)
    generated = os.path.join(directory, name)
    if file_exists(authored):
        if _level_load_file(level, assets, authored):
            return True
        eprint(f"level: authored room {authored} failed; using generated room",
              flush=True)
        level_unload(level)
    if file_exists(generated):
        return _level_load_file(level, assets, generated)
    return False


def level_load(level: Level, assets, directory: str) -> bool:
    area = env_int("DC_AREA")
    if area is not None:   # DC_AREA=0 is the colosseum, not "unset"
        if _load_room_with_override(level, assets, directory,
                                    f"room_area{area}.json"):
            return True
    return _load_room_with_override(level, assets, directory, "room.json")


def level_load_area(level: Level, assets, directory: str, area_id: int) -> bool:
    return _load_room_with_override(level, assets, directory,
                                    f"room_area{area_id}.json")


def level_unload(level: Level) -> None:
    level.__dict__.update(Level().__dict__)


def level_attr_at(level: Level, world_x: float, world_y: float) -> int:
    c = level.collision
    cx = math.floor(world_x / float(c.cell))
    cy = math.floor(world_y / float(c.cell))
    if cx < 0 or cy < 0 or cx >= c.width or cy >= c.height:
        return 0
    return c.attrs[cy * c.width + cx]


def level_is_solid_at(level: Level, world_x: float, world_y: float) -> bool:
    return (level_attr_at(level, world_x, world_y) & 0x1F) != 0


def level_surface_offset(attr: int, local_x: int) -> int:
    shape = attr & 0x1F
    local_x &= 15
    if shape in (0x01, 0x15, 0x16, 0x18, 0x19, 0x1A, 0x1B):
        return 0
    if shape in (0x02, 0x17):
        return 8
    if shape == 0x03:
        return ((15 - local_x) >> 1) + 8
    if shape == 0x04:
        return (15 - local_x) >> 1
    if shape == 0x05:
        return local_x >> 1
    if shape == 0x06:
        return (local_x >> 1) + 8
    if shape == 0x07:
        return ((15 - local_x) >> 2) + 12
    if shape == 0x08:
        return ((15 - local_x) >> 2) + 8
    if shape == 0x09:
        return ((15 - local_x) >> 2) + 4
    if shape == 0x0A:
        return (15 - local_x) >> 2
    if shape == 0x0B:
        return local_x >> 2
    if shape == 0x0C:
        return (local_x >> 2) + 4
    if shape == 0x0D:
        return (local_x >> 2) + 8
    if shape == 0x0E:
        return (local_x >> 2) + 12
    if shape == 0x0F:
        return 15 - local_x
    if shape == 0x10:
        return local_x
    if shape == 0x11:
        return local_x >> 1
    if shape == 0x12:
        return (local_x >> 1) + 8
    if shape == 0x13:
        return (15 - local_x) >> 1
    if shape == 0x14:
        return ((15 - local_x) >> 1) + 8
    return -1


def level_is_wall_at(level: Level, world_x: float, world_y: float) -> bool:
    shape = level_attr_at(level, world_x, world_y) & 0x1F
    return shape in (0x01, 0x15, 0x1A, 0x02, 0x17)


def level_env_flags_at(level: Level, world_x: float, world_y: float) -> int:
    return level_attr_at(level, world_x, world_y) & 0xE0


def level_is_hazard_at(level: Level, world_x: float, world_y: float) -> bool:
    return level_env_flags_at(level, world_x, world_y) == 0x20


def level_is_breakable_at(level: Level, world_x: float, world_y: float) -> bool:
    return level_env_flags_at(level, world_x, world_y) == 0x40


def level_break_block_at(level: Level, world_x: float, world_y: float) -> bool:
    c = level.collision
    cx = math.floor(world_x / float(c.cell))
    cy = math.floor(world_y / float(c.cell))
    if cx < 0 or cy < 0 or cx >= c.width or cy >= c.height:
        return False
    attr = c.attrs[cy * c.width + cx]
    if (attr & 0xE0) != 0x40:
        return False
    c.attrs[cy * c.width + cx] = 0
    if level.bg_count >= 2:
        bg1 = level.bg[1]
        for dy in range(2):
            for dx in range(2):
                tx = cx * 2 + dx
                ty = cy * 2 + dy
                if 0 <= tx < bg1.map_w and 0 <= ty < bg1.map_h:
                    bg1.tiles[ty * bg1.map_w + tx] = 0
    return True


def level_is_water_at(level: Level, world_x: float, world_y: float) -> bool:
    return level_env_flags_at(level, world_x, world_y) == 0x60


def level_is_slope_ramp_at(level: Level, world_x: float, world_y: float) -> bool:
    return level_env_flags_at(level, world_x, world_y) == 0x80


def level_floor_at(level: Level, world_x: float, feet_y: float):
    """Return the surface y under the feet, or None (C returns bool + out)."""
    c = level.collision
    cx = math.floor(world_x / float(c.cell))
    cy = math.floor(feet_y / float(c.cell))
    if cx < 0 or cy < 0 or cx >= c.width or cy >= c.height:
        return None
    attr = c.attrs[cy * c.width + cx]
    local_x = int(math.floor(world_x)) & (c.cell - 1)
    offset = level_surface_offset(attr, local_x)
    if offset < 0:
        return None
    return float(cy * c.cell + offset)
