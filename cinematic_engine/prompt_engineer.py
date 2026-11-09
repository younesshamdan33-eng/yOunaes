"""
Prompt engineering module for CINEMA AI — Wan 2.1 T2V 1.3B.
Supports the 5 canonical visual styles, multilingual prompt understanding
across 11 key languages (Arabic MSA & Dialects, English, French, Spanish, German,
Portuguese, Turkish, Chinese, Japanese, Korean), semantic concept extraction,
and negative prompt mapping.
"""
from __future__ import annotations
import re
from typing import Optional, Dict, Tuple, Any, List

# ==============================================================================
# The 5 Canonical Visual Styles
# ==============================================================================
FIVE_STYLES: Dict[str, Dict[str, str]] = {
    "cinematic_realistic": {
        "name": "Cinematic Realistic",
        "positive": (
            "cinematic live-action film, photorealistic environment, deliberate visual storytelling, "
            "natural physics, realistic motion, anamorphic 35mm film texture, balanced color grading"
        ),
        "negative": (
            "2d cartoon, anime, 3d cartoon, illustration, plastic skin, drawing, deformed anatomy, "
            "extra limbs, low quality, blurry, flicker, jitter, text, watermark, logo"
        ),
    },
    "realistic_human": {
        "name": "Realistic Human",
        "positive": (
            "photorealistic human subject, natural skin pores and micro-texture, anatomically plausible face "
            "and hands, subtle authentic facial expressions, natural eye blinking, realistic body mechanics, "
            "physically plausible lighting, live-action cinematography"
        ),
        "negative": (
            "cartoon, anime, 3d render, illustration, artificial waxy skin, distorted face, bad hands, "
            "extra fingers, deformed limbs, blurry, flicker, text, watermark"
        ),
    },
    "cartoon_3d": {
        "name": "3D Cartoon",
        "positive": (
            "high-end 3D animated feature film aesthetic, stylized appealing character design, "
            "expressive readable eyes and facial features, smooth volumetric forms, detailed stylized 3D environment, "
            "soft global illumination, polished material shaders, fluid character animation"
        ),
        "negative": (
            "photorealistic live action, real human skin pores, flat 2d illustration, anime, "
            "rough sketch, deformed shapes, muddy lighting, blurry, flicker, watermark, text"
        ),
    },
    "cartoon_2d": {
        "name": "2D Cartoon",
        "positive": (
            "traditional 2D animation, crisp clean line art, hand-drawn aesthetic, "
            "vibrant cel shading, expressive character poses, consistent silhouette design, "
            "hand-painted backgrounds, classic animated motion"
        ),
        "negative": (
            "photorealistic live action, 3d CGI render, realistic skin pores, volumetric 3D lighting, "
            "muddy strokes, inconsistent art style, blurry, flicker, watermark, text"
        ),
    },
    "anime": {
        "name": "Anime",
        "positive": (
            "Japanese anime aesthetic, clean refined line art, stylized expressive character eyes, "
            "delicate cel shading, painterly detailed anime background art, intentional anime color palette, "
            "dynamic dramatic framing, fluid anime motion"
        ),
        "negative": (
            "photorealistic live action, western 3d cartoon, realistic skin pores, waxy CGI, "
            "rough unpolished lines, blurry, deformed anatomy, flicker, watermark, text"
        ),
    },
}

STYLE_ALIASES: Dict[str, str] = {
    "cinematic": "cinematic_realistic",
    "cinematic_realistic": "cinematic_realistic",
    "realistic": "cinematic_realistic",
    "human": "realistic_human",
    "realistic_human": "realistic_human",
    "cartoon3d": "cartoon_3d",
    "3d_cartoon": "cartoon_3d",
    "cartoon_3d": "cartoon_3d",
    "3d": "cartoon_3d",
    "cartoon2d": "cartoon_2d",
    "2d_cartoon": "cartoon_2d",
    "cartoon_2d": "cartoon_2d",
    "2d": "cartoon_2d",
    "anime": "anime",
    "japanese_anime": "anime",
}

# Cinematographic Lexicons
SHOT_MAP: Dict[str, str] = {
    "wide": "wide shot, establishing environmental framing",
    "medium": "medium shot, waist-up framing",
    "close_up": "close-up shot, detailed facial features and expressions",
    "extreme_close_up": "extreme close-up, macro detail",
    "establishing": "establishing shot, wide environmental scale",
    "over_shoulder": "over-the-shoulder shot, intimate perspective",
}

