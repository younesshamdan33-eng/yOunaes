"""Short-film pipeline: scenes -> narration -> subtitles -> per-scene MP4 -> concat -> verify."""
import asyncio, colorsys, functools, json, re, shutil, subprocess, time
from pathlib import Path

PROFILES = {
    "preview": dict(w=426, h=240, fps=12, preset="ultrafast", crf=32, mbps=0.03),
    "480p": dict(w=854, h=480, fps=24, preset="veryfast", crf=28, mbps=0.12),
    "720p": dict(w=1280, h=720, fps=24, preset="veryfast", crf=26, mbps=0.25),
    "1080p": dict(w=1920, h=1080, fps=24, preset="veryfast", crf=25, mbps=0.5),
}
PAD = 0.4
MAX_SCENES = 150
FONTS_DIR = "/system/fonts"
RTL = {"ar", "he", "fa", "ur"}
SENT_RE = re.compile(r"(?<=[.!?؟…])\s+")

class RenderError(Exception):
    pass

class Cancelled(Exception):
    pass

def plan_scenes(script):
    s = (script or "").strip()
    if not s:
        return []
    parts = [p.strip() for p in re.split(r"\n\s*\n", s) if p.strip()]
    if len(parts) == 1:
        parts = [p.strip() for p in SENT_RE.split(s) if p.strip()]
    return [" ".join(p.split()) for p in parts]

def est_seconds(text):
    return max(2.0, len(text.split()) / 2.5)

def chunks(text, max_words=9):
    w = text.split()
    return [" ".join(w[i:i + max_words]) for i in range(0, len(w), max_words)]

def timed_chunks(text, duration, max_words=9):
    ch = chunks(text, max_words)
    weights = [max(1, len(c)) for c in ch]
    tot, t, out = sum(weights), 0.0, []
    for c, wt in zip(ch, weights):
        d = duration * wt / tot
        out.append((t, t + d, c))
        t += d
    return out

