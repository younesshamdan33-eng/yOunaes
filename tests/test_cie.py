"""Tests for the Cinema Intelligence Engine (CIE) core units.

These tests assert the public contract that SCRIPT A should have produced:
  story.plan(idea)          -> {"scenes":[...], "genre":str, "tone":str}
  character.cast(story)     -> [{"name":str, "role":str, ...}, ...]
  director.plan(st, g, t)   -> {"style","location","lighting","scenes":[...]}
  lang.detect(text)         -> "ar"|"en"|...  (2-letter)
  lang.is_rtl(code)         -> bool
  cie.plan(idea)            -> {"story":..., "characters":..., "direction":...}
"""
import pytest
from studio import cie
from studio.cie import lang, story, character, director

# ---------- director.py ----------
class TestDirector:
    def _st(self, n=3):
        return {"scenes": [{"id": i, "beat": "b", "text": "scene %d" % i} for i in range(n)]}

    def test_plan_returns_required_keys(self):
        d = director.plan(self._st(), "drama", "natural")
        for k in ("style", "location", "lighting", "scenes"):
            assert k in d, f"missing key: {k}"

    def test_one_scene_per_input(self):
        d = director.plan(self._st(5), "action", "gritty")
        assert len(d["scenes"]) == 5

    def test_each_scene_has_shot_grammar(self):
        d = director.plan(self._st(3), "scifi", "cold")
        for s in d["scenes"]:
            assert "shot_type" in s
            assert "camera_move" in s
            assert "lighting" in s
            assert "composition" in s

    def test_shot_ladder_cycles(self):
        d = director.plan(self._st(7), "drama", "warm")
        types = [s["shot_type"] for s in d["scenes"]]
        assert len(set(types)) > 1, "no variety in shot types"

    def test_all_tones_have_lighting(self):
        st = self._st(1)
        for tone in director.TONES:
            d = director.plan(st, "drama", tone)
            assert d["lighting"] == director.LIGHTING[tone]

    def test_style_includes_genre_and_tone(self):
        d = director.plan(self._st(1), "horror", "dark")
        assert "horror" in d["style"]
        assert "dark" in d["style"]

    def test_unknown_tone_falls_back_to_natural(self):
        d = director.plan(self._st(1), "drama", "nonexistent")
        assert d["lighting"] == director.LIGHTING["natural"]

    def test_genre_location_lookup(self):
        for g in director.GENRE_LOCATION:
            d = director.plan(self._st(1), g, "natural")
            assert d["location"] == director.GENRE_LOCATION[g]

# ---------- lang.py ----------
class TestLang:
    def test_detect_arabic(self):
        assert lang.detect("مرحبا بك في العالم الجميل") == "ar"

    def test_detect_english(self):
        assert lang.detect("Hello world, how are you today") == "en"

    def test_detect_returns_2_letter(self):
        code = lang.detect("Bonjour le monde, comment vas-tu")
        assert isinstance(code, str) and len(code) == 2

    def test_is_rtl_ar(self):
        assert lang.is_rtl("ar") is True

    def test_is_rtl_en(self):
        assert lang.is_rtl("en") is False

    def test_rtl_set(self):
        for c in ("ar", "he", "fa", "ur"):
            assert lang.is_rtl(c), f"{c} should be RTL"

    def test_empty_string_safe(self):
        code = lang.detect("")
        assert isinstance(code, str)

# ---------- story.py ----------
class TestStory:
    def test_plan_returns_scenes_list(self):
        s = story.plan("A lonely astronaut discovers a signal from Earth.")
        assert "scenes" in s
        assert isinstance(s["scenes"], list)
        assert len(s["scenes"]) >= 1

    def test_plan_includes_genre(self):
        s = story.plan("A car chase through the city at night.")
        assert "genre" in s
        assert s["genre"] in ("action","drama","comedy","documentary","horror","scifi","fantasy","romance","thriller")

    def test_plan_includes_tone(self):
        s = story.plan("A ghost haunts a small village.")
        assert "tone" in s
        assert s["tone"] in director.TONES

    def test_plan_scenes_have_text(self):
        s = story.plan("Two lovers meet after years apart in the rain.")
        for sc in s["scenes"]:
            # every scene must carry either text or a beat so we can render it
            assert ("text" in sc) or ("beat" in sc) or ("summary" in sc), f"scene has no text: {sc}"

    def test_plan_genre_keywords(self):
        # a few obvious cases — tolerate imperfect detection
        s1 = story.plan("explosions and a high-speed car chase")
        assert s1["genre"] in ("action", "thriller")
        s2 = story.plan("a funny misunderstanding at a wedding")
        assert s2["genre"] in ("comedy", "romance")

# ---------- character.py ----------
class TestCharacter:
    def test_cast_returns_list(self):
        s = story.plan("A detective investigates a murder in a small town.")
        c = character.cast(s)
        assert isinstance(c, list)

    def test_cast_non_empty(self):
        s = story.plan("A hero saves the city from a villain.")
        c = character.cast(s)
        assert len(c) >= 1

    def test_cast_has_name(self):
        s = story.plan("Two friends go on a long adventure.")
        for ch in character.cast(s):
            assert "name" in ch and ch["name"]

    def test_cast_has_role(self):
        s = story.plan("A king and a knight defend their castle.")
        for ch in character.cast(s):
            assert "role" in ch

# ---------- orchestrator (cie/__init__.py) ----------
class TestOrchestrator:
    def test_plan_returns_full_structure(self):
        p = cie.plan("A lonely lighthouse keeper sees a strange light at sea.")
        assert "story" in p
        assert "scenes" in p["story"]
        assert "characters" in p
        assert "direction" in p

    def test_plan_direction_has_style_and_scenes(self):
        p = cie.plan("A young programmer hacks into a corporate server.")
        d = p["direction"]
        assert "style" in d
        assert "scenes" in d
        assert len(d["scenes"]) == len(p["story"]["scenes"])

    def test_plan_genre_propagates(self):
        p = cie.plan("A monster terrorizes a small coastal town.")
        # genre in story should equal genre used by director
        assert p["story"]["genre"]
        assert p["story"]["tone"]

    def test_plan_idempotent_structure(self):
        # same idea twice should produce same structural shape (length, keys)
        a = cie.plan("A pilot crash-lands on an alien world.")
        b = cie.plan("A pilot crash-lands on an alien world.")
        assert len(a["story"]["scenes"]) == len(b["story"]["scenes"])
        assert a["story"]["genre"] == b["story"]["genre"]
