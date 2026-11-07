# =====================================================================
#  CINEMATIC QUALITY ENGINE  (Kaggle T4 - single script)
#  Stage 0: Prompt engineering (LLM expander + style presets + Wan negative prompt)
#  Stage 1: Smart generation (Wan2.1 1.3B, UniPC flow sampler, best-of-N seed
#           selection with automatic quality scoring, optional V2V refine pass)
#  Stage 2: True super-resolution (Real-ESRGAN weights via `spandrel`, NO basicsr)
#           + tiled inference + temporal anti-flicker stabilization -> 1080p
#  Stage 3: Frame interpolation (Practical-RIFE 4.26, 16fps -> 32fps)
#  Stage 4: Cinematic grading (procedural 3D LUT + bloom + vignette + film grain)
#  Notebook settings: Accelerator = GPU T4 x1, Internet = ON
# =====================================================================
import os, sys, gc, time, shutil, subprocess, traceback, urllib.request, zipfile

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"          # use ONE T4 only
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ------------------------------ CONFIG -------------------------------
ROOT = "/kaggle/working" if os.path.isdir("/kaggle/working") else os.getcwd()
CFG = {
    "prompt": "A lone astronaut walks across red desert dunes at sunset, dust blowing in the wind",
    "style": "cinematic",          # cinematic | realistic | cartoon
    "seed": 1234,
    "width": 848, "height": 480,   # multiples of 16
    "num_frames": 81,              # must be 4k+1  (81 frames = ~5s @16fps)
    "base_fps": 16,
    "steps": 60, "guidance": 6.0,
    "flow_shift": 5.0,             # tune 3.0 (softer) .. 8.0 (more contrast/detail)
    "n_candidates": 3,             # best-of-N seeds (1 = disabled)
    "cand_steps": 20, "cand_frames": 33,
    "use_llm_expander": True,      # Qwen2.5-1.5B prompt extension (falls back to rules)
    "refine_pass": True,           # low-strength video-to-video detail pass (guarded)
    "refine_strength": 0.3, "refine_steps": 30,
    "sr_model": "auto",            # auto | RealESRGAN_x4plus | realesr-general-x4v3 | realesr-animevideov3
    "sr_tile": 256,
    "target_w": 1920, "target_h": 1080,
    "interp_passes": 1,            # 1 => 2x (16->32fps), 2 => 4x (16->64fps)
    "output": os.path.join(ROOT, "final_cinematic.mp4"),
    "work": os.path.join(ROOT, "cqe_work"),
}

# --------------------------- DEPENDENCIES ----------------------------
def run(cmd, check=True):
    print("$", cmd if isinstance(cmd, str) else " ".join(cmd))
    return subprocess.run(cmd, shell=isinstance(cmd, str), check=check)

def install_dependencies():
    # We never touch torch/torchvision, so no ABI conflicts on Kaggle.
    run([sys.executable, "-m", "pip", "install", "-q",
         "diffusers>=0.33.0", "transformers>=4.49", "accelerate", "ftfy",
         "sentencepiece", "imageio", "imageio-ffmpeg", "spandrel"])

install_dependencies()

import numpy as np
import cv2
import torch
import torch.nn.functional as F

os.makedirs(CFG["work"], exist_ok=True)

# ----------------------------- UTILITIES -----------------------------
def get_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        enc = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        if "libx264" in enc:
            return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

FFMPEG = get_ffmpeg()

def free_gpu():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

def download(url, dst, min_bytes=100_000, retries=3):
    if os.path.exists(dst) and os.path.getsize(dst) > min_bytes:
        return dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180) as r, open(dst, "wb") as f:
                shutil.copyfileobj(r, f)
            if os.path.getsize(dst) > min_bytes:
                return dst
        except Exception as e:
            print(f"download retry {i+1}: {e}")
            time.sleep(3)
    raise RuntimeError(f"download failed: {url}")

def save_png(path, rgb):
    cv2.imwrite(path, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_PNG_COMPRESSION, 1])

