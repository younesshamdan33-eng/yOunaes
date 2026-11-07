#!/usr/bin/env python3
import os, sys, json, time, shutil, subprocess
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        sys.exit(1)
    prompt = sys.argv[1]
    kfile = Path.home() / ".kaggle" / "kaggle.json"
    username = json.load(open(kfile))["username"]
    job_id = int(time.time())
    kernel_slug = f"{username}/quality-stable-{job_id}"
    kdir = Path("var/cloud_job")
    kdir.mkdir(parents=True, exist_ok=True)

    gpu_script = f'''
import os, sys, subprocess, json
def log(msg): print(msg, flush=True)

# 1. تثبيت المكتبات (بدون basicsr أو RIFE)
log("⏳ [1/3] تثبيت المكتبات...")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--upgrade",
    "diffusers", "transformers", "accelerate", "sentencepiece",
    "imageio[ffmpeg]", "protobuf", "ftfy",
    "--use-deprecated=legacy-resolver"], capture_output=True)
log("✅ المكتبات جاهزة")

import torch
from diffusers import WanPipeline
from diffusers.utils import export_to_video
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# 2. تحميل النموذج
log("⏳ [2/3] تحميل Wan 2.1...")
pipe = WanPipeline.from_pretrained(
    "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
    torch_dtype=torch.float16
)
pipe.enable_model_cpu_offload()
if hasattr(pipe, "vae") and hasattr(pipe.vae, "enable_tiling"):
    pipe.vae.enable_tiling()
log("✅ تم تحميل النموذج")

# 3. التوليد بـ 50 خطوة (جودة أعلى)
log("🎬 [3/3] توليد الفيديو (50 خطوة)...")
negative_prompt = (
    "blurry, low quality, distorted, deformed, extra limbs, extra fingers, "
    "bad anatomy, bad hands, missing fingers, text, watermark, logo, "
    "static image, slideshow, freeze frame, duplicate frames, flicker, jitter, "
    "oversaturated, overexposed, underexposed, worst quality, jpeg artifacts"
)
video = pipe(
    prompt={repr(prompt)},
    negative_prompt=negative_prompt,
    height=480, width=704,
    num_frames=81,
    num_inference_steps=50,
    guidance_scale=6.0,
    generator=torch.Generator(device="cuda").manual_seed(42)
).frames[0]
export_to_video(video, "/kaggle/working/base_video.mp4", fps=16)
log("✅ تم التوليد")

# 4. رفع الدقة باستخدام ffmpeg فقط (مستقر)
log("🔍 رفع الدقة إلى 1080p باستخدام ffmpeg...")
subprocess.run([
    "ffmpeg", "-y", "-i", "/kaggle/working/base_video.mp4",
    "-vf", "scale=1920:1080:flags=lanczos,eq=contrast=1.05:saturation=1.1",
    "-c:v", "libx264", "-preset", "slow", "-crf", "18",
    "-pix_fmt", "yuv420p", "/kaggle/working/final.mp4"
], check=True)
log("SUCCESS")
'''
    (kdir / "script.py").write_text(gpu_script)
    meta = {"id": kernel_slug, "title": f"Quality Stable {job_id}", "code_file": "script.py", "language": "python", "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True, "dataset_sources": [], "competition_sources": [], "kernel_sources": []}
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))

    print("🚀 جاري الإرسال...")
    subprocess.run(["kaggle", "kernels", "push", "-p", str(kdir)], check=True)
    print(f"✅ تم الإرسال: https://www.kaggle.com/code/{kernel_slug}")
    print("⏳ ننتظر (10-15 دقيقة)...")

    while True:
        r = subprocess.run(["kaggle", "kernels", "status", kernel_slug], capture_output=True, text=True)
        status = r.stdout.strip()
        if "complete" in status.lower():
            print("✅ اكتمل!")
            break
        elif "error" in status.lower() or "fail" in status.lower():
            print(f"❌ فشل! افحص: https://www.kaggle.com/code/{kernel_slug}")
            sys.exit(1)
        time.sleep(20)

    out_dir = Path("var/generated_stable")
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["kaggle", "kernels", "output", kernel_slug, "-p", str(out_dir)])

    mp4s = list(out_dir.rglob("final.mp4")) + list(out_dir.rglob("base_video.mp4"))
    if not mp4s:
        print("❌ لا يوجد فيديو.")
        sys.exit(1)

    target = Path("static/quality_video.mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(mp4s[0], target)
    print(f"🎉 SUCCESS! الفيديو جاهز: http://127.0.0.1:8750/static/quality_video.mp4")

if __name__ == "__main__":
    main()
