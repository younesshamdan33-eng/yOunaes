"""Worker tests. The fake adapter draws a test pattern: these prove the queue/auth/validation logic, NOT real GPU inference."""
import shutil, threading, time
import pytest
from worker import hardware, models, registry, validate
from worker.adapters import Adapter, Cancelled
from worker.config import Cfg
from worker.server import create_app

ff = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not available")
TOKEN = "t" * 40
H = {"Authorization": "Bearer " + TOKEN}

@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("CW_TOKEN", TOKEN)
    monkeypatch.setenv("CW_ENABLE_FAKE", "1")
    return create_app(Cfg(tmp_path), start_runner=False)

def job(c, **kw):
    body = {"model": "fake-motion", "prompt": "a dog", "seconds": 2}
    body.update(kw)
    return c.post("/v1/jobs", json=body, headers=H)

def test_auth_and_health(app):
    c = app.test_client()
    assert c.get("/v1/health").status_code == 200
    assert c.get("/v1/capabilities").status_code == 401
    assert c.get("/v1/capabilities", headers={"Authorization": "Bearer wrong"}).status_code == 401
    caps = c.get("/v1/capabilities", headers=H).get_json()
    assert caps["models"]["fake-motion"]["ready"] is True
    assert caps["models"]["wan2.2-ti2v-5b"]["ready"] is False and caps["models"]["framepack"]["ready"] is False
    assert TOKEN not in c.get("/v1/capabilities", headers=H).get_data(as_text=True)

def test_short_token_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("CW_TOKEN", "short")
    with pytest.raises(RuntimeError):
        create_app(Cfg(tmp_path), start_runner=False)

def test_request_validation(app):
    c = app.test_client()
    for bad in ({"seconds": 99}, {"aspect_ratio": "4:3"}, {"prompt": " "}, {"steps": 500}, {"task": "i2v"}, {"seed": -1}, {"model": "nope"}):
        assert job(c, **bad).status_code == 400, bad
    r = job(c, model="wan2.2-ti2v-5b")
    assert r.status_code == 409 and any("GPU" in x for x in r.get_json()["reasons"])

def test_model_readiness_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("CW_ENABLE_FAKE", "0")
    cfg = Cfg(tmp_path)
    monkeypatch.setattr(models.hardware, "has_module", lambda n: True)
    gpu = lambda mb: [{"index": 0, "name": "X", "vram_total_mb": mb, "vram_used_mb": 0, "driver": "1"}]
    st = models.status(cfg, gpu(24564))["wan2.2-ti2v-5b"]
    assert not st["ready"] and any("not installed" in r for r in st["reasons"])
    (cfg.models_dir / "wan2.2-ti2v-5b").mkdir(parents=True)
    (cfg.models_dir / "wan2.2-ti2v-5b" / "READY").write_text("{}")
    assert models.status(cfg, gpu(24564))["wan2.2-ti2v-5b"]["ready"] is True
    low = models.status(cfg, gpu(16384))["wan2.2-ti2v-5b"]
    assert not low["ready"] and any("24" in r and "VRAM" in r for r in low["reasons"])
    assert not models.status(cfg, [])["wan2.2-ti2v-5b"]["ready"]
    assert models.status(cfg, gpu(24564))["framepack"]["ready"] is False

def test_frame_counts():
    assert registry.num_frames(registry.MODELS["wan2.2-ti2v-5b"], 5) == 121
    assert registry.num_frames(registry.MODELS["ltx-video"], 5) == 121
    assert registry.num_frames(registry.FAKE, 2) == 24

def test_nvidia_smi_parsing(monkeypatch):
    class R:
        returncode = 0
        stdout = "0, NVIDIA GeForce RTX 4090, 24564, 512, 560.35\n1, Tesla T4, 15360, 0, 535.1\nbad line\n"
    monkeypatch.setattr(hardware.subprocess, "run", lambda *a, **k: R())
    g = hardware.gpus()
    assert [x["name"] for x in g] == ["NVIDIA GeForce RTX 4090", "Tesla T4"] and g[0]["vram_total_mb"] == 24564
    assert hardware.free_vram_gb(g) == pytest.approx(24.05, abs=0.1)

