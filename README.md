# Demon's Crest — Python Port

A Python 3 + raylib port of the native C11 fan port in
`../DemonsCrestNativePort`, which is now **frozen** as the source spec and the
reference binary. This repository is the living implementation and is
self-contained: the ROM-derived assets, captures, research docs and the
verification suite all live here.

> **No ROM data is distributed here.** `assets/generated/` and `captures/` are
> git-ignored. You need your own *Demon's Crest (USA)* ROM to regenerate them
> with `tools/build_assets.sh`.

## Status

All 8,816 lines of the C game are ported: assets, level/collision, player
state machine, object pool + per-species AI, projectiles, camera, animation,
dialogue font, audio, rendering and the full game-state machine
(title / playing / pause / subscreen / overworld / shop / password / options /
clear / game over / ending / dialogue).

Verified against the C build (see `docs/PARITY.md` for the commands):

| Check | Result |
| --- | --- |
| 600-frame cemetery demo (`DC_DEMO=15`), player+object+projectile traces | byte-identical |
| 300-frame Hippogriff fight (`DC_DEMO=12`, `DC_BOSS_HP=1`), all traces | byte-identical |
| Area 1 frame 200, render target vs C window shot | mean diff 0.029, 0.17 % pixels |
| Area 1 frame 60 (entry banner visible) | mean diff 0.42, 1.55 % pixels |
| Areas 0, 2, 3, 10, 61 at frame 120 | mean diff 0.03-0.21, <=0.36 % pixels |
| Full suite (`tools/run_regression.py`, default binary = this port) | PASS |

Rendering is pixel-identical outside antialiased text edges: the world region
of frame 200 measures exactly 0.0 difference
([side-by-side + amplified diff](docs/parity_area1_f200.png)). Render cost is ~6.3 ms/frame and
the simulation ~0.12 ms/frame on this machine (headless, software GL), so the
60 Hz loop has plenty of headroom.

## Quick start

```sh
cd ~/Projetos/opencode/DemonsCrestPythonPort
python3 -m venv .venv
.venv/bin/pip install -e .

# assets are local (git-ignored); --assets overrides the default
.venv/bin/python -m dcpy.main
```

Asset lookup order: `--assets DIR`, `$DC_ASSETS`, `./assets/generated`, then
the sibling C project as a legacy fallback. `DC_ASSETS` is the convenient
override. `tools/build_assets.sh` regenerates the tree from the ROM and
`captures/` (both paths are relative to this repository).

## Controls

| Key | SNES | Action |
| --- | --- | --- |
| Arrows / WASD | d-pad | move |
| Z / Space | B | jump, hover, wall-jump |
| X / J | Y | fireball |
| C / K | A | talisman / headbutt / talk |
| Tab / I / V | X | crest & item subscreen |
| Q / E | L / R | cycle crest form |
| Enter | Start | confirm / pause menu |
| Esc | Select | pause |
| F1 | — | collision debug overlay |
| F3 | — | FPS counter |

## Deterministic / headless runs

The port keeps the C build's environment contract, so the same demo scripts
and the project's own checkers drive it unchanged.

```sh
# one room, 300 fixed 60 Hz updates, dump the 256x224 render target
DC_AREA=1 DC_RUN_FRAMES=300 DC_SCREENSHOT_RT=frame.png \
  .venv/bin/python -m dcpy.main --assets ../DemonsCrestNativePort/assets/generated

# scripted input demo + traces
DC_AREA=1 DC_DEMO=15 DC_RUN_FRAMES=600 \
DC_TRACE_CSV=player.csv DC_TRACE_OBJECTS=objects.csv \
  .venv/bin/python -m dcpy.main
```

Useful variables: `DC_AREA`, `DC_DEMO`, `DC_RUN_FRAMES`, `DC_START_X/Y`,
`DC_STATE` (`title`, `overworld`, `subscreen`, `pause`, `shop`, `password`,
`options`, `clear`, `gameover`, `ending`), `DC_CAMPAIGN`, `DC_BOSS_*`,
`DC_SCREENSHOT_RT` (render target, upright) and `DC_SCREENSHOT` (window shot,
like the C build), `DC_TRACE_*`, `DC_NO_AUDIO`, `DC_AUDIO_FORCE`,
`DC_AUDIO_DEBUG`.

