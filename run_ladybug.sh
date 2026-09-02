#!/usr/bin/env bash
set -euo pipefail
WORKSPACE="${LADYBUG_WORKSPACE:-$HOME/.openclaw/workspace}"
exec python3 "$WORKSPACE/ladybug_main.py" --workspace "$WORKSPACE" "$@"
