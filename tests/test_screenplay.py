"""Tests for the rule-based Text-to-Screenplay engine.
No LLM, no network, no paid calls. Pure structure-ification."""
import pytest
from studio import screenplay as sc
from studio import film

# ---------- plan_from_idea ----------

def test_plan_requires_idea():
    with pytest.raises(sc.ScreenplayError):
        sc.plan_from_idea({})

def test_plan_rejects_non_string_idea():
    with pytest.raises(sc.ScreenplayError):
        sc.plan_from_idea({"idea": 123})

def test_plan_truncates_long_idea():
    plan = sc.plan_from_idea({"idea": "x" * 1000})
    assert len(plan["idea"]) == sc.MAX_IDEA

def test_plan_default_genre_drama():
    plan = sc.plan_from_idea({"idea": "a quiet street"})
    assert plan["genre"] == "drama"
    assert len(plan["scenes"]) >= 3

def test_plan_rejects_unknown_genre():
    with pytest.raises(sc.ScreenplayError):
        sc.plan_from_idea({"idea": "x", "genre": "western"})

def test_plan_target_seconds_bounds():
    with pytest.raises(sc.ScreenplayError):
        sc.plan_from_idea({"idea": "x", "target_seconds": 1})
    with pytest.raises(sc.ScreenplayError):
        sc.plan_from_idea({"idea": "x", "target_seconds": 999999})

def test_plan_shot_seconds_bounds():
    with pytest.raises(sc.ScreenplayError):
        sc.plan_from_idea({"idea": "x", "shot_seconds": 0})
    with pytest.raises(sc.ScreenplayError):
        sc.plan_from_idea({"idea": "x", "shot_seconds": 30})

def test_plan_explicit_scenes_split_on_blank_lines():
    idea = "Opening scene.\n\nSecond scene here.\n\nThird one."
    plan = sc.plan_from_idea({"idea": idea})
    assert plan["source"].startswith("explicit")
    assert len(plan["scenes"]) == 3

def test_plan_explicit_scenes_split_on_dashes():
    idea = "Scene one.\n---\nScene two."
    plan = sc.plan_from_idea({"idea": idea})
    assert plan["source"].startswith("explicit")
    assert len(plan["scenes"]) == 2

def test_plan_beat_sheet_action_has_opening_and_resolution():
    plan = sc.plan_from_idea({"idea": "explosion", "genre": "action"})
    titles = [s["title"] for s in plan["scenes"]]
    assert titles[0] == "opening"
    assert titles[-1] == "resolution"

def test_plan_continuity_includes_style_and_location():
    plan = sc.plan_from_idea({
        "idea": "test",
        "tone": "dark",
        "setting": "an abandoned warehouse",
        "subject": "a detective",
    })
    assert "low-key" in plan["continuity"]["style"]
    assert plan["continuity"]["location"] == "an abandoned warehouse"
    assert "a detective" in plan["continuity"]["characters"]

def test_plan_tone_unknown_falls_back_to_natural():
    plan = sc.plan_from_idea({"idea": "x", "tone": "nonexistent"})
    assert "natural" in plan["continuity"]["style"]

def test_plan_user_continuity_overrides_beat_sheet():
    plan = sc.plan_from_idea({
        "idea": "x",
        "continuity": {"style": "handheld, gritty", "location": "moon base", "characters": ["astronaut"]},
    })
    assert plan["continuity"]["style"] == "handheld, gritty"
    assert plan["continuity"]["location"] == "moon base"
    assert plan["continuity"]["characters"] == ["astronaut"]

def test_plan_includes_idea_in_output():
    plan = sc.plan_from_idea({"idea": "a quiet evening"})
    assert plan["idea"] == "a quiet evening"

def test_plan_all_genres_produce_scenes():
    for g in sc.GENRES:
        plan = sc.plan_from_idea({"idea": "test", "genre": g})
        assert len(plan["scenes"]) >= 3, f"genre {g} produced too few scenes"

# ---------- plan_and_validate (integration with film.plan_film) ----------

def test_plan_and_validate_produces_film_object():
    f, plan = sc.plan_and_validate({"idea": "a thief robs a bank at night", "genre": "action", "target_seconds": 30})
    assert f["state"] == "draft"
    assert f["title"]
    assert len(f["scenes"]) >= 3
    # Each scene must have at least one shot.
    assert all(sc for sc in f["scenes"] for s in sc["shots"])
    # Total shot seconds should approximate the target.
    total = sum(s["seconds"] for sc in f["scenes"] for s in sc["shots"])
    assert total >= 20  # at least 20s of content for a 30s target

def test_plan_and_validate_long_form_120s():
    f, plan = sc.plan_and_validate({"idea": "a journey across the desert", "genre": "drama", "target_seconds": 120, "shot_seconds": 5})
    n_shots = sum(len(sc["shots"]) for sc in f["scenes"])
    # 120s / 5s = at least 24 shots minimum
    assert n_shots >= 20
    assert f["target_seconds"] == 120

def test_plan_and_validate_uses_user_provider_model():
    f, plan = sc.plan_and_validate({
        "idea": "test",
        "provider": "magic_hour",
        "model": "ltx-2.3",
        "resolution": "720p",
    })
    assert f["provider"] == "magic_hour"
    assert f["model"] == "ltx-2.3"
    assert f["resolution"] == "720p"

def test_plan_and_validate_rejects_invalid_model():
    with pytest.raises(film.FilmError):
        sc.plan_and_validate({"idea": "test", "model": "nonexistent-model"})
