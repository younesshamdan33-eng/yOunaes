"""Anchor Frames — reference images for continuity."""
import shutil
from pathlib import Path
class AnchorFrames:
    def __init__(self, root: Path):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.index = {}
    def register(self, key, image_path):
        src = Path(image_path)
        if not src.exists(): return None
        dst = self.root / f"{key}{src.suffix}"
        shutil.copy(src, dst); self.index[key] = str(dst); return str(dst)
    def get(self, key): return self.index.get(key)
