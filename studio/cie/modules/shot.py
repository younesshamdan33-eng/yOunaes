"""Shot Intelligence — scene → shots with camera specs."""
from dataclasses import dataclass
@dataclass
class Shot:
    id: str; scene_id: str; duration_sec: float
    camera: str; movement: str; description: str; prompt: str

class ShotIntelligence:
    def plan(self, scene, scene_build, direction, default_duration=5.0):
        n = max(1, int(round(scene.duration_seconds / default_duration)))
        out = []
        for i in range(n):
            out.append(Shot(f"{scene.id}_S{i+1:02d}", scene.id, default_duration,
                            "wide" if i==0 else "medium",
                            "slow push-in" if i==0 else "static",
                            scene.summary,
                            f'{scene_build["env_prompt"]}, {scene.summary}, {direction["camera"]}'))
        return out
