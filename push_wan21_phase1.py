import json, gzip, base64, tempfile, subprocess, time
from pathlib import Path

root = Path.cwd()
trainer = root / "cinema_trainer.py"
config = root / "phase1_quality_cfg.json"
credentials = Path.home() / ".kaggle" / "kaggle.json"

for p in (trainer, config, credentials):
    if not p.exists():
        raise SystemExit(f"Missing file: {p}")

username = json.loads(credentials.read_text())["username"]
slug = f"{username}/wan21-phase1-quality-v1"

source = base64.b64encode(
    gzip.compress(trainer.read_bytes())
).decode()
cfg = base64.b64encode(config.read_bytes()).decode()

wrapper = r'''
import os, sys, subprocess, base64, gzip

W = "/kaggle/working"
open(W + "/cinema_trainer.py", "wb").write(
    gzip.decompress(base64.b64decode("__SOURCE__"))
)
open(W + "/cinema_config.json", "wb").write(
    base64.b64decode("__CONFIG__")
)

def install(*packages):
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "--quiet", "--no-deps", *packages
    ])

print("Installing pinned packages...", flush=True)

install(
    "diffusers==0.33.1",
    "peft==0.17.0",
    "transformers==4.46.3",
    "huggingface_hub==0.34.4",
    "tokenizers==0.20.3",
    "accelerate==1.10.1"
)
install("sentencepiece", "ftfy", "imageio-ffmpeg")

print("Checking imports...", flush=True)
import torch
import diffusers, peft, transformers
from diffusers import WanPipeline, WanTransformer3DModel
from peft import LoraConfig, get_peft_model

print("diffusers:", diffusers.__version__, flush=True)
print("peft:", peft.__version__, flush=True)
print("transformers:", transformers.__version__, flush=True)
print("torch:", torch.__version__, flush=True)

assert torch.cuda.is_available(), "CUDA GPU unavailable"
print("GPU:", torch.cuda.get_device_name(0), flush=True)
print("VRAM GiB:",
      round(torch.cuda.get_device_properties(0).total_memory / 2**30, 2),
      flush=True)

print("Starting Wan 2.1 BASELINE only...", flush=True)
sys.exit(subprocess.call([
    sys.executable,
    W + "/cinema_trainer.py",
    "--config", W + "/cinema_config.json",
    "baseline"
]))
'''

wrapper = wrapper.replace("__SOURCE__", source).replace("__CONFIG__", cfg)

folder = Path(tempfile.mkdtemp(prefix="wan21_baseline_"))
(folder / "run.py").write_text(wrapper)

metadata = {
    "id": slug,
    "title": "Wan21 Phase1 Quality Test",
    "code_file": "run.py",
    "language": "python",
    "kernel_type": "script",
    "is_private": "true",
    "enable_gpu": "true",
    "enable_internet": "true",
    "dataset_sources": [],
    "kernel_sources": [],
    "competition_sources": []
}
(folder / "kernel-metadata.json").write_text(
    json.dumps(metadata, indent=2)
)

print("Uploading:", slug, flush=True)
subprocess.run(
    ["kaggle", "kernels", "push", "-p", str(folder)],
    check=True
)
print("\nUPLOAD SUCCESS")
print("SLUG:", slug)
print("URL: https://www.kaggle.com/code/" + slug)
