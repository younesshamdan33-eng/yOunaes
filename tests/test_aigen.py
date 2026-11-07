"""All tests here are MOCKED (no network, no credits). They are NOT proof of real AI generation;
the real proof is studio/live_test.py."""
import io, json, shutil, subprocess, urllib.error
import pytest
from cinema_core import config, jobs
from studio import magichour as mh
from studio.app import create_app

ff = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not available")
P = {"prompt": "a dog running", "model": "ltx-2.5", "seconds": 2, "resolution": "480p", "aspect_ratio": "16:9", "audio": False}
DONE = {"status": "complete", "downloads": [{"url": "https://x.example/y.mp4", "expires_at": "z"}]}

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv(mh.ENV_KEY, raising=False)
    app = create_app(tmp_path); app.testing = True
    return app.test_client()

def test_mocked_status_hides_key(client, monkeypatch):
    assert client.get("/api/ai/status").get_json()["configured"] is False
    monkeypatch.setenv(mh.ENV_KEY, "mhk_test_SECRET")
    r = client.get("/api/ai/status")
    assert r.get_json()["configured"] is True and "SECRET" not in r.get_data(as_text=True)

def test_mocked_generate_rules(client, monkeypatch):
    monkeypatch.setattr(mh, "run_job", lambda *a, **k: None)
    body = {"prompt": "a dog running", "seconds": 3, "confirm_cost": True}
    assert client.post("/api/ai/generate", json=body).status_code == 503
    monkeypatch.setenv(mh.ENV_KEY, "k")
    assert client.post("/api/ai/generate", json={**body, "confirm_cost": False}).status_code == 400
    assert client.post("/api/ai/generate", json={**body, "seconds": 99}).status_code == 400
    assert client.post("/api/ai/generate", json={**body, "model": "nope"}).status_code == 400
    assert client.post("/api/ai/generate", json={**body, "prompt": "  "}).status_code == 400
    r = client.post("/api/ai/generate", json=body)
    assert r.status_code == 202 and r.get_json()["kind"] == "aigen"
    assert client.post("/api/ai/generate", json=body).status_code == 409

def test_mocked_daily_limit(monkeypatch):
    monkeypatch.setenv(mh.DAILY_ENV, "1")
    old = [{"kind": "aigen", "state": "completed", "created": 1000}]
    assert mh.guard(old, now=1500)[0] == 429
    assert mh.guard(old, now=1000 + 86401) is None

def _http(code, payload):
    def fake(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(json.dumps(payload).encode()))
    return fake

@pytest.mark.parametrize("code,payload,err,retry", [
    (401, {"code": "unauthorized", "message": "bad"}, "unauthorized", False),
    (402, {"code": "insufficient_credits", "message": "no credits"}, "insufficient_credits", False),
    (500, {"code": "internal_server_error", "message": "x"}, "internal_server_error", True)])
def test_mocked_http_errors(monkeypatch, code, payload, err, retry):
    monkeypatch.setenv(mh.ENV_KEY, "k")
    monkeypatch.setattr(mh.urllib.request, "urlopen", _http(code, payload))
    with pytest.raises(mh.MagicHourError) as e:
        mh.fetch("abc123")
    assert e.value.code == err and e.value.retryable is retry

def test_mocked_network_and_missing_key(monkeypatch):
    monkeypatch.delenv(mh.ENV_KEY, raising=False)
    with pytest.raises(mh.MagicHourError) as e:
        mh.fetch("abc")
    assert e.value.code == "not_configured"
    monkeypatch.setenv(mh.ENV_KEY, "k")
    def boom(req, timeout=0):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(mh.urllib.request, "urlopen", boom)
    with pytest.raises(mh.MagicHourError) as e:
        mh.fetch("abc")
    assert e.value.code == "network" and e.value.retryable

def mkvideo(path, secs=2):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x96:rate=10:duration=%d" % secs,
                    "-pix_fmt", "yuv420p", str(path)], check=True, timeout=120)

