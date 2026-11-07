"""Self-hosted GPU Worker client + platform provider "cinema_worker". No third-party platform required.
Env: CINEMA_WORKER_URL, CINEMA_WORKER_TOKEN (never logged), CINEMA_WORKER_ALLOW_HTTP=1 (explicit opt-in: plain http to a non-local host).
Worker contract v1: GET /capabilities | POST /jobs | GET /jobs/<id> | POST /jobs/<id>/cancel | GET /jobs/<id>/video
CLI: python -m studio.vidgen status | test"""
import json, os, re, shutil, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import urlparse
from .providers import Provider, ProviderError

BLOCKED = "BLOCKED — GPU WORKER NOT AVAILABLE"
MAX_BYTES = 500 * 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

class WorkerError(Exception):
    def __init__(self, msg, http=None, network=False):
        super().__init__(msg)
        self.http, self.network = http, network

def _base():
    url = os.environ.get("CINEMA_WORKER_URL", "").strip().rstrip("/")
    if not url:
        return None, "CINEMA_WORKER_URL is not set"
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return None, "invalid CINEMA_WORKER_URL"
    if u.scheme == "http" and u.hostname not in ("127.0.0.1", "localhost") and os.environ.get("CINEMA_WORKER_ALLOW_HTTP") != "1":
        return None, "a non-local worker must use https"
    return url, None

def _open(method, target, body=None, timeout=20):
    base, err = _base()
    if err:
        raise WorkerError(err, network=True)
    url = target if target.startswith(("http://", "https://")) else base + target
    if not url.startswith(base + "/"):
        raise WorkerError("refusing a URL outside the worker")
    headers, data = {}, None
    tok = os.environ.get("CINEMA_WORKER_TOKEN")
    if tok:
        headers["Authorization"] = "Bearer " + tok
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    try:
        return urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=timeout)
    except urllib.error.HTTPError as e:
        raise WorkerError(f"worker returned HTTP {e.code}", http=e.code)
    except (urllib.error.URLError, OSError, TimeoutError):
        raise WorkerError("worker unreachable", network=True)

def _json(method, path, body=None, timeout=20):
    with _open(method, path, body, timeout) as r:
        try:
            return json.loads(r.read(1 << 20))
        except ValueError:
            raise WorkerError("worker sent invalid JSON")

def _blocked(reason):
    return {"state": BLOCKED, "ready": False, "reason": reason}

def status():
    _, err = _base()
    if err:
        return _blocked(err)
    try:
        caps = _json("GET", "/capabilities", timeout=8)
    except WorkerError as e:
        return _blocked(str(e))
    if not isinstance(caps, dict) or caps.get("api") != 1:
        return _blocked("incompatible worker (API version)")
    if not caps.get("gpu"):
        return _blocked("worker reports no GPU")
    if not caps.get("model") or not isinstance(caps.get("profiles"), dict) or not caps["profiles"]:
        return _blocked("worker did not report its model and profiles")
    return {"state": "READY", "ready": True, "reason": "", "caps": caps}

def build_spec(req, caps):
    prof = caps["profiles"].get(req.get("resolution"))
    if not prof:
        raise ValueError("resolution not supported by the worker (supported: %s)" % ", ".join(caps["profiles"]))
    ar = req.get("aspect_ratio") or prof["aspect_ratio"]
    if ar != prof["aspect_ratio"]:
        raise ValueError("aspect ratio %s is not supported at %s (worker offers %s)" % (ar, req["resolution"], prof["aspect_ratio"]))
    s = req.get("seconds")
    if isinstance(s, bool) or not isinstance(s, (int, float)) or not 0 < s <= caps["max_seconds"]:
        raise ValueError("duration must be between 0 and %s seconds" % caps["max_seconds"])
    p = req.get("prompt")
    if not isinstance(p, str) or not 1 <= len(p.strip()) <= 2000:
        raise ValueError("prompt must be 1-2000 characters")
    mode = req.get("mode") or "text_to_video"
    if mode not in caps.get("modes", []):
        raise ValueError("mode not supported by the worker")
    spec = {"mode": mode, "prompt": p.strip(), "seconds": s, "profile": req["resolution"]}
    if isinstance(req.get("seed"), int) and not isinstance(req.get("seed"), bool):
        spec["seed"] = req["seed"]
    return spec

def verify_video(path):
    if not shutil.which("ffprobe"):
        raise WorkerError("ffprobe not available to verify the video")
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,nb_frames,width,height:format=duration",
                              "-of", "json", str(path)], capture_output=True, text=True, timeout=30, check=True).stdout
        d = json.loads(out)
        dur = float(d["format"]["duration"])
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        raise WorkerError("downloaded file is not a readable video")
    v = [s for s in d.get("streams", []) if s.get("codec_type") == "video"]
    if not v or dur < 0.2:
        raise WorkerError("downloaded file has no usable video stream")
    nb = str(v[0].get("nb_frames", ""))
    if nb.isdigit() and int(nb) < 2:
        raise WorkerError("video has fewer than 2 frames")
    return {"duration": round(dur, 2), "width": v[0].get("width"), "height": v[0].get("height"),
            "size_mb": round(Path(path).stat().st_size / 1048576, 2)}

