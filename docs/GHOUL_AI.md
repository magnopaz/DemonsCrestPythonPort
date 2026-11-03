# Species `$67` — Graveyard Ghoul

The ROM's own handler, ported into `src/object.c` (`GhoulUpdate`). Init is
`$83:AF19`, update is `$83:AF74`: it reads the state byte `$05`, jumps through
the table at `$AF7F`, and each state dispatches again on the substate `$06`
through its own table. Substates are **even byte offsets** (`JSR (abs,X)` with
`X = $06`), so every state has four of them: `0, 2, 4, 6`.

| state | handler | role | substates |
|---|---|---|---|
| 0 | `$AF89` | small hop loop | 0 decide, 2 windup, 4 airborne, 6 land |
| 2 | `$B065` | long hop | 0 face, 2 windup, 4 airborne, 6 land |
| 4 | `$B0E4` | stand and spit children | 0 face, 2 windup, 4 three children, 6 hold |
| 6 | `$B1AF` | leap / child flight | 0 aim, 2 fly, 4 impact, 6 despawn |
| 8 | `$B249` | cooldown | 0 wait `$43`, 2 re-check range |

## Constants recovered from the code

| value | source | meaning |
|---|---|---|
| `$20 = 0x0050` | `$B2B1` caller | small-hop horizontal speed |
| `$22 = 0x0398` | `$B15E`, `$B164` | small-hop lift (`0x04D0` on odd hops, `$B019`) |
| `$26 = 0x0040` | `$AF65` (init) | gravity |
| `$34 -= 9` | `$B2B1` | lift on launch |
| `$34 += 7` | `$B2C7` | snap on landing |
| `$3B = 3` | `$AFC6` | windup before a small hop |
| `$3B = 0x20` | `$B07F`, `$B0FB`, `$B14A` | windup before a long hop / volley / hold |
| `$3C = 0x40`, `$3D = 3` | `$B110`, `$B114` | three children, 64 frames apart |
| `$43 = 0x50` | `$B26F` | cooldown in state 8 |
| range `|x + 0x70 - player.x| < 0xE0`, `player.y - o.y < 0x50` | `$B2E8` | attack range |

`$B14F` is the spit: it calls the allocator at `$82877B` with species `$67`,
sets the child's `$05 = 6` and writes `$3F = $31` (its own x) at `$B17C`, so the
child is aimed at where its parent stands, not at the player: it lobs out with
the near band's `vx = 0x80`, `vy = 0x03A0` and falls. The port spawns the same
object as `OBJECT_ENEMY_SHOT` with those speeds; an earlier port version homed
on Firebrand, which let a perched ghoul hit a player 600 px away — the demo 6
physics replay caught it (the player lost HP at spawn).

## What the live oracle trace confirmed

Sampling an injected `$67` next to the player for 300 frames (`/tmp/ghoul_trace`,
from `mvp_murkland-cemetery.sav`, area 1) shows exactly the ROM's order:

```
state 4 sub 0  face
state 4 sub 2  32 frames           ($3B 0x20 -> 0)
state 4 sub 4  3 x 64 frames       ($3C cadence, children leaving)
state 4 sub 6  32 frames
state 0 sub 2  3 frames            (small-hop windup)
state 0 sub 4  airborne, vx=0x50, vy starts at 0x0398 and gains 0x40/frame
state 0 sub 6  6 frames            (landing, facing flips, $38++)
```

`$B1AB` (state 4 sub 6) jumps into the hop entry directly, which is why a
volley always ends in hops instead of re-deciding.

## Still approximate (and why)

- **Animation ids** (`$80F81D`) select frame streams out of WRAM `$7F`; the port
  maps the behaviour onto the baked `species_anim` poses instead of replaying
  those streams.
- **`$DEA2` random picker** chooses which behaviour follows an idle decision.
  The port rotates deterministically (hop, volley, long hop) so replays stay
  reproducible; the ROM's exact distribution is 1-of-16 from `$BC904B`'s low
  nibble.
- **`$DE8F/$DE93/$DE9B` step tables** (animation pacing inside a hop) live in
  the metasprite block in WRAM and are read byte-wise at runtime; the port lets
  its own animation timer drive the poses, so those bytes are not transcribed.
- **`$DEB2/$DEBA/$DEC2`** scale the leap's speed with the distance to the
  player. The port uses the three measured bands (96/48 px) with the ROM's
  speeds; the exact table bytes are not decoded.

Everything else — states, substates, transitions, cadence, gravity, launch
speeds, range check, the spit and the contact damage — is the ROM's own.
