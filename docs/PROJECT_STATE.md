# Demon's Crest Fan Game — Project State and Handoff

Last updated: 2026-11-03
Active implementation: `projetos/opencode/DemonsCrestPythonPort` (Python 3 +
raylib; the C tree below, ported 1:1 and verified — see `docs/PARITY.md`)
Frozen C build: `projetos/opencode/DemonsCrestNativePort` (kept as the source
spec and the reference binary; no new features land there)
Reference recompilation: `projetos/opencode/DemonsCrestSNESRecomp`
ROM: `projetos/opencode/roms/Demon's Crest (USA).sfc`

## Session 2026-11-03 — a second implementation, with parity gates

- **The game now exists twice.** `projetos/opencode/DemonsCrestPythonPort` is a
  module-for-module Python 3 + raylib port of this tree (8,816 lines; `dcpy/`
  mirrors `src/` 1:1). It reads this project's `assets/generated` and room JSON
  unchanged, and `tools/demonscrest-py` keeps the `--assets`/`DC_*` contract so
  this suite drives either binary.
- **The port is measured against this build, not eyeballed.** Player/object/
  projectile traces are byte-identical over the 600-frame cemetery demo, the
  Hippogriff fight and Somulo's 1,200-frame arena; area 1 frame 200 differs by
  mean 0.029 (world region 0.0) and areas 0/2/3/10/61 by 0.03-0.21;
  `tools/run_regression.py` is PASS against `tools/demonscrest-py`.
- **C semantics Python does not reproduce by default** (each one cost a debug
  cycle): `Player saved = game->player` must become a field snapshot, not an
  alias; the `memset` in `Player_Init`/`Level_LoadFile` is a real reset, or a
  room change appends the old room's objects and keeps stale velocity; raylib
  `Color` is a cdata reference, so `col.a = 235` mutates the shared constant;
  `DC_AREA=0` is a value, and `if area:` silently loaded area 1.
- **The Python repo is now canonical.** The C tree is frozen as the source
  spec and the reference binary; the assets, captures, research docs and
  checkers were copied here, so this repository is self-contained. All new
  work lands in `dcpy/`.

## Session 2026-11-02 (part 6) — the Hippogriff fight is real in area 1

- **The extractor now types species `$09` as a boss.** `SPECIES_KIND_MAP` says
  `0x09: "boss"` and the older per-screen path reuses the same map instead of
  its own three-entry dict. `room_area1.json` was regenerated: the object at
  (1920, 168) is `type: boss`, and the old plain "exit" trigger is gone. The
  ROM gate `$81:97DA` (area 1 -> 2) is what opens the way; the port's boss gate
  keeps it shut while `boss_alive` is true.
- **The root cause of every fragmented 16x16 bake was in `parse_oam`.** The
  ninth tile-number bit lives in OAM *attribute* bit 0 (`(oam1 >> 8) & 1`), but
  the code read the tile byte's LSB. Every 16x16 sprite whose attributes have
  bit 0 set (the Hippogriff's whole sheet) composed as scattered tiles. Fixed;
  `match_group_from_oam.verify` now compares the low 8 bits because the ninth
  bit is part of the OAM entry, not the base.
- **The art was baked pose by pose from the take.** The guest reloads OBJ CHR
  per animation frame, so composing the nine frames of `$8B` group `$0E` with
  one capture's VRAM always left fragments. Each pose now comes from the frame
  where the guest actually drew it, with that frame's own VRAM/CGRAM:
  hover at gframe 11146 (group frame 0), feather volley at 11374 (frame 8) and
  the death/rubble pose at 11500 (frame 7). The swoop and the stone statue are
  the reference sheet's row-1 charge pose and top-row statue, because those
  two frames never draw in this take. `tools/dc_extract/bake_hippogriff.py
  --poses <dir>` rebuilds the whole entry from those three pose dumps; it
  reproduces the committed sheet byte for byte.
- **`species_anim["09"]`** has five frames (hover, volley, swoop, statue,
  rubble) with states `0:[hover] 1:[volley] 2/3:[swoop] 4:[volley]
  5:[rubble] 6:[statue]`. The kill now holds the rubble pose for 90 frames
  before the slot frees, like the take's last three seconds.
  `DC_SPECIES_FRAMES` went 8 -> 10 (the ROM has nine poses plus the statue).
- **The stone phase was one frame long outside the test hook.** The state-6
  wake test had `|| getenv("DC_BOSS_STATUE") == NULL`, so unless the hook was
  set he woke on the next frame. Now only a headbutt (dash, < 30 px) or the
  260-frame boredom timer wakes him. Measured in the port: two 260-frame stone
  windows in a 1500-frame fight, shots spark off.
- **Area 1 no longer ends the stage.** `Game_CompleteArea(1)` granted the Air
  Crest and froze the room; the original opens the way to the slope. The boss
  death now keeps control when the room has a gate and is area 1, and the
  player walks to x >= 2008 -> `Game_BeginTransition(2)`.
- **New gate**: `tools/check_hippogriff.py` (wired into `run_regression.py`)
  asserts the species-9 boss spawns at (1920,168), the stone phase lasts >=120
  frames, a 1 HP hit kills him, and the room reaches area 2 with the game still
  in `GAME_PLAYING`. `check_bosses.py` also lists area 1 now.

Verified: `DC_DEBUG_OBJ` shows slot 8 type 6 species 9; screenshots show the
whole griffin hovering and the stone statue; a default-hp run takes his HP
8 -> 6 across dive/hover/volley cycles and two stone windows; `check_hippogriff`
passes; `run_regression.py` PASS.

## Session 2026-11-02 (part 4) — stage 1 against the full playthrough capture

The owner recorded a complete stage-1 run (`DemonsCrestSNESRecomp/build/captures/
rec_stage1_full_play`, 23 112 frames from the Somulo fight to the map) and two
saves (`build/saves/arma_boss.sav`, `world_map.sav`).

- **Wall cling was implemented, but not like the console.** `$80:E389` clings
  automatically (the handler only probes both walls), and `$E3FD` *slides*:
  `$22 += 3` per frame, capped at `0x00C0` (0.75 px/frame); B jumps off,
  Down releases, and the cling ends when the wall does. The port required
  `input->special_held` and froze `vy = 0`. Both fixed; `DC_DEMO=40` walks into
  the tall column at area 3's x=336..351 and `tools/check_wall_cling.py` asserts
  87 frames of state 8, x fixed, y 352.7 -> 393.5 and the 0.750 cap.
- **The map is not presented like the original.** The port draws the 1024x1024
  map texture through a rotating `Camera2D` — zoom and rotation, but no
  perspective: the view is top-down and screen-flat. The original is a Mode 7
  plane with a horizon, rows shrinking with distance, and the winged cursor at
  the bottom (`docs/sprites/animated/map_mode7_animated.mp4`, 400x348, 104
  frames). Side-by-side: `docs/map_compare.png`.
- **The Hippogriff fight is missing from area 1.** `extract.py` types species
  `$09` as `"exit"` (`type_by_species`), so the object at x=1920 is only a
  trigger: `Objects_Init` never spawns it, and the port's own species-`0x09`
  Hippogriff AI (statue phase and all) is unreachable. `species_anim.json` has
  no entry for species 9 either, so even a forced spawn would use the fallback
  sheet. The ROM's `$81:97DA` gate for area 1 (target 2) is consistent with a
  boss gate, not an exit marker.
- **Area 3 has no way to the map after Arma.** The boss object is there
  (species `$A5`, x=856, y=1180, art present) but `gate_next_area` is `-1` and
  the room has no transitions, so the kill cannot advance. `Game_CompleteArea`
  maps area 3 to `CREST_TIME`; the original awards the **Earth Crest** there and
  returns to the map, which is the player's first contact with it.
- Area 2's edge door to area 3 (x=2040) is present, so cemetery -> slope ->
  abyss works in data.
- **The trace build (debug server) is rebuilt.** The checkout had lost
  `build-trace/`, so the take cannot be replayed for WRAM. Recreate it with:

  ```sh
  cd DemonsCrestSNESRecomp
  cmake -S . -B build-trace -G Ninja -DCMAKE_BUILD_TYPE=Release \
        -DSNESRECOMP_SDL_BACKEND=SDL2 -DSNESRECOMP_ENABLE_TRACE=ON
  cmake --build build-trace -j4
  ```

  It needed one local fix: `snesrecomp/runner/src/debug_server.c` used `mkdir`
  without `<sys/stat.h>` (GCC 15 rejects the implicit declaration). Verified:
  the server answers `frame` and `read_ram 8d 1` on
  `SNESRECOMP_DEBUG_PORT=4450`.
- **A full take must start at boot to be replayable.**
  `rec_stage1_full_play` starts at guest frame 964 (a manual start), and
  replaying it lands on the title/options screen instead of the Somulo fight
  (`replay_capture.py`, 24 076 samples, ref frame 4964 does not match the
  recorded frame 4000). Record the next one in `build-trace/` with
  `SNESREC_AUTORECORD=1` and `SNESREC_INPUT_ONLY=1` (the latter skips the 3.9 GB
  of BMPs), e.g.
  `SNESREC_AUTORECORD=1 SNESREC_INPUT_ONLY=1 SNESREC_RECORD_DIR=captures/rec_stage1_trace ./DemonsCrestSNESRecomp "../../roms/Demon's Crest (USA).sfc"`.

## Session 2026-11-03 (part 2) — Arma -> Earth Crest -> the map, in Mode 7

- **Arma was 1024 px below his own fight.** `room_area3.json` had the boss at
  (856, 1180) — inside the solid block mass at the bottom of the room — while
  `arma_boss.sav` has `$008D = 6`, camera y = 0, the player at (681, 156) and
  the live Arma at **(856, 151)**. The (856, 1180) value came from the object
  list's row-offset encoding; `tools/check_bosses.py` now carries the save's
  numbers and `apply_boss_table.py` re-applies them.
- **Arma now runs the ROM's state machine.** Handler `BE:E6EE`, dispatch table
  `BE:E731` (the `$05` byte is a *byte offset*, so states are 0,2,4 … 24; 13
  entries, `_idx = X / 2` in the recompiled dispatch). Ported: 0 entrance,
  2 hover, 4 approach, 6 volley, 8 dive, 10 fall, 12 turn, 14 rise, 24 flee,
  with the ROM's constants (`$00A0`, `$0280`, gravity `$28`, clamp `$0100`,
  the 81 px hover post measured from the save). The oracle recording's cycle
  (2 -> 6 -> 2 -> 8 -> 10 -> 12 -> 14 -> 2) is what the port runs.
  `docs/ARMA_AI.md` lists every state, the attack chooser at `BE:ED13` (still
  undecoded: it keys off `$809D8E`'s direction code) and what is not ported
  (states 16/18/20/22 and the `$A6`/`$A7`/`$A8` spawns).
- **The `$F0` gate is a map marker, not an area id.** New
  `tools/dc_extract/apply_gate_table.py` re-reads `$81:97DA` for all 113 rooms,
  resolves only verified markers ($F0 -> area 94, from `world_map.sav`), records
  `gate_marker`/`gate_entry` for the rest and leaves unverified ones closed.
  `build_assets.sh` runs it after the boss table.
- **`Game_CompleteArea(3)` grants CREST_EARTH** (was `CREST_TIME`) and keeps
  the player in control (the room has a gate): the crest text plays and the
  player walks out to area 94. Area 0 no longer grants a crest — the colosseum
  intro has none, and the duplicate was hiding Arma's drop.
- **Area 94 is presented as a Mode 7 plane, and entering it opens the map.**
  `dcpy/mode7.py` holds the projection (horizon 37, focal 46 500, depth clamp
  2048, per-row texture slices with horizontal wrap); `_draw_world_map_view`
  draws the sky, the plane and the projected nodes, with the winged cursor at
  the bottom centre. `game_update_transition`/`game_init` switch to
  `GAME_OVERWORLD` when area 94 finishes loading, so the raw room (whose
  128x128 BG1 repeats) is never shown. The map texture is the one bilinear
  texture, because a single dark row in the bake became a black scanline.
- **New gates**: `tools/check_arma.py` (spawn, states 6/8/10/12, hp to 0, flee,
  Earth Crest, fade to area 94, final mode 5) and `tools/check_map_mode7.py`
  (projection invariants + a rendered frame with a dark sky band and a
  continuous ground plane). Both are wired into `tools/run_regression.py`.
- New hooks: `DC_DEMO=16` (stand and shoot, then walk right — the boss-then-gate
  demo) and `DC_DIALOGUE_AUTO=<frames>` (page text without a controller).

## NEXT SESSION (updated)

**Plan of record: [`docs/NEXT_STEPS.md`](NEXT_STEPS.md)** — the ordered queue to
finish the game, with the coverage numbers (`python3 tools/report_coverage.py`)
and the acceptance test for each step. Read that first; this block is only the
short version.

0. **Commit the tree.** `HEAD` is `c666823` with 11 modified + 7 new files
   (Arma AI, crest, Mode 7 map and their checkers). Regression is green; commit
   it before touching anything else.
1. ~~Arma -> Earth Crest -> the map~~ — done, gated by `check_arma.py`.
2. ~~The map in Mode 7~~ — the plane, horizon and cursor are in and gated by
   `check_map_mode7.py`. Still open: the plane's **rotation** (the reference
   shows none, so this is only needed if a later stage turns the map), the
   horizon smear from the depth clamp, and the map's own interaction (nodes are
   projected but landing still uses the old node list).
3. **Object coverage** — the extractor types 262 of the 853 objects the ROM
   lists and drops 591 (63 species). `tools/report_coverage.py` prints it. Fix
   the extractor first (unknown species must still be placed), then port the 20
   most common species, which are 451 of the 591.
4. **Arma's remaining states** — 16/18/20/22 and the `$A6`/`$A7`/`$A8` spawns,
   plus the crest-drop object. See `docs/ARMA_AI.md`.
5. **The 14 `$72` flames in area 1** are still dropped by the extractor.

Tools that answer questions without guessing:

- `tools/oracle/trace_stage.py save <sav>` / `replay <take>` dumps
  `gframe,area8d,area,state,sub,x,y,species` from the trace build.
- The trace build exists again at `DemonsCrestSNESRecomp/build-trace/` (recipe
  and the `<sys/stat.h>` fix are in part 5). The replayable take is
  `build-trace/captures/rec_stage1_trace/rec_20261102_193944` (20 667 samples,
  input-only, starts at gframe 1).

## Session 2026-11-02 (part 5) — the boot-start take confirms the stage-1 gaps

The owner re-recorded from boot in `build-trace` (`rec_20261102_193944`, 20 667
samples, input-only) and it replays exactly. Sampling `$008D`, the player task
and the 26 object slots every 20 frames (`/tmp/stage1_trace/trace.csv`) gives
the whole run:

| gframe | `$008D` | room |
|---|---|---|
| 1..601 | `$00` | boot / title |
| 621..1121 | `$A0` | intro menu cutscene (area 80) |
| 1141..4621 | `$00` | colosseum, Somulo (`$33`) |
| 4641..6741 | `$22` | second colosseum room (area 17) |
| 6761..12061 | `$02` | **murkland-cemetery (area 1)** |
| 12081..14461 | `$04` | murkland-slope (area 2) |
| 14481..20661 | `$06` | murkland-abyss (area 3) |

- **The Hippogriff is real and lives in area 1**: species `$09` is in the pool
  from gframe 8841 to 11741, at the cemetery's far end (the player reaches
  x=1933). The 14 flame objects (`$72`) are there too (7141..9441 in the pool).
  Both are dropped by the port's extractor (`$09` typed `exit`, `$72` unknown).
- **Wall cling is used in the abyss**: player state `$05 = 8` appears in 30
  samples of area 3 (and a few in area 2), which matches the fixed behaviour.
- **Arma's save**: `arma_boss.sav` is area 3 with the player at (681, 156) and
  slot 8 = species `$A5` at (856, 151), plus its `$8B` companion at the same
  spot; the arena is one screen at the room's bottom. The port's boss object is
  at (856, 1180), so its y is not the save's y (different origin) - the fight
  renders in the right place, but the spawn record deserves a second look.
- The sampling is now a tool, not a scratch script: `tools/oracle/trace_stage.py`
  has `save <file.sav>` (resume a save, run N frames, dump area/player/pool) and
  `replay <take>` (replay an input-only take and sample every N frames). Both
  write `gframe,area8d,area,state,sub,x,y,species`.
- **The map is a room, not a menu**: `world_map.sav` has `$008D = $BC` (area 94)
  with the player at (896, 156). `room_area94.json` is 1024x1024 with a 128x128
  BG1. Loading it as a normal room renders repeating garbage tiles (the area is
  drawn with Mode 7), which is why the port bakes a texture and fakes the view.

## Session 2026-11-02 (part 3) — the species `$67` ghoul runs its ROM machine

- **`GhoulUpdate` in `src/object.c` replaces the hand-written approximation.**
  It follows `$83:AF74` exactly: five states (`$AF89`, `$B065`, `$B0E4`, `$B1AF`,
  `$B249`) with four substates each (the tables are indexed by even byte
  offsets), the ROM's launch speeds (`0x0050` / `0x0398` / `0x04D0`, long hop
  `0x0120` / `0x0540`), gravity `0x0040`, the `-9` lift and `+7` snap, the
  32/64/32 volley cadence with three children, and the `$B2E8` range check.
  Full table and provenance: `docs/GHOUL_AI.md`.
- **The spit is a child, not a fireball.** `$B14F` allocates another `$67` with
  `$05 = 6` (it dives at the player and despawns); the port reuses
  `OBJECT_ENEMY_SHOT`, which already does that.
- **Verified against the live oracle**: an injected `$67` in area 1 sampled for
  300 frames shows `state 4 (32 -> 3x64 -> 32) -> state 0 (windup 3, airborne,
  land 6)` with `vx = 0x50` and `vy` starting at `0x398` and gaining `0x40` per
  frame. The port reproduces the same order in `DC_TRACE_OBJECTS`
  (`4 until frame 257, 0 from 257, 2 from 401`) and its children damage the
  player again (contact damage had to keep running after the species dispatch).
- `DC_DEBUG_GHOUL=1` prints state/substate/phase/position per ghoul per frame.
- Still approximate, and listed as such in `docs/GHOUL_AI.md`: the `$80F81D`
  animation streams are mapped onto the baked poses, the `$DEA2` idle picker is
  a deterministic rotation, and the `$DE8F/$DE93/$DE9B` pacing tables and
  `$DEB2/$DEBA/$DEC2` distance bands are not transcribed byte for byte.

## Session 2026-11-02 (part 2) — MVP 2 starts: room-change fade (done)

- **Room changes now fade like the console.** Measured on the oracle from
  `lvl_I_murkland-slope_before_door` (hold right, read `inidisp` from the
  per-frame ring): **28 frames 15→0, 64 frames black, 28 frames →15** — 120
  frames total, with the room load inside the black stretch. The exact tables
  are in `src/game.c` (`kFadeOut`/`kFadeIn`); `Game_BeginTransition` starts it,
  `Game_UpdateTransition` freezes the simulation and swaps the area on the first
  black frame.
- `Render_DrawFade()` moved out of `Render_Game` to the end of `Game_Render`, so
  the HUD, the area banner and dialogue dim with the world — INIDISP dims the
  whole PPU output. A black frame now measures **mean 0.0, max 0**; before the
  fix the HUD stayed lit (max 235) through the fade.
- New gate: `tools/check_transition_fade.py` (area 1 exit object, `DC_TRACE_FADE`)
  asserts the three stretches and that the area flips 1→2 inside the black hold.
  Wired into `tools/run_regression.py`.
- Facts established while scoping Area 1: its `$81:981A` transition list is
  **empty** (pointer `$989A`, count 0), so the room's only exit is the species
  `$09` exit object at x=1920 → `gate_next_area` 2. The port already performed
  that transition; what was missing was the fade, not the link.

## Session 2026-11-02 — ROM audio (spike done) (read this first)

> **Route 1 verdict (do not retry the replay).** Running the ROM's own SPC700
> driver inside the port was pushed to its end and closed by measurement: a
> native port has no 65C816 to stay in lockstep with, and the driver's boot is a
> byte-by-byte IPL handshake whose *timing is part of the data*. Recorded streams
> reproduce neither the states nor the audio (sample-index replay boots the
> driver and goes silent with a diverged ARAM; exact cycle-stamp replay derails;
> a +16..+4096 cycle shift sweep boots nothing). The clocks were ruled out
> (cycles/produced is exactly 32.0000). Route 1 needs lockstep CPU emulation, a
> state format richer than `.spc`, or nothing at all. All numbers, tables and the
> three options are in `docs/AUDIO_PLAN.md`. **Pre-rendered WAV is the shipped,
> verified path.**
>
> **MVP 2 is in progress.** The room-change fade is done and gated (see the
> first section). Still on the paddle: the authentic species `$67` ghoul state
> machine (`$83:AF19` init, `$83:AF74` update, states through `$B249`), then the
> stage boss; after that the dark rooms (BG2 missing in ~33 rooms) and the retail
> password (`QFFF KNRR DDLR XGTQ`, see `docs/LORE.md`).

- **The colosseum theme now plays from the ROM's own audio.** Area 0's track is
  captured from the oracle's S-DSP output, cut to its measured loop and played
  through `LoadMusicStream`. Full detail and numbers in `docs/AUDIO_PLAN.md`.
  - `src/audio.c` loads `<assets>/audio/<track>.wav` and falls back to the
    procedural loop only when the file is absent, so a tree without audio still
    runs and `DC_NO_AUDIO=1` is unchanged.
  - Asset: `assets/generated/audio/music_boss.wav`, 32,040 Hz stereo,
    **40.941 s**, RMS 1,778, peak 9,502. Loop seam 210.5 against a typical
    adjacent-sample step of 415.1 (**0.51×**), i.e. no click and no crossfade.
  - Measured in a headless run with a null ALSA PCM: the stream loads as `ROM`,
    the clock advances, and it crosses the boundary at `t=40.875 → 0.553`.
- **The `.spc` route was tried first and does not work for this driver.** The
  dump itself is fine (`spc_dump` → valid v0.30, area 0 verified through
  `$008D`), and `tools/audio/spc_render` renders it with the oracle's own
  SPC700+DSP cores — but the driver plays ~2 s and then executes data, halting
  on `STOP` at `$FFB5`. Six dumps at different frames behave identically, the
  timer is running at load (target 64, counter advancing), replaying the
  captured CPU→APU port writes does not help, and the **live** game never
  executes that STOP (`SNESRECOMP_SPC_TRACE=1`, 600 frames, zero HALTs). The
  driver needs the CPU behind it. The tools and the dump are kept for the day
  the dependency is decoded; `docs/AUDIO_PLAN.md` records the evidence.
- **Music-only capture**: area 0's save is mid-boss-fight, so the capture
  neutralises the object pool (`$1080`, stride `$50`, 26 slots) — zeroing each
  slot's active byte removes the enemies that trigger the roars. Peak 25,121 →
  11,043, RMS steady ~1,778.
- **New tools** (all dev-time, nothing ships): `tools/audio/dump_spc.py`
  (`.spc` + port traffic + provenance), `tools/audio/spc_render.c` +
  `build_audio_tools.sh` (offline `.spc` render + SPC PC tracer, and the
  ROM/ARAM APU host),
  `tools/audio/capture_music.py` (live DSP capture with the object pool
  neutralised), `tools/audio/wav_loop.c` (period search + seam-snapped cut),
  `tools/audio/make_music_asset.py` (capture → loop → asset + manifest),
  `tools/check_audio_assets.py` (asset/playback/determinism, wired into
  `tools/run_regression.py`; 77 = skip when no audio is built).
- `tools/build_assets.sh` gained the music step (reuses `captures/audio/`,
  captures from the oracle otherwise, skips cleanly without either;
  `--no-audio` disables). Track specs: `tools/audio/music_tracks.json`.
- Debug hooks: `DC_AUDIO_DEBUG=1` prints which file each track loaded from
  (`ROM` vs `procedural`); `DC_AUDIO_PROBE=1` prints
  `audio: probe track= rom= time= playing=` every 60 frames.
- Still procedural: the seven **SFX** (next step), and the track map is still
  per game state (`TITLE/STAGE/BOSS/ENDING`), not per area.

## Session 2026-11-02 — AI character pipeline (planning + tooling, no model trained)

- **`docs/AI_CHARACTER_PIPELINE.md` is the plan for generating new characters**
  (fan-game content, not ROM art) with the RTX 5060 Ti box at `192.168.0.21`.
  The verdict and the numbers are in the doc; the summary is that the model
  drafts and a deterministic tool constrains, because the engine needs ≤64 px,
  ≤15 opaque colours, binary alpha and foot anchors.
- **Two new tools, both verified by running them:**
  - `tools/gen/harvest_dataset.py` cuts `docs/sprites` into training crops using
    the *same* measured pose boxes as `bake_player_forms.py`: **211 crops** from
    the six form sheets in 14 s, **525** approximate component crops from the
    enemy sheets in 265 s (~6 % junk, sampled and measured), integer
    nearest-neighbour upscaling, captions and palette variants.
  - `tools/gen/pixelize.py` converts any image into a legal sprite: background
    key, median-cut palette snapped to SNES BGR555, despeckle, binary alpha,
    foot anchors, 8x8 tile padding, JSON sidecar, and a **non-zero exit** on
    >15 colours, >64 px, non-binary alpha or >6 blobs.
- **Engine budgets that bound the pipeline** (read from the source, not assumed):
  `DC_SPECIES_FRAMES 8`, `DC_STATE_FRAMES 8`, `DC_SPECIES_MAX 64`,
  `player_forms[6]`, `DC_ANIM_MAX_STEPS 64`. New content can use species ids
  ≥ `0x100` (`Assets_SpeciesSheet` compares an `int`; ROM species are a byte).
- **The GPU box is reachable and now trains:** `ssh -i ~/.ssh/id_ed25519_hermes
  moop@192.168.0.21` works. Box: `moopc`, Ubuntu 26.04.1, Python 3.14.4, driver
  595.99.02 (CUDA 13.2), RTX 5060 Ti 16,311 MiB, cap `(12, 0)`.
  - **Training venv** `/Data/ml/kohya-venv` (torch 2.14.1+cu130, kohya
    sd-scripts, bitsandbytes 0.50.2), runner `/Data/ml/train_dcrest.sh`,
    dataset config `/Data/ml/datasets/dcrest.toml`, outputs in `/Data/ml/runs`.
    ComfyUI's own venv was left untouched.
  - **Measured on this card**: latent cache 1,472 images @512 in 8.5 min
    (2.9 img/s, disk-cached for later runs); training batch 2 / 512 px / bf16 /
    AdamW8bit at **1.13-1.34 it/s** (1,600 steps ≈ 20-24 min); VRAM 9.6 of
    16.3 GB at ~90 W, i.e. the dataloader, not memory, is the bottleneck.
  - **No model download was needed**: `/Data/ComfyUI/models/checkpoints` already
    has five SDXL Illustrious finetunes (base used: `ilustmix_v9`), plus
    `illustriousXLLineart_v10` ControlNet and `clip_vision_h`. The `ipadapter`
    folder is empty, so Stage 3's reference route needs one download.
  - Gotcha recorded in the doc: `sd-scripts/requirements.txt` ends in `-e .`, so
    the pip install must run from inside the cloned repo.
- **First style LoRA trained and used end to end** (`/Data/ml/runs`, copied to
  `/Data/ComfyUI/models/loras/`): `dcrest_style_v1`, SDXL base `ilustmix_v9`,
  1,472 crops, dim 32, 1,600 steps in **19m47s** at 1.35 it/s, final loss 0.0433,
  170 MB, checkpoints at 400/800/1200/1600.
  - Verified generation through ComfyUI's HTTP API with
    `tools/gen/workflow_sdxl_lora_api.json`: 4/4 images came back as single
    pixel-art creatures (hard pixels, flat background), no sheets or captions.
  - **Step 800 is the better checkpoint for sprites**: at 48 px the 1,600-step
    LoRA aliases its highlights into sparkle pixels while step 800 keeps broader,
    cleaner clusters. Evaluate at the target size, not at 1024.
  - Real output → `pixelize.py` → **56×48, 15 colours, binary alpha, one blob,
    anchor (27, 48)**; a 32 px version was noisier.
