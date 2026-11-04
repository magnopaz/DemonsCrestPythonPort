"""World rendering (port of render.c)."""

from __future__ import annotations

import math
import os

from . import rl
from .assets import (DC_BG_PALETTES, DC_SPECIES_STATES,
                     assets_area_bg, assets_area_bg2, assets_boss_sheet,
                     assets_has_area_bg2, assets_player_anim_for_form,
                     assets_species_sheet, species_part_index)
from .consts import (ANIM_CLIP_COUNT, CREST_AIR, CREST_EARTH, CREST_TIME,
                     CREST_ULTIMATE, CREST_WATER, LEVEL_OBJECT_DECOR,
                     LEVEL_OBJECT_INERT, LEVEL_OBJECT_UNKNOWN,
                     OBJECT_BOSS, OBJECT_CREST_ITEM,
                     OBJECT_ENEMY, OBJECT_ENEMY_SHOT, OBJECT_NPC, OBJECT_PICKUP,
                     OBJECT_PLATFORM, OBJECT_POOL_SIZE, OBJECT_TALISMAN,
                     OBJECT_URN)
from .util import eprint, env, env_int, lround

_WHITE = rl.rgb(255, 255, 255)

# Counters for the placeholder path: a room with a species the port has no
# handler for must still show that the record is there.  ``_placeholder_drawn``
# counts the boxes issued this frame, ``_placeholder_visible`` the ones inside
# the 256x224 viewport (what a screenshot can actually prove).
_placeholder_drawn = 0
_placeholder_visible = 0
_decor_drawn = 0
_decor_visible = 0
_decor_clock = 0


def placeholders_drawn() -> int:
    return _placeholder_drawn


def placeholders_visible() -> int:
    return _placeholder_visible


def decor_drawn() -> int:
    return _decor_drawn


def decor_visible() -> int:
    return _decor_visible


# Reused structs: raylib-python-cffi builds a fresh ffi struct (with weakref
# bookkeeping) for every Rectangle()/Vector2() call, which costs more than the
# draw itself at ~1800 tiles/frame. Mutating scratch structs is the same API
# with a fraction of the overhead.
_SRC = rl.Rectangle(0.0, 0.0, 8.0, 8.0)
_DST = rl.Rectangle(0.0, 0.0, 8.0, 8.0)
_ORIGIN = rl.Vector2(0.0, 0.0)


