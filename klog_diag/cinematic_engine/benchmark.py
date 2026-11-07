import json
from config import CinematicConfig
from pipeline import run_cinematic_engine
BENCHMARKS = [
    {"name": "city_night_walk", "prompt": "A person walking alone in a modern city at night, neon reflections on wet pavement"},
    {"name": "dramatic_interior", "prompt": "A tense conversation in a dimly lit room, single window light"},
    {"name": "forest_nature", "prompt": "Sunlight filtering through a dense green forest, mist between trees"},
    {"name": "ocean_waves", "prompt": "Powerful ocean waves crashing on rocky shore, golden hour"},
    {"name": "car_chase", "prompt": "High-speed car chase on a coastal highway, motion blur"},
    {"name": "orbit_character", "prompt": "Orbit shot around a warrior standing in a battlefield"},
    {"name": "talking_head", "prompt": "A scientist speaking directly to camera in a laboratory"},
    {"name": "detailed_clothing", "prompt": "Close-up of intricate embroidered silk clothing, rich textures"},
    {"name": "rain_fog", "prompt": "Heavy rain and thick fog in a Victorian street, gas lamps glowing"},
    {"name": "wide_city", "prompt": "Aerial establishing shot of a futuristic megacity at dusk"}
]
if __name__ == "__main__":
    results = []
    for b in BENCHMARKS:
        cfg = CinematicConfig(seed=42, look="natural", lighting="natural", shot_type="medium", camera_motion="static")
        try:
            path = run_cinematic_engine(b["prompt"], cfg, output_name=f"bench_{b['name']}")
            results.append({"name": b["name"], "output": path, "status": "ok"})
        except Exception as e:
            results.append({"name": b["name"], "error": str(e), "status": "failed"})
    with open("./outputs/benchmark_report.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("Done. Report saved.")
