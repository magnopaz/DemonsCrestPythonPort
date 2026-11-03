# MVP 2 — Murkland cemetery

Second delivery target: **area 2 (Murkland cemetery)** fully playable, with the
same definition-of-done discipline as `MVP_SOMULO.md`.

## What exists

- Room `area2` loads: world 2048×512, spawn at (64,428), 21 objects
  (enemies `$07`, `$26`, `$2C`, `$67`, one Fire-Crest pickup, urns), and a door
  to area 4 at (1701,300) plus an extracted door to area 3 at (2040,80).
- The player, movement, shooting, urns and pickups all work there today.
- A BW/2-palette backdrop capture exists (`bg2_area2_pal0.png`) but is only
  ~5 KB, and the room's BG layer is almost entirely empty tiles: **the sky is
  black in game**.

## Definition of done

| # | Requirement | Status |
|---|---|---|
| 1 | The cemetery backdrop renders (sky, graves, fog) | **gap** — BG layer is empty, capture is incomplete |
| 2 | Its four enemy species render as real sprites | **gap** — they show as fallback silhouettes |
| 3 | Enemies behave (patrol/shot) and can be killed | partial — generic enemy loop, no per-species AI |
| 4 | Urns give hearts/potions, the Fire-Crest pickup grants its piece | **done** |
| 5 | Walk from the spawn to the door to area 4 and transition | **done** (door present, regression door test) |
| 6 | The area is reachable in the campaign flow | **done** (stage entry / area graph) |

## Blocking work for MVP 2

1. **Re-extract the cemetery background.** The stored BG2 capture is too small
   and the room's tilemap is empty. Either re-run the BG2 capture for area 2
   (VRAM dump at that area) or take the backdrop from
   `docs/sprites/SNES - Demon's Crest - Backgrounds - Cemetery.png`.
2. **Enemy sheets for `$07`, `$26`, `$2C`, `$67`.** `Enemies 1/2.gif` in
   `docs/sprites` has the art but no species labels; the matching tool discussed
   in the plan (`A2`) is the route. `$67` already exists (the ghoul shot).
3. Per-species behaviour for the cemetery enemies (the generic loop is not
   enough for a "fully playable" claim).

## Why it is the right second delivery

It is small (one 2048-wide room), it reuses everything MVP 1 built (urns,
pickups, doors, shooting), and it forces the two asset gaps (backgrounds and
enemy sheets) that every later stage needs anyway.


## Status after the sprite and background work

Playable today: the room loads with its sky/trees backdrop and the gravestone
terrain, the HUD shows the dot row, skeletons (`$2C`) and ghouls (`$67`) walk the
graveyard with sheet-based art, the Hippogriff mid-boss fights with its statue
phase, and dying restarts an arena.

Open items found while running a scripted traversal (`DC_DEMO=15`):

1. **The player gets stuck at world x ~266** in a straight walk-right: the terrain
   needs a jump the demo does not time. Not a collision bug as far as we can tell,
   but the first gap/ledge of the room should be checked against a recording.
2. **A second Firebrand-like figure** appears at the left of the player around
   x ~238. It is not an object (the debug print of every drawn enemy/boss/NPC
   shows only `$2C/$67/$07/$26`) and `DrawPlayer` is called once, so the source is
   still unknown - the debug hook `DC_DEBUG_OBJ=1` prints what `DrawObjects` draws
   and is the tool for chasing it.
3. The room's exits sit at y 300 (area 4) and y 80 (area 3); a straight walk never
   reaches them, so an end-to-end run needs a proper jump script or a human.


## The room's object list was wrong, and the take proved it

The user's boot-start take (`captures/rec_20261027_151150`, 16 025 frames) covers
the whole Somulo fight, the transition to area 34 and a slow walk through the
cemetery. Reading the live object pool while the player is in area 2 shows the
room is populated by **0x72 (flame spirits), 0x67 (ghouls), 0x40, 0x0A, 0x23,
0x39, 0x57 (urns), 0x09 and 0x41** — while our extracted room listed
`0x2C/0x07/0x26/0x67`. So the ROM object table we used for this area does not
match what the game spawns, and most of the cemetery's enemies were invisible or
plain wrong.

`tools/harvest_objects.py` walks a take, reads the pool while the player is in the
chosen area, and collects every distinct object; `rewrite_room_objects.py` then
rewrites the room's enemy list from that harvest, keeping only species we have art
for. Area 2 now spawns **71 objects**: 25 flames, 22 ghouls, 9 of 0x23, 5 of
0x41, 5 Hippogriff slots, 3 urns and the pickups.

The flame sprite itself was cut from the composed OAM layer of frame 7002
(`enemy_72_0.png`, 24x40) — exact art, no background, since the compositor only
draws sprites.

**Open**: a Firebrand-like figure still appears in the cemetery that is *not* the
player (hiding `DrawPlayer` leaves it) and *not* a projectile (hiding those changes
nothing), so it is an object drawn by `DrawObjects` whose species we have not
identified yet — the `DC_DEBUG_OBJ` print only covers the first frames, so it needs
a frame filter before it can answer that.


## The stray "second Firebrand" was baked into the backdrop

Solved with three throwaway hooks: hiding the player (`DC_NO_PLAYER`) left the
figure, hiding the objects (`DC_NO_OBJ`) left it too, and hiding the projectiles
changed nothing - so it was not drawn by any of them. It was **inside
`bg_backdrop_area2.png`**: the backdrop had been cut from a frame in which
Firebrand stood high enough to fall inside the cropped band, so his sprite was part
of the layer and scrolled with the parallax.

`tools/fix_backdrop4.py` now builds the backdrop properly: it scores candidate
frames by bright pixels below the HUD, takes a **sky-only band (110 rows)**, and
paints every pixel inside the HUD rectangles or brighter than the sky with that
column's own sky colour. Nothing from the game's sprites can survive that.

Verified in game: one Firebrand, no ghost copy, the purple tree behind him, HUD
correct. Regression PASS.

Still open for the cemetery: sprite art for `0x23` (9), `0x40` (16), `0x0A` (15)
and `0x39` (9), which are now spawned but have no pictures - their frames can be
cut from OAM dumps the same way the flame was.
