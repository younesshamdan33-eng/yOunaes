"""Cinema Intelligence Engine (CIE) — the central production brain.

Orchestrates the specialized intelligence units:
  story -> characters -> direction -> scenes/shots -> narration plan.

The CIE converts a raw idea (Arabic or English) into a complete,
provider-ready film plan, then hands execution to the existing
film engine (FilmRunner + providers). It is rule-based and fully
offline; an optional LLM enrichment hook (llm.py) can improve the
plan when the user configures one, but is never required.

Honesty contract:
- Prompts sent to video models are English (models respond best);
  narration and subtitles stay in the film's language.
- CIE structures and plans; it does not claim creative genius.
- Continuity is enforced by injecting identical character visual
  descriptions into every prompt; it is best-effort, not guaranteed
  by the model.
"""
import math, time
from .. import film
from . import lang, story, character, director
try:
    from . import scene as scene_mod
except ImportError:
    scene_mod = None
try:
    from . import voice
except ImportError:
    voice = None
from . import lang, story, character, director
try:
    from . import scene as scene_mod
except ImportError:
    scene_mod = None
try:
    from . import voice
except ImportError:
    voice = None
from . import lang, story, character, director
try:
    from . import scene as scene_mod
except ImportError:
    scene_mod = None
try:
    from . import voice
except ImportError:
    voice = None

MAX_IDEA = 800
MIN_TARGET, MAX_TARGET_CIE = 8, 600
DEFAULT_SHOT = 5


class CIEError(Exception):
    pass


def _s(v, n):
    return (v or "").strip()[:n] if isinstance(v, str) else ""


def plan(spec):
    """idea -> full CIE production plan (pure dict, no I/O, deterministic)."""
    if isinstance(spec, str):
        spec = {"idea": spec}
    if not isinstance(spec, dict):
        raise CIEError("body must be an object")
    idea = _s(spec.get("idea"), MAX_IDEA)
    if len(idea) < 4:
        raise CIEError("idea is required (at least 4 characters)")
    language = (_s(spec.get("language"), 8) or lang.detect_language(idea)).lower()
    if language not in ("ar", "en"):
        language = "en"
    genre = (_s(spec.get("genre"), 20) or lang.detect_genre(idea)).lower()
    if genre not in story.GENRES:
        genre = "drama"
    tone = (_s(spec.get("tone"), 20) or lang.detect_tone(idea)).lower()
    if tone not in director.TONES:
        tone = "natural"
    ts = spec.get("target_seconds", 30)
    if isinstance(ts, bool):
        raise CIEError("target_seconds must be an integer")
    try:
        target = int(ts)
    except (TypeError, ValueError):
        raise CIEError("target_seconds must be an integer")
    if not MIN_TARGET <= target <= MAX_TARGET_CIE:
        raise CIEError("target_seconds must be between %d and %d" % (MIN_TARGET, MAX_TARGET_CIE))
    shot = spec.get("shot_seconds", DEFAULT_SHOT)
    if isinstance(shot, bool) or not isinstance(shot, int) or not 2 <= shot <= 10:
        raise CIEError("shot_seconds must be an integer between 2 and 10")

    st = story.build(idea, genre, tone, target, language)
    st["genre"] = genre
    st["tone"] = tone
    chars = character.build(st, language, spec)
    direction = director.plan(st, genre, tone)
    # Build enriched scene records using the actual scene module API.
    # Each story scene is combined with its environment and director shot grammar.
    scenes = []
    director_scenes = direction.get("scenes", [])

    for index, story_scene in enumerate(st.get("scenes", [])):
        scene_input = dict(story_scene)
        scene_input["location"] = direction.get("location", "")

        scene_direction = dict(direction)
        scene_direction["tone"] = tone

        environment = scene_mod.build(scene_input, scene_direction)
        shot_direction = (
            director_scenes[index]
            if index < len(director_scenes) and isinstance(director_scenes[index], dict)
            else {}
        )

        prompt_parts = [
            story_scene.get("description", ""),
            "Location: " + direction.get("location", ""),
            "Visual style: " + direction.get("style", ""),
            "Shot type: " + shot_direction.get("shot_type", "wide shot"),
            "Camera movement: " + shot_direction.get("camera_move", "static"),
            "Composition: " + shot_direction.get("composition", ""),
            "Lighting: " + shot_direction.get("lighting", direction.get("lighting", "")),
            "Environment: " + environment.get("env_prompt", ""),
        ]
        prompt = ". ".join(
            part.strip().rstrip(".")
            for part in prompt_parts
            if isinstance(part, str) and part.strip()
        )

        scenes.append({
            **story_scene,
            **environment,
            **shot_direction,
            "location": direction.get("location", ""),
            "prompt": prompt,
        })
    narration = voice.narrate({"scenes": scenes}, language=language)
    submissions = math.ceil(target / shot)
    return {
        "idea": idea, "language": language, "genre": genre, "tone": tone,
        "target_seconds": target, "shot_seconds": shot,
        "story": st, "characters": chars, "direction": direction,
        "scenes": scenes, "narration": narration,
        "submissions_est": submissions,
        "note": "each shot is one provider submission; Magic Hour free tier "
                "defaults to 5 submissions/day (MAGIC_HOUR_DAILY_LIMIT env)",
        "created": time.time(),
    }



