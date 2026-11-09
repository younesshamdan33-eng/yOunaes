"""
Prompt engineering and cinematic intelligence module for CINEMA AI — Wan 2.1 T2V 1.3B.
Supports the 5 canonical visual capabilities, deep bilingual Arabic (MSA, Moroccan Darija,
Egyptian, Levantine, Gulf/Saudi/Emirati, Iraqi, Sudanese) and English semantic understanding,
character/action/environment/emotion extraction, and negative prompt mapping.
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
# Comprehensive Arabic Dialect & Multilingual Vocabulary Expansion
# ==============================================================================
DIALECT_DICTIONARY = [
    # 1. Characters across MSA & Regional Dialects (Egyptian, Levantine, Maghrebi, Gulf, Iraqi, Sudanese)
    (r"(?:ال)?(?:راجل|ريال|زلمة|رجل|راقل|زول)", "a man with detailed facial features and expressive eyes"),
    (r"(?:ال)?(?:ست|مرا|حرمة|مرأة|امرأة|ولية|نسوان)", "a woman with natural expressive face"),
    (r"(?:ال)?(?:بنت|صبية|طفلة|فتاة|بنوتة)", "a young woman with natural authentic expression"),
    (r"(?:ال)?(?:ولد|طّفل|عيّل|ياهل|درّي|شافع|صبي|طفل)", "a young child"),
    (r"(?:ال)?(?:عجوز|شيبة|ختيار|مسن|شايب)", "an elderly person with weathered features and wisdom"),
    (r"(?:ال)?(?:فارس|خيّال)", "a noble knight on horseback"),
    (r"(?:ال)?(?:قطة|بسة|مش|هرّة|سنور|قطوس)", "a small agile cat"),
    (r"(?:ال)?(?:كلب|جرو)", "a loyal dog"),

    # 2. Environments & Locations
    (r"(?:ال)?صحراء", "vast desert landscape with sweeping golden sand dunes"),
    (r"(?:ال)?غروب", "dramatic sunset with warm golden hour horizon"),
    (r"(?:ال)?شروق", "atmospheric sunrise morning soft light"),
    (r"(?:ال)?(?:بحر|محيط)", "majestic ocean with rolling waves"),
    (r"(?:ال)?(?:مطر|شتا|نوء)", "heavy cinematic rain falling through the air"),
    (r"(?:ال)?ليل", "atmospheric dark night illuminated by subtle ambient sources"),
    (r"(?:ال)?نهار", "bright clear daylight with crisp natural shadows"),
    (r"(?:ال)?غابة", "dense lush ancient forest with tall majestic trees"),
    (r"(?:ال)?(?:شارع|زنقة|درب|حارة|سكة)", "atmospheric city street with rich urban textures"),
    (r"(?:ال)?مدينة", "bustling metropolitan city skyline"),

    # 3. Actions & Movement (MSA & Dialects)
    (r"(?:بيتمشى|كيتمشى|قاعد يمشي|عم يمشي|يمشي|يتمشى)", "walking steadily through the scene"),
    (r"(?:بيجري|كيركض|عم يركض|يركض|يجري|يطرد)", "running dynamically with energetic motion"),
    (r"(?:بيضحك|كيضحك|عم يبتسم|يبتسم|يضحك)", "smiling warmly with subtle facial emotion"),
    (r"(?:بيشوف|كيشوف|عم يتطلع|يطالع|يبحلق|ينظر|يشوف)", "looking intently with purposeful gaze"),
    (r"(?:بيسوق|كيصوڭ|عم يسوق|يسوق|يقود)", "driving smoothly across the landscape"),
    (r"(?:ال)?سيف", "gleaming steel sword held with authority"),
    (r"(?:ال)?معركة", "epic dynamic cinematic encounter"),

    # 4. English & International Key terms
    (r"\bknight\b", "noble knight on horseback"),
    (r"\bdesert\b", "vast desert landscape with sand dunes"),
    (r"\bsunset\b", "dramatic sunset golden horizon"),
    (r"\bforest\b", "dense lush forest with tall trees"),
    (r"\brain\b", "heavy cinematic rain falling"),
    (r"\bnight\b", "atmospheric night"),
    (r"\bwalking\b", "walking steadily"),
    (r"\brunning\b", "running dynamically"),
]

def detect_language(text: str) -> str:
    """
    Detects whether prompt is Arabic ('ar') or English ('en').
    Recognizes Arabic script across all dialects and Modern Standard Arabic.
    """
    if not isinstance(text, str) or not text.strip():
        return "en"
    arabic = sum(1 for ch in text if "\u0600" <= ch <= "\u06FF")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return "ar" if arabic > 0 and arabic >= latin else "en"

def enrich_bilingual_prompt(text: str) -> str:
    """
    Enriches Arabic prompts (MSA & regional dialects: Moroccan, Egyptian, Levantine, Gulf, etc.)
    by extracting visual concepts and mapping them to cinematic English descriptors while preserving original input.
    """
    lang = detect_language(text)
    if lang == "en":
        return text

    found_anchors = []
    for pattern, en_desc in DIALECT_DICTIONARY:
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
    Parses an Arabic or English prompt into structured components:
    characters, action, environment, lighting, and detected style.
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

    # Character heuristics across dialects and English
    if any(k in prompt for k in ["راجل", "ريال", "زلمة", "رجل", "زول", "man", "guy"]):
        res["characters"].append("man")
    if any(k in prompt for k in ["مرا", "ست", "حرمة", "امرأة", "فتاة", "woman", "girl"]):
        res["characters"].append("woman")
    if any(k in prompt for k in ["ولد", "طفل", "طفلة", "صغيرة", "عيّل", "ياهل", "درّي", "شافع", "child", "kid"]):
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
