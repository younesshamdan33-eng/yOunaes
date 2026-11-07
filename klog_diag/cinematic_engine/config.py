import os
from dataclasses import dataclass
from typing import Optional, Literal

@dataclass
class CinematicConfig:
    model_id: str = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
    height: int = 720
    width: int = 1280
    num_frames: int = 81
    fps: int = 24
    num_inference_steps: int = 30
    guidance_scale: float = 5.0
    seed: int = 42
    negative_prompt: str = (
        "blurry, low quality, distorted, deformed, flickering, ghosting, "
        "warping, oversaturated, plastic skin, unnatural lighting, text, watermark"
    )
    look: str = "natural"
    lighting: str = "natural"
    shot_type: str = "medium"
    camera_motion: str = "static"
    lens: str = "normal"
    depth_of_field: str = "shallow"
    color_grade: str = "natural_flat_standard"
    color_intensity: float = 0.7
    enable_face_restore: bool = False
    face_restore_fidelity: float = 0.7
    enable_upscale: bool = True
    upscale_factor: int = 2
    upscaler: str = "real_esrgan"
    enable_frame_interpolation: bool = True
    target_fps: int = 60
    enable_stabilization: bool = False
    preserve_original: bool = True
    device: str = "cuda"
    dtype: str = "float16"
    enable_cpu_offload: bool = True
    vae_tiling: bool = True
    output_dir: str = "./outputs"
    stable_model_dir: str = "./stable_models"
    cache_dir: str = "./cache"

    def __post_init__(self):
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.stable_model_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
