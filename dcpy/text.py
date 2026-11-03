"""Dialogue script and BG3 ASCII font (port of text.c)."""

from __future__ import annotations

import os

from . import rl
from .util import file_exists, read_json

TEXT_GLYPH_W = 8
TEXT_GLYPH_H = 8
TEXT_COLUMNS = 16
TEXT_FIRST = 0x20
TEXT_LAST = 0x7E

TEXT_MAX_STRINGS = 512
TEXT_MAX_PAGES = 6
TEXT_MAX_LINES = 8
TEXT_LINE_MAX = 48
TEXT_LINE_H = 10

_APOSTROPHE = "["   # the ROM's in-band apostrophe
_FULLSTOP = "\\"    # period/quote stand-in


class TextScript:
    def __init__(self):
        self.count = 0
        self.page_count: list[int] = []
        self.pages: list[list[list[str]]] = []
        self.line_count: list[list[int]] = []


def _copy_line(src: str) -> str:
    out = []
    for ch in src[:TEXT_LINE_MAX - 1]:
        if ch == _APOSTROPHE:
            ch = "'"
        elif ch == _FULLSTOP:
            ch = "."
        out.append(ch)
    return "".join(out)


def _split_line(src: str) -> list[str]:
    """Split one ROM line on the in-line break symbol ('j')."""
    out = []
    buf = []
    for ch in src:
        if ch == "j":
            if buf:
                out.append(_copy_line("".join(buf)))
            buf = []
        elif len(buf) + 1 < TEXT_LINE_MAX:
            buf.append(ch)
    if buf:
        out.append(_copy_line("".join(buf)))
    return out


def text_load_script(script: TextScript, asset_dir: str) -> bool:
    path = os.path.join(asset_dir, "text_strings.json")
    if not file_exists(path):
        return False
    try:
        root = read_json(path)
    except (OSError, ValueError):
        return False
    strings = root.get("strings") or []
    for entry in strings:
        if script.count >= TEXT_MAX_STRINGS:
            break
        pages_out: list[list[str]] = []
        counts_out: list[int] = []
        page_index = 0
        for page in entry.get("pages") or []:
            if page_index >= TEXT_MAX_PAGES:
                break
            lines: list[str] = []
            for line in page:
                if len(lines) >= TEXT_MAX_LINES:
                    break
                if isinstance(line, str):
                    for piece in _split_line(line):
                        if len(lines) < TEXT_MAX_LINES:
                            lines.append(piece)
            if lines:
                pages_out.append(lines)
                counts_out.append(len(lines))
                page_index += 1
        if page_index > 0:
            script.pages.append(pages_out)
            script.line_count.append(counts_out)
            script.page_count.append(page_index)
            script.count += 1
    return script.count > 0


def text_unload_script(script: TextScript) -> None:
    script.count = 0
    script.page_count = []
    script.pages = []
    script.line_count = []


def _normalize(text: str) -> str:
    out = []
    pending_space = False
    for ch in text:
        c = ch.upper()
        if ("A" <= c <= "Z") or ("0" <= c <= "9"):
            if pending_space and out:
                out.append(" ")
            pending_space = False
            out.append(c)
        else:
            pending_space = True
    return "".join(out)


def text_contains_loose(haystack: str, needle: str) -> bool:
    if not haystack or not needle:
        return False
    pin = _normalize(needle)
    if not pin:
        return False
    return pin in _normalize(haystack)


def text_find(script: TextScript, needle: str) -> int:
    if script is None or not needle:
        return -1
    for i in range(script.count):
        for page in script.pages[i]:
            for line in page:
                if text_contains_loose(line, needle):
                    return i
    return -1


def text_width(text: str) -> int:
    width = 0
    for ch in text:
        if ch == "\n":
            width = 0
            continue
        width += TEXT_GLYPH_W
    return width


def text_draw_string(assets, text: str, x: int, y: int, tint) -> None:
    if not rl.IsTextureValid(assets.font):
        return
    cx = x
    cy = y
    for ch in text:
        code = ord(ch)
        if code == 0x0A:
            cx = x
            cy += TEXT_LINE_H
            continue
        if code < TEXT_FIRST or code > TEXT_LAST:
            cx += TEXT_GLYPH_W
            continue
        index = code - TEXT_FIRST
        src = rl.Rectangle(float((index % TEXT_COLUMNS) * TEXT_GLYPH_W),
                           float((index // TEXT_COLUMNS) * TEXT_GLYPH_H),
                           float(TEXT_GLYPH_W), float(TEXT_GLYPH_H))
        dst = rl.Rectangle(float(cx), float(cy), float(TEXT_GLYPH_W),
                           float(TEXT_GLYPH_H))
        rl.DrawTexturePro(assets.font, src, dst, rl.Vector2(0, 0), 0.0, tint)
        cx += TEXT_GLYPH_W


def text_draw_page(assets, script: TextScript, index: int, page: int, x: int,
                   y: int, width: int, tint) -> int:
    if index < 0 or index >= script.count:
        return 0
    if page < 0 or page >= script.page_count[index]:
        return 0
    lines = script.pages[index][page]
    height = len(lines) * TEXT_LINE_H
    rl.DrawRectangle(x - 4, y - 4, width + 8, height + 8, rl.rgb(8, 8, 16, 210))
    rl.draw_rect_lines(x - 4, y - 4, width + 8, height + 8,
                          rl.rgb(200, 180, 120, 180))
    for i, line in enumerate(lines):
        text_draw_string(assets, line, x, y + i * TEXT_LINE_H, tint)
    return height
