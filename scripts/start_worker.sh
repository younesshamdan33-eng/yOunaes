#!/usr/bin/env bash
set -euo pipefail
CW_HOME="${CW_HOME:-$HOME/cinema-worker}"
PORT="${CW_PORT:-8800}"
cd "$CW_HOME"
[ -f token ] || { echo "no token: run scripts/setup_worker.sh first"; exit 1; }
if pgrep -f "worker.server" >/dev/null; then echo "worker already running"; exit 0; fi
export CW_HOME CW_HOST=127.0.0.1 CW_PORT="$PORT" PYTHONPATH="$CW_HOME"
nohup "$CW_HOME/venv/bin/python" -m worker.server >> logs/worker.log 2>&1 &
sleep 3
if curl -s "http://127.0.0.1:$PORT/v1/health"; then echo; echo "worker started on 127.0.0.1:$PORT (reach it through an SSH tunnel)"; else echo "failed to start: tail -30 $CW_HOME/logs/worker.log"; exit 1; fi
