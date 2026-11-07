"""Canonical, validated data contract for cinematic production plans.

This module is deliberately independent of providers, GPU and model inference.
It defines stable references between characters, locations, scenes and shots.
"""

from copy import deepcopy


SCHEMA_VERSION = "1.0"


class ContractError(ValueError):
    """Raised when a production plan violates the canonical contract."""


def _require_text(value, field, allow_empty=False):
    if not isinstance(value, str):
        raise ContractError(f"{field} must be a string")
    value = value.strip()
    if not allow_empty and not value:
        raise ContractError(f"{field} must not be empty")
    return value


def _require_list(value, field):
    if not isinstance(value, list):
        raise ContractError(f"{field} must be a list")
    return value


def _unique_entities(items, collection, required_fields):
    items = _require_list(items, collection)
    result = []
    seen = set()

    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ContractError(f"{collection}[{index}] must be an object")

        item = deepcopy(raw)
        item_id = _require_text(item.get("id"), f"{collection}[{index}].id")

        if item_id in seen:
            raise ContractError(f"duplicate {collection} id: {item_id}")
        seen.add(item_id)

        for field in required_fields:
            item[field] = _require_text(
                item.get(field), f"{collection}[{index}].{field}"
            )

        result.append(item)

    return result, seen


def validate_contract(payload):
    """Validate and return a normalized JSON-compatible production contract."""
    if not isinstance(payload, dict):
        raise ContractError("contract must be an object")

    characters, character_ids = _unique_entities(
        payload.get("characters", []),
        "characters",
        ("name", "role", "visual_identity"),
    )
    locations, location_ids = _unique_entities(
        payload.get("locations", []),
        "locations",
        ("name", "visual_identity"),
    )
    scenes, scene_ids = _unique_entities(
        payload.get("scenes", []),
        "scenes",
        ("title", "summary"),
    )
    shots, shot_ids = _unique_entities(
        payload.get("shots", []),
        "shots",
        ("scene_id", "action"),
    )

    for i, character in enumerate(characters):
        aliases = character.get("aliases", [])
        if not isinstance(aliases, list) or not all(
            isinstance(x, str) for x in aliases
        ):
            raise ContractError(f"characters[{i}].aliases must be a list of strings")
        character["aliases"] = [x.strip() for x in aliases if x.strip()]

        states = character.get("states", {})
        if not isinstance(states, dict):
            raise ContractError(f"characters[{i}].states must be an object")
        character["states"] = states

    for i, location in enumerate(locations):
        aliases = location.get("aliases", [])
        if not isinstance(aliases, list) or not all(
            isinstance(x, str) for x in aliases
        ):
            raise ContractError(f"locations[{i}].aliases must be a list of strings")
        location["aliases"] = [x.strip() for x in aliases if x.strip()]

    for i, scene in enumerate(scenes):
        location_id = scene.get("location_id")
        if location_id is not None and location_id not in location_ids:
            raise ContractError(
                f"scenes[{i}] references unknown location: {location_id}"
            )

        refs = scene.get("character_ids", [])
        if not isinstance(refs, list):
            raise ContractError(f"scenes[{i}].character_ids must be a list")
        unknown = set(refs) - character_ids
        if unknown:
            raise ContractError(
                f"scenes[{i}] references unknown characters: {sorted(unknown)}"
            )

        state = scene.get("continuity_state", {})
        if not isinstance(state, dict):
            raise ContractError(f"scenes[{i}].continuity_state must be an object")

        scene["character_ids"] = list(dict.fromkeys(refs))
        scene["continuity_state"] = state

    for i, shot in enumerate(shots):
        if shot["scene_id"] not in scene_ids:
            raise ContractError(
                f"shots[{i}] references unknown scene: {shot['scene_id']}"
            )

        duration = shot.get("duration_seconds", 5)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise ContractError(f"shots[{i}].duration_seconds must be numeric")
        if not 0 < duration <= 60:
            raise ContractError(f"shots[{i}].duration_seconds must be in (0, 60]")

        refs = shot.get("character_ids", [])
        if not isinstance(refs, list):
            raise ContractError(f"shots[{i}].character_ids must be a list")
        unknown = set(refs) - character_ids
        if unknown:
            raise ContractError(
                f"shots[{i}] references unknown characters: {sorted(unknown)}"
            )

        shot["duration_seconds"] = float(duration)
        shot["character_ids"] = list(dict.fromkeys(refs))
        shot["camera"] = _require_text(
            shot.get("camera", "static"), f"shots[{i}].camera"
        )
        shot["movement"] = _require_text(
            shot.get("movement", "static"), f"shots[{i}].movement"
        )
        shot["prompt"] = _require_text(
            shot.get("prompt", ""), f"shots[{i}].prompt", allow_empty=True
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": _require_text(
            payload.get("project_id", "untitled"), "project_id"
        ),
        "title": _require_text(payload.get("title", "Untitled"), "title"),
        "language": _require_text(
            payload.get("language", "en"), "language"
        ),
        "style": _require_text(payload.get("style", "cinematic"), "style"),
        "characters": characters,
        "locations": locations,
        "scenes": scenes,
        "shots": shots,
    }


def from_cie_plan(plan, project_id="untitled"):
    """Adapt the current CIE plan into the canonical contract.

    This adapter preserves known facts only. It does not invent scene-character
    relationships or pretend that scene plans are already shot plans.
    """
    if not isinstance(plan, dict):
        raise ContractError("CIE plan must be an object")

    story = plan.get("story") or {}
    direction = plan.get("direction") or {}

    characters = []
    for index, item in enumerate(plan.get("characters") or [], 1):
        if not isinstance(item, dict):
            raise ContractError(f"CIE character {index} must be an object")

        visual = item.get("visual") or item.get("description") or item.get("name")
        characters.append({
            "id": f"c{index}",
            "name": item.get("name") or f"Character {index}",
            "role": item.get("kind") or item.get("role") or "person",
            "visual_identity": visual or "",
            "voice": item.get("voice"),
            "aliases": [],
            "states": {},
        })

    location_name = direction.get("location") or "Unspecified location"
    locations = [{
        "id": "l1",
        "name": location_name,
        "visual_identity": location_name,
        "aliases": [],
    }]

    scenes = []
    for index, item in enumerate(plan.get("scenes") or [], 1):
        if not isinstance(item, dict):
            raise ContractError(f"CIE scene {index} must be an object")

        scenes.append({
            "id": str(item.get("id") or f"s{index}"),
            "title": item.get("title") or f"Scene {index}",
            "summary": item.get("description") or item.get("prompt") or "",
            "beat": item.get("beat"),
            "location_id": "l1",
            # The current CIE does not reliably identify scene-level cast.
            "character_ids": [],
            "continuity_state": {},
        })

    payload = {
        "project_id": project_id,
        "title": story.get("title") or "Untitled",
        "language": plan.get("language") or "en",
        "style": direction.get("style") or "cinematic",
        "characters": characters,
        "locations": locations,
        "scenes": scenes,
        # Shot planning remains a separate next-stage responsibility.
        "shots": [],
    }
    return validate_contract(payload)
