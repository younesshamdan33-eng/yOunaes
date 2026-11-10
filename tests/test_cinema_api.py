"""Unit tests for cinema_api endpoints and persistent job storage."""
import pytest
import json
from flask import Flask
from pathlib import Path
from studio.cinema_api import cinema_bp, _new_job, _get, _update, _STORE_DIR

@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(cinema_bp)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

def test_cinema_health_endpoint(client):
    res = client.get("/api/cinema/health")
    assert res.status_code == 200
    data = res.get_json()
    assert "engine_present" in data
    assert "total_jobs" in data

def test_cinema_generate_validation(client):
    res = client.post("/api/cinema/generate", json={})
    assert res.status_code == 400
    assert "prompt required" in res.get_json()["error"]

    res_long = client.post("/api/cinema/generate", json={"prompt": "x" * 501})
    assert res_long.status_code == 400
    assert "too long" in res_long.get_json()["error"]

def test_job_persistence_on_disk():
    jid = _new_job(
        prompt="A testing prompt",
        style="anime",
        lighting="dramatic",
        camera="pan",
        duration=15,
    )
    job_file = _STORE_DIR / f"{jid}.json"
    assert job_file.is_file()

    saved_data = json.loads(job_file.read_text(encoding="utf-8"))
    assert saved_data["id"] == jid
    assert saved_data["prompt"] == "A testing prompt"
    assert saved_data["style"] == "anime"
    assert saved_data["duration"] == 15

    _update(jid, status="generating", message="running on kaggle")
    updated_data = json.loads(job_file.read_text(encoding="utf-8"))
    assert updated_data["status"] == "generating"
    assert updated_data["message"] == "running on kaggle"
