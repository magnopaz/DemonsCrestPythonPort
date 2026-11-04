"""Firebrand's movement state machine (port of player.c).

The authoritative position is 8.8 fixed point, exactly as in the C port; the
float x/y/vx/vy fields are the public view used by the camera and renderer.
"""

from __future__ import annotations

import math
import os

from . import consts as C
from .level import (level_break_block_at, level_floor_at, level_is_hazard_at,
                    level_is_slope_ramp_at, level_is_wall_at, level_is_water_at)
from .util import env, env_int, float_to_fx, fx_to_float, lround

PLAYER_HALF_W = 6.0
PLAYER_HEIGHT = 22.0

PLAYER_WALK_INITIAL_FX = 0x00B3
PLAYER_WALK_MAX_FX = 0x0166
PLAYER_WALK_WATER_FX = 0x0100
PLAYER_EARTH_DASH_FX = 0x0280
PLAYER_WALK_ACCEL_FX = 0x0003
PLAYER_GRAVITY_FX = 0x0038
PLAYER_GRAVITY_WATER_FX = 0x002A
PLAYER_JUMP_FX = 0x059C
PLAYER_JUMP_WATER_FX = 0x02CE
PLAYER_TERMINAL_FALL_FX = 0x0600
PLAYER_TERMINAL_FALL_WATER_FX = 0x0300
PLAYER_FLY_UP_FX = 0x0200
PLAYER_SHOT_FRAMES = 17
PLAYER_SPECIAL_FRAMES = 31

FX_ONE = 256

# Set by the first Player_Init that honours DC_START_X/Y; DC_START_ONCE uses it
# to keep the hook on the boot room only.
_start_hook_used = False

_FORM_NAMES = [
    "FIRE GARGOYLE",
    "EARTH GARGOYLE",
    "AERIAL GARGOYLE",
    "WATER GARGOYLE",
    "TIME GARGOYLE",
    "ULTIMATE GARGOYLE",
]


class Player:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.x_fx = 0
        self.y_fx = 0
        self.vy_fx = 0
        self.walk_speed_fx = 0
        self.on_ground = False
        self.on_slope = False
        self.underwater = False
        self.fly_enabled = False
        self.facing = 1
        self.prev_dir = 0
        self.jump_sub = 0
        self.state = C.PLAYER_IDLE
        self.anim_time = 0.0
        self.crest_form = C.CREST_BASE
        self.crests_mask = 0
        self.fire_element = 0
        self.active_talisman = 0
        self.talisman_mask = 0
        self.potions = 0
        self.scrolls = 0
        self.gold = 0
        self.wall_cling_dir = 0
        self.dash_timer = 0
        self.special_timer = 0
        self.shot_timer = 0
        self.land_timer = 0
        self.shot_fired = False
        self.hp = 0
        self.max_hp = 0
        self.invuln_timer = 0
        self.knockback_timer = 0
        self.knockback_dir = 0
        self.jump_started = False
        self.landed_event = False
        self.hurt_event = False
        self.block_broken_event = False
        self.anim_clip = -1
        self.anim_step = 0
        self.anim_timer = 0


def player_form_name(form: int) -> str:
    if form < 0 or form >= C.CREST_COUNT:
        return _FORM_NAMES[0]
    return _FORM_NAMES[form]


def player_cycle_form(player: Player, delta: int) -> None:
    mask = player.crests_mask if player.crests_mask else 0x3F
    cur = player.crest_form
    for _ in range(C.CREST_COUNT):
        cur = (cur + delta + C.CREST_COUNT) % C.CREST_COUNT
        if mask & (1 << cur):
            player.crest_form = cur
            break
    if player.crest_form == C.CREST_EARTH and \
            player.state in (C.PLAYER_HOVER, C.PLAYER_FLY,
                             C.PLAYER_WALL_CLING):
        player.state = C.PLAYER_JUMP
        player.jump_sub = 4


