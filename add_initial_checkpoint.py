from pathlib import Path
import sys

p = Path("cinema_trainer.py")
s = p.read_text(encoding="utf-8")

old = '''        p = cm.save(step, payload); log.info("checkpoint %s %s", p.name, tag); return payload
    reason = "max_steps"; bad = 0; tr.train()
'''

new = '''        p = cm.save(step, payload); log.info("checkpoint %s %s", p.name, tag); return payload

    if pl is None:
        save("initial")

    reason = "max_steps"; bad = 0; tr.train()
'''

count = s.count(old)
if count != 1:
    sys.exit(f"ERROR: expected exactly 1 insertion point, found {count}. No changes made.")

tmp = p.with_name("cinema_trainer.py.retmp")
tmp.write_text(s.replace(old, new, 1), encoding="utf-8")
tmp.replace(p)

print("PATCH APPLIED: initial step-0 checkpoint")
