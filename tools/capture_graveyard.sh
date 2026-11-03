#!/usr/bin/env bash
# Capture the graveyard reference frame from the recompilation build.
#
# Usage:
#   RECOMP_DIR=/path/to/DemonsCrestSNESRecomp \
#   ROM="/path/to/Demon's Crest (USA).sfc" \
#   ./tools/capture_graveyard.sh
#
# The recomp build must be a trace build (SNESRECOMP_ENABLE_TRACE=ON), which
# is what build-trace/ is. The script writes stage_start and stage_600 dumps;
# the extractor consumes stage_600.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RECOMP_DIR="${RECOMP_DIR:-$ROOT/../DemonsCrestSNESRecomp}"
DEFAULT_ROM="projetos/opencode/roms/Demon's Crest (USA).sfc"
ROM="${ROM:-$DEFAULT_ROM}"
OUT="${OUT:-$ROOT/captures/graveyard}"
BIN="${RECOMP_BIN:-$RECOMP_DIR/build-trace/DemonsCrestSNESRecomp}"

if [[ ! -x "$BIN" ]]; then
  echo "capture: missing trace build: $BIN" >&2
  echo "capture: set RECOMP_DIR or RECOMP_BIN" >&2
  exit 1
fi
if [[ ! -f "$ROM" ]]; then
  echo "capture: missing ROM: $ROM" >&2
  exit 1
fi

mkdir -p "$OUT"
cd "$RECOMP_DIR"
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
SNESRECOMP_DUMP_DIR="$OUT" \
"$BIN" "$ROM" --script scripts/routes/gameplay.script

echo "capture: wrote $OUT/stage_600.*"
