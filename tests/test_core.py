import json, socket
import pytest
from cinema_core import config, lifecycle

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "cinema.json").write_text(json.dumps({"port": free_port()}))
    c = config.load(tmp_path)
    yield c
    lifecycle.stop(c)

def test_defaults(tmp_path):
    c = config.load(tmp_path)
    assert c.host == "127.0.0.1"

@pytest.mark.parametrize("bad", [{"host": "0.0.0.0"}, {"port": 80}, {"port": "x"}, {"min_free_mb": -1}, {"nope": 1}])
def test_invalid_config(tmp_path, bad):
    (tmp_path / "cinema.json").write_text(json.dumps(bad))
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)

def test_start_health_duplicate_stop(cfg):
    code, _ = lifecycle.start(cfg)
    assert code == 0
    assert lifecycle.health(cfg)["status"] == "ok"
    code, msg = lifecycle.start(cfg)
    assert code == 0 and "already running" in msg
    assert lifecycle.status(cfg)["running"]
    assert lifecycle.stop(cfg)[0] == 0
    assert lifecycle.health(cfg) is None
    assert not cfg.pid_file.exists()

def test_stale_pid(cfg):
    cfg.run_dir.mkdir(parents=True)
    cfg.pid_file.write_text("999999")
    assert not lifecycle.status(cfg)["running"]
    assert lifecycle.start(cfg)[0] == 0
