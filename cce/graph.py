"""Shot Continuity Graph — links shots with invariant/variant fields."""
class ShotContinuityGraph:
    def __init__(self): self.nodes = {}; self.edges = []
    def add(self, shot_id, invariants, variants):
        self.nodes[shot_id] = {"invariants":invariants,"variants":variants}
    def link(self, a, b, reason=""):
        self.edges.append({"from":a,"to":b,"reason":reason})
    def invariants_between(self, a, b):
        return set(self.nodes[a]["invariants"]) & set(self.nodes[b]["invariants"])
    def export(self): return {"nodes":self.nodes,"edges":self.edges}
