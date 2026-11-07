"""Long-form film engine: film -> scenes -> shots -> per-shot generation -> assembly.
Provider-agnostic (providers.py). State is persisted, so a film survives restarts: a shot with a recorded
provider job is re-polled, never re-submitted (re-submitting costs credits)."""
import json, math, re, shutil, subprocess, threading, time, uuid
from . import providers, render
from . import magichour as mh
from .providers import ProviderError

ID_RE = re.compile(r"^[0-9a-f]{32}$")
SID_RE = re.compile(r"^s\d{1,3}-\d{1,3}$")
MAX_SHOTS, MAX_SCENES, MAX_TARGET, MAX_PROMPT = 600, 200, 7200, 2000
FATAL = {"plan_upgrade_required", "unauthorized", "insufficient_credits", "not_configured", "invalid_request"}
OPEN_STATES = ("pending", "retrying", "running")

class FilmError(Exception):
    pass
class FilmNotFound(FilmError):
    pass

class FilmStore:
    def __init__(self, cfg):
        self.dir = cfg.root / "var" / "films"
        self.lock = threading.RLock()
    def path(self, fid):
        if not isinstance(fid, str) or not ID_RE.match(fid):
            raise FilmNotFound("film not found")
        return self.dir / fid
    def get(self, fid):
        try:
            return json.loads((self.path(fid) / "film.json").read_text())
        except FileNotFoundError:
            raise FilmNotFound("film not found")
        except (OSError, ValueError):
            raise FilmError("film file unreadable")
    def save(self, f):
        with self.lock:
            d = self.path(f["id"]); d.mkdir(parents=True, exist_ok=True)
            f["updated"] = time.time()
            tmp = d / "film.json.tmp"
            tmp.write_text(json.dumps(f, indent=1))
            tmp.replace(d / "film.json")
    def update(self, fid, fn):
        with self.lock:
            f = self.get(fid); fn(f); self.save(f)
            return f
    def list(self):
        out = []
        if self.dir.is_dir():
            for d in sorted(self.dir.iterdir()):
                if ID_RE.match(d.name):
                    try:
                        out.append(self.get(d.name))
                    except FilmError:
                        pass
        return sorted(out, key=lambda f: f.get("created", 0))
    def log(self, fid, msg):
        try:
            with open(self.path(fid) / "film.log", "a") as fh:
                fh.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
        except OSError:
            pass
    # Local record of credits the provider reported. NOT the provider's real balance.
    def _lp(self):
        return self.dir / "ledger.json"
    def ledger_add(self, fid, credits, now):
        if isinstance(credits, bool) or not isinstance(credits, (int, float)) or credits <= 0:
            return
        with self.lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            try:
                rows = json.loads(self._lp().read_text())
            except (OSError, ValueError):
                rows = []
            rows = (rows + [{"t": now, "film": fid, "credits": credits}])[-2000:]
            tmp = self.dir / "ledger.json.tmp"
            tmp.write_text(json.dumps(rows)); tmp.replace(self._lp())
    def spent(self, window, now):
        try:
            rows = json.loads(self._lp().read_text())
        except (OSError, ValueError):
            return 0
        return sum(r.get("credits", 0) for r in rows if now - r.get("t", 0) < window)
    def recover(self):
        n = 0
        for f in self.list():
            if f["state"] == "running":
                self.update(f["id"], lambda x: x.update(state="interrupted", error="server restarted: resume to continue (provider jobs are re-polled, never re-submitted)"))
                n += 1
            if (f.get("assembly") or {}).get("state") == "running":
                self.update(f["id"], lambda x: x.update(assembly={"state": "failed", "error": "interrupted by a restart"}))
        return n

def _s(v, n):
    return v.strip()[:n] if isinstance(v, str) else ""

def _find(f, sid):
    if not isinstance(sid, str) or not SID_RE.match(sid):
        raise FilmError("invalid shot id")
    for sc in f["scenes"]:
        for s in sc["shots"]:
            if s["id"] == sid:
                return s
    raise FilmError("shot not found")

def build_prompt(f, sc, j, k):
    c = f.get("continuity") or {}
    bits = [sc["text"]]
    if c.get("style"): bits.append("Visual style: " + c["style"])
    if c.get("location"): bits.append("Location: " + c["location"])
    if c.get("characters"): bits.append("Recurring characters (keep their appearance identical): " + "; ".join(c["characters"]))
    if k > 1: bits.append("Shot %d of %d in this scene, same setting and subjects." % (j + 1, k))
    return " | ".join(bits)[:MAX_PROMPT]

