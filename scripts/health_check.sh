#!/usr/bin/env bash
CW_HOME="${CW_HOME:-$HOME/cinema-worker}"
PORT="${CW_PORT:-8800}"
H=$(curl -s -m 8 "http://127.0.0.1:$PORT/v1/health") || { echo "worker NOT reachable on 127.0.0.1:$PORT"; exit 1; }
echo "health: $H"
if [ -f "$CW_HOME/token" ]; then
  curl -s -m 15 -H "Authorization: Bearer $(cat "$CW_HOME/token")" "http://127.0.0.1:$PORT/v1/capabilities" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("gpus:", [g["name"] for g in d["gpus"]]); print("queue:", d["queue"]); [print(" ", k, "ready" if v["ready"] else "NOT ready: " + "; ".join(v["reasons"])) for k, v in d["models"].items()]'
fi