def load_png(path):
    return cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB)

def list_pngs(d):
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".png"))

def encode_sequence(frames_dir, fps, out_path, vf=None, filter_complex=None, crf=14):
    """Encode a %06d.png sequence to H.264 MP4 (optionally through a filter graph)."""
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-framerate", str(fps), "-i", os.path.join(frames_dir, "%06d.png")]
    if filter_complex:
        cmd += ["-filter_complex", filter_complex, "-map", "[out]"]
    elif vf:
        cmd += ["-vf", vf]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]
    subprocess.run(cmd, check=True)

# ------------------------ STAGE 0: PROMPT ENGINEERING -----------------
NEG_BASE = ("Bright tones, overexposed, static, blurred details, subtitles, style, works, paintings, "
            "images, static, overall gray, worst quality, low quality, JPEG compression residue, ugly, "
            "incomplete, extra fingers, poorly drawn hands, poorly drawn faces, deformed, disfigured, "
            "misshapen limbs, fused fingers, still picture, messy background, three legs, "
            "many people in the background, walking backwards")

STYLES = {
    "cinematic": {
        "suffix": ("Cinematic film still, shot on ARRI Alexa 65 with anamorphic lens, shallow depth of field, "
                   "soft volumetric lighting, rich color contrast, natural motion blur, subtle film grain, "
                   "highly detailed, sharp focus, smooth camera movement, 8k."),
        "neg": "cartoon, flat lighting, flicker",
        "lut": dict(tone=0.60, lift=0.020, split=1.0, sat=1.05, contrast=1.05, gamma=1.0,
                    grain=7, bloom=True, vignette=True),
    },
    "realistic": {
        "suffix": ("Ultra-realistic footage, shot on RED Komodo 6K, natural lighting, true-to-life skin and "
                   "material textures, realistic physics and motion, high dynamic range, sharp focus, "
                   "highly detailed, documentary style."),
        "neg": "cartoon, anime, illustration, 3d render, flicker",
        "lut": dict(tone=0.35, lift=0.008, split=0.35, sat=0.97, contrast=1.03, gamma=1.0,
                    grain=5, bloom=False, vignette=True),
    },
    "cartoon": {
        "suffix": ("High-quality 3D animated feature film style, stylized characters, clean shapes, "
                   "vibrant colors, expressive motion, soft global illumination, smooth fluid animation, "
                   "detailed background, sharp lines."),
        "neg": "photorealistic, noise, grain, flicker",
        "lut": dict(tone=0.25, lift=0.0, split=0.15, sat=1.25, contrast=1.05, gamma=1.0,
                    grain=0, bloom=False, vignette=False),
    },
}

def llm_expand(prompt, style):
    """Wan was trained on long captions: expand a short idea into a rich paragraph with a small local LLM."""
    from transformers import AutoModelForCausalLM, AutoTokenizer
    name = "Qwen/Qwen2.5-1.5B-Instruct"
    tok = AutoTokenizer.from_pretrained(name)
    model = AutoModelForCausalLM.from_pretrained(name, torch_dtype=torch.float16).to("cuda")
    msgs = [
        {"role": "system", "content":
            "You are a prompt engineer for a text-to-video diffusion model. Rewrite the user's idea as ONE "
            "detailed English paragraph (60-90 words) describing: subject, physically plausible action, "
            "environment, lighting, camera movement and lens, colors and mood. No lists, no quotes, no preface. "
            f"Visual style: {style}."},
        {"role": "user", "content": prompt},
    ]
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = tok([text], return_tensors="pt").to("cuda")
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=200, do_sample=False, repetition_penalty=1.05)
    res = tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    del model, tok, inputs, out
    free_gpu()
    if len(res.split()) < 20:
        raise ValueError("LLM output too short")
    return res

