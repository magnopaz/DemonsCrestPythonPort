# Arma (species `$A5`): ROM machine, what the port runs, what is missing

Arma is the stage-I boss (murkland abyss, area 3) and the first source of the
**Earth Crest**. He does not die in this fight: "he uses the Crest of Earth and
escapes after taking enough hits, dropping the crest" (Ghosts'n Goblins wiki,
`captures/wiki/Arma.wiki`).

## Where his code lives

The object dispatcher calls the stub `$02:FBB6`, which jumps to **`BE:E6EE`** in
the boss bank. That entry is:

```
BE:E6EE  SEP #$30
BE:E6F0  LDX $05          ; state, a *byte offset* into the table below
BE:E6F2  JSR ($E731,X)
BE:E6F5  JSL $80F83D      ; animation timer/step advance
BE:E6F9  LDA $00
BE:E6FB  STA $1DE1
BE:E6FE  LDA $1DDE        ; hurt flash
BE:E701  BEQ ...
BE:E703  JSL $80A2AB      ; knockback
BE:E707  JSR $E726
...
BE:E71E  LDA #$0025       ; SFX when the animation hits a given frame
BE:E721  JSL $80BD57
```

`JSR ($E731,X)` reads a 16-bit pointer at `BE:E731 + state`, so state values are
**0, 2, 4, ...** (byte offsets, not indices). The recompiled dispatch confirms
`_idx = X / 2` with 13 entries:

| state | handler | role |
|---|---|---|
| 0 | `BE:E74B` | entrance (`INC $1042` locks the player), sink onto the post |
| 2 | `BE:E8EF` | hover; when anim `$0A01` and `$38 == 2`, choose 4 or 8 from `$1DDD` |
| 4 | `BE:E92F` | approach / line up (`$809D8E`, `$809B53`, `$809FA2`) |
| 6 | `BE:E9C3` | volley: at anim `$0601` spawns object `$A6`, at `$0801` -> `$E8CE` |
| 8 | `BE:EA09` | dive setup + charge (`$808C31`, `$808BED`, speed to `$0280`) |
| 10 | `BE:EAAC` | fall (gravity `$28`, clamp `$0100`), land at `$1DD2` |
| 12 | `BE:EB00` | one-frame turn: `$20=0`, `$21=1`, flip `$09` |
| 14 | `BE:EB19` | rise (`$38` gravity) with collision checks |
| 16 | `BE:EB77` | rise variant (`$0E` gravity) |
| 18 | `BE:EBA5` | stop at `$1DD2`, choose 12 or 20 |
| 20 | `BE:EC02` | countdown `$38`, spawns `$B4` every 4 frames |
| 22 | `BE:EC2C` | attack cycle: spawns `$A7`, `INC $1DDD`, anim `$0401`/`$0601` |
| 24 | `BE:E999` | scripted sequence at anim `$0030`/`$0258`/`$0830`, spawns `$A8` |

The attack chooser is **`BE:ED13`**:

```
BE:ED13  JSL $809D8E      ; returns a small code (0x0A/0x17/0x1A thresholds)
BE:ED19  CMP #$1A ; BCS -> state 6 (volley)
BE:ED1D  CMP #$17 ; BCS -> return
BE:ED21  CMP #$0A ; BCS -> state 6
BE:ED25  CMP #$07 ; BCS -> return
BE:ED29  ... LDA #$06 ; STA $05  ; volley
```

so the choice depends on whatever `$809D8E` returns. That value is still one of
the small direction codes seen in `$1DD0` (0x0C/0x0E) and has **not** been
decoded yet.

## What the port runs (`dcpy/object.py`, `_arma_update`)

Implemented with the ROM's own state numbers and constants:

- **0** entrance: rises from the spawn point to the hover post
  (`origin_y - 81 px`, measured from the save: he sits at 151 and hovers at 70).
- **2** hover: 10 px sine bob; after the timer, alternates volley/dive.
  The alternation replaces the undecoded `$809D8E` chooser so that both attacks
  the recording shows actually happen.
- **4** approach: closes the horizontal gap at `0x00A0`/frame (ROM constant).
- **6** volley: two aimed shots (`0x0200`..) at the start of the state, then back
  to the hover.
- **8** dive: `0x0280`/frame toward the player's line + `0x0100`/frame down.
- **10** fall: gravity `0x28`, terminal `0x0100`, lands on the room floor.
- **12** turn: zeroes velocity, faces the player.
- **14** rise: climbs back to the post at `0x0200`/frame.
- **24** flee: rises off-screen and frees the slot.

Not ported yet (documented, not faked):

- the exact `$809D8E` direction code and the `$1A/$17/$0A/$07` chooser;
- states 16/18/20/22 (the `$B4`/`$A7` helper spawns and the `$1DDD` cycle);
- the `$A6`/`$A8` objects the ROM spawns in states 6 and 24 (the crest drop
  object is not drawn; the crest is granted by the area-clear path instead);
- Arma's per-pose animation streams (`$EEE7` sets `$56/$58/$59/$5B`).

The fight is therefore ROM-shaped (same state names, same motion constants,
same dive->land->rise cycle, same "leave after enough hits") but not
byte-identical.

## Crest, gate and map

- `$81:97DA + 3` is **`$F0`**, not an area id. `00:BB66` reads it, and for
  `>= $F0` jumps to `00:BB1F`: `AND #$0F; STA $0EA6` (map entry index) then
  `LDA #$1C; STA $00F9` and a task switch. Area 3 is entry 0.
