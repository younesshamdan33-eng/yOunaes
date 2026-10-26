import json
import pytest
from studio import i18n, voices
from studio.app import create_app

@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    app.testing = True
    return app.test_client()

def mk(client, **kw):
    body = {"title": "فيلمي الأول", "script": "مرحباً بالعالم"}
    body.update(kw)
    return client.post("/api/projects", json=body)

def test_health_ready(client):
    assert client.get("/health").get_json()["service"] == "cinema-core"
    assert client.get("/ready").get_json()["ready"] is True

def test_project_crud_unicode(client):
    r = mk(client)
    assert r.status_code == 201
    pid = r.get_json()["id"]
    assert client.get(f"/api/projects/{pid}").get_json()["title"] == "فيلمي الأول"
    r = client.put(f"/api/projects/{pid}", json={"script": "نص جديد", "script_lang": "ar"})
    assert r.get_json()["script"] == "نص جديد"
    lst = client.get("/api/projects").get_json()
    assert [p["id"] for p in lst] == [pid] and "script" not in lst[0]
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.get(f"/api/projects/{pid}").status_code == 404

@pytest.mark.parametrize("bad", [
    {"title": ""}, {"title": "x" * 101}, {"title": "a", "script_lang": "xx"},
    {"title": "a", "voice": "rm -rf /"}, {"title": "a", "evil": 1},
    {"title": "a", "script": "x" * 20001}, {"title": "a", "profile": "8k"}, {"script": "no title"}])
def test_validation(client, bad):
    assert client.post("/api/projects", json=bad).status_code == 400

@pytest.mark.parametrize("pid", ["..%2Fetc", "abc", "0" * 31, "../x"])
def test_bad_ids(client, pid):
    assert client.get(f"/api/projects/{pid}").status_code == 404
    assert client.put(f"/api/projects/{pid}", json={"title": "x"}).status_code == 404
    assert client.delete(f"/api/projects/{pid}").status_code == 404

def test_requires_json_and_size_limit(client):
    assert client.post("/api/projects", data="x", content_type="text/plain").status_code == 415
    big = b"x" * (1024 * 1024 + 10)
    assert client.post("/api/projects", data=big, content_type="application/json").status_code == 413

def test_tunnel_guard(client):
    tun = "https://abc.trycloudflare.com"
    assert client.get("/api/projects", base_url=tun).status_code == 403
    assert client.get("/", base_url=tun).status_code == 403
    assert client.get("/health", base_url=tun).status_code == 200
    assert client.get("/api/projects", headers={"Cf-Ray": "1"}).status_code == 403
    assert client.get("/api/projects", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 403

def test_index_and_headers(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["X-Content-Type-Options"] == "nosniff"
    assert client.get("/static/app.js").status_code == 200

def test_i18n(client):
    ar = client.get("/api/i18n/ar").get_json()
    en = client.get("/api/i18n/en").get_json()
    assert ar["dir"] == "rtl" and en["dir"] == "ltr"
    assert set(ar["strings"]) == set(en["strings"])
    assert client.get("/api/i18n/xx").status_code == 404
    assert client.get("/api/i18n/..%2Fx").status_code == 404
    assert i18n.available() == ["ar", "en"]

def test_voices_failure_and_filter(client, monkeypatch):
    def boom():
        raise OSError("no network")
    monkeypatch.setattr(voices, "fetch_remote", boom)
    assert client.get("/api/voices?lang=ar").status_code == 503
    monkeypatch.setattr(voices, "fetch_remote",
                        lambda: [{"ShortName": "ar-MA-JamalNeural", "Locale": "ar-MA", "Gender": "Male"}])
    assert len(client.get("/api/voices?lang=ar").get_json()) == 1
    assert client.get("/api/voices?lang=en").get_json() == []
    assert client.get("/api/voices?lang=zz").status_code == 400

def test_jobs_endpoint_empty(client):
    assert client.get("/api/jobs").get_json() == []

def test_system_stats(client):
    d = client.get("/api/system").get_json()
    assert d["projects"] == 0 and d["jobs_active"] == 0
    assert d["free_mb"] > 0 and d["total_mb"] >= d["free_mb"]
