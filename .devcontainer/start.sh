#!/usr/bin/env bash
cd "$(dirname "$0")/.."
mkdir -p var/logs
export CINEMA_ROOT="$PWD" PYTHONPATH="$PWD" CINEMA_ALLOW_HOST_SUFFIX=".app.github.dev"
pkill -f "cinema_core.server" 2>/dev/null || true
nohup python -m cinema_core.server > var/logs/codespace-server.log 2>&1 &
sleep 3
curl -s http://127.0.0.1:8750/health || echo "server did not start: see var/logs/codespace-server.log"
