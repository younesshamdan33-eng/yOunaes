# =====================================================================
#  CINEMATIC LoRA TRAINER  -  Wan2.1-T2V-1.3B  on Kaggle T4 (16GB)
#  Goal: bake "cinematic aesthetics" INTO the model (no ESRGAN / no RIFE).
#
#  Quality techniques borrowed from the big video models' training recipes:
#   [Q1] Data curation: auto-score clips (sharpness, contrast, flicker, motion),
#        drop scene-cuts / static / too-dark clips, sample the best clips more often.
#   [Q2] Latent + text-embedding caching (VAE and the 11GB T5 never sit in VRAM
#        during training -> the whole 16GB goes to the transformer).
#   [Q3] Logit-normal + shifted timestep sampling (SD3 / Wan style flow matching)
#        -> more training on the mid-noise levels where detail and structure form.
#   [Q4] Caption dropout (10%) -> keeps classifier-free guidance healthy.
#   [Q5] Extra losses on the predicted clean latent: spatial-gradient loss (detail
#        sharpness) + temporal-difference loss (smooth motion), both weighted by (1-sigma).
#   [Q6] EMA of the LoRA weights (used for the saved file and the final test).
#   [Q7] Trigger phrase prepended to every caption -> the style can be switched on/off.
#   [Q8] Cosine LR + warmup + grad clipping, A/B test (base vs LoRA, same seed) at the end.
#
#  Memory optimizations for 16GB (all enabled):
#   [M1] bitsandbytes AdamW8bit            (optimizer states ~4x smaller)
#   [M2] gradient checkpointing            (activations recomputed in backward)
#   [M3] fp16 frozen base weights + autocast + GradScaler (T4 has no native bf16)
#   [M4] LoRA params only (r=16) in fp32, base model frozen (no grads / no states)
#   [M5] pre-computed latents & embeddings, VAE/T5 freed before training
#   [M6] batch size 1 + gradient accumulation, SDPA memory-efficient attention
#   [M7] low train resolution/frames (320x576x33), inference at 480p afterwards
#
#  Dataset layout:   dataset/clips/*.mp4     dataset/captions/*.txt  (same file stem)
#  Notebook: Accelerator = GPU T4 x1, Internet = ON
# =====================================================================
import os, sys, gc, io, json, math, time, random, shutil, subprocess, traceback
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

ROOT = "/kaggle/working" if os.path.isdir("/kaggle/working") else os.getcwd()
CFG = {
    "model_id": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
    "dataset_dir": os.path.join(ROOT, "dataset"),      # <- change if your data is in /kaggle/input/...
    "cache_dir": os.path.join(ROOT, "cache"),
    "out_dir": os.path.join(ROOT, "cinematic_lora"),
    "trigger": "cinematic film look, ",                # [Q7]
    # ---- training resolution (multiples of 16; frames must be 4k+1) ----
    "train_w": 576, "train_h": 320, "train_frames": 33, "train_fps": 16,
    "max_segments_per_clip": 4,                        # cut long clips into several training windows
    # ---- LoRA ----
    "lora_r": 16, "lora_alpha": 32, "lora_dropout": 0.0,
    # ---- optimisation ----
    "precision": "fp16",                               # "fp16" (T4 default) or "bf16" (NaN-safe fallback, slower)
    "lr": 1e-4, "weight_decay": 1e-2, "warmup_steps": 20,
    "max_steps": 400, "grad_accum": 2, "grad_clip": 1.0,
    "ema_decay": 0.99, "save_every": 100,
    "max_minutes": 420,                                # hard time budget (Kaggle session safety)
    # ---- flow-matching schedule [Q3] ----
    "flow_shift": 5.0, "logit_mean": 0.0, "logit_std": 1.0,
    "caption_dropout": 0.10,
    # ---- extra losses [Q5] ----
    "lambda_grad": 0.10, "lambda_temporal": 0.10,
    # ---- curation [Q1] ----
    "drop_lowest_percent": 15, "max_jump": 0.30, "min_motion": 0.003,
    # ---- final test ----
    "test_prompts": [
        "A lone astronaut walks across red desert dunes at sunset, dust blowing in the wind, slow dolly shot",
        "A rainy neon-lit city street at night, a woman in a trench coat walks toward the camera, reflections on wet asphalt",
    ],
    "test_w": 832, "test_h": 480, "test_frames": 49,   # 49 frames @16fps = ~3 seconds
    "test_steps": 40, "test_guidance": 6.0, "test_seed": 42,
    "seed": 1234,
}

