# Cinema worker (GPU server)

Runs open video models on a Linux machine with an NVIDIA GPU. The phone only controls it.

1. On the GPU server: `bash scripts/setup_worker.sh`, then `bash scripts/download_models.sh wan2.2-ti2v-5b` (about 32 GB), then `bash scripts/start_worker.sh`.
2. The worker listens on 127.0.0.1:8800 only. Reach it through an SSH tunnel (`ssh -N -L 8800:127.0.0.1:8800 user@server`).
3. `bash scripts/health_check.sh` shows which models are ready and, if not, exactly why.
4. `python -m worker.cli selftest --yes` runs one real generation and validates the video. Until it prints REAL GPU GENERATION VERIFIED, nothing here is proven on a GPU.

Models: wan2.2-ti2v-5b (Apache-2.0, 24 GB-class GPU, verified from its model card), ltx-video (figures unverified). FramePack, Stable Video Infinity and LTX-2 are listed as planned only.
