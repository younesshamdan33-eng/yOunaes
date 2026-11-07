import math, shutil, struct, wave
from types import SimpleNamespace
import pytest
from cinema_core import config, jobs
from studio import render, runner
from studio.app import create_app
from studio.projects import ProjectStore

ff = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not available")
ALL = {"ffmpeg": True, "ffprobe": True, "libx264": True, "aac": True, "ass": True}

def fake_synth(text, voice, out_path, timeout=60):
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(19200)))

def env(tmp_path, **proj):
    cfg = config.load(tmp_path)
    ps, js = ProjectStore(cfg), jobs.JobStore(cfg)
    base = {"title": "اختبار", "script": "الأولى. الثانية.", "script_lang": "ar", "subtitle_lang": "none",
            "voice": "ar-MA-JamalNeural", "profile": "preview"}
    base.update(proj)
    return cfg, ps, js, ps.create(base)

def test_plan_scenes():
    assert render.plan_scenes("أ.\n\nب") == ["أ.", "ب"]
    assert render.plan_scenes("One. Two! Three?") == ["One.", "Two!", "Three?"]
    assert render.plan_scenes("  ") == []

def test_timed_chunks_cover_duration():
    items = render.timed_chunks("كلمة " * 25, 10.0)
    assert len(items) == 3 and items[0][0] == 0
    assert abs(items[-1][1] - 10.0) < 1e-6
    assert all(a[1] == b[0] or abs(a[1] - b[0]) < 1e-9 for a, b in zip(items, items[1:]))

def test_ass_helpers():
    assert render.ass_time(3661.5) == "1:01:01.50"
    assert render.ass_escape("a{b}\\c\nd") == "a\\{b\\}/c d"
    ass = render.build_ass([(0, 1, "مرحباً")], 426, 240, "ar")
    assert "Noto Naskh Arabic" in ass and "مرحباً" in ass

def test_validation(monkeypatch):
    monkeypatch.setattr(render, "capabilities", lambda: ALL)
    base = {"script": "نص.", "script_lang": "ar", "subtitle_lang": "ar", "voice": "ar-MA-JamalNeural", "profile": "480p"}
    assert render.validate_for_render(base) == ["نص."]
    for bad in ({"script": ""}, {"voice": ""}, {"subtitle_lang": "en"}, {"profile": "8k"}):
        with pytest.raises(render.RenderError):
            render.validate_for_render({**base, **bad})
    monkeypatch.setattr(render, "capabilities", lambda: {**ALL, "ffmpeg": False})
    with pytest.raises(render.RenderError, match="ffmpeg"):
        render.validate_for_render(base)

def test_space_check(tmp_path, monkeypatch):
    cfg = config.load(tmp_path)
    monkeypatch.setattr(render.shutil, "disk_usage", lambda p: SimpleNamespace(free=0, total=1, used=1))
    with pytest.raises(render.RenderError, match="storage"):
        render.check_space(cfg, tmp_path)

def test_cleanup_only_owned_files(tmp_path):
    root = tmp_path / "jobs"; work = root / "j" / "work"; work.mkdir(parents=True)
    (work / "a.mp4").write_text("x"); (work / "sub").mkdir(); (work / "sub" / "k.txt").write_text("k")
    outside = tmp_path / "keep.txt"; outside.write_text("keep"); (work / "link").symlink_to(outside)
    render.cleanup_work(work, root)
    assert not (work / "a.mp4").exists() and (work / "sub" / "k.txt").exists() and outside.exists()
    other = tmp_path / "elsewhere"; other.mkdir(); (other / "f").write_text("f")
    render.cleanup_work(other, root)
    assert (other / "f").exists()

@ff
def test_full_pipeline_mocked_tts(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "synth", fake_synth)
    cfg, ps, js, p = env(tmp_path)
    j = js.create("render", {"project_id": p["id"]}, need_mb=1)
    runner.run_job(cfg, js, ps, j["id"])
    done = js.get(j["id"])
    assert done["state"] == "completed" and done["progress"] == 100, done
    out = cfg.jobs_dir / j["id"] / "output" / "film.mp4"
    assert out.stat().st_size > 0 and not (cfg.jobs_dir / j["id"] / "work").exists()
    assert render.verify_output(out, 2 * (1.2 + render.PAD))["width"] == 426

@ff
def test_pipeline_with_subtitles(tmp_path, monkeypatch):
    if not render.capabilities()["ass"]:
        pytest.skip("ffmpeg has no ass filter")
    monkeypatch.setattr(render, "synth", fake_synth)
    cfg, ps, js, p = env(tmp_path, subtitle_lang="ar")
    j = js.create("render", {"project_id": p["id"]}, need_mb=1)
    runner.run_job(cfg, js, ps, j["id"])
    assert js.get(j["id"])["state"] == "completed", js.get(j["id"])

@ff
def test_tts_failure_fails_job(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(render, "synth", boom)
    cfg, ps, js, p = env(tmp_path)
    j = js.create("render", {"project_id": p["id"]}, need_mb=1)
    runner.run_job(cfg, js, ps, j["id"])
    d = js.get(j["id"])
    assert d["state"] == "failed" and "narration failed" in d["error"]

@ff
def test_cancel_before_work(tmp_path):
    cfg, ps, js, p = env(tmp_path)
    with pytest.raises(render.Cancelled):
        render.render_project(cfg, p, tmp_path / "w", tmp_path / "o", cancelled=lambda: True)

@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path); app.testing = True
    return app.test_client()

def mkp(client, **kw):
    body = {"title": "ف", "script": "نص أول.", "voice": "ar-MA-JamalNeural", "subtitle_lang": "none"}
    body.update(kw)
    return client.post("/api/projects", json=body).get_json()["id"]

def test_render_endpoint_rules(client, monkeypatch):
    monkeypatch.setattr(render, "capabilities", lambda: ALL)
    monkeypatch.setattr(runner, "run_job", lambda *a, **k: None)
    assert client.post(f"/api/projects/{mkp(client, voice='')}/render", json={}).status_code == 400
    pid = mkp(client)
    r = client.post(f"/api/projects/{pid}/render", json={})
    assert r.status_code == 202
    assert client.post(f"/api/projects/{pid}/render", json={}).status_code == 409
    assert client.post("/api/projects/abc/render", json={}).status_code == 404

def test_job_endpoints(client, tmp_path):
    cfg = config.load(tmp_path)
    js = jobs.JobStore(cfg)
    j = js.create("render", {"project_id": "x"}, need_mb=1)
    assert client.get(f"/api/jobs/{j['id']}").get_json()["state"] == "queued"
    assert client.get(f"/api/jobs/{j['id']}/output").status_code == 404
    js.transition(j["id"], "running"); js.transition(j["id"], "completed")
    out = cfg.jobs_dir / j["id"] / "output"
    (out / "film.mp4").write_bytes(b"0123456789")
    r = client.get(f"/api/jobs/{j['id']}/output")
    assert r.status_code == 200 and r.data == b"0123456789"
    j2 = js.create("render", {"project_id": "x"}, need_mb=1)
    assert client.post(f"/api/jobs/{j2['id']}/cancel", json={}).get_json()["state"] == "cancelled"
    for bad in ("abc", "..%2Fx", "0" * 32):
        assert client.get(f"/api/jobs/{bad}").status_code == 404
        assert client.get(f"/api/jobs/{bad}/output").status_code == 404