def run(cmd):
    print("$", " ".join(cmd)); subprocess.run(cmd, check=True)

# torch / torchvision are NOT touched -> no ABI conflicts on Kaggle
run([sys.executable, "-m", "pip", "install", "-q", "diffusers>=0.33.0", "transformers>=4.49",
     "accelerate", "peft>=0.14.0", "bitsandbytes", "ftfy", "sentencepiece", "imageio", "imageio-ffmpeg"])

import numpy as np
import cv2
import torch
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler

DTYPE = torch.float16 if CFG["precision"] == "fp16" else torch.bfloat16
DEV = "cuda"
os.makedirs(CFG["cache_dir"], exist_ok=True)
os.makedirs(CFG["out_dir"], exist_ok=True)

def seed_all(s):
    random.seed(s); np.random.seed(s); torch.manual_seed(s); torch.cuda.manual_seed_all(s)

def free_gpu():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache(); torch.cuda.ipc_collect()

# ======================= [Q1][Q2] DATA: CURATE + CACHE LATENTS =======================
def fit_cover(img, W, H):
    h, w = img.shape[:2]
    s = max(W / w, H / h)
    nw, nh = int(round(w * s)), int(round(h * s))
    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    x0, y0 = (nw - W) // 2, (nh - H) // 2
    return img[y0:y0 + H, x0:x0 + W]

