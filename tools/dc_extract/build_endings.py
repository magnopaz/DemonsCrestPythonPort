#!/usr/bin/env python3
"""Build `endings.json`: the four Demon's Crest endings.

The narration lines are **transcribed from reference ending screenshots**
(vgmuseum Bad/Normal/Good/True ending pages) because the ending narration is not
stored as plain ASCII in the ROM (the battle dialogue is: `$BE:B947..C128`).
The epilogue uses the ROM string at `$81:8DF2` ("I NEVER EXPECTED THAT PHALANX
WOULD BE DEFEATED...") which is the ending portrait text.

Variant selection in the port (crest count among the five power crests):
  0 -> bad, 1-2 -> normal, 3-4 -> good, 5 -> true.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ENDINGS = {
    "bad": {
        "title": "BAD ENDING",
        "lines": [
            "TAKEN BY SURPRISE, THE MIGHTY PHALANX WAS",
            "DESTROYED BY FIREBRAND BEFORE HE COULD SUMMON",
            "THE POWER OF INFINITY.",
            "HIS REVENGE COMPLETE, FIREBRAND LEFT FOR",
            "THE DEMON REALM TO REST HIS WOUNDED WINGS.",
        ],
        "epilogue": 0,
    },
    "normal": {
        "title": "NORMAL ENDING",
        "lines": [
            "FACING CERTAIN DEATH AT THE HANDS OF FIREBRAND,",
            "PHALANX SEALED HIMSELF INTO THE CREST OF HEAVEN",
            "FOREVER.",
        ],
        "epilogue": -1,
    },
    "good": {
        "title": "GOOD ENDING",
        "lines": [
            "PHALANX ALMOST SUMMONED THE POWER OF INFINITY,",
            "BUT HE WAS DESTROYED BY THE POWER OF FIREBRAND",
            "BEFORE IT CAME UNDER HIS CONTROL.",
            "WITH ALL THE CRESTS SAFELY IN HIS POSSESSION,",
            "FIREBRAND MUSED OVER THE POWER AT HIS COMMAND.",
            "IT WOULD BE A SIMPLE THING TO USE IT TO REIGN",
            "SUPREME... BUT IN THE END, FIREBRAND DECIDED",
            "THAT HIS DESTINY LIES ELSEWHERE...",
        ],
        "epilogue": -1,
    },
    "true": {
        "title": "TRUE ENDING",
        "lines": [
            "FIREBRAND SLEW THE DARK DEMON",
            "WHO HAD LURKED DEEP WITHIN THE HUMAN WORLD.",
            "REALIZING THAT HIS TRUE POWER WAS NOT DERIVED",
            "FROM THE CRESTS.",
            "FIREBRAND DISPOSED OF ALL THE CRESTS",
            "AND SET FORTH FOR THE DEMON REALM.",
            "THERE HE HOPED TO FIND A TRUE WARRIOR.",
            "A WARRIOR WITH WHOM HE COULD ONCE AGAIN TASTE",
            "GLORY OF BATTLE!",
        ],
        "epilogue": -1,
    },
}


def wrap_lines(lines: list[str], width: int = 30) -> list[str]:
    """Word-wrap narration to the 8px font's usable width (30 chars)."""
    out: list[str] = []
    for line in lines:
        words = line.split()
        cur = ""
        for w in words:
            if not cur:
                cur = w
            elif len(cur) + 1 + len(w) <= width:
                cur += " " + w
            else:
                out.append(cur)
                cur = w
        if cur:
            out.append(cur)
    return out


# The bad ending's pages, transcribed from the `captures/badend` recording
# (2026-11-10), which shows the text on screen one page at a time: the console
# does NOT use the port's 30-char wrap, and the page breaks fall on sentence
# boundaries.  `page_frames` are the measured windows (docs/ENDINGS.md).
BAD_PAGES = [
    ["TAKEN BY SURPRISE,", "THE MIGHTY PHALANX WAS"],
    ["DESTROYED BY FIREBRAND", "BEFORE HE COULD SUMMON"],
    ["THE POWER OF INFINITY."],
    ["HIS REVENGE COMPLETE,", "FIREBRAND LEFT FOR"],
    ["THE DEMON REALM TO REST", "HIS WOUNDED WINGS."],
]
BAD_PAGE_FRAMES = [610, 430, 450, 600, 490]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "generated")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for spec in ENDINGS.values():
        spec["lines"] = wrap_lines(spec["lines"])
        # Two wrapped lines per page, except the bad ending, whose pages were
        # read off the capture (line breaks and sentence breaks are the game's).
        spec["pages"] = [spec["lines"][i:i + 2]
                         for i in range(0, len(spec["lines"]), 2)]
    ENDINGS["bad"]["pages"] = BAD_PAGES
    ENDINGS["bad"]["page_frames"] = BAD_PAGE_FRAMES
    doc = {
        "source": "ending narration transcribed from vgmuseum reference "
                  "screenshots; bad-ending pages from captures/badend; "
                  "epilogue = ROM text $81:8DF2",
        "order": ["bad", "normal", "good", "true"],
        "endings": ENDINGS,
    }
    (args.out / "endings.json").write_text(json.dumps(doc, indent=1))
    print(f"wrote {args.out / 'endings.json'} "
          f"({sum(len(v['lines']) for v in ENDINGS.values())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
