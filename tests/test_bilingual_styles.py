"""Unit tests for bilingual Arabic/English parsing and the 5 canonical styles."""
import pytest
from cinematic_engine.prompt_engineer import (
    FIVE_STYLES,
    STYLE_ALIASES,
    resolve_style,
    detect_language,
    enrich_bilingual_prompt,
    parse_prompt_structure,
    build_cinematic_prompt,
)

def test_five_styles_completeness():
    expected = {"cinematic_realistic", "realistic_human", "cartoon_3d", "cartoon_2d", "anime"}
    assert set(FIVE_STYLES.keys()) == expected
    for style_key, data in FIVE_STYLES.items():
        assert "positive" in data and len(data["positive"]) > 10
        assert "negative" in data and len(data["negative"]) > 10

def test_style_resolution_and_aliases():
    assert resolve_style("cinematic")[0] == "cinematic_realistic"
    assert resolve_style("realistic_human")[0] == "realistic_human"
    assert resolve_style("3d_cartoon")[0] == "cartoon_3d"
    assert resolve_style("cartoon2d")[0] == "cartoon_2d"
    assert resolve_style("anime")[0] == "anime"
    # fallback
    assert resolve_style("unknown_style")[0] == "cinematic_realistic"

def test_bilingual_detection():
    assert detect_language("A lone knight riding across a desert at sunset") == "en"
    assert detect_language("فارس يمتطي جواده في الصحراء عند الغروب") == "ar"
    assert detect_language("") == "en"

def test_arabic_prompt_enrichment():
    ar_prompt = "فارس يمتطي جواده في الصحراء عند الغروب"
    enriched = enrich_bilingual_prompt(ar_prompt)
    assert "knight" in enriched
    assert "desert" in enriched
    assert "sunset" in enriched
    assert "فارس" in enriched  # preserves original text

def test_build_cinematic_prompt():
    prompt = "A warrior walking"
    pos_str = build_cinematic_prompt(prompt, style_override="anime")
    assert isinstance(pos_str, str)
    assert "Japanese anime aesthetic" in pos_str

    pos, neg = build_cinematic_prompt(prompt, style_override="anime", return_negative=True)
    assert "Japanese anime aesthetic" in pos
    assert "photorealistic live action" in neg
    assert "A warrior walking" in pos

def test_parse_prompt_structure():
    p = "رجل يمشي في الغابة بنمط anime"
    parsed = parse_prompt_structure(p)
    assert parsed["language"] == "ar"
    assert "man" in parsed["characters"]
    assert parsed["style_detected"] == "anime"