@ff
def test_job_end_to_end_with_validation(app):
    c = app.test_client()
    jid = job(c).get_json()["id"]
    assert app.runner.run_next() is True
    j = c.get("/v1/jobs/" + jid, headers=H).get_json()
    assert j["state"] == "completed" and j["report"]["ok"] and j["report"]["info"]["width"] == 128, j
    assert c.get("/v1/jobs/%s/output" % jid, headers=H).status_code == 200
    assert c.get("/v1/jobs/abc/output", headers=H).status_code == 404

@ff
def test_validator_rejects_static_wrong_size_and_short_files(tmp_path):
    import subprocess
    static = tmp_path / "s.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x3366aa:s=128x72:r=12:d=2", "-pix_fmt", "yuv420p", str(static)], check=True)
    rep = validate.validate(static, {"width": 128, "height": 72, "fps": 12, "num_frames": 24})
    assert not rep["ok"] and any("static" in i for i in rep["issues"])
    moving = tmp_path / "m.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=128x72:rate=12:duration=2", "-pix_fmt", "yuv420p", str(moving)], check=True)
    assert validate.validate(moving, {"width": 128, "height": 72, "fps": 12, "num_frames": 24})["ok"]
    wrong = validate.validate(moving, {"width": 1280, "height": 704, "fps": 24, "num_frames": 121})
    assert not wrong["ok"] and len(wrong["issues"]) >= 2
    junk = tmp_path / "j.mp4"; junk.write_bytes(b"x" * 50000)
    assert not validate.validate(junk, {"width": 128, "height": 72, "fps": 12, "num_frames": 24})["ok"]

def test_oom_is_classified_and_leaves_no_output(app):
    class Oom(Adapter):
        def generate(self, p, out, progress, cancelled):
            out.write_bytes(b"partial")
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
    app.runner.adapters["fake"] = Oom()
    c = app.test_client()
    jid = job(c).get_json()["id"]
    app.runner.run_next()
    j = c.get("/v1/jobs/" + jid, headers=H).get_json()
    assert j["state"] == "failed" and j["error_code"] == "gpu_oom" and not app.store.output(jid).exists()

def test_cancel_queued_and_running_jobs(app):
    class Block(Adapter):
        def generate(self, p, out, progress, cancelled):
            for _ in range(300):
                if cancelled():
                    raise Cancelled()
                time.sleep(0.02)
            raise RuntimeError("was never cancelled")
    app.runner.adapters["fake"] = Block()
    c = app.test_client()
    q = job(c).get_json()["id"]
    assert c.post("/v1/jobs/%s/cancel" % q, json={}, headers=H).get_json()["state"] == "cancelled"
    assert app.runner.run_next() is False
    r = job(c).get_json()["id"]
    t = threading.Thread(target=app.runner.run_next); t.start()
    for _ in range(100):
        if c.get("/v1/jobs/" + r, headers=H).get_json()["state"] == "running":
            break
        time.sleep(0.02)
    assert c.post("/v1/jobs/%s/cancel" % r, json={}, headers=H).status_code == 200
    t.join(10)
    assert c.get("/v1/jobs/" + r, headers=H).get_json()["state"] == "cancelled"
    assert c.post("/v1/jobs/%s/cancel" % r, json={}, headers=H).status_code == 400

def test_recovery_requeues_then_gives_up(app):
    c = app.test_client()
    jid = job(c).get_json()["id"]
    app.store.update(jid, lambda x: x.update(state="running", attempts=1))
    assert app.store.recover() == 1 and app.store.get(jid)["state"] == "queued"
    app.store.update(jid, lambda x: x.update(state="running", attempts=2))
    assert app.store.recover() == 1
    g = app.store.get(jid)
    assert g["state"] == "failed" and g["error_code"] == "worker_restarted"

def test_queue_limit_and_cleanup(app):
    app.cfg.max_queue = 2
    c = app.test_client()
    assert job(c).status_code == 202 and job(c).status_code == 202 and job(c).status_code == 429
    old = app.store.list()[0]["id"]
    app.store.update(old, lambda x: x.update(state="failed", finished=1.0))
    assert app.store.cleanup(1) == 1
