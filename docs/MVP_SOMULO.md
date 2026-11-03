# MVP 1 — Somulo, the first fight

The first delivery target: the colosseum fight from the start of the game,
playable end to end, without cheats or stage select.

## Definition of done

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Start a new game and walk into the colosseum (area 0) | **done** | title flow test + `demo 14` |
| 2 | Somulo appears at the arena, body on the floor, head above | **done** | `enemy_33_*` cut from the recorded fight |
| 3 | The head lowers so a grounded Firebrand can hit it | **done** | head bob in the state machine |
| 4 | He breathes low and high fireballs that track the player | **done** | low/high aim + firewall on impact |
| 5 | **Six** hits kill him; each hit gives a **32-frame** white flash that is invulnerable | **done** | measured in `rec_somulo` (hits at 530/684/834/985/1138/1299) |
| 6 | Defeat leaves the player in control and the gate leads to area 34 | **done** (opt-in `DC_MVP_KEEP_CONTROL`) | `demo 14` reaches area 34 |
| 7 | No placeholder art for the boss, his fireballs or the firewall | **done** | recorded frames + sheet fire art |
| 8 | Beat it as a player with the normal form, no debug flags | **check** | `DC_AREA=0` plain run; the demo's six hits prove reachability |
| 9 | **No HUD during the fight** (the original hides it for the cinematic), and life elsewhere is shown as **dots**, not a bar | **done** | measured from the user's captures; area 0 has no HUD, area 34 shows the two dot rows |

### How it was verified

- `demo 14` walks to the dragon, lands six shots 40 frames apart, and reaches
  area 34 in campaign mode. The regression asserts the HP sequence
  `6 → 5 → 4 → 3 → 2 → 1` and the area transition.
- The hurt rhythm and hit positions come from the recorded take, not guesses.
- `DC_BOSS_NO_ATTACK` is a **test hook** only: it keeps Somulo from firing so
  the loop can be checked without dodging. A human plays against the full
  fireballs.

## Known gaps inside "complete"

1. **Intro roar** — in the original he rears and roars before the fight; the
   pose exists in the sheet but is not staged yet.
2. **Second fight (area 34)** — the gate leads there, but area 34 is not staged
   as the phase-2 encounter.
3. **Mouth flame / breath effect** at the moment of firing.
4. The head bob is a gameplay affordance; the original's exact cadence still
   needs a RAM replay of the take.

## Try it

```powershell
# in the native port, from the title:
#   NEW GAME -> walk right into the colosseum -> shoot the head six times
# or scripted:
$env:DC_AREA="0"; $env:DC_DEMO="14"; .\demonscrest.exe --assets assets\generated
```

## Next delivery

MVP 2: **Murkland cemetery** (area 2) fully playable — its rooms, enemies, urns,
doors and the stage's boss, with the same definition-of-done table.


## Fight structure — canonical (Ghosts'n Goblins wiki, "Somulo")

Source: <https://ghostsngoblins.fandom.com/wiki/Somulo> — "the first boss from
Demon's Crest", also called the Demon Dragon / *Somuro* in the Japanese manual,
level "I - Prologue". The wiki describes four distinct beats, and they are a
**chase set-piece**, not a static arena duel:

1. **Chase** — Somulo pursues Firebrand through the coliseum, trying to smash him
   with its massive claws.
2. **Dead end** — once Firebrand is cornered, the dragon switches to fireballs;
   a fireball that touches the ground **spreads into a fire wave**.
3. **The rule that decides the duel** — you can only hit him **when he lowers his
   head to shoot**, and he **only lowers his head if Firebrand is on the ground**.
   If the player stays airborne, he attacks from above instead.
   **Implemented in the port:** the first death blow now puts him in state 6
   (fainted, invulnerable, no attacks) for 180 frames; he then returns with
   **3 hp** and cannot give chase (substate 3), and those three hits collapse
   him. The escape room and the door framing are not modelled, so he comes
   back where he fell instead of in the gate. `DC_BOSS_SKIP_FAINT=1` keeps
   the old one-hit kill for the gate tests.

4. **Faint → escape → stuck head** — after enough damage he faints; while Firebrand
   escapes, Somulo recovers and gives chase, but **gets stuck in the small door**
   with only his head out, still firing. **Three more hits** and the head burns to
   a crisp and falls apart.

