"""In-depth tests for bilingual Arabic dialects (Moroccan, Egyptian, Levantine, Gulf, Iraqi, Sudanese, MSA) and English."""
import pytest
from cinematic_engine.prompt_engineer import (
    detect_language,
    enrich_bilingual_prompt,
    parse_prompt_structure,
    build_cinematic_prompt,
)

def test_dialect_detection():
    # MSA
    assert detect_language("فارس يمتطي جواده في الصحراء") == "ar"
    # Egyptian
    assert detect_language("راجل بيتمشى في الشارع والمطر نازل") == "ar"
    # Levantine
    assert detect_language("زلمة عم يركض بالشارع وقت الغروب") == "ar"
    # Moroccan Darija
    assert detect_language("واحد كيجري فالزنقة وكيدير لقطة زوينة") == "ar"
    # Gulf / Saudi / Emirati
    assert detect_language("ريال يطالع البحر وقت الشروق") == "ar"
    # Sudanese
    assert detect_language("زول ماشي في الدرب") == "ar"
    # English
    assert detect_language("A lone warrior walking across the dusty wasteland") == "en"

def test_dialect_concept_enrichment():
    # Egyptian
    eg = enrich_bilingual_prompt("راجل بيتمشى في الشارع")
    assert "man" in eg
    assert "walking" in eg

    # Levantine
    lev = enrich_bilingual_prompt("زلمة عم يركض بغروب الشمس")
    assert "man" in lev
    assert "sunset" in lev

    # Moroccan Darija
    mor = enrich_bilingual_prompt("واحد الراجل كيتمشى فواحد الغابة")
    assert "man" in mor
    assert "forest" in mor

    # Gulf
    gulf = enrich_bilingual_prompt("ريال يطالع البحر والغروب")
    assert "man" in gulf
    assert "ocean" in gulf

    # Sudanese
    sud = enrich_bilingual_prompt("زول ماشي بالشارع")
    assert "man" in sud

def test_parse_prompt_structure_bilingual():
    p_ar = "راجل ومعاه ست وطفل صغير في الصحراء"
    parsed_ar = parse_prompt_structure(p_ar)
    assert parsed_ar["language"] == "ar"
    assert "man" in parsed_ar["characters"]
    assert "woman" in parsed_ar["characters"]
    assert "child" in parsed_ar["characters"]

    p_en = "A man and a woman in the forest"
    parsed_en = parse_prompt_structure(p_en)
    assert parsed_en["language"] == "en"
    assert "man" in parsed_en["characters"]
    assert "woman" in parsed_en["characters"]
