#!/usr/bin/env bash
# Build the offline APU tools against the oracle's SPC700 + S-DSP cores.
#
#   build/spc_render  — render a .spc snapshot (and trace the SPC's PC stream)
#   build/apu_host    — boot the driver from the ROM's upload stream and render
#                       it, optionally replaying a CPU->APU command log
#
# These are dev-time asset/reference tools: they link snesrecomp's
# spc.c/dsp.c/apu.c (the same cores the behavioural oracle runs) plus
# tools/audio/spc_stubs.c, which no-ops the observability hooks. Nothing here
# ships in the game; the game loads only what these tools produce.
#
# Usage:
#   tools/audio/build_audio_tools.sh [--recomp DIR]
#
# RECOMP_DIR overrides the oracle checkout, like the tools/oracle/*.py tools.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RECOMP="${RECOMP_DIR:-$ROOT/../DemonsCrestSNESRecomp}"

while [ $# -gt 0 ]; do
  case "$1" in
    --recomp) RECOMP="$2"; shift 2 ;;
    *) echo "build_audio_tools: unknown option $1" >&2; exit 2 ;;
  esac
done

SRC="$RECOMP/snesrecomp/runner/src"
for f in "$SRC/snes/spc.c" "$SRC/snes/dsp.c" "$SRC/snes/apu.c"; do
  [ -f "$f" ] || { echo "build_audio_tools: missing oracle source $f" >&2; exit 1; }
done

mkdir -p "$ROOT/build"
CC="${CC:-gcc}"
COMMON=(-O2 -std=c11 -I"$ROOT/tools/audio" -I"$SRC" -I"$SRC/snes"
        "$SRC/snes/spc.c" "$SRC/snes/dsp.c" "$SRC/snes/apu.c"
        "$ROOT/tools/audio/spc_stubs.c" -lm)

$CC "${COMMON[@]}" -o "$ROOT/build/spc_render" "$ROOT/tools/audio/spc_render.c"
$CC "${COMMON[@]}" -o "$ROOT/build/apu_host"   "$ROOT/tools/audio/apu_host.c"
echo "build_audio_tools: $ROOT/build/spc_render $ROOT/build/apu_host"
