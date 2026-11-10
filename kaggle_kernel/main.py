import os, sys, time, json, hashlib, subprocess
from pathlib import Path

print("=== CINEMA AI — Autonomous Cloud Runner (Wan 2.1 T2V 1.3B) ===")
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "torch", "torchvision", "diffusers>=0.35.0", "transformers>=4.46.0",
    "accelerate", "peft", "safetensors", "imageio[ffmpeg]", "opencv-python-headless"], check=False)

import torch
from diffusers import WanPipeline, AutoencoderKLWan

out_dir = Path("/kaggle/working/outputs")
out_dir.mkdir(parents=True, exist_ok=True)

device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.float16 if device == "cuda" else torch.float32

print(f"Device: {device} | VRAM: {torch.cuda.get_device_properties(0).total_memory / (1024**3):.2f} GB" if device == "cuda" else "No GPU")

model_id = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
print("Loading model...")
vae = AutoencoderKLWan.from_pretrained(model_id, subfolder="vae", torch_dtype=dtype)
pipe = WanPipeline.from_pretrained(model_id, vae=vae, torch_dtype=dtype)
pipe.enable_model_cpu_offload()
if hasattr(pipe.vae, "enable_tiling"):
    pipe.vae.enable_tiling()

styles = [
    ("cinematic_realistic", "A lone explorer wearing a weathered coat walks across desert sand dunes at sunset, 35mm film", "cartoon, anime, blurry"),
    ("realistic_human", "A middle-aged man with natural skin texture and expressive eyes looking thoughtfully beside a window", "cartoon, deformed, waxy"),
    ("3d_cartoon", "A small cute orange fox character with large expressive eyes running playfully through a magical forest", "photorealistic, live action"),
    ("2d_cartoon", "A cheerful young adventurer with green jacket running along a hand-drawn fantasy forest trail", "photorealistic, 3d render"),
    ("anime", "A noble swordswoman with long dark hair drawing her blade as cherry blossom petals drift in the wind", "photorealistic, live action")
]

records = []
for style, prompt, neg in styles:
    print(f"Generating style: {style}...")
    t0 = time.time()
    generator = torch.Generator(device="cpu").manual_seed(42)
    res = pipe(prompt=prompt, negative_prompt=neg, height=480, width=832, num_frames=49, num_inference_steps=25, generator=generator)
    frames = res.frames[0] if isinstance(res.frames, list) else res.frames

    # Export to video
    import imageio
    import numpy as np
    out_file = out_dir / f"{style}_5s.mp4"
    imageio.mimsave(str(out_file), [np.array(f) for f in frames], fps=16)

    elapsed = round(time.time() - t0, 2)
    print(f"Saved: {out_file} in {elapsed}s")
    records.append({"style": style, "file": out_file.name, "elapsed": elapsed})

with open(out_dir / "report.json", "w") as f:
    json.dump(records, f, indent=2)

print("=== Generation Complete! ===")
