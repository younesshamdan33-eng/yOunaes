import os, cv2, numpy as np
from PIL import Image
from config import CinematicConfig

def frames_to_video(frames, path, fps):
    if not frames: raise ValueError("Empty frames")
    h, w = frames[0].height, frames[0].width
    out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for img in frames:
        arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR) if isinstance(img, Image.Image) else img
        out.write(arr)
    out.release()
    return path

def upscale_frames(frames, cfg):
    if not cfg.enable_upscale or cfg.upscale_factor == 1: return frames
    try:
        from realesrgan import RealESRGANer
        from basicsr.archs.rrdbnet_arch import RRDBNet
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
        upsampler = RealESRGANer(scale=4, model_path=None, model=model, half=True)
        return [Image.fromarray(upsampler.enhance(np.array(img), outscale=cfg.upscale_factor)[0]) for img in frames]
    except Exception as e:
        print(f"[Post] Skip upscale: {e}")
        return frames

def interpolate_frames(frames, cfg, temp_path):
    if not cfg.enable_frame_interpolation or cfg.target_fps <= cfg.fps: return frames
    tmp_dir = os.path.join(cfg.cache_dir, "tmp_frames"); os.makedirs(tmp_dir, exist_ok=True)
    for i, img in enumerate(frames): img.save(os.path.join(tmp_dir, f"frame_{i:05d}.png"))
    out_path = temp_path.replace(".mp4", "_interp.mp4")
    os.system(f'ffmpeg -y -framerate {cfg.fps} -i "{tmp_dir}/frame_%05d.png" -vf "minterpolate=fps={cfg.target_fps}:mi_mode=mci:mc_mode=aobmc:vsbmc=1" -c:v libx264 -pix_fmt yuv420p "{out_path}"')
    cap = cv2.VideoCapture(out_path); new_frames = []
    while True:
        ret, frame = cap.read()
        if not ret: break
        new_frames.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
    cap.release(); return new_frames

def run_postprocess(frames, cfg, raw_video_path):
    if cfg.preserve_original:
        frames_to_video(frames, raw_video_path.replace(".mp4", "_original.mp4"), cfg.fps)
    frames = upscale_frames(frames, cfg)
    frames = interpolate_frames(frames, cfg, raw_video_path)
    final_path = raw_video_path.replace(".mp4", "_cinematic.mp4")
    frames_to_video(frames, final_path, cfg.target_fps if cfg.enable_frame_interpolation else cfg.fps)
    return final_path
