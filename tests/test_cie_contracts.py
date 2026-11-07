import pytest

from studio.cie.contracts import (
    ContractError,
    from_cie_plan,
    validate_contract,
)


def valid_contract():
    return {
        "project_id": "test-project",
        "title": "The Journey",
        "language": "en",
        "style": "cinematic",
        "characters": [{
            "id": "c1",
            "name": "Mina",
            "role": "protagonist",
            "visual_identity": "short black hair, blue coat",
            "aliases": ["The traveler"],
            "states": {"1": "carrying a backpack"},
        }],
        "locations": [{
            "id": "l1",
            "name": "Old city",
            "visual_identity": "narrow stone streets",
        }],
        "scenes": [{
            "id": "s1",
            "title": "Arrival",
            "summary": "Mina enters the old city.",
            "location_id": "l1",
            "character_ids": ["c1"],
            "continuity_state": {"weather": "rain"},
        }],
        "shots": [{
            "id": "s1_sh1",
            "scene_id": "s1",
            "duration_seconds": 5,
            "action": "Mina walks forward",
            "character_ids": ["c1"],
            "camera": "wide",
            "movement": "slow tracking",
            "prompt": "A traveler enters a rainy old city.",
        }],
    }


def test_valid_contract_is_normalized():
    result = validate_contract(valid_contract())
    assert result["schema_version"] == "1.0"
    assert result["characters"][0]["id"] == "c1"
    assert result["shots"][0]["duration_seconds"] == 5.0


def test_duplicate_ids_are_rejected():
    data = valid_contract()
    data["characters"].append(dict(data["characters"][0]))
    with pytest.raises(ContractError, match="duplicate"):
        validate_contract(data)


def test_unknown_scene_character_reference_is_rejected():
    data = valid_contract()
    data["scenes"][0]["character_ids"] = ["missing"]
    with pytest.raises(ContractError, match="unknown characters"):
        validate_contract(data)


def test_unknown_location_reference_is_rejected():
    data = valid_contract()
    data["scenes"][0]["location_id"] = "missing"
    with pytest.raises(ContractError, match="unknown location"):
        validate_contract(data)


def test_shot_must_reference_existing_scene():
    data = valid_contract()
    data["shots"][0]["scene_id"] = "missing"
    with pytest.raises(ContractError, match="unknown scene"):
        validate_contract(data)


def test_invalid_shot_duration_is_rejected():
    data = valid_contract()
    data["shots"][0]["duration_seconds"] = 0
    with pytest.raises(ContractError, match="duration_seconds"):
        validate_contract(data)


def test_boolean_duration_is_rejected():
    data = valid_contract()
    data["shots"][0]["duration_seconds"] = True
    with pytest.raises(ContractError, match="numeric"):
        validate_contract(data)


def test_cie_adapter_preserves_known_data_without_inventing_cast_links():
    plan = {
        "language": "ar",
        "story": {"title": "رحلة"},
        "characters": [{
            "name": "Mina",
            "kind": "woman",
            "visual": "woman with a blue coat",
        }],
        "direction": {"style": "cinematic", "location": "Old city"},
        "scenes": [{
            "id": "s1",
            "title": "Arrival",
            "description": "She enters the city.",
        }],
    }

    result = from_cie_plan(plan, project_id="demo")

    assert result["project_id"] == "demo"
    assert result["characters"][0]["visual_identity"] == "woman with a blue coat"
    assert result["scenes"][0]["location_id"] == "l1"
    assert result["scenes"][0]["character_ids"] == []
    assert result["shots"] == []


def test_adapter_rejects_scene_without_summary():
    plan = {
        "story": {"title": "Test"},
        "direction": {"location": "Somewhere"},
        "scenes": [{"id": "s1", "title": "Empty"}],
    }
    with pytest.raises(ContractError, match="summary"):
        from_cie_plan(plan)