def plan_film(spec):
    if not isinstance(spec, dict):
        raise FilmError("body must be an object")
    title = _s(spec.get("title"), 100)
    if not title:
        raise FilmError("title is required")
    try:
        prov = providers.get(spec.get("provider", "magic_hour"))
    except ProviderError as e:
        raise FilmError(str(e))
    shot = spec.get("shot_seconds", 5)
    if isinstance(shot, bool) or not isinstance(shot, int):
        raise FilmError("shot_seconds must be an integer")
    try:
        req = prov.validate({"prompt": "x", "model": spec.get("model", "ltx-2.5"), "seconds": shot,
                             "resolution": spec.get("resolution", "480p"), "aspect_ratio": spec.get("aspect_ratio", "16:9"),
                             "audio": spec.get("audio", False)})
    except ProviderError as e:
        raise FilmError(str(e))
    raw = spec.get("scenes")
    if raw is None and isinstance(spec.get("script"), str):
        raw = render.plan_scenes(spec["script"])
    if not isinstance(raw, list) or not raw:
        raise FilmError("provide scenes (a non-empty list) or a script")
    if len(raw) > MAX_SCENES:
        raise FilmError("too many scenes (%d); max %d" % (len(raw), MAX_SCENES))
    scenes = []
    for i, r in enumerate(raw, 1):
        text = _s(r.get("text") or r.get("description"), 1000) if isinstance(r, dict) else _s(r, 1000)
        if not text:
            raise FilmError("scene %d is empty" % i)
        ttl = (_s(r.get("title"), 80) if isinstance(r, dict) else "") or "Scene %d" % i
        scenes.append({"id": "s%d" % i, "title": ttl, "text": text, "shots": []})
    target = spec.get("target_seconds")
    if target is not None and (isinstance(target, bool) or not isinstance(target, int) or not 2 <= target <= MAX_TARGET):
        raise FilmError("target_seconds must be an integer between 2 and %d" % MAX_TARGET)
    fps = spec.get("fps", 24)
    if isinstance(fps, bool) or not isinstance(fps, int) or not 12 <= fps <= 60:
        raise FilmError("fps must be an integer between 12 and 60")
    n = len(scenes)
    total = max(n, math.ceil((target or 0) / shot))
    if total > MAX_SHOTS:
        raise FilmError("too many shots (%d); max %d: raise shot_seconds or lower the target" % (total, MAX_SHOTS))
    c = spec.get("continuity") if isinstance(spec.get("continuity"), dict) else {}
    chars = c.get("characters") if isinstance(c.get("characters"), list) else []
    cont = {"style": _s(c.get("style"), 200), "location": _s(c.get("location"), 200),
            "characters": [_s(x, 200) for x in chars if isinstance(x, str) and x.strip()][:10]}
    f = {"id": uuid.uuid4().hex, "title": title, "state": "draft", "created": time.time(), "updated": time.time(),
         "provider": prov.name, "model": req["model"], "resolution": req["resolution"], "aspect_ratio": req["aspect_ratio"],
         "audio": req["audio"], "fps": fps, "shot_seconds": shot, "target_seconds": target,
         "language": _s(spec.get("language"), 8) or "en", "continuity": cont,
         "budget": {"confirmed": False, "daily_cap": None, "total_cap": None, "auto_resume": False},
         "credits_spent": 0, "scenes": scenes, "output": None, "assembly": None, "error": None}
    base, extra = divmod(total, n)
    for i, sc in enumerate(scenes):
        k = base + (1 if i < extra else 0)
        for j in range(k):
            sc["shots"].append({"id": "%s-%d" % (sc["id"], j + 1), "prompt": build_prompt(f, sc, j, k), "seconds": shot,
                                "state": "pending", "attempts": 0, "provider_job": None, "credits": None, "error": None,
                                "output": None, "next_try": None, "ambiguous": False})
    return f

def create(store, spec):
    f = plan_film(spec)
    store.save(f)
    store.log(f["id"], "created: %d scenes" % len(f["scenes"]))
    return f

def shot_req(f, s):
    return {"prompt": s["prompt"], "model": f["model"], "seconds": s["seconds"], "resolution": f["resolution"],
            "aspect_ratio": f["aspect_ratio"], "audio": f["audio"]}

