#!/usr/bin/env python3
import sys
import json
import time
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRAINER = ROOT / "cinema_trainer.py"

def run(args, check=True):
    print("+", " ".join(map(str, args)), flush=True)
    return subprocess.run(args, cwd=ROOT, check=check)

def main():
    if len(sys.argv) < 2:
        print("Usage: python cloud_gen.py CONFIG.json [timeout_hours]")
        raise SystemExit(2)

    config = Path(sys.argv[1]).expanduser()
    if not config.is_absolute():
        config = (ROOT / config).resolve()

    if not TRAINER.is_file():
        raise SystemExit("ERROR: cinema_trainer.py not found")
    if not config.is_file():
        raise SystemExit(f"ERROR: config not found: {config}")

    cfg = json.loads(config.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise SystemExit("ERROR: config must be a JSON object")

    stages = cfg.get("stages", [])
    if not stages:
        raise SystemExit(
            "ERROR: config.stages is empty. Set the intended training pipeline."
        )

    if "train" not in stages:
        raise SystemExit(
            "ERROR: config.stages does not include 'train'; refusing to launch."
        )

    if not cfg.get("data_dirs") and not cfg.get("resume_dirs"):
        print(
            "WARNING: data_dirs and resume_dirs are empty. "
            "Training may have no usable dataset or checkpoint.",
            flush=True
        )

    kfile = Path.home() / ".kaggle" / "kaggle.json"
    if not kfile.is_file():
        raise SystemExit("ERROR: Kaggle credentials file not found")

    credentials = json.loads(kfile.read_text(encoding="utf-8"))
    username = credentials.get("username")
    if not username:
        raise SystemExit("ERROR: Kaggle username missing in credentials")

    job_id = int(time.time())
    slug = f"{username}/cinema-training-{job_id}"
    timeout_hours = float(sys.argv[2]) if len(sys.argv) > 2 else 11.0

    print("Training stages:", " -> ".join(stages), flush=True)
    print("Model:", cfg.get("model_id", "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"))
    print("Kaggle kernel:", slug, flush=True)

    run([
        sys.executable, str(TRAINER),
        "--config", str(config),
        "kaggle-push", "--slug", slug
    ])

    print("Kernel submitted. Waiting for Kaggle...", flush=True)
    deadline = time.time() + timeout_hours * 3600
    terminal = False

    while time.time() < deadline:
        r = subprocess.run(
            ["kaggle", "kernels", "status", slug],
            cwd=ROOT, capture_output=True, text=True
        )
        status = (r.stdout + "\n" + r.stderr).strip()
        print("Kaggle status:", status[-1200:], flush=True)

        low = status.lower()
        if any(x in low for x in ("complete", "completed", "kernelworkerstatus.complete")):
            terminal = True
            break
        if any(x in low for x in ("error", "failed", "cancel", "kernelworkerstatus.error")):
            raise SystemExit(
                f"Kaggle training failed. Logs: https://www.kaggle.com/code/{slug}"
            )
        time.sleep(30)

    if not terminal:
        raise SystemExit(
            f"Timed out waiting for Kaggle. Kernel: https://www.kaggle.com/code/{slug}"
        )

    out = ROOT / "var" / "training_output" / slug.split("/")[-1]
    out.mkdir(parents=True, exist_ok=True)

    result = run([
        "kaggle", "kernels", "output", slug, "-p", str(out)
    ], check=False)

    if result.returncode != 0:
        raise SystemExit("Kaggle completed, but downloading outputs failed.")

    files = [x for x in out.rglob("*") if x.is_file()]
    print(f"Downloaded {len(files)} files to: {out}", flush=True)
    for f in files[:80]:
        print(f" - {f.relative_to(out)} ({f.stat().st_size} bytes)")

    print("Kaggle training job completed:", slug, flush=True)
    print("Review checkpoints and training reports before using the adapter.")

if __name__ == "__main__":
    main()
