from config import CinematicConfig
SHOT_MAP = {"wide": "wide shot, establishing composition","medium": "medium shot, waist-up framing","close_up": "close-up shot, detailed facial features","extreme_close_up": "extreme close-up, macro detail","establishing": "establishing shot, wide environmental context","over_shoulder": "over-the-shoulder shot, shallow depth of field"}
CAMERA_MAP = {"static": "static camera, locked-off tripod","pan": "smooth panning camera movement","tilt": "slow tilt camera movement","dolly_in": "dolly in, pushing toward subject","dolly_out": "dolly out, pulling away from subject","tracking": "tracking shot, following subject smoothly","orbit": "orbit shot, circling around subject","handheld": "subtle handheld camera movement"}
LENS_MAP = {"wide": "wide-angle lens, 24mm","normal": "normal lens, 50mm","telephoto": "telephoto lens, 85mm","macro": "macro lens, extreme close focus"}
LIGHT_MAP = {"natural": "natural soft lighting, balanced exposure","dramatic": "dramatic chiaroscuro lighting, strong contrast","studio": "studio lighting, softbox key and fill","night": "night lighting, practical sources, low-key","day": "bright daylight, soft shadows","volumetric": "volumetric lighting, visible light rays","backlight": "backlit subject, rim light, silhouette effect"}
LOOK_MAP = {"natural": "natural cinematic color science, balanced contrast","dramatic": "high-contrast dramatic look, deep shadows","warm": "warm golden tones, soft highlights","cold": "cool blue tones, desaturated shadows","sci_fi": "sci-fi cinematic look, teal and orange, neon accents","documentary": "documentary realism, muted colors, natural texture","epic": "epic cinematic scale, rich colors, filmic tone mapping"}
def build_cinematic_prompt(user_prompt: str, cfg: CinematicConfig) -> str:
    parts = [user_prompt.strip().rstrip(".")]
    parts.append(SHOT_MAP.get(cfg.shot_type, SHOT_MAP["medium"]))
    parts.append(CAMERA_MAP.get(cfg.camera_motion, CAMERA_MAP["static"]))
    parts.append(LENS_MAP.get(cfg.lens, LENS_MAP["normal"]))
    parts.append(LIGHT_MAP.get(cfg.lighting, LIGHT_MAP["natural"]))
    parts.append(LOOK_MAP.get(cfg.look, LOOK_MAP["natural"]))
    if cfg.depth_of_field == "shallow":
        parts.append("shallow depth of field, bokeh background")
    else:
        parts.append("deep focus, sharp foreground and background")
    parts.append("cinematic film grain, high detail, professional color grading")
    return ", ".join(parts)
