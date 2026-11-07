LOOKS = {}

def _l(i, en, ar, prompt, grade="", grain=0, vignette=False, bars=False):
    LOOKS[i] = dict(en=en, ar=ar, prompt=prompt, grade=grade, grain=grain, vignette=vignette, bars=bars)

_l("cinematic", "Cinematic", "سينمائي", "cinematic film still, dramatic lighting, shallow depth of field, anamorphic lens, rich color grading, highly detailed", "eq=contrast=1.08:saturation=1.1", 6, True, True)
_l("cartoon", "Cartoon", "كرتوني", "cartoon style, flat colors, bold outlines, 2D animation, vibrant, clean shapes", "eq=saturation=1.7:contrast=1.15:brightness=0.02")
_l("anime", "Anime", "أنمي", "anime style, cel shading, detailed background art, soft glow, vibrant colors", "eq=saturation=1.45:contrast=1.1:brightness=0.03")
_l("animation3d", "3D animation", "رسوم ثلاثية الأبعاد", "3D animated film style, soft global illumination, expressive characters, high quality render", "eq=saturation=1.35:contrast=1.1")
_l("documentary", "Documentary", "وثائقي", "documentary photography, natural light, candid, realistic, 35mm", "eq=saturation=0.92:contrast=1.04", 4)
_l("noir", "Film noir", "نوار", "film noir, black and white, high contrast, deep shadows, rain, 1940s", "hue=s=0,eq=contrast=1.3:brightness=-0.02", 10, True)
_l("vintage", "Vintage 8mm", "قديم 8mm", "vintage 8mm film, faded colors, light leaks, nostalgic, 1970s", "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131", 12, True)
_l("scifi", "Sci-Fi", "خيال علمي", "science fiction, futuristic, cool teal and orange tones, volumetric light, epic scale", "colorbalance=bs=.18:bm=.12:rs=-.08,eq=contrast=1.1:saturation=1.1")
_l("fantasy", "Fantasy", "فانتازيا", "epic fantasy, magical atmosphere, golden hour glow, painterly, intricate detail", "colorbalance=rm=.08:bm=.1,eq=saturation=1.25:brightness=0.03")
_l("horror", "Horror", "رعب", "horror, dark moody atmosphere, fog, low-key lighting, unsettling", "eq=brightness=-0.07:saturation=0.65:contrast=1.2", 8, True)
_l("cyberpunk", "Cyberpunk", "سايبربانك", "cyberpunk city at night, neon lights, rain reflections, futuristic, high contrast", "colorbalance=rs=.2:bs=.25:gs=-.1,eq=contrast=1.15:saturation=1.4")
_l("watercolor", "Watercolor", "ألوان مائية", "watercolor painting, soft washes, paper texture, gentle colors, illustrated", "eq=saturation=0.9:contrast=0.95:brightness=0.04")
_l("realistic", "Realistic", "واقعي", "photorealistic, natural lighting, ultra detailed, sharp focus", "eq=contrast=1.04:saturation=1.05")

def get(i):
    return LOOKS.get(i) or LOOKS["cinematic"]

def chain(i):
    k, out = get(i), []
    if k["grade"]:
        out.append(k["grade"])
    if k["vignette"]:
        out.append("vignette=PI/5")
    if k["grain"]:
        out.append("noise=alls=%d:allf=t" % k["grain"])
    if k["bars"]:
        out.append("drawbox=x=0:y=0:w=iw:h=ih*0.11:color=black:t=fill,drawbox=x=0:y=ih-ih*0.11:w=iw:h=ih*0.11:color=black:t=fill")
    return out

def listing():
    return [dict(id=k, en=v["en"], ar=v["ar"]) for k, v in LOOKS.items()]
