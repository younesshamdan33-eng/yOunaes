"""Magic Hour text-to-video client (official REST API, stdlib only, no new dependency).
Endpoints (verified in docs.magichour.ai): POST /v1/text-to-video, GET /v1/video-projects/{id}.
This is AI generation. FFmpeg is only used here to VALIDATE the downloaded clip."""
import json, os, re, subprocess, time, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import quote, urlparse
from cinema_core.jobs import JobError

BASE = "https://api.magichour.ai"
ENV_KEY = "MAGIC_HOUR_API_KEY"
DAILY_ENV = "MAGIC_HOUR_DAILY_LIMIT"
POLL_SECONDS, TIMEOUT_SECONDS = 8, 20 * 60
MAX_SECONDS, MAX_PROMPT, MAX_DOWNLOAD_MB = 10, 2000, 150
RATIOS = ("16:9", "9:16", "1:1")
# Only models/values listed in the official API reference; seconds are also capped by MAX_SECONDS (spend guard).
MODELS = {
    "wan-2.2": dict(seconds=(3, 4, 5, 6, 7, 8, 9, 10), res=("480p", "720p", "1080p"), ratios=RATIOS, audio="not supported"),
    "ltx-2.3": dict(seconds=tuple(range(1, 11)), res=("480p", "720p", "1080p"), ratios=RATIOS, audio="no extra credits"),
    "ltx-2.5": dict(seconds=tuple(range(1, 11)), res=("480p", "720p", "1080p"), ratios=RATIOS, audio="no extra credits"),
    "kling-3.0": dict(seconds=tuple(range(3, 11)), res=("720p", "1080p"), ratios=RATIOS, audio="extra credits"),
    "veo3.1-lite": dict(seconds=(4, 6, 8), res=("720p", "1080p"), ratios=("16:9", "9:16"), audio="extra credits"),
}
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

class MagicHourError(Exception):
    def __init__(self, code, message, retryable=False, http=None):
        super().__init__(message)
        self.code, self.retryable, self.http = code, retryable, http

class Cancelled(Exception):
    pass

def api_key():
    return os.environ.get(ENV_KEY, "").strip() or None

def daily_limit():
    try:
        return max(1, int(os.environ.get(DAILY_ENV, "5")))
    except ValueError:
        return 5

def status():
    return {"provider": "magic_hour", "configured": bool(api_key()), "env_var": ENV_KEY,
            "max_seconds": MAX_SECONDS, "daily_limit": daily_limit(), "paid": True,
            "progress_supported": False, "cancel_supported": False,
            "models": {m: {"seconds": list(s["seconds"]), "resolutions": list(s["res"]),
                           "aspect_ratios": list(s["ratios"]), "audio": s["audio"]} for m, s in MODELS.items()}}

def validate(d):
    bad = lambda m: MagicHourError("invalid_request", m)
    if not isinstance(d, dict):
        raise bad("body must be an object")
    prompt = d.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise bad("prompt is required")
    prompt = prompt.strip()
    if len(prompt) > MAX_PROMPT:
        raise bad("prompt is too long (max %d characters)" % MAX_PROMPT)
    model = d.get("model", "ltx-2.5")
    if model not in MODELS:
        raise bad("unsupported model: use one of " + ", ".join(MODELS))
    spec = MODELS[model]
    secs = d.get("seconds", 5)
    if isinstance(secs, bool) or not isinstance(secs, int) or secs not in spec["seconds"]:
        raise bad("seconds for %s must be one of %s" % (model, list(spec["seconds"])))
    res = d.get("resolution", spec["res"][0])
    if res not in spec["res"]:
        raise bad("resolution for %s must be one of %s" % (model, list(spec["res"])))
    ratio = d.get("aspect_ratio", "16:9")
    if ratio not in spec["ratios"]:
        raise bad("aspect_ratio for %s must be one of %s" % (model, list(spec["ratios"])))
    audio = d.get("audio", False)
    if not isinstance(audio, bool):
        raise bad("audio must be true or false")
    if audio and spec["audio"] == "not supported":
        raise bad("%s does not support audio" % model)
    return dict(prompt=prompt, model=model, seconds=secs, resolution=res, aspect_ratio=ratio, audio=audio)

