from pathlib import Path
from datetime import datetime
import shutil
import sys

p = Path("cinema_trainer.py")
src = p.read_text(encoding="utf-8")
original = src

def replace_exact(old, new, expected=1, label=""):
    global src
    count = src.count(old)
    if count != expected:
        raise RuntimeError(
            f"{label or 'replacement'}: expected {expected} matches, found {count}. No changes written."
        )
    src = src.replace(old, new)

# 1. Invalidate old scan/cache identity without deleting old artifacts.
replace_exact(
    'PREP_VERSION = "prep-1"',
    'PREP_VERSION = "prep-2"',
    1,
    "PREP_VERSION"
)

# 2. Full content SHA-256; stream in bounded memory.
replace_exact(
'''def fingerprint(path, size):
    h = hashlib.sha1(str(size).encode())
    with open(path, "rb") as f:
        for off in (0, max(0, size // 2 - 32768), max(0, size - 65536)):
            f.seek(off); h.update(f.read(65536))
    return h.hexdigest()
''',
'''def fingerprint(path, size=None):
    """Full-file SHA-256, streamed with bounded memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
''',
1,
"fingerprint"
)

# 3. Deterministic, streaming traversal; no symlink directory traversal.
replace_exact(
'''def iter_videos(dirs):
    stack = [str(d) for d in dirs]
    while stack:
        d = stack.pop()
        try: it = os.scandir(d)
        except OSError: continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False): stack.append(e.path)
                    elif os.path.splitext(e.name)[1].lower() in VIDEO_EXT:
                        st = e.stat(); yield e.path, st.st_size, st.st_mtime
                except OSError: continue
''',
'''def iter_videos(dirs):
    """Yield video files in deterministic order without materializing the tree."""
    roots = sorted({os.path.abspath(str(d)) for d in dirs})
    for root in roots:
        for current, subdirs, files in os.walk(root, topdown=True, followlinks=False):
            subdirs[:] = sorted(
                d for d in subdirs
                if not os.path.islink(os.path.join(current, d))
            )
            for name in sorted(files):
                if os.path.splitext(name)[1].lower() not in VIDEO_EXT:
                    continue
                path = os.path.join(current, name)
                try:
                    st = os.stat(path, follow_symlinks=False)
                    if not os.path.isfile(path):
                        continue
                    yield path, st.st_size, st.st_mtime
                except OSError:
                    continue
''',
1,
"iter_videos"
)

# 4. Exact-path assertions; no suffix ambiguity.
replace_exact(
'''    r = scan(cfg, db); st = dict(db.con.execute("SELECT substr(path,-12),status FROM clips").fetchall())
    ok("scan: a.mp4 ok", st.get("/a.mp4") == "ok" or any(k.endswith("a.mp4") and v == "ok" for k, v in st.items()))
    def S(n): return db.con.execute("SELECT status,reason FROM clips WHERE path LIKE ?", (f"%/{n}",)).fetchone()
''',
'''    r = scan(cfg, db)
    def S(n):
        return db.con.execute(
            "SELECT status,reason FROM clips WHERE path=?",
            (str(data / n),)
        ).fetchone()
    ok("scan: a.mp4 ok", S("a.mp4") is not None and S("a.mp4")[0] == "ok")
''',
1,
"selftest exact path"
)

replace_exact(
'''    ok("scan: نسخة طبق الأصل = dup", S("a_copy.mp4")[0] == "dup" or S("a.mp4")[0] == "dup")
''',
'''    ok("scan: الأصل محفوظ والنسخة dup",
       S("a.mp4") is not None and S("a.mp4")[0] == "ok"
       and S("a_copy.mp4") is not None and S("a_copy.mp4")[0] == "dup")
''',
1,
"duplicate assertion"
)

# 5. Remove accidental repeated cleanup, preserving exactly one cleanup block.
cleanup = '''    db.con.execute("DELETE FROM clips WHERE path LIKE '%/a_copy.mp4'")
    db.con.execute("UPDATE clips SET status='ok' WHERE path LIKE '%/a.mp4'")
    db.con.commit()
'''
count = src.count(cleanup)
if count != 8:
    raise RuntimeError(f"selftest cleanup: expected 8 repeated blocks, found {count}. No changes written.")
src = src.replace(cleanup * 8, cleanup, 1)

if src == original:
    raise RuntimeError("No modifications produced.")

backup = p.with_name(
    p.name + ".backup." + datetime.now().strftime("%Y%m%d_%H%M%S")
)
shutil.copy2(p, backup)

try:
    p.write_text(src, encoding="utf-8")
except Exception:
    shutil.copy2(backup, p)
    raise

print("PATCH APPLIED")
print("Backup:", backup)
print("PREP_VERSION: prep-2")
print("Fingerprint: full SHA-256")
print("Traversal: deterministic streaming os.walk")
print("Selftest: exact-path checks; duplicate cleanup reduced from 8 to 1")
