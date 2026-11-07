"""Adaptive Shot Router — picks model by shot constraints + available workers."""
class AdaptiveShotRouter:
    def __init__(self, registry, available_models, workers):
        self.registry = registry; self.available = available_models; self.workers = workers
    def route(self, shot):
        cands = [m for m in self.available if m in self.registry]
        cands = [m for m in cands if self.registry[m].get("ready")]
        if not cands: return None
        # prefer higher-resolution for close-ups, t2v for wide
        if "close" in shot.camera: cands.sort(key=lambda m: -self.registry[m].get("width",480))
        return cands[0]
