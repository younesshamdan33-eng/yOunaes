"""Cinema Intelligence Engine: idea -> story -> memory -> shots -> engine routing -> persistent film project."""
import time
from . import director, looks, router, story
from .errors import CieError

DEFAULT_LIMITS = {"allowed_seconds": [3, 4, 5, 6, 8, 10]}

def plan(req, limits=None, stats=None):
    if not isinstance(req, dict):
        raise CieError("body must be an object")
    if req.get("planner", "rule_based") != "rule_based":
        raise CieError("planner '%s' is not available: only rule_based is implemented (an open-LLM planner needs the GPU worker, planned)" % req.get("planner"))
    look = req.get("look") or "cinematic"
    if look not in looks.LOOKS:
        raise CieError("unknown look: %s" % look)
    text = str(req.get("script") or req.get("idea") or "").strip()
    if not text:
        raise CieError("idea or script is required")
    if len(text) > 20000:
        raise CieError("text is too long (max 20000 characters)")
    target = req.get("target_seconds")
    if target is None:
        target = max(30, round(len(text.split()) / 2.5)) if req.get("script") else 60
    if isinstance(target, bool) or not isinstance(target, int) or not 10 <= target <= 7200:
        raise CieError("target_seconds must be an integer between 10 and 7200")
    try:
        st = story.plan_story(req, target)
    except ValueError as e:
        raise CieError(str(e))
    d = director.direct(st, looks.get(look)["prompt"], limits or DEFAULT_LIMITS, target)
    return {"planner": "rule_based", "language": st["language"], "look": look, "logline": st["logline"], "target_seconds": d["planned_target"],
            "limits": limits or DEFAULT_LIMITS, "scenes": d["scenes"], "memory": st["memory"], "warnings": st["warnings"] + d["warnings"],
            "totals": {"scenes": len(d["scenes"]), "shots": d["total_shots"], "seconds": d["total_seconds"]}}

def _need(req):
    return {"aspect_ratio": req.get("aspect_ratio") or "16:9", "resolution": req.get("resolution")}

def limits_for(engines, req, stats=None):
    dec = router.pick(engines, _need(req if isinstance(req, dict) else {}), stats)
    return {"allowed_seconds": dec["choice"]["allowed_seconds"], "engine": dec["choice"]} if dec["choice"] else DEFAULT_LIMITS

def engines_view(engines, stats=None):
    cands, rej = router.candidates(engines, {"aspect_ratio": "16:9"}, stats)
    return {"usable": cands, "rejected": rej}

def create_film(store, film_mod, registry, req, stats=None):
    if not isinstance(req, dict):
        raise CieError("body must be an object")
    prefer = (req.get("provider"), req.get("model")) if req.get("provider") else None
    dec = router.pick(list(registry.values()), _need(req), stats, prefer)
    ch = dec["choice"]
    if not ch:
        raise CieError("no generation engine is connected or usable", 503, dec["rejected"])
    p = plan(req, {"allowed_seconds": ch["allowed_seconds"], "engine": ch}, stats)
    from . import memory
    mem = p["memory"]
    first_loc = next(iter(mem["locations"].values()), None)
    spec = {"title": str(req.get("title") or p["logline"][:60] or "Film"), "provider": ch["provider"], "model": ch["model"], "resolution": ch["resolution"],
            "aspect_ratio": _need(req)["aspect_ratio"], "shot_seconds": director.pick(ch["allowed_seconds"], 5), "language": p["language"],
            "style_id": None, "scenes": [{"title": s["title"], "text": s["text"]} for s in p["scenes"]],
            "continuity": {"style": looks.get(p["look"])["prompt"][:200], "location": (first_loc or {}).get("look", "")[:200],
                           "characters": [memory.core(c)[:200] for c in mem["characters"].values()]}}
    spec = {k: v for k, v in spec.items() if v is not None}
    f = film_mod.create(store, spec)
    meta = {k: p[k] for k in ("planner", "language", "look", "logline", "target_seconds", "warnings", "totals")}
    meta.update(engine=ch, weak_continuity=dec["weak_continuity"], created=time.time())
    def apply(x):
        for i, sc in enumerate(x["scenes"]):
            sc["shots"] = p["scenes"][i]["shots"]
            sc["text"], sc["title"] = p["scenes"][i]["text"], p["scenes"][i]["title"]
        x["memory"], x["cie"], x["target_seconds"] = mem, meta, p["target_seconds"]
    return store.update(f["id"], apply)