def ass_time(s):
    cs = int(round(s * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    sec, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"

def ass_escape(t):
    # backslash would start an ASS override; replaced by "/" (the only text change)
    return t.replace("\\", "/").replace("{", "\\{").replace("}", "\\}").replace("\n", " ")

def build_ass(items, w, h, lang):
    font = "Noto Naskh Arabic" if lang in RTL else "Droid Sans"
    size, mv, mh = max(14, h // 15), h // 12, w // 20
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 0",
             "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
             f"Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,{mh},{mh},{mv},1",
             "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for s, e, txt in items:
        lines.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Default,,0,0,0,,{ass_escape(txt)}")
    return "\n".join(lines) + "\n"

def title_hue(title):
    x = 0
    for c in title or "x":
        x = (x * 31 + ord(c)) % 360
    return x

def make_background(path, w, h, hue):
    top = colorsys.hls_to_rgb(hue / 360, .30, .6)
    bot = colorsys.hls_to_rgb(((hue + 70) % 360) / 360, .10, .6)
    rows = []
    for y in range(h):
        f = y / (h - 1)
        rows.append(bytes(int(255 * (top[i] + (bot[i] - top[i]) * f)) for i in range(3)) * w)
    with open(path, "wb") as fh:
        fh.write(f"P6\n{w} {h}\n255\n".encode())
        fh.write(b"".join(rows))

@functools.lru_cache(maxsize=1)
def capabilities():
    c = {"ffmpeg": bool(shutil.which("ffmpeg")), "ffprobe": bool(shutil.which("ffprobe")),
         "libx264": False, "aac": False, "ass": False}
    if c["ffmpeg"]:
        try:
            enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20).stdout
            fil = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, timeout=20).stdout
            c["libx264"], c["aac"] = " libx264 " in enc, " aac " in enc
            c["ass"] = bool(re.search(r"\sass\s", fil))
        except (OSError, subprocess.SubprocessError):
            pass
    return c

def require_caps(subtitles):
    c = capabilities()
    need = ["ffmpeg", "ffprobe", "libx264", "aac"] + (["ass"] if subtitles else [])
    miss = [n for n in need if not c.get(n)]
    if miss:
        raise RenderError("missing FFmpeg capabilities: " + ", ".join(miss))

def validate_for_render(project):
    scenes = plan_scenes(project.get("script", ""))
    if not scenes:
        raise RenderError("the script is empty")
    if len(scenes) > MAX_SCENES:
        raise RenderError(f"too many scenes ({len(scenes)}); max {MAX_SCENES}")
    if not project.get("voice"):
        raise RenderError("choose a narration voice first")
    sl = project.get("subtitle_lang", "none")
    if sl not in ("none", project.get("script_lang")):
        raise RenderError("subtitle translation is not implemented: use the script language or no subtitles")
    if project.get("profile") not in PROFILES:
        raise RenderError("unsupported render profile")
    require_caps(sl != "none")
    return scenes

def estimate_mb(project, scenes):
    secs = sum(est_seconds(s) for s in scenes)
    return int(secs * PROFILES[project["profile"]]["mbps"] * 2.5 + 20)

def check_space(cfg, path, need_mb=0):
    free = shutil.disk_usage(path).free // (1024 * 1024)
    if free - need_mb < cfg.min_free_mb:
        raise RenderError(f"insufficient storage ({free} MB free, reserve {cfg.min_free_mb} MB)")

def _kill(p):
    p.terminate()
    try:
        p.wait(3)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()

def run_cmd(args, cwd, timeout, cancelled=None):
    try:
        p = subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise RenderError(f"cannot run {args[0]}: {e}")
    deadline = time.monotonic() + timeout
    while True:
        try:
            p.wait(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            pass
        if cancelled and cancelled():
            _kill(p)
            raise Cancelled()
        if time.monotonic() > deadline:
            _kill(p)
            raise RenderError(f"{args[0]} timed out")
    out = p.stdout.read().decode(errors="replace")
    err = p.stderr.read().decode(errors="replace")[-500:]
    if p.returncode:
        raise RenderError(f"{args[0]} failed ({p.returncode}): {err}")
    return out

def synth(text, voice, out_path, timeout=60):
    import edge_tts
    async def go():
        await asyncio.wait_for(edge_tts.Communicate(text, voice).save(str(out_path)), timeout)
    asyncio.run(go())

def narrate(text, voice, audio, log, attempts=2):
    last = None
    for a in range(attempts):
        try:
            synth(text, voice, audio)
            if audio.exists() and audio.stat().st_size > 0:
                return
            last = "empty audio"
        except ImportError:
            raise RenderError("edge-tts is not installed")
        except Exception as e:
            last = str(e) or e.__class__.__name__
        log(f"narration attempt {a + 1} failed: {last}")
    if audio.exists() and audio.stat().st_size == 0:
        audio.unlink()
    raise RenderError(f"narration failed: {last}")

def probe_duration(path, cancelled=None):
    out = run_cmd(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], None, 30, cancelled)
    try:
        d = float(json.loads(out)["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        raise RenderError("cannot read audio duration")
    if d <= 0:
        raise RenderError("audio has zero duration")
    return d

def verify_output(path, expected, cancelled=None):
    out = run_cmd(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height",
                   "-of", "json", str(path)], None, 30, cancelled)
    try:
        d = json.loads(out)
        streams = d["streams"]
        dur = float(d["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        raise RenderError("output could not be read by ffprobe")
    v = [s for s in streams if s.get("codec_type") == "video"]
    a = [s for s in streams if s.get("codec_type") == "audio"]
    if not v or v[0].get("codec_name") != "h264":
        raise RenderError("output has no H.264 video")
    if not a or a[0].get("codec_name") != "aac":
        raise RenderError("output has no AAC audio")
    if abs(dur - expected) > max(1.5, expected * 0.05):
        raise RenderError(f"duration mismatch ({dur:.1f}s vs {expected:.1f}s expected)")
    return {"duration": round(dur, 2), "width": v[0]["width"], "height": v[0]["height"],
            "size_mb": round(Path(path).stat().st_size / 1048576, 2)}

def _render_scene(work, i, dur, prof, subs, lang, text, cancelled):
    audio, out = f"s{i:03d}.mp3", f"s{i:03d}.mp4"
    args = ["ffmpeg", "-y", "-nostats", "-loglevel", "error", "-loop", "1", "-framerate", str(prof["fps"]),
            "-i", "bg.ppm", "-i", audio]
    if subs:
        ass = f"s{i:03d}.ass"
        (work / ass).write_text(build_ass(timed_chunks(text, dur), prof["w"], prof["h"], lang), encoding="utf-8")
        vf = f"ass={ass}" + (f":fontsdir={FONTS_DIR}" if Path(FONTS_DIR).is_dir() else "")
        args += ["-vf", vf]
    args += ["-af", "apad", "-t", f"{dur + PAD:.3f}", "-c:v", "libx264", "-preset", prof["preset"],
             "-crf", str(prof["crf"]), "-pix_fmt", "yuv420p", "-r", str(prof["fps"]), "-g", str(prof["fps"] * 2),
             "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-ac", "1", out]
    run_cmd(args, work, 120 + dur * 20, cancelled)

def render_project(cfg, project, work, out_dir, progress=None, cancelled=None, log=None):
    progress = progress or (lambda p: None)
    cancelled = cancelled or (lambda: False)
    log = log or (lambda m: None)
    scenes = validate_for_render(project)
    prof = PROFILES[project["profile"]]
    subs = project["subtitle_lang"] != "none"
    work, out_dir = Path(work), Path(out_dir)
    work.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    total, done = 2 * len(scenes) + 2, 0

    def tick():
        nonlocal done
        done += 1
        progress(min(99, int(done * 100 / total)))

    def guard(need=10):
        if cancelled():
            raise Cancelled()
        check_space(cfg, work, need)

    guard()
    make_background(work / "bg.ppm", prof["w"], prof["h"], title_hue(project["title"]))
    log(f"{len(scenes)} scene(s), profile {project['profile']} {prof['w']}x{prof['h']}")
    expected = 0.0
    for i, text in enumerate(scenes, 1):
        guard()
        audio = work / f"s{i:03d}.mp3"
        if not (audio.exists() and audio.stat().st_size > 0):
            narrate(text, project["voice"], audio, log)
        dur = probe_duration(audio, cancelled)
        expected += dur + PAD
        tick()
        log(f"scene {i}: narration {dur:.1f}s")
        guard()
        _render_scene(work, i, dur, prof, subs, project["script_lang"], text, cancelled)
        tick()
        log(f"scene {i}: rendered")
    guard()
    (work / "list.txt").write_text("".join(f"file 's{i:03d}.mp4'\n" for i in range(1, len(scenes) + 1)))
    tmp = out_dir / "film.tmp.mp4"
    run_cmd(["ffmpeg", "-y", "-nostats", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt",
             "-c", "copy", "-movflags", "+faststart", str(tmp)], work, 300, cancelled)
    tick()
    info = verify_output(tmp, expected, cancelled)
    tmp.replace(out_dir / "film.mp4")
    tick()
    log(f"verified: {info['duration']}s {info['width']}x{info['height']} {info['size_mb']} MB")
    return info

def cleanup_work(work, root):
    work, root = Path(work), Path(root)
    if work.is_symlink() or not work.is_dir() or root.resolve() not in work.resolve().parents:
        return
    for f in work.iterdir():
        if f.is_file() and not f.is_symlink():
            f.unlink()
    try:
        work.rmdir()
    except OSError:
        pass