`tools/demonscrest-py` keeps the C build's CLI/env contract. The checkers
copied from the C project now default to it and to this repo's assets, so they
run from here unchanged:

```sh
python3 tools/check_hippogriff.py      # whole suite: tools/run_regression.py
```

## Layout

| File | Ported from | Contents |
| --- | --- | --- |
| `dcpy/rl.py` | — | raylib binding shim + C-compatible outline helper |
| `dcpy/consts.py` | `*.h` enums | states, object types, audio ids |
| `dcpy/util.py` | — | env flags, JSON, C rounding |
| `dcpy/assets.py` | `assets.c` | textures, species sheets, rooms, endings |
| `dcpy/anim.py` | `anim.c` | player/crest/projectile animation sheets |
| `dcpy/level.py` | `level.c` | room JSON, tile collision, slope table |
| `dcpy/player.py` | `player.c` | 8.8 fixed-point movement state machine |
| `dcpy/object.py` | `object.c` | 26-slot pool, spawns, per-species AI |
| `dcpy/projectile.py` | `projectile.c` | fireball pool |
| `dcpy/camera.py` | `camera.c` | deadzone camera |
| `dcpy/input.py` | `input.c` | keyboard/gamepad + demo scripts |
| `dcpy/text.py` | `text.c` | ROM dialogue script + BG3 font |
| `dcpy/audio.py` | `audio.c` | ROM music tracks (one per stage family) + ROM/procedural effects |
| `dcpy/render.py` | `render.c` | tile layers, sprites, HUD, fade |
| `dcpy/game.py` | `game.c` | states, saves, password, overworld, overlays |
| `dcpy/main.py` | `main.c` | window, fixed-step loop, screenshot |
| `reference/c-src/` | — | the frozen C implementation, as the spec to read |
| `docs/` | — | the project's research: state/handoff, level map, audio plan, AI notes, sprite/map references |
| `captures/` | — | reference frames and save-state dumps used by the extractors (git-ignored) |

## Tooling

- `tools/parity_trace.py` — runs the frozen C build and this port on one demo
  script and diffs player/object/projectile traces.
- `tools/compare_frames.py` — measures a C window screenshot against a Python
  render-target dump and writes a side-by-side.
- `tools/demonscrest-py` — same CLI/env as `build/demonscrest`.
- `tools/run_regression.py`, `tools/check_*.py` — the project's gates, driving
  this port by default.
- `tools/dc_extract/`, `tools/oracle/`, `tools/gen/`, `tools/audio/` — the asset
  pipeline and oracle probes, unchanged.
- `tools/build_assets.sh` — regenerates `assets/generated/` from the ROM and
  `captures/`; run it as `PYTHON=.venv/bin/python tools/build_assets.sh`
  (the extractors need Pillow/numpy, which the venv has).

## Known gaps

- Antialiased UI text can differ by a pixel of coverage from the C build's
  raylib version (`DrawRectangleLines` geometry was matched explicitly).
- The full campaign (every room, shop stock, all four endings) is translated
  but only area 1's content is gated by the C suite so far.
- Audio: every stage theme is the ROM's own audio (14 looping WAVs selected
  from a measured room table, see `docs/AUDIO_PLAN.md`), but only the jump
  effect has been captured from the console — the other effects are still the
  procedural stand-ins. The ending cue is not captured yet either (the ending
  save state is silent), so `MUSIC_ENDING` falls back to a synthesised loop.
  No sample-exact A/B has been run against the C binary's device output.

`docs/PARITY.md` records the measurements and the porting traps that cost real
debugging time (C struct copies, level reload resets, raylib `Color` aliasing,
struct-construction cost). `docs/PROJECT_STATE.md` is the project handoff; the
next session starts there.
