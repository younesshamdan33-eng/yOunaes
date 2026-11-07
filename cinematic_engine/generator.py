import torch
from diffusers import WanPipeline, AutoencoderKLWan
from config import CinematicConfig
from prompt_engineer import build_cinematic_prompt

class WanGenerator:
    def __init__(self, cfg: CinematicConfig):
        self.cfg = cfg
        self.pipe = None
    def load(self):
        dtype = torch.float16 if self.cfg.dtype == "float16" else torch.bfloat16
        print(f"[Generator] Loading {self.cfg.model_id} ...")
        vae = AutoencoderKLWan.from_pretrained(self.cfg.model_id, subfolder="vae", torch_dtype=dtype, cache_dir=self.cfg.cache_dir)
        self.pipe = WanPipeline.from_pretrained(self.cfg.model_id, vae=vae, torch_dtype=dtype, cache_dir=self.cfg.cache_dir)
        if self.cfg.enable_cpu_offload:
            self.pipe.enable_model_cpu_offload()
        else:
            self.pipe.to(self.cfg.device)
        if self.cfg.vae_tiling:
            try: self.pipe.vae.enable_tiling()
            except Exception: pass
        print("[Generator] Model loaded.")
    @torch.inference_mode()
    def generate(self, user_prompt: str, negative_prompt: str = None):
        if self.pipe is None: self.load()
        prompt = build_cinematic_prompt(user_prompt, self.cfg)
        neg = negative_prompt or self.cfg.negative_prompt
        generator = torch.Generator(device="cpu").manual_seed(self.cfg.seed)
        result = self.pipe(prompt=prompt, negative_prompt=neg, height=self.cfg.height, width=self.cfg.width, num_frames=self.cfg.num_frames, num_inference_steps=self.cfg.num_inference_steps, guidance_scale=self.cfg.guidance_scale, generator=generator)
        return result.frames[0] if isinstance(result.frames, list) else result.frames
