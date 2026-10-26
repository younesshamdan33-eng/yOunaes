import json, socket, sys
import pytest
from cinema_core import config, lifecycle, tunnel

FAKE = ("import sys, time\n"
        "print('boot', flush=True)\n"
        "print('x https://api.trycloudflare.com/t y https://fake-test.trycloudflare.com z', file=sys.stderr, flush=True)\n"
        "time.sleep(60)\n")

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "cinema.json").write_text(json.dumps({"port": free_port()}))
    c = config.load(tmp_path)
    yield c
    tunnel.offline(c)
    lifecycle.stop(c)

def test_requires_server(cfg):
    code, msg = tunnel.online(cfg, True)
    assert code == 1 and "not running" in msg

def test_requires_confirmation(cfg, monkeypatch):
    monkeypatch.setattr(tunnel, "_binary", lambda: ["unused"])
    assert lifecycle.start(cfg)[0] == 0
    code, msg = tunnel.online(cfg, False)
    assert code == 1 and "PUBLIC ACCESS" in msg
    assert not (cfg.run_dir / "tunnel.pid").exists()

def test_missing_binary(cfg, monkeypatch):
    monkeypatch.setattr(tunnel, "_binary", lambda: None)
    lifecycle.start(cfg)
    code, msg = tunnel.online(cfg, True)
    assert code == 1 and "not found" in msg

def test_online_offline_cycle(cfg, tmp_path, monkeypatch):
    fake = tmp_path / "cloudflared.py"
    fake.write_text(FAKE)
    monkeypatch.setattr(tunnel, "_binary", lambda: [sys.executable, str(fake)])
    assert lifecycle.start(cfg)[0] == 0
    code, msg = tunnel.online(cfg, True)
    assert code == 0 and "fake-test.trycloudflare.com" in msg and "api.trycloudflare" not in msg
    assert "already online" in tunnel.online(cfg, True)[1]
    assert tunnel.offline(cfg)[0] == 0
    assert tunnel._state(cfg)[2] == "none"

def test_offline_when_nothing(cfg):
    assert tunnel.offline(cfg) == (0, "not online")
