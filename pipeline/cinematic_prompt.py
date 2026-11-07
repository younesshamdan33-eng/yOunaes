"""Converts a plain idea into a cinema-grade prompt.
Built from verified best-practice structures for LTX/Wan/Sora-class models."""
import re

LENS = {"wide":"24mm wide-angle","medium":"50mm standard","close":"85mm portrait"}
LIGHT = {"DAY":"natural soft daylight, gentle shadows",
         "DUSK":"golden hour rim light, warm haze",
         "NIGHT":"moody low-key, practical neon accents",
         "DAWN":"cool blue-gold, misty depth"}
MOVE = {"static":"locked-off static frame",
        "push":"slow dolly push-in",
        "pull":"slow dolly pull-back",
        "pan":"smooth lateral pan",
        "handheld":"subtle handheld drift"}

def enhance(base, scene=None, shot=None, direction=None):
    """Build a 60-100 word cinematic prompt."""
    scene = scene or {}; shot = shot or {}; direction = direction or {}
    subj = base.strip()[:200]
    cam = LENS.get(shot.get("camera","medium"), "50mm")
    mov = MOVE.get(shot.get("movement","push"), "slow dolly push-in")
    light = LIGHT.get(scene.get("time_of_day","DAY"), "natural light")
    tone = direction.get("tone","cinematic")
    palette = direction.get("palette","natural")
    core = (f"{subj}. {cam}, {mov}. {light}. "
            f"{palette} palette, {tone} mood. "
            f"Photoreal, film grain, 4K, 24fps, shallow depth of field, "
            f"volumetric light, no flicker, no text, no watermark.")
    return core[:800]

def negative():
    return ("blurry, low quality, distorted, deformed hands, extra limbs, "
            "text, watermark, logo, static image, slideshow, freeze frame, "
            "duplicate frames, flicker, jitter, oversaturated")
