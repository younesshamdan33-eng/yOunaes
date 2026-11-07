"""Adaptive Shot Router: ranks usable engine/model pairs for a shot's needs and says why others were rejected."""
RANK = {"ai_video": 3, "image_motion": 1, "procedural": 0}

def candidates(engines, need, stats=None):
    out, rej = [], []
    for p in engines:
        d = p.describe() if hasattr(p, "describe") else p
        name = d["name"]
        if not d.get("configured"):
            rej.append({"provider": name, "reason": "not configured / not connected"}); continue
        kind = d.get("kind", "ai_video")
        for mname, m in (d.get("models") or {}).items():
            key = "%s:%s" % (name, mname)
            if m.get("plan_note"):
                rej.append({"provider": name, "model": mname, "reason": m["plan_note"]}); continue
            if need.get("aspect_ratio", "16:9") not in (m.get("aspect_ratios") or []):
                rej.append({"provider": name, "model": mname, "reason": "aspect ratio %s not supported" % need.get("aspect_ratio", "16:9")}); continue
            if not m.get("seconds"):
                rej.append({"provider": name, "model": mname, "reason": "no supported durations"}); continue
            resl = m.get("resolutions") or []
            res = need.get("resolution") if need.get("resolution") in resl else (resl[0] if resl else None)
            rate = stats.rate(key) if stats else 0.5
            score = RANK.get(kind, 1) * 10 + rate * 5 - (0 if d.get("free") else 2) + (1 if d.get("open_weights") else 0)
            out.append({"provider": name, "model": mname, "kind": kind, "real_ai_video": kind == "ai_video", "resolution": res,
                        "allowed_seconds": sorted(m["seconds"]), "score": round(score, 2), "free": bool(d.get("free")), "i2v": bool(m.get("i2v"))})
    out.sort(key=lambda c: -c["score"])
    return out, rej

def pick(engines, need, stats=None, prefer=None):
    cands, rej = candidates(engines, need, stats)
    if prefer and prefer[0]:
        cands = [c for c in cands if c["provider"] == prefer[0] and (not prefer[1] or c["model"] == prefer[1])]
    best = cands[0] if cands else None
    return {"choice": best, "alternatives": cands[1:4], "rejected": rej, "weak_continuity": bool(need.get("needs_anchor") and best and not best["i2v"])}
