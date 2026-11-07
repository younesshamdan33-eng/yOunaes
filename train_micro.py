#!/usr/bin/env python3
"""Micro-Trainer v3 — حل جذري: تثبيت المكتبات في /tmp/cinema_libs وإجبار sys.path."""
import os, sys, json, time, random, subprocess
from pathlib import Path

# ============ الخطوة الحرجة: تنظيف + تثبيت في مجلد منفصل ============
LIB_DIR = "/tmp/cinema_libs"
import shutil
if os.path.exists(LIB_DIR): shutil.rmtree(LIB_DIR, ignore_errors=True)
os.makedirs(LIB_DIR, exist_ok=True)
print(f"[MICRO] تثبيت المكتبات في {LIB_DIR}...", flush=True)

pkgs = "peft==0.19.0 diffusers==0.35.0 transformers==4.46.3 accelerate bitsandbytes sentencepiece imageio[ffmpeg] ftfy safetensors huggingface_hub --no-deps"
r = subprocess.run(f"pip install -q --target={LIB_DIR} --no-cache-dir --upgrade {pkgs}",
                   shell=True, capture_output=True, text=True)
print(f"[MICRO] pip exit={r.returncode}", flush=True)
if r.returncode != 0:
    print(f"[MICRO] pip stderr: {r.stderr[-400:]}", flush=True)

# إجبار Python على البحث في LIB_DIR أولاً وقبل أي شيء آخر
sys.path.insert(0, LIB_DIR)

# مسح أي نسخة قديمة من الذاكرة
for mod in list(sys.modules.keys()):
    if mod.startswith(("diffusers", "peft", "transformers")):
        del sys.modules[mod]

# ============ التحقق الصارم ============
import diffusers, peft
print(f"[MICRO] diffusers={diffusers.__version__} @ {diffusers.__file__}", flush=True)
print(f"[MICRO] peft={peft.__version__} @ {peft.__file__}", flush=True)

from peft.helpers import disable_input_dtype_casting
print("[MICRO] ✅ disable_input_dtype_casting OK", flush=True)

# ============ المكتبات الرئيسية ============
import torch
import numpy as np
import cv2
from huggingface_hub import hf_hub_download
from diffusers import AutoencoderKLWan, WanTransformer3DModel, UniPCMultistepScheduler
from peft import LoraConfig
from transformers import AutoTokenizer, UMT5EncoderModel

REPO = "Wild-Heart/Tom-and-Jerry-VideoGeneration-Dataset"
N_VIDEOS = 5
MAX_STEPS = 50
LR = 1e-4
LORA_R = 8
LORA_ALPHA = 16
RES_W, RES_H = 640, 384
N_FRAMES = 17
OUT_DIR = Path("/kaggle/working/lora_out")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def log(msg): print(f"[MICRO] {msg}", flush=True)
log(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NONE'}")

# ============ تحميل البيانات ============
log("تحميل captions.txt و videos.txt")
def dl(fn):
    try: return Path(hf_hub_download(REPO, fn, repo_type="dataset"))
    except Exception as e: log(f"❌ فشل {fn}: {e}"); return None

cap_p, vid_list_p = dl("captions.txt"), dl("videos.txt")
if not cap_p or not vid_list_p: sys.exit(1)

caps = [l.strip() for l in cap_p.read_text(encoding="utf-8").splitlines() if l.strip()]
vids = [l.strip() for l in vid_list_p.read_text(encoding="utf-8").splitlines() if l.strip()]
log(f"عدد الأوصاف: {len(caps)}, مسارات: {len(vids)}")

n = min(N_VIDEOS, len(caps), len(vids))
selected = list(zip(caps[:n], vids[:n]))

log("تحميل الفيديوهات")
video_paths = []
for i, (cap, rel) in enumerate(selected):
    try: video_paths.append((hf_hub_download(REPO, rel, repo_type="dataset"), cap))
    except Exception as e: log(f"⚠️ {i+1}: {e}")
log(f"تم تحميل {len(video_paths)} فيديو")

# ============ تحميل VAE و T5 ============
MODEL_ID = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
dtype = torch.float16
log("تحميل VAE و T5")
vae = AutoencoderKLWan.from_pretrained(MODEL_ID, subfolder="vae", torch_dtype=torch.float32).to("cuda").eval()
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, subfolder="tokenizer")
t5 = UMT5EncoderModel.from_pretrained(MODEL_ID, subfolder="text_encoder", torch_dtype=torch.bfloat16).to("cuda").eval()

def load_frames(path, n, w, h):
    cap = cv2.VideoCapture(path); total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total < 2: cap.release(); return None
    idxs = np.linspace(0, total-1, n).astype(int); frames = []
    for idx in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx)); ok, fr = cap.read()
        if ok: frames.append(cv2.cvtColor(cv2.resize(fr, (w, h)), cv2.COLOR_BGR2RGB))
    cap.release()
    while len(frames) < n and frames: frames.append(frames[-1])
    return np.stack(frames[:n]) if frames else None

