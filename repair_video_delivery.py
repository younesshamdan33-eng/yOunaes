from pathlib import Path
from datetime import datetime
import shutil
import py_compile

ROOT = Path.cwd()
POST = ROOT / "cinematic_engine" / "postprocess.py"
API = ROOT / "studio" / "cinema_api.py"

for p in (POST, API):
    if not p.is_file():
        raise SystemExit(f"STOP: required file missing: {p}")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backups = []

for p in (POST, API):
    backup = p.with_name(p.name + ".backup." + stamp)
    shutil.copy2(p, backup)
    backups.append(backup)
    print(f"BACKUP: {backup}")

postprocess = r'''import os
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
'''

api_text = API.read_text(encoding="utf-8")

start_marker = "def _download(slug, job_id):"
end_marker = "\ndef _worker():"

if api_text.count(start_marker) != 1:
    raise SystemExit("STOP: _download definition is missing or ambiguous")

if api_text.count(end_marker) != 1:
    raise SystemExit("STOP: _worker boundary is missing or ambiguous")

new_download = r'''def _valid_mp4(path):
    path = Path(path)

    if not path.is_file() or path.stat().st_size < 1024:
        return False

    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=codec_type,width,height",
                    "-show_entries", "format=duration",
                    "-of", "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return False

            data = json.loads(result.stdout or "{}")
            streams = data.get("streams") or []
            fmt = data.get("format") or {}

            return bool(
                streams
                and streams[0].get("codec_type") == "video"
                and int(streams[0].get("width") or 0) > 0
                and int(streams[0].get("height") or 0) > 0
                and float(fmt.get("duration") or 0) > 0
            )

        except Exception as exc:
            print(f"[cinema-worker] ffprobe validation error: {exc}")
            return False

    try:
        import cv2

        cap = cv2.VideoCapture(str(path))
        try:
            if not cap.isOpened():
                return False
            ok, frame = cap.read()
            return bool(ok and frame is not None and frame.size > 0)
        finally:
            cap.release()

    except Exception:
        return False


def _download(slug, job_id):
    tmp = BASE / "var" / f"dl_{job_id}"
    tmp.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            ["kaggle", "kernels", "output", slug, "-p", str(tmp)],
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            return None, (
                "Kaggle output download failed: "
                + (result.stderr or result.stdout or "")[:500]
            )

        vids = [
            p for p in tmp.rglob("*")
            if p.is_file() and p.suffix.lower() == ".mp4"
        ]

        if not vids:
            return None, "Kaggle completed but returned no MP4 files"

        expected_name = f"{job_id}_cinematic.mp4"

        def priority(path):
            name = path.name.lower()

            if name == expected_name.lower():
                return 0
            if name.endswith("_cinematic.mp4"):
                return 1
            if not any(
                marker in name
                for marker in ("_raw.mp4", "_original.mp4", "_interp.mp4")
            ):
                return 2
            return 3

        vids.sort(key=lambda p: (priority(p), -p.stat().st_size))

        source = next(
            (p for p in vids if priority(p) < 3 and _valid_mp4(p)),
            None,
        )

        if source is None:
            return None, "No valid final MP4 found in Kaggle output"

        dest = GENERATED / f"{job_id}.mp4"
        partial = GENERATED / f".{job_id}.part.mp4"

        if partial.exists():
            partial.unlink()

        shutil.copy2(source, partial)

        if not _valid_mp4(partial):
            partial.unlink(missing_ok=True)
            return None, "Downloaded MP4 failed local validation"

        os.replace(partial, dest)

        if not _valid_mp4(dest):
            dest.unlink(missing_ok=True)
            return None, "Final video failed validation after installation"

        print(
            f"[cinema-worker] validated video: {dest} "
            f"({dest.stat().st_size} bytes)",
            flush=True,
        )

        return dest.name, None

    except Exception as exc:
        return None, f"Video download/validation error: {exc}"

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
'''

new_api = (
    api_text[:api_text.index(start_marker)]
    + new_download
    + api_text[api_text.index(end_marker):]
)

# Make the Kaggle script explicitly verify and report its final output.
old_call = (
    'run_cinematic_engine({repr(prompt)}, cfg, output_name="{job_id}")\n'
    'print("DONE")'
)

new_call = (
    'final_path = run_cinematic_engine('
    '{repr(prompt)}, cfg, output_name="{job_id}")\n'
    'if not os.path.isfile(final_path) or os.path.getsize(final_path) < 1024:\n'
    '    raise RuntimeError("Final video missing or empty: " + str(final_path))\n'
    'print("FINAL_VIDEO=" + str(final_path), flush=True)\n'
    'print("DONE", flush=True)'
)

if new_api.count(old_call) != 1:
    raise SystemExit(
        "STOP: Kaggle generation call did not match exactly once; "
        "no source files were modified"
    )

new_api = new_api.replace(old_call, new_call, 1)

# Write only after all structural checks have passed.
POST.write_text(postprocess, encoding="utf-8")
API.write_text(new_api, encoding="utf-8")

print("\nPATCH APPLIED")
print("Updated:", POST)
print("Updated:", API)

for p in (POST, API):
    py_compile.compile(str(p), doraise=True)
    print("PY_COMPILE PASS:", p)

# Verify expected functions and route definitions remain present.
post_text = POST.read_text(encoding="utf-8")
api_check = API.read_text(encoding="utf-8")

required_post = (
    "def frames_to_video(",
    "def interpolate_frames(",
    "def run_postprocess(",
    "def validate_video(",
)

required_api = (
    "def _valid_mp4(",
    "def _download(",
    'print("FINAL_VIDEO="',
    '@cinema_bp.route("/generate"',
    '@cinema_bp.route("/job/<job_id>"',
    '@cinema_bp.route("/videos/<path:filename>"',
)

for item in required_post:
    assert item in post_text, f"Missing postprocess component: {item}"

for item in required_api:
    assert item in api_check, f"Missing API component: {item}"

print("STRUCTURE CHECK PASS")
print("\nBackups retained:")
for p in backups:
    print(p)

print("\nPATCH VERIFICATION COMPLETE")
