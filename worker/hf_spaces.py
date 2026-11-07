"""Verified HF Spaces for real video generation. Each entry tested individually."""
SPACES = {
    "ltx-distilled": {
        "space": "Lightricks/ltx-video-distilled",
        "durations": (0.3, 8.5), "fps": 24,
        "resolutions": [(704, 480), (512, 512), (480, 704), (768, 512)],
        "modes": ["text-to-video", "image-to-video"],
        "notes": "Fast, cinematic. Default choice."
    },
    "wan22-ti2v": {
        "space": "vaibhavpandeyvpz/wan2.2-text-image-to-video",
        "durations": (0.3, 5.0), "fps": 24,
        "resolutions": [(704, 480), (480, 704), (512, 512)],
        "modes": ["text-to-video", "image-to-video"],
        "notes": "Full parameter control, 5B model."
    },
}
def pick_best():
    """Return (key, spec) — prefer LTX for speed."""
    return ("ltx-distilled", SPACES["ltx-distilled"])
