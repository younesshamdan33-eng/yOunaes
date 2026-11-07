"""Output Validator: a clip is accepted only if it is a real, moving video of the expected size and length."""
import json, subprocess
from pathlib import Path

def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,avg_frame_rate:format=duration,size",
                        "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise ValueError("ffprobe rejected the file")
    d = json.loads(r.stdout or "{}")
    vs = [s for s in d.get("streams", []) if s.get("codec_type") == "video"]
    if not vs:
        raise ValueError("no video stream")
    try:
        n, m = vs[0].get("avg_frame_rate", "0/1").split("/")
        fps = float(n) / float(m) if float(m) else 0.0
    except ValueError:
        fps = 0.0
    return {"width": vs[0].get("width"), "height": vs[0].get("height"), "fps": round(fps, 2), "codec": vs[0].get("codec_name"),
            "duration": float(d["format"]["duration"]), "has_audio": any(s.get("codec_type") == "audio" for s in d["streams"]),
            "size_bytes": int(d["format"].get("size") or Path(path).stat().st_size)}

def _gray(path, t):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % t, "-i", str(path), "-frames:v", "1", "-vf", "scale=32:18,format=gray",
                        "-f", "rawvideo", "-"], capture_output=True, timeout=60)
    return r.stdout if len(r.stdout) == 32 * 18 else None

def validate(path, expect, samples=8):
    issues = []
    try:
        info = probe(path)
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "issues": ["unreadable video: %s" % e], "info": None, "motion": []}
    if info["size_bytes"] < 10 * 1024:
        issues.append("file is too small to be a real video")
    if (info["width"], info["height"]) != (expect["width"], expect["height"]):
        issues.append("resolution %sx%s, expected %sx%s" % (info["width"], info["height"], expect["width"], expect["height"]))
    if abs(info["fps"] - expect["fps"]) > 1.0:
        issues.append("frame rate %.2f, expected %s" % (info["fps"], expect["fps"]))
    want = expect["num_frames"] / expect["fps"]
    if abs(info["duration"] - want) > max(0.35, want * 0.06):
        issues.append("duration %.2fs, expected about %.2fs" % (info["duration"], want))
    frames = [g for g in (_gray(path, info["duration"] * (i + 0.5) / samples) for i in range(samples)) if g]
    diffs = []
    if len(frames) < 4:
        issues.append("could not decode enough frames to check motion")
    else:
        diffs = [round(sum(abs(a - b) for a, b in zip(x, y)) / len(x), 2) for x, y in zip(frames, frames[1:])]
        if max(diffs) < 1.0:
            issues.append("video is static (no real motion between frames)")
        elif sum(1 for d in diffs if d < 0.3) >= len(diffs) * 0.6:
            issues.append("mostly duplicated frames (slideshow-like)")
        if all(sum(f) / len(f) < 2 or sum(f) / len(f) > 253 for f in frames):
            issues.append("blank (all black or all white) frames")
    return {"ok": not issues, "issues": issues, "info": info, "motion": diffs}
