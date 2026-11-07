"""MOCKED tests: fake provider + synthetic clips. No network, no credits.
They prove the engine's logic, NOT that a real provider works (that is studio/live_test.py)."""
import shutil, subprocess
import pytest
from cinema_core import config
from studio import film, providers, magichour as mh
from studio.app import create_app
from studio.providers import ProviderError

ff = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not available")

class Fake(providers.Provider):
    name, label = "fake", "Fake"
    def __init__(self, clip=None, rate=24):
        self.clip, self.rate, self.submits, self.fail = clip, rate, [], {}
        self.polls, self.on_poll, self.poll_state = 0, None, "complete"
    def configured(self): return True
    def models(self): return {"m": {}}
    def validate(self, req):
        if req.get("model") != "m" or req.get("seconds") not in (2, 3, 4, 5) or req.get("resolution") != "480p" or req.get("aspect_ratio") != "16:9":
            raise ProviderError("invalid_request", "unsupported settings")
        return req
    def estimate_credits(self, req): return self.rate * req["seconds"]
    def submit(self, req):
        self.submits.append(req["prompt"])
        q = self.fail.get(req["prompt"])
        if q:
            raise q.pop(0)
        return {"id": "job%d" % len(self.submits), "credits": self.rate * req["seconds"]}
    def poll(self, pid):
        self.polls += 1
        if self.on_poll:
            self.on_poll(pid)
        return {"state": self.poll_state, "url": "https://x.example/c.mp4", "error": None}
    def download(self, url, dest, cancelled=lambda: False):
        shutil.copy(self.clip, dest)

def mkclip(path):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x96:rate=10:duration=2",
                    "-pix_fmt", "yuv420p", str(path)], check=True, timeout=120)

def spec(**kw):
    d = {"title": "T", "provider": "fake", "model": "m", "resolution": "480p", "aspect_ratio": "16:9", "shot_seconds": 2,
         "scenes": ["A woman walks.", "A man waves.", "A dog runs."]}
    d.update(kw)
    return d

@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = config.load(tmp_path)
    st = film.FilmStore(cfg)
    fake = Fake(tmp_path / "clip.mp4")
    monkeypatch.setitem(providers.REGISTRY, "fake", fake)
    clock = [1000.0]
    fr = film.FilmRunner(cfg, st, sleep=lambda s: None, now=lambda: clock[0])
    fr.wait_tries = 1
    return dict(cfg=cfg, st=st, fake=fake, fr=fr, clock=clock, clip=tmp_path / "clip.mp4")

def go(env, extra=None, daily=10 ** 6, total=None, auto=False):
    f = film.create(env["st"], spec(**(extra or {})))
    film.arm(env["st"], f["id"], True, daily, total, auto)
    env["fr"].run(f["id"])
    return env["st"].get(f["id"])

def states(f):
    return [s["state"] for sc in f["scenes"] for s in sc["shots"]]

def test_plan_long_film(env):
    f = film.plan_film(spec(target_seconds=1200, shot_seconds=5, scenes=["a", "b", "c", "d"]))
    shots = [s for sc in f["scenes"] for s in sc["shots"]]
    assert len(f["scenes"]) == 4 and len(shots) == 240 and sum(s["seconds"] for s in shots) == 1200
    assert all(len(s["prompt"]) <= 2000 for s in shots)
    assert film.summary(f)["seconds_total"] == 1200

@pytest.mark.parametrize("bad", [{"shot_seconds": 9}, {"model": "zzz"}, {"provider": "nope"}, {"title": " "}, {"scenes": []},
                                 {"target_seconds": 7200}, {"target_seconds": 1}, {"fps": 5}])
def test_plan_rejects_bad_input(env, bad):
    with pytest.raises(film.FilmError):
        film.plan_film(spec(**bad))

def test_arm_requires_confirmation_and_cap(env):
    f = film.create(env["st"], spec())
    for args in ((None, 100, None), (True, None, None), (True, 0, None), (True, "100", None)):
        with pytest.raises(film.FilmError):
            film.arm(env["st"], f["id"], *args)
    assert env["st"].get(f["id"])["state"] == "draft"

