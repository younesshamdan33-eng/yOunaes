"""Text-to-Screenplay engine: converts a one-line idea into a structured film plan.

This is a RULE-BASED engine (no LLM dependency). It uses genre templates and beat
sheets to produce scenes with narration prompts. An LLM provider can be added later
to enrich the output, but the engine must work without one.

Honesty contract:
- The output is a structured plan, NOT a creative screenplay.
- Quality is bounded by the templates; complex ideas get simpler plans.
- The engine never claims to "understand" the idea — it structure-ifies it.
"""
import re
from . import film, render

MAX_IDEA = 500
MAX_SCENES = 60  # cap before film.MAX_SCENES kicks in
DEFAULT_SHOT_SECONDS = 5

GENRES = ("action", "drama", "comedy", "documentary", "horror", "scifi", "fantasy", "romance", "thriller")

# Beat sheet templates: (position_fraction, beat_name, narration_template)
# Each beat becomes one scene. Templates use {subject}, {setting}, {tone}.
BEAT_SHEETS = {
    "action": [
        (0.0,  "opening",      "Establish the world: {setting}. {subject} moves through it."),
        (0.15, "inciting",     "A sudden threat disrupts {subject}'s routine."),
        (0.30, "response",      "{subject} takes action, pushing back against the threat."),
        (0.50, "midpoint",     "A reversal: the situation changes in a major way."),
        (0.70, "escalation",   "Stakes rise. {subject} faces a harder challenge."),
        (0.85, "climax",       "Final confrontation. {subject} gives everything."),
        (1.0,  "resolution",   "Aftermath: {setting} settles into a new equilibrium."),
    ],
    "drama": [
        (0.0,  "ordinary_world", "We meet {subject} in their everyday life at {setting}."),
        (0.20, "want",           "{subject} reveals a desire or unfulfilled need."),
        (0.40, "struggle",       "Obstacles mount. {subject} confronts what holds them back."),
        (0.65, "turn",           "A choice is made that cannot be undone."),
        (0.85, "consequence",    "The cost of that choice becomes visible."),
        (1.0,  "acceptance",     "{subject} comes to terms with the new reality."),
    ],
    "comedy": [
        (0.0,  "setup",        "{subject} is in a familiar mess at {setting}."),
        (0.20, "sparked",      "A small lie or mistake snowballs."),
        (0.40, "rising",       "{subject} digs themselves in deeper."),
        (0.65, "twist",        "An unexpected visitor or revelation."),
        (0.85, "unraveling",   "Everything comes apart — chaotically."),
        (1.0,  "landing",     "A resolution, awkward but warm."),
    ],
    "documentary": [
        (0.0,  "context",     "Establish the subject: {subject} at {setting}."),
        (0.25, "history",     "How things came to be this way."),
        (0.50, "stakeholders","The people involved and their perspectives."),
        (0.75, "tension",     "The central conflict or question."),
        (1.0,  "reflection",  "What it means, and what comes next."),
    ],
    "horror": [
        (0.0,  "calm",        "{setting} is quiet. Too quiet."),
        (0.20, "wrong",       "Something is off — {subject} senses it."),
        (0.40, "manifest",    "The threat becomes visible."),
        (0.65, "pursuit",     "{subject} is hunted."),
        (0.85, "reveal",      "The true nature of the threat is exposed."),
        (1.0,  "aftermath",   "Dawn breaks, but nothing is the same."),
    ],
    "scifi": [
        (0.0,  "establish",   "The future: {setting}. {subject} navigates it."),
        (0.20, "anomaly",     "An unexpected signal or event."),
        (0.40, "investigate", "{subject} digs deeper."),
        (0.65, "discovery",   "A truth about the world is uncovered."),
        (0.85, "decision",    "{subject} must choose what to do with it."),
        (1.0,  "consequence", "The world is changed."),
    ],
    "fantasy": [
        (0.0,  "homeland",    "{subject} lives at {setting}, unaware of what's coming."),
        (0.20, "called",       "A call to adventure arrives."),
        (0.40, "trial",        "{subject} faces a first test."),
        (0.65, "ally",         "Help arrives from an unexpected source."),
        (0.85, "confront",     "{subject} confronts the central threat."),
        (1.0,  "return",       "{subject} returns, transformed."),
    ],
    "romance": [
        (0.0,  "meet",        "{subject} and {other} meet at {setting}."),
        (0.25, "spark",       "A connection forms."),
        (0.50, "blocker",      "Something keeps them apart."),
        (0.75, "reunion",     "They find their way back."),
        (1.0,  "together",    "Together at last."),
    ],
    "thriller": [
        (0.0,  "ordinary",    "{subject}'s ordinary life at {setting}."),
        (0.20, "intrusion",   "Something invades that life."),
        (0.40, "investigate",  "{subject} starts digging."),
        (0.65, "wrong_turn",  "{subject} makes a mistake."),
        (0.85, "cornered",    "{subject} is trapped."),
        (1.0,  "escape",      "{subject} breaks free — at a cost."),
    ],
}

# Tone → visual style hint
TONE_STYLES = {
    "dark":       "low-key lighting, muted palette, deep shadows",
    "bright":     "high-key lighting, saturated colors, soft contrast",
    "warm":       "golden hour, amber tones, soft grain",
    "cold":       "blue tint, hard light, sterile feel",
    "dreamy":     "soft focus, pastel palette, slow motion",
    "gritty":     "high contrast, handheld camera, desaturated",
    "epic":       "wide shots, dramatic skies, slow camera moves",
    "intimate":   "close-ups, shallow depth of field, natural light",
}

