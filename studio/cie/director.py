"""Director Intelligence: shot grammar, camera movement, lighting and pacing.
Deterministic shot ladder so consecutive scenes vary visually like a real
shot list, with tone-driven lighting design."""
TONES = ("natural", "dark", "bright", "warm", "cold", "dreamy", "gritty", "epic", "intimate")

SHOT_LADDER = [
    "wide establishing shot",
    "medium shot",
    "close-up shot",
    "over-the-shoulder shot",
    "extreme close-up detail shot",
    "low angle shot",
    "high angle wide shot",
]
CAMERA_MOVES = [
    "slow dolly in",
    "static tripod shot",
    "gentle pan to the right",
    "handheld tracking shot",
    "slow crane up",
    "slow push-in with subtle shake",
]
LIGHTING = {
    "natural":  "soft natural daylight, balanced contrast",
    "dark":     "low-key lighting, deep shadows, single hard source",
    "bright":   "high-key lighting, even soft light, airy palette",
    "warm":     "golden-hour warmth, amber tones, soft bounce",
    "cold":     "cool blue tones, hard sterile light",
    "dreamy":   "diffused glow, soft focus edges, pastel haze",
    "gritty":   "harsh practical lights, heavy contrast, desaturated",
    "epic":     "vast skylight, god rays, dramatic rim light",
    "intimate": "candle-soft close light, shallow pools of glow",
}
GENRE_LOCATION = {
    "action": "a rain-slick city street at dusk", "drama": "a quiet family home",
    "comedy": "a cluttered neighborhood cafe", "documentary": "a real city landscape",
    "horror": "an abandoned corridor at night", "scifi": "a futuristic terminal bathed in monitor glow",
    "fantasy": "an ancient stone courtyard under strange skies", "romance": "a small flower shop at golden hour",
    "thriller": "a dim underground parking garage",
}
_STYLE_TAIL = "cinematic, photorealistic, film grain, 24fps motion feel"


def plan(st, genre, tone):
    scenes = []
    for i in range(len(st["scenes"])):
        scenes.append({
            "shot_type": SHOT_LADDER[i % len(SHOT_LADDER)],
            "camera_move": CAMERA_MOVES[(i * 2 + 1) % len(CAMERA_MOVES)],
            "composition": "rule of thirds, layered foreground and background",
            "lighting": LIGHTING.get(tone, LIGHTING["natural"]),
        })
    return {
        "style": "%s %s, %s" % (tone, genre, _STYLE_TAIL),
        "location": GENRE_LOCATION.get(genre, GENRE_LOCATION["drama"]),
        "lighting": LIGHTING.get(tone, LIGHTING["natural"]),
        "scenes": scenes,
    }
