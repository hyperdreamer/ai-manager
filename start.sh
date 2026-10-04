#!/usr/bin/env bash
# ai-manager — launch desktop administration GUI
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "/home/bin/yesconda" ]; then
    source "/home/bin/yesconda"
elif command -v conda &>/dev/null; then
    eval "$(conda shell.bash hook)"
    conda activate daily || true
fi

export PYTHONPATH="$SCRIPT_DIR/src:${PYTHONPATH:-}"
exec python -m ai_manager.main "$@"
