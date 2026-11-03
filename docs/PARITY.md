# Parity record

Reference build: `../DemonsCrestNativePort/build/demonscrest` (C11 + raylib).
Python port: `python -m dcpy.main` / `tools/demonscrest-py`.

## Trace parity

`tools/parity_trace.py` drives both binaries with identical `DC_*` variables
and compares the CSVs byte for byte.

```
$ .venv/bin/python tools/parity_trace.py --demo 15 --frames 600 --area 1
player.csv: 600 rows identical
objects.csv: 5840 rows identical
projectiles.csv: 70 rows identical
PARITY OK

$ .venv/bin/python tools/parity_trace.py --demo 12 --frames 300 --area 1 \
      --start-x 1850 --start-y 168 --env DC_CAMPAIGN=1 --env DC_BOSS_HP=1
player.csv: 300 rows identical
objects.csv: 2243 rows identical
projectiles.csv: 91 rows identical
PARITY OK
```

This covers walking, slope contact, jumps/hover, wall cling, fireballs, urn
destruction, heart pickups, the species `$67` ghoul, the species `$09`
Hippogriff (spawn, stone phase, hit, rubble) and the area 1 -> 2 gate.

## Frame parity

`tools/compare_frames.py` downscales the C build's 1024x896 window shot by 4
(nearest) and compares it with the Python render-target export.

```
frame 200 (no banner): mean abs diff 0.029, pixels >8: 0.17 %
  - HUD region (rows 0-29): mean 0.219
  - world region:           mean 0.000
frame 60 (entry banner): mean abs diff 0.422, pixels >8: 1.55 %
```

A sweep over other rooms at frame 120 (same command, different `DC_AREA`):

| Area | mean abs diff | pixels >8 |
| --- | --- | --- |
| 0 (colosseum, Somulo intro) | 0.210 | 0.36 % |
| 2 (slope) | 0.029 | 0.17 % |
| 3 (abyss) | 0.058 | 0.23 % |
| 10 | 0.029 | 0.17 % |
| 61 | 0.030 | 0.17 % |

The world is bit-identical. The residuals are the default font's antialiased
edges and the HUD's highlighted slot outline.

## The project suite against the Python port

Run from this repository; the checkers default to `tools/demonscrest-py` and
`assets/generated` (pass `--binary ../DemonsCrestNativePort/build/demonscrest`
to score the frozen C build instead):

| Check | Result |
| --- | --- |
| `check_hippogriff.py` | PASS (spawn, 260-frame stone phase, gate to area 2) |
| `check_ghoul.py` | PASS |
| `check_wall_cling.py` | PASS (87 frames, 0.750 px/frame cap) |
| `check_transition_fade.py` | PASS (28+64+28 frames) |
| `check_mvp_somulo.py` | PASS (4 ordered intro phases, 610 locked frames, blind walk, six-hit rhythm) |
| `check_campaign.py` | PASS (13 ok, 0 no-boss) |
| `check_playthrough.py` | PASS (6/6 steps) |
| `check_areas.py` | PASS |
| `run_regression.py` | PASS |

```
regression: PASS (demos 6,7,9,10,11,12,13, boss data/runtime,
                   hippogriff fight, boss defeat + multi-area loads)
exit=0
```

## Performance

Measured on the dev machine (headless, Xvfb + llvmpipe), 200 frames of the
cemetery demo after warm-up:

```
update  0.12 ms/frame
render  6.30 ms/frame
total   156 fps (vsync off)
```

The first Python render loop was 41 ms/frame. Profiling showed
`raylib-python-cffi`'s `Rectangle()`/`Vector2()` constructors (four per tile,
~6k calls/frame) cost more than the draws. Reusing module-level scratch
structs and hoisting the per-palette texture lookup brought it to 6.3 ms.

## Porting traps found by measurement

- **A C struct assignment is a copy; Python assignment aliases.** `Player saved
  = game->player;` in `Game_TransitionToArea` became `saved = game.player`, so
  `Player_Init` overwrote the "saved" progression and every room change reset
  HP to the spawn kit (4/6 instead of 7/7). Snapshot the fields explicitly.
- **C structs zero themselves.** `Player_Init` and `Level_LoadFile` start with
  `memset`. Reusing Python objects without an equivalent reset left stale
  `vx/vy` after a transition and appended the new room's objects to the old
  room's list (29 objects in a 12-object room, boss respawned).
- **raylib `Color` is a cdata reference, not a value.** `slot_col = WHITE;
  slot_col.a = 235` mutated the shared module constant and dimmed every later
  draw by 8 %.
- **`DrawRectangleLines` changed implementation between raylib 5 and 6.** The
  C build's GL line lands one pixel left/one lower than 6.x's filled-rectangle
  outline; `rl.draw_rect_lines()` reproduces the C geometry.
- **Render textures are bottom-up.** `LoadImageFromTexture` on a render target
  needs `ImageFlipVertical` before export to match the window.
- **`DC_AREA=0` is a value, not a falsy flag.** `if area:` skipped the
  colosseum and loaded area 1, which made every Somulo check fail with
  "intro phases: []". Test `is not None`, mirroring C's `*env` check.
- **The checkers parse stderr.** The C build writes debug hooks with
  `fprintf(stderr, ...)`; Python `print()` goes to stdout, so a captured run
  looked silent even though the phases ran. `util.eprint()` keeps the contract.
- **Asset palettes are indexed, not appended.** `bg_area` slots must stay
  fixed at 8 entries or palette 2 lands in slot 1 when palette 1 is absent.
