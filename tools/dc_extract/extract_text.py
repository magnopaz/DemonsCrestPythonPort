#!/usr/bin/env python3
"""Extract the game's dialogue/UI text from the ROM.

The BG3 font is indexed by ASCII (a captured subscreen shows tiles
`0x46 0x49 0x52 0x45` = "FIRE"), so the script is stored as plain ASCII with
two control codes:

  * `0x01` line break inside a page
  * `0x02` page break (new box)
  * `0x5D` (`]`) terminates the last line of a page in most strings

This tool walks the ROM for printable runs that contain at least one control
code, splits them into pages/lines and writes `text_strings.json`:

    {"strings": [{"addr": "81:8DFA", "pages": [["I NEVER", ...], ...]}]}

The output is ROM-derived and git-ignored like the other generated assets.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--min-length", type=int, default=10)
    return ap.parse_args()


def to_snes(offset: int) -> str:
    return f"{(offset >> 15) | 0x80:02X}:{((offset & 0x7FFF) | 0x8000):04X}"


def is_text_byte(b: int) -> bool:
    return 0x20 <= b < 0x7F or b in (0x01, 0x02)


def decode_run(raw: bytes) -> list[list[str]] | None:
    pages: list[list[str]] = []
    lines: list[str] = []
    line = []
    saw_control = False
    for b in raw:
        if b == 0x01:
            saw_control = True
            lines.append("".join(line).rstrip())
            line = []
        elif b == 0x02:
            saw_control = True
            lines.append("".join(line).rstrip())
            line = []
            pages.append([l for l in lines if l])
            lines = []
        else:
            line.append(chr(b))
    lines.append("".join(line).rstrip())
    if lines:
        pages.append([l for l in lines if l])
    pages = [p for p in pages if p]
    if not saw_control or not pages:
        return None
    # Strip the `]` page terminator the original writes at the end of a page.
    cleaned = []
    for page in pages:
        page = [l for l in page if l.strip(" ]")]
        if page:
            for i, l in enumerate(page):
                page[i] = l.replace("]", "").rstrip()
            cleaned.append(page)
    return cleaned or None


def main() -> int:
    args = parse_args()
    data = args.rom.read_bytes()
    if len(data) == 0x200000 + 512:
        data = data[512:]
    strings = []
    i = 0
    n = len(data)
    while i < n:
        if not is_text_byte(data[i]):
            i += 1
            continue
        start = i
        while i < n and is_text_byte(data[i]):
            i += 1
        length = i - start
        if length < args.min_length:
            continue
        raw = data[start:i]
        pages = decode_run(raw)
        if not pages:
            continue
        strings.append({"addr": to_snes(start), "length": length,
                        "pages": pages})
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "text_strings.json").write_text(
        json.dumps({"strings": strings}, indent=1))
    print(f"extract_text: {len(strings)} strings -> "
          f"{args.out / 'text_strings.json'}")
    for s in strings[:10]:
        print(f"  {s['addr']}: {s['pages'][0][:2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
