"""Character Intelligence: extracts characters from the idea and builds
persistent visual identity files (deterministic descriptors) so every
generation prompt describes the same-looking character. This is
best-effort continuity by prompt engineering, honestly not guaranteed
by the underlying model."""
import hashlib

MAX_CHARS = 3

# (kind, [en keywords], [ar keywords], en base, ar base, gender)
_ARCHETYPES = [
    ("man", ["man", "guy", "father", "detective", "soldier"],
     ["رجل", "أب", "مخبر", "جندي", "شاب"],
     "a man in his thirties with short dark hair and a weathered jacket",
     "رجل في الثلاثينات بشعر داكن قصير وسترة مهترئة", "male"),
    ("woman", ["woman", "girl", "mother", "lady"],
     ["امرأة", "فتاة", "بنت", "أم", "سيدة"],
     "a woman in her twenties with long black hair and a warm coat",
     "امرأة في العشرينات بشعر أسود طويل ومعطف دافئ", "female"),
    ("child", ["child", "kid", "boy", "son", "daughter"],
     ["طفل", "ولد", "ابن", "بنت صغيرة"],
     "a curious eight-year-old child with messy hair and a backpack",
     "طفل في الثامنة من عمره بشعر مضطرب وحقيبة ظهر", "male"),
    ("old_man", ["old man", "grandfather", "elder"],
     ["رجل كبير", "جد", "شيخ", "عجوز"],
     "an elderly man with white hair, deep wrinkles, and a cane",
     "رجل مسن بشعر أبيض وتجاعيد عميقة وعصا مشي", "male"),
    ("cat", ["cat", "kitten"], ["قطة", "قط ", "قطه"],
     "a small orange tabby cat with bright green eyes and a torn ear",
     "قطة برتقالية صغيرة بعيون خضراء لامعة وأذن ممزقة", "male"),
    ("dog", ["dog", "puppy", "hound"], ["كلب", "جرو"],
     "a loyal brown dog with floppy ears and a red collar",
     "كلب بني مخلص بأذنين متدليتين وطوق أحمر", "male"),
    ("robot", ["robot", "android", "machine"], ["روبوت", "آلة"],
     "a sleek humanoid robot with a brushed-steel body and one blue glowing eye",
     "روبوت بهيكل فولاذي مصقول وعين زرقاء واحدة متوهجة", "male"),
    ("ghost", ["ghost", "spirit", "phantom"], ["شبح", "روح", "طيف"],
     "a pale translucent figure in a long tattered gown",
     "شبح شاحب شبه شفاف يرتدي ثوباً طويلاً ممزقاً", "female"),
]

_HAIR = ("black", "dark brown", "chestnut", "salt-and-pepper")
_CLOTH = ("a grey hoodie", "a leather jacket", "a long dark coat", "a plain white shirt")
_GENDER_VOICES = {
    "ar": {"male": "ar-SA-HamedNeural", "female": "ar-SA-ZariyahNeural"},
    "en": {"male": "en-US-GuyNeural", "female": "en-US-JennyNeural"},
}


def _stable_pick(seed, pool):
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    return pool[h % len(pool)]


def _scan(text, language):
    t = (text or "").lower()
    found = []
    for kind, en_kw, ar_kw, en_base, ar_base, gender in _ARCHETYPES:
        kws = en_kw + ar_kw
        if any(k in t for k in kws):
            base = en_base if language == "en" else ar_base
            found.append({"kind": kind, "base": base, "gender": gender})
        if len(found) >= MAX_CHARS:
            break
    return found


def build(st, language, spec=None):
    spec = spec or {}
    idea_text = st.get("logline", "") + " " + " ".join(sc["description"] for sc in st["scenes"])
    found = _scan(idea_text, language)
    chars = []
    user_chars = spec.get("characters") if isinstance(spec.get("characters"), list) else []
    if user_chars:
        for c in user_chars[:MAX_CHARS]:
            if isinstance(c, dict) and isinstance(c.get("name"), str) and c["name"].strip():
                desc = (c.get("description") or "").strip() or c["name"].strip()
                g = c.get("gender", "male")
                chars.append({"kind": "custom", "name": c["name"].strip()[:60],
                              "visual": desc[:200], "gender": g,
                              "voice": _GENDER_VOICES.get(language, _GENDER_VOICES["en"])
                                        .get(g, _GENDER_VOICES["en"]["male"])})
    if not chars and not found:
        base = ("the protagonist, an ordinary person with a determined face"
                if language == "en" else "البطل، شخص عادي بملامح عازمة")
        found = [{"kind": "protagonist", "base": base, "gender": "male"}]
    for fc in found:
        seed = fc["kind"] + "|" + st.get("title", "")
        if fc["kind"] in ("cat", "dog", "robot", "ghost"):
            visual = fc["base"]
        else:
            visual = fc["base"] + ", " + _stable_pick(seed + "h", _HAIR) + \
                     " hair alt tone, wearing " + _stable_pick(seed + "c", _CLOTH)
        chars.append({"kind": fc["kind"], "name": fc["kind"].replace("_", " ").title(),
                      "visual": visual[:200], "gender": fc["gender"],
                      "voice": _GENDER_VOICES.get(language, _GENDER_VOICES["en"])
                                .get(fc["gender"], _GENDER_VOICES["en"]["male"])})
    return chars[:MAX_CHARS]



# Backward-compatible character casting API.
def cast(st, language=None):
    from . import lang

    source = " ".join([
        str((st or {}).get("title", "")),
        str((st or {}).get("logline", "")),
        str((st or {}).get("synopsis", "")),
        " ".join(
            str(x.get("description", ""))
            for x in (st or {}).get("scenes", [])
            if isinstance(x, dict)
        ),
    ])
    language = language or lang.detect_language(source)
    characters = build(st or {}, language)

    for ch in characters:
        if not ch.get("role"):
            ch["role"] = ch.get("kind") or "character"

    return characters
