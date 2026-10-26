import json, os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(os.environ.get("CINEMA_ROOT") or Path(__file__).resolve().parent.parent)
ALLOWED = {"host", "port", "min_free_mb"}

class ConfigError(ValueError):
    pass

@dataclass(frozen=True)
class Config:
    root: Path
    host: str = "127.0.0.1"
    port: int = 8750
    min_free_mb: int = 300
    start_timeout: float = 15.0
    stop_timeout: float = 10.0
    @property
    def run_dir(self): return self.root / "var" / "run"
    @property
    def log_dir(self): return self.root / "var" / "logs"
    @property
    def pid_file(self): return self.run_dir / "cinema.pid"

def load(root=None):
    root = Path(root or ROOT)
    raw = {}
    f = root / "cinema.json"
    if f.exists():
        try:
            raw = json.loads(f.read_text())
        except (OSError, ValueError) as e:
            raise ConfigError(f"cinema.json unreadable: {e}")
        if not isinstance(raw, dict):
            raise ConfigError("cinema.json must be a JSON object")
    bad = set(raw) - ALLOWED
    if bad:
        raise ConfigError(f"unknown keys: {sorted(bad)}")
    c = Config(root=root, **raw)
    if c.host not in ("127.0.0.1", "localhost"):
        raise ConfigError("host must be 127.0.0.1 or localhost (public access is not enabled in this core)")
    if isinstance(c.port, bool) or not isinstance(c.port, int) or not 1024 <= c.port <= 65535:
        raise ConfigError("port must be an integer between 1024 and 65535")
    if isinstance(c.min_free_mb, bool) or not isinstance(c.min_free_mb, int) or c.min_free_mb < 0:
        raise ConfigError("min_free_mb must be a non-negative integer")
    return c
