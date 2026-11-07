"""Procedural ambient score (sine pads). It is generated, not composed: label it as such."""
import subprocess

MOODS = {"calm": (110, 164.8, 220), "tense": (98, 146.8, 155.6), "epic": (73.4, 110, 146.8), "warm": (130.8, 196, 261.6)}
LOOK_MOOD = {"horror": "tense", "noir": "tense", "scifi": "epic", "cyberpunk": "epic", "fantasy": "warm", "cartoon": "warm", "anime": "warm"}

def mood_for(look):
    return LOOK_MOOD.get(look, "calm")

def make_bed(out, seconds=90, mood="calm"):
    cmd = ["ffmpeg", "-y", "-nostats", "-loglevel", "error"]
    for f in MOODS[mood]:
        cmd += ["-f", "lavfi", "-i", "sine=f=%s:r=44100:d=%d" % (f, seconds)]
    fc = "[0][1][2]amix=inputs=3:normalize=0,tremolo=f=0.15:d=0.5,lowpass=f=1200,volume=0.8,afade=t=in:d=3,afade=t=out:st=%d:d=4[a]" % (seconds - 4)
    r = subprocess.run(cmd + ["-filter_complex", fc, "-map", "[a]", "-c:a", "aac", "-b:a", "64k", "-ac", "2", str(out)], capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError("music bed failed: " + (r.stderr or "")[-200:])
