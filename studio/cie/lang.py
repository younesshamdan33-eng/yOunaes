"""Language detection and bilingual (AR/EN) keyword understanding."""
GENRE_KEYWORDS = {
    "action": ["action", "fight", "chase", "explosion", "battle", "war", "hero",
               "اكشن", "قتال", "مطاردة", "انفجار", "معركة", "حرب", "بطل"],
    "drama": ["drama", "emotional", "family", "loss", "father", "mother", "child",
              "دراما", "عاطفي", "عائلة", "فقدان", "أب", "أم", "طفل", "حزين", "ابن", "بنت"],
    "comedy": ["comedy", "funny", "laugh", "humor", "silly",
               "كوميدي", "مضحك", "ضحك", "هزلي", "طريف"],
    "documentary": ["documentary", "history", "nature", "city", "ocean",
                    "وثائقي", "تاريخ", "طبيعة", "مدينة", "محيط", "صحراء"],
    "horror": ["horror", "scary", "ghost", "nightmare", "haunted", "monster",
               "رعب", "خوف", "شبح", "كابوس", "مسكون", "وحش", "مرعب", "ليل"],
    "scifi": ["sci-fi", "science fiction", "space", "robot", "future", "alien",
              "خيال علمي", "فضاء", "روبوت", "مستقبل", "كائن فضائي", "تقنية"],
    "fantasy": ["fantasy", "magic", "dragon", "kingdom", "wizard", "sword",
                "خيال", "سحر", "تنين", "مملكة", "ساحر", "سيف"],
    "romance": ["romance", "romantic", "love", "wedding", "heart",
                "رومانسي", "حب", "عشق", "زفاف", "قلب"],
    "thriller": ["thriller", "mystery", "suspense", "crime", "detective", "murder",
                 "إثارة", "تشويق", "غموض", "جريمة", "مخبر", "قتل"],
}

TONE_KEYWORDS = {
    "dark": ["dark", "gloomy", "noir", "مظلم", "قاتم", "كئيب", "نوار"],
    "bright": ["bright", "cheerful", "colorful", "مشرق", "مبهج", "ملون", "بهيج"],
    "warm": ["warm", "cozy", "golden", "دافئ", "حنون", "ذهبي"],
    "cold": ["cold", "frozen", "winter", "ice", "بارد", "متجمد", "شتاء", "جليد"],
    "dreamy": ["dreamy", "surreal", "magical", "حالم", "سريالي", "خيالي", "منوم"],
    "gritty": ["gritty", "raw", "street", "واقعي", "قاس", "شارع"],
    "epic": ["epic", "grand", "legendary", "ملحمي", "عظيم", "ضخم", "أسطوري"],
    "intimate": ["intimate", "personal", "quiet", "حميمي", "شخصي", "هادئ"],
}


def detect_language(text):
    if not isinstance(text, str) or not text.strip():
        return "en"
    arabic = sum(1 for ch in text if "\u0600" <= ch <= "\u06FF")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return "ar" if arabic >= latin else "en"


def _match(text, table):
    t = (text or "").lower()
    best, hits = None, 0
    for key, words in table.items():
        n = sum(1 for w in words if w in t)
        if n > hits:
            best, hits = key, n
    return best


def detect_genre(text):
    return _match(text, GENRE_KEYWORDS) or "drama"


def detect_tone(text):
    return _match(text, TONE_KEYWORDS) or "natural"



# Backward-compatible public API.
def detect(text):
    return detect_language(text)


def is_rtl(language):
    return str(language or "").lower().split("-")[0] in {
        "ar", "he", "fa", "ur"
    }