@ff
def test_generate_and_assemble(env):
    mkclip(env["clip"])
    f = go(env, {"target_seconds": 12})
    assert f["state"] == "generated" and film.summary(f)["by_state"] == {"completed": 6}
    assert len(env["fake"].submits) == 6 and f["credits_spent"] == 6 * 48
    assert env["st"].spent(86400, 1000.0) == 6 * 48
    film.assemble(env["cfg"], env["st"], f["id"])
    g = env["st"].get(f["id"])
    assert g["state"] == "assembled" and g["output"]["media"]["duration"] == pytest.approx(12, abs=1.5)
    assert not (env["st"].path(f["id"]) / "work").exists()

@ff
def test_failed_shot_does_not_regenerate_others(env):
    mkclip(env["clip"])
    f0 = film.create(env["st"], spec())
    bad = f0["scenes"][1]["shots"][0]
    env["fake"].fail[bad["prompt"]] = [ProviderError("content_rejected", "prompt rejected")]
    film.arm(env["st"], f0["id"], True, 10 ** 6, None)
    env["fr"].run(f0["id"])
    f = env["st"].get(f0["id"])
    assert f["state"] == "failed" and states(f) == ["completed", "failed", "completed"]
    n = len(env["fake"].submits)
    film.retry_shot(env["st"], f["id"], bad["id"], confirm_cost=True)
    film.resume(env["st"], f["id"])
    env["fr"].run(f["id"])
    f = env["st"].get(f["id"])
    assert f["state"] == "generated" and len(env["fake"].submits) == n + 1

def test_fatal_error_stops_film(env):
    f0 = film.create(env["st"], spec())
    env["fake"].fail[f0["scenes"][0]["shots"][0]["prompt"]] = [ProviderError("plan_upgrade_required", "not on your plan")]
    film.arm(env["st"], f0["id"], True, 10 ** 6, None)
    env["fr"].run(f0["id"])
    f = env["st"].get(f0["id"])
    assert f["state"] == "failed" and "plan_upgrade_required" in f["error"] and len(env["fake"].submits) == 1

def test_ambiguous_submit_is_never_auto_retried(env):
    f0 = film.create(env["st"], spec())
    first = f0["scenes"][0]["shots"][0]
    env["fake"].fail[first["prompt"]] = [ProviderError("network", "timeout", retryable=True, ambiguous=True)]
    film.arm(env["st"], f0["id"], True, 10 ** 6, None)
    env["fr"].run(f0["id"])
    f = env["st"].get(f0["id"])
    s = f["scenes"][0]["shots"][0]
    assert len(env["fake"].submits) == 1 and s["state"] == "failed" and s["ambiguous"] and f["state"] == "interrupted"
    with pytest.raises(film.FilmError):
        film.retry_shot(env["st"], f["id"], first["id"], confirm_cost=True)

@ff
def test_rate_limit_is_retried_with_backoff(env):
    mkclip(env["clip"])
    f0 = film.create(env["st"], spec())
    env["fake"].fail[f0["scenes"][0]["shots"][0]["prompt"]] = [ProviderError("rate_limited", "slow down", retryable=True)]
    film.arm(env["st"], f0["id"], True, 10 ** 6, None)
    env["fr"].run(f0["id"])
    f = env["st"].get(f0["id"])
    assert f["state"] == "generated" and len(env["fake"].submits) == 4

@ff
def test_daily_cap_defers_then_resumes(env):
    mkclip(env["clip"])
    f0 = film.create(env["st"], spec())
    film.arm(env["st"], f0["id"], True, 100, None)
    env["fr"].run(f0["id"])
    f = env["st"].get(f0["id"])
    assert f["state"] == "waiting_budget" and len(env["fake"].submits) == 2
    env["clock"][0] += 86401
    film.resume(env["st"], f["id"])
    env["fr"].run(f["id"])
    f = env["st"].get(f["id"])
    assert f["state"] == "generated" and len(env["fake"].submits) == 3

@ff
def test_auto_resume_tick(env):
    mkclip(env["clip"])
    f0 = film.create(env["st"], spec())
    film.arm(env["st"], f0["id"], True, 100, None, True)
    env["fr"].run(f0["id"])
    assert env["fr"].tick() == []
    env["clock"][0] += 86401
    threads = env["fr"].tick()
    assert len(threads) == 1
    threads[0].join(20)
    assert env["st"].get(f0["id"])["state"] == "generated"

@ff
def test_resume_polls_existing_job_without_resubmitting(env):
    mkclip(env["clip"])
    f0 = film.create(env["st"], spec())
    film.arm(env["st"], f0["id"], True, 10 ** 6, None)
    first = f0["scenes"][0]["shots"][0]
    env["st"].update(f0["id"], lambda f: f["scenes"][0]["shots"][0].update(state="running", provider_job="existing1", credits=48))
    env["fr"].run(f0["id"])
    f = env["st"].get(f0["id"])
    assert f["state"] == "generated" and first["prompt"] not in env["fake"].submits and len(env["fake"].submits) == 2

