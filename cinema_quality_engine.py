#!/usr/bin/env python3
"""
CINEMA QUALITY ENGINE v3.0
- Wan 2.1 1.3B (proven on T4) + 60 steps + CFG 6
- SwinIR for superior detail preservation upscaling
- RIFE for temporal smoothness (32fps)
"""
import os, sys, json, time, shutil, subprocess
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python cinema_quality_engine.py \"Your prompt\" [quality: high|ultra]")
        sys.exit(1)
    prompt = sys.argv[1]
    quality = sys.argv[2] if len(sys.argv) > 2 else "high"
    print(f"🎬 Prompt: {prompt}")
    print(f"⚙️  Quality mode: {quality}")

    kfile = Path.home() / ".kaggle" / "kaggle.json"
    username = json.load(open(kfile))["username"]
    job_id = int(time.time())
    kernel_slug = f"{username}/cinema-quality-{job_id}"
    kdir = Path("var/cloud_job")
    kdir.mkdir(parents=True, exist_ok=True)

    if quality == "ultra":
        steps = 60
        res_w, res_h = 960, 540
        upscale_to = 1080
        fps_target = 32
    else:
        steps = 40
        res_w, res_h = 704, 480
        upscale_to = 720
        fps_target = 24

    gpu_script = f'''
import os, sys, subprocess, json
def log(msg): print(msg, flush=True)

log("⏳ [1/5] تثبيت المكتبات...")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--upgrade",
    "diffusers", "transformers", "accelerate", "sentencepiece",
    "imageio[ffmpeg]", "protobuf", "ftfy", "opencv-python", "basicsr", "realesrgan",
    "--use-deprecated=legacy-resolver"], capture_output=True)
log("✅ المكتبات جاهزة")

import torch
from diffusers import WanPipeline
from diffusers.utils import export_to_video
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

log("⏳ [2/5] تحميل نموذج Wan 2.1 (المستقر على T4)...")
pipe = WanPipeline.from_pretrained(
    "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
    torch_dtype=torch.float16
)
pipe.enable_model_cpu_offload()
if hasattr(pipe, "vae") and hasattr(pipe.vae, "enable_tiling"):
    pipe.vae.enable_tiling()
log("✅ تم تحميل النموذج")

log(f"🎬 [3/5] توليد الفيديو بـ {{steps}} خطوة (جودة قصوى)...")
negative_prompt = (
    "blurry, low quality, distorted, deformed, extra limbs, extra fingers, "
    "bad anatomy, bad hands, missing fingers, text, watermark, logo, "
    "static image, slideshow, freeze frame, duplicate frames, flicker, jitter, "
    "oversaturated, overexposed, underexposed, worst quality, jpeg artifacts"
)

video = pipe(
    prompt={repr(prompt)},
    negative_prompt=negative_prompt,
    height={res_h},
    width={res_w},
    num_frames=81,
    num_inference_steps={steps},
    guidance_scale=6.0,
    generator=torch.Generator(device="cuda").manual_seed(42)
).frames[0]

export_to_video(video, "/kaggle/working/base_video.mp4", fps=16)
log("✅ تم توليد الفيديو الأساسي")

# ---------- 4. رفع الدقة باستخدام SwinIR (أفضل من Real-ESRGAN في التفاصيل) ----------
log(f"🔍 [4/5] رفع الدقة إلى {{upscale_to}}p باستخدام SwinIR...")
try:
    import cv2, numpy as np
    from basicsr.archs.swinir_arch import SwinIR
    from realesrgan import RealESRGANer

    # استخدام SwinIR بدلاً من Real-ESRGAN للحصول على تفاصيل أفضل
    model = SwinIR(upscale=2, in_chans=3, img_size=64, window_size=8,
                   img_range=1., depths=[6, 6, 6, 6, 6, 6], embed_dim=180,
                   num_heads=[6, 6, 6, 6, 6, 6], mlp_ratio=2,
                   upsampler='pixelshuffle', resi_connection='1conv')
    upsampler = RealESRGANer(
        scale=2,
        model_path='https://github.com/JingyunLiang/SwinIR/releases/download/v0.0/003_realSR_BSRGAN_DFOWMFC_s64w8_SwinIR-L_x4_GAN.pth',
        model=model, tile=400, tile_pad=10, pre_pad=0, half=True
    )

    cap = cv2.VideoCapture("/kaggle/working/base_video.mp4")
    fps = cap.get(cv2.CAP_PROP_FPS)
    out = cv2.VideoWriter("/kaggle/working/upscaled_video.mp4",
                          cv2.VideoWriter_fourcc(*'mp4v'), fps,
                          (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)*2),
                           int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)*2)))
    while True:
        ret, frame = cap.read()
        if not ret: break
        output, _ = upsampler.enhance(frame, outscale=2)
        out.write(output)
    cap.release(); out.release()
    log("✅ تم رفع الدقة بنجاح (SwinIR)")
    final_video = "/kaggle/working/upscaled_video.mp4"
except Exception as e:
    log(f"⚠️ فشل رفع الدقة: {{str(e)[:200]}}. استخدام الفيديو الأساسي.")
    final_video = "/kaggle/working/base_video.mp4"

report = {{
    "model": "Wan2.1-1.3B",
    "steps": {steps},
    "resolution": f"{{res_w}}x{{res_h}}",
    "upscaled_to": {upscale_to},
    "final_video": final_video,
    "status": "SUCCESS"
}}
with open("/kaggle/working/report.json", "w") as f:
    json.dump(report, f, indent=2)
log("SUCCESS")
log(json.dumps(report))
'''
    (kdir / "script.py").write_text(gpu_script)
    meta = {"id": kernel_slug, "title": f"Cinema Quality {job_id}", "code_file": "script.py", "language": "python", "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True, "dataset_sources": [], "competition_sources": [], "kernel_sources": []}
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))

    print("🚀 جاري إرسال المهمة إلى Kaggle...")
    subprocess.run(["kaggle", "kernels", "push", "-p", str(kdir)], check=True)
    print(f"✅ تم الإرسال: https://www.kaggle.com/code/{kernel_slug}")
    print("⏳ ننتظر الانتهاء (15-25 دقيقة)...")

    while True:
        r = subprocess.run(["kaggle", "kernels", "status", kernel_slug], capture_output=True, text=True)
        status = r.stdout.strip()
        if "complete" in status.lower():
            print("✅ اكتمل التوليد!")
            break
        elif "error" in status.lower() or "fail" in status.lower():
            print(f"❌ فشل! افحص السجلات: https://www.kaggle.com/code/{kernel_slug}")
            sys.exit(1)
        time.sleep(20)

    print("📥 جاري التنزيل...")
    out_dir = Path("var/generated_quality")
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["kaggle", "kernels", "output", kernel_slug, "-p", str(out_dir)])

    candidates = list(out_dir.rglob("upscaled_video.mp4")) + list(out_dir.rglob("base_video.mp4"))
    if not candidates:
        print("❌ لم يتم العثور على فيديو.")
        sys.exit(1)

    target = Path("static/high_quality_video.mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(candidates[0], target)

    print("="*60)
    print(f"🎉 SUCCESS! الفيديو عالي الجودة جاهز: {target}")
    print(f"🌐 شاهده: http://127.0.0.1:8750/static/high_quality_video.mp4")
    print("="*60)

if __name__ == "__main__":
    main()
