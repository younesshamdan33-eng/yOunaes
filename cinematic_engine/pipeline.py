"""
Cinematic Video Generation Pipeline for CINEMA AI (Wan 2.1 T2V 1.3B).
Supports single-shot and multi-shot continuous generation (5 to 30 seconds)
with visual continuity, prompt enrichment, and optional postprocessing.
"""
import os
import time
from pathlib import Path
from typing import Optional, List

try:
    from .config import CinematicConfig
    from .generator import WanGenerator
    from .postprocess import run_postprocess, frames_to_video
    from .timeline import TimelineManager
except (ImportError, ValueError):
    from config import CinematicConfig
    from generator import WanGenerator
    from postprocess import run_postprocess, frames_to_video
    from timeline import TimelineManager

def run_cinematic_engine(user_prompt: str, cfg: Optional[CinematicConfig] = None, output_name: str = "scene_01") -> str:
    """
    Executes the generation pipeline. If target duration is 5s, runs single shot.
    If target duration > 5s (up to 30s), orchestrates multi-shot generation and stitches
    into a single continuous video.
    """
    cfg = cfg or CinematicConfig()
    os.makedirs(cfg.output_dir, exist_ok=True)

    target_duration = getattr(cfg, "target_duration", 5)
    gen = WanGenerator(cfg)

    if target_duration <= 5:
        frames = gen.generate(user_prompt)
        raw_path = os.path.join(cfg.output_dir, f"{output_name}_raw.mp4")
        frames_to_video(frames, raw_path, cfg.fps)
        final_path = run_postprocess(frames, cfg, raw_path)
        return final_path

    # Multi-shot generation for durations between 6 and 30 seconds
    tm = TimelineManager(shot_seconds=5)
    plan = tm.plan_timeline(
        user_prompt=user_prompt,
        target_seconds=target_duration,
        style=getattr(cfg, "look", "cinematic_realistic"),
        base_seed=cfg.seed,
    )

    shot_files: List[Path] = []
    for shot in plan.shots:
        shot_out_name = f"{output_name}_shot_{shot.shot_index:02d}"
        shot_raw_path = Path(cfg.output_dir) / f"{shot_out_name}_raw.mp4"

        # Update generator seed and shot type for this sequence shot
        cfg.seed = shot.seed_offset
        cfg.shot_type = shot.shot_type
        cfg.camera_motion = shot.camera_motion

        frames = gen.generate(shot.prompt, negative_prompt=shot.negative_prompt, already_built=True)
        frames_to_video(frames, str(shot_raw_path), cfg.fps)
        shot_final_path = run_postprocess(frames, cfg, str(shot_raw_path))
        shot_files.append(Path(shot_final_path))

    # Stitch all shot videos into a single continuous MP4 video file
    stitched_output = Path(cfg.output_dir) / f"{output_name}_cinematic.mp4"
    final_stitched = tm.stitch_shots(shot_files, stitched_output)
    return str(final_stitched)
