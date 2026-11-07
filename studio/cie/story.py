"""Story Intelligence: idea -> title, logline, synopsis, scene beats with narration.
Universal dramatic arc (setup, spark, rising, climax, resolution) parameterized
by genre flavor, scaled to the target duration, in Arabic or English."""
GENRES = ("action", "drama", "comedy", "documentary", "horror", "scifi", "fantasy", "romance", "thriller")

_EN = {
    "logline": "{idea}.",
    "synopsis": "A {genre} story told in {n} scenes with a {tone} visual tone: {idea}.",
    "beats": [
        ("setup",      "The world of the story begins: {idea}. Everything seems ordinary."),
        ("spark",      "Something changes: an unexpected event breaks the daily routine."),
        ("rising",     "Tension builds; the situation grows heavier and more intense."),
        ("climax",     "The decisive moment arrives; everything comes to a head."),
        ("resolution", "Aftermath; the world settles into a new shape."),
    ],
    "genre_flavor": {
        "action": "high-stakes and kinetic", "drama": "emotional and human",
        "comedy": "playful and absurd", "documentary": "observational and factual",
        "horror": "dread-soaked and tense", "scifi": "speculative and technological",
        "fantasy": "wondrous and mythical", "romance": "tender and heartfelt",
        "thriller": "taut and suspenseful",
    },
}

_AR = {
    "logline": "{idea}.",
    "synopsis": "قصة {genre_ar} تُروى في {n} مشاهد بأسلوب {tone_ar}: {idea}.",
    "beats": [
        ("setup",      "تبدأ الحكاية: {idea}. يبدو كل شيء عادياً في مكان عادي."),
        ("spark",      "يتغير شيء ما: حدث غير متوقع يكسر الروتين المعتاد."),
        ("rising",     "يتصاعد التوتر؛ يثقل الموقف ويزداد حدّة."),
        ("climax",     "تحين اللحظة الحاسمة؛ تبلغ الأحداث ذروتها."),
        ("resolution", "بعد الأحداث؛ يستقر العالم على وضع جديد."),
    ],
    "genre_flavor": {
        "action": "مشوق ومليء بالحركة", "drama": "عاطفي وإنساني",
        "comedy": "مرح وغريب", "documentary": "رصدي وواقعي",
        "horror": "مخيف ومتوتر", "scifi": "تخيلي وتقني",
        "fantasy": "عجيب وأسطوري", "romance": "حنون ووجداني",
        "thriller": "مشوق ومحكم",
    },
}

_GENRE_AR = {"action": "أكشن", "drama": "دراما", "comedy": "كوميديا", "documentary": "وثائقية",
             "horror": "رعب", "scifi": "خيال علمي", "fantasy": "خيال", "romance": "رومانسية", "thriller": "إثارة"}
_TONE_AR = {"natural": "طبيعي", "dark": "مظلم", "bright": "مشرق", "warm": "دافئ", "cold": "بارد",
            "dreamy": "حالم", "gritty": "واقعي قاس", "epic": "ملحمي", "intimate": "حميمي"}

_BEAT_AR = {"setup": "البداية", "spark": "الشرارة", "rising": "التصعيد",
            "climax": "الذروة", "resolution": "الحل"}
_BEAT_EN = {"setup": "Setup", "spark": "Spark", "rising": "Rising Action",
            "climax": "Climax", "resolution": "Resolution"}


def _title_from(idea, language):
    words = idea.strip().split()
    t = " ".join(words[:7])
    return t.capitalize() if language == "en" else t


def _scene_count(target):
    return max(3, min(10, target // 8))


def _pick_beats(n):
    """Map n scenes onto the 5-beat arc, preserving setup/climax/resolution."""
    base = _EN["beats"]
    if n <= 3:
        return [base[0], base[3], base[4]]
    if n == 4:
        return [base[0], base[1], base[3], base[4]]
    out = list(base)
    while len(out) < n:
        out.insert(2, base[2])
    return out[:n]


def build(idea, genre, tone, target_seconds, language):
    T = _AR if language == "ar" else _EN
    idea_clean = idea.strip().rstrip(".")
    n = _scene_count(target_seconds)
    flavor = T["genre_flavor"].get(genre, "")
    synopsis = T["synopsis"].format(
        genre=genre, genre_ar=_GENRE_AR.get(genre, genre),
        tone=tone, tone_ar=_TONE_AR.get(tone, tone),
        idea=idea_clean, n=n)
    beats = _pick_beats(n)
    names = _BEAT_AR if language == "ar" else _BEAT_EN
    scenes = []
    for i, (name, tpl) in enumerate(beats, 1):
        text = tpl.format(idea=idea_clean)
        if flavor:
            text = text + (" (%s)" % flavor if language == "en" else " — %s" % flavor)
        scenes.append({"id": "s%d" % i, "beat": name,
                       "title": names.get(name, name),
                       "description": text, "narration": text})
    return {
        "title": _title_from(idea_clean, language),
        "logline": T["logline"].format(idea=idea_clean),
        "synopsis": synopsis,
        "scene_count": n,
        "scenes": scenes,
    }



# Backward-compatible story planner.
def plan(idea, target_seconds=30, language=None):
    from . import lang

    text = str(idea or "")
    language = language or lang.detect_language(text)
    genre = lang.detect_genre(text)
    tone = lang.detect_tone(text)

    result = build(
        text, genre, tone,
        target_seconds, language
    )
    result["genre"] = genre
    result["tone"] = tone

    for scene in result.get("scenes", []):
        scene.setdefault("text", scene.get("description", ""))
    return result