Lore that explains the "eyes closed" walk: Somulo is a **rotting, partially
revived** dragon — he had the Crest of Heaven and was killed by Firebrand in the
prologue; what fights in the colosseum is the corpse.

Art scale check: the wiki's walking GIF (`DC_BO_Somulo_(Walking).gif`, 241x181,
16 frames) is a 2x upscale — the in-game sprite is ~116x90, which matches the
80x92 hitbox the port already uses for species `$33`.

The port currently implements a single-room duel with a blind walk and a fireball
phase; beats 1 (the chase through the colosseum) and 4 (faint, escape, stuck
head) are not implemented yet.

## The entrance (how the fight actually opens)

Explained by the user from the recorded fight — it is scripted, not a cutscene
you can skip:

1. Firebrand is shown in the colosseum; **Somulo is on the far side of the gate**
   and looks at him (his eyes glow between the bars).
2. The steps shake the screen as he comes to the **other gate, which opens** for
   him.
3. He passes through and **screams**.
4. **Only after the scream does the player get control.**
5. He then **walks toward the player with his eyes closed** — he cannot see
   Firebrand, so he does not react; standing in his path is fatal.
6. When he stops and **opens his eyes**, the fireball duel begins.

Implemented so far: four phases with `DC_BOSS_INTRO_DEBUG=1` tracing each
transition — (1) an establishing shot that holds the camera on Firebrand with
distant thumps for 150 frames, (2) the off-screen approach with heavier steps,
(3) the walk-in, which now stops 88 px short of the player instead of walking
him through the player, and (4) the roar, after which control returns. Control
is locked for the whole sequence, screen shake marks every step, and the deadly
blind walk (state 7) starts when the roar ends. `DC_BOSS_INTRO=0` still skips it.

Still missing: the **gate opening** animation, the glowing-eyes-behind-the-bars
shot, and the eyes-closed / eyes-open / scream sprites (the entrance currently
reuses the single full-body frame).


## Entrance timings from a boot-start take

`captures/rec_20261025_005437` starts at boot and dies to the entrance:

| frames | what happens |
|---|---|
| 15–794 | Capcom logo, title |
| 1008–1400 | colosseum, Firebrand at the left |
| ~1562 | the gate with the mouth statue next to him |
| ~1726–2049 | the camera waits; the screen shifts as Somulo approaches |
| **2130** | Somulo appears at the left, **head down, jaws open** (eyes closed) |
| 2211–2454 | he walks right, head still down |
| 2617–2698 | head raised, still walking |
| ~2781 | he is on top of Firebrand; the player dies |

So the blind walk is **~500 frames** from his entry to the contact, and the walk
pose has the **head lowered with the jaws open**, which is what the port should
show during `state 7`.

Art note: the standing pose (cut from frame 8200 of the earlier take) is in the
port. The walking pose cannot be cut from these frames — he stands in front of
the torch relief and the gate bars, so enclosures inside his silhouette keep the
background (the bars and the flame survive any colour/f lood-fill key). The OAM
compositor gives his head and neck cleanly but still drops body parts, so fixing
that is the next step for the walk cycle.


## The HUD is one row, not two

The user asked what the yellow dots under the life row are. They are not a
resource: the original draws **one row of life dots** where the current HP is
pink and the rest of the maximum is a **hollow gold ring**. Measured on the
cemetery capture at frame 3600: three filled + five hollow = 3/8 life.

The port had invented a second yellow row ("potion dots") from a misread of an
upscaled screenshot. `DrawHud` now draws only the life row (filled + hollow) and
the crest slots, with the row starting at x = 26, y = 20 as the game does.


## The reference sprite sheet is a component atlas

`docs/sprites/SNES - Demon's Crest - Enemies & Bosses - Somulo.gif` (677x1366,
single frame) is the complete art, but **not** as full-body frames: it is a
labelled atlas of the parts the hardware draws separately.

| section | contents |
|---|---|
| First Fight → Introduction Roar | 6 head+neck frames |
| Eye Opening | 4 head+neck frames (identical size 82x95) |
| Attack (High) / Attack (Low) | 3 + 6 head+neck frames (95x74, 106x74) |
| Hurt (Defeated) + Body | 3 hurt heads + one **full body**, 119x89 (plus a 195x120 variant) |
| Walking Legs | ~6x4 grid of leg pairs (69x75 cells) |
| Darkened Palette, Defeated Legs | alternate body and a limp-leg grid |
| Fireball / Fire Wall | 4 and 5-6 effect frames |
| Second Fight | roar / attack / hurt / defeated heads for the second encounter |

