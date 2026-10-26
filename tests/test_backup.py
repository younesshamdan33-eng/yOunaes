import hashlib, io, json, tarfile
import pytest
from cinema_core import config, backup

def mk(tmp_path):
    (tmp_path / "app.py").write_text("print(1)")
    (tmp_path / ".env").write_text("KEY=1")
    (tmp_path / "clip.mp4").write_bytes(b"x")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "x.py").write_text("v")
    return config.load(tmp_path)

def craft(path, members, manifest):
    with tarfile.open(path, "w:gz") as tf:
        for name, data in members.items():
            ti = tarfile.TarInfo(name); ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        d = json.dumps(manifest).encode()
        ti = tarfile.TarInfo("MANIFEST.json"); ti.size = len(d)
        tf.addfile(ti, io.BytesIO(d))

def test_create_excludes(tmp_path):
    cfg = mk(tmp_path)
    path, _ = backup.create(cfg)
    with tarfile.open(path) as tf:
        assert set(tf.getnames()) == {"app.py", "MANIFEST.json"}

def test_roundtrip_and_overwrite_guard(tmp_path):
    cfg = mk(tmp_path)
    path, _ = backup.create(cfg)
    (tmp_path / "app.py").write_text("changed")
    code, _ = backup.restore(cfg, path)
    assert code == 1 and (tmp_path / "app.py").read_text() == "changed"
    code, _ = backup.restore(cfg, path, yes=True)
    assert code == 0 and (tmp_path / "app.py").read_text() == "print(1)"

def test_rejects_traversal(tmp_path):
    cfg = mk(tmp_path)
    bad = tmp_path / "bad.tar.gz"
    craft(bad, {"../evil.txt": b"x"}, {"../evil.txt": {"sha256": hashlib.sha256(b"x").hexdigest(), "size": 1}})
    with pytest.raises(backup.BackupError):
        backup.restore(cfg, bad)
    assert not (tmp_path.parent / "evil.txt").exists()

def test_detects_tamper(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    craft(bad, {"a.txt": b"x"}, {"a.txt": {"sha256": "0" * 64, "size": 1}})
    with pytest.raises(backup.BackupError):
        backup.verify(bad)
