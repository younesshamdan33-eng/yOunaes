import os
import shutil
import subprocess
import tempfile

import cv2
import numpy as np
from PIL import Image

from config import CinematicConfig


def _frame_to_bgr(img):
    arr = np.asarray(img)

    if arr.ndim == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    elif arr.ndim == 3 and arr.shape[2] == 4:
        arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
    elif arr.ndim == 3 and arr.shape[2] == 3:
        if isinstance(img, Image.Image):
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        else:
            # Generated frames are expected to be RGB.
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    else:
        raise ValueError(f"Unsupported frame shape: {arr.shape}")

    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)

    return np.ascontiguousarray(arr)


def validate_video(path):
    if not os.path.isfile(path) or os.path.getsize(path) < 1024:
        return False

    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            return False
        ok, frame = cap.read()
        return bool(ok and frame is not None and frame.size > 0)
    finally:
        cap.release()


def frames_to_video(frames, path, fps):
    if frames is None or len(frames) == 0:
        raise ValueError("Cannot create video: frames are empty")

    if not isinstance(fps, (int, float)) or fps <= 0:
        raise ValueError(f"Invalid FPS: {fps}")

    first = _frame_to_bgr(frames[0])
    height, width = first.shape[:2]

    if width < 2 or height < 2:
        raise ValueError("Invalid frame dimensions")

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    writer = cv2.VideoWriter(
        path,
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(fps),
        (width, height),
    )

    if not writer.isOpened():
        writer.release()
        raise RuntimeError(f"VideoWriter could not open: {path}")

    try:
        for index, img in enumerate(frames):
            frame = first if index == 0 else _frame_to_bgr(img)

            if frame.shape[:2] != (height, width):
                raise ValueError(
                    f"Frame {index} dimensions differ: {frame.shape[:2]}"
                )

            writer.write(frame)
    finally:
        writer.release()

    if not validate_video(path):
        raise RuntimeError(f"Generated video failed validation: {path}")

    return path


def upscale_frames(frames, cfg):
    if not cfg.enable_upscale or cfg.upscale_factor == 1:
        return frames

    try:
        from realesrgan import RealESRGANer
        from basicsr.archs.rrdbnet_arch import RRDBNet

        model = RRDBNet(
            num_in_ch=3,
            num_out_ch=3,
            num_feat=64,
            num_block=23,
            num_grow_ch=32,
            scale=4,
        )

        upsampler = RealESRGANer(
            scale=4,
            model_path=None,
            model=model,
            half=True,
        )

        result = []
        for img in frames:
            enhanced, _ = upsampler.enhance(
                np.asarray(img),
                outscale=cfg.upscale_factor,
            )
            result.append(Image.fromarray(enhanced))

        return result

    except Exception as exc:
        print(f"[Post] Upscale skipped safely: {exc}", flush=True)
        return frames


def interpolate_frames(frames, cfg, temp_path):
    if not cfg.enable_frame_interpolation or cfg.target_fps <= cfg.fps:
        return frames

    tmp_dir = tempfile.mkdtemp(
        prefix="cinema_interp_",
        dir=cfg.cache_dir,
    )
    out_path = temp_path.replace(".mp4", "_interp.mp4")

    try:
        for index, img in enumerate(frames):
            img.save(
                os.path.join(tmp_dir, f"frame_{index:05d}.png")
            )

        input_pattern = os.path.join(tmp_dir, "frame_%05d.png")

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-framerate", str(cfg.fps),
            "-i", input_pattern,
            "-vf",
            f"minterpolate=fps={cfg.target_fps}:"
            "mi_mode=mci:mc_mode=aobmc:vsbmc=1",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            out_path,
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0 or not validate_video(out_path):
            print(
                "[Post] Interpolation failed; retaining original FPS. "
                + (result.stderr or "")[-500:],
                flush=True,
            )
            return frames

        cap = cv2.VideoCapture(out_path)
        new_frames = []

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                new_frames.append(
                    Image.fromarray(
                        cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    )
                )
        finally:
            cap.release()

        if len(new_frames) <= len(frames):
            print(
                "[Post] Interpolation produced no additional frames; "
                "retaining original FPS.",
                flush=True,
            )
            return frames

        return new_frames

    except Exception as exc:
        print(
            f"[Post] Interpolation skipped safely: {exc}",
            flush=True,
        )
        return frames

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_postprocess(frames, cfg, raw_video_path):
    if frames is None or len(frames) == 0:
        raise ValueError("Postprocess received empty frames")

    original_count = len(frames)

    if cfg.preserve_original:
        original_path = raw_video_path.replace(
            ".mp4", "_original.mp4"
        )
        frames_to_video(frames, original_path, cfg.fps)

    processed = upscale_frames(frames, cfg)
    processed = interpolate_frames(processed, cfg, raw_video_path)

    interpolation_succeeded = len(processed) > original_count
    output_fps = (
        cfg.target_fps
        if interpolation_succeeded
        else cfg.fps
    )

    final_path = raw_video_path.replace(
        ".mp4", "_cinematic.mp4"
    )

    frames_to_video(processed, final_path, output_fps)

    if not validate_video(final_path):
        raise RuntimeError("Final cinematic video is invalid")

    print(
        f"[Post] Final video: {final_path} "
        f"({len(processed)} frames, {output_fps} FPS)",
        flush=True,
    )

    return final_path
