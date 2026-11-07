from pathlib import Path
import sys

p = Path("cinema_trainer.py")
s = p.read_text(encoding="utf-8")

old = '''    @staticmethod
    def _load(p):
        import torch
        return torch.load(p, map_location="cpu", weights_only=False)
'''

new = '''    @staticmethod
    def _load(p):
        try:
            import torch
        except ImportError:
            with open(p, "rb") as f:
                return pickle.load(f)
        return torch.load(p, map_location="cpu", weights_only=False)
'''

if old not in s:
    sys.exit("ERROR: Exact _load function not found. No changes made.")

s = s.replace(old, new, 1)

tmp = p.with_name("cinema_trainer.py.retmp")
tmp.write_text(s, encoding="utf-8")
tmp.replace(p)

print("SUCCESS: Checkpoint loader fixed.")
