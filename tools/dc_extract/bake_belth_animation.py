#!/usr/bin/env python3
"""Bake Belth's full pose set from the community boss sheet.

Belth is the reference case for ``docs/SPRITE_SHEET_EXTRACTION.md``: nine
measured bands, 32 frames, one entry in the authored species overlay.  The
band table now lives in ``bake_sheet_anim.py`` (``SPECS["belth"]``) so the
measured numbers exist once, and this command stays as the documented
shortcut:

    python tools/dc_extract/bake_belth_animation.py

It writes ``assets/authored/sprites/belth/belth_<index>_<animation>.png`` and
updates ``assets/authored/species_anim.json``.  Nothing is written to
``assets/generated``.

For a new sheet, copy the *spec* shape rather than this file: see
``SPECS`` in ``bake_sheet_anim.py`` and run

    python tools/dc_extract/bake_sheet_anim.py --only <target> --contact
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))

from bake_sheet_anim import SPECS, bake_target  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--contact", action="store_true")
    args = ap.parse_args()
    spec = SPECS["belth"]
    print(f"== belth: {spec['sheet']}")
    result = bake_target(spec, dry_run=args.dry_run, contact=args.contact)
    print(f"   {result['frames']} frames, {len(result['states'])} states")
    for problem in result["problems"]:
        print(f"   ! {problem}", file=sys.stderr)
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
