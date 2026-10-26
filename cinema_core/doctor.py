import importlib.util, shutil, sys
from pathlib import Path

def run(cfg):
    r = []
    r.append(("python", sys.version_info >= (3, 9), sys.version.split()[0]))
    r.append(("venv", sys.prefix != sys.base_prefix, sys.prefix))
    for mod in ("flask", "edge_tts", "pytest"):
        r.append((mod, importlib.util.find_spec(mod) is not None, "installed" if importlib.util.find_spec(mod) else "missing"))
    ff = shutil.which("ffmpeg")
    r.append(("ffmpeg", bool(ff), ff or "missing"))
    try:
        free = shutil.disk_usage(cfg.root).free // (1024 * 1024)
        r.append(("disk", free >= cfg.min_free_mb, f"{free} MB free (min {cfg.min_free_mb})"))
    except OSError as e:
        r.append(("disk", False, f"unavailable: {e}"))
    r.append(("config", True, f"{cfg.host}:{cfg.port}"))
    return r
