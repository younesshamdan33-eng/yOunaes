import json, threading
from pathlib import Path

class Stats:
    """Project-level outcome counters per engine. This tunes routing only; it never changes model weights."""
    def __init__(self, path):
        self.path, self.lock = Path(path), threading.Lock()
    def _load(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
    def record(self, key, ok):
        with self.lock:
            d = self._load()
            e = d.setdefault(key, {"ok": 0, "fail": 0})
            e["ok" if ok else "fail"] += 1
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(d))
            tmp.replace(self.path)
    def rate(self, key):
        e = self._load().get(key)
        return 0.5 if not e else (e["ok"] + 1) / (e["ok"] + e["fail"] + 2)
