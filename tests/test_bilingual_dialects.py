"""Unit tests for multilingual prompt understanding (11 languages/dialects)."""
import pytest
from cinematic_engine.prompt_engineer import (
    detect_language,
    enrich_bilingual_prompt,
    parse_prompt_structure,
)

def test_language_detection_11_languages():
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
    # 6. English
    assert detect_language("A futuristic city at night") == "en"
    # 7. French
    assert detect_language("Un homme marche dans la forêt") == "fr"
    # 8. Spanish
    assert detect_language("Un hombre camina en el bosque") == "es"
    # 9. German
    assert detect_language("Ein Mann geht durch den Wald") == "de"
    # 10. Chinese
    assert detect_language("沙漠中的骑士在日落时分") == "zh"
    # 11. Japanese
    assert detect_language("夕日の砂漠を歩く騎士") == "ja"
    # 12. Korean
    assert detect_language("석양의 사막을 걷는 기사") == "ko"

def test_multilingual_concept_enrichment():
    zh_res = enrich_bilingual_prompt("沙漠中的骑士在日落时分")
    assert "noble warrior" in zh_res or "desert" in zh_res or "sunset" in zh_res

    ja_res = enrich_bilingual_prompt("夕日の砂漠を歩く騎士")
    assert "samurai" in ja_res or "knight" in ja_res or "desert" in ja_res

    ko_res = enrich_bilingual_prompt("석양의 사막을 걷는 기사")
    assert "knight" in ko_res or "desert" in ko_res or "sunset" in ko_res

    fr_res = enrich_bilingual_prompt("Un homme marche dans la forêt")
    assert "man" in fr_res or "forest" in fr_res

def test_parse_prompt_structure_multilingual():
    p_zh = "一个男人在森林里"
    parsed_zh = parse_prompt_structure(p_zh)
    assert parsed_zh["language"] == "zh"
    assert "man" in parsed_zh["characters"]

    p_fr = "Une femme dans le désert"
    parsed_fr = parse_prompt_structure(p_fr)
    assert parsed_fr["language"] == "fr"
    assert "woman" in parsed_fr["characters"]
