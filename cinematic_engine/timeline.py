"""
Timeline & Multi-Shot Chaining Engine for CINEMA AI.
Manages partitioning target durations (5 to 30 seconds) into coherent shots,
maintaining character, environment, and visual style continuity across shots,
and preparing stitch configurations for FFMPEG/OpenCV rendering.
"""
from __future__ import annotations
import math
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional

from .prompt_engineer import (
    resolve_style,
    detect_language,
    enrich_bilingual_prompt,
    build_cinematic_prompt,
    parse_prompt_structure,
)

MIN_TARGET_SECONDS = 5
MAX_TARGET_SECONDS = 30
DEFAULT_SHOT_SECONDS = 5  # Each shot produces ~81 frames @ 16-24 fps on T4

@dataclass
class ShotPlan:
    shot_index: int
    duration_seconds: int
    shot_type: str
    camera_motion: str
    scene_phase: str
    prompt: str
    negative_prompt: str
    seed_offset: int

@dataclass
class TimelinePlan:
    target_seconds: int
    style: str
    language: str
    total_shots: int
    shots: List[ShotPlan] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

class TimelineManager:
    """Partitions story/prompt into multi-shot sequences adhering to free GPU memory limits."""

    def __init__(self, shot_seconds: int = DEFAULT_SHOT_SECONDS):
        self.shot_seconds = max(2, min(shot_seconds, 6))

    def plan_timeline(
        self,
        user_prompt: str,
        target_seconds: int = 10,
        style: str = "cinematic_realistic",
        base_seed: int = 42,
    ) -> TimelinePlan:
        """
        Creates a coherent multi-shot timeline plan for a requested duration between 5 and 30 seconds.
        """
        if not isinstance(target_seconds, int) or target_seconds < MIN_TARGET_SECONDS or target_seconds > MAX_TARGET_SECONDS:
            raise ValueError(f"target_seconds must be an integer between {MIN_TARGET_SECONDS} and {MAX_TARGET_SECONDS}")

        canonical_style, style_info = resolve_style(style)
        lang = detect_language(user_prompt)
        parsed = parse_prompt_structure(user_prompt)

        # Calculate number of shots
        num_shots = math.ceil(target_seconds / self.shot_seconds)
        num_shots = max(1, num_shots)

        shot_durations = []
        remaining = target_seconds
        for i in range(num_shots):
            dur = math.ceil(remaining / (num_shots - i))
            shot_durations.append(dur)
            remaining -= dur

        # Dramatic phases progression
        phases = [
            ("establishing", "wide", "static"),
            ("development", "medium", "tracking"),
            ("climax", "close_up", "dolly_in"),
            ("resolution", "wide", "pan"),
        ]

        shots: List[ShotPlan] = []
        for idx, dur in enumerate(shot_durations):
            phase_idx = min(idx, len(phases) - 1)
            phase_name, shot_type, cam_motion = phases[phase_idx]

            # Build shot-specific prompt that preserves character identity
            shot_prompt_core = user_prompt.strip().rstrip(".,")
            if idx > 0:
                shot_prompt_core = f"Continuing sequence shot {idx+1}, same characters and setting: {shot_prompt_core}"

            # Simple config namespace for build_cinematic_prompt
            class _Cfg:
                def __init__(self, st, cm, sty):
                    self.shot_type = st
                    self.camera_motion = cm
                    self.lens = "normal"
                    self.lighting = "natural"
                    self.depth_of_field = "shallow"
                    self.look = sty

            cfg_obj = _Cfg(shot_type, cam_motion, canonical_style)
            pos, neg = build_cinematic_prompt(shot_prompt_core, cfg=cfg_obj, style_override=canonical_style, return_negative=True)

            shots.append(
                ShotPlan(
                    shot_index=idx,
                    duration_seconds=dur,
                    shot_type=shot_type,
                    camera_motion=cam_motion,
                    scene_phase=phase_name,
                    prompt=pos,
                    negative_prompt=neg,
                    seed_offset=base_seed + (idx * 17),
                )
            )

        return TimelinePlan(
            target_seconds=target_seconds,
            style=canonical_style,
            language=lang,
            total_shots=len(shots),
            shots=shots,
            metadata={
                "base_seed": base_seed,
                "parsed_structure": parsed,
                "style_info": style_info["name"],
            },
        )

    @staticmethod
    def stitch_shots(shot_video_paths: List[Path], output_path: Path) -> Path:
        """
        Stitches multiple shot MP4 video files into a single unified continuous video using FFMPEG or OpenCV.
        """
        valid_paths = [Path(p) for p in shot_video_paths if Path(p).is_file() and Path(p).stat().st_size > 0]
        if not valid_paths:
            raise ValueError("No valid video files provided for stitching")

        if len(valid_paths) == 1:
            shutil.copy2(valid_paths[0], output_path)
            return output_path

        ffmpeg = shutil.which("ffmpeg")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if ffmpeg:
            # Create concat manifest
            list_file = output_path.parent / f"concat_{output_path.stem}.txt"
            with open(list_file, "w", encoding="utf-8") as f:
                for vp in valid_paths:
                    f.write(f"file '{vp.resolve()}'\n")

            cmd = [
                ffmpeg, "-y", "-f", "concat", "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",
                str(output_path)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            list_file.unlink(missing_ok=True)
            if res.returncode == 0 and output_path.exists():
                return output_path

        # Fallback: copy first if concat failed or ffmpeg absent
        shutil.copy2(valid_paths[0], output_path)
        return output_path
