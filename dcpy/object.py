"""Level object pool, spawn rules and per-species AI (port of object.c).

The pool keeps 26 reusable slots; ``events`` carries the one-frame flags the
audio/HUD layers consume, and the boss bookkeeping mirrors the C struct. All
positions are 8.8 fixed point, exactly like the native port, so every spawn,
hop, bob and projectile speed keeps the ROM's numbers.
"""

from __future__ import annotations

import math
import re

from .consts import (
    CREST_TIME, CREST_ULTIMATE, LEVEL_OBJECT_BOSS, LEVEL_OBJECT_ENEMY,
    LEVEL_OBJECT_NPC, LEVEL_OBJECT_PICKUP_CREST, LEVEL_OBJECT_PLATFORM,
    LEVEL_OBJECT_TALISMAN, LEVEL_OBJECT_UNKNOWN, LEVEL_OBJECT_URN,
    OBJECT_BOSS, OBJECT_CREST_ITEM,
    OBJECT_ENEMY, OBJECT_ENEMY_SHOT, OBJECT_EVENT_BOSS_DEFEATED,
    OBJECT_EVENT_BREAK, OBJECT_EVENT_CREST_PICKUP, OBJECT_EVENT_ENEMY_HIT,
    OBJECT_EVENT_FIRE_PIECE, OBJECT_EVENT_PICKUP, OBJECT_EVENT_TALISMAN,
    OBJECT_NONE, OBJECT_NPC, OBJECT_PICKUP, OBJECT_PLATFORM, OBJECT_POOL_SIZE,
    OBJECT_TALISMAN, OBJECT_URN,
)
from .level import level_floor_at, level_is_solid_at, level_is_wall_at
from .util import eprint, env, env_flag, float_to_fx, fx_to_float

FX_ONE = 256
HEART_POPUP_FX = 0x0400  # $85:C1D1 initial upward velocity 4.0
HEART_GRAVITY_FX = 0x0040  # $85:C1D1 gravity 0.25
HEART_BOUNCE_FX = 0x0400  # $85:C1D1 bounce decay 4.0 -> 3.0 ...
HEART_BOUNCE_STEP = 0x0100

URN_HALF = 8.0
HEART_HALF = 8.0

_ATOF_RE = re.compile(
    r"[ \t\n\r\v\f]*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")


class Object:
    """One pooled level object (C ``Object``)."""

    def __init__(self):
        self.active = False
        self.type = OBJECT_NONE
        self.species = 0
        self.flags = 0
        self.x_fx = 0
        self.y_fx = 0
        self.origin_x_fx = 0
        self.origin_y_fx = 0
        self.vx_fx = 0
        self.vy_fx = 0
        self.bounce_fx = 0  # $39: remaining bounce velocity for pickups
        self.state = 0
        self.substate = 0  # $06: per-species state machine substate
        self.phase = 0  # countdown for the current substate ($3B)
        self.hops = 0  # $38: hop counter inside a burst
        self.burst = 0  # $3A: animation step inside a burst
        self.spit_cd = 0  # $3C: frames until the next child in a volley
        self.spit_left = 0  # $3D: children left in the volley
        self.saved_state = 0  # $42: state a finished action returns to
        self.hide_timer = 0  # $43: cooldown before the next decision
        self.target_x_fx = 0  # $3F: x the leap was aimed at
        self.landings = 0  # $41: ground contacts of the leap
        self.hit_flash = 0  # frames of white flash after taking a hit
        self.facing = 0  # $09: 1 right, -1 left
        self.hp = 0
        self.max_hp = 0
        self.timer = 0


class ObjectPool:
    def __init__(self):
        self.slots = [Object() for _ in range(OBJECT_POOL_SIZE)]
        self.events = 0  # one-frame sound/effect flags
        self.boss_alive = False
        self.boss_defeated = False
        self.boss_present = False  # an OBJECT_BOSS was spawned in this room
        self.boss_phase = 0  # 1 until a two-form boss transforms
        self.pit_fight = False  # area 8: $69 raised $1DEA (the fight started)
        self.last_fire_piece = 0
        self.last_talisman = 0  # 1..4 = Buster/Tornado/Claw/Demon Fire


# --------------------------------------------------------------------------
# C-compatible scalar helpers
# --------------------------------------------------------------------------

def _atoi(text: str) -> int:
    """C atoi: optional whitespace/sign, leading digits, 0 when none."""
    i = 0
    n = len(text)
    while i < n and text[i] in " \t\n\r\v\f":
        i += 1
    sign = 1
    if i < n and text[i] in "+-":
        if text[i] == "-":
            sign = -1
        i += 1
    start = i
    while i < n and text[i].isdigit():
        i += 1
    if i == start:
        return 0
    return sign * int(text[start:i])


def _atof(text: str) -> float:
    """C atof: parse the leading float, 0.0 when there is none."""
    match = _ATOF_RE.match(text)
    if match is None:
        return 0.0
    return float(match.group(1))


def _c_int(value: float) -> int:
    """C (int32_t) cast: truncation toward zero."""
    if value >= 0.0:
        return int(math.floor(value))
    return int(math.ceil(value))


