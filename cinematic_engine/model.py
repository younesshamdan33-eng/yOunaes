"""
Unified CINEMA AI Model Architecture Wrapper.
Wraps the base Wan 2.1 T2V 1.3B model, managing foundation weights, specialized internal
adapters for the 5 visual capabilities, CPU offloading, VAE tiling, and seamless inference.
"""
from __future__ import annotations
import os
import gc
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List

try:
    from .config import CinematicConfig
    from .prompt_engineer import resolve_style, build_cinematic_prompts
except (ImportError, ValueError):
    from config import CinematicConfig
    from prompt_engineer import resolve_style, build_cinematic_prompts

@dataclass
class CinemaAIModelConfig:
    model_id: str = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
    device: str = "cuda"
    dtype: str = "float16"
    enable_cpu_offload: bool = True
    vae_tiling: bool = True
    active_style: str = "cinematic_realistic"
    adapter_paths: Dict[str, str] = None

class CinemaAIModel:
    """
    Unified CINEMA AI model instance providing specialized generation capabilities
    over the core Wan 2.1 T2V 1.3B foundation.
    """

    def __init__(self, config: Optional[CinemaAIModelConfig] = None):
        self.config = config or CinemaAIModelConfig()
        self.pipe = None
        self._loaded_adapters: Dict[str, str] = {}

    def load(self):
        """Loads Wan 2.1 T2V 1.3B pipeline with memory optimizations."""
        try:
            import torch
            from diffusers import WanPipeline, AutoencoderKLWan
        except ImportError:
            raise RuntimeError("diffusers and torch required to load CinemaAIModel")

        dtype = torch.float16 if self.config.dtype == "float16" else torch.bfloat16
        vae = AutoencoderKLWan.from_pretrained(
            self.config.model_id,
            subfolder="vae",
            torch_dtype=dtype,
        )
        self.pipe = WanPipeline.from_pretrained(
            self.config.model_id,
            vae=vae,
            torch_dtype=dtype,
        )

        if self.config.enable_cpu_offload:
            self.pipe.enable_model_cpu_offload()
        else:
            self.pipe.to(self.config.device)

        if self.config.vae_tiling and hasattr(self.pipe.vae, "enable_tiling"):
            self.pipe.vae.enable_tiling()

    def load_style_adapter(self, style_name: str, adapter_path: str):
        """Loads an internal PEFT LoRA adapter for a specific style capability."""
        canonical_style, _ = resolve_style(style_name)
        if not Path(adapter_path).exists():
            raise FileNotFoundError(f"Adapter not found at {adapter_path}")

        if self.pipe is None:
            self.load()

        try:
            self.pipe.load_lora_weights(adapter_path, adapter_name=canonical_style)
            self._loaded_adapters[canonical_style] = adapter_path
        except Exception as e:
            # PEFT manual fallback
            from peft import LoraConfig, set_peft_model_state_dict
            import torch
            d = torch.load(adapter_path, map_location="cpu", weights_only=False)
            if "lora_config" in d and "lora" in d:
                self.pipe.transformer.add_adapter(LoraConfig(**d["lora_config"]), adapter_name=canonical_style)
                set_peft_model_state_dict(self.pipe.transformer, d["lora"], adapter_name=canonical_style)
                self._loaded_adapters[canonical_style] = adapter_path

    def activate_capability(self, style_name: str):
        """Activates one of the 5 specialized cinematic visual capabilities."""
        canonical_style, _ = resolve_style(style_name)
        self.config.active_style = canonical_style
        if self.pipe is not None and hasattr(self.pipe, "set_adapters") and canonical_style in self._loaded_adapters:
            self.pipe.set_adapters([canonical_style])

    def generate_shot(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        height: int = 480,
        width: int = 832,
        num_frames: int = 49,
        steps: int = 25,
        guidance_scale: float = 5.0,
        seed: int = 42,
    ):
        """Generates a single video shot using the active CINEMA AI configuration."""
        import torch
        if self.pipe is None:
            self.load()

        generator = torch.Generator(device="cpu").manual_seed(seed)
        res = self.pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            height=height,
            width=width,
            num_frames=num_frames,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            generator=generator,
        )
        return res.frames[0] if isinstance(res.frames, list) else res.frames
