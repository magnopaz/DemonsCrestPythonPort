# Demon's Crest — Python Port

A Python 3 + raylib port of the native C11 fan port in
`../DemonsCrestNativePort`. The same ROM-derived assets, the same extracted
room data and the same recovered SNES behaviour — rewritten module by module
in Python so gameplay iteration does not need a C rebuild.

> **No ROM data is distributed here.** `assets/generated/` belongs to the C
> project and is git-ignored there too. You need your own *Demon's Crest (USA)*
> ROM and the C project's `tools/build_assets.sh` to produce it.

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
| C suite: hippogriff, ghoul, wall cling, room fade | PASS |
| C regression suite (`tools/run_regression.py`) | see `docs/PARITY.md` |

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

# assets live in the C project unless you copy them here
.venv/bin/python -m dcpy.main \
  --assets ../DemonsCrestNativePort/assets/generated
```

Asset lookup order: `--assets DIR`, `$DC_ASSETS`, `./assets/generated`,
`../DemonsCrestNativePort/assets/generated`, then the absolute path of this
checkout's sibling. `DC_ASSETS` is the convenient override.

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

`tools/demonscrest-py` is a drop-in replacement for `build/demonscrest`, so
the C project's checkers run against the Python port:

```sh
cd ../DemonsCrestNativePort
python3 tools/check_hippogriff.py \
  --binary ../DemonsCrestPythonPort/tools/demonscrest-py \
  --assets assets/generated
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
| `dcpy/audio.py` | `audio.c` | ROM music WAVs + procedural fallbacks |
| `dcpy/render.py` | `render.c` | tile layers, sprites, HUD, fade |
| `dcpy/game.py` | `game.c` | states, saves, password, overworld, overlays |
| `dcpy/main.py` | `main.c` | window, fixed-step loop, screenshot |

## Tooling

- `tools/parity_trace.py` — runs the C build and this port on one demo script
  and diffs player/object/projectile traces.
- `tools/compare_frames.py` — measures a C window screenshot against a Python
  render-target dump and writes a side-by-side.
- `tools/demonscrest-py` — same CLI/env as `build/demonscrest` for the C
  suite's checkers.

## Known gaps

- Antialiased UI text can differ by a pixel of coverage from the C build's
  raylib version (`DrawRectangleLines` geometry was matched explicitly).
- The full campaign (every room, shop stock, all four endings) is translated
  but only area 1's content is gated by the C suite so far.
- Audio output is the same ROM WAV / procedural mix; no sample-exact A/B has
  been run against the C binary's device output.

`docs/PARITY.md` records the measurements and the porting traps that cost
real debugging time (C struct copies, level reload resets, raylib `Color`
aliasing, struct-construction cost).