- `world_map.sav` resumes with `$008D = $BC` (**area 94**) at `(896, 156)`, so
  `$F0` means "the world map".
- `tools/dc_extract/apply_gate_table.py` re-applies `$81:97DA` to every room:
  verified markers get a real `gate_next_area` (only `$F0 -> 94` today), the
  rest keep `-1` but record `gate_marker`/`gate_entry` so nothing unverified
  gains an exit. `build_assets.sh` runs it after `apply_boss_table.py`.
- `Game_CompleteArea(3)` now grants **CREST_EARTH** (it used to grant
  `CREST_TIME`) and keeps the player in control, because the room has a gate:
  the crest text plays and the player walks out to area 94. Area 0 no longer
  grants a crest (the colosseum intro has none; Earth is Arma's drop).
- Area 3's boss position in `tools/check_bosses.py` was `(856, 1180)`, 1024 px
  below the fight and inside solid rock. `arma_boss.sav` has `$008D = 6`,
  camera y = 0, player `(681, 156)` and the live Arma at `(856, 151)`; the table
  now uses that.

## Verification

`tools/check_arma.py` (wired into `tools/run_regression.py`) runs area 3 with
`DC_DEMO=16` (stand and shoot, then walk right), `DC_BOSS_HP=3`,
`DC_DIALOGUE_AUTO=25` and asserts: spawn at (856,151), states 6/8/10/12 all run,
the boss reaches the hover height, hp reaches 0, the flee state runs, the Earth
Crest is granted, and the fade loads area 94 with the game still in play.

## Known data gaps around area 3

- **The spawn record is still (64, 1180).** `$81:A1A9 + 3*2` points at
  `40 00 9c 04 00`, i.e. x=64 y=1180 exactly as `room_area3.json` says, so the
  extractor is faithful — but the Arma save has the player at (681, 156) with
  the camera at y=0. Area 1 has the same shape (spawn y=428 in a 256 px room),
  so the spawn records are not plain world coordinates. Entering area 3 from
  area 2 (spawn id 0) therefore still lands at the bottom of the abyss; the
  fight checks start from (845, 170) instead.
- **The room's camera starts at y=1004** (`room_area3.json`), the bottom of the
  shaft. `check_bosses.py` no longer requires the boss to sit inside that
  initial band for rooms taller than 1.5 viewports; it checks the `play` box
  instead.

## Measured transition chain (oracle, 2026-11-03)

Sampling `$1305` with `set_wram_watch` over a 3 000-frame take of
`arma_boss.sav` (player holding Y) gives the writes and the block that made
them, in game order:

| gframe | block | state written |
|---|---|---|
| 20601 | `BE:E8CE` | 2 |
| 20664 | `BE:E92C` | 4 |
| 20682 | `BE:ED3A` | 6 |
| 20761 | `BE:E8CE` | 2 |
| 20824 | `BE:E92C` | 4 |
| 20842 | `BE:ED3A` | 6 |
| 20921 | `BE:E8CE` | 2 |
| 20984 | `BE:E92C` | 4 |
| 21002 | `BE:ED84` | 8 |
| 21037 | `BE:E8CE` | 2 |
| 21100 | `BE:E92C` | 4 |
| 21130 | `BE:EDD2` | 10, then `BE:EDDF` runs `INC $05` twice (transient 11, final 12) |
| 21146 | `BE:EAFD` | 8 (`STA $05` from `$1DCE`) |
| 21277 | `BE:E8CE` | 2 |
| 21340 | `BE:E92C` | 4 |
| 21354 | `BE:ED3A` | 6 |
| 21433 | `BE:E8CE` | 2 |

So the real graph is **2 -> 4 -> {6 | 8 | 10}**, **10 -> 12**, **12 -> 8**, and
**{6, 8} -> 2**.  `BE:ED13` (the chooser) and `BE:ED65`/`BE:ED7F`/`BE:ED8A`
(the distance tests that pick 6, 8 or 10) are the missing piece; the port
currently alternates 2 -> 6 / 2 -> 8 and always routes 12 -> 14 (rise), which
covers the same attacks but not the ROM's chaining.

## Open question: the late-fight 4 <-> 12 loop

A 5 000-frame take with the player force-healed every 5 frames (so the fight
never resets) shows two phases:

- **early** (g20557..g21433): the full chain above — 2 -> 4 -> {6 | 8 | 10} ->
  12 -> 8 -> 2, with volleys and dives;
- **late** (g25855..g26545): only **4 (sub 2) <-> 12 (sub 0/2)**, x wandering
  between 854 and 935, y bobbing between 74 and 122, no 6 and no 8.

Across the same window `$1DCE` reads 0x01 (it was 0x04 in the early fight) and
`$1DD1` reads 0x16.  State 2's handler reads and clears `$1DCE` and uses it as
the next state (`LDA $1DCE; STZ $1DCE; BNE ... STA $05`), so a value of 1 there
means the latch holds a state number this table cannot represent — i.e. `$1DCE`
is being used for something other than a state id in the late phase.

What is not yet known: whether that loop is the "he has taken enough hits and
is about to leave" behaviour, a damage-stagger loop, or a different attack the
port has not seen. The port does not model `$1DCE`; its Arma runs the early
chain and leaves when `hp` reaches 0.