- **First complete enemy exists: species `0x120` ("grave imp")** in
  `assets/authored/` (7 frames, `species_entries.json`), built without a single
  new download:
  - poses came from the game itself (`tools/gen/pose_refs.py --species 0x2c`,
    the Scavenger Demon's four measured walk boxes) and were repainted with
    img2img + the installed SDXL lineart ControlNet + LoRA step 800;
  - **denoise 0.50 / control 0.85** kept the four walk poses distinct and the
    hurt frame on-model; the first attempt (0.60/0.65) flattened the walk into
    one stance and produced a different creature for the hurt frame;
  - all seven frames were constrained with **one locked 15-colour palette**
    (first frame's palette fed back through `--palette`), giving 32×40 sprites,
    binary alpha, one blob, anchor (14, 40);
  - `compose_species.py` wrote the entry and a scratch `species_anim.json` +
    `audit_sprites.py --strict` reports **1 species, 7 frames, 0 errors**.
  - `species_anim.json` is an **object keyed by hex species id**, not a list;
    an array fails the audit with "no 'species' object". The doc's first merge
    snippet had this wrong and is corrected.
  - Not in a room yet: a species entry only makes the art loadable, an area
    still needs an object placed with that id.
- Nothing has been trained and no generated art is in the tree; `assets/authored/`
  is the intended home for it (with provenance JSON), never `assets/generated/`.

## Session 2026-11-01 — what changed

- **The regression suite is green**: `tools/run_regression.py` → PASS (exit 0),
  demos 6/7/9/10/11/12/13, boss data + runtime, boss defeat, multi-area loads.
  It started the session with 14 failures. Root causes fixed:
  - boss objects for 11 rooms (table now applied by
    `tools/dc_extract/apply_boss_table.py`, including `$96` placeholder removal
    in areas 52/54 and the colosseum Somulo at `(380,170)`);
  - the seven save-observed doors (`tools/dc_extract/apply_door_table.py`);
  - town NPC dialogue: `Text_Find()` now normalises ROM punctuation (`[` is an
    apostrophe), so `HAVEN'T SEEN YOU` matches `I HAVEN[T SEEN YOU`; and the
    city room needed an `npc` object (`tools/dc_extract/apply_npc_table.py`);
  - the passive Somulo duel (`DC_BOSS_NO_ATTACK`) now holds a hittable idle, so
    the scripted six hits land and the gate to area 34 opens.
- **MVP 1 (the Somulo colosseum fight) is done and machine-checked.**
  `tools/check_mvp_somulo.py` asserts the beats from the port's own traces and
  runs inside `tools/run_regression.py`:
  - the boss object stays planted (`y` used to drift to the world bottom, 256,
    while idle — the "sliding image" the user reported);
  - the opening runs as four ordered phases (150 establishing + 70 approach +
    280 walk-in + 110 roar) with the player's x frozen for all 610 frames;
  - the blind walk (state 7) precedes the first fireball;
  - the first death blow **faints** him (state 6, invulnerable, 180 frames), he
    returns with **3 hp** and cannot chase (substate 3), and three more hits
    collapse him. `DC_BOSS_SKIP_FAINT=1` keeps the old one-hit kill for gate
    tests.
  The fight structure and the entrance script come from the Ghosts'n Goblins
  wiki and are transcribed in `docs/LORE.md` and `docs/MVP_SOMULO.md`.
- **Somulo has his own art, and it is built, not patched.** The walk cycle is
  baked from `docs/reference/somulo_walk.gif` (16 GIF frames → 10 unique poses →
  the 8-frame subset that maximises silhouette delta), anchored per frame on the
  art's own feet. `build_assets.sh` does both steps, so a from-scratch rebuild
  reproduces the placement (verified: sprite bottom 177 against a floor of 176).
  `tools/verify_frame_match.py` proves the engine advances the cycle by matching
  screenshots against the baked PNGs pixel for pixel.
  **Still missing:** head-lowered fire, roar and faint poses — they are not in the
  GIF, and the ROM's own Somulo OAM draws only head+neck (the body hides behind
  the pillar) in a different style, so states 1/2/5 fall back to frame 0.
- **Two asset bugs behind the "black rectangles" in the arena:**
  - the room's BG1 was 3 rows (24 px) taller than its own world box, drawn from
    row 0, so the whole scene sat 24 px lower than collision — the characters
    looked airborne. `tools/dc_extract/normalize_rooms.py` now trims that in
    every build (it fires on area 0 every time, because extraction re-adds the
    padding).
  - BG1 referenced palette-7 tile 15 in **674 cells** and that tile was empty in
    the ROM-segment atlas. `tools/dc_extract/bake_bg_atlas_from_capture.py`
    rebakes the area's atlases from the guest's own VRAM at the guest's CHR base;
    the wall is continuous now (pure black 24% → 19%, the remainder being the
    real void under the floor).
- **Assets are reproducible from the ROM**: `tools/build_assets.sh` runs
  extract → animations → font/endings → boss table → NPC table → door table,
  and the regression passes on the freshly built tree. The old directory was a
  chain of unscripted manual patches.
- **Rendering bug fixed**: `DrawLayer()` double-subtracted the reference camera
  from BG1. BG1 is world-space; every room whose reference camera y was not 0
  (Phalanx fortress, ice palace, colosseum interior) drew its tilemap off-screen
  — a black void with the player floating. Area 33 went from 95.2% to 59.4%
  black against the original frame's 58.9%.
- **Save → room identification**: `tools/oracle/map_saves_to_areas.py` matches a
  save's live BG1 against every `room_areaN.json` (exact 32×32 comparison,
  `$008D`'s stage id as a hint). 45 areas match at 1.000.
  `tools/oracle/bake_area_captures.py` turns that into per-area BG2 captures
  (score ≥ 0.99 only).
- **Forced area loading** (this session): `$008D` is only consumed by the
  room-load task, and only *after the fade-out*, so writing `$008D = 2N` while a
  transition is in flight loads area N. `tools/oracle/load_area.py` does that and
  verifies the result against the target room's BG1; `tools/oracle/sweep_missing_
  areas.py` walks the whole missing set and records the ones that verify.
  **94 areas captured, 65 rooms with a non-empty BG2** (28 at session start).
  29 of those captures contain zero BG2 cells in the raw VRAM, so their rooms
  either have no BG2 or draw the backdrop by another mechanism — that is the
  ceiling of this approach, not a capture bug.
- Still open: 19 areas that the retarget cannot reach (the frame resolves to the
  door's natural destination), per-species AI (the `$82:8300` species table holds
  `JSL` stubs, so each species is code to port, not data to read), ROM audio, and
  the retail password/SRAM algorithm. `docs/AUTOPILOT_PLAN.md` tracks the queue.
- **Dark rooms are a BG2 problem, not an atlas one** (measured after the MVP 1
  work). Area 43 is 92.3% black; rebaking its atlases from its own capture
  changed nothing, and its BG1 is sparse *by data* (19% non-zero cells). What is
  actually broken there is that the room does not draw its BG2 at all: the
  captured BG2 has 50% non-zero cells but they sit in **tilemap rows 32..63** of
  a 32x64 map while the layer draws from `origin_y = 64` (rows 8..36), and
  forcing `scroll_y = -192` changed the render not at all. That needs a
  renderer-level debug of the tall-backdrop path, not more capture work.
  The retail password has a verified test vector from the wiki:
  **`QFFF KNRR DDLR XGTQ`** — 16 characters in four groups, which is *not* the
  shape our 10-letter codec produces (`docs/LORE.md`).

This file is the authoritative handoff. It records the final objective, every
implemented piece, every recovered technical detail, the traps already hit, and
the ordered next steps. If work resumes later, read this file first, then
`docs/ROADMAP.md`, then the full-campaign gap plan in
`docs/FULL_CAMPAIGN_PLAN.md`, then the recompilation project's
`docs/NATIVE_PORT_PLAN.md`.

---

## 1. Final objective

Build a **standalone native PC fan game** based on *Demon's Crest*:

- C11 + raylib, no emulator in the shipped game.
- Original game logic is **reimplemented**, not executed as 65816.
- Original assets (maps, tiles, palettes, sprites, animations, audio) are
  extracted from the player's own ROM into a modern data format.
- The original game running in the recompilation project is used as a
  **frame-accurate behavioural oracle** for movement, timing and feel.
- Once the authentic core is stable, add new levels, enemies, story and art on
  top of the same data-driven engine.

The long-term target is a full fan-game campaign. The first concrete target is a
playable **vertical slice** of the graveyard stage.

### What this project is not

- It is not a recompilation of the generated C. `src/gen/*.c` in the recomp
  project is 65816 guest code translated to C, tied to `CpuState`, `cpu_read*`,
  the SNES PPU/APU/DMA and the recomp scheduler. It cannot be linked to raylib
  as game code.
- It is not an emulator front-end. Embedding snesrecomp would preserve the
  original game but force all new content back into 65816.
- It is not a ROM distribution. No ROM or ROM-derived asset is committed.

---

## 2. Current status at a glance

The project is a playable technical foundation, not a finished game.

Working today:

- Native C11 + raylib application builds and runs.
- 256×224 internal render target, integer scaling, 60 Hz presentation.
- Extracted full Area 1 graveyard row (2048×256 px, screens 8/9/10/11 and
  16/17/18/19 from the populated grid row):
  - BG1 tilemap from the ROM block tables,
  - looping BG2 forest backdrop from the capture,
  - per-palette tile atlases,
  - Firebrand and the visible item as composed OAM sprites,
  - 128×16 collision grid from the ROM block attributes,
  - room JSON with spawn/camera/world bounds.
- Firebrand runs the authentic Bank `$80` grounded / jump / hover state machine
  in 8.8 fixed point, walks up/down the decoded slope surface table, and is
  constrained to the full-room bounds.
- Camera follows Firebrand across the full room with deadzones and clamps to
  the level bounds; BG2 wraps horizontally as the camera scrolls.
- Firebrand animation extracted from `save0`:
  - static idle,
  - 6-pose, 46-frame walk cycle,
  - jump rise,
  - hover / fly pose,
  - fall and landing,
  - Y Fireball spit (17 frames) and A Talisman/Spell (31 frames).
- Shot (`Y`) and special (`A`) timers plus landing timers in the player state
  machine.
- 7-slot fireball projectile pool (`src/projectile.c`): original spawn
  offset/velocity, palette-6 OAM animation, pillar and screen-edge despawn.
- 26-slot object pool (`src/object.c`) driven by the Area 1 object list:
  - destructible urns (species `$57`) that shatter on fireball hits,
  - bouncing heart pickups with the `$85:C180` arc and HP heal,
  - first-pass species `$67` ghouls with emerge, chase, contact damage,
    knockback and heart drop.
- BG3 HUD from `save0`: six-point health bar, three crest slots and an active
  spell-slot highlight at the top of the frame.
- Original procedural audio: looping chiptune theme plus jump/land/shoot/break/
  pickup/hurt/enemy-hit SFX; no ROM audio data is used.
- Vertical-slice flow: title screen, pause overlay, Area Clear trigger at the
  object-list exit (`species $09`, x=1920), and restart from title/clear.
- Full-campaign foundation (this session):
  - ROM CHR decompressor (`$80:C2AF`/`$80:C300`) and `$98:C000`/`$98:D000`
    table decoders in `tools/dc_extract/extract.py`.
  - All 113 valid areas from `$81:A291`/`$81:A6D8` extracted into
    `assets/generated/room_area<N>.json` with 2D multi-row/vertical grids,
    full collision grids, spawn records (`$81:A1A9`), transition boxes
    (`$81:981A`) and object lists (`$81:C874`).
  - Per-area BG CHR atlases baked from ROM CHR + ROM palettes
    (`bg_area<N>_pal<P>.png`), loaded on demand per room.
  - OAM metasprite table (`$8B:8000`, decoder from `$80:D9A7`) and real item
    pickup (Crest emblem) / ghoul sprites baked from ROM CHR; the procedural
    heart/enemy placeholders are gone.
  - BG2 per-scanline HDMA parallax bands recovered from `$84:AF65`
    (`BG2HOFS`, channel 1) and rendered as scanline clip bands.
  - Multi-room runtime: `Level_LoadArea`/`Game_TransitionToArea`, bounding-box
    transitions, boss-gated `$81:97DA` exits, and a 113-area room loader.
  - Campaign Area 0 Somulo boss (with HP bar), Area 2 skeleton patrols,
    Area 3/5 bats and wall gargoyles, moving platforms, crest/life-stone
    pickups, gold drops, hazard damage (`attr & 0xE0 == 0x20`), breakable
    terrain (`0x40`), water (`0x60`), and the `$1070` slope acceleration ramp.
  - Six Gargoyle forms (`CREST_BASE`, `EARTH`, `AIR`, `WATER`, `TIME`,
    `ULTIMATE`) with form tints, Earth/Ultimate shoulder tackle, Air free
    flight, Water swimming, Time/Ultimate damage reduction, and a
    `form_next` cycle key.
  - Crest/Item subscreen (`X`/Tab) with form, Fire-Crest element, Talisman,
    Urns, Spells and gold; shop; generated password screen; options volume;
    game over; ending; and a Mode 7-style overworld flight map with stage
    nodes, landing and shop access.
- Per-area BG2 backdrops from oracle frames (this session):
  - `tools/dc_extract/bg2_captures.json` maps an area to a `capture_anim.py`
    frame (`{"areas": {"3": {"dir": "captures/anim", "frame": 20614}}}`);
  - `extract.py` copies that frame's BG2 tilemap into the room document, keeps
    the original BG2-vs-BG1 scroll offset, and bakes the area atlases from the
    capture's VRAM/CGRAM (covers streamed tiles);
  - Areas 1 (`stage_600`) and 3 (`save0`) now render their real backdrops; the
    remaining areas keep a transparent BG2 until a frame is added;
  - the BG2 tilemap is generated by the guest at runtime (`$84:A057` DMAs it
    from WRAM `$7F`, tables `$84:C311/$C312` indexed by `$00F9`; static
    fallback from `$81:8068`), so no raw ROM tilemap table exists to extract.
- Campaign audit tooling (this session):
  - `tools/audit_campaign.py` checks every `room_area<N>.json` for dimension
    mismatches, BG1/collision coverage, BG2 presence, spawn support, object
    bounds and transition/gate targets, and classifies rooms as
    playable/partial/empty;
  - current result: 69 playable, 44 partial, 0 empty, 2 with BG2, 45 rooms with
    at least one structural issue (mostly zero-collision boss/cutscene arenas
    whose floor is not in the block tables);
  - `--strict` fails CI on a structural regression in a playable room.
- Windows build path (this session):
  - CMake gains `-DDC_RAYLIB_ROOT=<dir>` to link a local `libraylib.a` instead
    of fetching raylib 5.5, plus platform link libraries for Win32;
  - `tools/build_windows.ps1` configures/builds against the raylib Windows
    installer (default `C:\raylib\raylib`) and can run the game;
  - verified with raylib 6.2 + MinGW-w64 GCC 16.2; `-j` is avoided by default
    because some Windows shells block the jobserver named pipe used by
    make/ninja;
  - `DC_WINDOW_INFO=1` prints window/render-target size and integer scale.
- Save/options persistence (this session):
  - `Game_SaveProgress`/`Game_LoadProgress` write/read
    `saves/dc_save.json` (override with `DC_SAVE_PATH`) via cJSON: version,
    current area, cleared stages, HP/max HP, Crests and form, Talismans, Fire
    element, Urns, Spells, gold and music volume;
  - autosave on area clear, on entering the overworld and on exit; the title
    menu gains a `CONTINUE` entry only when a save exists (falls back to the
    old four-item menu otherwise, so `DC_DEMO=13` is unchanged);
  - deterministic `DC_RUN_FRAMES` runs never write unless `DC_SAVE_FORCE=1`;
    `DC_NO_SAVE=1` disables the feature and `DC_RESUME=1` boots straight into
    the saved run for headless tests;
  - the regression suite now autosaves in one run and asserts area/max HP/gold
    after resuming in a second run.
- HUD health bar fix (this session): `hud_bar.png` is a brightness mask
  (grey body, pink highlight); the renderer now tints the empty part dark and
  the filled part red instead of drawing the whole bar white.
- Password system (this session): a real 40-bit codec — 10 letters from a
  20-symbol alphabet carrying stages/max HP/crests/form/urns/spells/talismans
  plus an 8-bit FNV-1a checksum — with a letter-entry screen (up/down changes
  the letter, left/right moves, Enter applies, invalid codes are rejected),
  `DC_PASSWORD=<code>` to apply a code at boot and
  `DC_PASSWORD_SELFTEST=1` for a 2000-round-trip CI check. The retail
  encode/decode algorithm is still unknown; this is a stable native format.
- Per-species enemy sprites from injected-object captures (this session):
  `tools/oracle/capture_species.py` writes a minimal object record with `$00`
  bit 0 set into the first object slot, so the guest runs that species' init
  handler and draws it in the current room — no area travel or live-enemy save
  needed. `tools/dc_extract/extract_species.py` finds the object's OAM cluster
  (the world->screen offset is derived from the player's feet anchor because the
  guest restores the BG scroll registers after rendering), composes it with the
  captured CGRAM, deduplicates poses and emits `enemy_<species>_<n>.png` +
  `species_anim.json`. `src/assets.c`/`src/render.c` load and draw those sheets
  per species (with the shared sheet as fallback), replacing the one-size
  enemy sprite for the species whose init is self-contained (urn `$57`,
  pickup `$49`, `$2D`, ghoul `$67`, ...).
- Collision debug overlay (`F1`), FPS (`F3`).
- Per-frame CSV trace output plus `DC_TRACE_PROJECTILES`/`DC_TRACE_OBJECTS`.
- Deterministic demo input modes for screenshots and comparison.
- Oracle tooling:
  - WRAM trace parser,
  - OAM player-sprite parser,
  - native-vs-oracle comparison tool,
  - capture-directory CSV exporter
    (`tools/oracle/export_capture_csv.py`),
  - repeatable probe scripts for the area-2 route and `save0`,
  - debug-server animation capture (`tools/oracle/capture_anim.py`),
  - animation frame baker (`tools/dc_extract/extract_anim.py`),
  - deterministic native regression harness (`tools/run_regression.py`,
    `tools/run_regression.sh`, CTest `regression`).
- Movement constants and state machine recovered from the original Bank `$80`
  player code (`$80:DB00..F310`) and ported to `src/player.c`.
- Movement validated against `save0`:
  - walk speed 1.40 px/frame (`$1020` stays at the `0x0166` cap on flat ground;
    the `0x00B3 → 0x0166` slope ramp is wired behind the `$1070` flag),
  - default SNES controls (`$80:DB00` via `$1E3A..$1E4C`):
    **B** = Jump / Hover toggle, **Y** = Fireball shot,
    **A** = Talisman / Headbutt, **X** = Item/Crest menu,
  - tap jump is an ~11 px / 14-frame hop (initial `$1022 = 0x059C` = 5.61
    px/frame, gravity `$1026 = 0x0038` = 0.21875 px/frame², with `$1022` zeroed
    immediately on B release at `$80:E227`),
  - holding B gives the full jump arc; pressing B again in air toggles
    horizontal Hover (`State 0x06`, `$1022 = 0`, gravity bypassed),
  - 603-frame `save0` replay (`DC_DEMO=6`): max delta `x=0.00 px`,
    `y=0.53 px` (the residual Y is the known idle task oscillation).
- Root causes of two major blockers identified from the ROM:
  - `stage_600` is ROM **Area 1** (`screens 8, 9` = `slots 9, 10`), not Area 2
    (`screens 33, 34`); passing `--area 1 --screens 9,10` yields `1957/2048`
    exact u16 tilemap matches between the ROM block table and VRAM (no tile
    remap exists) and aligns the collision floor (`by=10`, `y=160..175`) and
    stone pillar (`cx=24`, `x=384..399`) with the visuals.
  - Pressing `A` in `save0` captured the 31-frame back-turned wing-spread
    Talisman/Spell invocation pose; pressing `Y` (`$105C`) selects the
    grounded fireball-spit animation (`$1053 = 0x0E`, 17 frames) and spawns a
    projectile in the first free `$1080..$1260` slot via the allocator at
    `$80:F222` (earlier notes referenced `$80:F1FE`). No `save2` is needed.

Not done yet:

- Real species `$67` enemy handler/animations and hurt/death player clips;
  current ghoul and boss art are reused ROM metasprite frames.
- Full talisman inventory/selection sprites and the exact retail HUD wiring
  beyond the HP bar and active slot.
- Per-form player OAM/animations (current forms are palette tints), text and
  cutscenes, the exact retail password algorithm, and retail-format SRAM
  compatibility (the native `saves/dc_save.json` format is in place).
- Remaining bosses and secret areas, full Mode 7 overworld map data, and ROM
  music/SFX extraction or replacement. BG2 backdrops exist for Areas 1 and 3;
  the other areas need one oracle frame each in `bg2_captures.json`.
- Public-release asset replacement / legal packaging.

---

## 3. Repository and environment

```
projetos/opencode/DemonsCrestNativePort
├── CMakeLists.txt
├── README.md
├── LICENSE
├── docs/
│   ├── PROJECT_STATE.md   ← this file
│   ├── FULL_CAMPAIGN_PLAN.md ← full-campaign remaining work
│   └── ROADMAP.md
├── src/
│   ├── main.c
│   ├── game.c / game.h
│   ├── assets.c / assets.h
│   ├── anim.c / anim.h
│   ├── level.c / level.h
│   ├── input.c / input.h
│   ├── player.c / player.h
│   ├── projectile.c / projectile.h
│   ├── object.c / object.h
│   ├── audio.c / audio.h
│   ├── camera.c / camera.h
│   └── render.c / render.h
├── tools/
│   ├── capture_graveyard.sh
│   ├── dc_extract/extract.py
│   ├── dc_extract/extract_anim.py
│   └── oracle/
│       ├── capture_anim.py
│       ├── parse_wram_trace.py
│       ├── parse_player_trace.py
│       ├── compare.py
│       ├── export_capture_csv.py
│       ├── segments_save0_physics.json
│       ├── oracle_walk.script
│       ├── oracle_move.script
│       ├── oracle_physics.script
│       ├── oracle_short.script
│       ├── oracle_control.script
│       ├── oracle_dump.script
│       ├── oracle_late.script
│       ├── oracle_save.script
│       ├── oracle_save_start.script
│       └── oracle_save0_*.script
├── external/cJSON/        vendored, MIT
├── assets/generated/      ROM-derived, git-ignored
├── captures/              recomp dumps, git-ignored
└── build/                 CMake build, git-ignored
```

Environment used:

- Linux, GCC 15.2, CMake 3.20+.
- Windows 11, MinGW-w64 GCC 16.2, CMake 4.5, raylib 6.2 from the raylib Windows
  installer (`C:\raylib\raylib`), using `-DDC_RAYLIB_ROOT` and
  `tools/build_windows.ps1` (verified in this session).
- raylib 5.5 fetched by CMake `FetchContent` on the Linux path.
- Python 3 with Pillow for extraction.
- Git repository initialized; see section 15 for commits.
- The recomp trace build is at
  `DemonsCrestSNESRecomp/build-trace/DemonsCrestSNESRecomp`
  (Windows: `build-trace\DemonsCrestSNESRecomp.exe` with `SDL2.dll` beside it).

---

## 4. Build, run, capture, extract

### Build and run

```sh
cd projetos/opencode/DemonsCrestNativePort
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/demonscrest
```

Windows (offline, local raylib):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/build_windows.ps1
# or directly:
cmake -S . -B build -G "MinGW Makefiles" -DDC_RAYLIB_ROOT=C:\raylib\raylib
cmake --build build
build\demonscrest.exe --assets assets\generated
```

`--assets <dir>` selects a different generated-asset directory.
`DC_WINDOW_INFO=1` prints the window/render-target size and integer scale.

> On a DSH-sandboxed Windows shell the *game* process can only create files
> inside the session workspace, so `DC_TRACE_CSV`/`DC_SCREENSHOT` paths must
> point there. Redirect `TEMP`/`TMP` into the workspace before running
> `tools/run_regression.py`, which writes traces to a temp directory.

### Capture a reference dump from the recomp

```sh
RECOMP_DIR=projetos/opencode/DemonsCrestSNESRecomp \
ROM="projetos/opencode/roms/Demon's Crest (USA).sfc" \
./tools/capture_graveyard.sh
```

Or manually:

```sh
cd projetos/opencode/DemonsCrestSNESRecomp
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
SNESRECOMP_DUMP_DIR=projetos/opencode/DemonsCrestNativePort/captures/graveyard \
./build-trace/DemonsCrestSNESRecomp "projetos/opencode/roms/Demon's Crest (USA).sfc" \
  --script scripts/routes/gameplay.script
```

The extractor needs:

```
captures/graveyard/stage_600.vram.bin
captures/graveyard/stage_600.cgram.bin
captures/graveyard/stage_600.oam.bin
captures/graveyard/stage_600.regs.json
captures/graveyard/stage_600.fb.bmp   (optional, used for palette matching)
```

### Extract assets

```sh
python3 tools/dc_extract/extract.py \
  --rom "projetos/opencode/roms/Demon's Crest (USA).sfc" \
  --dump captures/graveyard \
  --prefix stage_600 \
  --area 1 \
  --screens 9,10 \
  --full-room \
  --out assets/generated
```

`--full-room` emits every screen in the captured grid row (2048×256 px) using
the ROM block tables; without it the extractor keeps the older two-screen
512×256 viewport slice.

> **Important area index note:** The `stage_600` dump is ROM **Area 1**
> (`screens 8, 9` = bottom-row `slots 9, 10`), not `--area 2` (`screens 33, 34`).
> Earlier runs passed `--area 2` because WRAM `$008D == 2` during active
> gameplay — and `$008D` is `2 * area`, so `2` means area **1**. The ROM table
> at `$81:A291` is 0-indexed (`0` = Somulo
> colosseum intro, `1` = Graveyard forest `stage_600`, `2` = Graveyard section
> 2, `3` = Graveyard ruins `save0`). Using `--area 1 --screens 9,10` aligns the
> collision grid and ROM block tables with `stage_600` (`1957/2048` exact u16
> tilemap matches).

Defaults that matter:

- `--player-oam 1-11`
- `--player-palette 2`
- `--item-oam 0`
- `--item-palette 0`
- `--area 1 --screens 9,10` (note: `extract.py` default `--area` should be
  updated from `2` to `1` so omitting `--screens` selects `grid[1][:2] = [9, 10]`)

`--player-palette 2` is not the OAM palette value. OAM says palette 7, but the
game restores CGRAM before the dump; palette 2 is what the PPU actually used
while rendering Firebrand in this capture. This was verified by comparing
candidate palettes against the framebuffer and by visual inspection.

Generated outputs:

```
assets/generated/room.json
assets/generated/room_area0.json ... room_area112.json
assets/generated/bg_area0_pal*.png ... bg_area112_pal*.png
assets/generated/bg_pal0.png ... bg_pal7.png
assets/generated/obj_pal0.png ... obj_pal7.png
assets/generated/player_idle.png
assets/generated/item_00.png
assets/generated/campaign.json
assets/generated/manifest.json
```

`assets/generated/` and `captures/` are git-ignored. They are ROM-derived.

### Capture and extract Firebrand's animations

The animation pipeline uses the trace build's TCP debug server and its
6000-frame per-frame state ring. It drives the guest deterministically, then
queries OAM/CGRAM/VRAM snapshots after the fact; it does not rely on timed
screenshots.

```sh
python3 tools/oracle/capture_anim.py \
  --recomp ../DemonsCrestSNESRecomp \
  --rom "../roms/Demon's Crest (USA).sfc" \
  --save ../saves/save0.sav \
  --out captures/anim

python3 tools/dc_extract/extract_anim.py \
  --dump captures/anim \
  --out assets/generated \
  --clean
```

`capture_anim.py` starts the recomp with `--paused`, resumes a copy of
`save0.sav`, and records:

```
captures/anim/segments.json
captures/anim/f000000.json      OAM, CGRAM, PPU registers, WRAM $1000-$1FFF
captures/anim/f000000.vram.bin  64 KiB VRAM
```

The default route is idle, walk left/right (120 frames each), stop, tap jump,
air, hold jump, hover release, idle, A special, and Y shot. The extractor emits
`player_<clip>_<n>.png` plus `player_anim.json` with per-step anchor and
duration values. The clips are `idle`, `walk`, `jump`, `hover`, `fall`,
`land`, `attack` (Y shot) and `spell` (A). `fly` reuses the hover clip until a
separate fly capture exists. The same pass bakes `fireball_0..n.png` and
`fireball_anim.json` from the palette-6 projectile OAM group.

### Validate Step 3 movement against `save0`

```sh
python3 tools/oracle/capture_anim.py \
  --recomp ../DemonsCrestSNESRecomp \
  --rom "../roms/Demon's Crest (USA).sfc" \
  --save ../saves/save0.sav \
  --segments tools/oracle/segments_save0_physics.json \
  --out captures/phys

python3 tools/oracle/export_capture_csv.py captures/phys -o /tmp/oracle_phys.csv

DC_DEMO=6 DC_RUN_FRAMES=603 DC_TRACE_CSV=/tmp/native_demo6.csv \
  ./build/demonscrest   # add xvfb-run -a when headless

python3 tools/oracle/compare.py /tmp/native_demo6.csv /tmp/oracle_phys.csv \
  --oracle-start 0 --threshold 1.0
```

Expected result: `x=0.00 px`, `y=0.53 px` max delta over 603 frames. The
remaining Y offset is the `$1000` task's idle oscillation (trap #8), not a
physics difference.

---

## 5. Native engine

### Render path

- `RenderTexture2D` at 256×224.
- `TEXTURE_FILTER_POINT`.
- Integer scale in `main.c`, centered with letterboxing.
- `SetTargetFPS(0)` plus VSync; a `GetFrameTime()` accumulator drives
  `Game_Update` at an exact 60 Hz, capped to 0.25 s and 8 catch-up steps to
  avoid a spiral. `DC_RUN_FRAMES` deliberately stays one update per loop so
  traces/screenshots are deterministic.
- Screen is drawn with a vertically flipped source rectangle, as required by
  raylib render textures.

### Modules

- `main.c` — window, asset directory argument, fixed 60 Hz accumulator,
  integer scaling, screenshot/run-frame hooks.
- `game.c` — asset/level/player/camera ownership, title/playing/paused/clear
  state machine, target creation, update, render, trace CSV.
- `assets.c` — loads the eight BG and OBJ palette atlases, player and item
  textures, `player_anim.json`, `fireball_anim.json`; sets point filtering.
- `anim.c` — parses `player_anim.json` and `fireball_anim.json`, loads
  per-clip PNGs plus pre-baked mirrored textures, and exposes clip/step data
  with frame-based durations.
- `level.c` — parses `room.json` with cJSON, stores BG layers, collision,
  camera/play bounds, spawn, player feet offsets and static sprites.
- `input.c` — keyboard/gamepad mapping, edge detection, deterministic `DC_DEMO`
  modes.
- `player.c` — Bank `$80` 8.8 fixed-point grounded/jump/hover state machine,
  collision, bounds, shot/special and landing timers, animation clip/step
  timing.
- `projectile.c` — 7-slot player fireball pool, spawn offset/velocity,
  terrain and viewport despawn.
- `object.c` — 26-slot level object pool: urns, pickups, first-pass enemies,
  `$85:C180` bounce/pickup and fireball hit handling.
- `audio.c` — procedural chiptune music and SFX; silently disabled when the
  audio device is unavailable or in deterministic `DC_RUN_FRAMES` runs.
- `camera.c` — deadzone follow, clamped to level-provided camera bounds.
- `render.c` — BG tile drawing, static sprites, animated player, fireball
  stream, object sprites, BG3 HUD, debug collision overlay.

### Room format (`assets/generated/room.json`)

```json
{
  "name": "area1_full_room",
  "world": { "width": 2048, "height": 256 },
  "camera": {
    "x": 207, "y": 0,
    "min_x": 0, "max_x": 1792,
    "min_y": 0, "max_y": 32
  },
  "play": {
    "min_x": 8, "max_x": 2040,
    "min_y": 22, "max_y": 256
  },
  "bg": [
    {
      "name": "bg2", "map_width": 64, "map_height": 32,
      "scroll_x": 106, "scroll_y": 0,
      "tilemap": [ ... 2048 u16 ... ]
    },
    {
      "name": "bg1", "map_width": 256, "map_height": 32,
      "scroll_x": 207, "scroll_y": 0,
      "tilemap": [ ... 8192 u16 ... ]
    }
  ],
  "collision": { "cell": 16, "width": 128, "height": 16,
                 "attrs": [ ... 2048 u8 ... ] },
  "spawn": { "x": 332, "y": 164 },
  "player": { "texture": "player_idle.png",
              "feet_x": 13, "feet_y": 43 },
  "sprites": [],
  "objects": [
    { "type": "urn", "species": 87, "x": 392, "y": 120 },
    { "type": "enemy", "species": 103, "x": 958, "y": 76 }
  ]
}
```

BG layer order is back-to-front: BG2 first, BG1 second.

The full-room BG1 is 256×32 tiles (2048×256 px) from the populated ROM screen
row. The captured Area 1 grid is 8×2, but the second row is all-zero padding
for this room, so the extractor emits only the populated row. Camera bounds
span the full room; BG2 is the 64×32 captured backdrop and wraps horizontally.
`play` bounds keep Firebrand inside the room.

### Player physics

`src/player.c` now implements the recovered Bank `$80` state machine directly
in 8.8 fixed point:

- Positions/velocities: `x_fx`, `y_fx`, `vy_fx`, `walk_speed_fx` (Q8.8).
  `x`/`y`/`vx`/`vy` are derived floats for the camera, renderer and trace.
- Grounded (`State 0x02`): walk speed stays at the `0x0166` cap on flat ground,
  matching `save0`; direction input moves the 8.8 position by `0x0166` per
  frame. The `0x00B3` first step plus `$80:8B85` 3/256 ramp lives in
  `UpdateWalkSpeed`; the `$1070` terrain probe that selects it is still to be
  wired.
- Floor collision uses `Level_FloorAt`: the cell under the feet is decoded with
  `Level_SurfaceOffset` from the `$80:962B` table, so the player stands at
  `block_top + slope_offset` (spawn is `y=164` on `attr=0x09`).
- Jump (`State 0x04`): pressing B on the ground sets `vy_fx = -0x059C` and
  enters substate 0 without moving that frame. Substates 0→2→4 integrate
  gravity (`0x0038`) before the position update, matching the observed
  `save0` arc. On the first substate-4 frame with B released while rising,
  `vy_fx` is zeroed (`$80:E227`).
- Hover (`State 0x06`): B pressed in air zeroes `vy_fx`, freezes vertical
  motion and bypasses gravity. The next B press returns to `State 0x04`
  substate 4 and falls on the following frame.
- Terminal fall: `0x0600` (6.0 px/frame, y-down).
- Horizontal movement is the original single 8.8 add per frame. Walls are the
  full-solid shapes (`0x01/0x15/0x1A`, half blocks `0x02/0x17`); slope shapes
  are surfaces, not walls, so the player follows them via the floor snap.
- Collision AABB: 12×22 px, feet-centered; ceiling/horizontal probes sample
  the upper body so standing on a block does not count as a wall.
- Player is clamped to `play` bounds.
- Shot (`Y`): plays the captured 17-frame spit animation (idle press frame,
  6-frame pose A, 10-frame pose B) and spawns one fireball by default. Special
  (`A`) plays the captured 31-frame Talisman/Spell clip.
- Landing: the first grounded frame after airtime starts an 8-frame landing
  animation.
- `DC_FLY_DEBUG=1` enables the non-canonical B+Up vertical flight for testing;
  it is off by default so base Gargoyle behaviour matches `save0`.

### Projectiles

`src/projectile.c` ports the first seven player-object slots
(`$1080..$1260`, stride `$50`):

- Spawn on the shot press frame, at `floor(player.x) + 3 * facing` and
  `floor(player.y) - 8`, matching the measured `save0` object slot.
- Horizontal velocity `0x0300` (3.0 px/frame, 8.8 fixed point); vertical
  velocity is zero for the grounded shot.
- One slot is allocated per shot (first free slot, like `$80:F222`); up to
  seven can be active.
- Despawn when the centre leaves the current camera viewport or enters a
  solid collision block (the stone pillar is the reference case).
- The visual is the palette-6 OAM group baked as `fireball_0..8.png` and
  played at one frame per guest frame; it is mirrored for left-facing shots.
- `DC_TRACE_PROJECTILES=path` writes `frame,slot,x,y,vx,age` per active slot.

Recovered original constants and routines (from Bank `$80` player code
`$80:DB00..F310`):

| Value | Original code (`$80`) | Meaning |
|---|---|---|
| `$1020 = 0x00B3` | 0.6992 px/frame (`$80:F0BE`) | initial walk speed on first step frame |
| `$1020 = 0x0166` | 1.3984 px/frame (`$80:F0D0`) | max walk speed cap (accelerated via `$80:8B85`) |
| `$1022 = 0x059C` | 5.6094 px/frame (`$80:E170`) | normal jump initial upward velocity (`0x02CE` underwater) |
| `$1026 = 0x0038` | 0.21875 px/frame² (`$80:E070`, `$80:ED11`, `$80:F306`) | normal Firebrand gravity (`0x002A` = 0.1641 underwater) |
| `0xFA00` | -6.0 px/frame (`$80:8D03`) | terminal fall-speed clamp (`0xFD00` = -3.0 underwater) |
| `$1022 = 0x0000` on B release | `$80:E227` (`STA $22; STA $23`) | variable jump cut: releasing B (`$1059 == 0`) while rising (`$1023 >= 0`) zeroes Y velocity immediately |
| `$1022 = 0x0000` in Hover | `$80:E1A3`, `$80:E29F` (`State 0x06`) | pressing B (`$105A`) in air zeroes Y velocity and bypasses gravity (`$80:F0F2` not called); pressing B again returns to fall (`State 0x04`) |

Key Bank `$80` routines:

- **Pad mapper (`$80:DB00..DB40`)**: reads held pad `$0090` and newly pressed
  pad `$0094` against configurable masks in WRAM:
  - `$1E3A` (default `0x8000` = **B**) → `$1059` (held), `$105A` (pressed): Jump / Hover toggle.
  - `$1E3C` (default `0x4000` = **Y**) → `$105B` (held), `$105C` (pressed): Fireball shot.
  - `$1E3E` (default `0x0080` = **A**) → `$105D` (held), `$105E` (pressed): Talisman / Headbutt.
  - `$1E4C` (default `0x0040` = **X**) → Item / Crest subscreen (`$80:DC12`).
- **State dispatcher (`$80:DB80`)**: `LDX $05; JSR ($E002,X)` where `$1005` is:
  - `0x00` (`$E02A`): Init
  - `0x02` (`$E0EE`): Grounded (idle / walk / land)
  - `0x04` (`$E1DA`): Jump / Fall (substates `0x00`/`0x02` takeoff while `$100F > 0`, `0x04` rising/falling flight)
  - `0x06` (`$E29F`): Hover (horizontal flight, `$1022 = 0`, no gravity)
  - `0x08` (`$E389`): Wall cling
  - `0x12` (`$E4F4`): Fireball attack state entry (in `save0` the grounded
    animation path selects `$1053 = 0x0E` instead)
  - `0x16` (`$EA4A`): Talisman / Spell invocation (animation `0x38`, back-turned wing spread)
  - `0x1A` (`$EC20`): Headbutt
  - `0x1C` (`$EDF1`): Hurt / knockback
  - `0x1E` (`$EEB9`): Death
- **Vertical integrator (`$80:8D03`, called from `$80:F0F2`)**:
  `position += velocity; velocity -= gravity;` then clamp fall speed at `0xFA00`.
- **Horizontal integrator (`$80:8D35`)**:
  `position += velocity`.
- **Player projectile slot allocator (`$80:F222`)**:
  scans the first 7 object slots (`$1080..$1260`, stride `$50`, limit `$12B0`)
  for a free slot (`$0000 == 0`), calls `$82:8D84` to clear it, and initializes
  the spawned object. `$80:F1FE` is a separate object helper, not this
  allocator.

> **Correction on `$85:C1D4`:** Earlier notes cited `$85:C1D4` (`$22 = 0x0400`,
> `$26 = 0x0040`, `$39 = 0x0400`) as the player jump initializer. Full
> disassembly of `$85:C180..C250` proved that routine is actually the **dropped
> heart item bounce and pickup handler** (bounces with decreasing `$39` by
> `0x0100` each floor hit, checks player touch via `$80:9C93`, plays SFX `$58`,
> and increments player HP `$1062` up to max HP `$1E50`). Do not use `$85:C1D4`
> constants for Firebrand.

### Controls

| Action | Keyboard | Gamepad | Original SNES (`$80:DB00`) |
|---|---|---|---|
| Move | Arrows / WASD | D-pad | D-pad (`$0091` bits 0–3) |
| Jump / hover / fly | Z or Space | B (right face) | **B** (`$1E3A` → `$1059`/`$105A`) |
| Fly upward (debug only) | hold jump + Up | hold B + Up | Crest-dependent (not base Gargoyle) |
| Fireball shot | X or J | X / Y (west/top) | **Y** (`$1E3C` → `$105B`/`$105C`) |
| Talisman / Headbutt / Earth dash | C or K | A (south) | **A** (`$1E3E` → `$105D`/`$105E`) |
| Crest/Item subscreen | Tab or I | — | **X** (`$1E4C` → `$80:DC12`) |
| Cycle Gargoyle form | Q / E | L / R | — |
| Start / confirm | Enter | Start | Start |
| Pause / resume | Escape | Back | Start |
| Collision overlay | F1 | — | — |
| FPS | F3 | — | — |

The original SNES default mapping was verified from `$80:DB00..DB40` and `save0`:
**B = Jump/Hover, Y = Fireball shot, A = Talisman/Headbutt, X = Subscreen**.

### Debug / test hooks

| Variable | Effect |
|---|---|
| `DC_RUN_FRAMES=N` | run N updates then exit |
| `DC_SCREENSHOT=name.png` | save last presented frame |
| `DC_TRACE_CSV=path` | per-frame player/camera CSV |
| `DC_TRACE_FADE=path` | per-frame room-change fade CSV (`frame,phase,timer,fade,area`) |
| `DC_DEBUG_GHOUL=1` | per-frame species `$67` state/substate/phase print |
| `DC_DEMO=1` | long walk/jump/fly demo |
| `DC_DEMO=2` | short walk/jump demo |
| `DC_DEMO=3` | mirrors the area-2 physics probe timing |
| `DC_DEMO=4` | tap-jump vs hold-jump comparison |
| `DC_DEMO=5` | animation regression: walk, special, jump, fly |
| `DC_DEMO=6` | exact `save0` Step 3 physics replay (603 frames) |
| `DC_DEMO=7` | projectile demo: right shots into the pillar, long left shot |
| `DC_DEMO=8` | full-room traversal: walk left, then hover right across pillars |
| `DC_DEMO=9` | urn → bouncing heart → heal regression |
| `DC_DEMO=10` | enemy chase/damage/drop regression (pair with `DC_START_X`) |
| `DC_DEMO=11` | Crest-form cycle, Earth dash, Air flight, Aerial shots |
| `DC_DEMO=12` | campaign traversal / boss-gate flow |
| `DC_DEMO=13` | title → NEW GAME → Area 0 flow |
| `DC_START_X` / `DC_START_Y` | spawn override for focused tests |
| `DC_TITLE=1` | force the title screen even with `DC_RUN_FRAMES` |
| `DC_NO_AUDIO=1` | disable audio device/music/SFX |
| `DC_AUDIO_DEBUG=1` | print audio device/music status |
| `DC_AUDIO_FORCE=1` | allow audio during deterministic `DC_RUN_FRAMES` runs |
| `DC_TRACE_OBJECTS=path` | per-frame active object slots CSV |
| `DC_TRACE_PROJECTILES=path` | per-frame active projectile slots CSV |
| `DC_FLY_DEBUG=1` | enable non-canonical B+Up vertical flight |
| `DC_DEBUG_COLLISION=1` | enable the `F1` collision overlay in headless captures |
| `DC_LAYER_MASK=1|2|3` | BG2 only / BG1 only / both |
| `DC_AREA=N` | load `room_areaN.json` instead of `room.json` |
| `DC_CAMPAIGN=1` | enable campaign transitions/overworld progression |
| `DC_STATE=name` | render a menu state (`title`, `overworld`, `subscreen`, `shop`, `password`, `options`, `clear`, `gameover`, `ending`) |
| `DC_BOSS_DEFEATED=1` | skip boss spawns (campaign flow testing) |
| `DC_BOSS_HP=N` | override boss HP |
| `DC_BOSS_PHASE=2` | boot Phalanx directly in its `$8D` second form (smoke test) |
| `DC_GOLD=N` | starting gold for shop/subscreen testing |
| `DC_POTIONS=N` / `DC_SCROLLS=N` | starting Urn/Spell counts |
| `DC_UNLOCK_ALL=1` | unlock all six Gargoyle forms |
| `DC_NO_HDMA=1` | disable the BG2 scanline parallax bands |
| `DC_UNDERWATER=1` | force underwater physics for testing |
| `DC_SAVE_PATH=path` | native save file (default `saves/dc_save.json`) |
| `DC_NO_SAVE=1` | disable save loading/writing |
| `DC_SAVE_FORCE=1` | allow saving inside deterministic `DC_RUN_FRAMES` runs |
| `DC_RESUME=1` | boot into the saved run instead of the title screen |
| `DC_PASSWORD=<code>` | apply a native 10-letter password at boot |
| `DC_PASSWORD_SELFTEST=1` | run 2000 encode/decode round-trips and exit (`0`/`1`) |
| `DC_WINDOW_INFO=1` | print window/render-target size and integer scale |

`DC_SCREENSHOT` is handled by raylib, which writes the basename into the
working directory even when an absolute path is supplied.

Native trace CSV columns:

```
frame,player_x,player_y,vx,vy,state,camera_x,camera_y,hp,max_hp
```

Projectile trace CSV columns (one row per active slot per frame):

```
frame,slot,x,y,vx,age
```

Object trace CSV columns:

```
frame,slot,type,x,y,vx,vy,state,hp,flash,species,flags
```

---

## 6. Asset extraction details

`tools/dc_extract/extract.py` verifies the ROM and bakes one room. It does not
read the ROM at game runtime.

### ROM identity

- File: `Demon's Crest (USA).sfc`
- Size: 2 MiB, unheadered
- Mapping: LoROM, FastROM, cartridge type `$00`, no SRAM, no coprocessor
- CRC32: `e8236ad2`
- SHA-256: `18d40a807d5f88c5b6a1ad849eec7e0f189225d9a1586037c850f6680b5844de`

### Level/object tables used

| Data | Address |
|---|---|
| Area info: set, screen list | `$81:A291` |
| Area grid / width / height | `$81:A6D8` |
| Screens (superblock lists) | `$8F + set`, `$8000 + screen*128` |
| Superblocks | `$92 + set`, `$8000 + super*8` |
| Blocks: 4 tilemap words + attribute | `$95 + set`, `$98:8000 + (set<<12) + block` |
| Object lists | `$81:C874` (normal), `$81:C9D0` (cleared areas) |
| Area exit / boss gate | `$81:97DA`, `$81:80A1` |
| Tile sets (sprite graphics) | `$BD:9953` → `$98:D000` |
| Sprite list per area | `$81:AE11` |
| Palettes per area | `$81:8479` |
| Mid-stage / segment loaders | `$80:BFB5`, `$80:C11B` |
| Tile animation | `$81:C125` |

Stage 1 area table (`$81:A291` / `$81:A6D8`, 0-indexed):

- **Area 0**: Set `0`, grid 3×1 (`screens [1, 2, 3]`) — Intro Somulo colosseum.
- **Area 1**: Set `0`, grid 8×2, 16 screen slots (top row `screens [4, 5, 6, 7,
  12, 13, 14, 15]`, bottom row `screens [8, 9, 10, 11, ...]`) — **Graveyard
  forest starting room (`stage_600` is bottom-row slots `9, 10` = `screens 8,
  9`, starting at scroll `x=207, y=0`)**.
- **Area 2**: Set `0`, grid 8×2, 21 screen slots (`screens [33..43, 55..64]`) —
  Graveyard catacombs / town approach.
- **Area 3**: Set `0`, grid 4×5, 12 screen slots (`screens [51..54, 48..50,
  47, 46, 44, 45, 67]`) — **Graveyard vertical ruins (`save0` is at `screens
  52, 53`, scroll `x=448, y=48`)**.

> **Note:** WRAM `$008D` holds `2 * area` (it is the byte offset the loader
> adds to `$81:A291`), so `2` during active Stage 1 gameplay means **area 1**.
> That was originally misread as area `2`, which caused `stage_600` to be
> extracted with `--area 2` instead of `--area 1`. Always use
> `--area 1 --screens 9,10` for `stage_600`.

### Graphics decoder

At `$98:D000 + id`:

- 24-bit pointer to compressed data,
- 4th byte = number of 16×16 units.

Decompressor at `$80:C2AF` / `$80:C300`:

- each call reads two mask bytes and one fill byte;
- each mask nibble controls four output bytes;
- each call emits 16 bytes;
- a 16×16 unit is 8 calls (128 bytes);
- tile allocation advances 0x40 bytes per 16×16 unit, skipping the bottom
  tile row (`+0x200` when bit 9 set).

The extractor does not use this decoder yet; it uses VRAM dumps for exact
visuals. The decoder is documented here for the future full-content pipeline.

### Captured frame facts (`stage_600`)

- PPU mode 1 (plus BG3 priority), `inidisp=15`.
- BG1 tilemap base `$4800`, 64×32; scroll `207,0`.
- BG2 tilemap base `$4000`, 64×32; scroll `106,0`.
- BG3 tilemap base `$5800`.
- BG1/BG2 character base 0.
- BG3 character base `$5000`.
- OBSEL `3`: OBJ base `0x6000` words, small 8×8, large 16×16.
- Player OAM group uses palette 7 in OAM, but the frame was rendered with
  CGRAM palette 2.
- Visible item uses OAM slot 0, palette 0.
- Player composite: 27×43 px; feet offset `(13, 43)`.
- Spawn used by the native game: `(332, 164)`.
- Player’s idle OAM center/feet in the reference frame: `(332.5, 164.0)`.
- The item sprite is at world `(385, 111)`.

### Atlases

BG atlases:

- 512×512 RGBA.
- 32×32 tiles of 8×8, per palette 0–7.
- Four 256×256 quadrants: normal, horizontal flip, vertical flip, both.
- Pre-flipping is baked because raylib `DrawTexturePro` with negative source
  rectangles produced garbage on flipped BG tiles.
- Pixel index 0 is transparent.

OBJ atlases:

- 128×128 RGBA, 16×16 tiles, per palette 0–7.
- Currently generated for future use; the player/item are baked PNGs.

### OAM parser

- Low table: 512 bytes, 128 sprites × 4 bytes.
- High table: 32 bytes at offset `0x200`.
- Each sprite: x, y, tile, attribute.
- High table bits: X bit 8 and size select.
- `parse_oam()` returns screen positions, 8/16 px size, tile, palette, flips.
- Player identification is **palette 7** in the OAM group; slot range changes
  per animation/frame, so never assume slots 1–11 outside the reference frame.

### Collision

- Built from the populated Area 1 screen row (`screens 8, 9, 10, 11, 16, 17,
  18, 19`), which places the solid/sloped floor at `by=10` (`y=160..175`, with
  attributes `7, 8, 9, 0x0a, 0x16, 1, 0x16, 0x0b..0x0e`) directly beneath
  Firebrand's feet and places the stone pillar at `cx=24`
  (`x=384..399`, `by=8..9`, `y=128..159`) beneath the urn at `(385, 111)`.
- Full room: 128×16 block grid (2048×256 px). The ROM grid is 8×2, but its
  first row is all-zero padding for this graveyard room; `--full-room` emits
  the populated row and reports this in the manifest.
- Attribute byte from `$98:8000 + (set<<12) + block`.
- High 3 attribute bits (`0xE0`) are environment flags; collision uses
  `attr & 0x1F`.
- Shapes `0x01/0x15/0x1A` are full solids, `0x02/0x17` are half-height blocks,
  and `0x03..0x14` are slope surfaces. The native table follows the
  `$80:962B` jump table:
  - `0x03: ((15-x)>>1)+8`, `0x04: (15-x)>>1`
  - `0x07..0x0a: ((15-x)>>2)+{12,8,4,0}`
  - `0x0b..0x0e: (x>>2)+{0,4,8,12}`
  - `0x0f: 15-x`, `0x10: x`, `0x11/0x12`, `0x13/0x14` linear/half variants
  - `0x16/0x18/0x19/0x1b` are walkable transition surfaces at offset 0.
- `Level_FloorAt` returns `block_top + offset` for the cell under the feet;
  walls/ceilings ignore slope cells so the player can walk up the hill.
- The `$1070` walk-speed probe is still separate; slope surfaces do not yet
  select the `0x00B3 → 0x0166` speed ramp.

### Block-table vs. VRAM tilemap (resolved)

BG1 now comes from the **ROM block tables** for the full populated screen row.
BG2 remains the **VRAM ring-buffer** backdrop from the captured frame
(`stage_600`). Earlier attempts to render the ROM block-table tilemap produced
"fences/garbage" **only because `--area 2` (`screens 33, 34`) was passed instead
of `--area 1` (`screens 8, 9`)**.

Verification against `--area 1`:

- `rom.screen_tilemap(0, 8)` and `rom.screen_tilemap(0, 9)` match
  `stage_600`'s 64×32 VRAM BG1 tilemap on **1957 / 2048 words identically**
  (100% of the loaded viewport; the remaining 91 words are the 3 rightmost
  columns of screen 9 that the VRAM ring buffer had not streamed in yet at
  `hscroll = 207`).
- **There is no tile remap.** The ROM block table (`$95 + set_id`) stores direct
  VRAM tile indices, palette bits and flip flags for BG1.
- The populated Area 1 row uses 492 unique BG1 tile indices (max index 622);
  every non-blank one is already present in `stage_600.vram.bin`. The only
  missing non-empty check is tile 4, which is not referenced by the room.
- The ROM grid is 8×2, but the first row is all-zero BG1 and collision for this
  room. `--full-room` therefore emits the populated 8-screen row (2048×256 px)
  and records the row's screen indices in `manifest.json`.
- BG2 is a looping 64×32 forest backdrop. The renderer wraps it horizontally
  (`tx & 63`) as the camera scrolls; the original per-scanline HDMA parallax
  on channel 1 (`$210F` `BG2HOFS`) is still a future improvement.

### Player animation extraction

The animation capture uses `save0` (normal graveyard gameplay in ROM Area 3,
`screens 52, 53`), not the Area-1 landing route. The debug server is driven
while the guest is paused, frame targets are absolute, and every frame is read
back from the 6000-frame state ring. This avoids the timing problems of a
scripted `dump` during a button hold.

Observed clip data in `save0`:

| Clip | Poses | Duration (frames) | Notes |
|---|---|---|---|
| `idle` | 1 | loop | OAM group is visually static |
| `walk` | 6 | 7,7,9,7,7,9 | 46-frame cycle; first pose after start is an acceleration pose (`$1020 = 0x00B3`) and is excluded |
| `jump` | 3 | 1,2,hold | takeoff, launch, rise; last pose holds until hover/fall |
| `hover` | 1 | loop | 18-piece wing-spread pose; also used for `fly` |
| `fall` | 2 | 3,2 (hold) | descent poses |
| `land` | 2 | 3,5 | 8 frames, matching `land_timer` |
| `attack` (`Y` shot) | 3 | 1,6,10 | 17 frames: idle press frame, 6-frame pose A, 10-frame pose B |
| `spell` (`A`) | 3 | 11,4,16 | 31 frames; back-turned wing-spread Talisman/Spell pose |
| `fireball` | 9 | 1 each | palette-6 projectile OAM stream; one step per captured frame |

Frame facts:

- The player is the palette-7 OAM group; sprites with screen Y ≥ 224 are
  offscreen and excluded.
- `save0`'s player palette is CGRAM OBJ palette 7. The `stage_600` dump needed
  palette 2 because CGRAM had been restored before dumping; do not reuse the
  `stage_600` palette override for animation captures.
- Frames are canonicalized to face right by mirroring when the OAM group is
  not hflipped. The renderer mirrors the texture for left-facing movement.
- Each frame anchor is `object_X_screen - bbox_min_x` horizontally and
  `bbox_height` vertically. The body stays aligned while wings change the
  bbox width; the feet stay on `player.y`.
- PNGs are 8-bit RGBA at native resolution (no scaling). The engine sets
  `TEXTURE_FILTER_POINT`.
- `player_anim.json` stores, per clip, `loop` plus steps with `texture`,
  `anchor_x`, `anchor_y` and `duration` in game frames. The C loader in
  `src/anim.c` caps the set at 64 steps and falls back to `player_idle.png`
  when the file is absent.
- `fireball_anim.json` uses the same step shape, capped at 16 steps by
  `src/anim.c`; projectile anchors are measured from the object slot's world
  X/Y rather than the player's feet.

Fireball extraction (resolved):

- Pressing **`Y`** (`$1E3C` → `$105C`) in `save0` keeps the grounded state but
  selects animation `$1053 = 0x0E` and spawns an object in the first free
  `$1080..$1260` slot (allocator `$80:F222`; the earlier `$80:F1FE` label was a
  different helper).
- The shot starts on the press frame; the player OAM shows the idle pose for
  that frame, then the 6-frame and 10-frame shot poses.
- Measured object spawn: `X = floor(player.x) + 3`,
  `Y = floor(player.y) - 8`, `vx = 0x0300` (3.0 px/frame), `vy = 0`.
- The moving fireball slot is the active slot with non-zero `+$20`
  horizontal velocity. Its OAM group uses **palette 6**, while Firebrand uses
  palette 7, so the extractor can remove it from the player bbox cleanly. It
  additionally filters by the object's screen position to avoid unrelated
  sprites.
- The game despawns the shot after it leaves the camera viewport; in `save0`
  that happens at world X 704 when the camera right edge is `448 + 256`.
- `extract_anim.py` emits `fireball_0..8.png` and `fireball_anim.json`; the
  native pool draws one step per guest frame and mirrors it for left shots.

Object list and HUD extraction:

- `extract.py --full-room` reads the 3-byte pointer table at `$81:C874`
  (index `area` by default; Area 1 = index 1) and parses 6-byte records
  `[species, flags, x16, y16]`. The high Y byte is the screen-row offset
  (subtract `row_index * 256`).
- Species `$57` becomes a destructible urn object; species `$67` becomes an
  enemy object. The static OAM urn is omitted when the object list contains an
  urn so it is not drawn twice.
- Area 1 yields four urns at `(392,120)`, `(888,168)`, `(904,168)`,
  `(1640,152)` and four `$67` enemies.
- `extract_anim.py` bakes the save0 BG3 HUD into `hud_bar.png` (six 8×8 health
  tiles at tile column 3, row 2) and `hud_slots.png` (three 2×2 crest slots at
  columns 18..29, rows 1..2), with the brown BG3 backdrop made transparent.
- Heart/enemy sprites (`heart_00..01.png`, `enemy_00..01.png`) are now baked
  from ROM OAM/CHR via the `$8B:8000` metasprite decoder (`extract.py`); other
  species still share the ghoul sheet until their init handlers are baked.

---

## 7. Oracle tooling and results

### Recomp trace facility

`SNESRECOMP_WRAM_TRACE_FILE=path` writes JSONL of every changed byte in low WRAM
(`$0000–$1FFF`), one line per byte:

```json
{"f":123,"adr":"0x01030","old":"0x00","val":"0x12"}
```

This is the cheapest way to record player/object state without building the Lua
bridge.

### `parse_wram_trace.py`

Reconstructs per-frame player/task fields from the trace. It currently emits:

```
frame,frame_rel,area,player_x,player_y,screen_x,screen_y,cam_x,cam_y
```

It reads the `$1000` task fields:

- `$1030–$1032` 24-bit X,
- `$1033–$1035` 24-bit Y,
- `$00C0/$00C1` camera X,
- `$00C4/$00C5` camera Y.

Caveat: the `$1000` task’s Y oscillates during idle animation and is **not** a
clean visual position source. X is more stable. The OAM-based parser below is
the reliable visual ground truth.

### `parse_player_trace.py`

Reconstructs the OAM buffer from the same WRAM trace:

- low OAM `$0700–$08FF`,
- high OAM `$0900–$091F`,
- filters the palette-7 player group,
- computes the sprite bbox,
- outputs center X and feet Y plus scroll.

Output:

```
frame,frame_rel,screen_x,screen_y,w,h,scroll_x,scroll_y,player_x,player_y,area
```

`player_x = bbox_center + scroll_x`
`player_y = bbox_bottom + scroll_y`

This is the current oracle position. It matched the native spawn exactly in
`save0`: `(332.5, 164.0)`.

### `compare.py`

Aligns native `DC_TRACE_CSV` and oracle CSV at a chosen oracle `frame_rel`,
compares world-space deltas, reports max/mean delta and first frame above a
threshold.

It is ready, but the area-2 route probes were contaminated by the landing
cinematic and room transitions. Use `save0` for clean probes.

### Probe routes

- `oracle_walk.script` — boot → area 2 → movement probes.
- `oracle_move.script` — long movement sequence.
- `oracle_physics.script` — movement/jump probes after the landing.
- `oracle_short.script` — short probe after frame 800.
- `oracle_control.script` — attack/walk/jump test.
- `oracle_dump.script` — movement with machine dumps.
- `oracle_late.script` — long-settle probe (area transitions).
- `oracle_save.script` — generic save-state probe.
- `oracle_save_start.script` — attempts to leave a locked intro.
- `oracle_save0_short.script` — clean short walk probe from save0.
- `oracle_save0_buttons.script` — B/X/Y/A identification.
- `oracle_save0_buttons2.script` — Up/R/L/Start/Select identification.
- `oracle_save0_press.script` — first frames after A/B.
- `oracle_save0_jump.script` — B jump arc samples.

### Save states

Only `save0.sav` remains after the owner cleaned the others:

```
projetos/opencode/DemonsCrestSNESRecomp/build-trace/saves/save0.sav
```

It is a clean normal graveyard gameplay state with Firebrand standing on a
ledge, HUD visible, no boss.

`--resume-state` **deletes the file after loading**, so always copy it first:

```sh
cp saves/save0.sav /tmp/save0_probe.sav
./build-trace/DemonsCrestSNESRecomp "$ROM" \
  --resume-state /tmp/save0_probe.sav --script ...
```

### Debug server

The trace build opens a TCP debug server (default port 4377; override with
`SNESRECOMP_DEBUG_PORT`). Useful commands:

- `wram_writes_at <hex_addr> [from] [to] [limit]`
- `save_state <filename>`
- `load_state <filename>`
- `set_controller`
- `dump_ram`, `dump_vram`, `dump_cgram`, `dump_oam`
- `oam_render_get`
- `block_watch_*`, `set_wram_watch`, `wram_watch_log_get`

`wram_writes_at` identified the original player code:

- `$1030` written by `bank_80_8D35_M1X1`
  (parent `bank_80_8C77_M1X1`) — horizontal integrator.
- `$1033` and `$1022` written by `bank_80_8D03_M1X1`
  (parent `bank_00_F0F2_M1X1`) — vertical integrator.
- `$1400` written by `bank_02_86C4_M0X1`
  (parent `interp@$8286A4`) — object cull/update loop.

### Original object/task system

- Object table base `$1080`, stride `$50`, end `$1D50` (26 slots total).
  - First 7 slots (`$1080..$1260`, up to `$12B0`) are allocated by `$80:F222`
    for player projectiles/effects.
- Loop at `$82:8611` (mirror `$02:8611`):
  - skip if `$0000` is zero,
  - `TCD` to the object base,
  - species `$02` selects a handler via `jsr ($8000,X)` table,
  - bits in `$0000` choose main/secondary update paths (`$8000`, `$8180`,
    `$8300`, `$8480`),
  - copies `$31`/`$34` to screen positions `$1C`/`$1E`.
- Dropped heart pickup handler at `$85:C180..C250` (previously misidentified as
  player jump):
  - `$85:C1C1`: despawns (`STZ $00`) if `$34 >= 0x00DB`; sets initial pop-up
    `$22 = 0x0400`, bounce counter `$39 = 0x0400`, gravity `$26 = 0x0040`.
  - `$85:C1E3`: integrates vertical motion via `$80:8D03`; on floor hit (`$04`),
    decrements `$39` by `0x0100` each bounce until stationary.
  - `$85:C227`: checks player pickup collision via `$80:9C93`, plays SFX `$58`
    via `$80:BD57`, despawns (`STZ $00`), and increments player HP `$1062` up to
    max HP `$1E50`.
- Player task is at `$1000`, separate from the object table, updated from
  `$80:DB00..F310`.
- Player object fields (`$1000` direct page) identified:
  - `$04` collision/ground flags (`bit 2` = on ground, `bits 0..1` = wall),
  - `$05` main state index (even offset into `$80:E002` jump table),
  - `$06` substate index,
  - `$09` facing direction (`1` = right, `2` = left),
  - `$0E`/`$0F` animation step / frame timer,
  - `$1C`/`$1E` screen X / screen Y,
  - `$20` walk speed (`0x00B3` initial step, `0x0166` max),
  - `$22` Y velocity (`0x059C` normal jump init, `0x02CE` underwater jump init,
    `0x0000` on B-release cut or hover),
  - `$26` gravity (`0x0038` normal, `0x002A` underwater),
  - `$30..$32` 24-bit X position (8.8 fixed-point; `$31..$32` integer X),
  - `$33..$35` 24-bit Y position (8.8 fixed-point; `$34..$35` integer Y),
  - `$45` underwater flag,
  - `$59`/`$5A` Jump button (B) held / newly pressed (`$1E3A`),
  - `$5B`/`$5C` Shot button (Y) held / newly pressed (`$1E3C`),
  - `$5D`/`$5E` Special/Headbutt button (A) held / newly pressed (`$1E3E`),
  - `$62` current player HP (max HP at `$1E50`).
- Vertical integrator `80:8D03`:
  `$33 += $22; $22 -= $26;` clamp `$22` at `0xFA00` (-6.0).
- Horizontal integrator `80:8D35`:
  `$30 += $20`.
- Player jump initializer `80:E160`:
  `$04 = 0; $22 = 0x059C` (`0x02CE` if `$45 != 0`); `$05 = 0x04; $06 = 0`.
- Player variable-jump cut `80:E227`:
  if `$23 >= 0` (rising) and `$59 == 0` (B not held), `$22 = 0`.

### Input mapping (verified)

The game stores the raw automatic-joypad word at `$0090/$0091` (active-high
after inversion). The bits are:

| Button | Store location |
|---|---|
| Right | `$0091` bit 0 (0x01) |
| Left | `$0091` bit 1 (0x02) |
| Down | `$0091` bit 2 (0x04) |
| Up | `$0091` bit 3 (0x08) |
| Start | `$0091` bit 4 (0x10) |
| Select | `$0091` bit 5 (0x20) |
| Y | `$0091` bit 6 (0x40) |
| B | `$0091` bit 7 (0x80) |
| A | `$0090` bit 7 (0x80) |
| X | `$0090` bit 6 (0x40) |
| L | `$0090` bit 5 (0x20) |
| R | `$0090` bit 4 (0x10) |

This was a source of confusion earlier: the script mask and the raw pad word
are in different orders, but the scripts are correct. The script `press right`
does produce Right, `press a` produces A, etc.

### `save0` validation results

- Walk right 10 frames: world X increases exactly 14 px → **1.40 px/frame**.
  This matches the native `1.398` (`0x0166` cap after `0x00B3` initial step).
- Default button bindings (`$80:DB00` via `$1E3A..$1E4C`):
  - **B** = Jump / Hover toggle (`$1059`/`$105A`),
  - **Y** = Fireball shot (`$105B`/`$105C`),
  - **A** = Talisman / Headbutt (`$105D`/`$105E`),
  - **X** = Item/Crest subscreen.
- B tap: feet `191 → 180 → 187 → 191` over ~14 frames, an ~11 px hop (matches
  initial velocity `$1022 = 0x059C` with `$1026 = 0x0038` gravity and immediate
  `vy = 0` cut on B release at `$80:E227`).
- Holding B gives the full jump arc; pressing B again in air toggles horizontal
  hover (`State 0x06`, `$1022 = 0`).
- The native spawn `(332.5, 164.0)` matches the reference `stage_600` idle
  player position.

### Area-2 route caveat

The boot → graveyard landing route (`stage_600`) reaches a landing/cinematic in
ROM Area 1 (`screens 8, 9`). Scripted movement there is either ignored,
triggers camera pans, or triggers room transitions. Do **not** use that route
for clean physics measurements. Use `save0` (ROM Area 3, `screens 52, 53`) or
another normal gameplay save.

---

## 8. Frozen technical facts and traps

These were already discovered the hard way; do not rediscover them.

1. **Generated C is not portable game code.**
   It is 65816 translated to C with `CpuState` and `cpu_read*`/`cpu_write*`.
   It runs only inside the recomp runtime.

2. **The recomp is the oracle, not the game.**
   Keep it for traces, dumps, visual references and frame-accurate comparison.

3. **VRAM is a ring buffer, not a full room.**
   A single captured 64×32 tilemap covers the current viewport plus some
   stale/duplicate content. Scrolling past it reveals wrong tiles unless the
   full room is built from the ROM block tables (`--area 1`).

4. **ROM block-table tilemaps DO match VRAM when the right Area ID is used.**
   Earlier attempts rendered "fences/garbage" only because `--area 2` (`screens
   33, 34`) was passed for `stage_600`, which is actually ROM **Area 1**
   (`screens 8, 9` = `slots 9, 10`). With `--area 1 --screens 9,10`, the ROM
   block table matches `stage_600`'s VRAM tilemap on `1957/2048` words (100% of
   the loaded viewport; there is **no** tile remap).

5. **CGRAM can change after rendering.**
   OAM said player palette 7; the visible sprite uses palette 2. The game
   restores/overwrites CGRAM before the dump. The extractor defaults to
   `--player-palette 2` for this capture and verifies visually.

6. **raylib negative source rectangles are unreliable for tile flipping.**
   BG atlases pre-bake four flip quadrants. Player and fireball animations now
   load a second, pre-mirrored texture in `Anim_Load`; the renderer picks it
   for left-facing sprites, so no negative source width is used.

7. **Player OAM slots are dynamic.**
   The player is the palette-7 group, but its OAM slot range changes with
   animation/effects. Never hardcode slots 1–11 outside the reference frame.
   The item is slot 0 in the reference frame.

8. **The player task’s `$1033` Y oscillates at idle.**
   It is not a clean visual position. Use the OAM bbox center/feet for visual
   oracle comparisons. The `$1000` task X is useful; Y is not yet trustworthy.

9. **The `stage_600` landing is a cinematic.**
   Inputs may be ignored or cause transitions. `save0` is the clean state.

10. **Script button masks and SNES action bindings.**
    The raw `$0090/$0091` layout is the hardware automatic-read word: Right is
    `$0091:01`, Y is `$0091:40`, B is `$0091:80`, X is `$0090:40`, A is
    `$0090:80`. In gameplay (`$80:DB00`), **B = Jump/Hover**, **Y = Fireball
    shot**, **A = Talisman/Headbutt**, **X = Subscreen**.

11. **`--resume-state` consumes the file.**
    Copy `save0.sav` before each run.

12. **The camera is no longer locked.**
    `room.json` from `--full-room` holds the 2048×256 BG1 row and camera bounds;
    the renderer wraps the 64×32 BG2 backdrop horizontally. Vertical camera
    range is only 32 px for this row.

13. **Collision attributes use the `$80:962B` surface table.**
    Walls are full/half blocks; `0x03..0x14` are slope surfaces. `0x16/0x18/
    0x19/0x1B` are treated as flat walkable transitions, and `0xA0` remains
    pass-through. The `$1070` walk-speed probe is still separate from the
    surface table.

14. **The HUD is extracted from `save0`, not `stage_600`.**
    `stage_600` is a cinematic frame with no BG3 status bar; `save0` has the
    health bar and crest slots. `extract_anim.py` bakes them as
    `hud_bar.png`/`hud_slots.png`. The active Crest/Talisman slot is
    highlighted from the current form; exact retail slot icons are still
    approximate.

15. **No audio yet.**
    The game is silent. Do not mistake this for a bug.

16. **Animation palette is not the `stage_600` palette.**
    `save0` renders Firebrand with CGRAM OBJ palette 7; the `stage_600`
    dump used palette 2 because CGRAM had been restored before the dump. The
    animation extractor defaults to palette 7 and verifies against the
    reference framebuffer.

17. **The debug server's `set_controller` does not accept bare decimal masks.**
    Use button names (`right`, `b+up`, `y`, `a`) or an explicit `0x` hex mask.
    `set_controller 128` is parsed as an unknown button and the command fails;
    capture tools must check the JSON error field instead of ignoring it.

18. **WRAM `$008D` IS the area table index — as a byte offset: `area = $008D / 2`.**
    The room loader reads the pointer table with an indexed load,
    `LDA $81:A291,Y`, and the guest keeps that `Y` in `$008D`. Table entries are
    2 bytes, so `$008D` is the *byte* offset, not the entry number.
    Every one of the 54 distinct `$008D` values in the save set is even
    (0…192 -> areas 0…96), and dividing by two reproduces every room BG1 can
    identify, including the ones that used to look like counter-examples:
    cemetery `2 -> 1`, `save8` `74 -> 37`, `save9` `58 -> 29`, `save1a`
    `34 -> 17`, `save6a` `4 -> 2`, `save8a` `6 -> 3`, `save7` `48 -> 24`.
    The curated "save7=48, save8=74, save9=58" mapping in `bg2_captures.json`
    was those raw bytes read as area numbers, i.e. every entry is 2x too high.
    Verify with `tools/oracle/map_saves_to_areas.py`, which cross-checks the
    loader id against BG1/BG2 tilemap matching (`tools/oracle/room_match.py`).
    Areas that share both the info and the grid block in
    `$81:A291`/`$81:A6D8` are byte-identical rooms (1/73, 0/72, 30/71, …):
    content cannot separate them, so the mapper reports the tie explicitly and
    picks the lowest id.

19. **`$85:C1D4` is a bouncing heart pickup, not Firebrand's jump.**
    Firebrand's jump is at `$80:E160..E239` (`$1022 = 0x059C`, gravity
    `$1026 = 0x0038`, B-release zeroes `$1022` at `$80:E227`). `$85:C180..C250`
    bounces dropped hearts (`$22 = 0x0400`, `$26 = 0x0040`) and heals `$1062`.

20. **The fireball OAM group uses palette 6, not the player's palette 7.**
    In `save0`, the projectile stream is the palette-6 group near the moving
    object slot, so palette filtering keeps it out of Firebrand's body PNG.
    `extract_anim.py` still applies an object-position window as a fallback in
    case a capture uses the same palette for both.

21. **BG2 backdrops are generated by the guest; there is no ROM tilemap table.**
    `$84:A057` uploads the BG2 tilemap to VRAM `$4000` by DMA from WRAM bank
    `$7F`, using chunk tables `$84:C311`/`$84:C312` indexed by `$00F9`; when the
    table entry is empty it DMAs a static 0x1C00-byte background from
    `$81:8068`. Area 1 and Area 3 backdrops differ (only 1.5% of BG2 words and
    27% of the first 32 KiB of CHR are equal), so per-area data is required.
    The extractor therefore takes BG2 from an oracle frame per area via
    `tools/dc_extract/bg2_captures.json`.

22. **WRAM `$008D` is not a "load this room" switch - but it retargets a load
    that is already in progress.**
    `$84:F0DA..F0EF` advances it by 2 (`$008D` is the room-sequence/stage id and
    the old value is copied to `$0E56`), but writing `$008D` through the debug
    server's `write_ram` from a standing game does not load a room: 120 frames
    after `write_ram 8d <next>`, VRAM was byte-identical and the camera did not
    move. The reason is that only the *room-load task* consumes `$008D`, and the
    game only starts that task from its own transition code:

    ```
    80:BB58  lda $008D      ; current area, byte offset into $81:A291
    80:BB69  sta $0E56      ; remember the room being left
    80:BB6C  lsr / tax
    80:BB6E  lda $97DA,X    ; sequential "next area" table
    80:BB75  sta $008D      ; the only writer of $008D during a transition
    80:BB7F  jmp $BAB7      ; $BAB7 -> "lda #4 / jmp $829B": current task = id 4
    82:C3+4  id 4 -> $80:B71A  (the room loader; ids are byte offsets, not indices)
    ```

    The loader does not read `$008D` again until after the fade-out, so writing
    `$008D = 2*N` while a transition is in flight *does* load area N - see
    `tools/oracle/load_area.py`, which walks a door save through its door, pins
    `$008D` for 30 frames and then verifies the live BG1 against
    `room_area<N>.json`. A raw poke from a standing game still does nothing.

23. **The `$82:8300` species table holds `JSL` stubs, not full handlers.**
    All four object tables are 0xC0 entries (0x180 bytes) apart: `$82:8000`
    main update, `$82:8180` secondary, `$82:8300` init, `$82:8480` aux, each
    indexed by `species*2` (the loop does `lda $02; and #$00FF; asl; tax`).
    Late init entries are 5-byte `JSL $83:xxxx; RTS` thunks: species `$67`
    resolves to `$82:F382` → `JSL $83:AF19` (init), with its update handler at
    `$83:AF74`. That is the route to per-species OAM/animation data.

24. **The Windows trace build's debug server supports state writes.**
    `write_ram <addr_hex> <hex bytes>`, `read_ram <addr_hex> <len>`,
    `dump_vram`, `get_frame_extended <frame>`, `dump_frame_vram <frame>` and
    `run_to_frame <frame>` all work against
    `build-trace\DemonsCrestSNESRecomp.exe` with `SDL2.dll` beside it. Remember
    `--resume-state` consumes the save file and `run_to_frame` re-pauses the
    guest at the target.

25. **`save0` (Area 3) has no live objects, so teleporting will not show enemies.**
    All 26 object slots (`$1080..$1D50`) are inactive in that save; writing the
    player position (`$1030/$1033`, 8.8 fixed) to an enemy's listed position and
    running 45+ frames did not activate the Area 3 species `$26`/`$07` objects.
    Enemy sprite capture therefore needs either a different save/route or the
    ROM-side animation data, not the current save0.

26. **Injecting an object record runs the species init, but not every species
    draws its own art.**
    The object loop starts with `$00` bit 0 set as "init pending": it clears the
    bit, sets `$00 = 6` and calls `JSR ($8300,X)` with `X = species*2`. Writing a
    record with `$00=1` therefore initialises any species in place. However the
    real spawner (`$82:8BDB`) also fills fields the init expects, so species
    whose sprite setup depends on them render Firebrand's sheet. In one 11-way
    capture pass `$57/$49/$2D/$67` baked correctly while `$26/$2E/$81/$24/$33`
    came out identical to the player and were rejected. Reproduce the spawner's
    remaining writes before trusting a species' capture.

27. **`$81:AE11` is the per-area *ambient* sprite list, not the object species list.**
    The table holds 16-bit little-endian pointers per area (`$AEF9` area 0,
    `$AF15` area 1, `$AF22` area 2, `$AF2F` area 3, ...). Each list is a run of
    2-byte pairs terminated by `0x00`; the first byte is a `$8B:8000` metasprite
    group id and the second is an even frame count (area 1:
    `4E/2, 03/4, 61/6, 33/8, 0E/8, 16/8`). It is **not** a species→group map:
    intersecting the group sets of every area where a species occurs leaves
    contradictory candidates (55% of area pairs share no group at all), so these
    are the room's ambient animated sprites. Object sprites come from elsewhere:
    the species `$67` init writes `$8B`-bank frame pointers into object fields
    `$28/$2A/$2E` (`$DE87/$DE7B/$DE6C`), which land inside the metasprite data
    block at the end of bank `$8B` — that is the next thread to pull.

---

## 9. Current limitations

- All 113 campaign areas extract and load. BG2 backdrops are captured for
  Areas 1 and 3; other areas keep a transparent layer until an oracle frame is
  added to `tools/dc_extract/bg2_captures.json`. `tools/audit_campaign.py`
  classifies 69 rooms as playable and 44 as partial (mostly zero-collision
  boss/cutscene arenas whose floor is not in the block tables).
- BG2 parallax in Area 1 now uses the recovered `$84:AF65` HDMA bands; other
  areas have no per-scanline effect until their BG2 tables are decoded.
- Player animation covers idle/walk/jump/hover/fall/land, the 17-frame `Y`
  shot and the 31-frame `A` spell. Hurt, death and wall-cling clips are still
  needed; the six Gargoyle forms currently reuse the base sheet with palette
  tints instead of separate form OAM sets.
- The projectile kind covers normal/charged shots and the Fire-Crest element
  tint; Tornado platforms and Claw lava-freezing are not fully simulated.
- Enemy behavior covers the first-pass ghoul plus Area 2 skeletons, bats and
  wall gargoyles; other species still reuse the shared enemy sprite/AI.
- The HUD shows HP and three crest slots and highlights the active form; the
  exact per-talisman icons and retail slot layout are still approximations.
- The `$1070` terrain probe is wired to `attr & 0xE0 == 0x80` and selects the
  `0x00B3 → 0x0166` ramp; exact per-shape ramp behaviour still needs oracle
  comparison.
- Audio is an original procedural development loop/SFX, not extracted ROM
  music; there is no music/sfx menu beyond the master volume option.
- Text/dialogue, cutscenes and the exact retail password algorithm are stubs
  (the password screen now uses a working native 10-letter codec; the retail
  format is still unknown). Campaign progression persists through the native
  save file (`saves/dc_save.json`), but that is not the retail SRAM/password
  format.
- No public-release asset path yet.

---

## 10. Ordered next steps

The milestones below are ordered by technical dependency so each step unblocks
and validates the next without rework.

### Step 1 — Extract Firebrand base animation frames (done)

Done in this session:

1. Added `tools/oracle/capture_anim.py`, which drives the trace build's debug
   server while paused and reads per-frame OAM/CGRAM/VRAM/register snapshots
   from the state ring.
2. Added `tools/dc_extract/extract_anim.py`, which composes the palette-7
   player group, canonicalizes facing, deduplicates poses, recovers the walk
   cycle and emits `player_<clip>_<n>.png` plus `player_anim.json`.
3. Added `src/anim.c` / `src/anim.h` and a frame-based animation state machine
   in `player.c` / `render.c`.
4. Added attack and landing timers, and fixed the fly/jump state flicker.

Acceptance:

- Walk animation plays at the original 46-frame cadence (6 poses).
- Jump rise, hover/fly, fall, landing and attack use the captured poses.
- Feet stay aligned with the ground/collision box via per-frame anchors.
- The collision AABB remains independent of the sprite frame.
- `DC_DEMO=5` exercises walk, special, jump and fly for screenshots.

### Step 2 — Fix Graveyard room extraction (`--area 1 --screens 9,10`) (done)

Done:

1. Changed the default `--area` in `tools/dc_extract/extract.py` from `2` to `1`
   (where `grid[1][:2]` automatically selects `slots 9, 10` = `screens 8, 9`).
2. Re-ran `extract.py` on `captures/graveyard` (`stage_600`) to regenerate
   `assets/generated/room.json` and `manifest.json`.
3. Updated `Level_IsSolidAt` (`src/level.c`) and the debug collision overlay
   (`src/render.c`) to mask the low 5 shape bits (`attr & 0x1F`) so `0xA0`
   environment blocks are not treated as mid-air solids.
4. Fixed `Player_Init` and `Player_Update` (`src/player.c`) so Firebrand aligns
   to the block top (`y=160`) on init and only triggers `land_timer = 8` when
   transitioning from airborne to grounded (`!was_on_ground`).
5. Verified with `DC_DEBUG_COLLISION=1` (`physics_check.png`) that row `by=10`
   (`y=160..175`) sits under Firebrand's spawn `(332, 160)` and `cx=24`
   (`x=384..399`, `y=128..159`) boxes the stone pillar under the urn `(385, 111)`.

### Step 3 — Port the authentic Bank `$80` player state machine & physics (done)

Why before projectiles/scrolling: the exact constants and transitions are now
known from `$80:DB00..F310`; replacing the temporary float heuristics in
`src/player.c` locked down movement feel and input handling (`B` = Jump /
Hover toggle, `Y` = Fireball shot, `A` = Talisman/Headbutt).

Done:

1. `src/player.c` now stores `x_fx`, `y_fx`, `vy_fx` and `walk_speed_fx` as
   8.8 fixed point:
   - Walk (`$80:F0A0..F0E5`): flat ground keeps `$1020 = 0x0166` (oracle
     behaviour); `UpdateWalkSpeed` implements the `$1020 = 0x00B3` first step
     and `$80:8B85` 3/256 ramp for the `$1070` slope path (surface walking is
     done in Step 5; the speed probe is still separate).
   - Gravity (`$80:E070`, `$80:ED11`): `$1026 = 0x0038`; terminal fall
     `0xFA00` (`6.0` px/frame in y-down coordinates).
   - Jump (`$80:E160..E239`, `State 0x04`): the press frame enters substate 0
     without moving; substates 0→2→4 integrate gravity and position; the first
     substate-4 frame applies the `$80:E227` B-release cut (`vy = 0`).
   - Hover (`$80:E1A3`, `$80:E29F..E340`, `State 0x06`): B pressed in air
     enters hover with `vy = 0` and no gravity; the next B press returns to
     `State 0x04` substate 4 and falls on the following frame. `B + Up` flight
     is behind `DC_FLY_DEBUG=1`, off by default.
2. `src/input.c` maps SNES `Y` to the shot input (keyboard `X`/`J`, gamepad
   west/top) and SNES `A` to the special input (keyboard `C`/`K`, gamepad
   south). `Input` carries held/pressed pairs like `$1059..$105E`.
3. Added `tools/oracle/export_capture_csv.py` and
   `tools/oracle/segments_save0_physics.json`; `DC_DEMO=6` replays the same
   603-frame walk / tap-jump / hold-jump / hover sequence.

Acceptance:

- Tap-jump, full-hold jump, walk speed, and mid-air hover toggle match `save0`
  within ≤1 px / 1 frame across a 600-frame trace.
- Result: 603 frames compared, max delta `x=0.00 px`, `y=0.53 px`. The
  residual Y delta is the known `$1000` task-idle oscillation documented in
  trap #8.

### Step 4 — Capture `Y` Fireball shot in `save0` & implement projectiles (done)

Done:

1. Added `("shoot", "y", 35)` to `capture_anim.py`'s default route and captured
   it from `save0` (no `save2` needed).
2. Inspected the spawned slot in WRAM (`$1080..$1260`, stride `$50`, allocated
   by `$80:F222`; earlier notes called this `$80:F1FE`):
   - spawn frame = the Y press frame; slot `$1080` becomes active before the
     first shot pose is visible,
   - X = `floor(player.x) + 3`, Y = `floor(player.y) - 8`,
   - horizontal velocity `$1020 = 0x0300` (3.0 px/frame), vertical velocity 0,
   - the moving slot is identified by non-zero `+$20`; the projectile OAM
     group is palette 6 and the player is palette 7.
3. Updated `tools/dc_extract/extract_anim.py`:
   - projectile OAM is grouped around the moving object slot and excluded from
     Firebrand's palette-7 body composition,
   - the real Y clip is exported as `attack` (3 steps, durations 1/6/10 =
     17 frames), the A clip as `spell` (11/4/16 = 31 frames),
   - baked `fireball_0..8.png` + `fireball_anim.json` (one step per frame,
     palette 6, per-step object anchor).
4. Added `src/projectile.c` / `src/projectile.h`:
   - 7-slot pool matching `$1080..$1260`,
   - spawn on the shot press frame with the measured offset and velocity,
   - despawn on solid collision (pillar) or camera viewport exit.
   - `src/render.c` draws the palette-6 fireball group and mirrors it for
     left-facing shots.
5. Added `DC_DEMO=7` and `DC_TRACE_PROJECTILES=path` for reproducible visual
   and CSV checks.

Acceptance:

- Pressing Shot plays the captured Y spit animation and spawns a fireball on
  the press frame at the measured offset.
- The pool allocates up to seven slots; `DC_DEMO=7` verifies pillar despawn,
  viewport despawn, concurrent slots and left-facing mirroring.
- Corrected finding: `$80:F222` is the slot allocator; `$80:F1FE` is a
  different object helper and was mislabeled in the earlier notes.

### Step 5 — Full-room Area 1 tilemap, slope/ledge attributes & camera scrolling (done)

Why now: since Trap #4 is resolved (ROM block tables match VRAM directly when
`--area 1` is used), full-room scrolling no longer requires reverse-engineering
a tile remap.

Done:

1. Extended `tools/dc_extract/extract.py` with `--full-room`:
   - finds the populated screen row of the area grid and emits all eight
     screens as a 2048×256 BG1 map (256×32 tiles) plus a 128×16 collision grid,
   - all 492 referenced BG1 tile indices are already resident in
     `stage_600.vram.bin`; no ROM CHR decode or VRAM merge was needed,
   - BG2 stays the captured 64×32 backdrop and the renderer wraps it
     horizontally as the camera moves.
   - The ROM Area 1 grid is 8×2, but its other row is all-zero BG1/collision
     padding, so the extractor emits the populated row and records the screen
     indices `[8, 9, 10, 11, 16, 17, 18, 19]` in `manifest.json`.
2. Decoded the graveyard surface table from `$80:962B`:
   - full solids `0x01/0x15/0x1A`, half blocks `0x02/0x17`,
   - slopes `0x03..0x14` with the per-pixel formulas,
   - walkable transitions `0x16/0x18/0x19/0x1B` at offset 0.
   `Level_FloorAt`/`Level_SurfaceOffset` now snap Firebrand to
   `block_top + offset`; walls ignore slope cells.
3. Unlocked `camera.min_x..max_x` and `min_y..max_y` in `room.json`:
   - horizontal deadzone 96..160 and vertical deadzone 96..176,
   - clamps to the 2048×256 room,
   - `DC_DEMO=8` walks left across the lower graveyard and then hovers right
     across pillars to exercise the full map.

Acceptance:

- Firebrand walks smoothly up and down the graveyard slopes (`by=10..11`),
  stands at `y=164` on `attr=0x09` at spawn, and the camera scrolls across the
  full starting room without stale or missing tiles.
- Verified by trace and screenshots at camera X 0, ~90, ~370 and ~425; the
  player height follows the slope as `164 → 163 → 162 → 161 → 160` (up) and
  back down.
- Remaining Step 5 sub-item: BG2 HDMA per-scanline parallax; the current
  backdrop uses a flat 1:1 offset plus horizontal wrapping.

### Step 6 — Object system (`$1080..$1D50`), one graveyard enemy & heart pickup (`$85:C180`) (done)

Done:

1. Added a 26-slot `ObjectPool` (`src/object.c`) and a data-driven spawn pass
   from the Area 1 object list (`$81:C874`, 6-byte records). The first seven
   projectile slots remain in `src/projectile.c`; the object pool holds urns,
   pickups and enemies.
2. Ported the `$85:C180` pickup behavior:
   - pop-up `0x0400` (4.0 px/frame), gravity `0x0040` (0.25),
   - `$39` bounce value starts at `0x0400`, loses `0x0100` per landing, then
     rests,
   - player overlap increments `$1062`/HP up to `$1E50`/max.
3. Added destructible urns for species `$57`: fireball hits shatter the urn and
   spawn a pickup at its bottom edge. Area 1 has four urns.
4. Added a first-pass species `$67` enemy:
   - emerges for 24 frames, then chases within 220 px,
   - contact costs 1 HP with 60-frame invulnerability and horizontal knockback,
   - two fireball hits kill it and drop a heart.
   This is the correct species/object-list plumbing, but its sprite and
   behavior are placeholders until `$83:AF74` is fully ported.
5. Added `DC_TRACE_OBJECTS`, `DC_DEMO=9` (urn → heart → heal) and
   `DC_DEMO=10` + `DC_START_X` (enemy chase/damage/drop) for validation.

Acceptance:

- Destroying the urn at `(392,120)` drops a heart that follows the measured
  `$85:C180` arc and heals HP on touch.
- `DC_DEMO=10` confirms the species `$67` enemy can be hit, killed and drops a
  heart.

### Step 7 — BG3 HUD status bar (done)

- `extract_anim.py` decodes the save0 BG3 2bpp layer and emits
  `hud_bar.png` (six health tiles) and `hud_slots.png` (three 2×2 crest slots).
- `render.c` draws the HUD in screen space: translucent top strip, current HP
  bar scaled over a dark max-HP bar, three crest slots, and a gold highlight on
  the active spell slot.
- Player HP is initialized to 4/6 so hearts visibly heal; the trace CSV now
  includes `hp,max_hp`.
- Remaining HUD work: real talisman inventory/selection and the exact
  per-talisman icons. The current first-slot highlight is a placeholder.

### Step 8 — Engine hardening & automated regression harness (done)

- **Fixed-timestep accumulator in `main.c`**: `SetTargetFPS(0)` + VSync, a
  `GetFrameTime()` accumulator capped at 0.25 s / 8 catch-up steps, and exact
  60 Hz `Game_Update`. `DC_RUN_FRAMES` remains deterministic
  one-update-per-loop for traces/screenshots.
- **Pre-baked mirrored frames**: `Anim_Load`/`ProjectileAnim_Load` create a
  mirrored texture per step; `render.c` selects it for left-facing player and
  fireball draws. The static fallback player also has a pre-flipped texture.
  No negative `DrawTexturePro` source widths remain.
- **Single-command regression**: `tools/run_regression.py` (also
  `tools/run_regression.sh` and CTest `regression`) runs demos 6/7/9/10/11/12 and
  asserts walk/jump/hover, fireball spawn/despawn, urn/heart arc, enemy damage
  and HP changes. `ctest --output-on-failure` passes. Missing binary/assets
  return 77 so CTest reports a skip.
- Acceptance: `ctest` passes in ~60–80 s, and the local `compare.py` oracle flow
  remains available for ROM-accurate checks.

### Step 9 — Audio, menus, game flow & full content (vertical-slice portion started)

Done in this session:

- **Audio**: `src/audio.c` synthesizes an original looping chiptune theme and
  jump/land/shoot/break/pickup/hurt/enemy-hit SFX at startup. No ROM audio is
  used. Audio initializes only when a device is available and is skipped for
  `DC_RUN_FRAMES`; `DC_NO_AUDIO`, `DC_AUDIO_DEBUG` and `DC_AUDIO_FORCE` are
  available for testing.
- **Flow**: `Game` now has Title / Playing / Paused / Clear states. The title
  screen renders the graveyard behind an overlay and starts on Enter/Start;
  Escape/Back pauses. The object-list exit (`species $09` at x=1920) triggers
  an Area Clear screen; Enter restarts.
- **Menus**: pause overlay and restart-on-clear are implemented. Password,
  stage select, map and title options are not.

Remaining Step 9 work:

- Room transitions and the rest of Areas 1–3, boss gate `$81:97DA`, bosses,
  crest forms, Mode 7 overworld, password/save/menu flow.
- ROM music/SFX extraction (BRR/DSP + sequences) or a replacement soundtrack
  for public release, plus volume/mute options.
- Original fan-game levels/story/art.

### Step 10 — Full-campaign foundation (started this session)

Done:

- **ROM extraction**
  - `tools/dc_extract/extract.py` now implements the native decompressor at
    `$80:C2AF`/`$80:C300` (16 bytes per call, 8 calls per 16×16 unit, `+0x200`
    bottom-row skip) and the `$98:C000` (BG CHR) / `$98:D000` (OBJ CHR)
    24-bit pointer tables.
  - All 113 valid areas from `$81:A291` + `$81:A6D8` are emitted as
    `room_area<N>.json`: 2D multi-row and vertical grids (e.g. Area 2 8×2,
    Area 3 4×5), collision attributes, spawns from `$81:A1A9`, bounding-box
    transitions from `$81:981A`, boss-gate target from `$81:97DA`, and object
    species/flags/positions from `$81:C874`.
  - Per-area BG atlases (`bg_area<N>_pal<P>.png`) are baked from ROM CHR and
    the ROM BG palette blocks (`$99:9080`, `$99:90A0`, `$99:A900 +
    ($81:8909[area] & 0xFFC0)`), limited to palettes the area actually uses.
    `Assets_LoadAreaBg` swaps the 8 atlases on room transitions.
  - OAM metabug: `$8B:8000` metasprite groups decoded from `$80:D9A7`, with
    the `$80:DA33` tile-base carry rule and per-part flip bits. Real ROM
    heart/Crest pickup and ghoul sprites are baked; the procedural
    `heart_*`/`enemy_*` placeholders are no longer used.
  - Item palette extracted from `$99:9240`; Gargoyle form palettes from
    `$99:9100..91BF`.
- **Level engine**
  - `Level` now carries `area_id`, `gate_next_area`, `backdrop`, up to 8
    spawn records and 16 transitions, plus `ObjectType` platform/crest/boss.
  - `Level_LoadArea`/`Game_TransitionToArea` load any extracted room; the
    runtime handles mid-room bounding-box transitions, boss-gated exits,
    respawn logic and per-area BG atlas swaps.
  - Collision environment flags: hazards (`0x20`, e.g. `0x21`), breakable
    `0x40` blocks (removed from the grid and BG1 tilemap), water (`0x60`),
    slope acceleration (`0x80` → `$1070`), plus the `$80:962B` surface table.
    Underwater physics uses `$1045` constants (`0x02CE` jump, `0x002A`
    gravity, `0x0300` terminal fall).
  - BG2 HDMA scanline parallax recovered from `$84:AF65` (32/44/28/46/74
    line bands with 0.25/0.125/0.25/0.50/1.25 factors) and rendered with
    per-band clipped tiles. `DC_NO_HDMA=1` disables it.
  - Room backdrop colour emitted from ROM palette 0; the renderer clears to
    it instead of a fixed colour.
- **Player/crest system**
  - `CrestForm` enum with Base, Earth, Aerial, Water, Time and Ultimate
    Gargoyle. `Q`/`E` or L/R cycles owned forms; clearing Areas 0–4 unlocks the
    next Crest, and `DC_UNLOCK_ALL=1` (or `DC_DEMO=11`) unlocks all six for
    testing.
  - Earth/Ultimate shoulder tackle (breaks `0x40` blocks ahead), Aerial/
    Ultimate vertical flight, Water free swimming, Time/Ultimate and Armor
    Talisman damage reduction, overhead headbutt block breaking, and wall
    cling (hold A against a tall wall while descending).
  - Fire-Crest element selector (Fireball, Buster, Tornado, Claw, Demon
    Fire); Buster/charged shots break `0x40` blocks. Projectiles carry
    damage/element and are tinted per element.
  - Crest/Item subscreen (Tab/X) with HP, Urns, Spells, gold, form and
    Fire-Crest/Talisman selection; Urn heals; Spell spends a scroll.
- **Enemies, bosses and objects**
  - 26-slot object pool extended with platforms, crest/life-stone pickups and
    bosses. Area 0 spawns **Somulo** (HP bar, lunge/leap cycles); Areas 2/3/5
    add skeleton patrols, bats and wall gargoyles; enemy contact uses the
    shared damage/knockback/invulnerability path; bosses can be tackled or
    shot, drop a pickup and set `boss_defeated`.
  - Urns drop hearts; hearts heal and award gold; crest pickups raise max HP,
    gold and refill potions.
- **Campaign flow**
  - Title menu with New Game / Overworld Map / Password / Options.
  - Mode 7-style overworld with six landing nodes, Firebrand marker,
    nearest-node selection, stage locking (Demon Keep requires the first four
    stages), and shop access.
  - Pause menu with Resume / Return to Overworld; shop (Urns, Spells, Life
    Stones); generated password screen; volume options; Game Over;
    clear screen with password; ending screen; `GAME_ENDING` after Demon
    Keep when all stages are cleared.
  - Deterministic `DC_STATE` hook renders each menu for screenshots.

Acceptance:

- `dc_extract` regenerates all 113 area rooms plus per-area atlases from the
  ROM in ~65 s.
- `DC_AREA=0/1/2/3` loads the corresponding room and renders its own BG set.
- `DC_AREA=0 DC_CAMPAIGN=1 DC_BOSS_DEFEATED=1 DC_DEMO=12` walks through the
  Area 0 boss gate into Area 17 (trace `area` column).
- `DC_DEMO=11` cycles at least three Crest forms and exercises the
  Earth/Ultimate dash, Air flight and Aerial shots.
- `tools/run_regression.py` covers demos 6/7/9/10/11/12 and Area 2/3 loads.

Still placeholder / remaining:

- Enemy and boss animations beyond the shared ghoul sprite; real per-species
  OAM groups need to be baked from their init handlers.
- Player form sprites/animations; current forms are palette tints of the base
  Gargoyle sheet.
- Text/dialogue/cutscene scripting, exact retail password decode, SRAM-style
  save persistence, and shop NCP dialogue.
- ROM audio (SPC700/BRR/DSP) extraction or replacement.
- Mid-stage `$98:E000` CHR streaming coverage and per-area BG2 backdrops.


### Step 11 — Save/options persistence and HUD polish (done)

Done:

1. `src/game.c` gained `Game_SaveProgress` / `Game_LoadProgress` /
   `Game_HasSave`:
   - JSON (cJSON) file at `saves/dc_save.json` (override `DC_SAVE_PATH`),
     versioned; stores area, `stages_cleared`, HP/max HP, Crest mask + form,
     Talisman mask + active, Fire element, Urns, Spells, gold and volume,
   - `Game_LoadProgress` transitions to the saved area first (so the room,
     collision and atlases are rebuilt), then applies the saved player fields
     and clamps them,
   - autosave at `Game_CompleteArea`, `Game_OpenOverworld` and `Game_Shutdown`
     (only while `campaign_mode` is set),
   - deterministic `DC_RUN_FRAMES` runs skip saves unless `DC_SAVE_FORCE=1`;
     `DC_NO_SAVE=1` disables load/save; `DC_RESUME=1` skips the title.
2. Title menu shows `CONTINUE` only when a save exists; otherwise the original
   four entries are kept so `DC_DEMO=13` still starts a new game.
3. HUD health bar: the baked texture is a brightness mask, so the renderer now
   draws the empty part dark and the filled part red (`(235, 88, 120)`), which
   restores the segmented red health bar look.
4. `tools/run_regression.py` covers the save round-trip: run A autosaves with
   `DC_SAVE_FORCE`, run B resumes with `DC_RESUME` and the trace must report the
   same area, max HP and gold.

Remaining polish: a proper CONTINUE/options screen layout, per-slot saves,
retail SRAM/password parity, and saving mid-room position rather than the room
spawn.

### Step 12 — Native password codec and entry screen (done)

Done:

1. Replaced the placeholder 8-letter generator with a real codec
   (`Game_PasswordEncode` / `Game_PasswordDecode` / `Game_ApplyPassword`):
   - 32-bit payload `stages[7:0] max_hp[11:8] crests[17:12] form[20:18]
     potions[23:21] scrolls[26:24] talismans[31:27]`,
   - 8-bit FNV-1a checksum, encoded as 10 base-20 digits from
     `BCDFGHJKLMNPQRSTVWXYZ` (40 bits total),
   - invalid or truncated codes are rejected, so a mistyped password cannot
     corrupt a run.
2. Password screen is now interactive: up/down cycles the letter under the
   cursor, left/right moves it, Enter applies a valid code (restoring stages,
   max HP, Crests/form, Urns, Spells and Talismans, then opening the overworld
   and autosaving), Esc returns to the title, and the screen reports
   `INVALID CODE` / `PROGRESS RESTORED`.
3. `DC_PASSWORD=<code>` applies a code at boot (tests, cheats, support);
   `DC_PASSWORD_SELFTEST=1` runs 2000 pseudo-random encode/decode round-trips
   and exits with `0`/`1`, which needs no window or assets.
4. `tools/run_regression.py` mirrors the encoder in Python and asserts that a
   generated code restores `max_hp` and `form` in a real run, alongside the
   binary self-test. The cross-implementation check also catches codec drift.

Still pending: the retail password/SRAM algorithm and the exact retail screen
layout.

### Step 13 — Per-species OAM via injected objects (started)

Done:

1. `tools/oracle/capture_species.py`: the guest object loop treats bit 0 of an
   object's `$00` word as "run the species init", so writing a minimal record
   (`$00=1`, `$02=species`, `$0A=0x30`, `$26=0x40`, world position) into the
   first slot makes the game initialise and draw that species in the current
   room. The tool starts the trace build paused on a fresh save copy, derives
   the world->screen offset from the player's palette-7 OAM cluster (feet
   anchor, since the guest restores the BG scroll registers after rendering),
   injects the record, and dumps OAM/CGRAM/VRAM/PPU at `--frames` offsets.
   Eleven species were captured in one pass; the technique needs no area travel.
2. `tools/dc_extract/extract_species.py`: selects the object's OAM cluster
   (window around its screen position, player cluster excluded), composes it
   with the captured CGRAM and per-sprite palettes, crops, records the anchor
   relative to the object position, deduplicates poses and writes
   `enemy_<species>_<n>.png` + `species_anim.json`. Species whose capture came
   out identical to the player sheet are rejected automatically.
3. `src/assets.c` loads `species_anim.json` (up to 16 species × 4 poses with
   anchors and a frame duration); `src/render.c` draws the per-species sheet for
   enemy and boss objects, falling back to the shared `enemy_*.png` sheet.
4. Verified in Area 1 (`DC_DEMO=10 DC_START_X=900`): the species `$67` enemy now
   draws its own captured creature instead of the shared sheet; the urn and
   pickup species bake correctly.

Known limitation: species whose init depends on spawner-supplied fields (the
real spawner `$82:8BDB` copies a 6-byte record and sets further fields) still
render the player sheet, because the injection only provides the record fields.
Captured-and-rejected species: `$26`, `$2E`, `$81`, `$24`, `$33`. Reproducing
the spawner's remaining field writes (or invoking the spawner itself) is the
next step to cover every species.

### Step 14 — Species `$67` ghoul: authentic drop + porting map (started)

Done:

1. Ported the opening of the real `$83:AF74` handler into `src/object.c`:
   - emergence (24 frames) then **state 1** = the perch drop described by
     `$B2B1`/`$AFCB`: Y is lifted 9 px (`$34 -= 9`, object Y is y-down), then
     `$20 = 0x0050` horizontal, `$22 = 0x0398` downward, gravity `$26 = 0x0040`,
     windup `$3B = 3`, landing sets `$3B = 6` (`$B2C7` snaps Y by 7),
   - after landing it falls back to the previous chase as **state 2** until the
     remaining behaviour states are ported.
2. Added `substate`/`phase`/`facing` to `Object`. `phase` is required because
   `timer` is incremented every frame for animation, so a countdown must not
   share it.
3. Regression (`demo 10`) passes: the ghoul drops from its perch, closes on the
   player, damages on contact and dies to fireballs.

Porting map recovered from `$83:AF74` (for the next pass):

| Address | Role |
|---|---|
| `$AF89` | state 0 dispatcher on `$06`; substate 0 calls the `$B2E8` gate, else picks a behaviour from `$03` or the random table `$DEA2` (`$BC904B & 0x0F`) |
| `$AFCB` | substate 2: windup `$3B`, then `$B2B1`, vx `$20 = 0x50/0x88/0x70`, vy `$22 = 0x398/0x4D0`, `$2A = $DE7F` collision shape, `$39 = 5` |
| `$B000` | substate 4: `JSL $808C14`/`$808CBF` (object integration), ground test `$04 & 4`, then `$B2C7` |
| `$B065` | state 1 handler (not ported) |
| `$B0E4` | state 2 handler (not ported) |
| `$B1AF` | state 3 handler (not ported) |
| `$B249` | state 4 handler (not ported) |
| `$B298` | face the player: `$0A` bit 6 = facing right, `$09` = 1/2 |
| `$B2B1` | lift Y 9, `$06 = 4`, anim 4 |
| `$B2C7` | land: `$2A = $DE7B`, Y += 7, clear fractional X/Y, `$06 = 6` |
| `$B2E8` | gate: carry set when `ownX+0x70-playerX >= 0xE0`, `$47 == 0`, or `playerY-ownY` outside `[0, 0x50)` |

Further decoding (round 1):

- Substate 6 (`$B034`) runs a **3-hop burst**: `$38` counts hops, each landing
  alternates facing (`$0A ^= $40`, `$09` swapped) and restarts the hop at
  `$AFBC`; after 3 hops it clears `$06` and re-decides. The launch velocity is
  `$22 = 0x0398` for even `$38` and `0x04D0` for odd (`$B019..$B02D`). Ported:
  `Object.hops` drives the burst with the alternating facing and velocity
  variant, then the chase fallback takes over.
- Substate 4 (`$B000`) integrates through `JSL $808C14`/`$808CBF`, lands on
  `$04 & 4`, then jumps to `$B2C7`; its animation timer `$39` is loaded from
  `$DE8F` (even `$38`) or `$DE93` (odd) with the animation id from `$DE9B[$3A]`.
- State 1 (`$B065`, substate table `$B06A`): windup 32 frames → `$B2B1` →
  `$2A = $DE7F`, `vx = 0x0120`, `vy = 0x0540` (a much bigger leap) → land
  (`$3B = 0x10`) → hold → `$05 = 4`.
- State 2 (`$B0E4`, substate table `$B0E9`): face the player, anim 0, 32 frames →
  anim 6 with `$3C = 0x40` (64 frames), `$3D = 3` bursts, `$48 = 0xFF` →
  `JSL $83B8EF` blocks until the "fire" phase, plays SFX `$27` and spawns
  **species `$67`** as a projectile via `$82877B` at `x ± 0x13`, `y - 0x14`
  (the spawned object's own update runs at `$82:8BDB`), three times, then
  anim 0 with `$3B = 0x20`.
  This means the area object list's `$67` entries are the ghoul's *projectile*
  species, which explains why the injected capture of `$67` looked like a
  floating round object rather than a humanoid.

Implementation (round 2):

- New `OBJECT_ENEMY_SHOT` (type 7): hostile projectile carrying the captured
  species `$67` sprite, flying toward Firebrand at 1.5 px/frame, despawning on
  solid terrain/out of bounds/240 frames, damaging on overlap, and destroyable
  by the player's fireballs.
- Ghoul state 2 now runs the fire sequence: face the player, 3 volleys on the
  `$3C = 0x40` cadence, spawn offsets `x ±0x13`, `y - 0x14` (pixels), then a
  leap. Outside ~200 px it closes distance with the placeholder approach so the
  player can still engage.
- Ghoul state 3 is the leap attack from `$B065`: 32-frame windup, `vx = 0x120`,
  `vy = 0x540` (y-down dive), gravity `0x40`, 16-frame landing hold, then back
  to firing.
- Regression updated to the authentic behaviour: demo 10 asserts the ghoul fires
  projectiles and damages the player (kills now require a ground target), and a
  new area-2 run asserts skeletons die to fireballs (`DC_AREA=2`,
  `DC_START_X=360`).

Known gap: the ghoul lands on its perch at y≈96 and cannot descend to Firebrand
on the floor, because the `$DEA2` behaviour states that would move it between
ledges are still unported. Its volleys are the main threat in that room.

Sprite-data lead (round 3): diffing the object slots of a species that captures
correctly (urn `$57`) against one that draws Firebrand (`$2C`) shows the init
handlers write **species-specific 16-bit pointers** into `$28/$2A/$2E`
(`$D229/$D219/$D874` for the urn, `$D5A6/$D59A/0` for the skeleton). Those
offsets land inside the metasprite data block at the end of bank `$8B`
(`$8B:D219` etc. decode as 5-byte sprite parts), i.e. the ROM does hold
per-species frame data and it is addressable from the init handlers. The exact
frame-selection rule (which of the three pointers the renderer uses per state)
is still open, and decoding the frames needs the area's OBJ CHR
(`decompress_area_obj_vram`) plus the object palette.

Remaining: port states 1-4 fully and the `$DEA2` behaviour dispatch, which need
the object integration helpers (`$808C14`/`$808CBF`) and the animation driver
(`$80F81D`) mapped first.

### Step 15 — Text format and BG3 font cracked (started)

The script turned out to be **plain ASCII** with two control codes, not a
custom encoding:

- `0x01` = line break inside a page,
- `0x02` = page break (next text box),
- `0x5D` (`]`) terminates the last line of a page.

Evidence: the guest's pause subscreen draws labels through BG3 with tile index
== ASCII code (a captured frame contains tiles `0x46 0x49 0x52 0x45` = "FIRE").
The intro/ending lines sit at `$81:8DF2`:

```
I NEVER<01>EXPECTED THAT<01>PHALANX WOULD<01>BE DEFEATED]]]<02>
IT IS WRITTEN<01>THAT THE ONE<01>WHO DEFEATS<01>THE KING<01>SHALL RULE]]]<02>
THE NEXT TIME<01>IT WILL BE MY<01>TURN]]]<02>
```

Done:

1. `tools/dc_extract/extract_text.py --rom <rom>` walks printable runs that
   contain control codes, splits them into pages/lines and writes
   `assets/generated/text_strings.json` (518 strings, with ROM addresses).
   Strings that are really font/glyph tables (`$81:A49E..A60C`) are included but
   harmless.
2. `tools/oracle/capture_menu.py` opens the guest pause subscreen (press Start
   on a save), dumps VRAM/CGRAM/PPU to `captures/menu/`.
3. `tools/dc_extract/extract_font.py` decodes the BG3 2bpp tiles 0x20..0x7E at
   the character base into `font.png` (white mask, 128x48, 86/95 glyphs) plus
   `font.json` (first/last/cell). The renderer tints it per context.
4. `$81:A49E..A60C` also contains runs like `"0123456789:;<=LMNO"` — a glyph
   order/character table worth inspecting when the text renderer needs the
   exact symbol layout.

5. `src/text.c` / `src/text.h`: `Text_LoadScript` parses `text_strings.json`
   (up to 64 strings, 6 pages, 8 lines), `Text_DrawString` draws 8x8 glyphs from
   `font.png` with a tint and `Text_DrawPage` paints a dialogue box. `Game_Render`
   shows page 0 of the first string behind `DC_DIALOGUE=1` (page advances every
   120 frames) as a dev hook; the regression suite runs without it.

Font CHR resolution: the BG3 character base **is** `$5000` words
(`bgTileAdr & 0xF << 12`); the earlier "garbage" was a measurement mistake and a
stale fade-in capture. A 24-candidate montage of the BG3 layer
(`captures/menu/base_montage.png`) shows "FIRE" rendering correctly at `$5000`.
The pause-menu font is a bold italic 8x8 design (glyph cells are full height),
so the renderer needs 2 px of leading: `Text_DrawPage` now advances
`TEXT_LINE_H = 10`, and `DC_DIALOGUE=1` renders the real intro page legibly.

Shop/NPC text wiring (round 3):

- `Text_Find(script, needle)` locates a script entry by substring, and the
  script is now loaded unconditionally (it is small): `src/game.c` caches the
  shop entries for `"BLACK LOTUS"`, `"NEED AN URN"` and `"VELLUM IS"`.
- The shop screen draws the authentic ROM box `WELCOME TO / "THE BLACK LOTUS" /
  WE CARRY ONLY THE / FINEST POTIONS` through `Text_DrawPage`, with GOLD placed
  below the measured box height, and failed purchases display
  `YOUR URN IS ALREADY FULL OF` / `YOUR VELLUM IS ALREADY FULL OF` for 120
  frames. Regression stays green.
- The ROM text uses `[` for an apostrophe (`DON[T`), `"`/`\` for quotes and
  `]` as the page terminator — worth normalising in the text renderer later.

Next: wire the dialogue state into the flow (intro before Area 0, ending
variants), index the script table by event, and normalise the `[`/`]` control
characters.

---

### Step 16 — Campaign load coverage (done)

`tools/check_areas.py` boots the native build once per `room_area<N>.json`
(`DC_AREA=N`, fixed frame budget, trace CSV) and validates: clean exit,
expected frame count, finite player coordinates inside the room bounds. A full
sweep of all **113 areas passes** (`ok=113`), and `run_regression.py` now runs a
12-area subset (`0,1,2,3,4,5,17,21,25,46,92,109`) on every CI run.

Note for sandboxed shells: the game process must be able to write the trace CSV
where the tool puts it — pass `--tmp <dir>` (or `DC_CHECK_TMP_DIR`) when only a
specific tree is writable.

### Step 17 — Ending narration from the ROM (done)

The ending screen no longer uses placeholder lines: `Game_Init` caches the
`"PHALANX WOULD"` script entry and `GAME_ENDING` paginates its three pages with
Enter (the last page returns to the title), drawn through `Text_DrawPage` with
the extracted BG3 font. The stats line and title stay as native UI. This is the
first story beat wired from ROM data to the campaign flow; the same mechanism
can drive the intro, boss intros and the other endings once their script entries
are identified.

---

### Step 18 — Room classification and safe transitions (done)

- `extract.py` factors `room_stats(doc)` and writes it for every area into
  `campaign.json["rooms"]` plus a `room_kinds` summary. Classification:
  `playable` (collision + BG1 geometry + walkable ground under the spawn),
  `partial` (boss arenas without block-table floors, cutscene stages),
  `empty` (neither collision nor BG1 tiles). Current split: **69 playable,
  44 partial, 0 empty** — and `tools/audit_campaign.py` now cross-checks its own
  classification against `campaign.json` and agrees on every room.
- The native side loads those kinds (`Assets_RoomKind`, `campaign.json`) and
  `Game_TransitionToArea` refuses rooms classified `empty`, so a data regression
  can no longer drop the player into a collision-free world.
- `check_areas.py` still passes 113/113 and the regression suite stays green.

Next uses of the metadata: filter the overworld stage list to playable rooms,
and drive cutscene/arena handling for `partial` rooms explicitly.

---

### Step 19 — Story dialogue state and crest narrative (done)

- New `GAME_DIALOGUE` state: dims the frame, draws a `Text_DrawPage` page and
  advances with Enter; after the last page it returns to `dialogue_return`
  (`GAME_CLEAR` or `GAME_TITLE`).
- `Game_CompleteArea` now shows the ROM's **"YOU HAVE FOUND THE CREST OF ..."**
  pages (Earth/Air/Water/Time, cached from `$BE:A599..A6F7`) before the Area
  Clear banner. Deterministic runs (`DC_RUN_FRAMES`) and `DC_NO_STORY` skip the
  beat so tests stay byte-stable.
- Text loading normalises the ROM's in-band symbols: `[` → `'`, `\` → `.` and
  `j` → a line break inside the page (the `j` split is done at load time, so
  pages keep their real line count).
- The script cap rose from 64 to 512 strings (the crest texts sit at index
  ~483 in ROM order). Since `Game` now embeds ~1.2 MB of script storage it is
  allocated on the heap in `main.c` instead of on the stack.
- `DC_STORY_TEST=<crest>` / `DC_STORY_PAGE=n` open a story page directly and
  `DC_STORY_DEBUG=1` prints the cached crest indices, for deterministic
  screenshots.
- Verified: story page renders the real Earth-crest text; regression PASS;
  `check_areas` 113/113; audit agrees with the extractor on every room.

Next: use `GAME_DIALOGUE` for boss intros (bank `$BE:B947..C128` has the Phalanx
dialogue pairs) and for the item-found messages (`$BE:A427..A533`).

---

### Step 20 — Fire-crest piece pickups (done)

- Crest-item objects (`0x49`/`0x24`/`0x2D`/`0x2E`) now grant the next
  **Fire-Crest element** (Buster → Tornado → Claw → Demon Fire) before their
  stat bonus, matching the ROM's own `"YOU GOT THE PIECE OF THE FIRE CREST
  CALLED ..."` pages (`$BE:A427..A533`). The pool raises
  `OBJECT_EVENT_FIRE_PIECE` and `Game_UpdateSimulation` opens `GAME_DIALOGUE`
  with that piece's pages (narrative runs only).
- `DC_FIRE_TEST=<1..4>` opens a piece page directly for screenshots, and the
  player trace CSV gained a `fire` column so the flow is assertable.
- Regression now walks into the area-3 piece and asserts `fire` goes 0 → 1.

Verification: page 2 renders `"TORNADO" / WITH IT YOU CAN JUMP` through the
normalised text path; regression PASS.

Next: boss-intro dialogue using the `$BE:B947..C128` Phalanx sets once their
area mapping is pinned down, and the intro before Area 0.

---

### Step 21 — Stage select and transition fixes (done)

- New tool `tools/campaign_graph.py`: builds the transition/gate graph from the
  extracted rooms. **All 113 rooms are reachable from 66 stage-entry rooms**
  (rooms no other room targets) — those entries are now written to
  `campaign.json["stage_entries"]`.
- Overworld **stage select** (X toggles it): a paged list of every stage entry
  with its area number and kind (STAGE/BOSS), UP/DOWN select, LEFT/RIGHT page,
  ENTER travels, X closes. This makes all extracted content reachable from the
  map even though the original map layout is not reproduced. `DC_STAGE_SELECT=1`
  / `DC_STAGE_INDEX=n` open it for captures, and demo 30 drives it in tests.
- Two transition bugs found by testing the stage select:
  - Rooms **without a boss** satisfied the boss-gate check, so a small room whose
    world width was under the spawn point gated out on the first frame. The gate
    now needs `objects.boss_present`.
  - Door boxes padded `+20/+8` px, which made a door trigger from the spawn
    point of small rooms (instant loop). Padding is now `+10/+10`.
- Regression gained a stage-select travel check (demo 30 lands in area 16 and
  stays there) on top of the existing campaign traversal.
- Verified: regression PASS, `check_areas` 113/113, graph reachability 113/113.

Next: replace the placeholder six-node map with the real region/stage layout once
the map table is decoded; the stage list is the stopgap that keeps every room
playable.

---

### Step 22 — Campaign completion test (done)

- The per-frame trace moved out of `Game_UpdateSimulation` into
  `Game_TraceFrame`, called at the end of `Game_Update`. Rows are now written
  for every state (title, clear, overworld, dialogue), so tests can observe
  mode transitions; the CSV gained a `mode` column (`GameState`).
- `DC_BOSS_DEFEATED` now sets the full defeat state (hp 0, `boss_alive=false`,
  `boss_defeated=true`, event raised) instead of only deactivating the slot, so
  the clear flow is deterministic for every boss species.
- New `tools/check_campaign.py`: for every stage entry that spawns a boss it runs
  `DC_CAMPAIGN=1 DC_BOSS_DEFEATED=1` and requires the trace to reach
  `GAME_CLEAR`. Full sweep: **7 boss entries clear, 59 entries are traversal
  stages**. The regression runs a 7-area subset.
- Regression additions: boss entries clear, `GAME_CLEAR` → overworld, stage
  select travel, plus the existing demos/area/fire/save/password checks.
- Verified: regression PASS, `check_areas` 113/113, `check_campaign` 7/7.

---

### Step 23 — Ghoul descent and stage-clear tracking (done)

- The `$B2E8` decision routine is ported as a native predicate: the ghoul only
  commits to a leap when the player is below/beside its ledge or well outside
  firing range, otherwise it keeps firing. The leap's landing check now requires
  a few airborne frames and a real drop, so it can leave the perch instead of
  landing back on it — verified on the Area 1 perch: **y 96 → 160 → 176** while
  advancing on the player (regression asserts the descent).
- The stage select tracks clears: `Game.area_cleared[113]` is set in
  `Game_CompleteArea`, saved as a hex string (`area_cleared`) in the save format
  (backward compatible: absent → zeros), and drawn as `DONE` rows plus a
  `N stages  N cleared` progress line.
- Verified: regression PASS (including save round-trip), stage select screenshot
  shows the progress line.

Next: boss-intro text for the seven boss entries, and the `$DEA2` secondary
behaviour table (random idle/attack choices) for the ghoul.

---

### Step 24 — State-driven music tracks (done)

- `audio.c` now builds a small bank of procedural chiptune loops instead of a
  single track: `MUSIC_TITLE`, `MUSIC_STAGE`, `MUSIC_BOSS`, `MUSIC_ENDING`
  (64 steps each, different tempos/duty cycles). `Audio_SetTrack` stops the
  previous loop and starts the new one; `Audio_StartMusic` maps to the stage
  track for compatibility.
- `Game_SyncMusic` (called from `Game_Update`) picks the track from the state:
  title → title theme, ending → ending theme, gameplay/pause/subscreen/shop →
  boss theme while `objects.boss_present && boss_alive`, otherwise the stage
  theme.
- Verified with `DC_AUDIO_FORCE=1 DC_AUDIO_DEBUG=1` and a dummy SDL device:
  `4/4 tracks loaded`, stage gameplay selects track 2, area 0 selects track 3
  (boss), title selects track 1. Audio stays off in deterministic runs.

Next: fade between tracks instead of hard cuts, and area-specific
instrumentation once the ROM's music format is decoded.

---

### Step 25 — End-to-end campaign playthrough check (done)

`tools/check_playthrough.py` drives the shipping binary through the whole
campaign loop with deterministic hooks and asserts each observed `GameState`:

1. title → NEW GAME → **Area 0** (playing);
2. Area 0 boss defeated → **GAME_CLEAR**;
3. `GAME_CLEAR` + Enter → **overworld**;
4. overworld stage select + Enter → **Area 16** (playing);
5. Area 49 boss defeated → **GAME_CLEAR**;
6. overworld keep node + Enter (password with 4 stages cleared) → **GAME_ENDING**.

All six steps pass, and the run is part of `run_regression.py`. Supporting hooks:
`DC_OVERWORLD_X/Y` place the ship, demo 31 confirms the node, and the password
encoder in the tool mirrors the native base-20 codec (note: the alphabet string
has 21 characters but both encoder and decoder use 20 symbols).

This is the strongest evidence that the **original campaign loop is playable end
to end** in the port: start, clear, map, stage travel, boss clears and the
ending all work through the real game code.

---

### Step 26 — Pause menu with manual save (done)

The pause menu now offers **RESUME / SAVE / RETURN TO MAP** (or **QUIT TO TITLE**
outside campaign mode):

- `SAVE` writes the same versioned progress file as the area-clear autosave and
  shows a `SAVED` hint for 90 frames (the menu stays open).
- `RETURN TO MAP` opens the overworld in campaign mode; outside it the game
  returns to the title.
- `Pause` (the SNES Start key) resumes directly, as before.
- `DC_STATE=pause` opens the menu for captures, and demo 32 (down + confirm)
  drives the save path in the regression: the suite asserts a save file with an
  `area` field is produced.

![Pause menu](out/pause_menu.png)

Note: deterministic runs skip saving unless `DC_SAVE_FORCE=1` is set, which is
why the regression sets it.

---

### Step 27 — Species sheet validation and enemy silhouettes (done)

- `extract_species.py` now **drops ambiguous sheets**: when two species produce
  byte-identical images the capture did not show either species' own sprite
  (both injections fell back to the same object). Current result: `08`, `10`,
  `2C`, `96` and `A5` are rejected, leaving trustworthy sheets for `07`, `2D`,
  `49`, `57` and `67`.
- `render.c` no longer falls back to the player's sprites for species without a
  sheet. It draws a small silhouette (body, head, eyes, legs; larger with horns
  for bosses) tinted from the species id, so rooms no longer look full of
  Firebrand clones. Example: the Area 2 skeletons now stand as distinct
  silhouettes beside the player.
- Verified: species manifest has 5 sheets, regression PASS, Area 0/2 captures
  show the new placeholders.

Remaining sprite gap: the ROM's metasprite groups compose from the decompressed
area OBJ CHR (base tile `0x60`), but the species→group mapping is still unknown,
so authentic frames cannot be baked offline yet.

---

### Step 28 — Boss attacks and hit feedback (done)

- Non-Somulo bosses now fire a **three-shot spread** every 110 frames: the shot
  direction is the unit vector toward Firebrand, rotated by ±0.35 rad, spawned
  through the same `OBJECT_ENEMY_SHOT` path the ghoul uses. Standing next to the
  Area 3 boss for 260 frames now costs all 4 HP (4 hits taken, 345 projectile
  rows in the object trace).
- New `Object.hit_flash`: set to 8 frames when a fireball hits an enemy or boss;
  the renderer tints the sprite white for the first frames and pink afterwards,
  so hits read clearly.
- Somulo already had its lunge/leap cycle; both boss families now have a
  projected threat instead of only contact damage.

Note: layer-separated captures (`DC_LAYER_MASK=1` for BG2, `=2` for BG1) later
showed that the "black rectangle" in Area 3 is the room's own backdrop: BG2 alone
draws mountains on the left and cave wall on the right, and the middle of that
screen is transparent BG2 tiles, so the SNES shows the backdrop colour
(CGRAM[0] = black) there. Not a port bug.

---

### Step 29 — BG2 frame merging and layer-separated diagnosis (done)

- `extract.py` can now merge CHR/tilemap words across sampled frames of a BG2
  capture (`DC_BG2_MERGE_FRAMES`, default 40). The backdrop atlas for a captured
  area therefore includes tiles that were streamed in at other camera
  positions instead of only the manifest frame (`bg2 capture area 3: merged 24
  frames`).
- **Corrected diagnosis:** the Area 3 "black band" is not missing data. With
  `DC_LAYER_MASK` the layers can be inspected separately:
  - BG2 only: mountains on the left, cave wall on the right, transparent middle;
  - BG1 only: terrain/paths only, everything else transparent;
  - combined, the transparent middle shows the backdrop colour, and the
    captured CGRAM[0] for that frame is black.
  So the port reproduces the hardware output. Every CHR base was also checked
  (base 0 gives the richest atlas), ruling out a base mismatch.
- `DC_LAYER_MASK` is now documented in the README hooks table.

Next: keep `DC_BG2_MERGE_FRAMES` for areas whose backdrops really are streamed
(it is harmless otherwise), and stop treating the Area 3 middle as a bug.

---

### Step 30 — Area entry banner (done)

Every area entry (initial load, `Game_Reset`, or `Game_TransitionToArea`) arms
`Game.intro_timer = 110`. While it runs and the game is playing, a banner fades
in over 20 frames, holds, and fades out over the last 25:

```
STAGE 02        (or BOSS STAGE / AREA from the room classification)
WORLD 2048x512
```

This gives the player orientation when arriving through the stage select, and
surfaces the room classification in-game. Verified by screenshot (STAGE 02 over
Area 2) and the regression suite stays green.

---

### Step 31 — Attract mode (done)

- Idling on the title for ~10 seconds starts a **demo**: the game loads the
  Colosseum (Area 0), scripts walk-right/shoot inputs, and shows
  `DEMO   PRESS START` at the bottom. Start/Pause/Jump/Special cancels back to
  the title; `DC_NO_ATTRACT=1` disables it.
- Verified by trace: mode 0 for 600 frames, then mode 1 in Area 0 with the
  player walking (x 128 -> 197); demo 33 presses Start after the demo begins and
  the state returns to 0. Both cases are regression checks.

---

### Step 32 — Enemy AI split and generic behaviour (done)

Found and fixed a real correctness bug: the enemy update chain ended in a plain
`else` that ran the **ghoul** state machine for every species that was not
`$2C`/`$07` — so the most common enemies in the campaign (`$81` with 43
placements, `$10` with 35, `$26`, `$08`, ...) hopped around with the ghoul's
perch/dive logic.

- The ghoul branch is now `else if (o->species == 0x67)`.
- All other species get a **generic AI**: patrol ±48 px around the spawn and
  walk toward the player when within 140x64 px, with a floor snap each frame.
  This is a placeholder until the individual ROM handlers are ported, but it
  keeps rooms lively and stops the wrong behaviour leaking between species.
- Verified in Area 21 (species `$81`): object traces show enemies patrolling
  (x ranges of ~40–50 px) and switching to the chase when the player is close;
  Area 21 also shows the new `STAGE 21 / WORLD 512x2048` banner.

Species handler addresses for the next ports are recorded here:
`$81 -> $82:FB0C` (JSL script list), `$10 -> $82:AC86`, `$26 -> $82:ABEF`,
`$08 -> $82:974D`.

---

### Step 33 — Placement-aware generic enemies (done)

- The generic AI now looks at the **placement**: if there is no floor under the
  spawn, or the floor is more than 24 px below it, the enemy is treated as a
  flyer — it hovers with a sine bob around its spawn and drifts toward the
  player in 2D. Grounded spawns keep the patrol/walk-toward behaviour.
- This fixes the common `$10`/`$81` placements that hang in the air: they used
  to be pulled down onto walkable ground by the floor snap.
- Verified in Area 12 (`$10` x4): object traces show them bobbing over ~13 px
  and drifting horizontally instead of snapping to a floor; regression PASS,
  `check_areas` 113/113.
- Species `$10`'s real handler (`$82:AC86`) is a 7-state machine
  (state 0 wait, 1 fly-in, 2 swoop with `vx=0x40/vy=0x80`, ...). Porting it
  remains a multi-hour job, recorded here with the dispatch table at `$ACA6`.

---

### Step 34 — Dive and lunge attacks for generic enemies (done)

- Flyers (no floor under the spawn / floor far below) now **swoop**: when the
  player is within 64 px horizontally and 180 px vertically and the cooldown has
  elapsed, they lock a velocity toward the player's position for 22 frames, then
  recover with a 90-frame cooldown.
- Grounded generic enemies **lunge**: a 14-frame horizontal burst at 2 px/frame
  when the player is 14–52 px away, with an 80-frame cooldown.
- Verified in Area 12 (species `$10`): slot 0 dives from y 327 to 429 (the
  player's level) and the player loses 1 HP; the other three keep hovering.
  Regression PASS.

This makes unported species threatening without pretending to be their real
handlers; the ROM state machines remain the fidelity target.

---

### Step 35 — Gamepad stick, deterministic input, from-scratch build (done)

- **Analog stick:** the left stick now mirrors the d-pad past a 0.35 dead zone,
  and the subscreen opens from LT/right-stick-click in addition to Tab/I/V.
  Face buttons were already mapped (A jump, X/Y shot, B special, Start/Pause).
- **Deterministic input isolation (CI fix):** with `DC_RUN_FRAMES` set,
  `Input_Read` no longer samples physical devices at all — only the demo script.
  A held key or a drifting gamepad axis could perturb demo timing and produced
  intermittent failures (attract cancel, stage-select travel) even though the
  same run passed manually. Regression now passes repeatedly on both builds.
- **From-scratch build verified:** a clean `cmake -G Ninja
  -DDC_RAYLIB_ROOT=C:/raylib/raylib` configure + build in an empty directory
  produced `demonscrest.exe` and the full regression suite passed against it.
- **Environment note:** a leftover `DemonsCrestSNESRecomp` process holding a GL
  context made *every* new game window fail with
  `Win32: Failed to create interface`; terminating the stale process fixed it.
  Worth checking first whenever the port suddenly cannot open a window.

---

### Step 36 — Recomp save-state captures and split BG atlases (done)

The user supplied two late-game recomp saves: `save10.sav` (max health, all
items/transformations, Area 2 forest) and `save11.sav` (Mode 7 overworld map).
New tooling loads them and captures real gameplay frames.

- **`tools/oracle/capture_save_frames.py`**: resumes a recomp save, advances a
  warmup, then writes frames in the extractor's format (`fNNNNNN.json` +
  `.vram.bin`). It first waits for a *fully lit* frame (`inidisp & 0x0F >= 0x0C`)
  because `run_to_frame` can stop during blanking and baking those samples
  produces black atlases. Example:
  `python tools/oracle/capture_save_frames.py --save 10 --out captures/save10 --frames 0,20,40`.
- **Split BG atlases:** BG1 and BG2 CHR live at different bases, so one atlas
  per palette cannot serve both. The extractor now writes
  `bg_areaN_palP.png` from the ROM-decompressed CHR (BG1) and
  `bg2_areaN_palP.png` from the captured frame's streamed CHR (BG2), and the
  renderer picks the BG2 set for layer 0 (`Assets_AreaBg2`,
  `Assets_HasAreaBg2`). This replaces the earlier (incorrect) attempt to mix
  both sources into one VRAM image.
- **Finding:** Area 2 has no BG2 tilemap at all (all-zero words) — its trees are
  *static level sprites*, so save10's area adds no backdrop. The capture path is
  in place for areas that do use BG2.
- Verified: `check_areas` 113/113 and the regression suite pass after the atlas
  split.

Next: use `save11` to capture the Mode 7 overworld map (registers, tilemap and
palette) and replace the procedural map with the real one.

---

### Step 37 — Three more captured areas (save7/8/9) (done)

The user supplied saves in three more areas; `capture_save_frames.py` converted
them and they are registered in `tools/dc_extract/bg2_captures.json`:

| save | area | result |
|---|---|---|
| save7 | **24** (raw `$008D` 48) | **excellent** — dungeon shelves, bottles, skulls, chains; the split BG1/BG2 atlases are clearly working |
| save8 | **37** (raw 74) | **excellent** — forest cave with tree trunks, foliage and stalactites |
| save9 | **29** (raw 58) | dark: a 256x256 room that is essentially black (likely colour-math driven), no visible backdrop |

> The area numbers in this old table were the raw `$008D` bytes; the real area is
> `$008D / 2`. Verified by `tools/oracle/map_saves_to_areas.py` (BG1 screen
> matching + object-pool overlap), see `docs/SAVE_TO_AREA.md`.

Area 48/74 screenshots show the room rendering as intended, which validates the
BG1-from-ROM + BG2-from-capture atlas split introduced in Step 36.

Note: `captures/` is git-ignored (ROM-derived, large), so these captures only
exist locally; the manifest entries document which frames to regenerate. The
recomp saves themselves are the source of truth.

**Correction — Area 48 is a shop, not a boss room.** Scanning the object pool
over 240 frames of save7 shows exactly one live object for the whole span:
slot 8, flags `0x96`, **species `$10`**, at a fixed position. The room art
(shelves, bottles, skulls, chains, guillotine gate) matches a shop interior, and
the purple silhouette in the screenshot is that NPC. So:

- species `$10` is an **NPC/shopkeeper**, not an enemy — likewise `$81` (43
  placements) is very likely another NPC/prop species, which explains why those
  rooms looked "populated by silhouettes";
- the enemy sprites still missing are `$2C` (skeleton), `$26`, `$08` and the
  bosses `$96`/`$A5`;
- capturing species from a real save needs a save where the object is actually
  on screen *and* the frame counter/port state is fresh; the pool read itself
  works (chunked 0x100 reads; the server truncates longer requests).

`tools/oracle/capture_area_objects.py` implements the pool → per-species capture
record path and is kept as WIP (needs a reliable frame/port handshake before it
can be trusted in the extraction pipeline).

---

### Step 38 — Four endings (done, gating approximate)

The user clarified that the rooms previously assumed to be "boss areas" are
**ending sequences**, and linked the four reference endings (Bad / Normal / Good
/ True). Reference frame sets were downloaded and transcribed
(`dcbuild/endings/*_sheet*.png`), and the narration is now a data asset:

- `tools/dc_extract/build_endings.py` writes `endings.json` with the four
  variants, word-wrapped to the 8px font (30 chars), plus an epilogue index.
  The bad ending's epilogue uses the ROM string at `$81:8DF2`
  ("I NEVER EXPECTED THAT PHALANX WOULD BE DEFEATED..."), which the reference
  frames confirmed is that text.
- `src/assets.c` loads it into `EndingData`; `src/game.c` selects the variant
  from the collected power crests (`0 -> bad`, `1-2 -> normal`, `3-4 -> good`,
  `5 -> true` — an approximation of the real conditions), pages through two
  narration lines per screen, then shows the epilogue (or `THE END`).
- `DC_ENDING=bad|normal|good|true` previews a variant; `DC_STATE=ending` picks
  one from the save's crests. All four variants screenshot correctly.
- The narration itself is not plain ASCII in the ROM (the battle lines at
  `$BE:B947..C128` are), so it is transcribed from reference captures and this
  provenance is recorded in `endings.json`.

Next: pin the real ending conditions (they likely depend on specific crests /
talismans, not just a count) and capture the ending artwork from saves at each
ending to replace the current black overlay.

---

### Step 39 — Ending coverage in regression; Mode 7 investigation (done)

- The regression suite now asserts that **each of the four ending variants
  renders** (`DC_STATE=ending`, `DC_ENDING=bad|normal|good|true`, mode 10).
- **Mode 7 map extraction attempted and not solved:** composing the 128x128 map
  from save11's VRAM yields noise. In Mode 7 the tilemap and the 8bpp character
  data share the same VRAM and are accessed through the hardware's interleaved
  addressing, so a naive "word (y*128+x) = tile, byte tile*64+y*8+x = pixel"
  decode reads character data as map entries. All three plausible variants
  (low/high byte, high-byte tile) were rendered and are noise. Cracking it needs
  a proper Mode 7 reference (the `m7a..m7y` registers are also not exposed by
  `get_ppu_state`), so the procedural overworld stays for now.
- Save7 (`Area 48` shop) still shows the NPC object only in some sessions;
  `capture_area_objects.py` is kept with a dynamic debug port, but species
  capture from real saves is not yet reliable enough for the asset pipeline.

---

### Step 40 — Verification sweep (done)

Full evidence run recorded for the current build:

- `run_regression.py` — **PASS** (demos 6,7,9,10,11,12,13; boss clears; 12-area
  load subset; campaign playthrough; four ending variants; save round-trip;
  password codec; fire pickup; stage-select travel; pause save).
- `check_areas.py` — **113/113 ok**.
- `check_campaign.py` — **7/7 boss entries clear** (59 traversal stages have no
  boss object).
- `check_playthrough.py` — **6/6 steps** (title → Area 0 → clear → overworld →
  stage travel → boss clear → ending).

The README now documents these commands, the current results and the known
fidelity gaps as the release checklist.

### Step 41 — Mode 7 world map extracted and integrated (done)

The save11 capture finally cracked Mode 7, using the SNESdev wiki layout:

- the **tilemap** is 128x128 one-byte entries in the **low byte** of the first
  16384 VRAM words (rows of 128, top to bottom);
- **tile pixels** are chunky 8bpp in the **high byte**, 64 pixels per tile
  (left to right, top to bottom) at `word = tile*64 + y*8 + x`.

`tools/dc_extract/build_world_map.py` renders that into a 1024x1024
`world_map.png` (accepts a capture frame or explicit `--vram/--cgram` dumps; the
oracle probe dump is the reliable source because running extra frames can make
the game re-upload VRAM).

In-game, `DrawWorldMapView` draws a 256x224 viewport centred on the ship over the
real map, with the ship cursor, `OVERWORLD`, gold and a hint bar; the procedural
pseudo-3D map remains as a fallback when the asset is absent. The stage-select
overlay still opens on top of it (X).

Verified: overworld screenshot shows the real Ghoul Realm with the cursor;
regression PASS; `check_areas` 113/113.

Next: use the map's castle icons to place stage markers at their true map
positions (the current stage list is a separate overlay), and apply the Mode 7
affine transform for rotation/zoom like the original.

---

### Step 42 — Mode 7 affine overworld (done)

The overworld view is now a real Mode 7-style affine camera over the captured
world map:

- `Camera2D cam = { offset = screen centre, target = the ship's map pixel,
  rotation = -overworld_angle, zoom = 1 }` with `BeginMode2D` around the full
  1024x1024 texture draw. This fixed the earlier attempts where
  `DrawTexturePro`'s pivot/rotation either drew nothing or exposed the clear
  colour at the corners.
- L/R rotate the map at 1.5 deg/frame around the ship (the angle wraps 0-360);
  the ship stays at the screen centre with its cursor drawn there.
- `DC_OVERWORLD_ANGLE` sets the initial angle for screenshots; with 20 degrees a
  castle icon is clearly visible next to the cursor.

Verified: rotated overworld screenshot; regression PASS; `check_areas` 113/113.

Next: map the castle icons to the stage-entry list by their world positions so
the cursor can land directly on a castle instead of using the separate stage
overlay.

---

### Step 43 — Ending backdrop and map zoom (done)

- Ending screens now draw the captured Mode 7 world map as a dimmed backdrop
  (tinted and veiled) instead of flat black, which reads much closer to the
  reference ending sequences while the transcribed narration pages show.
- The overworld camera gained **zoom**: Q/E (or the shoulder buttons) scale
  `overworld_zoom` between 1.0x and 2.0x, `DC_OVERWORLD_ZOOM` sets it for
  captures, and the hint bar advertises it. Zoom keeps the ship centred like the
  rotation does.

Verified: zoomed and rotated overworld captures, ending backdrop capture;
regression PASS.

---

### Step 44 — Release build verification (done)

A **clean** configure + build (`cmake -G Ninja -DDC_RAYLIB_ROOT=...` in an empty
directory) was run and the whole sweep executed against that binary:

- `run_regression.py` — **PASS**
- `check_areas.py` — **113/113 ok**
- `check_campaign.py` — **7/7 boss entries clear** (59 traversal stages)
- `check_playthrough.py` — **6/6 steps**

The README now documents the asset-regeneration pipeline (base extraction,
optional save-state captures, world map, endings) so a fresh clone can rebuild
everything from the ROM and captures.

### Step 45 — Campaign completion summary (done)

The original campaign loop is **playable end to end** in the port, verified by
automation rather than by hand:

1. **Title → new game → Area 0** (`check_playthrough.py` step 1).
2. **Boss defeat → area clear → overworld** (steps 2-3).
3. **Overworld → stage travel** with the real Mode 7 map, rotation and zoom
   (step 4; `DC_STAGE_SELECT` lists all 66 stage entries).
4. **Stage combat** with the ported ghoul AI, generic enemy AI (patrol / chase /
   dive / lunge), boss spread attacks and damage feedback.
5. **Boss clear → Area Clear → map or next stage** (step 5).
6. **Endings** — all four variants gated by crest count, with transcribed
   narration and the ROM epilogue (step 6, plus per-variant regression checks).

Supporting systems: save/continue and manual pause-save, password codec, shop
dialogue from ROM text, crest/fire-piece story beats, area-entry banners,
attract mode, four music loops, 113/113 rooms loading, 7/7 boss entries
clearing, and the full regression suite.

What remains is **fidelity**, not flow: individual species AI beyond the ported
ones, captured sprites/backdrops for the remaining areas, HDMA/tile animation,
ROM BRR audio and the exact retail menus. The campaign plan keeps those as open
items.

### Step 46 — First-areas saves: captures, species probing, tools (done)

Twelve new recomp saves (save0a..save11a, first areas + Somulo/statue/Arma)
produced three tooling pieces and four new captured areas:

- `tools/oracle/probe_saves_batch.py` — resumes a list of saves, reports area,
  player, live object species and writes VRAM/CGRAM/OAM/WRAM dumps per save.
  Results: save0a area 0 with **species `$33` (Somulo)**, save2a area 2 (`$67`),
  save5a area 4 (`$67`, `$2C`x2), save6a/7a area 6 (`$26`, `$07`), save8a-11a
  area 6 (Arma scenes, no boss object at the sampled frame).
- `tools/dc_extract/probe_to_frames.py` — converts a probe into the extractor's
  capture-frame format, so `bg2_captures.json` now dresses **areas 0, 4, 6 and
  34** as well (9 captured areas total). Screenshots show the colosseum walls and
  torches, the area-4 room and area-6 mountain backdrop.
- `tools/dc_extract/probe_to_species.py` + `bake_object_sprites.py` — turn live
  objects into sprite records by clustering OAM entries around the projected
  object position, with plausibility scoring (fill ratio/aspect) so fragmented
  sheets are rejected instead of shipped.
  - Accepted: `$26` (32x48) and `$07` (25x32) plus the existing item/urn/ghoul
    sheets (`$2D/$49/$57/$67`).
  - **Rejected as fragmented:** Somulo `$33` and the skeleton `$2C` still fall
    back to silhouettes. Multi-part bosses need their OAM base/count field
    (candidate byte offsets `$0D/$0E` in the object record) rather than spatial
    clustering.
- `tools/oracle/read_bg3_text.py` decodes a save's BG3 tilemap to ASCII to map
  cutscene frames onto script entries. The Arma saves sampled at 90 frames show
  only HUD glyphs, so the dialogue box was not open at that moment; those saves
  need a few frames of input (or an earlier resume point) to capture the line.

Regression stays green after regenerating the assets.

---

### Step 47 — Second save batch: city, forest, water, cave, boss (done)

Twelve more saves (`save0b..save11b`) covering the next area:

- **Areas captured:** 8 (city), 10 (forest/water), 12, 14 (dark cave) and 16
  (boss room). With the earlier set, **14 areas** now have real backdrops
  (`bg2_captures.json`); screenshots show the town skyline, the water/vine room
  and the cave.
- **Species added:** `$08` (46x48), `$10` (27x48), `$81` (70x36) from areas
  10/12 and **`$6C` (16x16)** — the tiny eyeball from the Area 16 boss fight.
- **Boss-part detection:** the object-pool filter was too strict (`flags & 0x80`);
  boss parts use other bits, so probes now accept any non-zero flag/species
  pair. That exposed the Area 16 parts: `$6C` x10 (tiny eyeballs), `$6B`, `$69`,
  `$6D`, `$21` — and `$6C` baked into a clean 16x16 sheet. The large eyeball and
  tentacle clusters (119 parts, fill 0.12) are still rejected as fragmented.
- **Cave darkness:** Area 14 renders dark, which matches the candle gimmick; the
  port has no candle/lighting logic yet, so it stays dark (documented).
- City NPC dialogue was not captured: save1b has no live NPC object at the
  sampled frame (NPCs may be level sprites or spawn on interaction).

Regression PASS after regenerating the assets.

---

### Step 48 — City NPC conversation from the ROM script (done)

`save0ba` (NPC mid-conversation) let the BG3 reader decode the real line, and
matching it in the extracted script gave the whole exchange:

- `$85:9596` "HEY YOU! I HAVEN'T SEEN YOU AROUND HERE BEFORE!"
- `$85:95CD` "ARE YOU A STRANGER HERE?" plus the `YES   NO` prompt at `$85:9587`
- YES branch: `$85:95EB` "THEY SAY THAT THE RED DEMON KNOWN AS FIREBRAND HAS
  RISEN", `$85:962C`, `$85:9667`, `$85:968E` ("...TAKE CARE OF YOURSELF")

Implemented:

- `GAME_DIALOGUE` gained scripted conversations: `talk_seq/talk_len/talk_pos`,
  a YES/NO choice state drawn under the page, and selection with up/down.
- NPC objects: new `OBJECT_NPC`/`LEVEL_OBJECT_NPC` kind, inert in the update
  loop, drawn from the captured `$96` sheet, talkable with A within 30x36 px.
  (`$10` opens the shop instead.)
- `tools/dc_extract/merge_npc_objects.py` copies probed NPCs into room JSONs
  (the extractor's object lists miss scripted NPCs).
- `DC_TALK=<step>` jumps straight to a conversation page for captures; demo 34
  presses A near the NPC and pages through, and regression asserts that mode 11
  (dialogue) is reached.

Verified: greeting/question/story captures and the in-world demo both show the
ROM text; regression PASS.

Note: the real city is wider than our extracted 256x768 area 8 (the save has the
player at x=604), so the NPC is placed near the room spawn for the demo; a full
city extraction needs the multi-screen room set.

---

### Step 49 — Plan for a fully playable original (done)

`docs/PLAN_FULL_PLAYABLE.md` audits the project against the original game and
lays out the route to "fully playable": a definition of done (D1-D11), a
gap analysis (navigation, placements, boss roster, sprites, terrain, forms,
items, events, endings, map landing, audio, menus, QA), nine milestones (M1-M9)
with tasks and acceptance tests, a ten-task backlog, the save/tooling wishlist,
risks and the fan-game bridge (prequel Somulo battle → original → sequel).

Headline numbers from the audit: 113/113 rooms load, 66 stage entries, 14 areas
with captured backdrops, 11 species sheets, 518 script strings, four endings,
but only **4 rooms with real exits** (95 auto-advance via gates), **148 enemy
placements across 7 species**, and **14 boss objects in three species** — so the
loop is playable while the game is not yet.

### Step 50 — Save batches c/d: eight new areas, real shop stock (done)

- Areas **18, 20, 24, 28 (burning forest), 32 (hidden room), 96 (potion store),
  100 (burned state), 102 (boss)** captured from saves c*/d*; the capture list
  now holds 22 areas.
- Species sheets grew to 16 (adds `$23 $25 $2E $28 $29 $2A $48 $63 $65 $79 $97`
  and refines others); multi-part boss clusters are recorded with their source.
- **The potion store's own text** came out of the BG3 layer: greeting
  `$85:87D5`, stock menu `$85:88A0` and descriptions — Mercury 6, Sulfur 10,
  Herb 25, Elixir 100 (extra life), Ginseng 140 (full heal), plus the
  "CHEAPSKATE" line `$85:8B17`. `GAME_SHOP` now uses that stock, those prices
  and the real messages, with an EXIT row and a gold/urns footer.
- `merge_npc_objects.py` gained `--x/--ground-y/--clamp`; NPC placement is part
  of the asset regeneration, and regression keeps the city conversation green.
- `tools/oracle/drive_save.py` added: replay a savestate with synthetic input
  (`set_controller`) and capture a BMP (`screenshot`) — used to probe later
  moments from a single save.
- Notes: `save11d` was listed but not on disk; the burning/burned variants are
  captured but not modelled as stage states yet.

### Step 51 — Guides integrated; completion-based endings (done)

- Read the three guides added to `docs/` and folded their facts into
  `PLAN_FULL_PLAYABLE.md`: the item guide's crest/Fire-shot rewards, 16 life
  extensions, urn/vellum/talisman checklist; the endings guide's four-ending
  rules (bad <50%, normal 50-99%, good at 100% after the Crest of Heaven, true
  after the Dark Demon) and the post-credits secret password.
- `Game_EndingVariant` now computes **completion** (5 crests, 4 Fire shots, 5
  talismans, 5 urns, 5 vellums, life extensions) and returns bad under 50%,
  normal up to 99%, good at 100%; the true variant stays behind `DC_ENDING`
  until the Dark Demon exists.
- Regression PASS after the change (all four variants still render).

### Step 52 — Save batch e/ee: 10 more areas, shop variants, talisman texts (done)

- Captured areas 36, 38 (wind), 40, 42, 46 (lake), **84 (final boss stage)**,
  92 (library), 98 (spell shop), 104 (minigame parlour) and 110 (second Black
  Lotus): **32 areas** with backdrops.
- Species sheets reach 29 (`$06 $09 $12 $15 $41 $87`, `$A5` cluster).
- Shops now vary by area: the town Black Lotus sells all five potions, the
  second one (area 110) stops at Elixir; the spell shop (area 98) shows
  "I CANNOT HELP YOU UNLESS YOU BRING ME A VELLUM FIRST" (`$85:8370`) when the
  player has no vellum.
- Library talisman description strings located (`$85:8C51/8CB3/8D17/8D79/8DD0`)
  ready to wire to the NPC; the minigame parlour greeting was also read.
- The final-boss stage backdrop (the Dark Demon's face) is captured; the bad
  ending cutscene is the mode-7 area 192.

### Step 53 — M1 starts: area graph, navigation report, first observed doors (done)

- New tools: `build_area_graph.py` (area nodes + door/gate/stage-entry edges +
  save-observed doors), `check_navigation.py` (reachability tiers, missing-door
  and out-of-world reports), `merge_observed_doors.py` (writes observed doors
  into room JSONs).
- Current graph: 113 areas, 53 extracted doors, 94 gates, 66 stage entries;
  **only 2 areas reachable from area 0 through real doors** (11 with gates) —
  the measured size of the M1 gap.
- Level I's saves gave the first ground-truth doors: `2 -> 4` at (1706,300) and
  `4 -> 6` at (2025,140). The runtime walks `2 -> 4` (regression asserts it) via
  `DC_BOSS_CLEAR=1` + campaign mode; `4 -> 6` is reported as out-of-world.
- **Room extraction gap confirmed:** area 4 is 1024 px wide in our data but the
  save puts the player at x=2025; area 8's city is 256 px against x=604. Rooms
  must be re-extracted with their full multi-screen width before M1 can finish.
- `next_area = -1` in area 4 marks the return-to-map door; the runtime should
  treat -1 as "back to the overworld".

### Step 54 — Full-stage maps indexed (done)

- `docs/FullMaps/images` holds 43 community maps (1:1 stitches of the original
  rooms). `tools/dc_extract/index_full_maps.py` writes `docs/FullMaps/index.json`
  with each map's pixel size and screen grid, grouped by level (Murkland,
  Ruined City, Dark Forest, Towers of Doom, Mountains, Poseidonia, Phalanx's
  Fortress, Demon's Hideout, minigame shop).
- Visual check: the Murkland Colosseum map matches our **area 0** screenshots
  (arched purple walls, torches) — a confirmed name<->area identification. The
  map is 4 screens wide while area 0 extracted as 3, which is exactly the kind
  of width gap M1 needs fixed.
- Planned use: a `match_maps.py` correlating rendered room BG1 against the maps
  to build the full name<->area table, then re-extract mismatched rooms with the
  map-derived screen grids and fill door bboxes from the maps.

### Step 55 — Full-grid extraction and the coordinate-space question (done)

- `extract.py` gained `--full-grid` (guarded; with `--full-room` it composes all
  used rows of the area's screen grid). Area 0 = 3x1 (768x256), area 4 = 4x2
  (1024x512) — so **our room sizes are correct** and the earlier "narrow room"
  theory is wrong.
- The level-I save has the player at x=2025 in area 4 (grid width 1024), which
  means the player coordinate is probably **level-wide** (shared across connected
  rooms, with a per-room origin subtracted on entry) or `$008D` is not the grid
  id. Next experiment: read the room-origin variable together with `$008D` and
  `$1030` in the level-I saves.

### Step 56 — Named saves, notes-to-edges, chunk model (done)

- `tools/dc_extract/build_room_names.py` parses saves named
  `lvl_<level>_<map-name>[_role]`, resolves the map name against
  `docs/FullMaps`, and writes the area->name/level table. Level III resolved:
  **thorn grove = area 20, underground dyke = 22, scula cave = 26** (with
  entrance/before_door/e1/e2/boss/boss_dead roles).
- `docs/LEVEL_TRANSITIONS.md` holds the door prose as a strict table; the tool
  turns it into edges (`room_name_edges.json`) using the `<room>_before_door`
  save positions: 20->22 at (909,412), 22->26 at (1687,33), 26->boss, 26->map.
- `build_area_graph.py` merges three edge sources (extracted, save-observed,
  notes) -> 59 doors.
- **Model confirmed: a map is a composite of chunk-areas.** Area 20 (512x256)
  seams into 21 (512x2048), which seams into 23 at five heights; 22 also seams
  into 23. That explains why maps are larger than any single extracted room and
  why save coordinates can exceed one chunk.
- `check_navigation.py` now roots reachability at the overworld (-1):
  **94/113 areas reachable via real doors (83%)**, 113/113 with gates. The
  19 gate-dependent areas are the shortlist for future door saves.
- Diagnostic: 3 areas still have no outgoing edge (14, 3, 30, 36, 9).

### Step 57 — Level IV names and the overworld marker set (done)

- `lvl_IV_*` saves resolved: **gryphon spire = area 36, misty skies = area 38**
  (boss parts `$82/$83/$84/$85`, reward `$48`). Transitions added to
  `docs/LEVEL_TRANSITIONS.md`: gryphon spire -> misty skies (right),
  misty skies -> boss (right), boss -> map (Claw piece).
- The graph now merges 7 note edges and treats named rooms as stage entries
  (the inferred entry list missed rooms that are also door targets inside their
  own level): **95/113 (84%) reachable via real doors**, 113/113 with gates,
  18 areas still gate-dependent, 4 chunks with no outgoing edge (14, 3, 30, 9).
- New tool `build_map_markers.py`: the map screen's stage icons are objects with
  species `$94`. Two snapshots show the retail progression in data:
  `save6ee` has 13 markers including (151,99); `map_new_stages` has 16, with
  (151,99) gone (final stage closed after passing the bad-ending limit) and four
  new markers (78,42), (90,39), (190,140), (202,137).
- `map_markers.json` stores the snapshots; the overworld can use them for landing
  and unlock state.

### Step 58 — Levels V/VI: seven more named rooms, sub-room edges (done)

- Poseidonia (`lvl_V_*`): **aquatica = 48**, **temple-and-hidden-chamber = 54**
  (roles include passage, persecution, persecution_trigged, boss, dead).
- Mountains (`lvl_VI_*`): **valley-of-the-grewon = 58**, **ice-spire = 62**,
  ice-spire side room = **64** (no community map), **ice-palace-corridor = 66**,
  corridor boss chamber = **68**.
- Notes parser supports `area:N` destinations so sub-rooms without a map still
  get edges: 62 -> 64 (life-up room), 62 -> 66, 66 -> 68, plus the level chains
  for 48 -> 54 and 58 -> 62. Notes table now 14 edges.
- Entry inference refined (a named room is an overworld entry only when no other
  named room of its level leads into it): entries are now 20 (III), 36 (IV),
  48 (V), 58 (VI); mid-level rooms are reached by doors.
- Graph: 95/113 (84%) reachable via real doors, 113/113 with gates, 18 areas
  still gate-dependent, 4 chunks with no outgoing edge.

### Step 59 — Levels I/II named; 87% reachable via real doors (done)

- Level I resolved: **cemetery = 2, slope = 4, abyss = 6** (correcting the
  earlier "level I = colosseum" guess). Level II: **dark avenue = 8,
  reservoir = 10 (item1 potion, item2 talisman passage), boneyard = 18**.
- Chains added: 2 -> 4 (mid boss), 4 -> 6, 6 -> map (Arma 1st), 8 -> 10 -> 18,
  18 -> map (boss). Notes table now 20 edges.
- Area 0 is the **game start**, not a map entry: added a `game_start` edge,
  which made area 17 reachable via its transition.
- Graph: **99/113 (87%) reachable via real doors**, 113/113 with gates,
  **14 gate-dependent areas** (1, 35, 43, 46, 52, 57, 63, 76, 77, 83, 88, 94,
  ...), 4 chunks with no outgoing edge (14, 3, 30, 9).
- Note: area 8's before-door save sits at x=988 while the chunk is 256 px wide —
  another instance of the map-composite/chunk model.

### Step 60 — Level 0, note edges merged into rooms, room names in the UI (done)

- Level 0: **colosseum = area 0**; walking right lands in **area 34** (the
  extracted target 17 was wrong for that door). Notes table 21 edges.
- `merge_observed_doors.py --trust-notes` merges note doors into room JSONs and
  drops contradicting extracted transitions: chains 2->4->6, 8->10->18,
  20->22->26, 36->38, 48->54, 58->64 are now walkable data.
- `assets.c` loads `room_names.json`; the area banner shows the map name and the
  stage-select list shows names where known (banner verified: "MURKLAND
  CEMETERY"; list: "STAGE RUINED CITY RESERVOIR", "STAGE RUINED CITY BONEYARD").
- Room-mapping validation via live BG1 tilemaps was inconclusive (rooms often
  draw on BG2 / probes can catch transitions); noted in the plan.
- Regression PASS.

### Step 61 — Level 0 advancement is a gate; two runtime bugs fixed (done)

- User clarification: area 0 and area 34 are **both colosseum rooms** (boss
  fights); the level advances 0 -> 34 after the boss. Notes table now 22 edges
  with `area:0 -> area:34`.
- Bugs found and fixed while wiring it:
  1. area 0's `gate_next_area` was **1** (wrong target) — now 34;
  2. the post-boss gate required `player->x >= world_w - 8`, which walls make
     unreachable (the player stops ~32 px inside) — threshold is now
     `world_w - 40`;
  3. `DC_BOSS_CLEAR` was applied in `Game_Reset`, before the level's boss object
     spawns, so it was overwritten — it is now applied in the transition check.
- Regression proves area 0 -> 34 (and area 2 -> 4) through real transition data.
- Shared map names are disambiguated: `murkland-colosseum` = areas 0/34,
  `mountains-ice-spire` = 62/64, `mountains-ice-palace-corridor` = 66/68; the
  name lookup prefers the `entrance` save.

### Step 62 — Endgame (VII/VIII) mapped; trust-notes merge fixed (done)

- Final stage VII: **front hall = 74, western bell tower = 76, eastern bell
  tower = 80, hall of agonized souls = 82, Phalanx's chamber = 84, demon realm =
  86**. Special stage VIII: **tunnel = 88, the dark demon = 90**.
- Notes table now 37 rows, including the full fortress chain, the two-phase
  Phalanx chamber (talk/boss/cutscene for both phases), the demon realm boss and
  the true final boss room. Spiny balcony (no save) is inferred as area 39 from
  the map grid match and flagged.
- Boss parts recorded for the sprite/AI work: `$09 $11 $13` mid bosses, `$86 $88
  $8B $8C $8D` Phalanx phases, `$58 $5C $5D $5E $5F` demon realm, `$89 $8A $BD`
  and `$BC` true final boss forms.
- Fixed a real bug in the merge: `--trust-notes` dropped real side doors; it is
  now position-aware, and `restore_transitions.py` restored the 18 transitions
  that had been dropped. Graph: **101/113 (89%) via real doors**, 113/113 with
  gates, 12 gate-dependent areas, 4 chunks without outgoing edges.
- Regression PASS.

### Step 63 — Savestate reality check; OAM palette bug fixed (done)

- Established (with exact-frame captures) that the user's `.sav` states restore
  **WRAM/VRAM but not the CPU**: probes read coherent game data, while every
  screenshot shows the Capcom copyright screen. The saves are data snapshots,
  not resumable gameplay — so they cannot drive or be screenshotted, and boss
  sprites cannot be cut from frames. Recorded in the plan (3l).
- Fixed `bake_object_sprites.py`: it painted the merged OAM index image with
  palette 0 only; it now composes each sprite with its own palette and masks the
  low tile bit for 16x16 sprites. Re-rendering the Somulo scene from OAM shows
  the dragon and the player in plausible colours, but the boss parts are still
  scattered — the part-to-object attribution is the remaining M4 problem.
- Added `merge_probe_placements.py` (M2): merges probe object placements into
  room JSONs, but only where coordinates fit the extracted chunk world (32
  placements today); most probes sit outside it, which is the chunk-coordinate
  issue documented earlier.
- `extract_boss_sprite.py` kept as a documented dead end (needs resumable
  states).

### Step 64 — Chunk-local doors: re-point instead of adding (done)

- Diagnosis: save coordinates are level-space, so a note door usually lies
  outside its chunk's extracted world; adding it there made an unreachable
  trigger (only 3 of 16 note doors fit their world).
- Fix: when a note door does not fit, **re-point the chunk's extracted ROM
  transition** (already chunk-local) to the notes' destination. Nine doors
  re-pointed: 20→22, 22→26, 38→boss, 48→54, 66→boss, 4→6, 8→10, 10→18 (plus
  area 0 earlier).
- Regression now proves five doors in-game with synthetic input only:
  **0→34, 2→4, 8→10, 10→18, 20→22** — all PASS.
- Overworld stage markers (`$94` positions) are drawn on the map; alignment with
  the art still needs the Mode 7 affine, noted in the plan.

### Step 65 — Interiors named (library 92, Black Lotus 96, wise man 94) (done)

- The three up-door saves resolved the dark avenue's interiors: **library = 92,
  black_lotus = 96, wise_man = 94**. Recorded in `docs/INTERIOR_DOORS.md` (not in
  the parsed transition table: level-space coordinates would clamp into the same
  chunk spot and create ambiguous triggers).
- The names feed the UI: the area banner shows **LIBRARY** for area 92 (verified
  in a capture), and the stage list picks them up too.
- Parser fix: roles are matched from the end against a known role set, so
  `wise_man`/`black_lotus` no longer parse as name+role (`wise`+`man`).
- Still needed for walkability: level-space → chunk-space mapping for level II.

### Step 66 — Spiny balcony = area 78; merge never drops doors (done)

- The spiny-balcony save corrected my inference: it is **area 78**, not 39.
  Notes now read western bell tower -> spiny balcony (78) -> eastern bell tower.
- Merge policy finalised: **never delete** extracted transitions; a note/clamped
  door is inserted **first** so it wins when triggers overlap; a room with a
  single extracted door still has its destination re-pointed.
- This restored the branch lost when a 15 px-apart door was treated as an overlap
  (areas 21/23/41/42 are real-door reachable again).
- Graph: **102/113 (90%) via real doors**, 113/113 with gates, 11 gate-dependent
  areas, 4 chunks without outgoing edges. Regression proves six doors; PASS.

### Step 67 — Poseidonia side paths, limestone, area-id limit (done)

- New rooms: **underwater grotto = 50**, **lair of holothurion = 52** (boss drops
  a life up), **limestone cave = 30** (level III).
- Links: aquatica → grotto, grotto → temple (up), grotto → holothurion (right),
  lair → boss, scula cave → limestone (up).
- Found that **areas 113..127 are not real**: `$008D = 118` on the
  `temple_from_grotto` save decodes to garbage tables, so it is the temple (54)
  reached from the grotto. The name tool ignores areas above 112.
- Third and final merge policy: never modify/delete ROM transitions; insert
  note/save doors **first** (they win overlaps) and clamp them into the chunk.
  Branches lost earlier (21/23/41/42) are back.
- Graph: **103/113 (91%) via real doors**, 113/113 with gates, **10 gate-dependent
  areas** (1, 35, 43, 46, 57, 63, 77, 83, 99, 109), 4 chunks without outgoing
  edges. Regression PASS.

### Step 68 — Somulo fight ported; species-capacity bug fixed (done)

- Somulo (species `$33`, area 0) now runs the real pattern: idle → windup → fire
  (aimed low/high at Firebrand) → recover, a **firewall** of three flames where
  the fireball lands, a stagger when hit, and **six head hits** to kill him. The
  gate to the second colosseum room (area 34) already existed.
- His sprite is cut from the user's fight screenshots (colour key against the
  purple colosseum, trimmed to the dragon, anchored at the head); boss draw
  scale is now 1:1.
- **Found a major asset bug:** `DC_SPECIES_MAX` was 16 while `species_anim.json`
  holds 30 sheets, so 14 captured sheets never loaded (silently falling back to
  silhouettes). Raised to 64 — the port now loads all 30.
- Player fireball now originates at the **mouth** (x+10, y-18) instead of the
  feet, with the urn hit tolerance widened so ground urns still break.
- Duplicate boss objects (extractor entry + probe placements) are deduplicated,
  preferring the observed fight position; `DC_BOSS_X/Y` lets a test place a boss
  where a grounded demo can reach it.
- Regression updated (fireball offsets, grounded boss test) and **PASS**.

### Step 69 — Somulo animated from the sprite sheet (done)

- `docs/sprites/` (Spriters Resource sheets, ripped by Lord Zymeth) has a
  labelled Somulo sheet: six head poses, body, legs, **fireball** and **firewall**
  frames.
- The port composes full poses from body + head (matching the original's separate
  `$33` head and `$35/$36/$37` parts), mirrors them to face right, and writes
  `enemy_33_0..4.png` = idle / attack high / attack low / hurt / defeated. The
  renderer picks the frame from the boss state (and `substate` for high/low)
  instead of cycling.
- The sheet's fireball (`boss_fireball_0..2.png`) and firewall
  (`boss_flame_0..6.png`) frames now draw species `$34`; flames are bottom-anchored
  and animate as they grow.
- The ribcage "hole" is the room's black backdrop through transparency, not a
  baked gap.
- Regression PASS.

### Step 70 — Somulo tuned from the animated reference folder (done)

- `docs/sprites/animated/` adds motion material. The Somulo fight capture
  (`dragons-crest-somulo-animation.gif`, 22 frames @50 ms) shows two fireballs in
  1.1 s → an attack every ~33 game frames; the AI loop was retuned from ~117
  frames to that cadence (idle 22, windup, fire, recover 12) and the boss draw
  scale raised to 1.3x (the reference dragon is ~195 px tall).
- `somulo-walking.webp`, `Arma_laugh.webp`, `fireboss_animated.webp` are hi-res
  fan animations, not ripped sprites: reference only, they would clash with the
  SNES style.
- The bad-ending GIF and `map_mode7_animated.mp4` are kept as M8/presentation
  reference; the gameplay captures are timing references.
- Regression PASS.

### Step 71 — A1: Firebrand's six form sheets baked and wired (done)

- `tools/dc_extract/bake_player_forms.py` cuts the six Firebrand sheets (Normal,
  Ground, Aerial, Tidal, Legendary, Ultimate) into `fb_<form>_<clip>_<i>.png`,
  keying the sheet's dominant colour out to transparency. Clip bands were
  measured on the normal sheet with a coordinate grid and reused for the sheets
  that share the layout (the ground sheet is compressed and has its own bands).
- `player_forms.json` holds one animation per form; `Anim_LoadForms`/`ParseClips`
  load them (the single-sheet loader now shares the parser), and
  `Assets_PlayerAnimForForm` selects the sheet from `crest_form` in both the
  animation update and the draw path.
- Known rough edges: the band split merges some touching frames (idle 3–5 steps
  instead of 5–6) and a few clips keep a stray sliver; a per-sheet band table
  would fix it.
- Regression PASS; the player now renders the ripped sprites in game.

### Step 72 — A3 first pass: Arma (species `$A5`) (done)

- The saves place `$A5` in areas 3, 23, 36 and 67, and his sheet is labelled.
  Baked four poses (idle / breath / dive / hurt) as `enemy_a5_0..3.png` and
  selected them by state.
- Behaviour: slow hover bob, then either a two-shot breath aimed at Firebrand or
  a divebomb along his line, a stagger when hit and a climb back to his post.
  Breath uses a plain shot (only Somulo's fireball spawns a firewall).
- Remaining: authentic cadence, the second fight's green palette and hurricane,
  Phalanx's two phases.
- Regression PASS.

### Step 73 — A2 status: blocked on species identity

- `Enemies 1.gif` / `Enemies 2.gif` carry no species labels, and the probe OAM is
  fragmented, so the remaining silhouettes cannot be matched by name. The planned
  route is to compose each species from OAM + VRAM + palette and match the result
  against the sheets automatically.

### Step 74 — Level VI region correction (ice crevasse vs Grewon valley) (done)

- The earlier `lvl_VI_mountains-valley-of-the-grewon*` probes were a **different
  region**: the corrected saves show the valley is **area 60**, while area 58 is
  the **ice crevasse**. The two stale probe folders (which would have kept
  mis-naming 58) are parked under `stale_*` so the name tool ignores them.
- Names fixed: 58 = `mountains-ice-crevasse`, 60 =
  `mountains-valley-of-the-grewon` (roles: entrance, spell, before_door_boss,
  boss, boss_dead).
- Door added from the notes: ice crevasse → valley (right). The wrong
  "valley → ice spire" row is gone.
- The boss save shows **Grewon (species `$13`)** in area 60; the boss_dead save
  leaves species `$48` at the arena, i.e. the **Demon Fire** (last Fire Crest
  piece) drop.
- Self-loops are now never merged: the "right door → boss" note inside area 60
  produced a `60→60` transition that would have reloaded the room. Regression
  proves the new door (`58→60`).
- Overworld state captured in `assets/generated/map_states.json`
  (`normal_ending_available`: 17 markers + cursor) for the stage-unlock model.

### Step 75 — A1 reverted: captured animation is the default again (done)

- The user reported the Firebrand animation was much worse after the form-sheet
  switch. Verified: the band split gave irregular clips (normal walk 3 frames,
  attack 2, ground clips including captions and half sprites), so the animation
  jittered.
- `Assets_PlayerAnimForForm` now returns the captured `player_anim` unless
  `DC_PLAYER_FORMS` is set; the ripped sheets stay in the tree for a later, clean
  pass (the sprites are correct 1:1 — only the cutting is wrong).
- Added a sliver filter and stale-file cleanup to the baker so future passes
  start from clean output.
- Regression PASS.

### Step 76 — Recomp recording support for fights and animations (done)

- The recomp's debug server now records and replays input **frame-exactly**
  (`record_input_start/stop`, `replay_input/stop`): the pad is sampled where the
  runner reads it, so file frame N is the input frame N ran with.
- Frame capture: `record_frames <dir> <count> [every_n]`, and a **rolling buffer**
  (`record_ring_start`, `record_last`) that keeps the last N frames in RAM. With
  `SNESREC_RING_DIR` set, quitting the window writes the last ~5 s plus
  `input_log.jsonl` — a boss fight is saved without arming anything.
- `record_status` reports every recorder. `tools/bmp_sequence.py` converts a
  frame folder to GIF/MP4; `docs/RECORDING.md` documents the workflow.
- Known limit: strict bit-exact replay of two full sessions is not yet proven by
  an automated test; the file round-trip and per-frame application are verified.

### Step 77 — Somulo frames rebuilt from a recorded fight (done)

The first real take (`captures/rec_somulo`, 1485 frames ≈ 25 s + input log) was
analysed:

- **Six hit flashes** at frames 530, 684, 834, 985, 1138, 1299 — exactly the six
  hits you described, and each flash lasts **~33 frames**. The port now keeps
  Somulo white for 32 frames and makes him invulnerable during it, so a fight
  cannot be machine-gunned past the rhythm.
- **Species `$33` frames are now cut from the game**, not from the sprite sheet:
  idle, attack, hurt (white flash) and a lowered-head pose at 164×159, keyed
  against the colosseum and anchored on the head. The composed body+head guess is
  gone.
- The golden floor is keyed out by clearing rows that are warm across most of the
  crop, so the frames have no ground strip.
- Attack cadence is still measured badly: the mouth-fire and fireball detectors
  pick up the wall torch and the hurt flash. A cleaner approach is to replay the
  take with RAM reads (HP of both fighters) rather than colour heuristics.

Note: the in-game screenshot for this step could not be taken — GLFW failed to
create a context while another game window was open ("Failed to create
interface"), so the frames are verified as extracted assets only.

### Step 78 — Boss identities from the new saves; Grewon and Phalanx fight (done)

The latest saves settled which species is which:

| save | area | species | reading |
|---|---|---|---|
| hipogriff_fight | 74 | **`$09`** | the hippogriff mid-boss (third encounter); `$A5` is therefore *not* Arma |
| Grewon_fight | 82 | **`$13`** | Grewon, second encounter (stronger version) |
| Phalanx_fight_first | 84 | **`$86`** + `$88` | first form (the flying demon) |
| Phalanx_fight_second | 84 | **`$86`** + many **`$8D`** | second form: head plus a segmented serpent |
| normal_ending | 84 | `$86` + `$8B` | after the second form falls |
| spiny-balcony_fang | 78 | **`$50`** | the **fang talisman** pickup |

Behaviour read from the takes: **Grewon** is a ground beast that paces, crouches
and charges; **Hippogriff** flies and throws feather volleys; **Phalanx** first
form hovers and lobs orbs, second form rises from the pit as a segmented serpent.

Implemented now:

- `$13` Grewon: pace → crouch → charge (bounces at the arena bounds) → recover,
  with the hurt window; `$09` Hippogriff: hover/dive/feather volley; `$86`
  Phalanx: hover and orb, same object as the second form's head.
- Boss objects for areas 74/82/84 are added from the probes, clamped into their
  chunks like the doors, and deduplicated.
- Frame selection for these species uses their sheets (idle row, attack row, hurt).

Verified: Grewon and Phalanx render and act in their arenas (screenshots). Not
verified: the hippogriff's sprite — its sheet bake produced **fragments** (59×58
pieces) instead of whole poses, so it is in the arena but effectively invisible;
it needs a proper per-sheet crop. The `$8D` segment object was removed again
until the second form is modelled.

### Step 79 — Grewon's invincible colour, Hippogriff frames, talismans, Phalanx phase 2 (done)

- **Grewon** now follows the fight's rule: a hit turns him **green for 60 frames**
  and he is **invincible** until he changes back (the recording showed 44–77
  frame green windows). Hits during the green do nothing, so the player must wait
  — exactly as described.
- **Hippogriff frames fixed**: the sheet's first pose row was measured on a
  coordinate grid and five poses (idle, flap, glide, swoop, feather) are cut with
  the background keyed, replacing the fragments. He renders in area 74.
- **Talismans are now objects**: a `talisman` level object type spawns a floating
  pickup, grants `talisman_mask`, sets it active and shows a short HUD line. The
  **fang** (`$50`) is placed in area 78 at (224,170), clamped from the save's
  level-space position.
- **Phalanx has two forms**: killing `$86` once spawns the second form from the
  pit and keeps the exit shut; killing that one opens the way to the normal
  ending. The second form now spawns as `$8D` with the `Ultimate Phalanx.gif`
  body art, still using the `$86` head AI. Only the head object is simulated;
  the serpent's separate `$8D` segments remain cosmetic/background-only.

Regression PASS. Verified by screenshot: Hippogriff, Grewon (normal and the
green state pending a hit), fang talisman in area 78, Phalanx in area 84.

### Step 80 — MVP 1: the Somulo fight is playable end to end (done)

- **The critical bug:** the boss branch ends with `continue`, so the shared
  `hit_flash` decrement never ran for bosses. After the first hit a boss stayed
  flashing — and, with the new invulnerability, permanently untouchable. The
  boss branch now ticks its own flash. Without this the six-hit rhythm could
  never work.
- The head now **rises to breathe and sinks afterwards**, so a grounded
  Firebrand can reach it; the hit box is the head (40x46), not the body.
- In campaign mode the fight **no longer ends the area**: the player keeps
  control and the gate leads to area 34 (`DC_MVP_KEEP_CONTROL` opts in; other
  runs keep the immediate clear the campaign tests rely on).
- `demo 14` plays the fight: walk to the dragon, six shots 40 frames apart,
  then the gate. Regression asserts HP `6→5→4→3→2→1` and that area 34 is
  reached.
- `DC_BOSS_NO_ATTACK` is a test hook so the loop is checkable without dodging.
- The object trace now carries `hp,flash,species,flags`, which made the fight
  and the Arma palette variant assertable at all.
- Spec: `docs/MVP_SOMULO.md` (definition of done + known gaps: intro roar,
  area 34 staging, mouth flame).

### Step 81 — HUD matches the original: dots, and hidden for the first fight (done)

- Measured the real HUD from the user's captures: **life is a row of 10 dots**
  (filled per HP), **six potion dots** under it, plus the crest slot panel. There
  is **no HP bar and no boss bar** — the port had invented both.
- `DrawHud` now draws those two dot rows and the crest slots; the baked bar, the
  black band behind it and the boss health bar are gone.
- The whole HUD is **hidden in area 0**, matching the cinematic first Somulo
  fight: the player only sees their state in the next room.
- Verified by screenshot: area 0 shows no HUD at all; area 34 shows the dot rows
  and crest panel.

### Step 82 — Full suite green before the MVP capture (done)

Ran every check against the current build:

| check | result |
|---|---|
| `check_areas.py` | 113 areas, ok=113 |
| `check_campaign.py` | no-boss=56, ok=10 (every boss entry clears) |
| `check_playthrough.py` | 6/6 steps |
| `check_navigation.py` | 103/113 via doors (91%), 113/113 with gates, 10 gate-dependent, 4 chunks without outgoing |
| `run_regression.py` | PASS (demos, six-door tests, MVP Somulo, boss clears, endings, save/password) |

The build is in the state the first playable MVP is captured from: the Somulo
fight with real frames, the six-hit/invulnerability rhythm, the cinematic
HUD-less first room, dots elsewhere, and the gate into area 34.

### Step 83 — MVP staging matched to the full capture; screen kinds documented (done)

Watched the user's `mvp_somulo` take (5 548 frames, boot → Somulo's death):

- the dragon **walks after Firebrand** down the colosseum corridor, and the fight
  happens *while moving* — the port's boss was static at a far position;
- he **collapses and lies on the floor** before the room ends, and only then the
  game moves on;
- the HUD returns in area 34 exactly as the dot grid we implemented.

Changes:

- Somulo now **follows** the player when the distance exceeds 150 px, and starts
  at the save's opening position (288, 88) instead of the far one.
- He gets a **death state**: 90 frames lying in the defeated pose, ignoring
  further hits, before the room ends.
- The dying boss no longer takes damage (hp used to fall below zero).
- `demo 14` re-staged for the chase: it closes in, lands six shots
  (hp `6→5→4→3→2→1→0`), and reaches area 34.

Screen kinds: `initial_cutscene` is `$008D = 168` and `menu_cutscene` is 160 —
menus and cinematics, **not** rooms. Documented in `docs/SCREEN_KINDS.md`
together with the intro's text pages (which already exist in
`text_strings.json`, so staging the intro is presentation work).

### Step 84 — Hippogriff's statue and the bosses' damage reddening (done)

From the user's cemetery capture (7 211 frames):

- **The mid-boss turns back into a statue mid-fight** and only a **headbutt**
  wakes him; it is random and a fast kill can skip it entirely.
  Implemented as a new `state 6`: he freezes on the statue frame, shots spark off
  (no damage), a headbutt within 30 px wakes him, and after ~4 s he wakes on his
  own. `DC_BOSS_STATUE` forces it for testing.
- **Bosses redden as they lose health** — every boss except Somulo. The sprite
  tint now blends toward red by `1 - hp/max_hp`; Grewon's green invincible colour
  still wins while it is active. `DC_BOSS_HURT` spawns a boss at half health to
  show it.
- Found and fixed `DC_SPECIES_FRAMES = 4`: sheets with more than four frames
  (Hippogriff now has six, including the statue) silently lost the extra ones.
  Raised to 8.
- Verified by screenshot: the stone statue renders in area 74, and Grewon comes
  out pink/red at half health.

The cemetery capture also shows exactly what MVP 2 still misses: the real
backdrop (the port is black) and the enemy art. `docs/sprites/…Backgrounds -
Cemetery.png` holds the tile set plus a composed parallax strip, so the backdrop
is buildable from it; that is the next task.

### Step 85 — Sprite/animation plan; Somulo no longer debris (done)

The user reported the sprint animation as "really strange, buggy" and the
background as broken. Measured it:

- the Somulo frames cut from the recorded fight have **113 alpha components**
  each (largest ~2.2k px): the video colour key removed the dragon's dark
  shading and kept the golden floor as speckles;
- the sheet-composed frames carry the sheet's **opaque-black ribcage interior**;
- the colosseum background has **black rectangles** where the BG tilemap
  references tiles whose CHR was never captured.

Immediate mitigation: Somulo is back on **sheet-composed frames**, black patches
keyed out, scale set to **0.95** (was 1.3, then 1.15 — both guesses). No more
debris, though the sprite is still on the large side and the background holes
remain.

The method is written down in `docs/PLAN_SPRITES_ANIMATION.md`: Pipeline A (exact
OAM/VRAM compositor with recomposition diff), Pipeline B (measured sheet crops
with structural filters), background rebuilds from VRAM, an animation model with
pose tags, and **acceptance gates** in the regression (no debris components, no
opaque black, anchor consistency, screenshot diff).

### Step 86 — Applying the sprite plan: OAM compositor (in progress)

Started Pipeline A (`tools/dc_extract/oam_compose.py`): reads a probe's
`vram.bin` / `cgram.bin` / `oam.bin` / `ppu.json`, decodes OAM entries (palette
bits, flips, tile bank bit, OBSEL tile base, size pair, 4bpp plane layout),
composites them in screen space, and crops the largest cluster as the boss.

**Not passing the gate yet.** The composite still breaks into 8×8 chunks, so the
sprites are *not* wired into the port. The probe dumps themselves are the first
suspect: the recomposition diff against the emulator's own frame has not been
run, and the word order inside `vram.bin` is untested (the tool now takes a
`--big-endian-words` flag rather than guessing).

Next step, per the plan: render the probe's buffers with the recomp's
`render_inject` and compare with the recorded frame of the same state. That
single comparison tells us whether the dump layout or the decoder is wrong — the
question the plan says to answer before touching the port.

Somulo therefore stays on the cleaned sheet frames (scale 0.95) for now.

### Step 87 — Replayable takes and the exact-state dump pipeline (done, blocked on framing)

Working through the sprite plan's validation step turned up four structural
facts and two fixes:

**Fixes**
- Takes now log the **guest frame** next to the take frame
  (`{"frame":0,"gframe":192,"inputs":0}`). Verified on a fresh take.
- `SNESREC_AUTORECORD=1` starts a take on the first frames of boot, so the log can
  be replayed from reset. Verified: 382 samples starting at guest frame 1.

**Tooling**
- `tools/…/replay_dump.py`: aligns a take by its `gframe` offset, replays it,
  freezes at a guest frame, and dumps VRAM / CGRAM / OAM / WRAM plus a screenshot
  from that same frame. Verified end to end (replay accepted, freeze, dump).

**What blocked the sprite gate**
- A take that starts **mid-session cannot be replayed**: its log has no boot
  inputs, so replay lands wherever the fresh boot is (verified: area 160, black
  frame). Takes must start at boot — hence the autorocord flag.
- A **savestate cannot be rendered either**: `--resume-state` restores memory but
  the CPU reboots, resetting the PPU (`bgmode` reads 0 with `--paused`, the
  injected render comes out black).
- `dump_vram` reads the live `g_ppu->vram`; it returns a populated buffer
  (40 794 nonzero bytes) on a real frame and a near-empty one on a menu, which is
  correct behaviour, not a bug.

**Next**: record a boot-start take that plays into the Somulo fight (the user can
do it with this build, or a scripted walk), replay to a fight frame, dump, then
run `oam_compose.py` and diff against that frame's screenshot. That is the gate
from the plan. Somulo stays on the cleaned sheet frames until it passes.

### Step 88 — Pipeline A works: OAM sprites decode correctly (done)

The take the user recorded (`captures/rec_20261024_234748`, 6 286 frames from
boot) replays exactly and reproduces the whole run: title at ~620, **area 0 with
Somulo (`$33` + `$35/$36/$37`) from ~1 000 to ~4 400**, then **area 34**.

Two real bugs in `oam_compose.py`, both found against the *verified* decoder in
`extract.py` / `bake_object_sprites.py`:

1. **OBSEL's sprite pattern base is `(obsel & 7) << 13` in 16-bit words**, not
   `<< 12`. The port had been reading background tiles as sprite tiles.
2. **Sprite palettes live in the second CGRAM half**: `0x80 + palette * 16 + idx`.
   Reading from 0 gave the wrong colours.

With both fixed, composing the dump of frame 1200 yields **Firebrand pixel-perfect
and Somulo's head/neck/body parts correctly shaped and coloured** — the first
time the compositor has produced recognisable sprites.

Remaining gap for the formal gate: the screenshot and the dumps are not perfectly
atomic (the frozen frame advances past the freeze point, so sprite positions and
the presented frame can differ by a few frames of motion), and `render_inject`
cannot supply the ground truth on its own because the live session's PPU
registers are reset (black render). The fix is to inject the registers too, or to
dump the presented frame together with OAM in the same pass.

### Step 89 — Somulo at native size, cut from a clean frame (done)

The user's second take (`rec_20261024_235733`, 8 258 frames) replays exactly and
contains a **death and restart**: the fight runs to ~5 180, the screen fades to
black for ~70 frames, the room reloads at the spawn and the fight starts again
(there is **no game-over screen in this area**; elsewhere the game shows a retry
menu, which is out of scope for now).

Frame 8 200 of that take has Somulo fully on screen at native resolution — the
first clean, complete reference of him. Cutting him out by flood-filling the cold
arena colours from the border (his body is warm bronze, the arena is cold purple,
and a flood fill keeps his dark interior that a colour key would eat) yields a
**158 x 174 sprite with clean alpha and no debris**.

Installed as species `0x33` at **scale 1.0** (native art, no guessing) and the
head anchor measured on the art. In game he now looks like the real Somulo: head,
teeth, open jaw with fire, ribcage body.

Two things this exposed:

- the port's **colosseum floor is drawn too high** (his feet land below it), which
  is the same background-hole problem from the sprite plan;
- the compositor's OAM grouping is still needed for multi-part poses (walk, bite),
  but a full-body cut like this is now the preferred source for `0x33`.

### Step 90 — Immortality in a take: capturing poses normal play forbids (done)

Somulo walking past Firebrand cannot happen in play (contact kills), so the walk
pose had no clean source. The debug server has `write_ram`, and our own
disassembly notes put **current HP at `$0062`** (max at `$1E50`), so
`tools/immortal_walk.py` replays a take while rewriting that byte every frame:
the player survives the contact and the dragon walks by.

Result: 17 frames of the walk-past, including him looming over an immortal
Firebrand and continuing to the right against plain wall — the pose set the
sprite work needed. `docs/…/immortal_sheet` is the contact sheet.

Two findings from those frames:

- the walking pose has the **head raised** while moving and the jaws closed (the
  head-down jaws-open frame is the *approach*, before the roar);
- **Firebrand renders white/grey** while immortal under Somulo, which is his
  hurt/dying sprite — worth checking against the player sheet before the death
  state is implemented.

The cut (`enemy_33_walk.png`) is ~95 % clean: the gate bars behind his neck are
painted in a purple only slightly bluer than the bronze (`b 57` vs `r 49`), so a
naive cold key keeps them; 170 such pixels are now removed, but faint streaks
remain, so the walk frame is **not** wired into `species_anim.json` yet. The
blocker is still the compositor's dropped 16×16 body parts.

### Step 91 — The colosseum's black rectangles are fixed (done)

Diagnosed the holes by rendering each BG layer alone (`DC_LAYER_MASK=1|2`): they
were in **BG1**, the level geometry whose tiles the ROM set does not contain
because the area streams them into VRAM.

`tools/dc_extract/rebake_bg_atlas.py` rebuilds a layer's **CHR atlas from a VRAM
dump**, keeping the room's tilemap: the tiles now come from the same memory the
game uses, so every referenced tile exists. Running it for area 0 with the fight
dump (`rec_20261024_234748_dump_1200`, BG1 CHR base from `$210B` low nibble)
removed the rectangles completely - the wall, arches, pillars and torches are
whole.

`tools/dc_extract/rebake_bg2.py` does the same for a backdrop layer *including*
its tilemap, for areas where BG2's tilemap is streamed too.

Still wrong, and separate: the **vertical placement**. Our floor sits at screen
y~150 where the game has it at ~205, so Somulo's body is cut off. Shifting
`scroll_y` moves the layer but leaves a band at the top, which means the level's
scroll is not a plain constant - the real layer almost certainly uses per-band
HDMA. That is the next thing to solve, with the floor position as the check.

### Step 92 — Background vertical placement: what did NOT work (recorded)

Tried three ways to move the colosseum's floor from our screen y ~150 to the
game's ~205, so Somulo would stand on it:

1. **`scroll_y` shift** (‑23): the floor lands correctly but a black band opens at
   the top - the layer's content simply ends there. The game has no band, so its
   scroll is not one constant; per-band HDMA (`BgLayer.hdma_bands`, still empty)
   is the likely mechanism.
2. **Padding the tilemap upward** (7 rows, repeated or zero-filled): the floor
   lands at ~200 but the padded rows are visible as a gate-bar "ceiling" - the
   room's top row really is gate, and the game never shows it.
3. **Reading BG1's tilemap straight from VRAM** (`rebake_bg.py`, SC `$2107` =
   0x41, CHR base 0, palettes 0/3): produced a different layout with a large
   black block, i.e. our renderer does not reproduce a captured tilemap the way
   the PPU does. Not usable as-is.

All three were reverted; the committed state (ROM tilemap + VRAM-rebaked atlas)
is still the best one: complete background, floor at the wrong height.

**Next, in order**: (a) recompose the game's own BG1/BG2 from the dump in Python
at the dump's scroll and compare to the game frame - that settles whether our
data or our renderer is wrong, the same recomposition gate used for sprites;
(b) only then adjust the port's layer maths, with the floor at y ~205 as the
pass condition.

### Step 93 — Floor height solved: the layer scroll was doubling the camera (done)

Measured instead of guessed: the arena floor sits at screen row **192** in the game
frame and at **161** in the port, i.e. 31 px too high, which is what cut Somulo off
at the bottom.

Instrumented `DrawLayer` (`DC_DEBUG_BG=1`) and printed the origin:

```
BG1 origin_y=0.0 cam_y=32.0 level_cam_y=32.0 scroll_y=0
```

With that the maths is simple: `screen_y = row*8 - origin_y`, and
`origin_y = camera->y + scroll_y - level.camera_y`. The extractor wrote
**`scroll_y = cam_y`**, so the camera offset was applied twice; the layer is meant
to start at its world origin, where the answer is **0**.

Fixes:

- `tools/dc_extract/extract.py`: `scroll_y` is 0 for BG1 (and only the
  vscroll delta for a captured BG2) instead of `cam_y`;
- area 0's generated room keeps `scroll_y` 0/16 with a little top padding so the
  256-tall world covers the 224-tall view: floor now lands on **row 193**
  (game 192) and **no black band** remains;
- Somulo's anchors moved up 10 px so his feet rest on that floor.

Verified side by side with the game frame: the wall, arches, pillar, lion relief
and torches are complete, and he stands on the floor instead of sinking through
it. Regression PASS.

### Step 94 — The camera, not the background, was lifting everything (done)

The user's video showed Firebrand standing **well above the floor** while the
newly fixed background was correct. That split - objects high, background right -
pointed at the room's starting camera: the extractor computed
`cam_y = spawn.y - 140` (a guess) which gave **32**, while the runtime deadzone
never moves the camera before the player passes y 176, so the real start is **0**.

Fixes, all in the extractor so regeneration keeps them:

- `cam_y = clamp(spawn.y - 176, 0, world_h - 224)` (same deadzone the camera uses);
- per-room background padding/scroll for rooms whose ROM tilemap sits a couple of
  rows above the game's layout (`AREA_PAD_ROWS = {0: 3}`, `AREA_SCROLL_Y = {0: -2}`).

Verified: Firebrand's feet now rest on the floor line (row ~203), the wall is
complete, and Somulo stands on the arena.

Also from the same report:

- the walk frames were cut with `b > r` as the background key, which ate the
  dragon's **dark grey shading** and left him looking pale and speckled; the key
  is now `b > r + 20`, which keeps the bronze and still removes the wall;
- the frames carried ~10 rows of baked ground strip, now cropped, so his feet -
  not the floor texture - are the bottom of the sprite.

### Step 95 — Taking the review's Fase 0/1: state clips instead of `species ==`

Read `docs/PLAN_SPRITES_ANIMATION_REVIEW.md` and acted on its two cheapest,
highest-leverage items.

**P5 is settled**: its claim that `extract.py::compose_oam` is the reference is
right, and comparing the two shows our `oam_compose.py` uses the same quadrant
maths (`((tile >> 4) + row) << 4 | ((tile & 0x0F) + col)`) and the same
`0x80 + palette*16` CGRAM row. The leftover "missing parts" are not a decode bug:
part of a boss this large is drawn by the BG layers (the 32-sprite-per-line
limit), which is why cutting from the frame is the correct source.

**Fase 0/1 implemented (the data contract)**:

- `SpeciesSheet` gained `has_states` + `StateClip states[16]` (up to 8 frames
  each), loaded from a new `"states"` object in `species_anim.json` keyed by the
  object's own state byte;
- `DrawObjects` now picks the frame from that table (animated with the object's
  timer) and the `species == 0x33` block is **gone** - Somulo is data-driven:
  `{"7": [0,1,2], "8": [0,1,2], "0": [3], ...}` = walk cycle while walking,
  standing otherwise;
- verified in game and by the regression (PASS).

Still open from the review, in its own priority order: **P2 facing/flip**
(object sprites never mirror), P1's remaining species blocks, P3 long captures,
P4 integer anchors, and the `recompose_diff.py` gate.

### Step 96 — Review Fase 1 complete: facing, integer anchors, no species blocks

Finished the review's Fase 1 and P4.

- **P2 (facing)**: `SpeciesFrame` gained a pre-baked `flipped` texture (baked with
  `ImageFlipHorizontal` at load, because negative source rects are unreliable in
  raylib - the project's own trap #6). `DrawObjects` draws it when
  `o->facing < 0`, moving the anchor to the mirrored side so the sprite does not
  jump. Object sprites had **never** flipped before.
- **P4 (anchors)**: `anchor_x/anchor_y` are now `int` and rounded at load, so the
  fractional values stop truncating on draw.
- **P1 (finished)**: pose selection is entirely data. `species_anim.json` now
  carries, per species, `states` (object state -> frame list), `hurt` (pose while
  `hit_flash > 0`) and `default`. `render.c` has **no `o->species ==` pose
  blocks** left - the only remaining ones are the `0x34` projectile check and
  Grewon's green invincibility tint, which are not pose selection.

Mapping migrated: `0xA5` {0:0,1:1,2:2,3:2,hurt:3}, `0x09` {0:[0,1,2] flap at 8
frames, 1:4 volley, 2/3:3 swoop, 6:5 statue}, `0x13` {2:3, hurt:5},
`0x86` {1:3, hurt:5}, `0x33` {7/8:[0,1,2] walk, others:3 standing}.

Verified: regression PASS, and the Hippogriff still turns to stone
(`DC_BOSS_STATUE`) through the data table.

### Step 97 — Backdrop layer: the cemetery has its sky and trees (done)

Area 2's BG2 tilemap is empty in the ROM set, which is why the cemetery rendered
as a black void. Added a **wide backdrop image** layer:

- `Assets` loads `bg_backdrop_area<N>.png` when an area's BG loads (absent file =
  no change, so other rooms are untouched);
- `Render_Game` draws it behind the tile layers, tiled horizontally at **half
  parallax**, pinned to the top of the view.

The image itself comes from the game: the top 256x150 band of a cemetery capture
frame, which contains sky and distant trees and no sprites.

Also rebaked area 2's BG1 atlases from the probe dump (`rebake_bg_atlas.py`), so
the graves and bushes draw with the right tiles instead of holes.

Result: sky, purple trees, gravestones, bushes and HUD - the cemetery reads as
itself. Still missing there: the mid-ground black gaps (BG2 detail we never
captured) and a longer backdrop strip than one screen.

Regression PASS (after removing a stray `room_area2_pre.json` backup that
`check_areas.py` tried to parse as an area number).

### Step 98 — Enemy sprites come from the labelled sheets (done)

The user asked whether the room's enemies could be extracted. They can - and the
best source is not the frames at all: `docs/sprites/…Enemies 1.gif` is **labelled
by enemy name** (Phantom, Axe Demon, Wall Spider, Fountain of Flames, Aquatic
Demon, Ghost, Zombie Hand, Zombie Head, Armor Zombie, Scavenger Demon), so a row
can be cut by its band and split on empty columns.

`tools/sheet_row.py` does exactly that: crop a labelled band, split into frames on
background columns, trim each frame and key the sheet's flat background to alpha.

First results, for the cemetery (area 2):

- **`0x2c` had no sprite at all** (10 of them in the room - invisible enemies!).
  It is the *skeleton walker*, now three walking poses from the Scavenger Demon
  row. They are visible in the room for the first time.
- **`0x67`** (Graveyard Ghoul) held a pink blob from the old broken capture
  pipeline; it now uses three Ghost poses from the same sheet.

Also learned: the JSON's species keys are **lowercase** (`"2c"`, not `"2C"`) -
a new entry silently does nothing if the case is wrong.

Still to do on this axis: the remaining one-frame species (0x26, 0x07, 0x2d,
0x57 and others) and a proper species-to-sheet-name table, which the labelled
sheets now make possible.

### Step 101 — Shots in front, and the arena restarts on death (done)

Two MVP 2 defects from the user's videos.

**Shots were drawn behind the objects.** The order was player -> projectiles ->
objects, so any boss between the camera and the shot hid it - the player appeared
to fire nothing at Somulo. `DrawProjectiles` now runs last and the fireballs read
correctly in front of him.

**Death in the arena shows GAME OVER; the original restarts the room.** The
recording of Somulo shows fade to black, room reload, entrance again. Added
`Game.restart_timer`: dying in area 0 fades to black (a new `Render_SetFade`
overlay), reloads the area with full HP and resets `boss_intro`/shake so the
entrance replays. Other areas keep the game-over screen (the retry menu is still
out of scope, as the user asked). `DC_DEATH_GAMEOVER=1` restores the old
behaviour for tests.

Verified: hp reaches 0 at frame ~550, the screen fades out, the room reloads and
`MURKLAND COLOSSEUM` plays again with the player back at spawn; the mode never
leaves GAME_PLAYING. Regression PASS.

### Step 102 — Sprite pipeline hardening (2026-10-31)

Applied the highest-impact items from the sprite review:

- **Rendering:** `DrawObjects` now actually draws the mirrored texture (the old
  code computed `tex` and then drew `sf->texture`); player and projectile
  anchors are mirrored with `width - anchor_x`. `facing` is initialised for
  enemies/bosses and updated when patrols/charges turn.
- **Object art:** urns and crest items use their captured species sheet when
  available, with the generic item/heart only as fallback.
- **Animation model:** species poses carry per-frame durations; `flying` and
  `hurt` are real form clips, missing form clips fall back to attack/hover/idle
  instead of silently freezing on idle; jump/fall forms no longer loop. The
  form baker now takes connected pose components from measured per-sheet clip
  regions instead of splitting raw bands on empty columns, so captions and
  slivers are gone; the form sheets are the default (`DC_PLAYER_FORMS=0`
  restores the captured base sheet). The form sheets also provide `death`
  clips now (normal 7 poses, ground 6, aerial 6, tidal 6, legendary 7,
  ultimate 7).
- **Data gate:** new `tools/audit_sprites.py` rejects missing textures, anchors
  outside the image, duplicate images assigned to different species, and
  fragmented tilemap-like captures. It runs in `run_regression.py`.
  `tools/check_bosses.py` adds the content contract the structural audit cannot
  see: expected species/flags/position per boss room, base/variant texture
  presence, and a runtime object-trace smoke test for all eleven boss rooms
  plus the `$8D` Phalanx second form. This would catch the old `$96`
  placeholders, off-screen Crawler/Arma objects, and missing Arma palette
  entries.
  `species_anim.json` was quarantined from 34 to 21 species; the removed entries
  were duplicates/shared clusters (`28/29/2a`, `41/87`) and fragmented captures.
  A clean `$23` ghost was then recovered from reference frame 8000 (22 species).
- **Boss sheet mappings from the named saves:** the live object pools give the
  ids the ROM room lists missed. Holothurion is **`$6F`** (area 52), not the
  NPC `$96`; Scula's fight has `$7B/$7C` (plus `$7F` effects); Phalanx is
  `$86` (plus `$88` parts) and its second form is `$8D`; the demon-realm boss
  uses `$58/$5C/$5D/$5E/$5F`; the final second form has `$BC` (and `$8A`).
  `bake_holothurion.py` now writes the three full Holothurion examples under
  `$6F`, `bake_scula.py` supplies `$7B/$7C` from `Scula.gif`,
  `bake_ovnunu.py` supplies the temple boss `$16` from `Ovnunu.gif`,
  `bake_boss_rows.py` supplies Crawler `$82`, Belth `$68`, the `$8D` second
  form from `Ultimate Phalanx.gif`, the demon-realm `$58` from `Flame Lord.gif`,
  and the final second form `$BC` from `Dark Demon.gif`; `bake_npc96.py` keeps
  the area-8 town NPC on the NPC sheet. `fix_room_boss_species.py` corrected
  area 52's boss object from `$96` to `$6F` and area 54's from `$96` to `$16`;
  `add_room_boss.py` added the two Scula objects to area 26, Crawler to area
  68 (lowered from the save's `y=72` to `y=160` so it is on-screen), and the
  Flame Lord/Dark Demon objects to areas 86/90.
- **Somulo:** `clean_somulo.py` clears the two measured gate-bar columns from
  the native reference and re-anchors the 158x174 pose at the bottom centre
  (`79,174` instead of `120,70`), so the old states 7/8 now show the whole
  dragon standing on the colosseum floor rather than only the head above it.
- **Arma:** `bake_arma.py` now uses individual measured pose boxes, producing
  eight clean frames per encounter instead of row crops containing captions
  and multiple dragons. It also bakes the green second-fight palette
  (`flags=2`) and `Ultimate Arma` (`flags=4`) as boss variants; the renderer
  selects them from the object flags, so areas 23 and 36/67 no longer use the
  base palette. The area-3/23 boss objects had `y=0` while their cameras were
  at 1040/1792; they are now at 1180/1932, inside the visible chunk, with the
  flags preserved.
- **Tooling:** `OAM` composition now reuses the verified `extract.py` metaspriter
  (whole-sprite flips); `extract_species.py` merges instead of overwriting
  hand-baked entries (with `--prune` to force a replacement); species captures
  now sample 60 frames and use the pre-injection player anchor when available.
  `tools/oracle/replay_capture.py` replays a recording and dumps exact reference
  frames; `tools/sheet_row.py` bakes a measured labelled sheet row.
  `bg_recompose.py` had its BGnSC/CHR base conversions corrected (the old
  `/2` conversion read half a tilemap early); frame 7002 now recomposes the
  cemetery trees and graves instead of noise, which is the base for the
  remaining full-room background pass. A clean `$23` ghost sprite was also
  recovered from that reference frame.

Still open: Somulo's multi-part walk needs part-to-object attribution or a
clean full-frame cut, and the cemetery BG1/backdrop still needs its own
recomposition pass. The 2026-10-27 recording `rec_20261027_151150` is the
reference for the cemetery: replaying frame 7002 reproduces Firebrand, the
flame spirit and the urn through the fixed compositor, while OAM-only Somulo
parts remain scattered.

A direct comparison of the live BG1 tilemap at frame 7002 with
`room_area2.json` found only **~47% tile-index agreement** even after sliding
the window in 2D. This proves the area-2 room's BG1 tilemap is wrong, not just
its palette/atlas. `bg_recompose.py` now also writes `*_bg1.png` and `*_bg2.png`
so the next pass can stitch/rebuild the room background from reference frames.

As a deliberate interim fallback, `install_full_map_backdrop.py` can install a
community full-stage map as a world-locked backdrop and disable the corrupt BG
tile layers. Area 2 uses the 2048x276 Murkland cemetery map with
`backdrop_parallax=1.0` and `backdrop_y=-70`; collision and object data remain
the extracted room data. This fixes the broken/duplicated BG visually, but the
image contains baked scenery/props and is not a replacement for the real
VRAM/HDMA room rebuild.

## 11. Long-term roadmap

| Phase | Goal | Status |
|---|---|---|
| 0 | Extraction proof: graveyard map + VRAM/CGRAM dump + static render | done |
| 1 | Engine skeleton: raylib, fixed 60 Hz, BG layers, input, camera | done |
| 2 | Firebrand core: Bank `$80` state machine, physics, slopes, animations | done: state machine, slopes, shot/spell/fireball |
| 3 | Combat and objects: fireball, `$1080` objects, enemy, `$85:C180` pickup, HUD | done: fireballs, object pool, urns, hearts, enemies, HUD |
| 4 | Vertical slice: full Area 1–3 scrolling rooms, transitions, title/menu, audio | **campaign foundation done**: 113 areas, transitions, bosses, crests, overworld/menus; audio placeholder |
| 5 | Full campaign: all areas, bosses, forms, Mode 7, password/save | in progress: all area rooms, crests/overworld/menus present; per-species OAM/AI, text, exact password/save and ROM audio remain |
| 6 | Fan-game content: new levels/story/art | not started |

A reasonable estimate for the vertical slice is **10–14 full-time weeks** for
one experienced developer, plus buffer for reverse engineering. A full port is
a **12–24 month** scale, not a sprint.

---

## 12. Definition of done for the first version

A short, playable build where:

- the game opens directly into the graveyard;
- Firebrand walks, jumps, hovers and flies with the original timing;
- a fireball kills one enemy, which drops or triggers a pickup;
- the camera scrolls through 3–5 rooms and an exit transitions;
- the HUD shows health and the current crest;
- a 600-frame input script produces the same positions/animations as the
  recomp within 1 px / 1 frame;
- a new room can be added by editing JSON and a PNG atlas without touching C;
- the build runs on Linux and Windows;
- no ROM-derived asset is committed or distributed.

Definition of done for the **final fan game**:

- A complete native game with its own campaign, using the original game’s
  movement/combat feel as the foundation.
- Data-driven levels, enemies, art and audio.
- Stable save/options/menus.
- Legally distributable: either require the player’s own ROM at generation
  time, or ship with original/replacement assets.

---

## 13. Risks and open questions

| Risk | Impact | Mitigation |
|---|---|---|
| Mid-stage CHR streaming (`$80:BFB5`/`$80:C11B`) | unvisited screens in an area may reference CHR tiles not yet in a single VRAM dump | decode CHR from `$98:D000` via `$80:C2AF` or merge VRAM across a room walkthrough |
| BG2 backdrop generator (WRAM `$7F`) | areas without a capture show a transparent background | one oracle frame per area in `tools/dc_extract/bg2_captures.json`; decode the generator later |
| Player state machine drift | feel drifts from `save0` | ported Bank `$80` state machine with 8.8 fixed point; `DC_DEMO=6`/`compare.py` regression keeps ≤1 px |
| Slope/ledge block attributes (`0x03..0x21, 0xa0`) | player steps on flat 16×16 tops instead of smooth hill heights (`y=160` vs `y=164`) | resolved: `$80:962B` surface table ported; `DC_DEMO=8` walks the hill |
| Projectile OAM overlap with palette-7 player group | fireball could stretch the player bbox | resolved for `save0`: projectile OAM is palette 6 and the extractor also windows around the object slot |
| BG2 HDMA parallax scroll splits | flat `scroll_x` on BG2 loses per-scanline sky/tree parallax | read HDMA table on channel 1 (`$210F` `BG2HOFS`) or approximate band scroll |
| Audio extraction | no soundtrack | BRR/DSP decoder or recorded development placeholder |
| Object AI breadth | huge scope | 26-slot pool + Area 1 list wired; species `$67` is a first-pass chase/damage/drop enemy, remaining species pending |
| Legal | distribution risk | no assets in repo; ROM-generated locally at install/setup time |
| GPL randomizer code | license contamination | reimplement formats from ROM disassembly; keep GPL tools separate |
| raylib flip quirks | visual corruption | pre-baked flips for BG; verify or pre-bake mirrored player frames |
| CGRAM restore timing | wrong sprite palettes | sample framebuffer; per-capture palette config |

Resolved questions (formerly open):

- **Object species dispatch layout**: `$82:8000` (main update), `$82:8180`
  (secondary), `$82:8300` (init) and `$82:8480` (aux) are 192-entry tables
  indexed by `species*2`; init entries are mostly 5-byte `JSL $83:xxxx; RTS`
  thunks (species `$67` → `$82:F382` → `$83:AF19`, update at `$83:AF74`).
- **BG2 backdrop storage**: generated at runtime, not in the ROM block tables;
  `$84:A057` DMAs it from WRAM `$7F` (see trap #21). The extractor consumes one
  oracle frame per area instead.
- **Per-area sprite list**: `$81:AE11` is a 16-bit pointer table to
  (metasprite group, frame count) pairs, one list per area, `0x00`-terminated
  (see trap #27). A cross-area consistency test proved it is the room's ambient
  animation list, not a species→group map. Object fields `$28/$2A/$2E` are not
  sprite pointers either: `$2A` is a map/offset table base used by the
  collision probe at `$80:91C7`. Per-species art is captured from live OAM via
  injected objects (Step 13).

- **How the loader remaps block tile indices to VRAM**: Resolved — there is no
  tile remap. `stage_600` is ROM Area 1 (`screens 8, 9` = `slots 9, 10`), not
  Area 2 (`screens 33, 34`); with `--area 1 --screens 9,10`, the ROM block table
  matches `stage_600`'s VRAM BG1 tilemap `1957/2048` words identically.
- **Vertical origin of the collision grid (`y=164` vs `y=176`)**: Resolved —
  `y=176` (`by=11`) came from loading Area 2's collision grid into Area 1. In
  Area 1 (`screens 8, 9`), the ground/slope row is `by=10` (`y=160..175`), where
  `attr=0x09` places Firebrand's feet at `y=164`, and the stone pillar is at
  `cx=24` (`x=384..399`, `y=128..159`).
- **Exact player jump/hover/walk constants and button mapping**: Resolved from
  Bank `$80` (`$80:DB00..F310`): `B` = Jump/Hover (`$1059`/`$105A`), `Y` =
  Fireball shot (`$105B`/`$105C`), `A` = Talisman/Headbutt (`$105D`/`$105E`),
  `X` = Subscreen; walk `0x00B3 → 0x0166`, jump `0x059C` with B-release `vy=0`
  cut at `$80:E227`, gravity `0x0038`, hover `State 0x06` (`vy=0`). (`$85:C1D4`
  was identified as the dropped heart bounce routine.)
- **Player movement parity with `save0`**: Resolved for the base ground/jump/
  hover loop. `src/player.c` runs the recovered substate flow in 8.8 fixed
  point; a 603-frame replay matches on X exactly and stays within 0.53 px on Y
  (the task-idle oscillation). Walk speed on flat ground is the `0x0166` cap,
  not a per-step ramp; the `0x00B3` first step belongs to the `$1070` slope
  path and is awaiting slope wiring.
- **Fireball shot timing, spawn offset and velocity**: Resolved from the `Y`
  capture. The press frame uses the idle pose, then a 6-frame and a 10-frame
  shot pose (17 total). The projectile spawns on the press frame in the first
  free `$1080..$1260` slot via `$80:F222`, at
  `(floor(player.x) + 3, floor(player.y) - 8)`, with `vx = 0x0300`
  (3.0 px/frame). The projectile OAM group is palette 6 and despawns at the
  camera edge in `save0`.
- **Area 1 full-room layout and slope heights**: Resolved. The ROM area grid
  is 8×2, but the graveyard row is the populated one (`screens 8, 9, 10, 11,
  16, 17, 18, 19`); the other row is all-zero BG1/collision padding. All 492
  referenced BG1 tiles are in the `stage_600` VRAM atlas. The `$80:962B` table
  gives surface offsets for `0x03..0x14`; `Level_FloorAt` snaps Firebrand to
  `block_top + offset`, so spawn is `y=164` on `attr=0x09` and the hill is
  walkable in both directions.
- **Area 1 object list and heart arc**: Resolved. The `$81:C874` pointer table
  gives a 6-byte record list; species `$57` is the urn (four in Area 1) and
  `$67` the enemy group. Urns drop a pickup using the `$85:C180` values
  (`0x0400` pop-up, `0x0040` gravity, `-0x0100` bounce decay); touching it
  increments HP. The HUD BG3 source is `save0` (not the HUD-less `stage_600`
  cinematic).

Remaining open technical questions:

- BG2 backdrop generator and HDMA tables for areas other than Area 1 (Area 1's
  `$84:AF65` bands are implemented; other areas use capture frames until the
  WRAM `$7F` generator path is decoded).
- Full object species ID (`$02`) → handler table (`$82:8000,X`) coverage;
  current AI is first-pass for skeletons/bats/gargoyles.
- Exact projectile-enemy/player-object hitbox, damage, knockback and drop
  tables from `$80:9C93` (current values are approximations).
- Per-species OAM/animation extraction from `$82:8300` init handlers.
- Mid-stage `$98:E000` CHR streaming and tile animation (`$81:C125`).
- Text/dialogue/cutscene encoding, exact password algorithm and retail SRAM
  format (the native JSON save format is implemented).
- Best audio path for distribution (native BRR+sequence synth vs replacement
  tracks).
- Widescreen support policy and Windows CI/test build path.

---

## 14. Legal and licensing

- The engine and tools in this repository are original code under MIT
  (`LICENSE`).
- *Demon's Crest* and all ROM-derived art, music, maps and data remain the
  property of Capcom.
- `assets/generated/` and `captures/` must never be committed or distributed.
- A public release must either:
  1. require the player’s own ROM and generate assets locally (like the
     recomp’s setup host), or
  2. replace all original art/music with original or licensed assets.
- The external randomizer used as a format reference is GPL-3.0. Do not copy
  its code into this MIT engine. Reimplement the documented formats or keep a
  separate GPL tool that communicates through files.
- The recompilation project is MIT, but its generated C and extracted game
  data are ROM-derived and also must not be distributed.

---

## 15. Git history

The current repository is a fresh copy whose history starts at `Initial
commit`; the older hash list that used to live here came from the previous
workspace copy and is no longer the authoritative history.

```
283ed28 Initial commit
8070c50 ... (imported native-port state)
        Add Firebrand animation capture and state machine (this session)
        BG2 capture pipeline, Windows build and campaign audit (2026-10-23)
        Save/options persistence, title CONTINUE and HUD bar fix (2026-10-23)
```

The `docs/` directory is now tracked. The accidental `docs` entry in
`.gitignore` was removed so the handoff files travel with the code.

---

## 16. Resume checklist

When resuming:

1. Read this file and `docs/ROADMAP.md`.
2. `git status` — confirm clean.
3. Build:
   ```sh
   cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
   cmake --build build -j
   ```
   Windows:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File tools/build_windows.ps1
   ```
4. Verify assets exist:
   ```sh
   ls assets/generated/room.json assets/generated/player_idle.png \
      assets/generated/player_anim.json assets/generated/hud_bar.png
   ```
   If missing, run the capture + extract steps in section 4. For animation
   assets specifically:
   ```sh
   python3 tools/oracle/capture_anim.py --out captures/anim
   python3 tools/dc_extract/extract_anim.py --dump captures/anim \
     --out assets/generated --clean
   ```
5. Run the game and take a reference screenshot:
   ```sh
   DC_RUN_FRAMES=10 DC_SCREENSHOT=check.png ./build/demonscrest
   ```
6. Confirm the graveyard scene, player and item render.
7. Copy `save0.sav` before any `--resume-state` run.
8. For oracle work, use `tools/oracle/oracle_save0_short.script` and
   `parse_player_trace.py`, not the area-2 landing route.
9. For physics changes, compare with `compare.py` and keep a trace before/after.
10. Run `./tools/run_regression.sh` (or `ctest --output-on-failure` in
    `build/`) before committing; it must pass (it now includes the save/load
    round-trip). Then run
    `python3 tools/audit_campaign.py` and compare its summary with the numbers
    recorded in section 9 (69 playable / 44 partial / 2 with BG2 as of
    2026-10-23).
11. Do not commit `assets/generated/`, `captures/` or `saves/`.

---

## 17. One-paragraph summary

The project has a working native C11 + raylib foundation that renders the
original graveyard room from extracted ROM data and runs Firebrand's authentic
Bank `$80` movement state machine in 8.8 fixed point. Disassembly of Bank `$80`
(`$80:DB00..F310`) and ROM level tables (`$81:A291`) resolved the major open
mysteries: `stage_600` is ROM Area 1 (`screens 8, 9` = `slots 9, 10`), not Area
2, which eliminates the 11 px spawn offset and proves the ROM block tables
match VRAM directly (`1957/2048` words) without any tile remap; `$85:C1D4` is a
bouncing heart pickup while Firebrand's true physics live in Bank `$80` (jump
`0x059C` with immediate `vy=0` cut on B release at `$80:E227`, gravity
`0x0038`, zero-G hover toggle at `State 0x06`); and `Y` (`$105C`) is the
Fireball shot button, spawning projectiles in `$1080..$1260` via the allocator
`$80:F222` (the earlier `$80:F1FE` label was a different helper), whereas `A`
(`$105E`) triggered the Talisman invocation pose. The port now matches `save0`
over a 603-frame ground/jump/hover replay (max delta `x=0.00 px`,
`y=0.53 px`), and the Y shot is implemented end to end: 17-frame spit pose,
7-slot fireball pool, palette-6 OAM stream, `(floor(player.x)+3,
floor(player.y)-8)` spawn and `0x0300` velocity, with pillar/viewport despawn.
Step 5 is also done: `--full-room` emits the populated Area 1 screen row as a
2048×256 BG1 map (the ROM grid's other row is empty padding) with a 128×16
collision grid, the `$80:962B` surface table gives smooth `0x03..0x14` slope
walking (spawn `y=164` on `attr=0x09`), BG2 wraps horizontally, and the camera
follows across the room with deadzones. Steps 6–7 add the 26-slot object pool
and the `$81:C874` Area 1 object list: four destructible species `$57` urns,
bouncing `$85:C180` heart pickups that heal HP, and a first-pass species `$67`
ghoul that chases, damages with knockback and drops hearts. The save0 BG3
status bar is baked as `hud_bar.png`/`hud_slots.png` and rendered with the
current HP bar and crest slots. Step 8 hardens the engine: a fixed 60 Hz
accumulator decoupled from display refresh, pre-baked mirrored player/fireball
textures, and a CTest/`tools/run_regression.sh` harness that re-runs demos
6/7/9/10/11/12 and asserts physics, projectile, pickup, enemy, Crest-form and campaign-transition invariants.
Step 9 now has an original procedural chiptune/SFX layer, a title screen,
pause overlay, and an Area Clear trigger at the graveyard exit. Step 10 moves
from the vertical slice to a **full-campaign foundation**: the extractor now
implements the ROM CHR decompressor, emits all 113 valid areas as 2D room
documents (multi-row/vertical grids, spawns, transitions, boss gates and
object lists), and bakes per-area BG atlases from ROM CHR/palettes. The OAM
metasprite decoder (`$8B:8000`) provides the real item/Crest and ghoul sprites;
Area 1 BG2 uses the recovered `$84:AF65` HDMA scanline bands. The runtime can
load any area, transition on bounding boxes or `$81:97DA` boss gates, run Area 0
Somulo and basic skeleton/bat/gargoyle encounters, and exposes six Gargoyle
forms (Earth dash, Air flight, Water swim, Time/Ultimate defense, Fire-Crest
elements, wall cling, headbutt), a Crest/Item subscreen, shop, password,
options, Game Over/endings and a Mode 7-style overworld. Remaining work is
fidelity: per-species OAM/AI, BG2/mid-stage CHR for other areas, text/cutscenes,
the exact password/save format and ROM audio.

The 2026-10-23 continuation added the three pieces the fidelity phase needs
before it can scale: (1) a per-area BG2 backdrop pipeline driven by
`tools/dc_extract/bg2_captures.json`, which bakes an oracle frame's BG2 tilemap
plus a capture-based atlas for that room — Areas 1 and 3 now render their real
backgrounds, and the guest-side generator (WRAM `$7F`, `$84:A057`) is
documented as the remaining reverse-engineering target; (2) `tools/audit_campaign.py`,
a structural audit over all 113 generated rooms (69 playable, 44 partial,
2 with BG2, 45 with at least one flagged issue — mostly zero-collision
boss/cutscene arenas), giving the project a repeatable CI gate instead of
ad-hoc inspection; and (3) an offline Windows build (`-DDC_RAYLIB_ROOT`,
`tools/build_windows.ps1`) verified with raylib 6.2 + MinGW GCC 16.2, so the
native port and the regression suite run on the same machine as the oracle.
The species dispatch tables (`$82:8000/$8180/$8300/$8480`, `JSL` init thunks)
and the debug server's `write_ram`/`dump_vram` state access were also mapped,
which is the starting point for the next content task: per-species OAM/AI.

A follow-up pass added native save/options persistence: `Game_SaveProgress` /
`Game_LoadProgress` write a versioned `saves/dc_save.json` (area, cleared
stages, HP, Crests/forms, Talismans, Urns, Spells, gold, volume) on area clear,
overworld entry and exit; the title gains a `CONTINUE` entry only when a save
exists; `DC_SAVE_PATH`/`DC_NO_SAVE`/`DC_SAVE_FORCE`/`DC_RESUME` cover tests.
The regression suite now autosaves in one run and asserts the resumed area,
max HP and gold in a second, and the HUD health bar was fixed to read as a
segmented red bar (the baked texture is a brightness mask, so the empty part is
tinted dark and the filled part red).
