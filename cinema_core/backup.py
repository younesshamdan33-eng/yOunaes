import hashlib, io, json, os, shutil, tarfile, time
from pathlib import Path, PurePosixPath

EXCL_DIRS = {".venv", ".git", "var", "__pycache__", ".pytest_cache", "node_modules"}
EXCL_EXT = {".mp4", ".mkv", ".mov", ".avi", ".mp3", ".wav", ".m4a",
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pyc"}
SECRET_HINTS = ("secret", "token", "password", "credential")

class BackupError(Exception):
    pass

def _secret(p):
    n = p.name.lower()
    return n.startswith(".env") or p.suffix.lower() in (".key", ".pem") or any(h in n for h in SECRET_HINTS)

def _files(root):
    for d, dirs, names in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in EXCL_DIRS)
        for n in sorted(names):
            p = Path(d) / n
            if p.is_symlink() or not p.is_file() or p.suffix.lower() in EXCL_EXT or _secret(p):
                continue
            yield p

def _sha(f):
    h = hashlib.sha256()
    for chunk in iter(lambda: f.read(65536), b""):
        h.update(chunk)
    return h.hexdigest()

def _safe(name):
    pp = PurePosixPath(name)
    return bool(name) and not pp.is_absolute() and ".." not in pp.parts and "\\" not in name

def create(cfg):
    root = cfg.root
    files = list(_files(root))
    size_mb = sum(p.stat().st_size for p in files) // (1024 * 1024)
    free_mb = shutil.disk_usage(root).free // (1024 * 1024)
    if free_mb - size_mb < cfg.min_free_mb:
        raise BackupError(f"not enough free space ({free_mb} MB free, need {size_mb} MB + {cfg.min_free_mb} MB reserve)")
    cfg.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    final, i = cfg.backup_dir / f"cinema-{stamp}.tar.gz", 0
    while final.exists():
        i += 1
        final = cfg.backup_dir / f"cinema-{stamp}-{i}.tar.gz"
    tmp = final.with_name(final.name + ".part")
    manifest = {}
    try:
        with tarfile.open(tmp, "w:gz") as tf:
            for p in files:
                rel = p.relative_to(root).as_posix()
                with open(p, "rb") as f:
                    manifest[rel] = {"sha256": _sha(f), "size": p.stat().st_size}
                tf.add(p, arcname=rel, recursive=False)
            data = json.dumps(manifest, indent=1).encode()
            ti = tarfile.TarInfo("MANIFEST.json")
            ti.size, ti.mtime = len(data), time.time()
            tf.addfile(ti, io.BytesIO(data))
        tmp.replace(final)
    finally:
        if tmp.exists():
            tmp.unlink()
    verify(final)
    return final, len(files)

def verify(path):
    try:
        with tarfile.open(path, "r:gz") as tf:
            members = {m.name: m for m in tf.getmembers()}
            if "MANIFEST.json" not in members:
                raise BackupError("archive has no manifest")
            manifest = json.load(tf.extractfile("MANIFEST.json"))
            for name, m in members.items():
                if name != "MANIFEST.json" and (not m.isreg() or not _safe(name)):
                    raise BackupError(f"unsafe member: {name}")
            if set(manifest) != set(members) - {"MANIFEST.json"}:
                raise BackupError("manifest does not match archive contents")
            for name, info in manifest.items():
                with tf.extractfile(members[name]) as f:
                    if _sha(f) != info["sha256"]:
                        raise BackupError(f"hash mismatch: {name}")
            return manifest
    except (tarfile.TarError, OSError, ValueError, KeyError, TypeError) as e:
        raise BackupError(f"invalid archive: {e}")

def restore(cfg, path, yes=False):
    path = Path(path)
    manifest = verify(path)
    root = cfg.root.resolve()
    conflicts = []
    for rel, info in manifest.items():
        t = (root / rel).resolve()
        if root not in t.parents:
            raise BackupError(f"path escapes project: {rel}")
        if t.exists():
            if not t.is_file():
                raise BackupError(f"not a regular file: {rel}")
            with open(t, "rb") as f:
                if _sha(f) != info["sha256"]:
                    conflicts.append(rel)
    if conflicts and not yes:
        return 1, (f"WARNING: restore would overwrite {len(conflicts)} changed file(s):\n  "
                   + "\n  ".join(conflicts[:20])
                   + "\nRe-run with --yes to proceed (a safety backup is taken first).")
    if conflicts:
        safety, _ = create(cfg)
        print(f"safety backup: {safety}")
    with tarfile.open(path, "r:gz") as tf:
        for rel in manifest:
            t = root / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            tmp = t.with_name(t.name + ".restore.tmp")
            with tf.extractfile(rel) as s, open(tmp, "wb") as d:
                shutil.copyfileobj(s, d)
            os.chmod(tmp, tf.getmember(rel).mode & 0o777)
            tmp.replace(t)
    return 0, f"restored {len(manifest)} files ({len(conflicts)} overwritten)"
