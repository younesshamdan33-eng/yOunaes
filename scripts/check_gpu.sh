#!/usr/bin/env bash
CW_HOME="${CW_HOME:-$HOME/cinema-worker}"
command -v nvidia-smi >/dev/null || { echo "NO NVIDIA GPU/driver on this machine"; exit 1; }
nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version --format=csv
echo "disk free:"; df -h "$CW_HOME" 2>/dev/null | tail -1 || df -h "$HOME" | tail -1
[ -x "$CW_HOME/venv/bin/python" ] && "$CW_HOME/venv/bin/python" -c 'import torch; print("torch", torch.__version__, "| CUDA usable:", torch.cuda.is_available())'
[ -x "$CW_HOME/venv/bin/python" ] && (cd "$CW_HOME" && PYTHONPATH="$CW_HOME" "$CW_HOME/venv/bin/python" -m worker.cli status)