def _draw_layer_band(assets, layer, area_id, wrap_x, wrap_y, is_bg2,
                     origin_x, origin_y, y_min, y_max, bg1_map_w) -> None:
    tx0 = math.floor(origin_x / 8.0)
    ty0 = math.floor((origin_y + float(y_min)) / 8.0)
    tx1 = math.floor((origin_x + 256.0) / 8.0) + 1
    ty1 = math.floor((origin_y + float(y_max)) / 8.0) + 1

    map_h = layer.map_h
    map_w = layer.map_w
    tiles = layer.tiles

    use_bg2 = is_bg2 and assets_has_area_bg2(assets)
    if use_bg2:
        textures = [assets_area_bg2(assets, p) for p in range(DC_BG_PALETTES)]
    else:
        textures = [assets_area_bg(assets, area_id, p)
                    for p in range(DC_BG_PALETTES)]
    valid = [rl.IsTextureValid(t) for t in textures]
    src = _SRC
    dst = _DST
    origin = _ORIGIN
    draw = rl.DrawTexturePro

    for ty in range(ty0, ty1 + 1):
        map_ty = ty
        if wrap_y and map_h > 0:
            map_ty %= map_h
            if map_ty < 0:
                map_ty += map_h
        elif ty < 0 or ty >= map_h:
            continue
        dst_y = float(ty) * 8.0 - origin_y
        if dst_y + 8.0 <= float(y_min) or dst_y >= float(y_max):
            continue
        row = map_ty * map_w
        for tx in range(tx0, tx1 + 1):
            map_tx = tx
            if wrap_x:
                map_tx %= map_w
                if map_tx < 0:
                    map_tx += map_w
            elif tx < 0 or tx >= map_w:
                continue
            word = tiles[row + map_tx]
            tile = word & 0x3FF
            pal = (word >> 10) & 7
            if not valid[pal]:
                continue
            src.x = (256.0 if (word & 0x4000) else 0.0) + \
                float((tile % 32) * 8)
            src.y = (256.0 if (word & 0x8000) else 0.0) + \
                float((tile // 32) * 8)
            src.width = 8.0
            src.height = 8.0
            dst.x = float(tx) * 8.0 - origin_x
            dst.y = dst_y
            dst.width = 8.0
            dst.height = 8.0
            if dst.y < float(y_min):
                clip = float(y_min) - dst.y
                src.y += clip
                src.height -= clip
                dst.y = float(y_min)
                dst.height -= clip
            if dst.y + dst.height > float(y_max):
                clip = (dst.y + dst.height) - float(y_max)
                src.height -= clip
                dst.height -= clip
            if dst.height > 0.0:
                draw(textures[pal], src, dst, origin, 0.0, _WHITE)


def _draw_layer(assets, layer, level, camera, index: int) -> None:
    world_space = index == 1
    if world_space:
        offset_x = 0.0
        offset_y = 0.0
    else:
        offset_x = float(layer.scroll_x) - float(level.camera_x)
        offset_y = float(layer.scroll_y) - float(level.camera_y)
    wrap_x = layer.map_w < level.bg[1].map_w or index == 0
    wrap_y = index == 0 and level.world_h > 256
    origin_y = camera.y + offset_y
    if wrap_y and layer.map_h * 8 > 224:
        origin_y = math.fmod(camera.y * 0.5,
                             float(layer.map_h * 8 - 224))

    if layer.hdma_bands and "DC_NO_HDMA" not in os.environ:
        scan_y = 0
        cam_dx = camera.x - level.camera_x
        for band in layer.hdma_bands:
            if scan_y >= 224:
                break
            next_y = scan_y + band.lines
            if next_y > 224:
                next_y = 224
            band_x = float(layer.scroll_x) + cam_dx * band.factor
            _draw_layer_band(assets, layer, level.area_id, wrap_x, wrap_y,
                             index == 0, band_x, origin_y, scan_y, next_y,
                             level.bg[1].map_w)
            scan_y = next_y
        return

    origin_x = camera.x + offset_x
    _draw_layer_band(assets, layer, level.area_id, wrap_x, wrap_y, index == 0,
                     origin_x, origin_y, 0, 224, level.bg[1].map_w)


def _crest_tint(crest_form: int, invuln_timer: int):
    if invuln_timer > 0 and ((invuln_timer // 2) & 1):
        return rl.rgb(255, 160, 160, 180)
    if crest_form == CREST_EARTH:
        return rl.rgb(235, 195, 115)
    if crest_form == CREST_AIR:
        return rl.rgb(165, 225, 255)
    if crest_form == CREST_WATER:
        return rl.rgb(135, 240, 220)
    if crest_form == CREST_TIME:
        return rl.rgb(255, 235, 140)
    if crest_form == CREST_ULTIMATE:
        return rl.rgb(245, 175, 255)
    return rl.rgb(255, 255, 255)


def _draw_player(assets, level, camera, player) -> None:
    if "DC_NO_PLAYER" in os.environ:
        return
    anim = assets_player_anim_for_form(assets, player.crest_form)
    step = None
    if anim.ready and player.anim_clip >= 0:
        from .anim import anim_step
        step = anim_step(anim, player.anim_clip, player.anim_step)

    left = player.facing < 0
    if step is not None:
        texture = step.flipped if left else step.texture
        anchor_x = float(step.anchor_x)
        anchor_y = float(step.anchor_y)
    else:
        texture = assets.player_flipped if left else assets.player
        anchor_x = level.player_feet_x
        anchor_y = level.player_feet_y
    if left and texture.width > 0:
        anchor_x = float(texture.width) - anchor_x

    x = player.x - anchor_x - camera.x
    y = player.y - anchor_y - camera.y
    src = rl.Rectangle(0, 0, float(texture.width), float(texture.height))
    dst = rl.Rectangle(x, y, float(texture.width), float(texture.height))
    tint = _crest_tint(player.crest_form, player.invuln_timer)
    rl.DrawTexturePro(texture, src, dst, rl.Vector2(0, 0), 0.0, tint)


def _draw_projectiles(assets, camera, projectiles) -> None:
    if "DC_NO_PROJ" in os.environ:
        return
    anim = assets.projectile_anim
    if not anim.ready:
        return
    from .anim import projectile_anim_step
    for p in projectiles.slots:
        if not p.active or p.age <= 0:
            continue
        step = projectile_anim_step(anim, p.age - 1)
        if step is None:
            continue
        texture = step.flipped if p.vx_fx < 0 else step.texture
        anchor_x = float(step.anchor_x)
        if p.vx_fx < 0 and texture.width > 0:
            anchor_x = float(texture.width) - anchor_x
        x = p.x_fx / 256.0 - anchor_x - camera.x
        y = p.y_fx / 256.0 - float(step.anchor_y) - camera.y
        src = rl.Rectangle(0, 0, float(texture.width), float(texture.height))
        dst = rl.Rectangle(x, y, float(texture.width), float(texture.height))
        if p.element == 1:
            tint = rl.rgb(255, 220, 120)
        elif p.element == 2:
            tint = rl.rgb(140, 240, 150)
        elif p.element == 3:
            tint = rl.rgb(140, 220, 255)
        elif p.element == 4:
            tint = rl.rgb(235, 130, 255)
        else:
            tint = _WHITE
        rl.DrawTexturePro(texture, src, dst, rl.Vector2(0, 0), 0.0, tint)


def _species_frame_duration(sheet, frame: int) -> int:
    if frame < 0 or frame >= len(sheet.frames):
        return 6
    return sheet.frames[frame].duration if sheet.frames[frame].duration > 0 \
        else 6


def _species_cycle_frame(sheet, frames: list[int], timer: int) -> int:
    if not frames:
        return 0
    total = sum(_species_frame_duration(sheet, f) for f in frames)
    if total <= 0:
        return frames[0]
    t = timer % total
    if t < 0:
        t += total
    for f in frames:
        d = _species_frame_duration(sheet, f)
        if t < d:
            return f
        t -= d
    return frames[-1]


def _species_default_frame(sheet, timer: int) -> int:
    return _species_cycle_frame(sheet, list(range(len(sheet.frames))), timer)


# The boss banks use their `$05` byte as a byte offset into a state table, so a
# species sheet's five animation slots do not match the state numbers.  These
# maps turn the ROM state into the sheet's slot; `docs/ARMA_AI.md` has the
# per-state meaning.
_SPECIES_STATE_MAP = {
    # Arma: 0 entrance, 2 hover, 4 approach, 6 volley, 8 dive, 10 fall,
    # 12 turn, 14 rise, 24 flee.
    0xA5: {0: 0, 2: 0, 4: 0, 6: 1, 8: 2, 10: 2, 12: 3, 14: 3, 24: 4},
}


def species_state_slot(species: int, state: int) -> int:
    return _SPECIES_STATE_MAP.get(species, {}).get(state, state)


def _draw_species_first_pose(assets, species: int, x: float, y: float,
                             tint) -> bool:
    sheet = assets_species_sheet(assets, species)
    if sheet is None or not sheet.frames:
        return False
    sf = sheet.frames[0]
    if not rl.IsTextureValid(sf.texture):
        return False
    src = rl.Rectangle(0, 0, float(sf.texture.width), float(sf.texture.height))
    dst = rl.Rectangle(x - sf.anchor_x, y - sf.anchor_y,
                       float(sf.texture.width), float(sf.texture.height))
    rl.DrawTexturePro(sf.texture, src, dst, rl.Vector2(0, 0), 0.0, tint)
    return True


def _draw_species_part(part, x: float, y: float, mirrored: bool, tint) -> None:
    if not rl.IsTextureValid(part.texture):
        return
    tex = part.texture
    dx = float(part.dx)
    if mirrored and rl.IsTextureValid(part.flipped):
        tex = part.flipped
        dx = -float(part.dx + part.texture.width)
    src = rl.Rectangle(0, 0, float(tex.width), float(tex.height))
    dst = rl.Rectangle(x + dx, y + float(part.dy), float(tex.width),
                       float(tex.height))
    rl.DrawTexturePro(tex, src, dst, rl.Vector2(0, 0), 0.0, tint)


def _draw_species_parts(sheet, obj, x: float, y: float, tint) -> bool:
    parts = sheet.parts
    if not parts.enabled or obj.state < 0 or obj.state >= DC_SPECIES_STATES:
        return False
    sel = parts.states[obj.state]
    if not sel.present:
        return False
    mirrored = obj.facing < 0
    legs = species_part_index(parts, "legs") if sel.legs else -1
    if legs >= 0:
        _draw_species_part(parts.parts[legs], x, y, mirrored, tint)
    if 0 <= sel.body < len(parts.parts):
        _draw_species_part(parts.parts[sel.body], x, y, mirrored, tint)
    if 0 <= sel.head < len(parts.parts):
        _draw_species_part(parts.parts[sel.head], x, y, mirrored, tint)
    return True


def _species_tint(obj):
    if obj.hit_flash > 4:
        tint = rl.rgb(255, 255, 255)
    elif obj.hit_flash > 0:
        tint = rl.rgb(255, 200, 200)
    else:
        tint = rl.rgb(255, 255, 255)
    if obj.species == 0x13 and obj.hit_flash > 0:
        tint = rl.rgb(120, 255, 140)
    elif obj.type == OBJECT_BOSS and obj.species != 0x33 and obj.max_hp > 0 and \
            obj.hp < obj.max_hp:
        hurt = 1.0 - float(obj.hp) / float(obj.max_hp)
        hurt = min(1.0, max(0.0, hurt))
        tint = rl.rgb(255, int(255.0 - 90.0 * hurt), int(255.0 - 120.0 * hurt))
    return tint


def _draw_objects(assets, camera, objects) -> None:
    if "DC_NO_OBJ" in os.environ:
        return
    printed = [0]
    for o in objects.slots:
        if not o.active:
            continue
        x = o.x_fx / 256.0 - camera.x
        y = o.y_fx / 256.0 - camera.y

        if o.type == LEVEL_OBJECT_UNKNOWN:
            # Pooled species with a partial handler (the pit boss trio): keep
            # the debug box, but at the live position.
            rl.draw_rect_lines(lround(x - 6), lround(y - 12), 12, 12,
                               rl.rgb(255, 80, 220))
            rl.DrawRectangle(lround(x - 2), lround(y - 4), 4, 4,
                             rl.rgb(255, 200, 245))
            continue

        if o.type == OBJECT_ENEMY_SHOT:
            if o.species == 0x34 and \
                    (len(assets.boss_flame) if o.state == 1
                     else len(assets.boss_fireball)) > 0:
                if o.state == 1:
                    idx = (o.timer // 4) % 7
                    if idx >= len(assets.boss_flame):
                        idx = len(assets.boss_flame) - 1
                    fire = assets.boss_flame[idx]
                    src = rl.Rectangle(0, 0, float(fire.width),
                                       float(fire.height))
                    dst = rl.Rectangle(x - fire.width * 0.5,
                                       y - float(fire.height),
                                       float(fire.width), float(fire.height))
                    rl.DrawTexturePro(fire, src, dst, rl.Vector2(0, 0), 0.0,
                                      _WHITE)
                else:
                    idx = (o.timer // 4) % len(assets.boss_fireball)
                    fire = assets.boss_fireball[idx]
                    src = rl.Rectangle(0, 0, float(fire.width),
                                       float(fire.height))
                    dst = rl.Rectangle(x - fire.width * 0.5,
                                       y - fire.height * 0.5,
                                       float(fire.width), float(fire.height))
                    rl.DrawTexturePro(fire, src, dst, rl.Vector2(0, 0), 0.0,
                                      _WHITE)
            else:
                sheet = assets_species_sheet(assets, o.species)
                if sheet is not None and sheet.frames:
                    sf = sheet.frames[0]
                    src = rl.Rectangle(0, 0, float(sf.texture.width),
                                       float(sf.texture.height))
                    dst = rl.Rectangle(x - sf.anchor_x, y - sf.anchor_y,
                                       float(sf.texture.width),
                                       float(sf.texture.height))
                    rl.DrawTexturePro(sf.texture, src, dst, rl.Vector2(0, 0),
                                      0.0, rl.rgb(255, 220, 255))
                else:
                    rl.DrawCircleV(rl.Vector2(x, y), 5.0, rl.rgb(240, 160, 220))
                    rl.DrawCircleV(rl.Vector2(x, y), 2.0, _WHITE)
        elif o.type == OBJECT_URN:
            if not _draw_species_first_pose(assets, o.species, x, y, _WHITE):
                tex = assets.item
                rl.DrawTexture(tex, lround(x - tex.width * 0.5),
                               lround(y - tex.height * 0.5), _WHITE)
        elif o.type == OBJECT_PICKUP:
            tex = assets.heart
            rl.DrawTexture(tex, lround(x - tex.width * 0.5),
                           lround(y - tex.height), _WHITE)
        elif o.type == OBJECT_TALISMAN:
            tex = assets.item
            if o.species == 0:
                tint = rl.rgb(255, 230, 120)
            elif o.species == 1:
                tint = rl.rgb(210, 210, 230)
            elif o.species == 2:
                tint = rl.rgb(170, 200, 255)
            elif o.species == 3:
                tint = rl.rgb(255, 200, 160)
            else:
                tint = rl.rgb(190, 255, 190)
            rl.DrawTexture(tex, lround(x - tex.width * 0.5),
                           lround(y - tex.height), tint)
        elif o.type == OBJECT_CREST_ITEM:
            tint = rl.rgb(255, 240, 120) if (o.timer // 6) & 1 \
                else rl.rgb(180, 230, 255)
            if not _draw_species_first_pose(assets, o.species, x, y, tint):
                tex = assets.heart
                rl.DrawTexture(tex, lround(x - tex.width * 0.5),
                               lround(y - tex.height), tint)
        elif o.type == OBJECT_PLATFORM:
            px = lround(x) - 16
            py = lround(y)
            rl.DrawRectangle(px, py, 32, 6, rl.rgb(128, 120, 108))
            rl.draw_rect_lines(px, py, 32, 6, rl.rgb(200, 192, 168))
        elif o.type in (OBJECT_ENEMY, OBJECT_BOSS, OBJECT_NPC):
            if "DC_DEBUG_OBJ" in os.environ and printed[0] < 40 and \
                    -40 < x < 296 and -40 < y < 264:
                eprint(f"obj type={o.type} species={o.species:02X} "
                      f"screen=({x:.0f},{y:.0f}) state={o.state}", flush=True)
                printed[0] += 1
            sheet = assets_boss_sheet(assets, o.species, o.flags) \
                if o.type == OBJECT_BOSS else None
            if sheet is None:
                sheet = assets_species_sheet(assets, o.species)
            if sheet is not None and sheet.frames:
                tint = _species_tint(o)
                if _draw_species_parts(sheet, o, x, y, tint):
                    continue
                frame = _species_default_frame(sheet, o.timer)
                slot = species_state_slot(o.species, o.state)
                if o.hit_flash > 0 and sheet.has_hurt and \
                        sheet.hurt_frame < len(sheet.frames):
                    frame = sheet.hurt_frame
                elif sheet.has_states and 0 <= slot < DC_SPECIES_STATES and \
                        sheet.states[slot]:
                    idx = _species_cycle_frame(sheet, sheet.states[slot],
                                               o.timer)
                    if 0 <= idx < len(sheet.frames):
                        frame = idx
                elif sheet.has_default and \
                        sheet.default_frame < len(sheet.frames):
                    frame = sheet.default_frame
                sf = sheet.frames[frame]
                dx = x - sf.anchor_x
                dy = y - sf.anchor_y
                scale = 1.0
                if o.type == OBJECT_BOSS:
                    dx = x - sf.anchor_x * scale
                    dy = y - sf.anchor_y * scale
                mirrored = o.facing < 0 and rl.IsTextureValid(sf.flipped)
                tex = sf.flipped if mirrored else sf.texture
                if mirrored and sf.flipped.width > 0:
                    dx = x - (sf.flipped.width - sf.anchor_x) * scale
                    dy = y - sf.anchor_y * scale
                src = rl.Rectangle(0, 0, float(tex.width), float(tex.height))
                dst = rl.Rectangle(dx, dy, float(tex.width) * scale,
                                   float(tex.height) * scale)
                rl.DrawTexturePro(tex, src, dst, rl.Vector2(0, 0), 0.0, tint)
            else:
                shade = 60 + (o.species * 41) % 70
                body = rl.rgb(shade // 2 + 20, shade // 3 + 16, shade + 10)
                eye = rl.rgb(255, 226, 140)
                r = 5.0
                bh = 8.0
                feet = y
                cy = feet - bh - 4.0
                rl.DrawEllipse(lround(x - r * 0.45), lround(feet - 2.0),
                               lround(1.6), lround(2.4), body)
                rl.DrawEllipse(lround(x + r * 0.45), lround(feet - 2.0),
                               lround(1.6), lround(2.4), body)
                rl.DrawEllipse(lround(x), lround(cy), lround(r), lround(bh),
                               body)
                hy = cy - bh - 2.0
                rl.DrawCircleV(rl.Vector2(x, hy), 3.6, body)
                rl.DrawCircleV(rl.Vector2(x - 1.5, hy - 0.6), 1.0, eye)
                rl.DrawCircleV(rl.Vector2(x + 1.5, hy - 0.6), 1.0, eye)
                if o.type == OBJECT_BOSS:
                    hr = 3.6
                    rl.DrawTriangle(rl.Vector2(x - hr * 0.8, hy - hr * 0.7),
                                    rl.Vector2(x - hr * 1.4, hy - hr * 2.2),
                                    rl.Vector2(x - hr * 0.1, hy - hr * 1.1),
                                    body)
                    rl.DrawTriangle(rl.Vector2(x + hr * 0.8, hy - hr * 0.7),
                                    rl.Vector2(x + hr * 1.4, hy - hr * 2.2),
                                    rl.Vector2(x + hr * 0.1, hy - hr * 1.1),
                                    body)


def _draw_hud(assets, player) -> None:
    dot_r = 2
    step = 6
    y = 20
    x0 = 26
    full = rl.rgb(198, 99, 132)
    hollow = rl.rgb(99, 49, 16)
    rim = rl.rgb(18, 14, 22)
    max_dots = min(10, max(1, player.max_hp))
    for i in range(max_dots):
        cx = x0 + i * step
        on = i < player.hp
        rl.DrawCircle(cx, y, dot_r + 1.0, rim)
        rl.DrawCircle(cx, y, dot_r, full if on else hollow)
        if not on:
            rl.DrawCircle(cx, y, dot_r - 1.0, rl.rgb(24, 16, 57))

    if rl.IsTextureValid(assets.hud_slots):
        rl.DrawTexture(assets.hud_slots, 144, 8, _WHITE)
        slot_idx = player.crest_form % 3
        tint = _crest_tint(player.crest_form, 0)
        # Build a fresh Color: mutating a shared cdata tint would also dim
        # every later draw that reuses the same constant (raylib structs are
        # references, unlike C's by-value Color).
        slot_col = rl.rgb(tint.r, tint.g, tint.b, 235)
        rl.draw_rect_lines(144 + slot_idx * 32, 8, 32, 16, slot_col)


_fade = 0.0


def render_set_fade(alpha: float) -> None:
    global _fade
    _fade = alpha


def render_draw_fade() -> None:
    if _fade <= 0.0:
        return
    alpha = int(_fade * 255.0)
    rl.DrawRectangle(0, 0, 256, 224, rl.rgb(0, 0, 0, alpha))


_layer_mask = None


def render_game(assets, level, camera, player, projectiles, objects,
                show_hud: bool, debug_collision: bool) -> None:
    global _layer_mask
    if _layer_mask is None:
        masked = env_int("DC_LAYER_MASK")
        _layer_mask = masked if masked is not None else 0x3
    rl.ClearBackground(level.backdrop)

    if rl.IsTextureValid(assets.backdrop) and assets.backdrop_w > 0:
        parallax = level.backdrop_parallax
        off = -math.fmod(camera.x * parallax, float(assets.backdrop_w))
        if off > 0:
            off -= float(assets.backdrop_w)
        x = off
        while x < 256.0:
            rl.DrawTexture(assets.backdrop, lround(x), level.backdrop_y,
                           _WHITE)
            x += float(assets.backdrop_w)

    for i in range(level.bg_count):
        if not (_layer_mask & (1 << i)):
            continue
        _draw_layer(assets, level.bg[i], level, camera, i)

    for s in level.sprites:
        rl.DrawTexture(s.texture, int(s.x - camera.x), int(s.y - camera.y),
                       _WHITE)

    global _placeholder_drawn, _placeholder_visible
    global _decor_drawn, _decor_visible, _decor_clock
    _placeholder_drawn = 0
    _placeholder_visible = 0
    _decor_drawn = 0
    _decor_visible = 0
    _decor_clock += 1
    for index, o in enumerate(level.objects):
        if o.species in (0x69, 0x6B, 0x6C):
            # The pit boss trio is pooled by objects_init: the handler owns
            # the live position, so the static record is not drawn here.
            continue
        if o.type == LEVEL_OBJECT_INERT:
            # Retail-list records that draw nothing and are driven by a boss
            # script (species $9B): no sprite, no placeholder.
            continue
        if o.type == LEVEL_OBJECT_DECOR:
            # Decorative flicker (the cemetery's torch flames, $72): the ROM's
            # handler has no movement or contact damage, so it is drawn from
            # the species sheet and never enters the pool.
            sheet = assets_species_sheet(assets, o.species)
            if sheet is None or not sheet.frames:
                # No art yet: keep the debug box so the record stays visible.
                o_type = LEVEL_OBJECT_UNKNOWN
            else:
                px = lround(o.x - camera.x)
                py = lround(o.y - camera.y)
                _decor_drawn += 1
                if -16 < px < 272 and -16 < py < 240:
                    _decor_visible += 1
                frame = _species_default_frame(
                    sheet, _decor_clock + index * 7 + int(o.x))
                sf = sheet.frames[frame]
                tex = sf.texture if rl.IsTextureValid(sf.texture) else sf.flipped
                if rl.IsTextureValid(tex):
                    rl.DrawTexture(tex, lround(o.x - sf.anchor_x - camera.x),
                                   lround(o.y - sf.anchor_y - camera.y), _WHITE)
                continue
        else:
            o_type = o.type
        if o_type != LEVEL_OBJECT_UNKNOWN:
            continue
        # Species the port cannot animate yet.  Keep the ROM's position on
        # screen as a magenta box so a missing handler is visible instead of
        # silently absent; the object pool never sees these.
        if not (0.0 <= o.x < float(level.world_w) and
                0.0 <= o.y < float(level.world_h)):
            continue
        px = lround(o.x - camera.x)
        py = lround(o.y - camera.y)
        _placeholder_drawn += 1
        if -16 < px < 272 and -16 < py < 240:
            _placeholder_visible += 1
        rl.draw_rect_lines(px - 6, py - 12, 12, 12, rl.rgb(255, 80, 220))
        rl.DrawRectangle(px - 2, py - 4, 4, 4, rl.rgb(255, 200, 245))

    _draw_player(assets, level, camera, player)
    _draw_objects(assets, camera, objects)
    _draw_projectiles(assets, camera, projectiles)
    if show_hud:
        _draw_hud(assets, player)

    if debug_collision:
        c = level.collision
        cx0 = math.floor(camera.x / float(c.cell))
        cy0 = math.floor(camera.y / float(c.cell))
        cx1 = math.floor((camera.x + 256.0) / float(c.cell)) + 1
        cy1 = math.floor((camera.y + 224.0) / float(c.cell)) + 1
        for cy in range(cy0, cy1 + 1):
            for cx in range(cx0, cx1 + 1):
                if cx < 0 or cy < 0 or cx >= c.width or cy >= c.height:
                    continue
                if not (c.attrs[cy * c.width + cx] & 0x1F):
                    continue
                rl.draw_rect_lines(int(cx * c.cell - camera.x),
                                      int(cy * c.cell - camera.y),
                                      c.cell, c.cell, rl.rgb(40, 220, 80, 110))
        rl.draw_rect_lines(int(player.x - 6 - camera.x),
                              int(player.y - 22 - camera.y), 12, 22,
                              rl.rgb(255, 220, 40, 220))
        rl.DrawRectangle(0, 0, 256, 12, rl.rgb(0, 0, 0, 170))
        rl.DrawText(f"x={player.x:.0f} y={player.y:.0f} hp={player.hp}/"
                    f"{player.max_hp}  F1 collision".encode(),
                    3, 1, 10, rl.rgb(220, 220, 220))