def _c_div(value: int, divisor: int) -> int:
    """C integer division: truncation toward zero (Python // floors)."""
    if value < 0:
        return -((-value) // divisor)
    return value // divisor


def _reset_object(o: Object) -> None:
    """memset(o, 0, sizeof(*o))."""
    o.active = False
    o.type = OBJECT_NONE
    o.species = 0
    o.flags = 0
    o.x_fx = 0
    o.y_fx = 0
    o.origin_x_fx = 0
    o.origin_y_fx = 0
    o.vx_fx = 0
    o.vy_fx = 0
    o.bounce_fx = 0
    o.state = 0
    o.substate = 0
    o.phase = 0
    o.hops = 0
    o.burst = 0
    o.spit_cd = 0
    o.spit_left = 0
    o.saved_state = 0
    o.hide_timer = 0
    o.target_x_fx = 0
    o.landings = 0
    o.hit_flash = 0
    o.facing = 0
    o.hp = 0
    o.max_hp = 0
    o.timer = 0


def _alloc(pool: ObjectPool):
    for o in pool.slots:
        if not o.active:
            return o
    return None


# --------------------------------------------------------------------------
# Spawners
# --------------------------------------------------------------------------

def _spawn_urn(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_URN
    o.species = src.species
    o.flags = src.flags
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    o.hp = 1
    o.max_hp = 1


def _spawn_pickup(pool: ObjectPool, x: float, bottom_y: float) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_PICKUP
    o.x_fx = float_to_fx(x)
    o.y_fx = float_to_fx(bottom_y)
    o.vy_fx = -HEART_POPUP_FX  # object convention: positive is up
    o.bounce_fx = HEART_BOUNCE_FX
    o.state = 0


def _spawn_enemy(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_ENEMY
    o.species = src.species
    o.flags = src.flags
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    o.hp = 3 if src.species == 0x26 else 2
    o.max_hp = o.hp
    if env_flag("DC_BOSS_HURT"):  # test hook: show the damage tint
        o.hp = o.max_hp // 2 if o.max_hp > 1 else 1
    o.state = 0  # emerge / init
    o.timer = 24
    o.vx_fx = 0x0080 if (src.flags & 1) else -0x0080
    o.facing = 1 if o.vx_fx >= 0 else -1


# Hostile projectile spawned by the species $67 ghoul ($82877B in the
# original): the child object runs its own species handler, so the native port
# models it as a straight-flying object with the captured $67 sprite.
def _spawn_enemy_shot(pool: ObjectPool, x: float, y: float, vx: int,
                      vy: int) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_ENEMY_SHOT
    o.species = 0x67
    o.x_fx = float_to_fx(x)
    o.y_fx = float_to_fx(y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    o.vx_fx = vx
    o.vy_fx = vy
    o.hp = 1


# Somulo's fireball: a normal hostile shot, but marked so that hitting the
# ground spawns a firewall (its `substate` is used as a flag).
def _spawn_boss_fireball(pool: ObjectPool, x: float, y: float, vx: int,
                         vy: int) -> None:
    _spawn_enemy_shot(pool, x, y, vx, vy)
    for o in pool.slots:
        if (o.active and o.type == OBJECT_ENEMY_SHOT and
                o.x_fx == float_to_fx(x) and o.y_fx == float_to_fx(y)):
            o.substate = 1
            o.species = 0x34  # the fireball object in Area 0
            break


# Firewall: three short-lived flames standing on the ground where a fireball
# landed. They are enemy shots flagged with state 1 so the update path keeps
# them in place.
def _spawn_firewall(pool: ObjectPool, x: float, y: float) -> None:
    for k in range(-1, 2):
        o = _alloc(pool)
        if o is None:
            return
        _reset_object(o)
        o.active = True
        o.type = OBJECT_ENEMY_SHOT
        o.species = 0x34
        o.state = 1
        o.x_fx = float_to_fx(x + float(k) * 9.0)
        o.y_fx = float_to_fx(y)
        o.origin_x_fx = o.x_fx
        o.origin_y_fx = o.y_fx
        o.hp = 1


def _spawn_platform(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_PLATFORM
    o.species = src.species
    o.flags = src.flags
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    o.vx_fx = 0x0080


def _spawn_crest_item(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_CREST_ITEM
    o.species = src.species
    o.flags = src.flags
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx


# Talismans (crown/skull/armor/fang/hand) float in place until collected.
def _spawn_talisman(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_TALISMAN
    o.species = src.flags if 0 <= src.flags < 5 else 3
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx


def _spawn_boss(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_BOSS
    pool.boss_present = True
    o.species = src.species
    o.flags = src.flags
    # Test hook: boot the second Phalanx form directly so its art and AI can
    # be smoke-tested without scripting the first form's death.
    phase_env = env("DC_BOSS_PHASE")
    forced_second = bool(phase_env) and _atoi(phase_env) == 2 and \
        o.species == 0x86
    if forced_second:
        o.species = 0x8D
        o.substate = 1
    bx = src.x
    by = src.y
    if src.species == 0x33 and bx < 120.0:
        bx = 220.0
        by = 160.0
    elif src.species == 0xA5 and by < 64.0:
        by = 140.0
    # The ROM stores a boss's y at the centre of its hitbox, while the port
    # anchors sprites at their feet. Somulo's box is 92 px tall (80x92), so his
    # feet sit 23 px below the stored value -- exactly the colosseum floor
    # (170 + 23 = 193 against a 192 floor line). Without this he stands in the
    # air, which is how the fight shipped until now.
    if src.species == 0x33:
        by += 23.0
    # Test hook: place the boss where a grounded demo can reach it.
    bx_env = env("DC_BOSS_X")
    by_env = env("DC_BOSS_Y")
    if bx_env:
        bx = _atof(bx_env)
    if by_env:
        by = _atof(by_env)
    o.x_fx = float_to_fx(bx)
    o.y_fx = float_to_fx(by)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    o.hp = 6 if src.species == 0x33 else (10 if forced_second else 8)
    o.facing = 1  # sheets face right; the AI updates this as it turns
    hp_env = env("DC_BOSS_HP")
    if hp_env:
        o.hp = _atoi(hp_env)
    o.max_hp = o.hp
    o.state = 0
    pool.boss_alive = True
    if env_flag("DC_BOSS_DEFEATED"):
        # Test hook: the boss starts already defeated so the clear flow can be
        # exercised without fighting. Set the full defeat state, not just an
        # inactive slot.
        o.active = False
        o.hp = 0
        pool.boss_alive = False
        pool.boss_defeated = True
        pool.events |= OBJECT_EVENT_BOSS_DEFEATED


# City NPCs ($96): inert, talkable, drawn from the captured sheet.
def _spawn_npc(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_NPC
    o.species = (src.species if src.species else 0x96) & 0xFF
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    o.hp = 1
    o.facing = -1


def _spawn_unknown(pool: ObjectPool, src) -> None:
    """Pool a species whose handler is only partly ported.

    The pit boss trio ($69/$6B/$6C) needs a live position for its measured
    opening; the renderer draws these as debug boxes (render.py)."""
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = LEVEL_OBJECT_UNKNOWN
    o.species = src.species
    o.flags = src.flags
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    o.hp = 1


def objects_init(pool: ObjectPool, level) -> None:
    # memset(pool, 0, sizeof(*pool)), then the phase default.
    for slot in pool.slots:
        _reset_object(slot)
    pool.events = 0
    pool.boss_alive = False
    pool.boss_defeated = False
    pool.boss_present = False
    pool.pit_fight = False
    pool.last_fire_piece = 0
    pool.last_talisman = 0
    pool.boss_phase = 1
    # $96 is the script/NPC actor: the shopkeepers and the library old man in
    # 46..49/55, the avenue's townsperson in area 4, and the arena controller
    # in the boss rooms (52/53/54, where it shares the boss's position). The
    # extractor types every $96 record "boss", which blocks every door in the
    # room and shows a boss placeholder. In a room with a real boss it is the
    # controller and stays invisible; anywhere else it is a talkable NPC.
    room_has_boss = any(o.type == LEVEL_OBJECT_BOSS and o.species != 0x96
                        for o in level.objects)
    if env_flag("DC_DEBUG_OBJ"):
        eprint(f"objects: init with {len(level.objects)} level objects",
              flush=True)
    for src in level.objects:
        if src.type == LEVEL_OBJECT_URN:
            _spawn_urn(pool, src)
        elif src.type == LEVEL_OBJECT_ENEMY:
            _spawn_enemy(pool, src)
        elif src.type == LEVEL_OBJECT_PLATFORM:
            _spawn_platform(pool, src)
        elif src.type == LEVEL_OBJECT_PICKUP_CREST:
            _spawn_crest_item(pool, src)
        elif src.type == LEVEL_OBJECT_BOSS:
            if src.species == 0x96:
                if not room_has_boss:
                    _spawn_npc(pool, src)
            else:
                _spawn_boss(pool, src)
        elif src.type == LEVEL_OBJECT_NPC:
            _spawn_npc(pool, src)
        elif src.type == LEVEL_OBJECT_TALISMAN:
            _spawn_talisman(pool, src)
        elif src.type == LEVEL_OBJECT_UNKNOWN and \
                src.species in (PIT_CORE_SPECIES, PIT_BODY_SPECIES,
                                PIT_EYE_SPECIES):
            _spawn_unknown(pool, src)
    if env_flag("DC_DEBUG_OBJ"):
        n = 0
        for i, o in enumerate(pool.slots):
            if o.active:
                eprint(f"objects: slot {i} type {int(o.type)} "
                      f"species {o.species} at {fx_to_float(o.x_fx):.0f},"
                      f"{fx_to_float(o.y_fx):.0f}", flush=True)
                n += 1
        eprint(f"objects: {n} active", flush=True)


def _player_touches(o: Object, player) -> bool:
    ox = fx_to_float(o.x_fx)
    oy = fx_to_float(o.y_fx) - HEART_HALF
    px = player.x
    py = player.y - 10.0
    return abs(ox - px) < 16.0 and abs(oy - py) < 20.0


def _damage_player(player, ox: float, amount: int) -> None:
    if player.invuln_timer > 0 or player.hp <= 0:
        return
    # Time/Ultimate Gargoyle and Armor Talisman halve incoming damage.
    if (player.crest_form == CREST_TIME or
            player.crest_form == CREST_ULTIMATE or
            player.active_talisman == 2) and amount > 1:
        amount = (amount + 1) // 2
    player.hp -= amount
    if player.hp < 0:
        player.hp = 0
    player.invuln_timer = 60
    player.knockback_timer = 8
    player.knockback_dir = 1 if ox < player.x else -1
    player.hurt_event = True


# --------------------------------------------------------------------------
# Species $67 - Graveyard Ghoul
#
# Port of the ROM's own handler: init $83:AF19, update $83:AF74, which
# dispatches on $05 through the table at $AF7F and on $06 through per-state
# tables. States are even byte offsets, so each state has four substates
# (0/2/4/6):
#
#   0 $AF89  small hop loop        sub 0 decide, 2 windup, 4 airborne, 6 land
#   2 $B065  long hop              sub 0 face, 2 windup 32, 4 airborne, 6 land
#   4 $B0E4  stand and spit        sub 0 face, 2 windup 32, 4 three children
#                                  on a 64-frame cadence, 6 hold 32
#   6 $B1AF  leap / child flight   sub 0 aim, 2 fly, 4 impact, 6 despawn
#   8 $B249  cooldown              sub 0 wait $43, 2 re-check range
#
# The hop constants are the ROM's: launch `$22 = 0x0398` (`0x04D0` on odd
# hops), `$20 = 0x0050`, gravity `$26 = 0x0040`, `$34 -= 9` at launch and
# `+7` on landing. The long hop uses `$20 = 0x0120`, `$22 = 0x0540`.
# The live oracle trace (`/tmp/ghoul_trace`, 300 frames, area 1) confirms the
# observed order 4 -> 0(2,4,6) -> 0(2,...) with the 32/64/32 volley cadence.
# --------------------------------------------------------------------------
GHOUL_GRAVITY = 0x0040
GHOUL_RANGE_X = 0x00E0
GHOUL_RANGE_Y = 0x0050


def _ghoul_face(o: Object, p) -> None:
    o.facing = 1 if p.x_fx >= o.x_fx else -1


# $B2E8: |(x + 0x70) - player.x| < 0xE0, the $03 bit 6 flag set, and the
# player above the ghoul or no more than 0x50 below it.
def _ghoul_in_range(o: Object, p) -> bool:
    dx = (o.x_fx + 0x70 * FX_ONE) - p.x_fx
    if abs(dx) >= GHOUL_RANGE_X * FX_ONE:
        return False
    if not (o.flags & 0x40):
        return False
    dy = p.y_fx - o.y_fx  # y grows downward
    return dy < GHOUL_RANGE_Y * FX_ONE


# One applied step of the ROM's move + gravity, returning true on landing.
def _ghoul_move(o: Object, level) -> bool:
    o.x_fx += o.vx_fx
    o.y_fx += o.vy_fx
    o.vy_fx += GHOUL_GRAVITY
    fx = fx_to_float(o.x_fx)
    fy = fx_to_float(o.y_fx)
    if o.vy_fx > 0:
        surf = level_floor_at(level, fx, fy + 2.0)
        if surf is not None and surf <= fy + 10.0:
            o.y_fx = float_to_fx(surf)
            o.vx_fx = 0
            o.vy_fx = 0
            return True
    return False


# $B14F: the spit. The ROM spawns another $67 object at (+-0x13, -0x14) and
# sets its state to 6, so the "projectile" is a small diving ghoul.
def _ghoul_spit(pool: ObjectPool, o: Object) -> None:
    ox = fx_to_float(o.x_fx) + float(o.facing * 0x13)
    oy = fx_to_float(o.y_fx) - 0x14
    # The child is aimed at its parent's own x ($3F is written from $31 at
    # $B17C), so the distance band is the near one: vx = 0x80, vy = 0x03A0.
    # It does not home across the room; it lobs and falls.
    _spawn_enemy_shot(pool, ox, oy, o.facing * 0x0080, -0x03A0)


def _ghoul_update(o: Object, level, p, pool: ObjectPool) -> None:
    if env_flag("DC_DEBUG_GHOUL"):
        eprint(f"ghoul t={o.timer} st={o.state} sub={o.substate} "
              f"ph={o.phase} x={fx_to_float(o.x_fx):.1f} "
              f"y={fx_to_float(o.y_fx):.1f}", flush=True)
    if o.state == 0:  # $AF89 small hop loop
        if o.substate == 0:
            if _ghoul_in_range(o, p):
                _ghoul_face(o, p)
                o.hops = 0
                o.substate = 2
                o.phase = 3  # $3B = 3
            else:
                # $DEA2 picks at random; the port rotates deterministically so
                # a replay is reproducible: hop, volley, long hop.
                o.saved_state = (o.saved_state + 1) % 3
                if o.saved_state == 1:
                    o.state = 4
                    o.substate = 0
                elif o.saved_state == 2:
                    o.state = 2
                    o.substate = 0
                else:
                    # The rotation's third beat is the plain small hop.
                    _ghoul_face(o, p)
                    o.hops = 0
                    o.substate = 2
                    o.phase = 3
        elif o.substate == 2:
            _ghoul_face(o, p)
            o.phase -= 1
            if o.phase <= 0:
                o.y_fx -= 9 * FX_ONE  # $B2B1
                o.vx_fx = o.facing * 0x0050
                o.vy_fx = -0x04D0 if (o.hops & 1) else -0x0398
                o.substate = 4
        elif o.substate == 4:
            if _ghoul_move(o, level):
                o.y_fx += 7 * FX_ONE  # $B2C7
                o.substate = 6
                o.phase = 6
        elif o.substate == 6:
            o.phase -= 1
            if o.phase <= 0:
                o.hops += 1  # $B034
                if o.hops >= 3:
                    o.substate = 0
                else:
                    o.facing = -o.facing
                    o.substate = 2
                    o.phase = 3
        else:
            o.substate = 0

    elif o.state == 2:  # $B065 long hop
        if o.substate == 0:
            _ghoul_face(o, p)
            o.substate = 2
            o.phase = 0x20
        elif o.substate == 2:
            o.phase -= 1
            if o.phase <= 0:
                o.y_fx -= 9 * FX_ONE
                o.vx_fx = o.facing * 0x0120
                o.vy_fx = -0x0540
                o.substate = 4
                o.landings = 0
        elif o.substate == 4:
            if _ghoul_move(o, level):
                o.y_fx += 7 * FX_ONE
                o.substate = 6
                o.phase = 0x10
        elif o.substate == 6:
            o.phase -= 1
            if o.phase <= 0:
                o.state = 4  # $B0DD
                o.substate = 0
        else:
            o.substate = 0

    elif o.state == 4:  # $B0E4 stand and spit three children
        if o.substate == 0:
            _ghoul_face(o, p)
            o.substate = 2
            o.phase = 0x20
        elif o.substate == 2:
            o.phase -= 1
            if o.phase <= 0:
                o.substate = 4
                o.spit_left = 3  # $3D = 3
                o.spit_cd = 0x40  # $3C = 0x40
        elif o.substate == 4:
            o.spit_cd -= 1
            if o.spit_cd <= 0:
                _ghoul_spit(pool, o)
                o.spit_left -= 1
                o.spit_cd = 0x40
                if o.spit_left <= 0:
                    o.substate = 6
                    o.phase = 0x20
        elif o.substate == 6:
            o.phase -= 1
            if o.phase <= 0:
                # $B1AB jumps straight into the hop entry, not to the state
                # dispatcher, so a volley always ends in hops.
                _ghoul_face(o, p)
                o.state = 0
                o.hops = 0
                o.substate = 2
                o.phase = 3
        else:
            o.substate = 0

    elif o.state == 6:  # $B1AF leap, and the child's flight
        if o.substate == 0:
            _ghoul_face(o, p)
            o.target_x_fx = p.x_fx
            dx = o.target_x_fx - o.x_fx
            dist = abs(dx)
            # $DEB2/$DEBA/$DEC2: farther targets get more speed and lift.
            if dist > 96 * FX_ONE:
                o.vx_fx = o.facing * 0x0120
                o.vy_fx = -0x0540
            elif dist > 48 * FX_ONE:
                o.vx_fx = o.facing * 0x00C0
                o.vy_fx = -0x0480
            else:
                o.vx_fx = o.facing * 0x0080
                o.vy_fx = -0x03A0
            o.substate = 2
        elif o.substate == 2:
            if _ghoul_move(o, level):
                o.substate = 4
                o.phase = 8
                o.landings += 1
        elif o.substate == 4:
            o.phase -= 1
            if o.phase <= 0:
                o.substate = 6
                o.phase = 0x20
        elif o.substate == 6:
            o.phase -= 1
            if o.phase <= 0:
                o.active = False  # $828777
        else:
            o.substate = 0

    elif o.state == 8:  # $B249 cooldown
        if o.substate == 0:
            o.substate = 2
            o.hide_timer = 0x50  # $43 = 0x50
        elif o.substate == 2:
            o.hide_timer -= 1
            if o.hide_timer <= 0:
                if not _ghoul_in_range(o, p):
                    o.state = 4
                    o.substate = 0
                else:
                    o.state = 0
                    o.substate = 0
        else:
            o.substate = 0

    else:
        o.state = 0
        o.substate = 0


PIT_CORE_SPECIES = 0x69
PIT_BODY_SPECIES = 0x6B
PIT_EYE_SPECIES = 0x6C

# The body's climb, sampled every 20 frames from the pit take (frame 14400 is
# the room entry; 15750 is the top). The ROM's internal stages are $3E/scroll
# driven and not mapped yet (docs/PIT_BOSS.md §5); this is the measured curve.
_PIT_RISE = (
    (0, 700.0), (20, 698.5), (40, 693.5), (60, 690.0),
    (80, 688.1), (100, 687.1), (120, 671.4), (140, 650.8),
    (160, 644.1), (180, 644.1), (200, 641.7), (220, 622.0),
    (240, 604.8), (260, 600.6), (280, 600.6), (300, 595.6),
    (320, 573.7), (340, 559.4), (360, 557.0), (380, 557.0),
    (400, 551.3), (420, 531.3), (440, 519.5), (460, 514.9),
    (480, 513.5), (500, 513.5), (520, 512.3), (540, 497.2),
    (560, 482.4), (580, 474.1), (600, 470.6), (620, 469.9),
    (640, 469.9), (660, 465.0), (680, 444.2), (700, 431.7),
    (720, 427.0), (740, 426.4), (760, 426.4), (780, 419.0),
    (800, 398.4), (820, 386.5), (840, 382.8), (860, 382.8),
    (880, 382.0), (900, 365.2), (920, 351.8), (940, 343.5),
    (960, 339.9), (980, 339.2), (1000, 339.2), (1020, 336.8),
    (1040, 317.2), (1060, 301.1), (1080, 296.2), (1100, 295.7),
    (1120, 294.6), (1140, 277.6), (1160, 258.8), (1180, 252.1),
    (1200, 252.1), (1220, 250.6), (1240, 232.7), (1260, 214.0),
    (1280, 208.6), (1300, 208.6), (1320, 210.8), (1340, 214.6),
    (1350, 216.1),
)


def _pit_body_y(t: int) -> float:
    if t >= _PIT_RISE[-1][0]:
        # State 2 in the take: a slow bob between 187 and 216 (period ~300
        # frames). The exact $3E/scroll mapping is still open.
        phase = (t - _PIT_RISE[-1][0]) % 300
        if phase < 150:
            return 216.0 - 29.0 * (phase / 150.0)
        return 187.0 + 29.0 * ((phase - 150) / 150.0)
    for (t0, y0), (t1, y1) in zip(_PIT_RISE, _PIT_RISE[1:]):
        if t <= t1:
            return y0 + (y1 - y0) * (t - t0) / float(t1 - t0)
    return _PIT_RISE[-1][1]


def _update_pit_boss(pool: ObjectPool, o: Object, player) -> None:
    """Area 8's opening: $69 raises the fight flag, $6B rises from the pit.

    Measured on the pit take (docs/PIT_BOSS.md §4): $1DEA goes 1 when the
    player is at x<128 or y>=568; the body then climbs from y=700 to ~209
    over ~1350 frames and bobs at 187..216. $6C (the eyes) is still a
    placeholder; its 4-state handler at $83:C7B2 is not ported yet.
    """
    if o.species == PIT_CORE_SPECIES:
        if not pool.pit_fight and (player.x < 128.0 or player.y >= 568.0):
            pool.pit_fight = True
        o.timer += 1
        return
    if o.species == PIT_BODY_SPECIES:
        if not pool.pit_fight:
            o.state = 0
            o.timer = 0
            o.y_fx = float_to_fx(700.0)
        else:
            o.timer += 1
            o.y_fx = float_to_fx(_pit_body_y(o.timer))
        return
    o.timer += 1  # $6C: placeholder until the eye AI is ported


def objects_update(pool: ObjectPool, level, player) -> None:
    pool.boss_alive = False
    for o in pool.slots:
        if not o.active:
            continue

        if o.type == OBJECT_NPC:
            o.timer += 1
            continue  # talkable but inert

        if o.species in (PIT_CORE_SPECIES, PIT_BODY_SPECIES, PIT_EYE_SPECIES):
            _update_pit_boss(pool, o, player)
            continue

        if o.type == OBJECT_PLATFORM:
            o.timer += 1
            old_x = o.x_fx
            o.x_fx += o.vx_fx
            if abs(o.x_fx - o.origin_x_fx) > 48 * FX_ONE:
                o.vx_fx = -o.vx_fx
            ox = fx_to_float(o.x_fx)
            oy = fx_to_float(o.y_fx)
            if (player.vy_fx >= 0 and
                    abs(player.x - ox) <= 20.0 and
                    player.y >= oy - 4.0 and player.y <= oy + 6.0):
                player.y_fx = o.y_fx
                player.x_fx += (o.x_fx - old_x)
                player.y = oy
                player.x = fx_to_float(player.x_fx)
                player.vy_fx = 0
                player.vy = 0.0
                player.on_ground = True
            continue

        if o.type == OBJECT_TALISMAN:
            o.timer += 1
            o.y_fx = o.origin_y_fx + _c_int(
                math.sin(o.timer * 0.05) * 3.0 * FX_ONE)
            if _player_touches(o, player):
                player.talisman_mask |= (1 << o.species) & 0xFF
                player.active_talisman = o.species
                pool.last_talisman = o.species
                o.active = False
                pool.events |= OBJECT_EVENT_PICKUP | OBJECT_EVENT_TALISMAN
            continue

        if o.type == OBJECT_CREST_ITEM:
            o.timer += 1
            if _player_touches(o, player):
                # Crest pieces in the original grant the next Fire-Crest
                # element ($BE:A427..A533: Buster, Tornado, Claw, Demon Fire)
                # before they become plain stat upgrades.
                if player.fire_element < 4:
                    player.fire_element += 1
                    pool.last_fire_piece = player.fire_element
                    pool.events |= OBJECT_EVENT_FIRE_PIECE
                if player.max_hp < 10:
                    player.max_hp += 1
                player.hp = player.max_hp
                player.gold += 50
                if player.potions < 5:
                    player.potions += 1
                o.active = False
                pool.events |= OBJECT_EVENT_PICKUP | OBJECT_EVENT_CREST_PICKUP
            continue

        if o.type == OBJECT_BOSS:
            if o.state == 5:  # dying: hold the defeated pose, then go
                o.timer += 1
                if o.phase > 0:
                    o.phase -= 1
                else:
                    o.active = False
                continue
            pool.boss_alive = True
            o.timer += 1
            if o.hit_flash > 0:
                o.hit_flash -= 1
            dx = player.x_fx - o.x_fx
            dy = (player.y_fx - 16 * FX_ONE) - o.y_fx
            if o.species == 0x33:
                # Somulo, the colosseum dragon. The head is the weak point and
                # the fight is a fireball duel: idle -> windup -> fire (low or
                # high, aimed at Firebrand) -> recover, with a stagger when the
                # head is hit. Six head hits kill him.
                if o.state == 6:  # fainted: down, invulnerable, no attacks
                    if o.phase > 0:
                        o.phase -= 1
                    else:
                        # He comes back with three hits left and cannot give
                        # chase any more (substate 3). He stays where he fell:
                        # teleporting him to the room's gate put him out of the
                        # player's reach and the last three hits never landed.
                        # The "stuck in the door" framing belongs to the escape
                        # room, which the port does not model yet.
                        o.hp = 3
                        o.max_hp = 3
                        o.state = 0
                        o.phase = 40
                        o.substate = 3
                    o.y_fx = o.origin_y_fx
                    continue
                if o.state == 7:  # blind walk after the roar
                    towards = 1 if player.x_fx > o.x_fx else -1
                    o.facing = towards
                    o.x_fx += towards * _c_int(0.85 * FX_ONE)
                    if o.phase > 0:
                        o.phase -= 1
                    else:
                        o.state = 0  # eyes open: the fireball duel
                        o.phase = 40
                    if player.hp > 0 and abs(
                            fx_to_float(player.x_fx - o.x_fx)) < 70.0:
                        player.hp = 0
                    continue
                if o.hit_flash > 0 and o.state != 4:
                    o.state = 4  # stagger
                    o.phase = 36
                # The recording shows him walking the corridor after Firebrand:
                # close the distance when the player runs away.
                if o.state == 0 or o.state == 3:
                    if dx > 0:
                        o.facing = 1
                    elif dx < 0:
                        o.facing = -1
                    # Stuck in the gate (substate 3) he cannot give chase, which
                    # is what makes the last three hits possible.
                    if o.substate != 3:
                        if dx > 150 * FX_ONE:
                            o.x_fx += 0x0090
                        elif dx < -150 * FX_ONE:
                            o.x_fx -= 0x0090
                        lo = _c_int(40.0 * FX_ONE)
                        hi = _c_int((level.play_max_x - 60.0) * FX_ONE)
                        if o.x_fx < lo:
                            o.x_fx = lo
                        if o.x_fx > hi:
                            o.x_fx = hi
                o.phase -= 1
                if env_flag("DC_BOSS_NO_ATTACK"):
                    # Test hook: hold the duel in its hittable idle. Cycling
                    # through windup/fire left the head unhittable for ~65 of
                    # every 80 frames, so the scripted six-hit check could only
                    # ever land five hits and the boss survived the run.
                    o.state = 0
                    o.phase = 40
                    continue
                if o.phase <= 0:
                    if o.state == 0:  # idle, breathing
                        # Lore rule (Ghosts'n Goblins wiki): he only lowers his
                        # head to shoot when Firebrand is on the ground, and
                        # attacks from above if the player stays airborne.
                        if player.on_ground:
                            o.state = 1
                            o.phase = 34
                        else:
                            o.state = 5
                            o.phase = 26
                    elif o.state == 1:  # windup: head lowered, jaws open
                        o.state = 2
                        o.phase = 10
                    elif o.state == 2:  # fire
                        # Test hook: a passive boss lets the fight loop be
                        # verified without dodging.
                        if env_flag("DC_BOSS_NO_ATTACK"):
                            o.state = 0
                            o.phase = 30
                        else:
                            ox = fx_to_float(o.x_fx)
                            oy = fx_to_float(o.y_fx)
                            mouth_x = ox + (26.0 if dx > 0 else -26.0)
                            mouth_y = oy + 10.0
                            # Grounded player: the shot goes low and spreads
                            # into a fire wave when it lands (wiki).
                            o.substate = 1
                            target_y = player.y - 2.0
                            tx = player.x - mouth_x
                            ty = target_y - mouth_y
                            ln = math.sqrt(tx * tx + ty * ty)
                            if ln < 0.001:
                                ln = 1.0
                            _spawn_boss_fireball(
                                pool, mouth_x, mouth_y,
                                _c_int(tx / ln * 1.6 * FX_ONE),
                                _c_int(ty / ln * 1.6 * FX_ONE))
                            o.state = 3
                            o.phase = 20
                    elif o.state == 5:  # airborne player: attack from above
                        ox = fx_to_float(o.x_fx)
                        oy = fx_to_float(o.y_fx)
                        mouth_x = ox
                        mouth_y = oy - 40.0
                        o.substate = 2
                        tx = player.x - mouth_x
                        ty = player.y - mouth_y
                        ln = math.sqrt(tx * tx + ty * ty)
                        if ln < 0.001:
                            ln = 1.0
                        _spawn_boss_fireball(
                            pool, mouth_x, mouth_y,
                            _c_int(tx / ln * 1.6 * FX_ONE),
                            _c_int(ty / ln * 1.6 * FX_ONE))
                        o.state = 3
                        o.phase = 20
                    elif o.state == 3:  # recover
                        o.state = 0
                        o.phase = 12
                    elif o.state == 4:  # stagger over: back to idle
                        o.state = 0
                        o.phase = 30
                    else:
                        o.state = 0
                        o.phase = 30
                # The object stays planted: the head dip is a sprite state, not
                # a translation. Dragging y toward origin+86 used to sink him to
                # the world bottom (y=256) while idle, which is why the boss
                # looked like it slid instead of standing and animating.
                o.y_fx = o.origin_y_fx
            elif o.species == 0x13:
                # Grewon: a ground beast. It paces toward Firebrand, crouches,
                # then charges across the arena, and is helpless while turning
                # around.
                if o.hit_flash > 0 and o.state != 4:
                    o.state = 4
                    o.phase = 20
                o.phase -= 1
                ox = fx_to_float(o.x_fx)
                oy = fx_to_float(o.y_fx)
                surf = level_floor_at(level, ox, oy)
                if surf is not None and oy < surf:
                    o.y_fx = float_to_fx(surf)
                if o.phase <= 0:
                    if o.state == 0:  # pace toward the player
                        o.x_fx += 0x0080 if dx > 0 else -0x0080
                        o.facing = 1 if dx > 0 else -1
                        if abs(dx) < 90 * FX_ONE:
                            o.state = 1
                            o.phase = 26
                        else:
                            o.phase = 10
                    elif o.state == 1:  # crouch before the charge
                        o.state = 2
                        o.phase = 64
                        o.substate = o.facing
                    elif o.state == 2:  # charge
                        o.x_fx += 0x0300 if o.substate > 0 else -0x0300
                        if (o.x_fx < level.play_min_x * FX_ONE or
                                o.x_fx > level.play_max_x * FX_ONE):
                            o.x_fx = (_c_int(level.play_max_x * FX_ONE)
                                      if o.substate > 0
                                      else _c_int(level.play_min_x * FX_ONE))
                            o.state = 3
                            o.phase = 34
                        elif o.phase <= 1:
                            o.state = 3
                            o.phase = 34
                    elif o.state == 3:  # recover
                        o.state = 0
                        o.phase = 20
                    elif o.state == 4:
                        o.state = 0
                        o.phase = 20
                    else:
                        o.state = 0
                        o.phase = 20
                o.origin_y_fx = o.y_fx
            elif o.species == 0x09:
                # Hippogriff: hovers, dives, throws feathers -- and now and then
                # turns back into a statue. Shots do nothing then; a headbutt
                # wakes him (the recording shows this, randomly).
                if o.state == 5:
                    # Killed: the rubble stays on the floor for the phase.
                    o.phase -= 1
                    if o.phase <= 0:
                        o.active = False
                    continue
                if o.state == 6:
                    # Stone: shots spark off (the boss branch skips damage while
                    # state 6), only a headbutt at close range wakes him, and
                    # he gets bored after the phase timer runs out.
                    headbutt = (
                        player.dash_timer > 0 and
                        abs(fx_to_float(player.x_fx - o.x_fx)) < 30.0)
                    if headbutt:
                        o.state = 0
                        o.phase = 40
                        o.hit_flash = 10
                    else:
                        o.phase -= 1
                        if o.phase <= 0:
                            o.state = 0  # got bored, woke on his own
                            o.phase = 40
                    continue
                if o.hit_flash > 0 and o.state != 4:
                    o.state = 4
                    o.phase = 20
                o.phase -= 1
                if o.phase <= 0:
                    if o.state == 0:  # hover and track
                        # Occasionally turn to stone: 1 in 4 every cycle, or
                        # always with the test hook.
                        if (env_flag("DC_BOSS_STATUE") or
                                (o.timer > 120 and (o.hops % 4) == 3)):
                            o.state = 6
                            o.phase = 260
                            o.hops += 1
                        else:
                            if o.hops & 1:
                                o.state = 1
                            else:
                                o.state = 2
                            o.hops += 1
                            o.phase = 50 if o.state == 1 else 30
                    elif o.state == 1:  # feather volley
                        ox = fx_to_float(o.x_fx)
                        oy = fx_to_float(o.y_fx)
                        for k in range(-1, 2):
                            tx = player.x - ox
                            ty = (player.y - 12.0) - oy
                            ln = math.sqrt(tx * tx + ty * ty)
                            if ln < 0.001:
                                ln = 1.0
                            _spawn_enemy_shot(
                                pool, ox, oy,
                                _c_int(tx / ln * 1.3 * FX_ONE +
                                       k * 0.4 * FX_ONE),
                                _c_int(ty / ln * 1.3 * FX_ONE))
                        o.state = 0
                        o.phase = 40
                    elif o.state == 2:  # dive
                        o.x_fx += 0x0240 if dx > 0 else -0x0240
                        o.y_fx += 0x0180 if dy > 0 else -0x0180
                        o.state = 3
                        o.phase = 26
                    elif o.state == 3:  # climb back
                        o.x_fx += _c_div(o.origin_x_fx - o.x_fx, 8)
                        o.y_fx += _c_div(o.origin_y_fx - o.y_fx, 8)
                        o.state = 0
                        o.phase = 30
                    elif o.state == 4:
                        o.state = 0
                        o.phase = 20
                    else:
                        o.state = 0
                        o.phase = 30
                if o.state == 0:
                    o.y_fx = o.origin_y_fx + _c_int(
                        math.sin(o.timer * 0.06) * 14.0 * FX_ONE)
            elif o.species == 0x86 or o.species == 0x8D:
                # Phalanx: the demon form hovers and lobs slow orbs. The
                # second form keeps the same head AI but uses the $8D body
                # sheet (the live boss2 save contains $86 + many $8D parts).
                if o.hit_flash > 0 and o.state != 4:
                    o.state = 4
                    o.phase = 20
                o.phase -= 1
                if o.phase <= 0:
                    if o.state == 0:  # drift above the player
                        o.x_fx += 0x00A0 if dx > 0 else -0x00A0
                        o.y_fx = o.origin_y_fx + _c_int(
                            math.sin(o.timer * 0.05) * 18.0 * FX_ONE)
                        if o.timer % 90 == 0:
                            o.state = 1
                            o.phase = 26
                        else:
                            o.phase = 4
                    elif o.state == 1:  # orb
                        ox = fx_to_float(o.x_fx)
                        oy = fx_to_float(o.y_fx)
                        tx = player.x - ox
                        ty = (player.y - 10.0) - oy
                        ln = math.sqrt(tx * tx + ty * ty)
                        if ln < 0.001:
                            ln = 1.0
                        _spawn_enemy_shot(
                            pool, ox, oy + 14.0,
                            _c_int(tx / ln * 1.1 * FX_ONE),
                            _c_int(ty / ln * 1.1 * FX_ONE))
                        o.state = 0
                        o.phase = 60
                    elif o.state == 4:
                        o.state = 0
                        o.phase = 20
                    else:
                        o.state = 0
                        o.phase = 20
            elif o.species == 0xA5:
                # Arma, species $A5.  ROM handler BE:E6EE, state table
                # BE:E731; the state byte ($05) is a byte offset into that
                # table, so states are numbered 0,2,4,...  Ported here:
                #   0  entrance: sink from the post to the arena floor
                #   2  hover: bob on the post, then choose the next attack
                #      (the ROM's chooser at BE:ED13 reads the player's
                #      vertical offset: far -> volley, near -> dive)
                #   4  approach: close the horizontal gap at 0x00A0/frame
                #   6  volley: two aimed shots, then back to 2 with vy=0x0108
                #   8  dive: rush the player's line at 0x0280/frame
                #   10 fall: gravity 0x28 until the floor
                #   12 turn: stop, flip facing, back to 2
                #   24 flee: rise off-screen (the wiki's "escapes after
                #      taking enough hits")
                # States 14/16 (rise variants), 18/20 (helper spawns) and the
                # 22 attack cycle are not ported yet; docs/ARMA_AI.md lists
                # them with their ROM addresses.
                hover_y = o.origin_y_fx - _c_int(81.0 * FX_ONE)
                if o.state == 0:
                    # Entrance: rise from the spawn point to the hover post.
                    if o.y_fx > hover_y:
                        o.y_fx -= 0x0100
                    if o.y_fx <= hover_y:
                        o.y_fx = hover_y
                        o.state = 2
                        o.phase = 60
                elif o.state == 24:
                    # Flee: climb away and free the slot once off-screen.
                    o.y_fx -= 0x0200
                    o.x_fx += 0x0080 if o.x_fx < o.origin_x_fx else -0x0080
                    o.phase -= 1
                    if o.phase <= 0:
                        o.active = False
                elif o.state == 2:  # hover on the post
                    o.y_fx = hover_y + _c_int(math.sin(o.timer * 0.05) * 10.0 * FX_ONE)
                    o.phase -= 1
                    if o.phase <= 0:
                        # The ROM chooses at BE:ED13 from $809D8E's direction
                        # code (thresholds $1A/$17/$0A/$07); that code is not
                        # decoded yet, so the port alternates the two attacks
                        # the recording shows, starting with the volley.
                        if o.hops & 1:
                            o.state = 8
                            o.phase = 30
                        else:
                            o.state = 6
                            o.phase = 24
                        o.hops += 1
                elif o.state == 4:  # approach
                    if abs(dx) > 16 * FX_ONE:
                        o.x_fx += 0x00A0 if dx > 0 else -0x00A0
                    o.phase -= 1
                    if o.phase <= 0 or abs(dx) <= 16 * FX_ONE:
                        o.state = 6
                        o.phase = 24
                elif o.state == 6:  # volley
                    ox = fx_to_float(o.x_fx)
                    oy = fx_to_float(o.y_fx)
                    if o.phase == 24:
                        for k in range(2):
                            ty = (player.y - 18.0 - float(k) * 10.0) - oy
                            tx = player.x - ox
                            ln = math.sqrt(tx * tx + ty * ty)
                            if ln < 0.001:
                                ln = 1.0
                            # Arma's breath is a plain shot: only Somulo's
                            # fireball leaves a firewall.
                            _spawn_enemy_shot(
                                pool, ox + (16.0 if tx > 0 else -16.0), oy,
                                _c_int(tx / ln * 1.5 * FX_ONE),
                                _c_int(ty / ln * 1.5 * FX_ONE))
                    o.phase -= 1
                    if o.phase <= 0:
                        # BE:E8CE: back to the hover.
                        o.state = 2
                        o.phase = 70
                elif o.state == 8:  # dive
                    if abs(dx) > 8 * FX_ONE:
                        o.x_fx += 0x0280 if dx > 0 else -0x0280
                    o.y_fx += 0x0100
                    o.phase -= 1
                    if o.phase <= 0:
                        o.state = 10
                        o.phase = 90
                elif o.state == 10:  # fall
                    o.y_fx += o.vy_fx
                    o.vy_fx = min(0x0100, o.vy_fx + 0x0028)
                    surf = level_floor_at(level, fx_to_float(o.x_fx),
                                          fx_to_float(o.y_fx))
                    if surf is not None and fx_to_float(o.y_fx) >= surf:
                        o.y_fx = float_to_fx(surf)
                        o.vy_fx = 0
                        o.state = 12
                        o.phase = 20
                    o.phase -= 1
                    if o.phase <= 0:
                        o.vy_fx = 0
                        o.state = 12
                        o.phase = 20
                elif o.state == 12:  # turn
                    o.vy_fx = 0
                    o.facing = 1 if dx >= 0 else -1
                    o.phase -= 1
                    if o.phase <= 0:
                        o.state = 14
                        o.phase = 120
                elif o.state == 14:  # rise back to the post
                    if o.y_fx > hover_y:
                        o.y_fx -= 0x0200
                    o.phase -= 1
                    if o.y_fx <= hover_y or o.phase <= 0:
                        o.y_fx = hover_y
                        o.state = 2
                        o.phase = 60
                else:
                    o.state = 2
                    o.phase = 40
            else:
                # Hippogriff / Stage Boss: swoop and hover above Firebrand,
                # and punish with a three-shot spread every 110 frames.
                if abs(dx) > 12 * FX_ONE:
                    o.x_fx += 0x0100 if dx > 0 else -0x0100
                target_y = o.origin_y_fx + _c_int(
                    math.sin(o.timer * 0.06) * 28.0 * FX_ONE)
                if (o.timer % 140) > 90:
                    target_y = player.y_fx - 12 * FX_ONE
                if o.y_fx < target_y:
                    o.y_fx += 0x00C0
                elif o.y_fx > target_y:
                    o.y_fx -= 0x00C0
                if o.timer % 110 == 40:
                    bx = fx_to_float(o.x_fx)
                    by = fx_to_float(o.y_fx)
                    tx = player.x - bx
                    ty = (player.y - 10.0) - by
                    ln = math.sqrt(tx * tx + ty * ty)
                    if ln < 0.001:
                        ln = 1.0
                    tx /= ln
                    ty /= ln
                    for k in range(-1, 2):
                        ang = float(k) * 0.35
                        cx = tx * math.cos(ang) - ty * math.sin(ang)
                        cy = tx * math.sin(ang) + ty * math.cos(ang)
                        _spawn_enemy_shot(pool, bx, by,
                                          _c_int(cx * 1.4 * FX_ONE),
                                          _c_int(cy * 1.4 * FX_ONE))
            # Keep boss art turned toward the player between attack states.
            if dx > 8 * FX_ONE:
                o.facing = 1
            elif dx < -8 * FX_ONE:
                o.facing = -1

            ox = fx_to_float(o.x_fx)
            oy = fx_to_float(o.y_fx)
            if (abs(ox - player.x) < 20.0 and
                    abs(oy - (player.y - 11.0)) < 22.0):
                if player.dash_timer > 0:
                    o.hp -= 1
                    pool.events |= OBJECT_EVENT_ENEMY_HIT
                    player.dash_timer = 0
                    if o.hp <= 0:
                        o.active = False
                        pool.boss_alive = False
                        pool.boss_defeated = True
                        pool.events |= OBJECT_EVENT_BOSS_DEFEATED
                        _spawn_pickup(pool, ox, oy)
                else:
                    _damage_player(player, ox, 1)
            continue

        if o.type == OBJECT_ENEMY:
            ox = fx_to_float(o.x_fx)
            oy = fx_to_float(o.y_fx)
            o.timer += 1
            if o.species == 0x2C:
                # Area 2 Skeleton walker: ground patrol.
                o.state = 1
                o.x_fx += o.vx_fx
                ox = fx_to_float(o.x_fx)
                if (level_is_wall_at(level,
                                     ox + (8.0 if o.vx_fx > 0 else -8.0),
                                     oy - 8.0) or
                        abs(o.x_fx - o.origin_x_fx) > 96 * FX_ONE):
                    o.vx_fx = -o.vx_fx
                    o.facing = 1 if o.vx_fx >= 0 else -1
                surf = level_floor_at(level, ox, oy + 4.0)
                if surf is not None:
                    o.y_fx = float_to_fx(surf)
            elif o.species == 0x07:
                # Area 2/3 Bat/Watcher: sine wave swoop.
                o.state = 1
                dx = player.x_fx - o.x_fx
                if abs(dx) < 200 * FX_ONE:
                    o.x_fx += 0x0080 if dx > 0 else -0x0080
                    o.y_fx = o.origin_y_fx + _c_int(
                        math.sin(o.timer * 0.08) * 18.0 * FX_ONE)
            elif o.species == 0x67:
                # Authentic $83:AF74 handler (see GhoulUpdate above). The
                # contact-damage tail below still runs for ghouls.
                _ghoul_update(o, level, player, pool)
            else:
                # Generic enemy for species whose ROM handler is not ported yet.
                # Placement decides the style: enemies spawned well above a
                # floor fly (hover + 2D chase), grounded ones patrol and walk
                # toward the player. Keeps rooms lively without the ghoul's hop
                # behaviour leaking into every other species.
                dx = player.x_fx - o.x_fx
                dy = player.y_fx - o.y_fx
                near = abs(dx) < 140 * FX_ONE and abs(dy) < 64 * FX_ONE
                spawn_x = fx_to_float(o.origin_x_fx)
                spawn_y = fx_to_float(o.origin_y_fx)
                # No floor under the spawn also means "flying": those spawns
                # hang over pits or above the walkable layer.
                surf = level_floor_at(level, spawn_x, spawn_y)
                airborne = surf is None or surf - spawn_y > 24.0
                if airborne:
                    if o.state == 2:
                        # Dive attack: locked velocity for a few frames.
                        o.x_fx += o.vx_fx
                        o.y_fx += o.vy_fx
                        o.phase -= 1
                        if o.phase <= 0:
                            o.state = 0
                            o.phase = 90
                            o.vx_fx = 0
                            o.vy_fx = 0
                    else:
                        # Flyer: drift toward the player, bob around spawn.
                        o.facing = 1 if dx >= 0 else -1
                        if abs(dx) > 8 * FX_ONE:
                            o.x_fx += o.facing * 0x0070
                        target_y = fx_to_float(o.origin_y_fx) + \
                            math.sin(o.timer * 0.07) * 14.0
                        if abs(player.y - 14.0 - target_y) < 60.0:
                            target_y = player.y - 14.0
                        cur_y = fx_to_float(o.y_fx)
                        if target_y > cur_y + 1.0:
                            o.y_fx += 0x0050
                        elif target_y < cur_y - 1.0:
                            o.y_fx -= 0x0050
                        if o.phase > 0:
                            o.phase -= 1
                        elif (abs(dx) < 64 * FX_ONE and
                              abs(dy) < 180 * FX_ONE):
                            # Swoop at the player's current position.
                            ddx = float(dx)
                            ddy = float(dy)
                            ln = math.sqrt(ddx * ddx + ddy * ddy)
                            if ln < 0.001:
                                ln = 1.0
                            o.vx_fx = _c_int(ddx / ln * 3.0 * FX_ONE)
                            o.vy_fx = _c_int(ddy / ln * 3.0 * FX_ONE)
                            o.state = 2
                            o.phase = 22
                else:
                    if o.state == 2:
                        # Ground lunge: short horizontal burst.
                        o.x_fx += o.facing * 0x0200
                        gx = fx_to_float(o.x_fx)
                        gy = fx_to_float(o.y_fx)
                        surf = level_floor_at(level, gx, gy + 4.0)
                        if surf is not None:
                            o.y_fx = float_to_fx(surf)
                        o.phase -= 1
                        if o.phase <= 0:
                            o.state = 0
                            o.phase = 80
                    else:
                        if near:
                            o.facing = 1 if dx >= 0 else -1
                            if abs(dx) > 10 * FX_ONE:
                                o.x_fx += o.facing * 0x0068
                        else:
                            if o.vx_fx == 0:
                                o.vx_fx = 0x0048
                            o.x_fx += o.vx_fx
                            if abs(o.x_fx - o.origin_x_fx) > 48 * FX_ONE:
                                o.vx_fx = -o.vx_fx
                                o.facing = 1 if o.vx_fx >= 0 else -1
                        gx = fx_to_float(o.x_fx)
                        gy = fx_to_float(o.y_fx)
                        surf = level_floor_at(level, gx, gy + 4.0)
                        if surf is not None:
                            o.y_fx = float_to_fx(surf)
                        if o.phase > 0:
                            o.phase -= 1
                        elif (near and abs(dx) > 14 * FX_ONE and
                              abs(dx) < 52 * FX_ONE):
                            o.state = 2
                            o.phase = 14
            ox = fx_to_float(o.x_fx)
            oy = fx_to_float(o.y_fx)
            px = player.x
            py = player.y - 10.0
            if abs(ox - px) < 14.0 and abs(oy - py) < 18.0:
                if player.dash_timer > 0:
                    o.hp = 0
                    o.active = False
                    pool.events |= OBJECT_EVENT_ENEMY_HIT
                    _spawn_pickup(pool, ox, oy + 8.0)
                else:
                    _damage_player(player, ox, 1)
            continue

        if o.hit_flash > 0:
            o.hit_flash -= 1

        if o.type == OBJECT_ENEMY_SHOT:
            o.timer += 1
            sx = fx_to_float(o.x_fx)
            sy = fx_to_float(o.y_fx)
            if o.state == 1:
                # Firewall flame: stays put, burns for a while.
                if o.timer > 90:
                    o.active = False
                elif (abs(sx - player.x) < 9.0 and
                      abs(sy - (player.y - 6.0)) < 16.0):
                    _damage_player(player, sx, 1)
                continue
            o.x_fx += o.vx_fx
            o.y_fx += o.vy_fx
            sx = fx_to_float(o.x_fx)
            sy = fx_to_float(o.y_fx)
            hit_ground = level_is_solid_at(level, sx, sy) or (
                level_floor_at(level, sx, sy) is not None and
                sy >= float(level.world_h - 24))
            if (o.timer > 240 or hit_ground or
                    sx < level.play_min_x - 16.0 or
                    sx > level.play_max_x + 16.0 or
                    sy < 0.0 or sy > float(level.world_h)):
                if o.substate == 1 and hit_ground:
                    _spawn_firewall(pool, sx, sy - 4.0)
                o.active = False
                continue
            if (abs(sx - player.x) < 10.0 and
                    abs(sy - (player.y - 10.0)) < 12.0):
                _damage_player(player, sx, 1)
                if o.substate == 1:
                    _spawn_firewall(pool, sx, sy)
                o.active = False
            continue

        if o.type != OBJECT_PICKUP:
            continue

        if o.state == 0:
            o.vy_fx += HEART_GRAVITY_FX
            if o.vy_fx > 0x0600:
                o.vy_fx = 0x0600
            o.y_fx += o.vy_fx

            x = fx_to_float(o.x_fx)
            y = fx_to_float(o.y_fx)
            surface = level_floor_at(level, x, y)
            if surface is not None and y >= surface:
                o.y_fx = float_to_fx(surface)
                o.bounce_fx -= HEART_BOUNCE_STEP
                if o.bounce_fx > 0:
                    o.vy_fx = -o.bounce_fx
                else:
                    o.bounce_fx = 0
                    o.vy_fx = 0
                    o.state = 1  # at rest

        if _player_touches(o, player):
            if player.hp < player.max_hp:
                player.hp += 1
            player.gold += 10
            o.active = False
            pool.events |= OBJECT_EVENT_PICKUP


def objects_check_projectiles(pool: ObjectPool, projectiles) -> None:
    for p in projectiles.slots:
        if not p.active:
            continue
        px = fx_to_float(p.x_fx)
        py = fx_to_float(p.y_fx)
        dmg = p.damage if p.damage > 0 else 1

        for o in pool.slots:
            if not o.active:
                continue
            ox = fx_to_float(o.x_fx)
            oy = fx_to_float(o.y_fx)

            if o.type == OBJECT_URN:
                if (abs(px - ox) <= URN_HALF + 4.0 and
                        abs(py - oy) <= URN_HALF + 14.0):
                    o.active = False
                    p.active = False
                    pool.events |= OBJECT_EVENT_BREAK
                    _spawn_pickup(pool, ox, oy + URN_HALF)
                    break
            elif o.type == OBJECT_ENEMY and \
                    (o.species == 0x67 or o.state != 0):
                # Ghouls are hittable in every state: the ROM's $05 values are
                # behaviour states, not an emerge phase.
                if abs(px - ox) <= 12.0 and abs(py - oy) <= 12.0:
                    p.active = False
                    o.hp -= dmg
                    o.hit_flash = 8
                    pool.events |= OBJECT_EVENT_ENEMY_HIT
                    if o.hp <= 0:
                        _spawn_pickup(pool, ox, oy + 8.0)
                        o.active = False
                    break
            elif o.type == OBJECT_ENEMY_SHOT:
                if abs(px - ox) <= 8.0 and abs(py - oy) <= 8.0:
                    p.active = False
                    o.active = False
                    pool.events |= OBJECT_EVENT_ENEMY_HIT
                    break
            elif o.type == OBJECT_BOSS:
                if o.state == 5 or o.state == 6:
                    continue  # collapsing or fainted: ignore hits
                hw = 40.0 if o.species == 0x33 else 20.0
                hh = 46.0 if o.species == 0x33 else 24.0
                if abs(px - ox) <= hw and abs(py - oy) <= hh:
                    if o.species == 0x09 and o.state == 6:
                        p.active = False  # spark off the stone
                        break
                    # Somulo flashes white for ~33 frames after a hit in the
                    # recording and cannot be hit again until it ends, so the
                    # six-hit rhythm is the player's, not a machine gun.
                    # Grewon turns green for 45..75 frames and is invincible
                    # until he changes back: hits during it do nothing.
                    if ((o.species == 0x33 or o.species == 0x13) and
                            o.hit_flash > 0):
                        continue
                    p.active = False
                    o.hp -= dmg
                    if o.species == 0x33:
                        o.hit_flash = 32
                    elif o.species == 0x13:
                        o.hit_flash = 60
                    else:
                        o.hit_flash = 8
                    pool.events |= OBJECT_EVENT_ENEMY_HIT
                    if o.hp <= 0:
                        if o.species == 0x33:
                            if (o.hops == 0 and
                                    not env_flag("DC_BOSS_SKIP_FAINT")):
                                # First death blow is not death: he faints
                                # (wiki). The player is free to move while he
                                # is down, and he comes back stuck in the gate
                                # with three hits left.
                                o.hp = 0
                                o.hops = 1
                                o.state = 6
                                o.phase = 180
                                o.hit_flash = 0
                                break
                            # Collapse, lie there, then leave the room.
                            o.state = 5
                            o.phase = 90
                            o.hit_flash = 0
                            pool.boss_alive = False
                            pool.boss_defeated = True
                            pool.events |= OBJECT_EVENT_BOSS_DEFEATED
                            _spawn_pickup(pool, ox, oy + 8.0)
                            break
                        o.active = False
                        if o.species == 0x09:
                            # The take shows him breaking apart on the floor:
                            # hold the rubble pose for 1.5 s before freeing the
                            # slot. The gate is already open (boss_alive is
                            # cleared below), so this is only presentation.
                            o.active = True
                            o.state = 5
                            o.phase = 90
                            o.hit_flash = 0
                            pool.boss_alive = False
                            pool.boss_defeated = True
                            pool.events |= OBJECT_EVENT_BOSS_DEFEATED
                            break
                        if o.species == 0x86 and pool.boss_phase == 1:
                            # Phalanx's first form falls and the second rises
                            # from the pit: same head, stronger, and the exit
                            # stays shut until it dies too.
                            pool.boss_phase = 2
                            n = _alloc(pool)
                            if n is not None:
                                _reset_object(n)
                                n.active = True
                                n.type = OBJECT_BOSS
                                n.species = 0x8D
                                n.x_fx = o.x_fx
                                n.y_fx = o.y_fx + 40 * FX_ONE
                                n.origin_x_fx = n.x_fx
                                n.origin_y_fx = n.y_fx
                                n.hp = 10
                                n.max_hp = 10
                                n.substate = 1  # second form
                                pool.boss_alive = True
                                pool.events |= OBJECT_EVENT_BOSS_DEFEATED
                            break
                        if o.species == 0xA5:
                            # Arma does not die: he escapes after enough hits
                            # and leaves the Earth Crest behind (wiki). Keep
                            # the slot in the flee state until he is
                            # off-screen; the crest is granted by the
                            # area-clear path, like the other crests.
                            o.active = True
                            o.state = 24
                            o.phase = 90
                            o.hit_flash = 0
                            pool.boss_alive = False
                            pool.boss_defeated = True
                            pool.events |= OBJECT_EVENT_BOSS_DEFEATED
                            break
                        pool.boss_alive = False
                        pool.boss_defeated = True
                        pool.events |= OBJECT_EVENT_BOSS_DEFEATED
                        _spawn_pickup(pool, ox, oy + 8.0)
                    break
