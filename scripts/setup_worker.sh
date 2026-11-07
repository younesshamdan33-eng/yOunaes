#!/usr/bin/env bash
# Run ON THE GPU SERVER (Linux + NVIDIA). Installs the Cinema worker. It never buys, creates or exposes anything.
set -euo pipefail
CW_HOME="${CW_HOME:-$HOME/cinema-worker}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TORCH_INDEX="${TORCH_INDEX:-https://download.pytorch.org/whl/cu126}"
say() { printf '%s\n' "$*"; }
fail() { say "FAIL: $*"; exit 1; }
[ "$(uname -s)" = "Linux" ] || fail "Linux is required"
command -v nvidia-smi >/dev/null || fail "nvidia-smi not found: no NVIDIA driver/GPU here, so real inference cannot run on this machine"
say "GPU:"; nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
command -v python3 >/dev/null || fail "python3 is missing"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || fail "python >= 3.10 is required"
python3 -c 'import venv' 2>/dev/null || fail "python venv module missing (sudo apt-get install -y python3-venv)"
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null || fail "ffmpeg/ffprobe missing (sudo apt-get install -y ffmpeg)"
free_gb=$(df -Pk "$HOME" | awk 'NR==2{printf "%d", $4/1048576}')
[ "$free_gb" -ge 50 ] || fail "only ${free_gb} GB free; the Wan 2.2 weights alone are about 32 GB"
mkdir -p "$CW_HOME"/models "$CW_HOME"/jobs "$CW_HOME"/logs
rm -rf "$CW_HOME/worker" "$CW_HOME/scripts"
cp -r "$HERE/worker" "$HERE/scripts" "$CW_HOME/"
python3 -m venv "$CW_HOME/venv"
"$CW_HOME/venv/bin/pip" install --quiet --upgrade pip
"$CW_HOME/venv/bin/pip" install --quiet flask huggingface_hub
"$CW_HOME/venv/bin/pip" install --quiet torch torchvision --index-url "$TORCH_INDEX"
"$CW_HOME/venv/bin/pip" install --quiet diffusers transformers accelerate sentencepiece ftfy imageio imageio-ffmpeg
if [ ! -f "$CW_HOME/token" ]; then
  (umask 077; head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$CW_HOME/token")
  say "A new worker token was written to $CW_HOME/token (mode 600). It is never printed here."
fi
chmod 600 "$CW_HOME/token"
"$CW_HOME/venv/bin/python" -c 'import torch; print("torch", torch.__version__, "cuda available:", torch.cuda.is_available())'
say "OK. Next: bash $CW_HOME/scripts/download_models.sh wan2.2-ti2v-5b   then   bash $CW_HOME/scripts/start_worker.sh"
