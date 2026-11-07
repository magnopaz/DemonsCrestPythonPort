#!/usr/bin/env python3
"""Turn captured APU commands into the port's sound-effect assets.

`capture_sfx.py` records the difference between a run that presses buttons and
one that does not, so each file is the console's own effect with the music
cancelled.  This tool maps the command ids to the names the port loads
(`<assets>/audio/sfx_<name>.wav`) and copies them into place.

Only effects with a *proven* trigger are mapped; the proof is written into the
manifest next to the asset.  A command with no proven meaning stays in
`captures/audio/` for the next session instead of being guessed into the port,
which would replace an honest stand-in with the wrong sound.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# cmd id -> (port effect name, how the trigger was proven)
COMMANDS = {
    0x01: ("jump",
           "pressing B alone in the cemetery, the slope, the colosseum and the "
           "Hippogriff fight sends exactly this byte, and nothing else does"),
    0x1c: ("pickup",
           "walking right into the reservoir's item sends it; walking left, "
           "standing still, and only 6 frames of walking right do not"),
}


def load_effects(dirs: list[Path]) -> dict[str, dict]:
    effects: dict[str, dict] = {}
    for directory in dirs:
        path = directory / "sfx_manifest.json"
        if not path.is_file():
            continue
        for key, entry in json.loads(path.read_text()).get("effects", {}).items():
            effects.setdefault(key, entry)
    return effects


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--captures", type=Path, action="append", default=None,
                    help="capture directory (repeatable); default: the two "
                         "audio/sfx* dirs the probes write")
    ap.add_argument("--outdir", type=Path,
                    default=ROOT / "assets" / "generated" / "audio")
    args = ap.parse_args()

    dirs = args.captures or [ROOT / "captures" / "audio" / "sfx",
                             ROOT / "captures" / "audio" / "sfx_pickup"]
    effects = load_effects(dirs)
    if not effects:
        print("make_sfx_asset: no captured effects", file=sys.stderr)
        return 77

    args.outdir.mkdir(parents=True, exist_ok=True)
    written = []
    for cmd, (name, proof) in sorted(COMMANDS.items()):
        key = f"cmd{cmd:02x}"
        entry = effects.get(key)
        if not entry:
            print(f"make_sfx_asset: no capture for {key} ({name}); "
                  "the port keeps the synthesised fallback", file=sys.stderr)
            continue
        src = None
        for directory in dirs:
            cand = directory / entry["file"]
            if cand.is_file():
                src = cand
                break
        if src is None:
            print(f"make_sfx_asset: missing {entry['file']}", file=sys.stderr)
            continue
        dst = args.outdir / f"sfx_{name}.wav"
        shutil.copyfile(src, dst)
        written.append({"name": name, "cmd": cmd, "file": dst.name,
                        "seconds": entry["seconds"], "proof": proof,
                        "source": entry.get("source", "")})
        print(f"sfx_{name}.wav <- {key} ({entry['seconds']} s)")

    out = args.outdir / "sfx_manifest.json"
    out.write_text(json.dumps({"effects": written}, indent=1))
    print(f"make_sfx_asset: {len(written)} effect(s) -> {out}")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
