from pathlib import Path
import sys

p = Path("cinema_trainer.py")
s = p.read_text(encoding="utf-8")

old = '''    @staticmethod
    def _step_number(path):
        m = re.search(r"ckpt_(\\d+)\\.pt$", Path(path).name)
        return int(m.group(1)) if m else -1
'''

new = '''    @staticmethod
    def _step_number(path):
        name = Path(path).name
        prefix = "ckpt_"
        suffix = ".pt"
        if not name.startswith(prefix) or not name.endswith(suffix):
            return -1
        number = name[len(prefix):-len(suffix)]
        return int(number) if number.isdigit() else -1
'''

if old not in s:
    sys.exit("ERROR: Exact _step_number function not found. No changes made.")

s = s.replace(old, new, 1)
tmp = p.with_name("cinema_trainer.py.retmp")
tmp.write_text(s, encoding="utf-8")
tmp.replace(p)

print("FIX APPLIED: _step_number no longer depends on re")