class ScreenplayError(Exception):
    pass

def _s(v, n):
    return (v or "").strip()[:n] if isinstance(v, str) else ""

def _extract(spec, key, default=""):
    """Extract a field from spec; treat empty/missing as default."""
    v = spec.get(key, default)
    return v.strip() if isinstance(v, str) else default

def _split_scenes_from_idea(idea):
    """If the idea already contains scene breaks (---), split them. Otherwise None."""
    parts = [p.strip() for p in re.split(r"\n\s*-{2,}\s*\n|\n\s*\n", idea) if p.strip()]
    return parts if len(parts) > 1 else None

def plan_from_idea(spec):
    """Convert a one-line idea + target_seconds into a film-ready plan.

    Required: {idea: str}
    Optional: genre, target_seconds, shot_seconds, title, language, tone, setting, subject, other, continuity, model, resolution, aspect_ratio, audio, fps
    """
    if not isinstance(spec, dict):
        raise ScreenplayError("body must be an object")
    idea = _s(spec.get("idea"), MAX_IDEA)
    if not idea:
        raise ScreenplayError("idea is required (a short description of the film)")

    genre = (spec.get("genre") or "drama").strip().lower()
    if genre not in GENRES:
        raise ScreenplayError("genre must be one of: " + ", ".join(GENRES))

    target = spec.get("target_seconds")
    if target is None:
        target = 60
    if isinstance(target, bool) or not isinstance(target, int) or not 6 <= target <= film.MAX_TARGET:
        raise ScreenplayError("target_seconds must be an integer between 6 and %d" % film.MAX_TARGET)

    raw_shot = spec.get("shot_seconds")
    shot = DEFAULT_SHOT_SECONDS if raw_shot is None else raw_shot
    if isinstance(shot, bool) or not isinstance(shot, int) or not 2 <= shot <= 10:
        raise ScreenplayError("shot_seconds must be an integer between 2 and 10")

    title = _s(spec.get("title"), 100) or idea[:60]
    language = _s(spec.get("language"), 8) or "en"
    tone = _s(spec.get("tone"), 40).lower()
    setting = _extract(spec, "setting") or "an unspecified location"
    subject = _extract(spec, "subject") or "the protagonist"
    other = _extract(spec, "other") or "another figure"
    style_hint = TONE_STYLES.get(tone, "natural lighting, balanced palette")

    # If the user supplied explicit scenes, prefer them over beat-sheet generation.
    explicit = _split_scenes_from_idea(idea)
    if explicit:
        scenes_raw = [{"title": "Scene %d" % i, "text": t} for i, t in enumerate(explicit, 1)]
        source = "explicit (split from idea)"
    else:
        beats = BEAT_SHEETS[genre]
        # How many scenes? Aim for ~1 scene per 8-15 seconds of target, capped by beat count and MAX_SCENES.
        target_scenes = max(3, min(len(beats), target // 10, MAX_SCENES))
        # If target is large, expand by repeating beat patterns (climax gets more shots).
        if target_scenes < len(beats):
            # Use a subset that preserves opening + resolution.
            keep = [beats[0], beats[len(beats)//2], beats[-1]]
            scenes_raw = [{"title": b[1], "text": b[2].format(subject=subject, setting=setting, other=other, tone=tone)} for b in keep]
        else:
            scenes_raw = [{"title": b[1], "text": b[2].format(subject=subject, setting=setting, other=other, tone=tone)} for b in beats]
        source = "beat-sheet (%s, %d beats)" % (genre, len(scenes_raw))

    # Build continuity metadata used by film.build_prompt().
    continuity = {
        "style": style_hint,
        "location": setting,
        "characters": [c for c in [subject, other] if c and c != "another figure" and c != "the protagonist"][:10],
    }
    # Merge any user-supplied continuity overrides.
    user_cont = spec.get("continuity") if isinstance(spec.get("continuity"), dict) else {}
    if user_cont.get("style"): continuity["style"] = _s(user_cont.get("style"), 200)
    if user_cont.get("location"): continuity["location"] = _s(user_cont.get("location"), 200)
    if isinstance(user_cont.get("characters"), list):
        continuity["characters"] = [_s(x, 200) for x in user_cont["characters"] if isinstance(x, str) and x.strip()][:10]

    plan = {
        "title": title,
        "language": language,
        "genre": genre,
        "tone": tone or "natural",
        "target_seconds": target,
        "shot_seconds": shot,
        "provider": spec.get("provider", "magic_hour"),
        "model": spec.get("model", "ltx-2.5"),
        "resolution": spec.get("resolution", "480p"),
        "aspect_ratio": spec.get("aspect_ratio", "16:9"),
        "audio": bool(spec.get("audio", False)),
        "fps": spec.get("fps", 24),
        "continuity": continuity,
        "scenes": scenes_raw,
        "source": source,
        "idea": idea,
    }
    return plan

def plan_and_validate(spec):
    """plan_from_idea + film.plan_film — produces a fully validated film object (not yet saved)."""
    plan = plan_from_idea(spec)
    # film.plan_film validates provider/model/resolution/aspect_ratio/audio and builds shots.
    return film.plan_film(plan), plan
