"""Player fireball pool (port of projectile.c)."""

from __future__ import annotations

import math

from .consts import CREST_TIME, CREST_ULTIMATE, PROJECTILE_POOL_SIZE
from .level import level_break_block_at, level_is_breakable_at, level_is_wall_at

FX_ONE = 256
PLAYER_FIREBALL_VX_FX = 0x0300
PLAYER_FIREBALL_X_OFFSET = 10
PLAYER_FIREBALL_Y_OFFSET = 18


class Projectile:
    __slots__ = ("active", "x_fx", "y_fx", "vx_fx", "damage", "element", "age")

    def __init__(self):
        self.active = False
        self.x_fx = 0
        self.y_fx = 0
        self.vx_fx = 0
        self.damage = 0
        self.element = 0
        self.age = 0


class ProjectilePool:
    __slots__ = ("slots",)

    def __init__(self):
        self.slots = [Projectile() for _ in range(PROJECTILE_POOL_SIZE)]


def projectiles_init(pool: ProjectilePool) -> None:
    for slot in pool.slots:
        slot.active = False
        slot.age = 0


def projectiles_spawn(pool: ProjectilePool, player) -> None:
    for p in pool.slots:
        if p.active:
            continue
        direction = -1 if player.facing < 0 else 1
        p.x_fx = (int(math.floor(player.x)) +
                  PLAYER_FIREBALL_X_OFFSET * direction) * FX_ONE
        p.y_fx = (int(math.floor(player.y)) -
                  PLAYER_FIREBALL_Y_OFFSET) * FX_ONE
        p.vx_fx = PLAYER_FIREBALL_VX_FX * direction
        p.element = player.fire_element
        p.damage = 2 if (player.crest_form in (CREST_TIME, CREST_ULTIMATE) or
                         player.active_talisman == 3) else 1
        p.age = 0
        p.active = True
        return


def projectiles_update(pool: ProjectilePool, level, camera) -> None:
    for p in pool.slots:
        if not p.active:
            continue
        p.age += 1
        p.x_fx += p.vx_fx
        x = p.x_fx / float(FX_ONE)
        y = p.y_fx / float(FX_ONE)
        offscreen = (x < camera.x or x > camera.x + 256.0 or
                     y < camera.y or y > camera.y + 224.0)
        if level_is_breakable_at(level, x, y) and \
                (p.element == 1 or p.damage >= 2):
            level_break_block_at(level, x, y)
            p.active = False
            continue
        if offscreen or level_is_wall_at(level, x, y):
            p.active = False
