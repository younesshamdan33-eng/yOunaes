# =====================================================================
# CINEMA QUALITY PIPELINE — Kaggle T4 (16GB)
# Wan2.1-1.3B  ->  RIFE (16->32fps)  ->  Real-ESRGAN (1080p)  ->  Grade
# شغّله في Kaggle: Accelerator = GPU T4 ، Internet = ON
# =====================================================================
# خلية التثبيت (نفّذها مرة واحدة):
# !pip install -q -U diffusers transformers accelerate ftfy imageio imageio-ffmpeg opencv-python-headless
# !pip install -q realesrgan basicsr facexlib gfpgan

import os, sys, gc, time, glob, shutil, zipfile, subprocess, traceback, argparse
import urllib.request, importlib, importlib.util
import numpy as np
import torch
import torch.nn.functional as F
import cv2

# ============================ الإعدادات ==============================
CFG = dict(
    model_id="Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
    work_dir="/kaggle/working",
    # --- المرحلة 1: التوليد ---
    width=832, height=480,        # الدقة الأصلية للنموذج (لا تغيّرها)
    num_frames=81,                # 81 = ~5 ثوانٍ عند 16fps
    steps=40,                     # 30 سريع / 40-50 جودة أعلى
    guidance=5.0,                 # 5-6 ؛ الأعلى = التزام أكبر بالبرومبت لكن تشبّع
    flow_shift=5.0,               # 3.0 للثبات ؛ 5-8 تفاصيل وحركة أكثر
    candidates=1,                 # >1 = يولّد عدة بذور ويختار الأفضل (أبطأ)
    base_fps=16,
    # --- المرحلة 2: RIFE ---
    rife_multi=2,                 # 16 -> 32 fps
    # --- المرحلة 3: رفع الدقة ---
    upscale_style="photo",        # "photo" أو "anime"
    tile=256,                     # قلّله إلى 128 إذا ظهر OOM
    out_w=1920, out_h=1080,
    out_fps=32,
    crf=14,
    grain=4,                      # حبيبات فيلم خفيفة تخفي مظهر "البلاستيك" (0 = إيقاف)
)

# ======================= قوالب البرومبت ===============================
# الصيغة: {subject} = الموضوع + الحدث + المكان
PROMPTS = {
    "cinematic": dict(
        positive=("{subject}, cinematic film still, shot on ARRI Alexa 65 with anamorphic lens, "
                  "shallow depth of field, volumetric lighting, soft rim light, natural skin texture, "
                  "subtle film grain, teal and orange color grading, high dynamic range, "
                  "slow smooth dolly camera movement, realistic motion, ultra detailed, sharp focus"),
        negative=("blurry, low quality, low resolution, jpeg artifacts, overexposed, washed out, static, "
                  "deformed, distorted face, extra fingers, bad hands, bad anatomy, watermark, text, "
                  "subtitles, logo, cartoon, plastic skin, flickering, morphing, duplicate, cropped, worst quality"),
        upscale="photo"),
    "cartoon3d": dict(
        positive=("{subject}, stylized 3D animated feature film, expressive characters, "
                  "soft global illumination, subsurface scattering, vibrant colors, clean shading, "
                  "rich textures, octane render, depth of field, smooth fluid animation, highly detailed"),
        negative=("photorealistic, live action, blurry, low quality, flat lighting, deformed, bad anatomy, "
                  "extra limbs, watermark, text, logo, flickering, morphing, jerky motion, worst quality"),
        upscale="photo"),
    "anime": dict(
        positive=("{subject}, high quality anime, cel shading, clean line art, vibrant colors, "
                  "detailed painted background, dynamic camera, fluid key animation, soft bloom, "
                  "studio quality, sharp details"),
        negative=("photorealistic, 3d render, blurry, low quality, bad anatomy, extra fingers, "
                  "deformed, inconsistent lines, watermark, text, logo, flickering, morphing, worst quality"),
        upscale="anime"),
}

# ============================ أدوات ==================================
def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def free_mem():
    """تنظيف ذاكرة GPU/CPU بين المراحل."""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

def sh(cmd):
    subprocess.run(cmd, shell=True, check=True)

def download(url, dst):
    if not os.path.exists(dst):
        log(f"تحميل: {url}")
        urllib.request.urlretrieve(url, dst)
    return dst

def write_mp4(frames, path, fps):
    import imageio
    imageio.mimsave(path, frames, fps=fps, codec="libx264", quality=9, macro_block_size=1)