CAMERA_MAP: Dict[str, str] = {
    "static": "static camera, locked-off tripod",
    "pan": "smooth panning camera movement",
    "tilt": "slow tilt camera movement",
    "dolly_in": "dolly in, pushing smoothly toward subject",
    "dolly_out": "dolly out, pulling away from subject",
    "tracking": "tracking shot, following subject smoothly",
    "orbit": "orbit camera movement, circling subject",
    "handheld": "subtle cinematic handheld camera movement",
}

LENS_MAP: Dict[str, str] = {
    "wide": "wide-angle lens, 24mm",
    "normal": "normal lens, 50mm",
    "telephoto": "telephoto lens, 85mm",
    "macro": "macro lens, extreme close focus",
}

LIGHT_MAP: Dict[str, str] = {
    "natural": "natural soft lighting, balanced exposure",
    "dramatic": "dramatic chiaroscuro lighting, strong tonal contrast",
    "studio": "studio lighting, soft key and fill lights",
    "night": "night lighting, atmospheric practical lights",
    "day": "bright daylight, natural shadows",
    "golden_hour": "golden hour lighting, warm sunlight, long soft shadows",
    "overcast": "soft diffuse overcast light, gentle shadows",
    "volumetric": "volumetric lighting, visible atmospheric light rays",
    "backlight": "backlit subject, rim lighting, subtle silhouette edge",
}

LOOK_MAP: Dict[str, str] = {
    "natural": "natural cinematic color science, balanced contrast",
    "dramatic": "high-contrast dramatic look, deep rich shadows",
    "warm": "warm golden tones, soft highlights",
    "cold": "cool blue tones, crisp highlights",
    "sci_fi": "sci-fi cinematic look, teal and orange highlights",
    "documentary": "documentary realism, muted colors, authentic textures",
    "epic": "epic cinematic scale, rich filmic tone mapping",
}

# ==============================================================================
# Multilingual Vocabulary & Entity Expansion
# ==============================================================================
MULTILINGUAL_TERMS = [
    # Arabic MSA & Dialects
    (r"(?:ال)?فارس", "knight on horseback"),
    (r"(?:ال)?(?:راجل|ريال|زلمة|رجل)", "a man with detailed facial features"),
    (r"(?:ال)?(?:ست|مرا|حرمة|مرأة|امرأة)", "a woman with natural expressive face"),
    (r"(?:ال)?(?:بنت|صبية|طفلة|فتاة)", "a young woman with natural expression"),
    (r"(?:ال)?(?:ولد|طّفل|عيّل|ياهل|درّي|طفل)", "a young child"),
    (r"(?:ال)?(?:قطة|بسة|مش|هرّة|سنور)", "a small agile cat"),
    (r"(?:ال)?كلب", "a loyal dog"),
    (r"(?:ال)?صحراء", "vast desert landscape with sand dunes"),
    (r"(?:ال)?غروب", "dramatic sunset golden horizon"),
    (r"(?:ال)?(?:مطر|شتا)", "heavy cinematic rain falling"),
    (r"(?:ال)?غابة", "dense lush forest with tall trees"),
    (r"(?:ال)?مدينة", "bustling city streets"),

    # French
    (r"\bchevalier\b", "knight on horseback"),
    (r"\bhublot\b|\bd[ée]sert\b", "vast desert landscape"),
    (r"\bcoucher de soleil\b", "dramatic sunset golden horizon"),
    (r"\bfor[êe]t\b", "dense lush forest"),
    (r"\bhomme\b", "a man with detailed facial features"),
    (r"\bfemme\b", "a woman with natural expressive face"),
    (r"\benfant\b", "a young child"),
    (r"\bpluie\b", "cinematic rain falling"),

    # Spanish
    (r"\bcaballero\b", "knight on horseback"),
    (r"\bdesierto\b", "vast desert landscape"),
    (r"\batardecer\b|\bpuesta de sol\b", "dramatic sunset golden horizon"),
    (r"\bbosque\b", "dense lush forest"),
    (r"\bhombre\b", "a man with detailed facial features"),
    (r"\bmujer\b", "a woman with natural expressive face"),
    (r"\bni[ñn]o\b|\bni[ñn]a\b", "a young child"),
    (r"\blluvia\b", "cinematic rain falling"),

    # German
    (r"\britter\b", "knight on horseback"),
    (r"\bw[üu]ste\b", "vast desert landscape"),
    (r"\bsonnenuntergang\b", "dramatic sunset golden horizon"),
    (r"\bwald\b", "dense lush forest"),
    (r"\bmann\b", "a man with detailed facial features"),
    (r"\bfrau\b", "a woman with natural expressive face"),
    (r"\bkind\b", "a young child"),
    (r"\bregen\b", "cinematic rain falling"),

    # Portuguese
    (r"\bcavaleiro\b", "knight on horseback"),
    (r"\bdeserto\b", "vast desert landscape"),
    (r"\bp[ôo]r do sol\b", "dramatic sunset golden horizon"),
    (r"\bfloresta\b", "dense lush forest"),
    (r"\bhomem\b", "a man with detailed facial features"),
    (r"\bmulher\b", "a woman with natural expressive face"),
    (r"\bcrian[çc]a\b", "a young child"),

    # Turkish
    (r"\bş[oö]valye\b|\bsovalye\b", "knight on horseback"),
    (r"\bç[oö]l\b|\bcol\b", "vast desert landscape"),
    (r"\bg[üu]n bat[ıi]m[ıi]\b", "dramatic sunset golden horizon"),
    (r"\borman\b", "dense lush forest"),
    (r"\badam\b", "a man with detailed facial features"),
    (r"\bkad[ıi]n\b", "a woman with natural expressive face"),
    (r"\b[çc]ocuk\b", "a young child"),

    # Chinese
    (r"骑士|武士", "noble warrior or knight"),
    (r"沙漠", "vast desert landscape with sand dunes"),
    (r"日落|夕阳", "dramatic sunset golden horizon"),
    (r"森林", "dense lush forest"),
    (r"男人|男子", "a man with detailed facial features"),
    (r"女人|女子", "a woman with natural expressive face"),
    (r"小孩|儿童", "a young child"),
    (r"下雨|雨中", "cinematic rain falling"),

    # Japanese
    (r"騎士|侍", "noble knight or samurai"),
    (r"砂漠", "vast desert landscape with sand dunes"),
    (r"夕日|夕焼け", "dramatic sunset golden horizon"),
    (r"森", "dense lush forest"),
    (r"男性|男", "a man with detailed facial features"),
    (r"女性|女", "a woman with natural expressive face"),
    (r"子供", "a young child"),
    (r"雨", "cinematic rain falling"),

    # Korean
    (r"기사|무사", "noble knight or warrior"),
    (r"사막", "vast desert landscape with sand dunes"),
    (r"일몰|석양", "dramatic sunset golden horizon"),
    (r"숲", "dense lush forest"),
    (r"남자", "a man with detailed facial features"),
    (r"여자", "a woman with natural expressive face"),
    (r"아이|어린이", "a young child"),
    (r"비", "cinematic rain falling"),
]

