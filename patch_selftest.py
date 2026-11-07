from pathlib import Path
import sys

p = Path("cinema_trainer.py")
s = p.read_text(encoding="utf-8")

old1 = 'ok("ckpt: يحتفظ بـ 2 فقط", len(list((tmp / "ck").glob("ckpt_*.pt"))) == 2)'
new1 = 'ok("ckpt: SAFE RETENTION يحتفظ بجميع النقاط", len(list((tmp / "ck").glob("ckpt_*.pt"))) == 3)'

old2 = '''cache = LatentCache(cfg, db, 2); cache.path(1, 0).write_bytes(b"x" * 1000); cache.add(1, 0, 1000); ok("cache: has", cache.has(1, 0))
    cache.evict(0.0); ok("cache: LRU eviction", not cache.has(1, 0))'''

new2 = '''cache = LatentCache(cfg, db, 2)
    cp = cache.path(1, 0)
    cp.write_bytes(b"x" * 1000)
    atomic_write(str(cp) + ".sha256", sha256_file(cp))
    cache.add(1, 0, 1000)
    db.con.commit()
    ok("cache: checksum validation", cache.has(1, 0))
    cache.evict(0.0)
    ok("cache: SAFE RETENTION prevents eviction", cache.has(1, 0))'''

if old1 not in s:
    sys.exit("ERROR: checkpoint selftest assertion not found; no changes made.")

if old2 not in s:
    sys.exit("ERROR: cache selftest block not found; no changes made.")

s = s.replace(old1, new1, 1)
s = s.replace(old2, new2, 1)

tmp = p.with_name("cinema_trainer.py.selftesttmp")
tmp.write_text(s, encoding="utf-8")
tmp.replace(p)

print("SELFTEST EXPECTATIONS UPDATED")