def test_cancel_is_not_reported_as_completed(env):
    f0 = film.create(env["st"], spec())
    film.arm(env["st"], f0["id"], True, 10 ** 6, None)
    env["fake"].poll_state = "running"
    env["fake"].on_poll = lambda pid: film.cancel(env["st"], f0["id"])
    env["fr"].run(f0["id"])
    f = env["st"].get(f0["id"])
    assert f["state"] == "cancelled" and "completed" not in states(f)

def test_duplicate_run_is_refused(env):
    f0 = film.create(env["st"], spec())
    film.arm(env["st"], f0["id"], True, 10 ** 6, None)
    env["fr"].active.add(f0["id"])
    assert env["fr"].run(f0["id"]) is False and env["fake"].submits == []

def test_recover_marks_running_films_interrupted(env):
    f0 = film.create(env["st"], spec())
    film.arm(env["st"], f0["id"], True, 10 ** 6, None)
    assert env["st"].recover() == 1 and env["st"].get(f0["id"])["state"] == "interrupted"

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CINEMA_FILM_TICKER", "0")
    monkeypatch.delenv(mh.ENV_KEY, raising=False)
    monkeypatch.setitem(providers.REGISTRY, "fake", Fake(None))
    monkeypatch.setattr(film.FilmRunner, "run", lambda self, fid: True)
    app = create_app(tmp_path); app.testing = True
    return app.test_client()

def test_api_providers_hide_secrets(client, monkeypatch):
    monkeypatch.setenv(mh.ENV_KEY, "mhk_live_SECRETSECRETSECRETSECRET")
    r = client.get("/api/providers")
    assert {"magic_hour", "fake"} <= {p["name"] for p in r.get_json()} and "SECRET" not in r.get_data(as_text=True)

def test_api_film_flow_rules(client):
    r = client.post("/api/films/plan", json=spec(target_seconds=20))
    assert r.status_code == 200 and r.get_json()["summary"]["seconds_total"] >= 20
    fid = client.post("/api/films", json=spec()).get_json()["id"]
    assert client.post("/api/films", json=spec(model="zzz")).status_code == 400
    assert client.post("/api/films/%s/start" % fid, json={"daily_cap": 100}).status_code == 400
    assert client.post("/api/films/%s/start" % fid, json={"confirm_cost": True}).status_code == 400
    r = client.post("/api/films/%s/start" % fid, json={"confirm_cost": True, "daily_cap": 500})
    assert r.status_code == 202 and r.get_json()["state"] == "running"
    assert client.post("/api/films/%s/start" % fid, json={"confirm_cost": True, "daily_cap": 500}).status_code == 400
    assert client.get("/api/films/%s/output" % fid).status_code == 404
    assert client.get("/api/films/abc").status_code == 404
    assert client.get("/api/films").get_json()[0]["id"] == fid

def test_api_unconfigured_provider_cannot_start(client):
    fid = client.post("/api/films", json=spec(provider="magic_hour", model="ltx-2.5", shot_seconds=5)).get_json()["id"]
    r = client.post("/api/films/%s/start" % fid, json={"confirm_cost": True, "daily_cap": 500})
    assert r.status_code == 503 and r.get_json()["code"] == "not_configured"


@ff
def test_retry_failed_batch(env):
    mkclip(env["clip"])
    f0 = film.create(env["st"], spec())
    for i in (0, 2):
        env["fake"].fail[f0["scenes"][i]["shots"][0]["prompt"]] = [ProviderError("content_rejected", "rejected")]
    film.arm(env["st"], f0["id"], True, 10 ** 6, None)
    env["fr"].run(f0["id"])
    f = env["st"].get(f0["id"])
    assert f["state"] == "failed" and states(f) == ["failed", "completed", "failed"]
    n = len(env["fake"].submits)
    with pytest.raises(film.FilmError):
        film.retry_failed(env["st"], f["id"], confirm_cost=False)
    film.retry_failed(env["st"], f["id"], confirm_cost=True)
    film.resume(env["st"], f["id"])
    env["fr"].run(f["id"])
    f = env["st"].get(f["id"])
    assert f["state"] == "generated" and len(env["fake"].submits) == n + 2
