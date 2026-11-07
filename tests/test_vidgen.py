import json, shutil, socket, subprocess, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from studio import providers, vidgen
from studio.providers import ProviderError

ff = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="no ffmpeg/ffprobe")
CAPS = {"api": 1, "gpu": True, "model": "fake/model", "modes": ["text_to_video"], "max_seconds": 6, "fps": 8,
        "profiles": {"480p": {"width": 720, "height": 480, "aspect_ratio": "3:2"}}}
REQ = {"prompt": "a lighthouse", "model": "auto", "seconds": 4, "resolution": "480p", "aspect_ratio": "3:2"}

@pytest.fixture
def fake(tmp_path, monkeypatch):
    mp4 = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=12:duration=1",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", str(mp4)], check=True)
    st = {"state": "done", "posted": [], "cancelled": False, "bad": False}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def _j(self, o, code=200):
            b = json.dumps(o).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            if self.headers.get("Authorization") != "Bearer tok":
                return self._j({"error": "unauthorized"}, 401)
            if self.path == "/capabilities":
                self._j(CAPS)
            elif self.path == "/jobs/job1":
                self._j({"state": st["state"], "progress": 100, "error": "boom" if st["state"] == "failed" else None})
            elif self.path == "/jobs/job1/video":
                d = b"not a video" if st["bad"] else mp4.read_bytes()
                self.send_response(200); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
            else:
                self._j({"error": "x"}, 404)
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/jobs":
                st["posted"].append(body); self._j({"id": "job1"}, 202)
            elif self.path == "/jobs/job1/cancel":
                st["cancelled"] = True; self._j({"ok": True})
            else:
                self._j({"error": "x"}, 404)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("CINEMA_WORKER_URL", "http://127.0.0.1:%d" % srv.server_address[1])
    monkeypatch.setenv("CINEMA_WORKER_TOKEN", "tok")
    yield st
    srv.shutdown()

def prov():
    return providers.get("cinema_worker")

def test_registered_and_blocked_when_unset(monkeypatch):
    monkeypatch.delenv("CINEMA_WORKER_URL", raising=False)
    assert vidgen.status()["state"] == vidgen.BLOCKED
    assert prov().describe()["configured"] is False
    with pytest.raises(ProviderError) as e:
        prov().validate(REQ)
    assert e.value.code == "worker_unavailable" and e.value.retryable and not e.value.ambiguous

def test_blocked_when_unreachable(monkeypatch):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    monkeypatch.setenv("CINEMA_WORKER_URL", "http://127.0.0.1:%d" % port)
    assert vidgen.status()["state"] == vidgen.BLOCKED

def test_plain_http_remote_rejected(monkeypatch):
    monkeypatch.setenv("CINEMA_WORKER_URL", "http://example.com")
    monkeypatch.delenv("CINEMA_WORKER_ALLOW_HTTP", raising=False)
    assert "https" in vidgen.status()["reason"]

def test_url_outside_worker_refused(monkeypatch):
    monkeypatch.setenv("CINEMA_WORKER_URL", "https://worker.example")
    with pytest.raises(vidgen.WorkerError):
        vidgen._open("GET", "https://evil.example/x")

@ff
def test_full_cycle_with_token(fake, tmp_path):
    p = prov()
    req = p.validate(REQ)
    assert req["model"] == "fake/model" and req["resolution"] == "480p"
    assert p.submit(req)["id"] == "job1"
    assert fake["posted"][0]["profile"] == "480p" and fake["posted"][0]["seconds"] == 4
    r = p.poll("job1")
    assert r["state"] == "complete" and r["url"].endswith("/jobs/job1/video")
    out = tmp_path / "d" / "shot.mp4"
    p.download(r["url"], out)
    assert out.exists() and not out.with_name("shot.mp4.part").exists()

@ff
def test_validation(fake):
    p = prov()
    assert p.validate({**REQ, "prompt": "x"})["prompt"] == "x"
    for bad in ({"resolution": "1080p"}, {"seconds": 99}, {"seconds": True}, {"model": "ltx-2.5"},
                {"aspect_ratio": "16:9"}, {"prompt": "a" * 2001}, {"prompt": ""}):
        with pytest.raises(ProviderError):
            p.validate({**REQ, **bad})

@ff
def test_failed_job_and_cancel_and_ids(fake):
    p = prov()
    fake["state"] = "failed"
    r = p.poll("job1")
    assert r["state"] == "error" and "boom" in r["error"]
    p.cancel("job1")
    assert fake["cancelled"]
    with pytest.raises(ProviderError):
        p.poll("../x")

@ff
def test_corrupt_download_rejected(fake, tmp_path):
    fake["bad"] = True
    with pytest.raises(ProviderError) as e:
        prov().download(prov().poll("job1")["url"], tmp_path / "x.mp4")
    assert e.value.code == "bad_video" and not (tmp_path / "x.mp4").exists()

def test_projects_list_endpoint_and_status(tmp_path, monkeypatch):
    monkeypatch.delenv("CINEMA_WORKER_URL", raising=False)
    from studio.app import create_app
    app = create_app(tmp_path); app.testing = True
    c = app.test_client()
    assert c.get("/api/projects").get_json() == []
    assert c.post("/api/projects", json={"title": "ف"}).status_code == 201
    assert len(c.get("/api/projects").get_json()) == 1
    assert c.get("/api/vidgen/status").get_json()["ready"] is False
