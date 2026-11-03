"""Raylib bindings for the Python port.

The C project links raylib directly.  This module keeps the same call style by
re-exporting the function names from `raylib` (the cffi binding) and the struct
constructors from `pyray`, which is how raylib-python-cffi >= 6 splits its API.

    from . import rl
    rl.DrawTexturePro(tex, rl.Rectangle(0, 0, w, h), dst, rl.Vector2(0, 0),
                      0.0, rl.WHITE)
"""

from __future__ import annotations

import raylib as _lib
import pyray as _p

# Struct constructors and the cffi handle live in pyray.
ffi = _p.ffi
Rectangle = _p.Rectangle
Vector2 = _p.Vector2
Color = _p.Color
Texture2D = _p.Texture2D
Image = _p.Image
RenderTexture2D = _p.RenderTexture2D
Camera2D = _p.Camera2D
Wave = _p.Wave
Sound = _p.Sound
Music = _p.Music

# Re-export every raylib function/constant.  Python modules then read like the
# C source: rl.LoadTexture(), rl.DrawTexturePro(), rl.WHITE, ...
for _name in dir(_lib):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_lib, _name)


def cstr(text: str) -> bytes:
    return text.encode("utf-8")


def rect(x, y, w, h):
    return Rectangle(float(x), float(y), float(w), float(h))


def vec2(x=0.0, y=0.0):
    return Vector2(float(x), float(y))


def rgb(r, g, b, a=255):
    return Color(int(r), int(g), int(b), int(a))


def draw_rect_lines(x, y, w, h, color):
    """DrawRectangleLines with the C build's rasterisation.

    The C port links raylib's GL line path: a 1 px outline requested at
    (x, y, w, h) lands on pixels x-1 .. x+w-1 and y .. y+h.  Raylib 6 draws
    outlines as filled rectangles instead, which shifts every box by a pixel,
    so the port reproduces the 5.x geometry explicitly.
    """
    x, y, w, h = int(x), int(y), int(w), int(h)
    _lib.DrawRectangle(x - 1, y, w + 1, 1, color)
    _lib.DrawRectangle(x - 1, y + h, w + 1, 1, color)
    _lib.DrawRectangle(x - 1, y, 1, h + 1, color)
    _lib.DrawRectangle(x + w - 1, y, 1, h + 1, color)


def flip_texture(tex):
    """Pre-baked horizontal mirror, like the C asset loader does.

    raylib's negative source rectangles are unreliable (see assets.h), so the
    flipped copy is baked once at load time and drawn with a normal src rect.
    """
    img = _lib.LoadImageFromTexture(tex)
    _lib.ImageFlipHorizontal(ffi.addressof(img))
    out = _lib.LoadTextureFromImage(img)
    _lib.UnloadImage(img)
    if _lib.IsTextureValid(out):
        _lib.SetTextureFilter(out, 0)  # TEXTURE_FILTER_POINT
    return out