# ===================== المرحلة 1: التوليد الأساسي =====================
def score_video(frames):
    """تقييم تقريبي: حدّة عالية وثبات زمني (تقليل الوميض) = أفضل."""
    g = [cv2.cvtColor(f, cv2.COLOR_RGB2GRAY) for f in frames[::4]]
    sharp = np.mean([cv2.Laplacian(x, cv2.CV_64F).var() for x in g])
    diffs = [np.abs(g[i + 1].astype(np.float32) - g[i]).mean() for i in range(len(g) - 1)]
    flicker = float(np.std(diffs)) if diffs else 0
    return sharp / (1 + 0.5 * flicker)

def stage1_generate(prompt, negative, seed):
    from diffusers import AutoencoderKLWan, WanPipeline, UniPCMultistepScheduler
    pipe = None
    try:
        log("المرحلة 1: تحميل Wan2.1...")
        vae = AutoencoderKLWan.from_pretrained(CFG["model_id"], subfolder="vae", torch_dtype=torch.float32)
        pipe = WanPipeline.from_pretrained(CFG["model_id"], vae=vae, torch_dtype=torch.bfloat16)
        pipe.scheduler = UniPCMultistepScheduler.from_config(
            pipe.scheduler.config, flow_shift=CFG["flow_shift"])
        pipe.enable_model_cpu_offload()          # يحفظ VRAM على T4
        try: pipe.vae.enable_tiling()
        except Exception: pass

        best, best_score = None, -1
        for i in range(CFG["candidates"]):
            s = seed + i
            log(f"توليد المرشح {i+1}/{CFG['candidates']} (seed={s})")
            try:
                out = pipe(prompt=prompt, negative_prompt=negative,
                           height=CFG["height"], width=CFG["width"],
                           num_frames=CFG["num_frames"],
                           guidance_scale=CFG["guidance"],
                           num_inference_steps=CFG["steps"],
                           generator=torch.Generator("cpu").manual_seed(s),
                           output_type="np").frames[0]
                frames = [(f * 255).clip(0, 255).astype(np.uint8) for f in out]
                sc = score_video(frames)
                log(f"  score={sc:.2f}")
                if sc > best_score: best, best_score = frames, sc
            except torch.cuda.OutOfMemoryError:
                log("OOM: قلّل num_frames أو steps"); free_mem()
            finally:
                free_mem()
        return best
    finally:
        del pipe; free_mem()

# ===================== المرحلة 2: RIFE =================================
def setup_rife():
    repo = os.path.join(CFG["work_dir"], "Practical-RIFE")
    if not os.path.exists(repo):
        sh(f"git clone -q https://github.com/hzwer/Practical-RIFE {repo}")
    tl = os.path.join(repo, "train_log"); os.makedirs(tl, exist_ok=True)
    if not os.path.exists(os.path.join(tl, "flownet.pkl")):
        z = download("https://huggingface.co/hzwer/RIFE/resolve/main/RIFEv4.26_0921.zip", "/tmp/rife.zip")
        with zipfile.ZipFile(z) as zf: zf.extractall("/tmp/rife_x")
        for name in ("flownet.pkl", "RIFE_HDv3.py", "IFNet_HDv3.py"):
            hit = glob.glob(f"/tmp/rife_x/**/{name}", recursive=True)
            if hit: shutil.copy(hit[0], tl)
    open(os.path.join(tl, "__init__.py"), "a").close()
    if repo not in sys.path: sys.path.insert(0, repo)
    return tl

def stage2_interpolate(frames):
    model = None
    try:
        log("المرحلة 2: RIFE (مضاعفة الإطارات)...")
        tl = setup_rife()
        from train_log.RIFE_HDv3 import Model
        dev = torch.device("cuda")
        model = Model(); model.load_model(tl, -1); model.eval(); model.device()

        h, w, _ = frames[0].shape
        ph, pw = (-h) % 128, (-w) % 128
        def prep(f):
            t = torch.from_numpy(f.transpose(2, 0, 1)).float().div(255).unsqueeze(0).to(dev)
            return F.pad(t, (0, pw, 0, ph))
        def post(t):
            return (t[0, :, :h, :w].clamp(0, 1) * 255).byte().cpu().numpy().transpose(1, 2, 0)

        def mid(a, b):
            try: return model.inference(a, b, 0.5, 1.0)
            except TypeError: return model.inference(a, b, 1.0)

        def double(fr):
            out = []
            with torch.no_grad():
                for i in range(len(fr) - 1):
                    a, b = prep(fr[i]), prep(fr[i + 1])
                    out += [fr[i], post(mid(a, b))]
                out.append(fr[-1])
            return out

        out = frames
        for _ in range({2: 1, 4: 2}.get(CFG["rife_multi"], 1)):
            out = double(out)
        log(f"  {len(frames)} -> {len(out)} إطار")
        return out
    except Exception:
        traceback.print_exc(); log("فشل RIFE — سأكمل بدون مضاعفة")
        return frames
    finally:
        del model; free_mem()

