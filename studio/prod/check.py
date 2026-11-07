import json, subprocess

def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration,size", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise ValueError("ffprobe rejected the file")
    d = json.loads(r.stdout or "{}")
    v = [s for s in d.get("streams", []) if s.get("codec_type") == "video"]
    return {"duration": float(d["format"]["duration"]), "width": v[0].get("width") if v else None, "height": v[0].get("height") if v else None,
            "has_video": bool(v), "has_audio": any(s.get("codec_type") == "audio" for s in d.get("streams", [])), "size": int(d["format"].get("size") or 0)}

def gray(path, t):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % t, "-i", str(path), "-frames:v", "1", "-vf", "scale=32:18,format=gray", "-f", "rawvideo", "-"],
                       capture_output=True, timeout=60)
    return r.stdout if len(r.stdout) == 576 else None

def motion(path, duration, samples=8):
    fr = [g for g in (gray(path, duration * (i + 0.5) / samples) for i in range(samples)) if g]
    if len(fr) < 4:
        return None
    return [round(sum(abs(a - b) for a, b in zip(x, y)) / len(x), 2) for x, y in zip(fr, fr[1:])]

def issues(path, expect=None, need_motion=False):
    out = []
    try:
        info = probe(path)
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        return ["unreadable video file"]
    if not info["has_video"]:
        out.append("no video stream")
    if info["size"] < 4096:
        out.append("file is too small")
    if expect and abs(info["duration"] - expect) > max(0.4, expect * 0.05):
        out.append("duration %.2fs, expected %.2fs" % (info["duration"], expect))
    if need_motion and info["duration"] >= 1.5:
        d = motion(path, info["duration"])
        if d is None:
            out.append("could not decode frames")
        elif max(d) < 0.6:
            out.append("static video (no real motion)")
    return out