def stage0_prompt():
    style = CFG["style"]
    base = CFG["prompt"].strip()
    if CFG["use_llm_expander"]:
        try:
            base = llm_expand(base, style)
            print("[Stage0] LLM-expanded prompt OK")
        except Exception as e:
            print("[Stage0] LLM expander failed, using rule-based only:", e)
            free_gpu()
    prompt = f"{base.rstrip('.')}. {STYLES[style]['suffix']}"
    neg = f"{NEG_BASE}, {STYLES[style]['neg']}"
    print("[Stage0] FINAL PROMPT:\n", prompt)
    return prompt, neg

# ------------------------ STAGE 1: SMART GENERATION --------------------
PIPE = {"obj": None, "dtype_idx": 0}
DTYPES = [torch.float16, torch.bfloat16]   # fp16 is faster on T4; bf16 is the NaN-safe fallback

def get_pipe():
    if PIPE["obj"] is not None:
        return PIPE["obj"]
    from diffusers import AutoencoderKLWan, WanPipeline, UniPCMultistepScheduler
    mid = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
    dtype = DTYPES[PIPE["dtype_idx"]]
    print(f"[Stage1] loading Wan2.1 1.3B in {dtype}")
    vae = AutoencoderKLWan.from_pretrained(mid, subfolder="vae", torch_dtype=torch.float32)  # VAE stays fp32
    pipe = WanPipeline.from_pretrained(mid, vae=vae, torch_dtype=dtype)
    pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config, flow_shift=CFG["flow_shift"])
    pipe.enable_model_cpu_offload()      # T5 encoder is ~11GB: offload keeps us under 16GB
    try:
        pipe.vae.enable_tiling()
    except Exception:
        pass
    PIPE["obj"] = pipe
    return pipe

def drop_pipe():
    PIPE["obj"] = None
    free_gpu()

def valid_clip(x):
    return bool(np.isfinite(x).all() and x.mean() > 0.02 and x.std() > 0.01)

