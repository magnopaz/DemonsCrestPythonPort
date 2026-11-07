#!/bin/sh
# Start the Demon's Crest content toolkit from anywhere in the checkout.
cd "$(dirname "$0")/../.." || exit 1
if [ -x ".venv/bin/python" ]; then
  exec ".venv/bin/python" "tools/editor/server.py" "$@"
fi
exec python3 "tools/editor/server.py" "$@"
