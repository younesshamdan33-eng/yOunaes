"""Production planner: screenplay -> characters (identity bible) -> voices -> shots with compiled prompts."""
import random, re, zlib
from . import looks, script, voices

class ProdError(ValueError):
    pass

ENGINES = ("image_motion", "cards")
ASPECTS = ("16:9", "9:16", "1:1")
RES = ("144p", "480p", "720p")
PALETTES = ["navy blue and orange", "forest green and cream", "crimson and charcoal", "teal and sand", "violet and silver", "mustard yellow and brown", "white and sky blue", "burgundy and gold"]
TIMES = [(("night", "midnight", "ليل"), "at night, moonlight and deep blue shadows"), (("dawn", "sunrise", "morning", "فجر", "صباح", "شروق"), "at dawn, soft golden light"),
         (("sunset", "dusk", "evening", "غروب", "مساء"), "at golden-hour sunset, long warm shadows"), (("day", "noon", "نهار", "ظهر"), "in bright natural daylight")]

def ascii_only(s):
    return all(ord(c) < 128 for c in s or "")

def time_frag(t):
    low = (t or "").lower()
    for words, frag in TIMES:
        if any(x in low for x in words):
            return frag
    return ""

def identity(ch):
    nm = ch["name"] if ascii_only(ch["name"]) else ""
    return "%sa %s %s, %s, %s accents" % ((nm + ", ") if nm else "", ch["age"], ch["role"], ch["look"], ch["palette"])

def _flag(req, name, default):
    v = req.get(name, default)
    if not isinstance(v, bool):
        raise ProdError("%s must be true or false" % name)
    return v