def setup(tmp_path, monkeypatch, seq):
    cfg = config.load(tmp_path); js = jobs.JobStore(cfg)
    monkeypatch.setattr(mh, "submit", lambda p: {"id": "abc123", "credits_charged": 1})
    it = iter(seq)
    monkeypatch.setattr(mh, "fetch", lambda pid: next(it))
    return cfg, js, js.create("aigen", dict(P), need_mb=1)

@ff
def test_mocked_pipeline_ok_and_served(tmp_path, monkeypatch):
    src = tmp_path / "src.mp4"; mkvideo(src)
    cfg, js, j = setup(tmp_path, monkeypatch, [{"status": "queued"}, {"status": "rendering"}, DONE])
    monkeypatch.setattr(mh, "download", lambda url, dest, cancelled=None: shutil.copy(src, dest))
    mh.run_job(cfg, js, j["id"], sleep=lambda s: None)
    d = js.get(j["id"])
    assert d["state"] == "completed" and d["progress"] == 100, d
    app = create_app(tmp_path); app.testing = True
    r = app.test_client().get("/api/jobs/%s/output" % j["id"])
    assert r.status_code == 200 and r.data == src.read_bytes()

@ff
def test_mocked_transient_poll_error_is_retried(tmp_path, monkeypatch):
    src = tmp_path / "src.mp4"; mkvideo(src)
    cfg, js, j = setup(tmp_path, monkeypatch, [])
    calls = {"n": 0}
    def flaky(pid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise mh.MagicHourError("network", "down", retryable=True)
        return DONE
    monkeypatch.setattr(mh, "fetch", flaky)
    monkeypatch.setattr(mh, "download", lambda url, dest, cancelled=None: shutil.copy(src, dest))
    mh.run_job(cfg, js, j["id"], sleep=lambda s: None)
    assert js.get(j["id"])["state"] == "completed"

def test_mocked_provider_error_fails_job(tmp_path, monkeypatch):
    cfg, js, j = setup(tmp_path, monkeypatch, [{"status": "error", "error": {"code": "bad", "message": "prompt rejected"}}])
    mh.run_job(cfg, js, j["id"], sleep=lambda s: None)
    d = js.get(j["id"])
    assert d["state"] == "failed" and "prompt rejected" in d["error"]

def test_mocked_no_download_url_fails(tmp_path, monkeypatch):
    cfg, js, j = setup(tmp_path, monkeypatch, [{"status": "complete", "downloads": []}])
    mh.run_job(cfg, js, j["id"], sleep=lambda s: None)
    d = js.get(j["id"])
    assert d["state"] == "failed" and "no_output" in d["error"]

def test_mocked_timeout(tmp_path, monkeypatch):
    cfg, js, j = setup(tmp_path, monkeypatch, [])
    monkeypatch.setattr(mh, "fetch", lambda pid: {"status": "rendering"})
    ticks = iter(range(0, 10 ** 7, 1000))
    mh.run_job(cfg, js, j["id"], sleep=lambda s: None, now=lambda: next(ticks))
    d = js.get(j["id"])
    assert d["state"] == "failed" and "timeout" in d["error"]

@ff
def test_mocked_invalid_video_is_rejected(tmp_path, monkeypatch):
    cfg, js, j = setup(tmp_path, monkeypatch, [DONE])
    monkeypatch.setattr(mh, "download", lambda url, dest, cancelled=None: open(dest, "wb").write(b"x" * 5000))
    mh.run_job(cfg, js, j["id"], sleep=lambda s: None)
    d = js.get(j["id"])
    assert d["state"] == "failed" and "invalid_output" in d["error"]
    assert not (cfg.jobs_dir / j["id"] / "output" / "film.mp4").exists()

def test_mocked_local_cancel_stops_polling(tmp_path, monkeypatch):
    cfg, js, j = setup(tmp_path, monkeypatch, [])
    def f(pid):
        js.cancel(j["id"])
        return {"status": "rendering"}
    monkeypatch.setattr(mh, "fetch", f)
    mh.run_job(cfg, js, j["id"], sleep=lambda s: None)
    assert js.get(j["id"])["state"] == "cancelled"