def _player_collides(level, x: float, y: float) -> bool:
    left = x - PLAYER_HALF_W
    right = x + PLAYER_HALF_W
    low = y - 3.0
    mid = y - PLAYER_HEIGHT * 0.5
    top = y - PLAYER_HEIGHT + 1.0
    return (level_is_wall_at(level, left, low) or
            level_is_wall_at(level, right, low) or
            level_is_wall_at(level, left, mid) or
            level_is_wall_at(level, right, mid) or
            level_is_wall_at(level, left, top) or
            level_is_wall_at(level, right, top))


def _ground_top(level, x: float, feet_y: float):
    return level_floor_at(level, x, feet_y)


def _sync_public(player: Player) -> None:
    player.x = fx_to_float(player.x_fx)
    player.y = fx_to_float(player.y_fx)
    player.vy = fx_to_float(player.vy_fx)


def _integrate_vertical(player: Player, level) -> None:
    grav = PLAYER_GRAVITY_WATER_FX if player.underwater else PLAYER_GRAVITY_FX
    term = PLAYER_TERMINAL_FALL_WATER_FX if player.underwater \
        else PLAYER_TERMINAL_FALL_FX
    player.vy_fx += grav
    if player.vy_fx > term:
        player.vy_fx = term
    if player.vy_fx < -PLAYER_TERMINAL_FALL_FX:
        player.vy_fx = -PLAYER_TERMINAL_FALL_FX

    old_y = player.y_fx
    player.y_fx += player.vy_fx
    _sync_public(player)

    if player.vy_fx > 0:
        surface = level_floor_at(level, player.x, player.y)
        if surface is not None and surface <= player.y:
            player.y_fx = float_to_fx(surface)
            player.vy_fx = 0
            player.on_ground = True
            player.jump_sub = 0
            player.landed_event = True
            _sync_public(player)
            return
    elif player.vy_fx < 0:
        if player.special_timer > 0 or player.dash_timer > 0:
            if level_break_block_at(level, player.x, player.y - PLAYER_HEIGHT):
                player.block_broken_event = True
        if _player_collides(level, player.x, player.y):
            player.y_fx = old_y
            player.vy_fx = 0
            _sync_public(player)
            return
    player.on_ground = False


def _move_horizontal(player: Player, level, direction: int,
                     speed_fx: int) -> None:
    old_x = fx_to_float(player.x_fx)
    if direction == 0:
        player.vx = 0.0
        return

    step = fx_to_float(speed_fx) * float(direction)
    target = old_x + step
    if not _player_collides(level, target, player.y):
        player.x_fx += direction * speed_fx
    else:
        reached = old_x
        dist = abs(step)
        d = 0.5
        while d <= dist:
            nx = old_x + math.copysign(d, step)
            if _player_collides(level, nx, player.y):
                break
            reached = nx
            d += 0.5
        player.x_fx = float_to_fx(reached)

    _sync_public(player)
    player.vx = fx_to_float(player.x_fx) - old_x


def _update_walk_speed(player: Player, direction: int,
                       prev_dir: int) -> None:
    if not player.on_slope:
        return
    if direction == 0:
        player.walk_speed_fx -= PLAYER_WALK_ACCEL_FX
        if player.walk_speed_fx < 0:
            player.walk_speed_fx = 0
        return
    if prev_dir == 0:
        player.walk_speed_fx = PLAYER_WALK_INITIAL_FX
    else:
        player.walk_speed_fx += PLAYER_WALK_ACCEL_FX
        if player.walk_speed_fx > PLAYER_WALK_MAX_FX:
            player.walk_speed_fx = PLAYER_WALK_MAX_FX


def _read_direction(inp) -> int:
    if inp.left and inp.right:
        return 1
    if inp.left:
        return -1
    if inp.right:
        return 1
    return 0


def _enter_jump(player: Player, level) -> None:
    player.on_ground = False
    player.wall_cling_dir = 0
    player.state = C.PLAYER_JUMP
    player.jump_sub = 0
    jv = PLAYER_JUMP_WATER_FX if player.underwater else PLAYER_JUMP_FX
    player.vy_fx = -jv
    player.walk_speed_fx = PLAYER_WALK_WATER_FX if player.underwater \
        else PLAYER_WALK_MAX_FX
    player.land_timer = 0
    player.jump_started = True
    _sync_public(player)