def summary(f):
    shots = [s for sc in f["scenes"] for s in sc["shots"]]
    cnt = {}
    for s in shots:
        cnt[s["state"]] = cnt.get(s["state"], 0) + 1
    total = sum(s["seconds"] for s in shots) or 1
    done = sum(s["seconds"] for s in shots if s["state"] == "completed")
    return {"shots": len(shots), "by_state": cnt, "seconds_total": total, "seconds_done": done,
            "percent": round(100 * done / total, 1), "credits_spent": f.get("credits_spent", 0)}

def estimate(f):
    try:
        prov = providers.get(f["provider"])
    except ProviderError:
        return {"credits": None, "days": None}
    tot, known = 0, True
    for sc in f["scenes"]:
        for s in sc["shots"]:
            if s["state"] in ("pending", "retrying"):
                e = prov.estimate_credits(shot_req(f, s))
                if e is None: known = False
                else: tot += e
    cap = (f.get("budget") or {}).get("daily_cap")
    return {"credits": tot if known else None, "days": math.ceil(tot / cap) if known and cap and tot else None,
            "note": "estimate from known per-second rates; the real charge is the credits reported by the provider"}

def arm(store, fid, confirm_cost, daily_cap=None, total_cap=None, auto_resume=False):
    if confirm_cost is not True:
        raise FilmError("paid generation needs confirm_cost=true")
    for k, v in (("daily_cap", daily_cap), ("total_cap", total_cap)):
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 1):
            raise FilmError("%s must be a positive integer (credits)" % k)
    if daily_cap is None and total_cap is None:
        raise FilmError("set daily_cap and/or total_cap (credits) to protect against overspending")
    def fn(f):
        if f["state"] == "running":
            raise FilmError("film is already running")
        f["budget"] = {"confirmed": True, "daily_cap": daily_cap, "total_cap": total_cap, "auto_resume": bool(auto_resume)}
        f["state"], f["error"] = "running", None
    return store.update(fid, fn)

def cancel(store, fid):
    def fn(f):
        if f["state"] not in ("running", "waiting_budget", "interrupted"):
            raise FilmError("film is not active")
        f["state"] = "cancelled"
    f = store.update(fid, fn)
    store.log(fid, "cancelled by user; provider jobs already submitted are NOT cancelled (credits may be spent)")
    return f

def resume(store, fid):
    def fn(f):
        if f["state"] == "running":
            raise FilmError("film is already running")
        if f["state"] not in ("waiting_budget", "interrupted", "cancelled", "failed"):
            raise FilmError("nothing to resume in state %s" % f["state"])
        if not (f.get("budget") or {}).get("confirmed"):
            raise FilmError("start the film first (budget confirmation required)")
        f["state"], f["error"] = "running", None
    return store.update(fid, fn)

def retry_shot(store, fid, sid, confirm_cost=False, resubmit=False, acknowledge=False):
    def fn(f):
        if f["state"] == "running":
            raise FilmError("film is running: cancel it first")
        s = _find(f, sid)
        if s["state"] != "failed":
            raise FilmError("only failed shots can be retried")
        if s.get("provider_job") and not resubmit:
            s.update(state="running", error=None)            # re-poll the existing job: no new charge
        else:
            if confirm_cost is not True:
                raise FilmError("retry submits a new paid request: confirm_cost=true required")
            if s.get("ambiguous") and acknowledge is not True:
                raise FilmError("the previous request may already have been charged; pass acknowledge_possible_charge=true")
            s.update(state="pending", provider_job=None, attempts=0, next_try=None, error=None, ambiguous=False)
        f["state"], f["error"] = "interrupted", None
    return store.update(fid, fn)

def retry_failed(store, fid, confirm_cost=False, acknowledge=False):
    """Reset every failed shot at once. Shots that already have a provider job are re-polled (no new charge)."""
    def fn(f):
        if f["state"] == "running":
            raise FilmError("film is running: cancel it first")
        bad = [s for sc in f["scenes"] for s in sc["shots"] if s["state"] == "failed"]
        if not bad:
            raise FilmError("no failed shots")
        for s in bad:
            if s.get("provider_job"):
                continue
            if confirm_cost is not True:
                raise FilmError("retry submits new paid requests: confirm_cost=true required")
            if s.get("ambiguous") and acknowledge is not True:
                raise FilmError("a previous request may already have been charged; pass acknowledge_possible_charge=true")
        for s in bad:
            if s.get("provider_job"):
                s.update(state="running", error=None)
            else:
                s.update(state="pending", provider_job=None, attempts=0, next_try=None, error=None, ambiguous=False)
        f["state"], f["error"] = "interrupted", None
    return store.update(fid, fn)

