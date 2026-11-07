"""Boss HP from ``docs/boss_hp.txt`` (supplied by the user, 2026-11-06).

The port spawns bosses from the room documents rather than from the ROM's
object records, so the hit count has to live somewhere.  This module is the
single place where a boss's HP is decided::

    hp = boss_hp(species, flags)

``flags`` is the record's second byte.  For Arma (``$A5``) and the Hippogriff
(``$09``) it selects the encounter — 0/2/4 — and each of the three fights has
its own HP in the document.  For other species the byte is a record flag
(Belth's thirty records in area 9 carry 129..244), so those live in
``SPECIES_HP`` and ignore it.

Every entry names the boss exactly as ``docs/boss_hp.txt`` does, so
``tools/check_boss_hp.py`` re-reads the document and proves the table matches
it.  Entries whose boss is not in the document (Somulo's scripted 3+3) are
marked ``documented=False`` and skipped by that comparison.

The document also lists the damage each Firebrand form deals.  That belongs to
the player/projectile code; ``_pit_damage`` in ``dcpy/object.py`` is where the
port models it today.
"""

from __future__ import annotations

from typing import NamedTuple


class BossHp(NamedTuple):
    name: str
    hp: int
    note: str = ""
    documented: bool = True


DOC = "docs/boss_hp.txt"

# No entry at all means the boss is not modelled yet.  Eight is the old
# fallback and stays visible: the checker fails on any boss species that is
# missing from these tables.
DEFAULT_BOSS_HP = 8

# (species, flags) -> BossHp, for bosses whose flags pick the encounter.
BOSS_HP: dict[tuple[int, int], BossHp] = {
    # Arma: three fights, flags 0/2/4.
    (0xA5, 0x00): BossHp("Arma 1", 16),
    (0xA5, 0x02): BossHp("Arma 2", 32),
    (0xA5, 0x04): BossHp("Arma 3", 72),
    # Hippogriff: three fights, flags 0/2/4.
    (0x09, 0x00): BossHp("Hippogriff 1", 16),
    (0x09, 0x02): BossHp("Hippogriff 2", 24),
    (0x09, 0x04): BossHp("Hippogriff 3", 64),
    # Stage bosses.  Scula is two linked species: the document gives 24 for the
    # tossing half and 10 for the rolling one; the ROM's per-slot HP would say
    # which is which, until then the larger body ($7B, the standing one in the
    # baked art) is the 24.
    (0x7B, 0x00): BossHp("Scula", 24, "Toss half"),
    (0x7C, 0x00): BossHp("Scula", 10, "Roll half"),
    (0x6F, 0x00): BossHp("Holothurion", 72),
    (0x16, 0x00): BossHp("Ovununu", 10, "main body; the eyes are $6C (3)"),
    (0x82, 0x00): BossHp("Crawler", 36),
    (0x58, 0x00): BossHp("Flame Lord", 26, "land form; flying form is 20"),
    (0x86, 0x00): BossHp("Phalanx", 50),
    (0x8D, 0x00): BossHp("Phalanx 2 (with Heaven Crest)", 127),
    (0xBC, 0x00): BossHp("Dark Demon - Three Headed/Fallen Angel", 200),
}

# species -> BossHp, for bosses whose record flags are not an encounter id.
SPECIES_HP: dict[int, BossHp] = {
    # Not in boss_hp.txt: the prologue is scripted as 3 hits (faint) + 3 hits
    # (head stuck in the gate), see docs/LORE.md.
    0x33: BossHp("Somulo", 6, "scripted 3+3", documented=False),
    # Grewon's two fights both have 64 HP, so the flags (0/2) do not matter.
    0x13: BossHp("Grewon 1", 64, "Grewon 2 is also 64"),
    # Belth's thirty records carry record flags (129..244), never a variant.
    0x68: BossHp("Belth", 32),
}

# Species whose boss fight is not spawned from a room boss record yet, so a
# table entry would be dead code: Flier 1 (24) and Flier 2 (48) are listed in
# boss_hp.txt but their species is still unknown (docs/NEXT_STEPS.md, Passo 4).
UNMODELLED = ("Flier 1", "Flier 2", "Phalanx 3 (lava stage)")


def _lookup(species: int, flags: int) -> BossHp | None:
    key = (species & 0xFF, flags & 0xFF)
    entry = BOSS_HP.get(key)
    if entry is None:
        entry = BOSS_HP.get((key[0], key[1] & 0x0F))
    if entry is None:
        entry = SPECIES_HP.get(key[0])
    return entry


def boss_hp(species: int, flags: int) -> int:
    """HP for a boss record; the documented value or the visible fallback."""
    entry = _lookup(species, flags)
    return entry.hp if entry is not None else DEFAULT_BOSS_HP


def boss_name(species: int, flags: int) -> str:
    entry = _lookup(species, flags)
    return entry.name if entry is not None else f"species {species:#04x}"


def all_entries():
    """Every (species, flags, BossHp) the module knows."""
    out = [(key[0], key[1], entry) for key, entry in BOSS_HP.items()]
    out += [(species, None, entry) for species, entry in SPECIES_HP.items()]
    return out


def documented_entries():
    """Entries whose boss is named in docs/boss_hp.txt."""
    return [(s, f, entry) for s, f, entry in all_entries() if entry.documented]
