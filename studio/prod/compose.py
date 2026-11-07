import subprocess
from pathlib import Path
from studio import render
from . import looks
from .plan import ProdError

def clip(work, out, image, head, look, w, h, dur, audio, subs, lang, fade_in, fade_out):
    """One shot: image + camera motion + grade + subtitles + speech (or silence) -> uniform MP4 so clips concatenate without re-encoding."""
    work = Path(work)
    vf = [head] if head else []
    vf += looks.chain(look)
    if subs:
        (work / "cap.ass").write_text(render.build_ass(render.timed_chunks(subs[0], max(1.0, subs[1])), w, h, lang), encoding="utf-8")
        vf.append("ass=cap.ass" + (":fontsdir=%s" % render.FONTS_DIR if Path(render.FONTS_DIR).is_dir() else ""))
    af = ["loudnorm=I=-16:TP=-1.5:LRA=11", "apad"] if audio else ["anull"]
    if dur >= 1.2:
        if fade_in:
            vf.append("fade=t=in:st=0:d=0.4"); af.append("afade=t=in:st=0:d=0.4")
        if fade_out:
            vf.append("fade=t=out:st=%.2f:d=0.4" % (dur - 0.4)); af.append("afade=t=out:st=%.2f:d=0.4" % (dur - 0.4))
    vf.append("format=yuv420p")
    cmd = ["ffmpeg", "-y", "-nostats", "-loglevel", "error", "-i", str(image)]
    cmd += ["-i", str(audio)] if audio else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"]
    cmd += ["-map", "0:v:0", "-map", "1:a:0", "-vf", ",".join(vf), "-af", ",".join(af), "-t", "%.3f" % dur, "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-pix_fmt", "yuv420p", "-r", "24", "-g", "48", "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-ac", "1", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, cwd=str(work), capture_output=True, text=True, timeout=240 + dur * 40)
    if r.returncode != 0 or not Path(out).is_file():
        raise ProdError("ffmpeg failed: %s" % (r.stderr or "")[-240:].strip())
