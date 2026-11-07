# Boss HP — mapping `docs/boss_hp.txt` onto the port

The document `docs/boss_hp.txt` (supplied by the user, 2026-11-06) lists every
boss's HP and the damage each Firebrand form deals.  `dcpy/bosses.py` is the
port's copy of the HP side; `tools/check_boss_hp.py` (in the regression) keeps
the two in step and proves the rooms spawn with those numbers.

## The table

Keys are `(species, flags)` — the two bytes of the room's boss record.  The
flags byte is what makes Arma's and the Hippogriff's three fights different
encounters.  Names match the document's lines verbatim so the checker can
compare them.

| species | flags | boss (doc name) | HP | rooms |
|---|---|---|---|---|
| `$A5` | 0 | Arma 1 | 16 | 3 |
| `$A5` | 2 | Arma 2 | 32 | 23 |
| `$A5` | 4 | Arma 3 | 72 | 36, 67 |
| `$09` | 0 | Hippogriff 1 | 16 | 1, 73 |
| `$09` | 2 | Hippogriff 2 | 24 | 20 |
| `$09` | 4 | Hippogriff 3 | 64 | 37 |
| `$7B` | 0 | Scula (Toss half) | 24 | 26 |
| `$7C` | 0 | Scula (Roll half) | 10 | 26 |
| `$6F` | 0 | Holothurion | 72 | 52 |
| `$16` | 0 | Ovununu (body) | 10 | 54 |
| `$82` | 0 | Crawler | 36 | 68 |
| `$58` | 0 | Flame Lord | 26 | 86 |
| `$86` | 0 | Phalanx | 50 | 84 |
| `$8D` | 0 | Phalanx 2 (Heaven Crest) | 127 | 84, phase 2 |
| `$BC` | 0 | Dark Demon | 200 | 90 |

Species whose record flags are not an encounter id live in `SPECIES_HP`
instead, because the byte carries record bits (Belth's thirty records in area
9 range from 129 to 244):

| species | boss | HP | rooms |
|---|---|---|---|
| `$33` | Somulo | 6 | 0 — scripted 3 (faint) + 3 (head in the gate), not in the document |
| `$13` | Grewon | 64 | 30, 41, 71 — "Grewon 1" and "Grewon 2" are both 64 |
| `$68` | Belth | 32 | 9 |

The pit body and eyes are not boss records: `$6B` keeps its 10 and each `$6C`
its 3 in `_spawn_unknown` (`dcpy/object.py`), from the same document.

## Runtime use

`_spawn_boss` sets `hp = boss_hp(species, flags)` and `max_hp` from it; the
Phalanx phase-2 body spawns with `boss_hp(0x8D, 0)` (127) instead of the old
10.  `DC_BOSS_HP` still overrides the value for tests.  Anything without an
entry gets `DEFAULT_BOSS_HP = 8`, which the checker treats as an error so a new
boss cannot silently ship with the wrong number.

## Not modelled yet

- **Flier 1 (24) and Flier 2 (48)** — the document names them but their
  species is still unknown (Passo 4 in `docs/NEXT_STEPS.md`).
- **Phalanx 3 (lava stage, 128)** — no separate species in the port yet.
- **Flame Lord's flying form (20)** — the port has one `$58` body, so it uses
  the land form's 26.
- **Damage per form** — the document's other columns (Fire 1, Buster 1,
  Claw 1, Demon Fire 3, Earth ground 2 / air 1, Aerial 2, Tidal 1,
  Legendary 5, Ultimate 5) are not wired to the player's crests yet.  Today
  `_pit_damage` gives Ultimate 5 and everything else 1.  When the crest forms
  are mapped, this is the table to use.
- **Scula halves** — the document's 24 (Toss) / 10 (Roll) are assigned to
  `$7B` / `$7C` by size; the ROM's per-slot HP would confirm which is which.

## The checker

```bash
DISPLAY=:99 .venv/bin/python tools/check_boss_hp.py
```

1. re-reads `docs/boss_hp.txt` and compares every documented entry's name and
   HP (the HP line may list several numbers, e.g. Ovununu's "3 (eyes);
   10 (main body)");
2. scans every `room_area*.json` boss record (`$96` is the arena controller,
   not a boss) and fails on any species the table does not cover;
3. boots each boss room and reads the `hp` column of the object trace; the
   second Phalanx form is booted with `DC_BOSS_PHASE=2`.
