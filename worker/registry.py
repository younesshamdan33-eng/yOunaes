"""Model registry. Facts tagged 'verified' come from the official model cards; everything else is marked."""
import random

PY_DIFFUSERS = ("torch", "diffusers", "transformers", "accelerate")

MODELS = {
    "wan2.2-ti2v-5b": dict(
        label="Wan 2.2 TI2V 5B", adapter="diffusers_wan", repo="Wan-AI/Wan2.2-TI2V-5B-Diffusers", license="Apache-2.0",
        status="integrated", needs_gpu=True, min_vram_gb=24, disk_gb=35, python=PY_DIFFUSERS, t2v=True, i2v=False,
        fps=24, max_seconds=5, frame_step=4, dims={"16:9": (1280, 704), "9:16": (704, 1280)}, res_label="720p",
        defaults=dict(steps=50, guidance=5.0),
        note="Verified (model card): 720p@24fps, Apache-2.0, 24 GB-class GPU for 720p, ~32 GB of weights. Image-to-video is not exposed until tested on a GPU. Not yet run on a GPU by this project."),
    "ltx-video": dict(
        label="LTX-Video", adapter="diffusers_ltx", repo="Lightricks/LTX-Video", license="see the model card (verify before commercial use)",
        status="integrated_unverified", needs_gpu=True, min_vram_gb=16, disk_gb=30, python=PY_DIFFUSERS, t2v=True, i2v=False,
        fps=24, max_seconds=6, frame_step=8, dims={"16:9": (704, 480), "9:16": (480, 704)}, res_label="480p",
        defaults=dict(steps=50, guidance=3.0),
        note="Follows the Diffusers docs. VRAM, disk and licence figures are NOT verified: measure on your GPU and edit this file. Not yet run on a GPU by this project."),
    "framepack": dict(label="FramePack", status="planned", note="Verified: 6 GB+ VRAM on RTX 30/40/50, >30 GB download, long videos. The official repo is a Gradio app without CLI/API, so a wrapper must be written and tested on a GPU. Licence not confirmed."),
    "stable-video-infinity": dict(label="Stable Video Infinity", status="planned", note="Not researched or integrated yet."),
    "ltx-2": dict(label="LTX-2", status="planned", note="Not researched or integrated yet."),
}
FAKE = dict(label="Test pattern (NOT AI)", adapter="fake", status="test_only", needs_gpu=False, min_vram_gb=None, disk_gb=0, python=(), t2v=True, i2v=False,
            fps=12, max_seconds=4, frame_step=1, dims={"16:9": (128, 72), "9:16": (72, 128)}, res_label="test", defaults=dict(steps=10, guidance=1.0),
            note="Synthetic pattern for automated tests only. Never real generation.")

def visible(cfg):
    out = dict(MODELS)
    if cfg.enable_fake:
        out["fake-motion"] = FAKE
    return out

def num_frames(spec, seconds):
    step = spec["frame_step"]
    n = spec["fps"] * seconds
    return round(n / step) * step + (1 if step > 1 else 0)

def normalize(spec, body):
    bad = ValueError
    if not isinstance(body, dict):
        raise bad("body must be an object")
    if body.get("task", "t2v") != "t2v" or not spec.get("t2v"):
        raise bad("only text-to-video (t2v) is available for this model")
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise bad("prompt is required")
    if len(prompt) > 2000:
        raise bad("prompt is too long (max 2000 characters)")
    neg = body.get("negative_prompt") or ""
    if not isinstance(neg, str) or len(neg) > 1000:
        raise bad("negative_prompt must be text up to 1000 characters")
    secs = body.get("seconds", min(5, spec["max_seconds"]))
    if isinstance(secs, bool) or not isinstance(secs, int) or not 1 <= secs <= spec["max_seconds"]:
        raise bad("seconds must be an integer between 1 and %d for this model" % spec["max_seconds"])
    ratio = body.get("aspect_ratio", "16:9")
    if ratio not in spec["dims"]:
        raise bad("aspect_ratio must be one of %s" % list(spec["dims"]))
    seed = body.get("seed")
    if seed is None:
        seed = random.randint(0, 2 ** 31 - 1)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2 ** 31 - 1:
        raise bad("seed must be an integer between 0 and 2147483647")
    d = spec["defaults"]
    steps = body.get("steps", d["steps"])
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 80:
        raise bad("steps must be an integer between 1 and 80")
    guidance = body.get("guidance", d["guidance"])
    if isinstance(guidance, bool) or not isinstance(guidance, (int, float)) or not 1 <= guidance <= 15:
        raise bad("guidance must be a number between 1 and 15")
    w_, h_ = spec["dims"][ratio]
    return dict(task="t2v", prompt=prompt.strip(), negative_prompt=neg.strip(), seconds=secs, aspect_ratio=ratio, width=w_, height=h_,
                fps=spec["fps"], num_frames=num_frames(spec, secs), seed=seed, steps=steps, guidance=float(guidance))