def _build_continuity_memory(contract):
    """Build persistent character/location memory from the canonical contract."""
    from . import memory

    mem = memory.new_memory()
    character_prompts = []

    for item in contract.get("characters", []):
        cid = memory.add_character(
            mem,
            name=item["name"],
            role=item.get("role") or "character",
            look=item.get("visual_identity") or "",
            age=item.get("age") or "adult",
            gender=item.get("gender"),
            en_name=item.get("en_name"),
            aliases=item.get("aliases") or [],
            voice=item.get("voice"),
        )
        # Keep the explicit name: memory.core() describes appearance but
        # does not include the character's name.
        identity_text = memory.identity(mem, cid)
        character_prompts.append(
            "%s: %s" % (item["name"], identity_text)
        )

    for item in contract.get("locations", []):
        memory.add_location(
            mem,
            name=item["name"],
            kind=item.get("kind") or "setting",
            look=item.get("visual_identity") or "",
            aliases=item.get("aliases") or [],
        )

    return mem, character_prompts

def film_spec(p, overrides=None):
    """CIE plan -> canonical contract -> dict compatible with film.plan_film()."""
    from .contracts import from_cie_plan

    o = overrides or {}
    contract = from_cie_plan(p)
    continuity_memory, character_identities = _build_continuity_memory(contract)
    scenes = [{"title": sc["title"], "text": sc["prompt"]} for sc in p["scenes"]]
    return {
        "title": p["story"]["title"],
        "provider": o.get("provider", "magic_hour"),
        "model": o.get("model", "ltx-2.5"),
        "resolution": o.get("resolution", "480p"),
        "aspect_ratio": o.get("aspect_ratio", "16:9"),
        "audio": bool(o.get("audio", False)),
        "fps": o.get("fps", 24),
        "shot_seconds": p["shot_seconds"],
        "target_seconds": p["target_seconds"],
        "language": p["language"],
        "continuity": {
            "style": contract["style"],
            "location": contract["locations"][0]["visual_identity"]
                        if contract["locations"] else p["direction"]["location"],
            "characters": character_identities[:10],
        },
        "continuity_memory": continuity_memory,
        "scenes": scenes,
    }


def create_film(film_store, spec):
    """Full pipeline: CIE plan -> validated film object saved to disk."""
    p = plan(spec)
    fs = film_spec(p, spec)
    f = film.plan_film(fs)
    f["cie"] = p
    f["continuity_memory"] = fs["continuity_memory"]
    film_store.save(f)
    film_store.log(f["id"], "CIE plan created: %s (genre=%s tone=%s lang=%s)"
                   % (p["story"]["logline"][:80], p["genre"], p["tone"], p["language"]))
    return f
