#!/usr/bin/env python3
"""Assert an authored forms_damage row wins over the documented table.

docs/EDITOR_NEXT_FEATURES.md feature 2: the authored enemy definition
(enemies.json) can carry the same ten damage columns dcpy/bosses reads
(Fire/Buster/Claw/DemonFire/Earth-ground/Earth-air/Aerial/Tidal/
Legendary/Ultimate).  The projectile-hit path must use that row first;
0 means N/A (the form cannot hurt it); a species with no authored row
keeps the documented boss_damage() row, and a species with neither
keeps the projectile's own damage.

This check builds the pool by hand with a throwaway authored tree, so
nothing in the real assets is touched.

Usage: python3 tools/check_forms_damage.py
Exit codes: 0 = pass, 1 = failure.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dcpy.consts import CREST_BASE, CREST_TIME  # noqa: E402
import dcpy.enemy_defs as enemy_defs  # noqa: E402
from dcpy.object import (  # noqa: E402
    _spawn_enemy, objects_check_projectiles, ObjectPool)
from dcpy.projectile import ProjectilePool  # noqa: E402


class Player:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.crest_form = CREST_BASE
        self.on_ground = True
        self.active_talisman = 0
        self.invuln_timer = 0
        self.hp = 7
        self.max_hp = 7
        self.gold = 0


TEST_SPECIES = 0x121  # free species id, no native handler


def spawn(pool, species, x, y, flags=0):
    _spawn_enemy(pool, SimpleNamespace(species=species, flags=flags,
                                       x=x, y=y))
    for o in pool.slots:
        if o.active and o.species == species and (o.flags & 0x0F) == (flags & 0x0F):
            return o
    raise AssertionError(f"{species:#x} flags {flags:#x} did not spawn")


def shoot(pool, o, damage=1, player=None):
    proj = ProjectilePool()
    p = proj.slots[0]
    p.active = True
    p.x_fx = o.x_fx
    p.y_fx = o.y_fx
    p.damage = damage
    objects_check_projectiles(pool, proj, player)


def authored_dir(forms_damage=None, hp=12):
    tmp = Path(tempfile.mkdtemp(prefix="dc-forms-damage-"))
    enemies = {
        "121": {
            "key": "121", "species": TEST_SPECIES, "flags": 0,
            "name": "Forms test",
            "status": {"hp": hp, "contact_damage": 1, "defense": 0,
                       "invulnerable": False},
            "movement": {"ai": "stationary", "speed": 0, "range": 180,
                         "bob": 0, "gravity": False, "override_ai": False},
            "attacks": [], "sounds": {},
        },
    }
    if forms_damage is not None:
        enemies["121"]["forms_damage"] = forms_damage
    (tmp / "enemies.json").write_text(json.dumps(
        {"version": 1, "enemies": enemies}))
    return tmp


def main() -> int:
    errors: list[str] = []

    def check(label, got, want):
        if got != want:
            errors.append(f"{label}: got {got}, want {want}")
        else:
            print(f"  ok {label} -> {got}")

    # 1. Authored row: Fire 3, Legendary 0 (N/A).  A shot that carries
    #    damage 1 must deal the authored 3 with the base form, and 0
    #    (immune) with the Legendary form.
    tmp = authored_dir({"fire": 3, "legendary": 0})
    enemy_defs.load(str(tmp))
    pool = ObjectPool()
    player = Player(128.0, 640.0)
    o = spawn(pool, TEST_SPECIES, 128.0, 640.0)
    check("authored hp", o.hp, 12)
    player.crest_form = CREST_BASE
    shoot(pool, o, damage=1, player=player)
    check("authored fire column (3, not the shot's 1)", o.hp, 9)
    o.hit_flash = 0
    player.crest_form = CREST_TIME
    shoot(pool, o, damage=1, player=player)
    check("authored legendary N/A (0, immune)", o.hp, 9)

    # 2. No authored row on the species: the shot keeps its own damage
    #    (0x121 has no boss_damage row either).
    tmp2 = authored_dir(None)
    enemy_defs.load(str(tmp2))
    pool2 = ObjectPool()
    o2 = spawn(pool2, TEST_SPECIES, 128.0, 640.0)
    player.crest_form = CREST_BASE
    shoot(pool2, o2, damage=2, player=player)
    check("no row anywhere -> the shot's own damage", o2.hp, 10)

    # 3. Authored row wins over a DOCUMENTED row: give Scula ($7B) an
    #    authored Fire of 1 while the document's row says its own value;
    #    the shot must deal the authored 1.
    from dcpy.bosses import boss_damage
    tmp3 = authored_dir(None)
    root = json.loads((tmp3 / "enemies.json").read_text())
    root["enemies"]["scula"] = {
        "key": "scula", "species": 0x7B, "flags": 0, "name": "Scula test",
        "status": {"hp": 24, "contact_damage": 1, "defense": 0,
                   "invulnerable": False},
        "movement": {"ai": "stationary", "speed": 0, "range": 180,
                     "bob": 0, "gravity": False, "override_ai": False},
        "attacks": [], "sounds": {},
        "forms_damage": {"fire": 2},
    }
    (tmp3 / "enemies.json").write_text(json.dumps(root))
    enemy_defs.load(str(tmp3))
    pool3 = ObjectPool()
    o3 = spawn(pool3, 0x7B, 128.0, 640.0)
    check("documented hp for Scula", o3.hp, 24)
    documented = boss_damage(0x7B, 0, CREST_BASE, True)
    print(f"  documented Scula fire is {documented}; the authored row "
          f"says 2 and must win")
    player.crest_form = CREST_BASE
    shoot(pool3, o3, damage=1, player=player)
    check("authored fire=2 overrides the documented row", o3.hp, 22)

    print(f"forms_damage: "
          f"{len(errors)} error(s)" + ("" if not errors else ""))
    for err in errors:
        print(f"  FAIL {err}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
