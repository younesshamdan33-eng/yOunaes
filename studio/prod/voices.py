"""Voice Intelligence: free Microsoft Neural voices through edge-tts (online service, not open source, not self-hostable)."""
import asyncio

CATALOG = {
    "en": {"male": ["en-US-GuyNeural", "en-GB-RyanNeural", "en-US-ChristopherNeural", "en-AU-WilliamNeural"],
           "female": ["en-US-JennyNeural", "en-GB-SoniaNeural", "en-US-AriaNeural", "en-AU-NatashaNeural"]},
    "ar": {"male": ["ar-SA-HamedNeural", "ar-EG-ShakirNeural", "ar-MA-JamalNeural", "ar-AE-HamdanNeural"],
           "female": ["ar-SA-ZariyahNeural", "ar-EG-SalmaNeural", "ar-MA-MounaNeural", "ar-AE-FatimaNeural"]},
}
FEMALE = {"mara", "anna", "ann", "sara", "sarah", "maria", "emma", "olivia", "sophia", "lily", "lina", "nora", "mia", "eva", "rose", "jane", "mary", "laura", "julia", "lucy", "emily", "alice",
          "مريم", "فاطمة", "سارة", "ليلى", "نور", "هدى", "سلمى", "أمل", "رنا", "منى", "ريم", "دعاء", "خديجة", "عائشة", "زينب", "سمية", "هند"}
MALE = {"tom", "john", "james", "david", "ali", "omar", "karim", "sam", "mark", "paul", "peter", "adam", "ryan", "rami", "طارق", "أحمد", "محمد", "عمر", "علي", "يوسف", "كريم", "رامي", "خالد", "حسن", "إبراهيم"}
PROSODY = {"angry": ("+8%", "-2Hz", "+15%"), "sad": ("-15%", "-4Hz", "-10%"), "happy": ("+8%", "+4Hz", "+5%"), "excited": ("+15%", "+6Hz", "+10%"),
           "worried": ("+0%", "+2Hz", "-5%"), "afraid": ("+5%", "+3Hz", "-5%"), "whisper": ("-10%", "-2Hz", "-40%"), "calm": ("-8%", "+0Hz", "+0%"),
           "غاضب": ("+8%", "-2Hz", "+15%"), "حزين": ("-15%", "-4Hz", "-10%"), "سعيد": ("+8%", "+4Hz", "+5%"), "خائف": ("+5%", "+3Hz", "-5%"), "خائفة": ("+5%", "+3Hz", "-5%"), "هادئ": ("-8%", "+0Hz", "+0%")}

def guess_gender(name, lang):
    n = (name or "").strip().lower()
    if n in FEMALE:
        return "female"
    if n in MALE:
        return "male"
    return "female" if lang == "ar" and n.endswith("ة") else None

def prosody(emotion):
    r, p, v = PROSODY.get((emotion or "").strip().lower(), ("+0%", "+0Hz", "+0%"))
    return dict(rate=r, pitch=p, volume=v)

def alternatives(lang, gender, voice):
    return [v for v in CATALOG.get(lang, CATALOG["en"])[gender] if v != voice][:2]

def assign(names, lang, genders=None, preferred=None):
    cat, used, out, preferred = CATALOG.get(lang, CATALOG["en"]), set(), {}, preferred or {}
    def pick(g):
        for v in cat[g]:
            if v not in used:
                used.add(v); return v
        return cat[g][len(used) % len(cat[g])]
    out["NARRATOR"] = preferred.get("NARRATOR") or pick("male")
    for n in names:
        g = (genders or {}).get(n) or "male"
        out[n] = preferred.get(n) or pick(g)
    return out

def synth(text, voice, out, emotion=None, timeout=60, attempts=2):
    import edge_tts
    pr = prosody(emotion)
    async def go():
        await asyncio.wait_for(edge_tts.Communicate(text, voice, rate=pr["rate"], pitch=pr["pitch"], volume=pr["volume"]).save(str(out)), timeout)
    last = None
    for _ in range(attempts):
        try:
            asyncio.run(go())
            if out.exists() and out.stat().st_size > 0:
                return
            last = RuntimeError("empty audio")
        except Exception as e:
            last = e
    raise RuntimeError("speech synthesis failed (%s)" % (str(last) or last.__class__.__name__))
