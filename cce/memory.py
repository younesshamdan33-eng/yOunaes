"""Film Memory — persists identity/state across shots."""
import json
from pathlib import Path
class FilmMemory:
    def __init__(self, root: Path):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.file = self.root / "memory.json"
        self.data = json.loads(self.file.read_text()) if self.file.exists() else {"characters":{},"locations":{},"events":[]}
    def save(self): self.file.write_text(json.dumps(self.data, indent=2))
    def set_character(self, h, state): self.data["characters"][h] = state; self.save()
    def get_character(self, h): return self.data["characters"].get(h)
    def set_location(self, k, state): self.data["locations"][k] = state; self.save()
    def log_event(self, ev): self.data["events"].append(ev); self.save()
