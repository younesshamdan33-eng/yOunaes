"""Quality Intelligence: checks finished clips (readable, really moving), prompt-level identity, colour continuity; recycles failures."""
import subprocess, time
from studio import magichour as mh
from worker import validate as wv
from . import memory
from .errors import CieError

def _frame(path, t=0.0, last=False):
    seek = ["-sseof", "-0.3"] if last else ["-ss", "%.3f" % t]
    r = subprocess.run(["ffmpeg", "-v", "error"] + seek + ["-i", str(path), "-frames:v", "1", "-vf", "scale=32:18", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True, timeout=60)
    return r.stdout if len(r.stdout) == 32 * 18 * 3 else None

def similarity(a, b):
    """Colour-histogram overlap (0..1) between the end of clip a and the start of clip b. Detects gross changes only, NOT identity."""
    fa, fb = _frame(a, last=True), _frame(b, 0.0)
    if not fa or not fb:
        return None
    def hist(buf):
        h, n = [0.0] * 48, len(buf) // 3
        for i in range(0, len(buf), 3):
            h[buf[i] // 16] += 1; h[16 + buf[i + 1] // 16] += 1; h[32 + buf[i + 2] // 16] += 1
        return [x / n for x in h]
    return round(sum(min(x, y) for x, y in zip(hist(fa), hist(fb))) / 3, 3)

def extract_anchor(clip, out_png):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-sseof", "-0.3", "-i", str(clip), "-frames:v", "1", str(out_png)], capture_output=True, timeout=60)
    return r.returncode == 0

def motion_issues(path, duration, samples=8):
    frames = [g for g in (wv._gray(path, duration * (i + 0.5) / samples) for i in range(samples)) if g]
    if len(frames) < 4:
        return [{"code": "undecodable", "severity": "error", "detail": "could not decode enough frames"}]
    d = [sum(abs(a - b) for a, b in zip(x, y)) / len(x) for x, y in zip(frames, frames[1:])]
    out = []
    if max(d) < 1.0:
        out.append({"code": "static", "severity": "error", "detail": "no real motion between frames"})
    elif sum(1 for x in d if x < 0.3) >= len(d) * 0.6:
        out.append({"code": "duplicated", "severity": "error", "detail": "mostly duplicated frames (slideshow-like)"})
    if all(sum(f) / len(f) < 2 or sum(f) / len(f) > 253 for f in frames):
        out.append({"code": "blank", "severity": "error", "detail": "blank frames"})
    return out

def prompt_issues(film, shot):
    mem, out = film.get("memory") or {}, []
    for cid in shot.get("characters", []):
        ch = (mem.get("characters") or {}).get(cid)
        if ch and memory.core(ch).lower() not in shot["prompt"].lower():
            out.append({"code": "identity_missing", "severity": "warn", "detail": "identity text of %s is missing from the prompt" % ch["name"]})
    return out

def review_film(store, fid, stats=None, limit=60):
    film = store.get(fid)
    results, prev_by_scene, checked = {}, {}, 0
    for sc in film["scenes"]:
        for sh in sc["shots"]:
            if sh["state"] != "completed" or not sh.get("output"):
                continue
            if checked >= limit:
                break
            checked += 1
            path, issues, sim = store.path(fid) / sh["output"], prompt_issues(film, sh), None
            try:
                mh.probe(path, sh["seconds"])
                dur = wv.probe(path)["duration"]
                issues += motion_issues(path, dur)
            except (mh.MagicHourError, ValueError, OSError, KeyError, subprocess.SubprocessError) as e:
                issues.append({"code": "unreadable", "severity": "error", "detail": str(e)[:160]})
            prev = prev_by_scene.get(sc["id"])
            if prev is not None and path.is_file():
                sim = similarity(prev, path)
                if sim is not None and sim < 0.35:
                    issues.append({"code": "continuity_shift", "severity": "warn", "detail": "large colour change from the previous shot (similarity %.2f)" % sim})
            if path.is_file():
                prev_by_scene[sc["id"]] = path
            sev = "error" if any(i["severity"] == "error" for i in issues) else "warn" if issues else "ok"
            results[sh["id"]] = {"checked": time.time(), "issues": issues, "severity": sev, "similarity": sim, "counted": bool((sh.get("quality") or {}).get("counted"))}
    def apply(f):
        for sc in f["scenes"]:
            for sh in sc["shots"]:
                r = results.get(sh["id"])
                if r:
                    if stats and not r["counted"]:
                        stats.record("%s:%s" % (f["provider"], f["model"]), r["severity"] != "error")
                    r["counted"] = True
                    sh["quality"] = r
        f.setdefault("cie", {})["review"] = {"time": time.time(), "checked": len(results),
                                             "errors": [k for k, v in results.items() if v["severity"] == "error"],
                                             "warnings": [k for k, v in results.items() if v["severity"] == "warn"]}
    store.update(fid, apply)
    rv = store.get(fid)["cie"]["review"]
    return dict(rv, partial=checked >= limit, recommend_redo=rv["errors"])

def improve_prompt(prompt, issues):
    codes, add = {i.get("code") for i in issues}, []
    if codes & {"static", "duplicated"}:
        add.append("clear visible subject motion, dynamic camera movement")
    if "blank" in codes:
        add.append("well lit, clearly visible subject")
    if "continuity_shift" in codes:
        add.append("consistent lighting and colour palette with the previous shot")
    new = prompt
    for a in add:
        if a not in new:
            new += ", " + a
    return new[:2000]

def recycle(store, fid, sid, free, confirm_cost):
    if not free and confirm_cost is not True:
        raise CieError("recycling submits a new paid request: confirm_cost=true is required")
    def fn(f):
        if f["state"] == "running":
            raise CieError("film is running: cancel it first", 409)
        shot = next((s for sc in f["scenes"] for s in sc["shots"] if s["id"] == sid), None)
        if shot is None:
            raise CieError("shot not found", 404)
        if shot["state"] not in ("failed", "completed"):
            raise CieError("only failed or completed shots can be recycled")
        issues = list((shot.get("quality") or {}).get("issues", []))
        if shot["state"] == "failed" and shot.get("error"):
            issues.append({"code": "provider_error", "severity": "error", "detail": shot["error"]})
        shot.setdefault("history", []).append({"time": time.time(), "prompt": shot["prompt"], "error": shot.get("error"), "issues": issues, "output": shot.get("output")})
        shot["prompt"] = improve_prompt(shot["prompt"], issues)
        shot.update(state="pending", provider_job=None, attempts=0, error=None, output=None, next_try=None, ambiguous=False, quality=None)
        f["state"], f["error"] = "interrupted", None
    return store.update(fid, fn)
