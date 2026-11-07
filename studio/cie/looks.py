LOOKS = {
    "cinematic": dict(en="Cinematic", ar="سينمائي", prompt="cinematic film still, dramatic lighting, shallow depth of field, anamorphic lens, rich color grading, highly detailed"),
    "cartoon": dict(en="Cartoon", ar="كرتوني", prompt="cartoon style, flat colors, bold outlines, 2D animation, vibrant, clean shapes"),
    "anime": dict(en="Anime", ar="أنمي", prompt="anime style, cel shading, detailed background art, soft glow, vibrant colors"),
    "animation3d": dict(en="3D animation", ar="رسوم ثلاثية الأبعاد", prompt="3D animated film style, soft global illumination, expressive characters, high quality render"),
    "documentary": dict(en="Documentary", ar="وثائقي", prompt="documentary photography, natural light, candid, realistic, 35mm"),
    "noir": dict(en="Film noir", ar="نوار", prompt="film noir, black and white, high contrast, deep shadows, rain, 1940s"),
    "vintage": dict(en="Vintage 8mm", ar="قديم 8mm", prompt="vintage 8mm film, faded colors, light leaks, nostalgic, 1970s"),
    "scifi": dict(en="Sci-Fi", ar="خيال علمي", prompt="science fiction, futuristic, cool teal and orange tones, volumetric light, epic scale"),
    "fantasy": dict(en="Fantasy", ar="فانتازيا", prompt="epic fantasy, magical atmosphere, golden hour glow, painterly, intricate detail"),
    "horror": dict(en="Horror", ar="رعب", prompt="horror, dark moody atmosphere, fog, low-key lighting, unsettling"),
    "cyberpunk": dict(en="Cyberpunk", ar="سايبربانك", prompt="cyberpunk city at night, neon lights, rain reflections, futuristic, high contrast"),
    "watercolor": dict(en="Watercolor", ar="ألوان مائية", prompt="watercolor painting, soft washes, paper texture, gentle colors, illustrated"),
    "realistic": dict(en="Realistic", ar="واقعي", prompt="photorealistic, natural lighting, ultra detailed, sharp focus"),
}
NEGATIVE = "blurry, low quality, distorted face, extra limbs, deformed hands, text, watermark, logo, subtitles"

def get(look_id):
    return LOOKS.get(look_id) or LOOKS["cinematic"]

def listing():
    return [dict(id=k, en=v["en"], ar=v["ar"]) for k, v in LOOKS.items()]
