import pytest
from studio.app import create_app

def mk(tmp_path, monkeypatch, suffix):
    if suffix is None:
        monkeypatch.delenv("CINEMA_ALLOW_HOST_SUFFIX", raising=False)
    else:
        monkeypatch.setenv("CINEMA_ALLOW_HOST_SUFFIX", suffix)
    monkeypatch.setenv("CINEMA_FILM_TICKER", "0")
    app = create_app(tmp_path); app.testing = True
    return app.test_client()

def test_default_is_local_only(tmp_path, monkeypatch):
    c = mk(tmp_path, monkeypatch, None)
    assert c.get("/api/meta").status_code == 200
    assert c.get("/api/meta", base_url="https://abc-8750.app.github.dev", headers={"X-Forwarded-Host": "abc"}).status_code == 403
    assert c.get("/api/meta", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 403

def test_opt_in_allows_only_the_configured_suffix(tmp_path, monkeypatch):
    c = mk(tmp_path, monkeypatch, ".app.github.dev")
    ok = c.get("/api/meta", base_url="https://abc-8750.app.github.dev", headers={"X-Forwarded-Host": "abc", "X-Forwarded-For": "1.2.3.4"})
    assert ok.status_code == 200
    for host in ("https://evil.com", "https://app.github.dev.evil.com", "https://abc.app.github.dev.evil.com"):
        assert c.get("/api/meta", base_url=host).status_code == 403
