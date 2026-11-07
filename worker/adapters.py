"""Inference adapters. torch/diffusers are imported lazily, so the API, registry and tests run on any machine."""
import subprocess, threading

class Cancelled(Exception):
    pass

class Adapter:
    def generate(self, params, out, progress, cancelled):
        raise NotImplementedError

class FakeAdapter(Adapter):
    """Tests only (CW_ENABLE_FAKE=1): synthetic pattern. This is NOT AI generation."""
    def generate(self, p, out, progress, cancelled):
        if cancelled():
            raise Cancelled()
        secs = p["num_frames"] / p["fps"]
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=%dx%d:rate=%d:duration=%.3f" % (p["width"], p["height"], p["fps"], secs),
                            "-pix_fmt", "yuv420p", str(out)], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg failed: " + (r.stderr or "")[-200:])
        progress(1, 1)

class _Diffusers(Adapter):
    def __init__(self, cfg):
        self.cfg, self._lock, self._key, self._pipe = cfg, threading.Lock(), None, None
    def _release(self):
        self._pipe, self._key = None, None
        try:
            import gc, torch
            gc.collect(); torch.cuda.empty_cache()
        except Exception:
            pass
    @staticmethod
    def _callback(progress, cancelled, steps):
        def cb(pipe, step, timestep, kwargs):
            if cancelled():
                raise Cancelled()
            progress(step + 1, steps)
            return kwargs
        return cb
    @staticmethod
    def _export(frames, out, fps):
        from diffusers.utils import export_to_video
        export_to_video(frames, str(out), fps=fps)
    @staticmethod
    def _place(pipe):
        import torch
        total = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
        pipe.to("cuda") if total >= 40 else pipe.enable_model_cpu_offload()

class DiffusersWan(_Diffusers):
    """Wan 2.2 TI2V 5B via Diffusers WanPipeline (usage per the official model card). Text-to-video only."""
    def generate(self, p, out, progress, cancelled):
        import torch
        from diffusers import AutoencoderKLWan, WanPipeline
        with self._lock:
            if self._key != p["model"]:
                self._release()
                path = str(self.cfg.models_dir / p["model"])
                vae = AutoencoderKLWan.from_pretrained(path, subfolder="vae", torch_dtype=torch.float32)
                pipe = WanPipeline.from_pretrained(path, vae=vae, torch_dtype=torch.bfloat16)
                self._place(pipe)
                self._pipe, self._key = pipe, p["model"]
            pipe = self._pipe
        frames = pipe(prompt=p["prompt"], negative_prompt=p["negative_prompt"] or None, height=p["height"], width=p["width"],
                      num_frames=p["num_frames"], guidance_scale=p["guidance"], num_inference_steps=p["steps"],
                      generator=torch.Generator(device="cpu").manual_seed(p["seed"]),
                      callback_on_step_end=self._callback(progress, cancelled, p["steps"])).frames[0]
        self._export(frames, out, p["fps"])

class DiffusersLTX(_Diffusers):
    """LTX-Video via Diffusers LTXPipeline (usage per the Diffusers docs). Text-to-video only. Not yet run on a GPU by this project."""
    def generate(self, p, out, progress, cancelled):
        import torch
        from diffusers import LTXPipeline
        with self._lock:
            if self._key != p["model"]:
                self._release()
                pipe = LTXPipeline.from_pretrained(str(self.cfg.models_dir / p["model"]), torch_dtype=torch.bfloat16)
                self._place(pipe)
                self._pipe, self._key = pipe, p["model"]
            pipe = self._pipe
        frames = pipe(prompt=p["prompt"], negative_prompt=p["negative_prompt"] or None, width=p["width"], height=p["height"],
                      num_frames=p["num_frames"], guidance_scale=p["guidance"], num_inference_steps=p["steps"],
                      generator=torch.Generator(device="cpu").manual_seed(p["seed"]),
                      callback_on_step_end=self._callback(progress, cancelled, p["steps"])).frames[0]
        self._export(frames, out, p["fps"])

def default_adapters(cfg):
    a = {"diffusers_wan": DiffusersWan(cfg), "diffusers_ltx": DiffusersLTX(cfg)}
    if cfg.enable_fake:
        a["fake"] = FakeAdapter()
    return a
