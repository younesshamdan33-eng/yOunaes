"""Shot visuals: a real AI image per shot (free Pollinations service) or a procedural gradient, both animated with camera motion.
Failures raise VisualError: there is never a silent substitution."""
import hashlib, subprocess, threading, time, urllib.error, urllib.request, zlib
from pathlib import Path
from urllib.parse import quote, urlencode
from studio import render

BASE = "https://image.pollinations.ai/prompt/"
PACING = {"min_gap": 16.0, "retry_wait": 20.0, "attempts": 3}
MAXB = 15 * 1048576
_gate, _last = threading.Lock(), [0.0]

class VisualError(Exception):
    pass

def http_get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "cinema-ai-studio/1.0", "Accept": "image/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read(MAXB + 1)
    except urllib.error.HTTPError as e:
        return e.code, (e.headers.get("Content-Type", "") if e.headers else ""), b""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise OSError(e.__class__.__name__)

def _magic(b):
    return b[:3] == b"\xff\xd8\xff" or b[:4] == b"\x89PNG" or (b[:4] == b"RIFF" and b[8:12] == b"WEBP")

def _valid(f):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(f)], capture_output=True, text=True, timeout=30)
        a, b = r.stdout.strip().split(",")[:2]
        return r.returncode == 0 and int(a) >= 256 and int(b) >= 144
    except (OSError, subprocess.SubprocessError, ValueError):
        return False

def fetch_image(prompt, w, h, seed, cache):
    url = BASE + quote(prompt[:700], safe="") + "?" + urlencode({"width": w, "height": h, "seed": seed % 1000000, "model": "flux", "nologo": "true"})
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    f = cache / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".img")
    if f.is_file() and _valid(f):
        return f
    last = "unknown error"
    for attempt in range(PACING["attempts"]):
        with _gate:
            wait = PACING["min_gap"] - (time.monotonic() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.monotonic()
        retry = True
        try:
            code, ctype, data = http_get(url)
        except OSError as e:
            last = "image service unreachable (%s)" % e
        else:
            if code == 200 and data and len(data) <= MAXB and ctype.lower().startswith("image/") and _magic(data):
                tmp = f.with_name(f.name + ".part"); tmp.write_bytes(data); tmp.replace(f)
                if _valid(f):
                    return f
                f.unlink(missing_ok=True); last = "image service returned an unreadable image"
            elif code == 429 or (isinstance(code, int) and code >= 500):
                last = "image service busy (HTTP %s)" % code
            else:
                last, retry = "image service refused the request (HTTP %s)" % code, False
        if not retry:
            break
        if attempt < PACING["attempts"] - 1:
            time.sleep(PACING["retry_wait"] * (attempt + 1))
    raise VisualError("%s: the free image service is rate-limited or down; retry later or allow the procedural fallback" % last)

def dims(res, aspect):
    short = {"144p": 144, "480p": 480, "720p": 720}[res]
    ev = lambda v: int(v) // 2 * 2
    if aspect == "9:16":
        return ev(short), ev(short * 16 / 9)
    if aspect == "1:1":
        return short, short
    return ev(short * 16 / 9), short

def zoom_head(sid, w, h, n):
    k, inc, mid = zlib.crc32(sid.encode()) % 4, 0.30 / max(1, n), "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    motion = {0: "z='min(zoom+%.6f,1.3)':%s" % (inc, mid), 1: "z='if(eq(on,0),1.3,max(zoom-%.6f,1.0))':%s" % (inc, mid),
              2: "z=1.25:x='(iw-iw/zoom)*on/%d':y='ih/2-(ih/zoom/2)'" % n, 3: "z=1.25:x='(iw-iw/zoom)*(1-on/%d)':y='ih/2-(ih/zoom/2)'" % n}[k]
    sw, sh = int(w * 1.5) // 2 * 2, int(h * 1.5) // 2 * 2
    return "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,zoompan=%s:d=%d:s=%dx%d:fps=24" % (sw, sh, sw, sh, motion, n, w, h)

def gradient_image(path, look, sid, w, h):
    scene = int("".join(c for c in sid.split("-")[0] if c.isdigit()) or 1)
    render.make_background(Path(path), w, h, (zlib.crc32(look.encode()) % 360 + scene * 37) % 360)
    return Path(path)