def sharpness(frames):
    idx = np.linspace(0, len(frames) - 1, min(8, len(frames))).astype(int)
    vals = []
    for i in idx:
        g = cv2.cvtColor((np.clip(frames[i], 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
        vals.append(cv2.Laplacian(g, cv2.CV_64F).var())
    return float(np.mean(vals))

def score_clip(frames):
    """Heuristic reward: sharp + contrasty + moderate motion (not frozen, not chaotic)."""
    small = frames[:, ::4, ::4].astype(np.float32)
    motion = float(np.mean(np.abs(np.diff(small, axis=0))))
    contrast = float(small.mean(axis=3).std())
    s = np.log1p(sharpness(frames)) + 2.0 * contrast
    s -= 40.0 * max(0.0, 0.008 - motion)   # penalize near-static clips
    s -= 20.0 * max(0.0, motion - 0.06)    # penalize flicker / chaos
    return s

def gen_clip(prompt, neg, seed, frames, steps):
    while PIPE["dtype_idx"] < len(DTYPES):
        pipe = get_pipe()
        out = pipe(prompt=prompt, negative_prompt=neg,
                   height=CFG["height"], width=CFG["width"], num_frames=frames,
                   num_inference_steps=steps, guidance_scale=CFG["guidance"],
                   generator=torch.Generator("cpu").manual_seed(seed),
                   output_type="np").frames[0]
        out = np.asarray(out, dtype=np.float32)
        if valid_clip(out):
            return out
        print("[Stage1] invalid output (NaN/black) -> switching dtype")
        drop_pipe()
        PIPE["dtype_idx"] += 1
    raise RuntimeError("Wan generation failed in fp16 and bf16")

def refine_clip(frames, prompt, neg, seed):
    """Second pass: low-strength V2V re-denoise adds detail. Kept only if it is really sharper."""
    try:
        from diffusers import WanVideoToVideoPipeline
        from PIL import Image
        v2v = WanVideoToVideoPipeline.from_pipe(get_pipe())
        vid = [Image.fromarray((np.clip(f, 0, 1) * 255).astype(np.uint8)) for f in frames]
        out = v2v(video=vid, prompt=prompt, negative_prompt=neg,
                  height=CFG["height"], width=CFG["width"],
                  num_inference_steps=CFG["refine_steps"], guidance_scale=CFG["guidance"],
                  strength=CFG["refine_strength"],
                  generator=torch.Generator("cpu").manual_seed(seed + 7),
                  output_type="np").frames[0]
        out = np.asarray(out, dtype=np.float32)
        if len(out) == len(frames) and valid_clip(out) and sharpness(out) > sharpness(frames) * 1.03:
            print("[Stage1] refine pass accepted")
            return out
        print("[Stage1] refine pass rejected (not better)")
    except Exception as e:
        print("[Stage1] refine pass skipped:", e)
    return frames

def stage1_generate(prompt, neg):
    best, best_score, best_seed = None, -1e9, CFG["seed"]
    if CFG["n_candidates"] > 1:
        for i in range(CFG["n_candidates"]):
            seed = CFG["seed"] + i
            try:
                c = gen_clip(prompt, neg, seed, CFG["cand_frames"], CFG["cand_steps"])
                sc = score_clip(c)
                print(f"[Stage1] candidate seed={seed} score={sc:.3f}")
                if sc > best_score:
                    best_score, best_seed = sc, seed
            except Exception as e:
                print("[Stage1] candidate failed:", e)
            free_gpu()
    print(f"[Stage1] final render: seed={best_seed}, steps={CFG['steps']}")
    frames = gen_clip(prompt, neg, best_seed, CFG["num_frames"], CFG["steps"])
    if CFG["refine_pass"]:
        frames = refine_clip(frames, prompt, neg, best_seed)
    drop_pipe()
    return (np.clip(frames, 0, 1) * 255).round().astype(np.uint8)

# ------------------------ STAGE 2: SUPER-RESOLUTION --------------------
SR_URLS = {
    "RealESRGAN_x4plus": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
    "realesr-general-x4v3": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth",
    "realesr-animevideov3": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth",
}

def pick_sr_name():
    if CFG["sr_model"] != "auto":
        return CFG["sr_model"]
    return "realesr-animevideov3" if CFG["style"] == "cartoon" else "RealESRGAN_x4plus"

def load_sr():
    from spandrel import ModelLoader      # loads the .pth directly: no basicsr, no torchvision clash
    name = pick_sr_name()
    path = download(SR_URLS[name], os.path.join(CFG["work"], "weights", name + ".pth"))
    desc = ModelLoader().load_from_file(path)
    desc.eval()
    dtype = torch.float32
    if getattr(desc, "supports_half", False):
        desc.half()
        dtype = torch.float16
    desc.to("cuda")
    print(f"[Stage2] SR model {name} (x{desc.scale}) dtype={dtype}")
    return desc, dtype

@torch.no_grad()
def tiled_sr(desc, x, scale, tile, pad=16):
    _, c, h, w = x.shape
    out = torch.zeros((1, c, h * scale, w * scale), dtype=x.dtype, device=x.device)
    for y0 in range(0, h, tile):
        for x0 in range(0, w, tile):
            y1, x1 = min(y0 + tile, h), min(x0 + tile, w)
            ya, yb = max(y0 - pad, 0), min(y1 + pad, h)
            xa, xb = max(x0 - pad, 0), min(x1 + pad, w)
            res = desc(x[:, :, ya:yb, xa:xb])
            oy, ox = (y0 - ya) * scale, (x0 - xa) * scale
            out[:, :, y0 * scale:y1 * scale, x0 * scale:x1 * scale] = \
                res[:, :, oy:oy + (y1 - y0) * scale, ox:ox + (x1 - x0) * scale]
    return out

def sr_frame(desc, dtype, img):
    x = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).to("cuda", dtype=dtype).div_(255.0)
    while True:
        try:
            y = tiled_sr(desc, x, int(desc.scale), CFG["sr_tile"])
            break
        except torch.cuda.OutOfMemoryError:
            free_gpu()
            CFG["sr_tile"] = max(64, CFG["sr_tile"] // 2)
            print("[Stage2] OOM -> tile =", CFG["sr_tile"])
    return (y.squeeze(0).permute(1, 2, 0).clamp_(0, 1) * 255).round().byte().cpu().numpy()

def fit_cover(img, W, H):
    h, w = img.shape[:2]
    s = max(W / w, H / h)
    nw, nh = int(round(w * s)), int(round(h * s))
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC
    img = cv2.resize(img, (nw, nh), interpolation=interp)
    x0, y0 = (nw - W) // 2, (nh - H) // 2
    return img[y0:y0 + H, x0:x0 + W]

def stabilize(cur, prev, thr=10.0, alpha=0.4):
    """Per-frame SR flickers. Blend with the previous frame only where the scene is static."""
    diff = np.abs(cur.astype(np.float32) - prev.astype(np.float32)).mean(axis=2)
    diff = cv2.GaussianBlur(diff, (0, 0), 3)
    w = (np.clip(1.0 - diff / thr, 0, 1) * alpha)[..., None]
    return (cur * (1 - w) + prev * w).round().astype(np.uint8)

def stage2_super_resolution(frames_u8, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    W, H = CFG["target_w"], CFG["target_h"]
    desc, dtype = None, None
    try:
        desc, dtype = load_sr()
    except Exception as e:
        print("[Stage2] spandrel/Real-ESRGAN failed -> Lanczos+unsharp fallback:", e)
    prev = None
    for i, f in enumerate(frames_u8):
        if desc is not None:
            up = fit_cover(sr_frame(desc, dtype, f), W, H)
        else:
            up = cv2.resize(f, (int(f.shape[1] * max(W / f.shape[1], H / f.shape[0]) + 0.5),
                                int(f.shape[0] * max(W / f.shape[1], H / f.shape[0]) + 0.5)),
                            interpolation=cv2.INTER_LANCZOS4)
            up = fit_cover(up, W, H)
            blur = cv2.GaussianBlur(up, (0, 0), 1.2)
            up = cv2.addWeighted(up, 1.5, blur, -0.5, 0)
        if prev is not None:
            up = stabilize(up, prev)
        prev = up
        save_png(os.path.join(out_dir, f"{i:06d}.png"), up)
        if i % 10 == 0:
            print(f"[Stage2] frame {i+1}/{len(frames_u8)}")
    del desc
    free_gpu()
    return out_dir

# ------------------------ STAGE 3: FRAME INTERPOLATION -----------------
def setup_rife():
    d = os.path.join(CFG["work"], "Practical-RIFE")
    if not os.path.isdir(d):
        run(["git", "clone", "--depth", "1", "https://github.com/hzwer/Practical-RIFE", d])
    tl = os.path.join(d, "train_log")
    if not os.path.exists(os.path.join(tl, "flownet.pkl")):
        zp = download("https://huggingface.co/hzwer/RIFE/resolve/main/RIFEv4.26_0921.zip",
                      os.path.join(CFG["work"], "weights", "rife426.zip"), min_bytes=1_000_000)
        ex = os.path.join(CFG["work"], "rife_extract")
        shutil.rmtree(ex, ignore_errors=True)
        with zipfile.ZipFile(zp) as z:
            z.extractall(ex)
        os.makedirs(tl, exist_ok=True)
        for root, _, files in os.walk(ex):
            for fn in files:
                if fn in ("flownet.pkl", "RIFE_HDv3.py", "IFNet_HDv3.py"):
                    shutil.copy(os.path.join(root, fn), os.path.join(tl, fn))
        open(os.path.join(tl, "__init__.py"), "a").close()
    if d not in sys.path:
        sys.path.insert(0, d)
    return d, tl

def to_tensor(img, ph, pw):
    t = torch.from_numpy(img.transpose(2, 0, 1)).float().div(255.0).unsqueeze(0).to("cuda")
    return F.pad(t, (0, pw - t.shape[3], 0, ph - t.shape[2]))

def rife_pass(model, src_dir, dst_dir, scale):
    os.makedirs(dst_dir, exist_ok=True)
    files = list_pngs(src_dir)
    h, w = load_png(files[0]).shape[:2]
    tmp = max(128, int(128 / scale))
    ph, pw = ((h - 1) // tmp + 1) * tmp, ((w - 1) // tmp + 1) * tmp
    n = 0
    for i in range(len(files) - 1):
        a, b = load_png(files[i]), load_png(files[i + 1])
        save_png(os.path.join(dst_dir, f"{n:06d}.png"), a); n += 1
        cut = np.abs(a[::8, ::8].astype(np.float32) - b[::8, ::8].astype(np.float32)).mean() / 255.0
        if cut > 0.2:                      # scene cut: duplicate instead of interpolating
            mid = a
        else:
            I0, I1 = to_tensor(a, ph, pw), to_tensor(b, ph, pw)
            with torch.no_grad():
                try:
                    m = model.inference(I0, I1, 0.5, scale)
                except TypeError:
                    m = model.inference(I0, I1, scale)
            mid = (m[0].clamp(0, 1) * 255).round().byte().cpu().numpy().transpose(1, 2, 0)[:h, :w]
        save_png(os.path.join(dst_dir, f"{n:06d}.png"), mid); n += 1
    save_png(os.path.join(dst_dir, f"{n:06d}.png"), load_png(files[-1]))
    return dst_dir

def ffmpeg_minterpolate(src_dir, dst_dir, fps_in):
    """Fallback if RIFE can't load: motion-compensated interpolation inside FFmpeg."""
    os.makedirs(dst_dir, exist_ok=True)
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps_in),
                    "-i", os.path.join(src_dir, "%06d.png"),
                    "-vf", f"minterpolate=fps={fps_in*2}:mi_mode=mci:mc_mode=aobmc:vsbmc=1",
                    os.path.join(dst_dir, "%06d.png")], check=True)
    return dst_dir

def stage3_interpolate(src_dir):
    fps = CFG["base_fps"]
    cur = src_dir
    model = None
    try:
        _, tl = setup_rife()
        from train_log.RIFE_HDv3 import Model
        model = Model()
        model.load_model(tl, -1)
        model.eval()
        model.device()
        print("[Stage3] RIFE 4.26 loaded")
    except Exception as e:
        print("[Stage3] RIFE load failed -> FFmpeg minterpolate fallback:", e)
        traceback.print_exc()
    for p in range(CFG["interp_passes"]):
        dst = os.path.join(CFG["work"], f"03_interp_{p}")
        shutil.rmtree(dst, ignore_errors=True)
        try:
            if model is None:
                raise RuntimeError("no RIFE model")
            try:
                cur = rife_pass(model, cur, dst, 1.0)
            except torch.cuda.OutOfMemoryError:
                free_gpu()
                print("[Stage3] OOM at scale 1.0 -> retry with scale 0.5")
                shutil.rmtree(dst, ignore_errors=True)
                cur = rife_pass(model, cur, dst, 0.5)
        except Exception as e:
            print("[Stage3] RIFE pass failed -> minterpolate:", e)
            shutil.rmtree(dst, ignore_errors=True)
            cur = ffmpeg_minterpolate(cur, dst, fps)
        fps *= 2
        free_gpu()
    del model
    free_gpu()
    return cur, fps

# ------------------------ STAGE 4: CINEMATIC GRADING -------------------
def write_cube_lut(path, p, size=33):
    """Procedural 3D LUT: filmic S-curve + lifted blacks + teal/orange split-tone + saturation."""
    g = np.linspace(0.0, 1.0, size)
    B, G, R = np.meshgrid(g, g, g, indexing="ij")        # R varies fastest (.cube convention)
    rgb = np.stack([R, G, B], axis=-1).reshape(-1, 3)
    s = rgb * rgb * (3 - 2 * rgb)                        # smoothstep S-curve
    rgb = rgb * (1 - p["tone"]) + s * p["tone"]
    rgb = rgb * (1 - p["lift"]) + p["lift"]              # faded blacks
    luma = (rgb @ np.array([0.2126, 0.7152, 0.0722]))[:, None]
    shadows, highs = (1 - luma) ** 2, luma ** 2
    teal = np.array([-0.020, 0.010, 0.040]) * p["split"]
    orange = np.array([0.040, 0.010, -0.030]) * p["split"]
    rgb = rgb + shadows * teal + highs * orange
    luma2 = (rgb @ np.array([0.2126, 0.7152, 0.0722]))[:, None]
    rgb = luma2 + (rgb - luma2) * p["sat"]
    rgb = np.clip(rgb, 0, 1)
    with open(path, "w") as f:
        f.write(f'TITLE "cqe"\nLUT_3D_SIZE {size}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        for r, gg, b in rgb:
            f.write(f"{r:.6f} {gg:.6f} {b:.6f}\n")

def stage4_grade(frames_dir, fps, out_path):
    p = STYLES[CFG["style"]]["lut"]
    lut = os.path.join(CFG["work"], "cinematic.cube")
    write_cube_lut(lut, p)
    chain = f"lut3d=file='{lut}',eq=contrast={p['contrast']}:saturation=1.0:gamma={p['gamma']}," \
            f"unsharp=5:5:0.4:5:5:0.0"
    tail = []
    if p["vignette"]:
        tail.append("vignette=PI/5")
    if p["grain"] > 0:
        tail.append(f"noise=alls={p['grain']}:allf=t+u")
    tail.append("format=yuv420p")
    tail_s = ",".join(tail)
    if p["bloom"]:
        graph = (f"[0:v]{chain},split=2[a][b];[b]gblur=sigma=25,eq=brightness=-0.12[g];"
                 f"[a][g]blend=all_mode=screen:all_opacity=0.12,{tail_s}[out]")
    else:
        graph = f"[0:v]{chain},{tail_s}[out]"
    try:
        encode_sequence(frames_dir, fps, out_path, filter_complex=graph, crf=14)
        print("[Stage4] graded video saved:", out_path)
    except Exception as e:
        print("[Stage4] grading failed -> plain encode:", e)
        encode_sequence(frames_dir, fps, out_path, vf="format=yuv420p", crf=14)

# ------------------------------- MAIN ---------------------------------
def main():
    T = {}
    t = time.time()
    print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NONE (CPU!)")
    d0 = os.path.join(CFG["work"], "01_base")
    d2 = os.path.join(CFG["work"], "02_sr")
    for d in (d0, d2):
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d0, exist_ok=True)

    # Stage 0 + 1
    prompt, neg = stage0_prompt()
    frames = stage1_generate(prompt, neg)
    for i, f in enumerate(frames):
        save_png(os.path.join(d0, f"{i:06d}.png"), f)
    encode_sequence(d0, CFG["base_fps"], os.path.join(ROOT, "base_480p.mp4"), crf=16)
    T["1_generation"] = time.time() - t; t = time.time()
    free_gpu()

    # Stage 2
    try:
        sr_dir = stage2_super_resolution(list(frames), d2)
    except Exception as e:
        print("[Stage2] FAILED, using base frames:", e)
        traceback.print_exc()
        sr_dir = d0
    free_gpu()
    T["2_super_resolution"] = time.time() - t; t = time.time()

    # Stage 3
    fps = CFG["base_fps"]
    try:
        mid_dir, fps = stage3_interpolate(sr_dir)
    except Exception as e:
        print("[Stage3] FAILED, keeping original fps:", e)
        traceback.print_exc()
        mid_dir = sr_dir
    free_gpu()
    T["3_interpolation"] = time.time() - t; t = time.time()

    # Stage 4
    stage4_grade(mid_dir, fps, CFG["output"])
    T["4_grading"] = time.time() - t

    print("\n================ DONE ================")
    for k, v in T.items():
        print(f"{k:22s} {v/60:6.1f} min")
    print("Final video :", CFG["output"], f"({fps} fps)")

if __name__ == "__main__":
    main()
