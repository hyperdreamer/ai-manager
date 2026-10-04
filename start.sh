#!/usr/bin/env bash
# ai-manager — launch desktop administration GUI
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$SCRIPT_DIR"

export QT_XCB_GL_INTEGRATION="${QT_XCB_GL_INTEGRATION:-none}"

if [ -f "/home/bin/yesconda" ]; then
    source "/home/bin/yesconda"
elif command -v conda &>/dev/null; then
    eval "$(conda shell.bash hook)"
    conda activate daily || true
fi

export PYTHONPATH="$SCRIPT_DIR/src:${PYTHONPATH:-}"
exec python -m ai_manager.main "$@"
