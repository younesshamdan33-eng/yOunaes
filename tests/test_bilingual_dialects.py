"""Unit tests for bilingual Arabic (MSA + regional dialects) and English prompt understanding."""
import pytest
from cinematic_engine.prompt_engineer import (
    detect_language,
    enrich_bilingual_prompt,
    parse_prompt_structure,
)

def test_language_detection_bilingual():
    # 1. Arabic MSA
    assert detect_language("فارس يمتطي جواده في الصحراء") == "ar"
    # 2. Arabic Egyptian
    assert detect_language("راجل بيتمشى في الشارع") == "ar"
    # 3. Arabic Levantine
    assert detect_language("زلمة عم يركض بالشارع") == "ar"
    # 4. Arabic Maghrebi
    assert detect_language("واحد كيجري فالزنقة") == "ar"
    # 5. Arabic Gulf
    assert detect_language("ريال يطالع البحر") == "ar"
    # 6. Arabic Sudanese
    assert detect_language("زول ماشي في الدرب") == "ar"
    # 7. English
    assert detect_language("A futuristic city at night") == "en"
    assert detect_language("A lone warrior walking across the dusty wasteland") == "en"

def test_bilingual_concept_enrichment():
    ar_res = enrich_bilingual_prompt("فارس يمتطي جواده في الصحراء عند الغروب")
    assert "knight" in ar_res
    assert "desert" in ar_res
    assert "sunset" in ar_res

    eg_res = enrich_bilingual_prompt("راجل بيتمشى في الشارع والمطر نازل")
    assert "man" in eg_res
    assert "walking" in eg_res
    assert "rain" in eg_res

def test_parse_prompt_structure_bilingual():
    p_ar = "راجل ومعاه ست في الصحراء"
    parsed_ar = parse_prompt_structure(p_ar)
    assert parsed_ar["language"] == "ar"
    assert "man" in parsed_ar["characters"]
    assert "woman" in parsed_ar["characters"]

    p_en = "A man walking through the rain"
    parsed_en = parse_prompt_structure(p_en)
    assert parsed_en["language"] == "en"
    assert "man" in parsed_en["characters"]