def read_segments(path, n_frames, W, H, target_fps, max_segments):
    """Yield uint8 arrays (F,H,W,3): consecutive windows resampled to ~target_fps."""
    cap = cv2.VideoCapture(path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    stride = max(1, int(round(fps / target_fps)))
    need = (n_frames - 1) * stride + 1
    if total < need * 0.75:
        cap.release(); return
    n_seg = max(1, min(max_segments, total // need))
    for s in range(n_seg):
        cap.set(cv2.CAP_PROP_POS_FRAMES, s * need)
        buf = []
        for _ in range(need):
            ok, fr = cap.read()
            if not ok: break
            buf.append(fit_cover(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB), W, H))
        if len(buf) < need * 0.75:
            break
        buf = buf[::stride]
        while len(buf) < n_frames:
            buf.append(buf[-1])
        yield np.stack(buf[:n_frames])
    cap.release()

def analyze(frames):
    g = [cv2.cvtColor(f, cv2.COLOR_RGB2GRAY) for f in frames[::max(1, len(frames) // 6)]]
    sharp = float(np.mean([cv2.Laplacian(x, cv2.CV_64F).var() for x in g]))
    small = frames[:, ::4, ::4].astype(np.float32) / 255.0
    diffs = np.abs(np.diff(small, axis=0)).mean(axis=(1, 2, 3))
    luma = small.mean(axis=3)
    return dict(sharp=sharp, motion=float(diffs.mean()), max_jump=float(diffs.max()),
                contrast=float(luma.std(axis=(1, 2)).mean()), mean_luma=float(luma.mean()),
                flicker=float(luma.mean(axis=(1, 2)).std()))

def build_latent_cache():
    from diffusers import AutoencoderKLWan
    clips_dir = os.path.join(CFG["dataset_dir"], "clips")
    caps_dir = os.path.join(CFG["dataset_dir"], "captions")
    clips = sorted(f for f in os.listdir(clips_dir) if f.lower().endswith(".mp4")) if os.path.isdir(clips_dir) else []
    if not clips:
        raise FileNotFoundError(f"No mp4 files in {clips_dir}. Expected dataset/clips/*.mp4 + dataset/captions/*.txt")
    index_path = os.path.join(CFG["cache_dir"], "index.json")
    if os.path.exists(index_path):
        print("[Data] cache found, reusing"); return json.load(open(index_path))

    vae = AutoencoderKLWan.from_pretrained(CFG["model_id"], subfolder="vae", torch_dtype=torch.float32).to(DEV)
    vae.eval()
    zdim = vae.config.z_dim
    mean = torch.tensor(vae.config.latents_mean).view(1, zdim, 1, 1, 1).to(DEV)
    inv_std = (1.0 / torch.tensor(vae.config.latents_std)).view(1, zdim, 1, 1, 1).to(DEV)

    index = []
    for ci, fn in enumerate(clips):
        stem = os.path.splitext(fn)[0]
        cap_path = os.path.join(caps_dir, stem + ".txt")
        if not os.path.exists(cap_path):
            print(f"[Data] skip {fn}: no caption"); continue
        caption = open(cap_path, encoding="utf-8").read().strip()
        for si, frames in enumerate(read_segments(os.path.join(clips_dir, fn), CFG["train_frames"],
                                                  CFG["train_w"], CFG["train_h"], CFG["train_fps"],
                                                  CFG["max_segments_per_clip"])):
            m = analyze(frames)
            bad = (m["max_jump"] > CFG["max_jump"] or m["motion"] < CFG["min_motion"]
                   or m["mean_luma"] < 0.05 or m["mean_luma"] > 0.92)
            if bad:
                print(f"[Data] reject {fn}#{si} (cut/static/exposure) {m}"); continue
            vid = torch.from_numpy(frames).permute(3, 0, 1, 2).unsqueeze(0).float().div(127.5).sub(1.0).to(DEV)
            with torch.no_grad():
                lat = vae.encode(vid).latent_dist.mode()
                lat = ((lat - mean) * inv_std).squeeze(0).to(torch.float16).cpu()
            lp = os.path.join(CFG["cache_dir"], f"lat_{ci:04d}_{si}.pt")
            torch.save(lat, lp)
            score = math.log1p(m["sharp"]) + 3.0 * m["contrast"] - 10.0 * m["flicker"]
            index.append(dict(lat=lp, caption=caption, score=score, **m))
        print(f"[Data] {fn} done ({len(index)} segments so far)")
    del vae; free_gpu()

    if not index:
        raise RuntimeError("All clips were rejected or captions missing.")
    # [Q1] drop lowest scores, weight the rest by quality rank
    scores = np.array([e["score"] for e in index])
    thr = np.percentile(scores, CFG["drop_lowest_percent"]) if len(index) > 5 else -1e9
    ranks = scores.argsort().argsort() / max(1, len(scores) - 1)
    for e, r in zip(index, ranks):
        e["keep"] = bool(e["score"] >= thr)
        e["weight"] = float(0.5 + r) if e["keep"] else 0.0
    print(f"[Data] kept {sum(e['keep'] for e in index)}/{len(index)} segments")
    json.dump(index, open(index_path, "w"))
    return index

# ======================= [Q2] TEXT EMBEDDING CACHE (T5 freed afterwards) =======================
def build_text_cache(index):
    from transformers import AutoTokenizer, UMT5EncoderModel
    todo = sorted({CFG["trigger"] + e["caption"] for e in index if e["keep"]} | {""})
    paths = {t: os.path.join(CFG["cache_dir"], f"emb_{abs(hash(t)) % (10**12)}.pt") for t in todo}
    if all(os.path.exists(p) for p in paths.values()):
        return paths
    tok = AutoTokenizer.from_pretrained(CFG["model_id"], subfolder="tokenizer")
    enc = UMT5EncoderModel.from_pretrained(CFG["model_id"], subfolder="text_encoder",
                                           torch_dtype=torch.bfloat16).to(DEV).eval()
    for t, p in paths.items():
        ids = tok(t, padding="max_length", max_length=512, truncation=True,
                  add_special_tokens=True, return_attention_mask=True, return_tensors="pt")
        seq = int(ids.attention_mask.gt(0).sum())
        with torch.no_grad():
            emb = enc(ids.input_ids.to(DEV), ids.attention_mask.to(DEV)).last_hidden_state[0, :seq]
        emb = torch.cat([emb, emb.new_zeros(512 - emb.size(0), emb.size(1))])   # same padding as WanPipeline
        torch.save(emb.to(torch.float16).cpu(), p)
    del enc, tok; free_gpu()
    print(f"[Text] cached {len(paths)} embeddings")
    return paths

class CachedDataset(Dataset):
    def __init__(self, index, emb_paths):
        self.items = [e for e in index if e["keep"]]
        self.emb_paths = emb_paths
        self.empty = torch.load(emb_paths[""])
    def __len__(self): return len(self.items)
    def __getitem__(self, i):
        e = self.items[i]
        lat = torch.load(e["lat"])
        # [Q4] caption dropout keeps unconditional branch alive for CFG
        if random.random() < CFG["caption_dropout"]:
            emb = self.empty
        else:
            emb = torch.load(self.emb_paths[CFG["trigger"] + e["caption"]])
        return lat, emb

# ======================= MODEL: Wan transformer + LoRA =======================
def setup_transformer():
    from diffusers import WanTransformer3DModel
    from peft import LoraConfig
    tr = WanTransformer3DModel.from_pretrained(CFG["model_id"], subfolder="transformer", torch_dtype=DTYPE)
    tr.requires_grad_(False)                                          # [M4] base frozen
    lcfg = LoraConfig(r=CFG["lora_r"], lora_alpha=CFG["lora_alpha"], lora_dropout=CFG["lora_dropout"],
                      init_lora_weights=True,
                      target_modules=["to_q", "to_k", "to_v", "to_out.0",          # self + cross attention
                                      "ffn.net.0.proj", "ffn.net.2"])              # feed-forward
    tr.add_adapter(lcfg)
    for p in tr.parameters():                                         # [M4] LoRA weights in fp32 (stable updates)
        if p.requires_grad:
            p.data = p.data.float()
    tr.enable_gradient_checkpointing()                                # [M2]
    tr.to(DEV).train()
    params = [p for p in tr.parameters() if p.requires_grad]
    print(f"[Model] trainable LoRA params: {sum(p.numel() for p in params)/1e6:.2f}M  "
          f"VRAM after load: {torch.cuda.memory_allocated()/2**30:.2f} GB")
    return tr, params

class EMA:                                                             # [Q6]
    def __init__(self, params, decay):
        self.decay, self.n = decay, 0
        self.shadow = [p.detach().clone() for p in params]
        self.backup = None
    @torch.no_grad()
    def update(self, params):
        self.n += 1
        d = min(self.decay, (1 + self.n) / (10 + self.n))
        for s, p in zip(self.shadow, params):
            s.mul_(d).add_(p.detach(), alpha=1 - d)
    @torch.no_grad()
    def swap_in(self, params):
        self.backup = [p.detach().clone() for p in params]
        for s, p in zip(self.shadow, params): p.data.copy_(s)
    @torch.no_grad()
    def restore(self, params):
        for b, p in zip(self.backup, params): p.data.copy_(b)
        self.backup = None

def save_lora(tr, ema, params, path):
    from diffusers import WanPipeline
    from diffusers.utils import convert_state_dict_to_diffusers
    from peft.utils import get_peft_model_state_dict
    os.makedirs(path, exist_ok=True)
    ema.swap_in(params)
    try:
        state = convert_state_dict_to_diffusers(get_peft_model_state_dict(tr))
        try:
            WanPipeline.save_lora_weights(path, transformer_lora_layers=state)
        except Exception as e:
            print("[Save] save_lora_weights failed, raw torch.save fallback:", e)
            torch.save(state, os.path.join(path, "pytorch_lora_weights.pt"))
    finally:
        ema.restore(params)
    print("[Save] LoRA saved ->", path)

# ======================= LOSS =======================
def sample_sigma(b):
    """[Q3] logit-normal sampling + timestep shift (same family as SD3/Wan flow matching)."""
    u = torch.sigmoid(torch.randn(b, device=DEV) * CFG["logit_std"] + CFG["logit_mean"])
    s = CFG["flow_shift"]
    return (s * u / (1 + (s - 1) * u)).clamp(1e-3, 1 - 1e-3)

def spatial_grad(x):
    return x[..., :, 1:] - x[..., :, :-1], x[..., 1:, :] - x[..., :-1, :]

def compute_loss(tr, lat, emb):
    lat = lat.to(DEV, torch.float32)
    emb = emb.to(DEV, DTYPE)
    noise = torch.randn_like(lat)
    sigma = sample_sigma(lat.shape[0])
    sb = sigma.view(-1, 1, 1, 1, 1)
    noisy = (1 - sb) * lat + sb * noise                              # flow matching interpolation
    target = noise - lat                                             # velocity target
    noisy_in = noisy.to(DTYPE).requires_grad_(True)                  # keeps grads flowing through checkpoints
    with torch.autocast("cuda", dtype=DTYPE):                        # [M3]
        pred = tr(hidden_states=noisy_in, timestep=sigma * 1000.0,
                  encoder_hidden_states=emb, return_dict=False)[0]
    pred = pred.float()
    loss_main = F.mse_loss(pred, target)
    # [Q5] detail + motion losses on the reconstructed clean latent
    x0p = noisy - sb * pred
    w = float((1 - sigma).mean())
    gx_p, gy_p = spatial_grad(x0p); gx_t, gy_t = spatial_grad(lat)
    loss_grad = F.l1_loss(gx_p, gx_t) + F.l1_loss(gy_p, gy_t)
    loss_temp = F.l1_loss(x0p[:, :, 1:] - x0p[:, :, :-1], lat[:, :, 1:] - lat[:, :, :-1])
    loss = loss_main + w * (CFG["lambda_grad"] * loss_grad + CFG["lambda_temporal"] * loss_temp)
    return loss, loss_main.item()

# ======================= TRAIN =======================
def train(tr, params, ds):
    import bitsandbytes as bnb
    from diffusers.optimization import get_cosine_schedule_with_warmup
    opt = bnb.optim.AdamW8bit(params, lr=CFG["lr"], betas=(0.9, 0.999),
                              weight_decay=CFG["weight_decay"])      # [M1]
    sched = get_cosine_schedule_with_warmup(opt, CFG["warmup_steps"], CFG["max_steps"])
    scaler = torch.amp.GradScaler("cuda", enabled=(DTYPE == torch.float16))
    ema = EMA(params, CFG["ema_decay"])
    n_micro = CFG["max_steps"] * CFG["grad_accum"]
    weights = [e["weight"] for e in ds.items]
    sampler = WeightedRandomSampler(weights, num_samples=n_micro, replacement=True)   # [Q1] quality-weighted
    dl = DataLoader(ds, batch_size=1, sampler=sampler, num_workers=0)                 # [M6]
    t0, step, micro, bad, run_loss = time.time(), 0, 0, 0, None
    for lat, emb in dl:
        try:
            loss, lm = compute_loss(tr, lat, emb)
        except torch.cuda.OutOfMemoryError:
            print("[Train] OOM on a micro-step -> skipped (lower train_w/train_h/train_frames if frequent)")
            opt.zero_grad(set_to_none=True); free_gpu(); continue
        if not torch.isfinite(loss):
            bad += 1; print(f"[Train] non-finite loss ({bad})")
            if bad > 20: raise RuntimeError("Too many NaN losses: set CFG['precision']='bf16' and rerun")
            opt.zero_grad(set_to_none=True); continue
        scaler.scale(loss / CFG["grad_accum"]).backward()
        micro += 1
        run_loss = lm if run_loss is None else 0.98 * run_loss + 0.02 * lm
        if micro % CFG["grad_accum"] == 0:
            scaler.unscale_(opt)
            gn = torch.nn.utils.clip_grad_norm_(params, CFG["grad_clip"])
            scaler.step(opt); scaler.update(); sched.step()
            opt.zero_grad(set_to_none=True)
            ema.update(params)
            step += 1
            if step % 10 == 0 or step == 1:
                el = (time.time() - t0) / 60
                print(f"[Train] step {step}/{CFG['max_steps']}  loss~{run_loss:.4f}  gn={float(gn):.2f}  "
                      f"lr={sched.get_last_lr()[0]:.2e}  VRAM peak={torch.cuda.max_memory_allocated()/2**30:.1f}GB  "
                      f"{el:.1f}min (ETA {el/step*(CFG['max_steps']-step):.0f}min)")
            if step % CFG["save_every"] == 0:
                save_lora(tr, ema, params, os.path.join(CFG["out_dir"], f"step_{step}"))
            if (time.time() - t0) / 60 > CFG["max_minutes"]:
                print("[Train] time budget reached, stopping"); break
    save_lora(tr, ema, params, os.path.join(CFG["out_dir"], "final"))
    ema.swap_in(params)                                                # final test uses EMA weights
    del opt, sched, scaler, dl; free_gpu()
    return ema

# ======================= FINAL TEST: 3-second A/B video =======================
def final_test(tr):
    from diffusers import AutoencoderKLWan, WanPipeline, UniPCMultistepScheduler
    from diffusers.utils import export_to_video
    tr.eval(); tr.requires_grad_(False)
    try: tr.disable_gradient_checkpointing()
    except Exception: pass
    tr.to("cpu"); tr.to(DTYPE); free_gpu()                             # fp16 LoRA for inference
    vae = AutoencoderKLWan.from_pretrained(CFG["model_id"], subfolder="vae", torch_dtype=torch.float32)
    pipe = WanPipeline.from_pretrained(CFG["model_id"], transformer=tr, vae=vae, torch_dtype=DTYPE)
    pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config, flow_shift=CFG["flow_shift"])
    pipe.enable_model_cpu_offload()
    try: pipe.vae.enable_tiling()
    except Exception: pass
    neg = ("Bright tones, overexposed, static, blurred details, subtitles, worst quality, low quality, "
           "JPEG compression residue, ugly, deformed, disfigured, extra fingers, poorly drawn hands, "
           "poorly drawn faces, still picture, messy background, walking backwards")
    outs = []
    for i, p in enumerate(CFG["test_prompts"]):
        prompt = CFG["trigger"] + p
        res = {}
        for tag, on in (("base", False), ("lora", True)):
            (tr.enable_adapters if on else tr.disable_adapters)()
            frames = pipe(prompt=prompt, negative_prompt=neg, height=CFG["test_h"], width=CFG["test_w"],
                          num_frames=CFG["test_frames"], num_inference_steps=CFG["test_steps"],
                          guidance_scale=CFG["test_guidance"],
                          generator=torch.Generator("cpu").manual_seed(CFG["test_seed"] + i),
                          output_type="np").frames[0]
            res[tag] = np.asarray(frames, dtype=np.float32)
            path = os.path.join(CFG["out_dir"], f"test{i}_{tag}.mp4")
            export_to_video(list(res[tag]), path, fps=16)
            free_gpu()
        side = np.concatenate([res["base"], res["lora"]], axis=2)       # left = base, right = LoRA
        sp = os.path.join(CFG["out_dir"], f"test{i}_BASE_vs_LORA.mp4")
        export_to_video(list(side), sp, fps=16)
        outs.append(sp)
        print("[Test] saved", sp)
    tr.enable_adapters()
    return outs

# ======================= MAIN =======================
def main():
    seed_all(CFG["seed"])
    print("GPU:", torch.cuda.get_device_name(0))
    index = build_latent_cache()
    emb_paths = build_text_cache(index)
    ds = CachedDataset(index, emb_paths)
    print(f"[Data] training segments: {len(ds)}")
    tr, params = setup_transformer()
    train(tr, params, ds)
    try:
        final_test(tr)
    except Exception as e:
        print("[Test] failed (LoRA is already saved):", e); traceback.print_exc()
    print("\nDONE. LoRA ->", os.path.join(CFG["out_dir"], "final"))
    print("Use it later:\n  pipe.load_lora_weights('%s/final'); prompt = '%s' + your_prompt"
          % (CFG["out_dir"], CFG["trigger"]))

if __name__ == "__main__":
    main()