def dims(resolution, ratio):
    short = {"480p": 480, "720p": 720, "1080p": 1080, "4k": 2160}[resolution]
    ev = lambda v: int(v) // 2 * 2
    if ratio == "9:16": return ev(short), ev(short * 16 / 9)
    if ratio == "1:1": return short, short
    return ev(short * 16 / 9), short

def norm_cmd(src, dst, w, h, fps, has_audio):
    vf = "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,fps=%d,format=yuv420p" % (w, h, w, h, fps)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += ["-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "26", "-c:a", "aac", "-ar", "44100", "-ac", "2"]
    if not has_audio:
        cmd.append("-shortest")
    return cmd + [dst]

def _assembly_plan(f, allow_partial):
    if f["state"] == "running":
        raise FilmError("film is still generating")
    shots = [s for sc in f["scenes"] for s in sc["shots"]]
    done = [s for s in shots if s["state"] == "completed"]
    missing = [s["id"] for s in shots if s["state"] != "completed"]
    if not done:
        raise FilmError("no completed clips to assemble")
    if missing and not allow_partial:
        raise FilmError("shots not completed: %s (allow_partial=true assembles what exists)" % ", ".join(missing[:10]))
    return done, missing

def assemble(cfg, store, fid, allow_partial=False, run=subprocess.run):
    f = store.get(fid)
    done, missing = _assembly_plan(f, allow_partial)
    d = store.path(fid)
    work, out_dir = d / "work", d / "output"
    work.mkdir(exist_ok=True); out_dir.mkdir(exist_ok=True)
    need = int(sum((d / s["output"]).stat().st_size for s in done) * 2 / 1048576) + 20
    free = shutil.disk_usage(d).free // 1048576
    if free - need < cfg.min_free_mb:
        raise FilmError("insufficient storage (%d MB free, need ~%d MB + %d MB reserve)" % (free, need, cfg.min_free_mb))
    w, h = dims(f["resolution"], f["aspect_ratio"])
    fps = f.get("fps", 24)
    names, lst, final = [], work / "list.txt", out_dir / "film.mp4"
    try:
        for i, s in enumerate(done):
            dst = work / ("n%03d.mp4" % i)
            r = run(norm_cmd(str(d / s["output"]), str(dst), w, h, fps, bool((s.get("media") or {}).get("has_audio"))),
                    capture_output=True, text=True, timeout=600)
            if r.returncode != 0 or not dst.exists():
                raise FilmError("could not normalize %s: %s" % (s["id"], (r.stderr or "")[-200:].strip()))
            names.append(dst)
        lst.write_text("".join("file '%s'\n" % n for n in names))
        r = run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(final)],
                capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            raise FilmError("concat failed: %s" % (r.stderr or "")[-200:].strip())
        info = mh.probe(final, sum(s["seconds"] for s in done))
    except mh.MagicHourError as e:
        final.unlink(missing_ok=True)
        raise FilmError("final video failed validation: %s" % e)
    finally:
        for n in names + [lst]:
            n.unlink(missing_ok=True)
        try:
            work.rmdir()
        except OSError:
            pass
    store.update(fid, lambda x: x.update(state="assembled", output={"path": "output/film.mp4", "media": info,
                                                                  "partial": bool(missing), "missing": missing}))
    store.log(fid, "assembled: %s" % json.dumps(info))
    return info

