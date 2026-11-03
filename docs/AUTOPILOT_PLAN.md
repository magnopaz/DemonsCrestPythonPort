# Autopilot plan — finishing the original campaign

Status file for the autonomous continuation work. Ordered by dependency; every
item ends with a verification command, not a claim.

Environment (this machine):
- ROM: `~/Projetos/opencode/roms/Demon's Crest (USA).sfc`
- Oracle: `~/Projetos/opencode/DemonsCrestSNESRecomp/build-trace/DemonsCrestSNESRecomp`
  (trace build, debug server; 100+ named save states in `build-trace/saves/`)
- Headless display: `Xvfb :99` (export `DISPLAY=:99`)
- Assets are regenerated with `tools/dc_extract/extract.py` (ROM + one capture)

## M1 — Verified baseline (done 2026-11-01)

- [x] Configure + build Release (`build/demonscrest`).
- [x] Graveyard capture `captures/graveyard/stage_600.*` from the oracle.
- [x] `extract.py` → 113 `room_areaN.json`, 573 asset files, 55 MB.
- [x] `capture_anim.py` + `extract_anim.py` → player/fireball/HUD clips.
- [x] `tools/run_regression.py` **PASS** under `DISPLAY=:99` (exit 0):
      demos 6/7/9/10/11/12/13, boss data + runtime, boss defeat, multi-area loads.
      The suite started this session with 14 failures; the fixes that closed it
      are recorded in `docs/PROJECT_STATE.md` and the commits of 2026-11-01.
- [x] Post-extraction pipeline made reproducible: `tools/build_assets.sh`
      (extract → anim → font/endings → `apply_boss_table` → `apply_npc_table`
      → `apply_door_table`). Verified end to end: wiped and rebuilt
      `assets/generated` from ROM + `captures/graveyard` + `captures/anim`,
      then `run_regression.py` → **PASS (exit 0)** on the rebuilt tree.
      113 rooms, 28 with a non-empty BG2 after the rebuild.

## M2 — BG2 backdrop for every mapped area

- [x] **Rendering bug fixed: BG1 was offset by the reference camera again.**
      `DrawLayer()` subtracted `level->camera_y` from BG1's scroll, but BG1's
      tilemap is already in world coordinates. Any room whose reference camera
      y was non-zero (the whole Phalanx fortress, ice palace, colosseum interior)
      drew the world tens to hundreds of pixels off-screen: a black void with
      the player floating in it. BG1 now uses world space; only captured
      backdrops stay camera-relative. Measured: area 33 95.2% → 59.4% black
      (the original frame is 58.9%), area 41 85% → 41.2%, and area 33 now shows
      its columns, arches, brick walls and skeleton enemy. Mean over the 45
      mapped rooms 44% → 39%.

- [x] Cross-platform capture helpers:
  `tools/oracle/dump_save_wram.py`, `tools/oracle/capture_area_frame.py`.
  (The old `capture_save_frames.py` hard-codes `M:\Opencode` and integer saves;
  a relative `--resume-state` is resolved against the recomp cwd and silently
  fails, so every path handed to the host must be absolute.)
- [x] Fresh `fNNNNNN.*` for 30 of the 31 manifest saves, manifest frames rewritten.
- [x] Re-extract with 30 captured backdrops (area 48 shows the night sky behind
      the dungeon; area 20 captured separately after a transient debug-server
      failure).
- [ ] **Area identification is unsolved.** `WRAM $008D` is a stage/room id, not
      the extractor's area index (`lvl_I_murkland-cemetery` reads 2 but its BG1
      matches area 1 at 1.000). `identify_area.py` matches BG1 exactly but ties
      on areas that share screen data (1 vs 73). Until a tie-break exists, the
      curated `bg2_captures.json` mapping cannot be extended safely.
- [x] **Area identification solved for 45 rooms.** `tools/oracle/map_saves_to_areas.py`
      matches each save's live BG1 against the extracted rooms (with `$008D`'s
      stage id as a hint); 45 areas land on an exact 1.000 match. A curated
      guess list was not enough — the new mapping disagrees with several of the
      old manifest entries (e.g. area 48 is `save1c`, not `save7`).
      `tools/oracle/bake_area_captures.py` turns the mapping into per-area
      captures and rewrites the manifest; only scores ≥0.99 are captured,
      because a wrong backdrop is worse than a black one.
- [x] 94 area captures baked (21 more from the force-load sweep); extraction
      reports **65 rooms with a non-empty BG2** (was 28 at the start of the
      session). 29 of the 94 captures contain no BG2 cells at all — verified in
      the raw VRAM, so those rooms either have no BG2 or draw their backdrop by
      another mechanism (sprites/HDMA), not a capture bug.. Measured effect: area 20 went from 91.1% to
      39.1% black pixels, area 34 from 80.5% to 12.7% — area 34 now renders the
      starry sky, mountain silhouettes, mist and the icy ledge with icicles.
      Area 84 (Phalanx arena) stays dark by design.