def guard(job_list, now=None):
    now = now or time.time()
    mine = [j for j in job_list if j.get("kind") == "aigen"]
    if any(j.get("state") in ("queued", "running") for j in mine):
        return 409, "an AI generation is already in progress"
    if sum(1 for j in mine if now - (j.get("created") or 0) < 86400) >= daily_limit():
        return 429, "daily AI generation limit reached (%d)" % daily_limit()
    return None

def _request(method, path, body=None, timeout=30):
    key = api_key()
    if not key:
        raise MagicHourError("not_configured", "MAGIC_HOUR_API_KEY is not set")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={
        "Authorization": "Bearer " + key, "Accept": "application/json",
        "Content-Type": "application/json", "User-Agent": "cinema-ai-studio/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(1048576)
    except urllib.error.HTTPError as e:
        try:
            info = json.loads(e.read(65536) or b"{}")
        except ValueError:
            info = {}
        if not isinstance(info, dict):
            info = {}
        code = info.get("code") if isinstance(info.get("code"), str) else "http_%d" % e.code
        if e.code == 401:
            msg = "invalid or revoked API key"
        else:
            msg = info.get("message") if isinstance(info.get("message"), str) else "HTTP %d" % e.code
        raise MagicHourError(code, msg, retryable=e.code == 429 or e.code >= 500, http=e.code)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MagicHourError("network", "cannot reach Magic Hour (%s)" % e.__class__.__name__, retryable=True)
    try:
        d = json.loads(raw)
    except ValueError:
        raise MagicHourError("bad_response", "Magic Hour returned malformed JSON")
    if not isinstance(d, dict):
        raise MagicHourError("bad_response", "unexpected response shape")
    return d

def submit(p):
    """The ONLY paid call. Never retried automatically (a retry could be charged twice)."""
    body = {"name": "CINEMA " + p["prompt"][:40], "end_seconds": p["seconds"], "aspect_ratio": p["aspect_ratio"],
            "resolution": p["resolution"], "model": p["model"], "audio": p["audio"], "style": {"prompt": p["prompt"]}}
    d = _request("POST", "/v1/text-to-video", body)
    if not isinstance(d.get("id"), str) or not ID_RE.match(d["id"]):
        raise MagicHourError("bad_response", "Magic Hour did not return a job id")
    return d

def fetch(pid):
    if not isinstance(pid, str) or not ID_RE.match(pid):
        raise MagicHourError("bad_response", "invalid provider job id")
    return _request("GET", "/v1/video-projects/" + quote(pid, safe=""))

def download(url, dest, cancelled=lambda: False):
    u = urlparse(url if isinstance(url, str) else "")
    if u.scheme != "https" or not u.netloc:
        raise MagicHourError("bad_output_url", "provider returned a non-https download URL")
    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    limit, n = MAX_DOWNLOAD_MB * 1048576, 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cinema-ai-studio/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
            while True:
                if cancelled():
                    raise Cancelled()
                b = r.read(262144)
                if not b:
                    break
                n += len(b)
                if n > limit:
                    raise MagicHourError("too_large", "generated video exceeds %d MB" % MAX_DOWNLOAD_MB)
                f.write(b)
        part.replace(dest)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MagicHourError("download_failed", "could not download the video (%s)" % e.__class__.__name__, retryable=True)
    finally:
        if part.exists():
            part.unlink()

def probe(path, seconds):
    """Strict validation: file exists, not tiny, has a video stream, plausible duration, first frames decode."""
    path = Path(path)
    bad = lambda m: MagicHourError("invalid_output", m)
    if not path.is_file() or path.stat().st_size < 1024:
        raise bad("output file is missing or too small")
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration",
                            "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
        data = json.loads(r.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        raise bad("ffprobe could not inspect the output")
    if r.returncode != 0:
        raise bad("ffprobe rejected the file")
    streams = data.get("streams") or []
    vs = [s for s in streams if s.get("codec_type") == "video"]
    if not vs:
        raise bad("no video stream in the output")
    try:
        dur = float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        raise bad("output has no readable duration")
    if not (max(0.5, seconds * 0.5) <= dur <= seconds * 2 + 2):
        raise bad("implausible duration %.1fs for %ds requested" % (dur, seconds))
    try:
        d = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "3", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        raise bad("could not run the decode check")
    if d.returncode != 0 or d.stderr.strip():
        raise bad("video failed the decode check")
    return {"duration": round(dur, 2), "width": vs[0].get("width"), "height": vs[0].get("height"),
            "codec": vs[0].get("codec_name"), "has_audio": any(s.get("codec_type") == "audio" for s in streams),
            "size_bytes": path.stat().st_size}

def _fail(store, jid, dest, msg):
    try:
        if Path(dest).exists():
            Path(dest).unlink()
    except OSError:
        pass
    try:
        store.transition(jid, "failed", error=msg)
    except JobError:
        pass

def run_job(cfg, store, jid, sleep=time.sleep, now=time.monotonic):
    try:
        store.transition(jid, "running")
    except JobError:
        return
    dest = cfg.jobs_dir / jid / "output" / "film.mp4"
    log = lambda m: store.log(jid, m)
    cancelled = lambda: store.get(jid)["state"] == "cancelled"
    try:
        p = store.get(jid)["params"]
        sub = submit(p)
        pid = sub["id"]
        (cfg.jobs_dir / jid / "provider.json").write_text(json.dumps(
            {"provider": "magic_hour", "provider_job": pid, "credits_estimate": sub.get("credits_charged")}))
        log("submitted provider_job=%s model=%s %ds %s credits_estimate=%s" % (
            pid, p["model"], p["seconds"], p["resolution"], sub.get("credits_charged")))
        t0, fails, d = now(), 0, {}
        while True:
            if cancelled():
                log("cancelled locally; the provider job (if still running) is NOT cancelled")
                return
            if now() - t0 > TIMEOUT_SECONDS:
                raise MagicHourError("timeout", "generation exceeded %d minutes" % (TIMEOUT_SECONDS // 60))
            try:
                d, fails = fetch(pid), 0
            except MagicHourError as e:
                if not e.retryable:
                    raise
                fails += 1
                log("poll problem %d: %s" % (fails, e.code))
                if fails >= 6:
                    raise
                sleep(POLL_SECONDS)
                continue
            st = d.get("status")
            if st == "complete":
                break
            if st == "error":
                err = d.get("error") if isinstance(d.get("error"), dict) else {}
                raise MagicHourError(str(err.get("code") or "provider_error"), str(err.get("message") or "provider reported an error"))
            if st == "canceled":
                raise MagicHourError("provider_canceled", "the job was canceled on the provider side")
            sleep(POLL_SECONDS)
        dl = d.get("downloads")
        url = dl[0].get("url") if isinstance(dl, list) and dl and isinstance(dl[0], dict) else None
        if not url:
            raise MagicHourError("no_output", "provider finished but returned no download URL")
        download(url, dest, cancelled)
        info = probe(dest, p["seconds"])
        log("validated: %s" % json.dumps(info))
        store.transition(jid, "completed")
    except Cancelled:
        log("cancelled during download")
        try:
            dest.unlink()
        except OSError:
            pass
    except MagicHourError as e:
        _fail(store, jid, dest, "%s: %s" % (e.code, e))
    except Exception as e:
        _fail(store, jid, dest, "unexpected error: %s" % e.__class__.__name__)