# ===================== المرحلة 3: رفع الدقة + التدرج ====================
def patch_basicsr():
    """إصلاح تعارض basicsr مع torchvision الحديث."""
    importlib.invalidate_caches()
    spec = importlib.util.find_spec("basicsr")
    if not spec: return
    p = os.path.join(list(spec.submodule_search_locations)[0], "data", "degradations.py")
    if os.path.exists(p):
        s = open(p).read()
        if "functional_tensor" in s:
            open(p, "w").write(s.replace("torchvision.transforms.functional_tensor",
                                         "torchvision.transforms.functional"))

def make_upsampler(style, tile):
    patch_basicsr()
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer
    base = "https://github.com/xinntao/Real-ESRGAN/releases/download"
    if style == "anime":
        url = f"{base}/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"
        net = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=6, num_grow_ch=32, scale=4)
    else:
        url = f"{base}/v0.1.0/RealESRGAN_x4plus.pth"
        net = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
    path = download(url, os.path.join("/tmp", os.path.basename(url)))
    return RealESRGANer(scale=4, model_path=path, model=net, tile=tile,
                        tile_pad=10, pre_pad=0, half=True, device="cuda")

def stage3_upscale_encode(frames, out_path):
    up = None
    try:
        log("المرحلة 3: رفع الدقة إلى 1080p + تدرج لوني...")
        tile = CFG["tile"]
        up = make_upsampler(CFG["upscale_style"], tile)
        scale = CFG["out_h"] / frames[0].shape[0]      # 2.25 → 1872x1080 ثم قص/تحجيم
        vf = (f"scale={CFG['out_w']}:{CFG['out_h']}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={CFG['out_w']}:{CFG['out_h']},eq=contrast=1.05:saturation=1.07,"
              f"unsharp=5:5:0.35:5:5:0.0")
        if CFG["grain"]: vf += f",noise=alls={CFG['grain']}:allf=t"

        proc = None
        for i, fr in enumerate(frames):
            bgr = cv2.cvtColor(fr, cv2.COLOR_RGB2BGR)
            try:
                big, _ = up.enhance(bgr, outscale=scale)
            except torch.cuda.OutOfMemoryError:
                free_mem(); tile = max(64, tile // 2); log(f"OOM → tile={tile}")
                up.tile_size = tile
                big, _ = up.enhance(bgr, outscale=scale)
            if proc is None:
                hh, ww = big.shape[:2]
                proc = subprocess.Popen(
                    ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                     "-s", f"{ww}x{hh}", "-r", str(CFG["out_fps"]), "-i", "-",
                     "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", str(CFG["crf"]),
                     "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path],
                    stdin=subprocess.PIPE)
            proc.stdin.write(big.tobytes())
            if i % 20 == 0: log(f"  إطار {i+1}/{len(frames)}")
        proc.stdin.close(); proc.wait()
        return out_path
    finally:
        del up; free_mem()

# ============================ التشغيل ==================================
def run(subject, style="cinematic", seed=42):
    p = PROMPTS[style]
    CFG["upscale_style"] = p["upscale"]
    prompt, neg = p["positive"].format(subject=subject), p["negative"]
    out_dir = CFG["work_dir"]; t0 = time.time()

    frames = stage1_generate(prompt, neg, seed)
    if frames is None: raise RuntimeError("فشل التوليد الأساسي")
    base = os.path.join(out_dir, "1_base_480p.mp4"); write_mp4(frames, base, CFG["base_fps"])
    log(f"حُفظ: {base}")

    frames = stage2_interpolate(frames)
    mid_p = os.path.join(out_dir, "2_interpolated_480p.mp4"); write_mp4(frames, mid_p, CFG["out_fps"])

    final = os.path.join(out_dir, f"FINAL_{style}_1080p_{CFG['out_fps']}fps.mp4")
    try:
        stage3_upscale_encode(frames, final)
    except Exception:
        traceback.print_exc(); log("فشل رفع الدقة — النسخة المتوسطة صالحة")
        final = mid_p
    log(f"✅ انتهى في {(time.time()-t0)/60:.1f} دقيقة → {final}")
    return final

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", default="a lone astronaut walking across a red desert at sunset, wind blowing dust")
    ap.add_argument("--style", default="cinematic", choices=list(PROMPTS))
    ap.add_argument("--seed", type=int, default=42)
    a, _ = ap.parse_known_args()
    run(a.subject, a.style, a.seed)