def _enter_hover(player: Player) -> None:
    if player.crest_form == C.CREST_EARTH:
        return
    player.state = C.PLAYER_HOVER
    player.wall_cling_dir = 0
    player.jump_sub = 0
    player.vy_fx = 0
    player.walk_speed_fx = PLAYER_WALK_MAX_FX
    _sync_public(player)


def player_init(player: Player, level) -> None:
    # C's Player_Init starts with memset(player, 0); Python reuses the object,
    # so stale vx/vy/timers would survive a room change.
    player.__dict__.update(Player().__dict__)
    demo = env("DC_DEMO")
    unlock_all = "DC_UNLOCK_ALL" in os.environ or demo == "11"
    player.x_fx = float_to_fx(level.spawn_x)
    player.y_fx = float_to_fx(level.spawn_y)
    # DC_START_X/Y are test hooks; by default they apply on every room load,
    # which teleports the player into the room a door just led to. Checkers
    # that only want to stand on a door set DC_START_ONCE=1 so the hook is
    # consumed by the boot room.
    global _start_hook_used
    start_x = env("DC_START_X")
    start_y = env("DC_START_Y")
    if _start_hook_used and "DC_START_ONCE" in os.environ:
        start_x = None
        start_y = None
    if start_x or start_y:
        _start_hook_used = True
    if start_x:
        player.x_fx = float_to_fx(float(start_x))
    if start_y:
        player.y_fx = float_to_fx(float(start_y))
    player.walk_speed_fx = PLAYER_WALK_MAX_FX
    player.facing = 1
    player.state = C.PLAYER_IDLE
    player.anim_clip = -1
    player.fly_enabled = "DC_FLY_DEBUG" in os.environ
    player.crest_form = C.CREST_BASE
    player.crests_mask = 0x3F if unlock_all else 0x01
    player.talisman_mask = 0x1F
    player.potions = 2
    player.scrolls = 1
    gold = env("DC_GOLD")
    if gold:
        player.gold = int(gold)
    potions = env("DC_POTIONS")
    if potions:
        player.potions = int(potions)
    scrolls = env("DC_SCROLLS")
    if scrolls:
        player.scrolls = int(scrolls)
    player.max_hp = 6
    player.hp = 4
    _sync_public(player)

    if player.x < level.play_min_x + 8.0:
        player.x_fx = float_to_fx(level.play_min_x + 8.0)
    if player.x > level.play_max_x - 8.0:
        player.x_fx = float_to_fx(level.play_max_x - 8.0)
    _sync_public(player)

    offsets = (0.0, 16.0, -16.0, 32.0, -32.0, 48.0, -48.0)
    found = False
    for attempt in range(12):
        if found:
            break
        base_x = fx_to_float(player.x_fx)
        base_y = fx_to_float(player.y_fx) - float(attempt // 2) * 16.0
        x = base_x + offsets[attempt % 7]
        y = base_y
        if x < level.play_min_x + 6.0 or x > level.play_max_x - 6.0:
            continue
        if _player_collides(level, x, y):
            continue
        player.x_fx = float_to_fx(x)
        player.y_fx = float_to_fx(y)
        _sync_public(player)
        found = True
    if not found:
        if _player_collides(level, player.x, player.y):
            cell = level.collision.cell * FX_ONE
            player.y_fx = (player.y_fx // cell) * cell
            _sync_public(player)

    top = _ground_top(level, player.x, player.y)
    if top is not None and player.y - 24.0 <= top <= player.y + 24.0:
        player.y_fx = float_to_fx(top)
        player.on_ground = True
        _sync_public(player)
    else:
        for dy in range(4, 97, 4):
            probe = player.y + float(dy)
            if player.x < level.play_min_x or player.x > level.play_max_x:
                break
            top = _ground_top(level, player.x, probe)
            if top is not None and player.y - 8.0 <= top <= probe + 4.0:
                player.y_fx = float_to_fx(top)
                player.on_ground = True
                _sync_public(player)
                break


def player_animate(player: Player, anim) -> None:
    if not anim.ready:
        return

    if player.hp <= 0:
        clip = C.ANIM_DIE
    elif player.knockback_timer > 0:
        clip = C.ANIM_HURT
    elif player.special_timer > 0:
        clip = C.ANIM_SPELL
    elif player.shot_timer > 0:
        clip = C.ANIM_ATTACK
    else:
        state = player.state
        if state in (C.PLAYER_WALK, C.PLAYER_HEADBUTT):
            clip = C.ANIM_WALK
        elif state == C.PLAYER_JUMP:
            clip = C.ANIM_JUMP if player.vy_fx < 0 else C.ANIM_FALL
        elif state == C.PLAYER_HOVER:
            clip = C.ANIM_HOVER
        elif state == C.PLAYER_FLY:
            clip = C.ANIM_FLYING if \
                anim.clips[C.ANIM_FLYING].step_count > 0 else C.ANIM_HOVER
        elif state == C.PLAYER_HURT:
            clip = C.ANIM_HURT
        elif state == C.PLAYER_DEAD:
            clip = C.ANIM_DIE
        elif state == C.PLAYER_WALL_CLING:
            clip = C.ANIM_JUMP
        elif state == C.PLAYER_LAND:
            clip = C.ANIM_LAND
        else:
            clip = C.ANIM_IDLE

    c = anim.clips[clip]
    if c.step_count <= 0:
        if clip == C.ANIM_SPELL and anim.clips[C.ANIM_ATTACK].step_count > 0:
            clip = C.ANIM_ATTACK
        elif clip == C.ANIM_FLYING and \
                anim.clips[C.ANIM_HOVER].step_count > 0:
            clip = C.ANIM_HOVER
        elif clip == C.ANIM_DIE:
            clip = C.ANIM_HURT if anim.clips[C.ANIM_HURT].step_count > 0 \
                else C.ANIM_IDLE
        elif clip == C.ANIM_HURT and \
                anim.clips[C.ANIM_IDLE].step_count > 0:
            clip = C.ANIM_IDLE
        else:
            clip = C.ANIM_IDLE
        c = anim.clips[clip]
    if not anim.ready or c.step_count <= 0:
        return

    if player.anim_clip != clip:
        player.anim_clip = clip
        player.anim_step = 0
        player.anim_timer = 0
    if c.step_count <= 1:
        player.anim_step = 0
        return

    if player.anim_step < 0:
        player.anim_step = 0
    if player.anim_step >= c.step_count:
        player.anim_step = c.step_count - 1

    step = anim.steps[c.first_step + player.anim_step]
    player.anim_timer += 1
    if player.anim_timer < step.duration:
        return
    player.anim_timer = 0
    player.anim_step += 1
    if player.anim_step >= c.step_count:
        if c.loop:
            player.anim_step = 0
        else:
            player.anim_step = c.step_count - 1


def player_update(player: Player, level, inp) -> None:
    player.shot_fired = False
    player.jump_started = False
    player.landed_event = False
    player.hurt_event = False
    player.block_broken_event = False

    if player.hp <= 0:
        player.state = C.PLAYER_DEAD
        player.vx = 0.0
        player.vy = 0.0
        return

    if inp.form_next_pressed:
        player_cycle_form(player, 1)

    if player.special_timer > 0:
        player.special_timer -= 1
    if player.shot_timer > 0:
        player.shot_timer -= 1
    if player.land_timer > 0:
        player.land_timer -= 1
    if player.invuln_timer > 0:
        player.invuln_timer -= 1
    if player.dash_timer > 0:
        player.dash_timer -= 1

    player.on_slope = player.on_ground and \
        level_is_slope_ramp_at(level, player.x, player.y + 1.0)
    player.underwater = \
        level_is_water_at(level, player.x, player.y - 8.0) or \
        ("DC_UNDERWATER" in os.environ)

    if player.invuln_timer == 0 and \
            (level_is_hazard_at(level, player.x, player.y) or
             level_is_hazard_at(level, player.x, player.y - 10.0)):
        if player.hp > 0:
            player.hp -= 1
        player.invuln_timer = 60
        player.knockback_timer = 8
        player.knockback_dir = -player.facing
        player.hurt_event = True

    if inp.special_pressed and player.special_timer == 0:
        player.special_timer = PLAYER_SPECIAL_FRAMES
        if player.on_ground and player.crest_form in (C.CREST_EARTH,
                                                     C.CREST_ULTIMATE):
            player.dash_timer = 18
            player.state = C.PLAYER_HEADBUTT
        elif not player.on_ground:
            if level_break_block_at(level, player.x,
                                    player.y - PLAYER_HEIGHT - 2.0):
                player.block_broken_event = True

    if inp.shot_pressed and player.shot_timer == 0:
        player.shot_timer = PLAYER_SHOT_FRAMES
        player.shot_fired = True

    can_free_fly = player.fly_enabled or \
        player.crest_form in (C.CREST_AIR, C.CREST_ULTIMATE)
    can_swim = player.underwater and \
        player.crest_form in (C.CREST_WATER, C.CREST_ULTIMATE)

    direction = _read_direction(inp)
    if player.knockback_timer > 0:
        player.knockback_timer -= 1
        direction = player.knockback_dir
        _move_horizontal(player, level, direction, 0x0200)
    elif player.dash_timer > 0:
        ahead_x = player.x + float(player.facing) * (PLAYER_HALF_W + 4.0)
        if level_break_block_at(level, ahead_x, player.y - 8.0) or \
                level_break_block_at(level, ahead_x, player.y - 18.0):
            player.block_broken_event = True
        _move_horizontal(player, level, player.facing, PLAYER_EARTH_DASH_FX)
    elif player.state == C.PLAYER_WALL_CLING:
        player.vx = 0.0
    else:
        if direction != 0:
            player.facing = direction
        if player.underwater and not can_swim:
            player.walk_speed_fx = PLAYER_WALK_WATER_FX
        elif not player.on_slope:
            player.walk_speed_fx = PLAYER_WALK_MAX_FX
        _update_walk_speed(player, direction, player.prev_dir)
        _move_horizontal(player, level, direction, player.walk_speed_fx)
    player.prev_dir = direction

    if can_swim:
        vdir = (1 if inp.down else 0) - (1 if inp.up else 0)
        player.vy_fx = vdir * 0x0180
        if vdir != 0:
            player.on_ground = False
            player.state = C.PLAYER_HOVER
            _integrate_vertical(player, level)
            _clamp_bounds(player, level)
            player.anim_time += 1.0 / 60.0
            return

    grounded_at_start = player.on_ground
    if grounded_at_start:
        top = _ground_top(level, player.x, player.y)
        supported = top is not None
        if supported and top > player.y + 6.0:
            supported = False
        if not supported:
            player.on_ground = False
            player.state = C.PLAYER_JUMP
            player.jump_sub = 4
            player.vy_fx = 0
            _integrate_vertical(player, level)
        else:
            player.y_fx = float_to_fx(top)
            player.vy_fx = 0
            _sync_public(player)
            if inp.jump_pressed:
                _enter_jump(player, level)
            elif player.dash_timer > 0:
                player.state = C.PLAYER_HEADBUTT
            elif direction != 0:
                player.state = C.PLAYER_WALK
            elif player.land_timer > 0:
                player.state = C.PLAYER_LAND
            else:
                player.state = C.PLAYER_IDLE
    else:
        if player.state == C.PLAYER_WALL_CLING:
            player.vy_fx += 0x0003
            if player.vy_fx > 0x00C0:
                player.vy_fx = 0x00C0
            old_y = player.y_fx
            player.y_fx += player.vy_fx
            _sync_public(player)
            if _player_collides(level, player.x, player.y):
                player.y_fx = old_y
                player.vy_fx = 0
                _sync_public(player)
            wall_x = player.x + float(player.wall_cling_dir) * (PLAYER_HALF_W + 1.0)
            if not level_is_wall_at(level, wall_x, player.y - 10.0):
                player.state = C.PLAYER_JUMP
                player.jump_sub = 4
                player.wall_cling_dir = 0
            elif inp.jump_pressed:
                player.facing = -player.wall_cling_dir
                _enter_jump(player, level)
            elif inp.down:
                player.state = C.PLAYER_JUMP
                player.jump_sub = 4
                player.wall_cling_dir = 0
        elif player.state in (C.PLAYER_HOVER, C.PLAYER_FLY):
            if inp.jump_pressed:
                player.state = C.PLAYER_JUMP
                player.jump_sub = 4
                player.vy_fx = 0
            elif can_free_fly and inp.up:
                player.state = C.PLAYER_FLY
                player.vy_fx = -PLAYER_FLY_UP_FX
                old_y = player.y_fx
                player.y_fx += player.vy_fx
                _sync_public(player)
                if _player_collides(level, player.x, player.y):
                    player.y_fx = old_y
                    player.vy_fx = 0
                    _sync_public(player)
            else:
                player.state = C.PLAYER_HOVER
        else:
            if player.jump_sub == 0:
                player.jump_sub = 2
                _integrate_vertical(player, level)
            elif player.jump_sub == 2:
                player.jump_sub = 4
                _integrate_vertical(player, level)
            elif player.jump_sub == 4 and inp.jump_pressed and \
                    player.crest_form != C.CREST_EARTH:
                _enter_hover(player)
            else:
                player.jump_sub = 4
                if player.vy_fx < 0 and not inp.jump_held:
                    player.vy_fx = 0
                _integrate_vertical(player, level)

            if not player.on_ground and player.vy_fx > 0 and direction != 0 and \
                    player.crest_form not in (C.CREST_EARTH, C.CREST_WATER):
                wall_x = player.x + float(direction) * (PLAYER_HALF_W + 1.0)
                if level_is_wall_at(level, wall_x, player.y - 10.0) and \
                        level_is_wall_at(level, wall_x, player.y - 28.0):
                    player.state = C.PLAYER_WALL_CLING
                    player.wall_cling_dir = direction
                    player.vy_fx = 0
                    _sync_public(player)

            if player.on_ground:
                player.state = C.PLAYER_LAND
                player.land_timer = 8
            elif player.state not in (C.PLAYER_HOVER, C.PLAYER_FLY,
                                      C.PLAYER_WALL_CLING):
                player.state = C.PLAYER_JUMP

    _clamp_bounds(player, level)
    _hold_player_hook(player)
    player.anim_time += 1.0 / 60.0


_hold_player = None
_hold_countdown = 0


def _hold_player_hook(player: Player) -> None:
    """DC_HOLD_PLAYER=x,y (DC_HOLD_AT=n): pin the player for arena checkers.

    The pit's eye AI probes the player's position, so a checker that wants the
    recorded fight's behaviour needs the player in the arena instead of idling
    at the room's lower-left spawn.
    """
    global _hold_player, _hold_countdown
    value = env("DC_HOLD_PLAYER")
    if not value:
        return
    if _hold_player is None:
        try:
            hx, hy = value.split(",")
            _hold_player = (float(hx), float(hy))
            _hold_countdown = int(env("DC_HOLD_AT") or 2)
        except ValueError:
            _hold_player = (0.0, 0.0)
            _hold_countdown = 2
    if _hold_countdown > 0:
        _hold_countdown -= 1
        return
    player.x_fx = float_to_fx(_hold_player[0])
    player.y_fx = float_to_fx(_hold_player[1])
    player.vx = 0.0
    player.vy = 0.0
    player.vx_fx = 0
    player.vy_fx = 0
    player.on_ground = True
    _sync_public(player)


def _clamp_bounds(player: Player, level) -> None:
    if player.x < level.play_min_x:
        player.x_fx = float_to_fx(level.play_min_x)
        player.vx = 0.0
    if player.x > level.play_max_x:
        player.x_fx = float_to_fx(level.play_max_x)
        player.vx = 0.0
    if player.y < level.play_min_y:
        player.y_fx = float_to_fx(level.play_min_y)
        player.vy_fx = 0
    if player.y > level.play_max_y:
        player.y_fx = float_to_fx(level.play_max_y)
        player.vy_fx = 0
        player.on_ground = True
    _sync_public(player)
