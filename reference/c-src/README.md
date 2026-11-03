# Frozen C implementation (source spec)

This is a verbatim copy of `DemonsCrestNativePort/src`, its CMakeLists and the
bundled `external/cJSON`, kept as the specification the Python modules were
translated from. (Building it would additionally need raylib, which CMake
fetches, and a display.) Nothing here
is built or run by this repository: the executable used for parity checks is the
already-built `../DemonsCrestNativePort/build/demonscrest` (see
`tools/parity_trace.py`).

Why keep it: when a Python module's behaviour is unclear, the C file is the
authority. The mapping is 1:1:

| C | Python |
| --- | --- |
| `src/assets.c` | `dcpy/assets.py` |
| `src/anim.c` | `dcpy/anim.py` |
| `src/level.c` | `dcpy/level.py` |
| `src/player.c` | `dcpy/player.py` |
| `src/object.c` | `dcpy/object.py` |
| `src/projectile.c` | `dcpy/projectile.py` |
| `src/camera.c` | `dcpy/camera.py` |
| `src/input.c` | `dcpy/input.py` |
| `src/text.c` | `dcpy/text.py` |
| `src/audio.c` | `dcpy/audio.py` |
| `src/render.c` | `dcpy/render.py` |
| `src/game.c` | `dcpy/game.py` |
| `src/main.c` | `dcpy/main.py` |

`docs/PARITY.md` lists the C semantics Python does not reproduce by default
(struct copies, `memset`, cdata `Color`, stderr diagnostics).