def detect_language(text: str) -> str:
    """
    Detects language across 11 supported languages and scripts:
    Arabic ('ar'), Chinese ('zh'), Japanese ('ja'), Korean ('ko'),
    Turkish ('tr'), German ('de'), French ('fr'), Spanish ('es'),
    Portuguese ('pt'), and English ('en').
    """
    if not isinstance(text, str) or not text.strip():
        return "en"

    # Script-based counts
    arabic = sum(1 for ch in text if "\u0600" <= ch <= "\u06FF")
    korean = sum(1 for ch in text if "\uAC00" <= ch <= "\uD7AF" or "\u1100" <= ch <= "\u11FF")
    japanese = sum(1 for ch in text if "\u3040" <= ch <= "\u309F" or "\u30A0" <= ch <= "\u30FF")
    cjk = sum(1 for ch in text if "\u4E00" <= ch <= "\u9FFF")

    if arabic > 0 and arabic >= max(korean, japanese, cjk):
        return "ar"
    if korean > 0:
        return "ko"
    if japanese > 0:
        return "ja"
    if cjk > 0:
        return "zh"

    # Latin-script language heuristics (using multi-word or distinctive stopword patterns)
    low = f" {text.lower()} "
    if any(k in low for k in [" the ", " and ", " with ", " in ", " at ", " of ", " is "]):
        return "en"
    if any(k in low for k in [" der ", " die ", " das ", " und ", " ein ", " eine "]):
        return "de"
    if any(k in low for k in [" dans la ", " dans le ", " une femme ", " un homme ", " avec "]):
        return "fr"
    if any(k in low for k in [" en el ", " en la ", " un hombre ", " una mujer ", " con "]):
        return "es"
    if any(k in low for k in [" no ", " na ", " um homem ", " uma mulher ", " com "]):
        return "pt"
    if any(k in low for k in [" bir ", " için ", " gibi ", " ve "]):
        return "tr"

    return "en"

