import os, time
from config import CinematicConfig
from generator import WanGenerator
from postprocess import run_postprocess, frames_to_video
def run_cinematic_engine(user_prompt, cfg=None, output_name="scene_01"):
    cfg = cfg or CinematicConfig()
    gen = WanGenerator(cfg)
    frames = gen.generate(user_prompt)
    raw_path = os.path.join(cfg.output_dir, f"{output_name}_raw.mp4")
    frames_to_video(frames, raw_path, cfg.fps)
    final_path = run_postprocess(frames, cfg, raw_path)
    return final_path
