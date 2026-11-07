#!/usr/bin/env python3
"""Assert the pit boss's damage model (docs/boss_hp.txt).

Ovununu's column in that table is 10 HP for the main body and 3 per eye, with
Fire/Buster/Claw/Tidal doing 1, Demon Fire 3, Earth (ground) 2, Earth (air) 1,
Aerial 2 and Legendary/Ultimate 5.  The port wires the body and the eyes into
the projectile-hit path (they used to be inert placeholders), so this check
builds the pool by hand, fires at each and asserts the hit count and the end of
the fight.

Usage: python3 tools/check_pit_damage.py
Exit codes: 0 = pass, 1 = failure.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dcpy.consts import CREST_ULTIMATE, OBJECT_EVENT_BOSS_DEFEATED  # noqa: E402
from dcpy.object import (  # noqa: E402
    PIT_BODY_HP, PIT_BODY_SPECIES, PIT_EYE_HP, PIT_EYE_SPECIES, ObjectPool,
    _pit_damage, _spawn_unknown, objects_check_projectiles)
from dcpy.projectile import ProjectilePool  # noqa: E402
from dcpy.util import fx_to_float  # noqa: E402


class Player:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.crest_form = 0
        self.active_talisman = 0
        self.invuln_timer = 0
        self.hp = 7
        self.max_hp = 7
        self.gold = 0


def spawn(pool, species, x, y, flags=0):
    _spawn_unknown(pool, SimpleNamespace(species=species, flags=flags,
                                         x=x, y=y))
    for o in pool.slots:
        if o.active and o.species == species:
            return o
    raise AssertionError(f"{species:#x} did not spawn")


def shoot(pool, o, damage=1):
    """Fire one projectile that starts on the body's own box."""
    proj = ProjectilePool()
    p = proj.slots[0]
    p.active = True
    p.x_fx = o.x_fx
    p.y_fx = o.y_fx
    p.damage = damage
    objects_check_projectiles(pool, proj)


def main() -> int:
    errors: list[str] = []

    player = Player(128.0, 640.0)
    if _pit_damage(player) != 1:
        errors.append(f"base form damage {_pit_damage(player)}, expected 1")
    player.crest_form = CREST_ULTIMATE
    if _pit_damage(player) != 5:
        errors.append(f"ultimate damage {_pit_damage(player)}, expected 5")
    player.crest_form = 0

    # Body: 10 hits of 1 damage, then the fight is over.
    pool = ObjectPool()
    body = spawn(pool, PIT_BODY_SPECIES, 128.0, 214.0)
    if body.hp != PIT_BODY_HP:
        errors.append(f"body HP {body.hp}, docs/boss_hp.txt says {PIT_BODY_HP}")
    pool.pit_fight = True
    pool.boss_alive = True
    for hit in range(1, PIT_BODY_HP + 1):
        shoot(pool, body)
        want = PIT_BODY_HP - hit
        if body.active and body.hp != want:
            errors.append(f"after {hit} hits the body has {body.hp}, "
                          f"expected {want}")
            break
    if body.active:
        errors.append("the body survived 10 fire hits")
    if pool.pit_fight:
        errors.append("the fight did not end when the body died")
    if not pool.boss_defeated:
        errors.append("boss_defeated is still false")
    if not (pool.events & OBJECT_EVENT_BOSS_DEFEATED):
        errors.append("no boss-defeated event")

    # Eye: 3 hits.
    pool = ObjectPool()
    eye = spawn(pool, PIT_EYE_SPECIES, 96.0, 254.0, flags=0)
    if eye.hp != PIT_EYE_HP:
        errors.append(f"eye HP {eye.hp}, docs/boss_hp.txt says {PIT_EYE_HP}")
    pool.pit_fight = True
    for hit in range(1, PIT_EYE_HP + 1):
        shoot(pool, eye)
    if eye.active:
        errors.append("the eye survived 3 fire hits")
    if pool.pit_dead != 1:
        errors.append(f"pit_dead {pool.pit_dead}, expected 1 ($1DF8)")

    # The ultimate form kills an eye in one hit (5 >= 3).
    pool = ObjectPool()
    eye = spawn(pool, PIT_EYE_SPECIES, 96.0, 254.0, flags=0)
    pool.pit_fight = True
    shoot(pool, eye, damage=5)
    if eye.active:
        errors.append("a 5-damage hit did not kill an eye")

    if errors:
        print("pit damage: FAIL")
        for e in errors:
            print("  - " + e)
        return 1
    print("pit damage: PASS (body 10 hits, eye 3, ultimate 5; "
          "the fight ends and sets boss_defeated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
