#!/usr/bin/env python3
"""Turn captured APU commands into the port's sound-effect assets.

`capture_sfx.py` records the difference between a run that presses buttons and
one that does not, so each file is the console's own effect with the music
cancelled.  This tool maps the command ids it captured to the names the port
loads (`<assets>/audio/sfx_<name>.wav`) and copies them into place.

Only the effects whose trigger is unambiguous are mapped.  A command with no
known meaning is left in `captures/audio/sfx/` for the next session instead of
being guessed into the port, and the port keeps its synthesised stand-in for
that id.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# cmd id -> port effect name.  0x01 is the byte the game writes to the APU in
# the frame the player jumps (tools/audio/input_probe.py shows it on its own
# when only B is pressed).
COMMANDS = {
    0x01: "jump",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--captures", type=Path,
                    default=ROOT / "captures" / "audio" / "sfx")
    ap.add_argument("--outdir", type=Path,
                    default=ROOT / "assets" / "generated" / "audio")
    args = ap.parse_args()

    manifest_path = args.captures / "sfx_manifest.json"
    if not manifest_path.is_file():
        print(f"make_sfx_asset: no captures at {manifest_path}", file=sys.stderr)
        return 77
    caps = json.loads(manifest_path.read_text())
    effects = caps.get("effects", {})
    args.outdir.mkdir(parents=True, exist_ok=True)
    written = []
    for cmd, name in sorted(COMMANDS.items()):
        key = f"cmd{cmd:02x}"
        entry = effects.get(key)
        if not entry:
            print(f"make_sfx_asset: no capture for {key} ({name}); "
                  "the port keeps the synthesised fallback", file=sys.stderr)
            continue
        src = args.captures / entry["file"]
        if not src.is_file():
            print(f"make_sfx_asset: missing {src}", file=sys.stderr)
            continue
        dst = args.outdir / f"sfx_{name}.wav"
        shutil.copyfile(src, dst)
        written.append({"name": name, "cmd": cmd, "file": dst.name,
                        "seconds": entry["seconds"],
                        "source": entry.get("source", "")})
        print(f"sfx_{name}.wav <- {key} ({entry['seconds']} s)")
    out = args.outdir / "sfx_manifest.json"
    out.write_text(json.dumps({"effects": written}, indent=1))
    print(f"make_sfx_asset: {len(written)} effect(s) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
