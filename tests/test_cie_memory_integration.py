from studio import cie, film


def _sample_plan():
    return cie.plan(
        "A brave explorer discovers an ancient temple in a desert."
    )


def test_film_spec_builds_character_memory():
    p = _sample_plan()
    fs = cie.film_spec(p)

    mem = fs["continuity_memory"]

    assert len(mem["characters"]) == len(p["characters"])
    assert len(mem["locations"]) >= 1

    identities = fs["continuity"]["characters"]
    assert len(identities) == len(p["characters"])

    for character in p["characters"]:
        assert any(
            character["name"] in identity
            for identity in identities
        )


def test_memory_identity_reaches_film_shot_prompts():
    p = _sample_plan()
    fs = cie.film_spec(p, {"provider": "magic_hour"})
    f = film.plan_film(fs)

    prompts = [
        shot["prompt"]
        for scene in f["scenes"]
        for shot in scene["shots"]
    ]

    assert prompts

    for character in p["characters"]:
        assert any(
            character["name"] in prompt
            for prompt in prompts
        )


def test_memory_is_preserved_in_film_spec():
    p = _sample_plan()
    fs = cie.film_spec(p)

    mem = fs["continuity_memory"]

    for cid, character in mem["characters"].items():
        assert character["id"] == cid
        assert character["name"]
        assert character["look"]
        assert character["palette"]