- [ ] 68 areas still have no verified save; they need either a save state from
      a fresh playthrough or a decoded runtime BG2 generator.
- [ ] Areas 43 / 42 / 30 / 29 still render dark (90%, 73%, 69%, 67% black).
      Area 43 was investigated: BG1 has only 19% non-zero cells, BG2 50%, and
      **both atlases are complete** (1/212 BG1 tiles and 0/17 BG2 tiles blank),
      so it is not a missing-art problem. A speculative `wrap_y` change for tall
      backdrops was tried and reverted (it did not help area 43 and moved area
      24 from 5.1% to 11.1% black). Prime suspect: partial BG1 extraction
      coverage for those rooms — the fix path is rebaking BG1 from the capture's
      VRAM (`bg_recompose.py`), which is what the area-loader work enables.
      Later data point: area 43's BG2 content sits **only in tilemap rows
      32..63** of a 32x64 map while the layer draws from `origin_y = 64`
      (rows 8..36), and forcing `scroll_y = -192` changed nothing (still 90.5%
      black) — so BG2 is not being drawn for this room at all, rather than being
      merely offset. That needs a renderer-level debug session, not an asset fix.
- [ ] Screenshot spot-checks: area 48 renders with a backdrop, but BG1 shows
      black bands and misaligned bricks (separate extraction defect).
- [x] Screenshot audit (30 areas, `/tmp/shots/shot_<area>.png`): black-pixel
      fraction ranges from 0.7% (area 14) to 91% (area 20). That is a real
      signal, but **the earlier "campaign BG1 is broken" conclusion was wrong**:
      it came from `compare_rooms.py` scoring a 1024x896 window dump against a
      256x224 oracle frame. With the native image downscaled to the render
      target, the graveyard room is clearly the same scene as the original
      (same trees, torches, water, green statue), MAD 27 mostly from camera
      framing, the area banner overlay and the HUD.
- [ ] `compare_rooms.py` fix applied: native screenshots are resized to
      256x224 before scoring. Re-run it for a sample of areas before drawing
      further conclusions about visual fidelity.
- [ ] Area banner ("STAGE 01 / WORLD ...") shows up in every headless
      screenshot and hides the top of the room; decide whether it should be
      suppressed for `DC_RUN_FRAMES` captures (it is a gameplay overlay, not a
      rendering defect).
- [ ] `identify_area.py`: empty blocks made every area tie at 1.000. It now
      ignores blocks that are <60% non-zero, but areas 1 and 73 still tie at
      1.000 on real data — they appear to share identical screen blocks, so a
      tie-break by world size or object list is still required.
- [ ] Screenshot spot-checks (`DC_AREA`, `DC_RUN_FRAMES`, `DC_SCREENSHOT`).

## M3 — Oracle screenshot comparison harness

- [x] `tools/oracle/compare_rooms.py`: oracle `screenshot` + native
      `DC_AREA/DC_SCREENSHOT`, brute-force shift alignment, side-by-side PNG and
      `compare.json` (mean abs diff). First result: area 1 native vs the
      cemetery save = MAD 26.45 at a 94 px shift, and the images are different
      rooms — see the M2 note.

## M4 — Enemies and bosses

- [ ] Bake the 17 object-list species with `capture_species.py` /
      `extract_species.py` (`$57 $81 $10 $67 $07 $2C $96 $26 $2D $08 $01 $09
      $A5 $2E $24 $33 $49`).
- [ ] Port the real `$83:AF74` species `$67` ghoul states 1–4 and the `$DEA2`
      behaviour dispatch.
- [ ] Port the remaining handlers in the `$82:8000` table, most-used first.
- [ ] Authentic player-object hitboxes (`$80:9C93`), damage, knockback, drops.

## M5 — Player forms

- [ ] Capture per-form OAM sets and animation tables (Earth, Air, Water, Time,
      Ultimate) from the oracle; replace palette-tint placeholders.
- [ ] Hurt/death clips.

## M6 — Audio

- [ ] Decode the SPC700 driver's sample directory; extract BRR instruments.
- [ ] Either re-sequence the tracks from the ROM sequence data or finish an
      original soundtrack with per-area/boss/menu tracks; wire SFX ids.

## M7 — Story and presentation

- [ ] Intro/cutscene sequencing (scene camera, timing, per-event script index).
- [ ] Ending artwork and credits.
- [ ] Town NPCs / shop dialogue / Headbutt minigame.

## M8 — Retail save and password

- [ ] Decode the retail 10-letter password encode/decode and the SRAM layout.

## M9 — Release

- [ ] Full campaign playthrough check without dev hooks.
- [ ] Windows build + CI; packaging notes; asset generation one-liner.

## Guardrails

- Never commit `assets/generated/` or `captures/` (ROM-derived).
- Do not tune physics by feel: use an oracle trace.
- Keep the simulation frame-based and deterministic.
- Every milestone commit must keep `tools/run_regression.py` green.
