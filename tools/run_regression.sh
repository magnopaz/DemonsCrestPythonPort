#!/bin/sh
# Single-command deterministic regression run for the native fan port.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec python3 "$ROOT/tools/run_regression.py" "$@"
