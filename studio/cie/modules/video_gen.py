"""Video Generation Intelligence — Adaptive Shot Router + adapter call."""
class VideoGenIntelligence:
    def __init__(self, registry, adapters):
        self.registry = registry; self.adapters = adapters
    def pick(self, shot, available, preferred=None):
        if preferred in available: return preferred
        for m in available:
            if m in self.registry and self.registry[m].get("t2v"): return m
        return available[0] if available else None
    def generate(self, shot, model_key, out_dir):
        return self.adapters.generate(model_key=model_key, prompt=shot.prompt,
                                       duration=shot.duration_sec, shot_id=shot.id, out_dir=out_dir)