class FilmRunner:
    def __init__(self, cfg, store, sleep=time.sleep, now=time.time, poll_seconds=8,
                 backoff=(30, 90, 240), max_attempts=3, shot_timeout=1500):
        self.cfg, self.st, self.sleep, self.now = cfg, store, sleep, now
        self.poll_seconds, self.backoff, self.max_attempts, self.shot_timeout = poll_seconds, backoff, max_attempts, shot_timeout
        self.active, self.asm_active, self._lk, self.wait_tries = set(), set(), threading.Lock(), 50

    def start(self, fid):
        t = threading.Thread(target=self.run, args=(fid,), daemon=True)
        t.start()
        return t

    def run(self, fid):
        for _ in range(self.wait_tries):
            with self._lk:
                if fid not in self.active:
                    self.active.add(fid)
                    break
            time.sleep(0.1)
        else:
            return False
        try:
            self._loop(fid)
        except Exception as e:
            self.st.log(fid, "runner crashed: %s" % e.__class__.__name__)
            try:
                self.st.update(fid, lambda x: x.update(state="interrupted", error="internal error: %s" % e.__class__.__name__) if x["state"] == "running" else None)
            except FilmError:
                pass
        finally:
            with self._lk:
                self.active.discard(fid)
        return True

    def _stopped(self, fid):
        return self.st.get(fid)["state"] != "running"

    def _nap(self, fid, secs):
        left = secs
        while left > 0:
            step = min(5, left)
            self.sleep(step); left -= step
            if self._stopped(fid):
                return False
        return True

    def _next(self, f):
        for sc in f["scenes"]:
            for s in sc["shots"]:
                if s["state"] in OPEN_STATES:
                    return s["id"]
        return None

    def _budget(self, f, est):
        b = f.get("budget") or {}
        if not b.get("confirmed"):
            return False, "paid generation was not confirmed"
        dc, tc = b.get("daily_cap"), b.get("total_cap")
        if est is None:
            if dc or tc:
                return False, "cost unknown for this model/resolution: credit caps cannot be enforced"
            return True, None
        spent = self.st.spent(86400, self.now())
        if dc is not None and spent + est > dc:
            return False, "daily credit cap reached (%d spent in 24h, cap %d)" % (spent, dc)
        if tc is not None and f.get("credits_spent", 0) + est > tc:
            return False, "total credit cap reached (cap %d)" % tc
        return True, None

    def _loop(self, fid):
        while True:
            f = self.st.get(fid)
            if f["state"] != "running":
                return
            sid = self._next(f)
            if sid is None:
                bad = any(s["state"] == "failed" for sc in f["scenes"] for s in sc["shots"])
                self.st.update(fid, lambda x: x.update(state="failed" if bad else "generated",
                                                        error="some shots failed: retry them individually" if bad else None))
                self.st.log(fid, "generation finished (%s)" % ("with failures" if bad else "all shots complete"))
                return
            if self._do_shot(fid, sid) == "stop":
                return

    def _do_shot(self, fid, sid):
        f = self.st.get(fid)
        shot = _find(f, sid)
        prov = providers.get(f["provider"])
        req = shot_req(f, shot)
        if not shot.get("provider_job"):
            wait = (shot.get("next_try") or 0) - self.now()
            if shot["state"] == "retrying" and wait > 0 and not self._nap(fid, wait):
                return "stop"
            ok, why = self._budget(f, prov.estimate_credits(req))
            if not ok:
                self.st.update(fid, lambda x: x.update(state="waiting_budget", error=why))
                self.st.log(fid, "waiting for budget: %s" % why)
                return "stop"
            try:
                sub = prov.submit(req)
            except ProviderError as e:
                return self._submit_failed(fid, sid, e)
            jid, cr = sub["id"], sub.get("credits")
            def m(x):
                s = _find(x, sid)
                s.update(state="running", provider_job=jid, credits=cr, attempts=s["attempts"] + 1, error=None)
                if isinstance(cr, (int, float)) and not isinstance(cr, bool):
                    x["credits_spent"] = x.get("credits_spent", 0) + cr
            self.st.update(fid, m)
            self.st.ledger_add(fid, cr, self.now())
            self.st.log(fid, "%s submitted job=%s credits=%s" % (sid, jid, cr))
        else:
            jid = shot["provider_job"]
            self.st.log(fid, "%s resuming existing provider job %s (no new submission)" % (sid, jid))
        return self._poll_and_fetch(fid, sid, prov, jid)

    def _submit_failed(self, fid, sid, e):
        self.st.log(fid, "%s submit failed: %s (%s)" % (sid, e.code, e))
        if e.ambiguous:
            msg = "%s: %s -- the request may have been charged; check the provider dashboard, then retry manually" % (e.code, e)
            def m(x):
                _find(x, sid).update(state="failed", error=msg[:300], ambiguous=True)
                x.update(state="interrupted", error=msg[:300])
            self.st.update(fid, m)
            return "stop"
        if e.code in FATAL:
            def m(x):
                _find(x, sid).update(state="failed", error="%s: %s" % (e.code, e))
                x.update(state="failed", error="stopped: %s: %s" % (e.code, e))
            self.st.update(fid, m)
            return "stop"
        attempts = _find(self.st.get(fid), sid)["attempts"] + 1
        if e.retryable and attempts < self.max_attempts:
            delay = self.backoff[min(attempts - 1, len(self.backoff) - 1)]
            self.st.update(fid, lambda x: _find(x, sid).update(state="retrying", attempts=attempts, next_try=self.now() + delay,
                                                                error="%s: %s (retry in %ds)" % (e.code, e, delay)))
            return "go"
        return self._shot_fail(fid, sid, "%s: %s" % (e.code, e))

    def _shot_fail(self, fid, sid, msg, keep_job=False):
        def m(x):
            s = _find(x, sid)
            s.update(state="failed", error=msg[:300])
            if not keep_job:
                s["provider_job"] = None
        self.st.update(fid, m)
        self.st.log(fid, "%s failed: %s" % (sid, msg))
        return "go"

    def _poll_and_fetch(self, fid, sid, prov, jid):
        t0, fails, p = self.now(), 0, {}
        while True:
            if self._stopped(fid):
                return "stop"
            if self.now() - t0 > self.shot_timeout:
                self.st.update(fid, lambda x: x.update(state="interrupted", error="timed out waiting for %s; resume to keep polling (the provider job is kept)" % sid))
                return "stop"
            try:
                p = prov.poll(jid)
            except ProviderError as e:
                if e.retryable and fails < 5:
                    fails += 1
                    self.st.log(fid, "%s poll problem %d: %s" % (sid, fails, e.code))
                    if not self._nap(fid, self.poll_seconds):
                        return "stop"
                    continue
                if e.retryable:
                    self.st.update(fid, lambda x: x.update(state="interrupted", error="provider unreachable; resume later (job %s is kept)" % sid))
                    return "stop"
                return self._shot_fail(fid, sid, "%s: %s" % (e.code, e))
            fails = 0
            if p["state"] == "complete":
                break
            if p["state"] == "error":
                return self._shot_fail(fid, sid, p.get("error") or "provider error")
            if not self._nap(fid, self.poll_seconds):
                return "stop"
        dest = self.st.path(fid) / "clips" / (sid + ".mp4")
        dest.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(3):
            try:
                prov.download(p["url"], dest, lambda: self._stopped(fid))
                break
            except mh.Cancelled:
                dest.unlink(missing_ok=True)
                return "stop"
            except ProviderError as e:
                if e.retryable and attempt < 2:
                    if not self._nap(fid, 5 * (attempt + 1)):
                        return "stop"
                    continue
                return self._shot_fail(fid, sid, "%s: %s" % (e.code, e), keep_job=True)
        seconds = _find(self.st.get(fid), sid)["seconds"]
        try:
            info = mh.probe(dest, seconds)
        except mh.MagicHourError as e:
            dest.unlink(missing_ok=True)
            return self._shot_fail(fid, sid, "%s: %s" % (e.code, e))
        self.st.update(fid, lambda x: _find(x, sid).update(state="completed", output="clips/%s.mp4" % sid, media=info, error=None))
        self.st.log(fid, "%s completed: %s" % (sid, json.dumps(info)))
        return "go"

    def assemble_bg(self, fid, allow_partial=False):
        f = self.st.get(fid)
        _assembly_plan(f, allow_partial)
        with self._lk:
            if fid in self.asm_active:
                raise FilmError("assembly already running")
            self.asm_active.add(fid)
        self.st.update(fid, lambda x: x.update(assembly={"state": "running", "error": None}))
        def job():
            try:
                assemble(self.cfg, self.st, fid, allow_partial)
                self.st.update(fid, lambda x: x.update(assembly={"state": "done", "error": None}))
            except FilmError as e:
                self.st.update(fid, lambda x: x.update(assembly={"state": "failed", "error": str(e)[:300]}))
            except Exception as e:
                self.st.update(fid, lambda x: x.update(assembly={"state": "failed", "error": "unexpected error: %s" % e.__class__.__name__}))
            finally:
                with self._lk:
                    self.asm_active.discard(fid)
        t = threading.Thread(target=job, daemon=True)
        t.start()
        return t

    def tick(self):
        """Auto-resume films waiting for budget (only films the user flagged auto_resume, within their caps)."""
        started = []
        for f in self.st.list():
            if f["state"] != "waiting_budget" or not (f.get("budget") or {}).get("auto_resume"):
                continue
            sid = self._next(f)
            if sid is None:
                continue
            try:
                est = providers.get(f["provider"]).estimate_credits(shot_req(f, _find(f, sid)))
                if not self._budget(f, est)[0]:
                    continue
                resume(self.st, f["id"])
            except (ProviderError, FilmError):
                continue
            started.append(self.start(f["id"]))
        return started

    def start_ticker(self, interval=300):
        def loop():
            while True:
                time.sleep(interval)
                try:
                    self.tick()
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()