log("استخراج Latents")
zd = vae.config.z_dim
mean = torch.tensor(vae.config.latents_mean).view(1, zd, 1, 1, 1).to("cuda")
inv_std = (1.0 / torch.tensor(vae.config.latents_std)).view(1, zd, 1, 1, 1).to("cuda")
data = []
with torch.no_grad():
    for i, (vp, cap) in enumerate(video_paths):
        frames = load_frames(vp, N_FRAMES, RES_W, RES_H)
        if frames is None: continue
        vid = torch.from_numpy(frames).permute(3, 0, 1, 2).unsqueeze(0).float().div(127.5).sub(1.0).to("cuda")
        lat = ((vae.encode(vid).latent_dist.mode() - mean) * inv_std).squeeze(0).half().cpu()
        ids = tokenizer(cap, padding="max_length", max_length=512, truncation=True, return_tensors="pt")
        sl = int(ids.attention_mask.sum())
        emb = t5(ids.input_ids.to("cuda"), ids.attention_mask.to("cuda")).last_hidden_state[0, :sl].half().cpu()
        ids0 = tokenizer("", padding="max_length", max_length=512, truncation=True, return_tensors="pt")
        emb0 = t5(ids0.input_ids.to("cuda"), ids0.attention_mask.to("cuda")).last_hidden_state[0, :1].half().cpu()
        data.append({"lat": lat, "emb": emb, "null": emb0, "cap": cap})
        log(f"✅ [{i+1}] latent {tuple(lat.shape)}")

log(f"تم استخراج {len(data)} latent")
if not data: sys.exit(1)

del vae, t5, tokenizer
torch.cuda.empty_cache()

# ============ Transformer + LoRA ============
log("تحميل Transformer + LoRA")
transformer = WanTransformer3DModel.from_pretrained(MODEL_ID, subfolder="transformer", torch_dtype=dtype)
transformer.requires_grad_(False)
transformer.add_adapter(LoraConfig(r=LORA_R, lora_alpha=LORA_ALPHA, init_lora_weights=True,
                                   target_modules=["to_q", "to_k", "to_v", "to_out.0", "ffn.net.0.proj", "ffn.net.2"]))
for p in transformer.parameters():
    if p.requires_grad: p.data = p.data.float()
transformer.enable_gradient_checkpointing()
transformer.to("cuda").train()
params = [p for p in transformer.parameters() if p.requires_grad]
log(f"✅ LoRA: {sum(p.numel() for p in params)/1e6:.2f}M param, VRAM={torch.cuda.memory_allocated()/2**30:.1f}GB")

# ============ التدريب ============
log("===== بدء التدريب =====")
import bitsandbytes as bnb
opt = bnb.optim.AdamW8bit(params, lr=LR, betas=(0.9, 0.999), weight_decay=0.01)
scaler = torch.amp.GradScaler("cuda", enabled=True)

def sample_sigma():
    u = torch.sigmoid(torch.randn(1, device="cuda")); s = 5.0
    return (s * u / (1 + (s - 1) * u)).clamp(1e-3, 1 - 1e-3)

t0 = time.time()
loss_val = 0.0
for step in range(1, MAX_STEPS + 1):
    d = random.choice(data)
    lat = d["lat"].unsqueeze(0).to("cuda", torch.float32)
    emb = (d["null"] if random.random() < 0.1 else d["emb"]).unsqueeze(0).to("cuda", dtype)
    noise = torch.randn_like(lat); sigma = sample_sigma(); sb = sigma.view(1,1,1,1,1)
    noisy = (1 - sb) * lat + sb * noise; target = noise - lat
    with torch.autocast("cuda", dtype=dtype):
        pred = transformer(hidden_states=noisy.to(dtype).requires_grad_(True), timestep=sigma*1000.0,
                           encoder_hidden_states=emb, return_dict=False)[0]
    loss = torch.nn.functional.mse_loss(pred.float(), target)
    if not torch.isfinite(loss):
        log(f"⚠️ step {step}: loss غير منتهية، تخطي"); opt.zero_grad(set_to_none=True); continue
    scaler.scale(loss).backward(); scaler.unscale_(opt)
    torch.nn.utils.clip_grad_norm_(params, 1.0)
    scaler.step(opt); scaler.update(); opt.zero_grad(set_to_none=True)
    loss_val = loss.item()
    if step % 5 == 0 or step == 1:
        log(f"step {step}/{MAX_STEPS} loss={loss_val:.4f} VRAM={torch.cuda.memory_allocated()/2**30:.1f}GB t={time.time()-t0:.0f}s")

# ============ الحفظ ============
log("حفظ LoRA")
from peft.utils import get_peft_model_state_dict
state = {k: v.detach().cpu() for k, v in get_peft_model_state_dict(transformer).items()}
torch.save(state, OUT_DIR / "lora.pt")
(OUT_DIR / "info.json").write_text(json.dumps({"n_videos": len(data), "steps": MAX_STEPS, "lora_r": LORA_R,
    "final_loss": float(loss_val), "res": f"{RES_W}x{RES_H}", "frames": N_FRAMES}, indent=2))
log(f"✅ SUCCESS — lora.pt saved ({len(state)} keys, {os.path.getsize(OUT_DIR/'lora.pt')/1e6:.1f}MB)")