def enrich_bilingual_prompt(text: str) -> str:
    """
    Enriches multilingual prompts (Arabic, CJK, European languages) by extracting
    visual concepts and mapping them to cinematic English descriptors while preserving original input.
    """
    lang = detect_language(text)
    if lang == "en":
        return text

    found_anchors = []
    for pattern, en_desc in MULTILINGUAL_TERMS:
        if re.search(pattern, text, re.IGNORECASE):
            found_anchors.append(en_desc)

    if found_anchors:
        anchors_str = ", ".join(dict.fromkeys(found_anchors))
        return f"{text.strip()} (Visual elements: {anchors_str})"
    return text

def resolve_style(style_name: Optional[str]) -> Tuple[str, Dict[str, str]]:
    """Resolves any style name or alias into the canonical style record."""
    key = str(style_name or "").strip().lower().replace("-", "_").replace(" ", "_")
    canonical = STYLE_ALIASES.get(key, "cinematic_realistic")
    return canonical, FIVE_STYLES[canonical]

def parse_prompt_structure(prompt: str) -> Dict[str, Any]:
    """
    Parses a multilingual prompt into structured components:
    subject, environment, mood, and detected language.
    """
    lang = detect_language(prompt)
    res = {
        "raw": prompt,
        "language": lang,
        "style_detected": "cinematic_realistic",
        "characters": [],
        "setting": "",
        "action": "",
    }

    low = prompt.lower()
    for s_alias, s_canon in STYLE_ALIASES.items():
        if s_alias in low:
            res["style_detected"] = s_canon
            break

    # Character heuristics across multilingual vocabulary
    if any(k in prompt for k in ["راجل", "ريال", "زلمة", "رجل", "man", "homme", "hombre", "mann", "homem", "adam", "男人", "男性", "남자"]):
        res["characters"].append("man")
    if any(k in prompt for k in ["مرا", "ست", "حرمة", "امرأة", "فتاة", "woman", "femme", "mujer", "frau", "mulher", "kadın", "女人", "女性", "여자"]):
        res["characters"].append("woman")
    if any(k in prompt for k in ["ولد", "طفل", "طفلة", "صغيرة", "عيّل", "ياهل", "درّي", "child", "enfant", "niño", "kind", "criança", "çocuk", "小孩", "子供", "아이"]):
        res["characters"].append("child")

    return res

def build_cinematic_prompt(
    user_prompt: str,
    cfg: Any = None,
    style_override: Optional[str] = None,
    return_negative: bool = False
) -> str | Tuple[str, str]:
    """
    Constructs a comprehensive positive and optional negative prompt for Wan 2.1 T2V 1.3B.
    If return_negative=True, returns (positive_prompt, negative_prompt).
    Otherwise returns positive_prompt (str) for 100% backward compatibility.
    """
    style_key = style_override or getattr(cfg, "look", "cinematic_realistic")
    canonical_style, style_info = resolve_style(style_key)

    shot_type = getattr(cfg, "shot_type", "medium")
    camera_motion = getattr(cfg, "camera_motion", "static")
    lens = getattr(cfg, "lens", "normal")
    lighting = getattr(cfg, "lighting", "natural")
    dof = getattr(cfg, "depth_of_field", "shallow")

    enriched_core = enrich_bilingual_prompt(user_prompt).strip().rstrip(".,")

    parts = [enriched_core]
    parts.append(SHOT_MAP.get(shot_type, SHOT_MAP["medium"]))
    parts.append(CAMERA_MAP.get(camera_motion, CAMERA_MAP["static"]))
    parts.append(LENS_MAP.get(lens, LENS_MAP["normal"]))
    parts.append(LIGHT_MAP.get(lighting, LIGHT_MAP["natural"]))
    parts.append(style_info["positive"])

    if dof == "shallow":
        parts.append("shallow depth of field, gentle background separation")
    else:
        parts.append("deep focus, clear depth across frame")

    positive_prompt = ", ".join(p for p in parts if p)
    negative_prompt = style_info["negative"]

    if return_negative:
        return positive_prompt, negative_prompt
    return positive_prompt

def build_cinematic_prompts(
    user_prompt: str,
    cfg: Any = None,
    style_override: Optional[str] = None
) -> Tuple[str, str]:
    """Helper that explicitly returns (positive_prompt, negative_prompt)."""
    return build_cinematic_prompt(user_prompt, cfg, style_override, return_negative=True)