def _int(req, name, default, lo, hi):
    v = req.get(name, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ProdError("%s must be an integer between %d and %d" % (name, lo, hi))
    return v

def _settings(req, kind):
    look = req.get("look") or "cinematic"
    if look not in looks.LOOKS:
        raise ProdError("unknown look: %s" % look)
    engine = req.get("engine") or "image_motion"
    if engine not in ENGINES:
        raise ProdError("engine must be one of %s" % list(ENGINES))
    aspect, res = req.get("aspect_ratio") or "16:9", req.get("resolution") or "480p"
    if aspect not in ASPECTS:
        raise ProdError("aspect_ratio must be one of %s" % list(ASPECTS))
    if res not in RES:
        raise ProdError("resolution must be one of %s" % list(RES))
    seed = _int(req, "seed", random.randint(0, 999999), 0, 999999)
    return dict(look=look, engine=engine, aspect_ratio=aspect, resolution=res, voices=_flag(req, "voices", True), music=_flag(req, "music", True),
                subtitles=_flag(req, "subtitles", kind == "film"), narrate_actions=_flag(req, "narrate_actions", False),
                action_seconds=_int(req, "action_seconds", 4, 2, 15), allow_fallback=_flag(req, "allow_fallback", False), seed=seed)

def _short_parsed(req):
    prompt = req.get("prompt")
    if not isinstance(prompt, str) or not 3 <= len(prompt.strip()) <= 500:
        raise ProdError("prompt must be text between 3 and 500 characters")
    narr = req.get("narration") or ""
    if not isinstance(narr, str) or len(narr) > 300:
        raise ProdError("narration must be text up to 300 characters")
    beat = dict(kind="narration" if narr.strip() else "action", speaker=None, emotion=None, text=narr.strip() or prompt.strip(), visual=prompt.strip())
    return dict(scenes=[dict(id="s1", heading="", location="", time="", beats=[beat])], characters=[], warnings=[]), _int(req, "seconds", 5, 3, 15)

def _compile(st, sc, b, present, chars, warn):
    lk = looks.get(st["look"])
    if b.get("visual"):
        core = b["visual"]
    elif b["kind"] == "action" and ascii_only(b["text"]):
        core = b["text"][:240]
    elif b["kind"] == "dialogue":
        sp = b["speaker"] if ascii_only(b["speaker"]) else "a character"
        emo = b["emotion"] if b.get("emotion") and ascii_only(b["emotion"]) else "natural"
        core = "%s speaking with a %s expression, medium close-up" % (sp, emo)
    else:
        core = "a dramatic cinematic moment"
        warn.add("Some beats have non-English text without a (visual: ...) hint: their images are generic. Add English (visual: ...) lines for exact images.")
    parts = [core] + [identity(chars[n]) for n in present]
    parts += [("Location: " + sc["location"]) if sc["location"] and ascii_only(sc["location"]) else "", time_frag(sc["time"] or sc["heading"]), looks.get(st["look"])["prompt"]]
    return ", ".join(p for p in parts if p)[:1500]

def build(req, kind="film"):
    if not isinstance(req, dict):
        raise ProdError("body must be an object")
    st = _settings(req, kind)
    miss = []
    if kind == "short":
        parsed, secs = _short_parsed(req)
        st["action_seconds"] = secs
        text = parsed["scenes"][0]["beats"][0]["text"]
    else:
        text = req.get("script")
        if not isinstance(text, str) or not text.strip():
            raise ProdError("script is required (screenplay text)")
        if len(text) > 60000:
            raise ProdError("script is too long (max 60000 characters)")
        parsed = script.parse(text)
        miss = script.coverage(text, parsed)
        if len(parsed["scenes"]) > 150 or sum(len(s["beats"]) for s in parsed["scenes"]) > 800:
            raise ProdError("too many scenes or shots (max 150 scenes, 800 shots)")
    lang = req.get("language") if req.get("language") in ("ar", "en") else script.detect_language(text)
    ov = {str(c.get("name", "")).lower(): c for c in (req.get("characters") or []) if isinstance(c, dict)}
    chars, genders, alt = {}, {}, 0
    for n in parsed["characters"]:
        o = ov.get(n.lower(), {})
        g = o.get("gender") if o.get("gender") in ("male", "female") else voices.guess_gender(n, lang)
        if g is None:
            g, alt = ("male" if alt % 2 == 0 else "female"), alt + 1
        genders[n] = g
        chars[n] = dict(name=n, gender=g, role=str(o.get("role") or ("man" if g == "male" else "woman"))[:40], age=str(o.get("age") or "adult")[:20],
                        look=str(o.get("look") or "with a distinctive, easy-to-recognise appearance and consistent clothing")[:200],
                        palette=PALETTES[zlib.crc32(n.encode()) % len(PALETTES)], seed=zlib.crc32((n + str(st["seed"])).encode()) % 1000000, voice=o.get("voice"))
    pref = {n: c["voice"] for n, c in chars.items() if c["voice"]}
    if isinstance(req.get("narrator_voice"), str):
        pref["NARRATOR"] = req["narrator_voice"]
    vmap = voices.assign(list(chars), lang, genders, pref)
    warn, scenes, idx = set(parsed["warnings"]), [], 0
    for sc in parsed["scenes"]:
        shots = []
        for i, b in enumerate(sc["beats"], 1):
            idx += 1
            sp = b.get("speaker")
            present = ([sp] if sp in chars else []) + [n for n in chars if n != sp and n.lower() in b["text"].lower()]
            present = present[:3]
            voice = vmap.get(sp) if b["kind"] == "dialogue" else vmap["NARRATOR"]
            g = genders.get(sp, "male")
            shots.append(dict(id="%s-%d" % (sc["id"], i), kind=b["kind"], speaker=sp, emotion=b.get("emotion"), text=b["text"], visual=b.get("visual"),
                              prompt=_compile(st, sc, b, present, chars, warn), seed=chars[present[0]]["seed"] if present else (st["seed"] + idx * 7) % 1000000,
                              voice=voice, voice_alt=voices.alternatives(lang, g, voice), characters=present, state="pending", error=None, attempts=0,
                              duration=None, audio_duration=None, clip=None, engine_used=None))
        scenes.append(dict(id=sc["id"], heading=sc["heading"], location=sc["location"], time=sc["time"], shots=shots))
    if lang == "ar":
        warn.add("Arabic: voices use Arabic Neural voices; image prompts stay English-only, so add English (visual: ...) hints.")
    if miss:
        raise ProdError("fidelity check failed: lines missing from the plan: %s" % miss[:3])
    return dict(kind=kind, title=str(req.get("title") or "Untitled")[:100], state="planned", error=None, language=lang, settings=st, characters=chars, voices=vmap,
                scenes=scenes, warnings=sorted(warn), fidelity={"missing_lines": miss}, output=None)

def create(store, req, kind="film"):
    return store.create(build(req, kind))