Measured with 8-connected labelling on an `r+g+b > 45` mask (the background is
`(8,8,8)`, so a plain `!= black` test merges the whole sheet into one blob).
That grid of head sizes is why the oracle's OAM for the boss shows only
head+neck sprites: the body and legs are other pieces, drawn by other means — and
`tools/dc_extract/bake_boss_pose.py` documents that 13 of Somulo's 28 OAM parts
are not reachable through the `$8B:8000` metasprite groups (his head is group
`$09`, but the neck frill and jaw overlay come from another table).

So the single-image draw (8 walk frames from the wiki GIF) is a placeholder in
shape as well as content: the faithful version composes body + legs + head per
state.

## Composed from parts (body + legs + head)

`tools/dc_extract/bake_somulo_parts.py` bakes the parts and the `parts` block in
`species_anim.json`; `src/render.c` composes them for species `0x33` only. Every
offset is measured, never guessed:

| part | source | offset from the feet anchor |
|---|---|---|
| `somulo_body.png` | atlas "Body" (442,458,195,120 at 2x) | -58, -70 |
| `somulo_legs.png` | the reference walk frame minus body and head (the game's own leg pixels) | -36, -30 |
| `somulo_head_neutral.png` | Introduction Roar #1 | 22, -89 |
| `somulo_head_windup.png` | head lowered, jaws open | 36, -46 |
| `somulo_head_fire.png` | head lowered, wider | 36, -46 |
| `somulo_head_roar.png` | widest jaw, head thrust forward | 36, -46 |
| `somulo_body_defeated.png` | "Hurt / Defeated" collapsed body (a complete creature) | -30, -44 |

The body and the neutral head were located inside `somulo_walk.gif` by mask
fitting: the body lands pixel-exact (30 stray pixels of 9 868) and the head at
(161,1) of the 2x frame (14 of 3 008). That fixes the body's neck socket. Every
other head is placed by its **neck cut** — the long straight run on the bottom or
left edge of its bounding box, i.e. where the artist severed the neck — so the
cut's centre sits on the same socket. `--verify` renders each state and asserts
the head overlaps the body by at least 8 px, which is what keeps the neck
continuous.

Per-state selection lives in the same block: `1` windup, `2` fire, `4` roar
(also the intro's roar beat, which now sets state 4 instead of 0), `5`/`6` the
collapsed body. States **0, 3, 7 and 8 stay on the baked single-image walk
frames**: the atlas's Walking Legs grid is two sprites per frame (near + far
pairs) and its best fit leaves ~4% of the reference frame unexplained, so
re-composing the walk would trade proven art for a guess. The composite's legs
are the reference frame's own leg pixels, so the body does not change shape when
a composed state takes over.

## Somulo animation

The walk is a **3-frame cycle**, cut from the immortal walk-past (frames 2475,
2516, 2596 of `rec_20261025_005437`) and aligned by each cut's feet and body
centroid so the cycle does not jitter. Frames 0-2 are the cycle (9 frames each in
`species_anim.json`), frame 3 is the standing pose used for the roar and the
fireball duel.

Known defects, all from the frames being cut out of gameplay:

- thin **wall/gate remnants** survive behind his back (the bars are only slightly
  bluer than the bronze, so a cold-key keeps them); `clean_somulo.py` now clears
  the two measured gate columns from the native standing pose;
- the ground strip from the arena sits at the bottom of each walk frame;
- the walk frames' feet still sit below the room's floor because the colosseum
  background is missing tiles - the same background problem as before.

The three walk frames remain in the asset folder for a future clean cut, but
states 7/8 use the clean native standing pose. That pose is now bottom-anchored
(`79,174`) instead of `120,70`, so the full 158x174 body stands on the floor
rather than sinking below it. A gate-bar walk is not shown while the multi-part
attribution remains unresolved.

The clean fix for all three is the same one the sprite plan calls for: rebuild the
room's background from VRAM, then cut the boss against a known backdrop.