class CinemaWorkerProvider(Provider):
    name, label = "cinema_worker", "Cinema Worker (self-hosted GPU)"
    cancel_supported = True
    progress_supported = True
    free = True

    def configured(self):
        return status()["ready"]

    def models(self):
        st = status()
        if not st["ready"]:
            return {}
        c = st["caps"]
        return {c["model"]: {"modes": c.get("modes", []), "resolutions": list(c["profiles"]),
                             "aspect_ratios": sorted({p["aspect_ratio"] for p in c["profiles"].values()}),
                             "max_seconds": c["max_seconds"], "fps": c.get("fps"), "plan_note": None}}

    def _caps(self):
        st = status()
        if not st["ready"]:
            raise ProviderError("worker_unavailable", "%s: %s" % (BLOCKED, st["reason"]), retryable=True)
        return st["caps"]

    @staticmethod
    def _id(pid):
        if not isinstance(pid, str) or not ID_RE.match(pid):
            raise ProviderError("bad_id", "invalid job id")

    @staticmethod
    def _err(e, **kw):
        return ProviderError("network" if e.network else "worker_error", str(e), **kw)

    def validate(self, req):
        caps = self._caps()
        try:
            spec = build_spec(req, caps)
        except ValueError as e:
            raise ProviderError("invalid_request", str(e))
        if req.get("model") not in (None, "", "auto", caps["model"]):
            raise ProviderError("unsupported_model", "this worker serves %s: set the model to that id or 'auto'" % caps["model"])
        return {**req, "model": caps["model"], "resolution": spec["profile"], "seconds": spec["seconds"],
                "aspect_ratio": caps["profiles"][spec["profile"]]["aspect_ratio"], "prompt": spec["prompt"]}

    def submit(self, req):
        caps = self._caps()
        try:
            spec = build_spec(req, caps)
        except ValueError as e:
            raise ProviderError("invalid_request", str(e))
        try:
            d = _json("POST", "/jobs", spec, timeout=30)
        except WorkerError as e:
            raise self._err(e, retryable=e.http in (429, 503), ambiguous=bool(e.network))
        jid = d.get("id") if isinstance(d, dict) else None
        if not isinstance(jid, str) or not ID_RE.match(jid):
            raise ProviderError("bad_response", "worker returned an invalid job id", ambiguous=True)
        return {"id": jid, "credits": None}

    def poll(self, pid):
        self._id(pid)
        try:
            j = _json("GET", "/jobs/" + pid, timeout=20)
        except WorkerError as e:
            raise self._err(e, retryable=True)
        st = j.get("state")
        prog = j.get("progress") if isinstance(j.get("progress"), int) else None
        if st == "done":
            return {"state": "complete", "url": _base()[0] + "/jobs/%s/video" % pid, "error": None, "progress": 100}
        if st in ("failed", "cancelled"):
            return {"state": "error", "url": None, "error": "worker job %s: %s" % (st, str(j.get("error") or "")[:200]), "progress": prog}
        return {"state": "queued" if st == "queued" else "running", "url": None, "error": None, "progress": prog}

    def cancel(self, pid):
        self._id(pid)
        try:
            _json("POST", "/jobs/%s/cancel" % pid, {}, timeout=10)
        except WorkerError as e:
            raise self._err(e, retryable=True)

    def download(self, url, dest, cancelled=lambda: False):
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        try:
            with _open("GET", url, timeout=60) as r, open(part, "wb") as f:
                total = 0
                while True:
                    if cancelled():
                        raise ProviderError("cancelled", "download cancelled")
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ProviderError("too_large", "video file too large")
                    f.write(chunk)
            try:
                verify_video(part)
            except WorkerError as e:
                raise ProviderError("bad_video", str(e))
            part.replace(dest)
        except WorkerError as e:
            raise self._err(e, retryable=True)
        finally:
            if part.exists():
                part.unlink()

def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "status"
    st = status()
    print(st["state"] + (" (%s)" % st["reason"] if st["reason"] else ""))
    if not st["ready"]:
        return 1
    c = st["caps"]
    print("model:", c["model"], "| profiles:", list(c["profiles"]), "| max_seconds:", c["max_seconds"])
    if cmd != "test":
        return 0
    from cinema_core import config
    p = CinemaWorkerProvider()
    prof = next(iter(c["profiles"]))
    out = config.load().root / "var" / "vidgen" / "test.mp4"
    try:
        req = p.validate({"prompt": "a slow cinematic shot of a lighthouse at dusk, waves, film look", "model": "auto",
                          "seconds": min(4, c["max_seconds"]), "resolution": prof, "aspect_ratio": c["profiles"][prof]["aspect_ratio"]})
        sub = p.submit(req)
        t0 = time.monotonic()
        while True:
            r = p.poll(sub["id"])
            if r["state"] == "complete":
                break
            if r["state"] == "error":
                print("GENERATION FAILED:", r["error"])
                return 1
            if time.monotonic() - t0 > 1800:
                p.cancel(sub["id"])
                print("GENERATION TIMED OUT")
                return 1
            print("  %s%%" % (r.get("progress") or 0))
            time.sleep(3)
        p.download(r["url"], out)
    except ProviderError as e:
        print("FAILED:", e)
        return 1
    print("VERIFIED FILE (valid video; judge the quality with your own eyes):", out, verify_video(out))
    return 0

if __name__ == "__main__":
    sys.exit(main())
