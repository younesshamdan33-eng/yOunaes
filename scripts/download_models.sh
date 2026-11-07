#!/usr/bin/env bash
# Downloads and verifies open model weights (about 32 GB for wan2.2-ti2v-5b). Free, but needs disk space and bandwidth.
set -euo pipefail
CW_HOME="${CW_HOME:-$HOME/cinema-worker}"
[ $# -ge 1 ] || { echo "usage: download_models.sh <model-id>   (see: python -m worker.cli status)"; exit 1; }
cd "$CW_HOME"
PYTHONPATH="$CW_HOME" "$CW_HOME/venv/bin/python" -m worker.cli download "$1"
