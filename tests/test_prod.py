"""Production Studio tests: REAL ffmpeg rendering; speech synthesis and the image service are MOCKED (no network, no credits)."""
import shutil, subprocess, time
from pathlib import Path
import pytest
from studio import render
from studio.prod import check, looks, pipeline, plan, script, store, visuals, voices

ff = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe") and render.capabilities().get("ass")), reason="ffmpeg with ass not available")
PATCHED = "prod_api.register" in Path("studio/app.py").read_text()
EN = """INT. LIGHTHOUSE - NIGHT

(visual: a stormy sea crashing against a tall stone lighthouse at night)
Waves pound the rocks as a storm rages.

MARA (worried): The light is failing, Tom.
TOM: I will follow you up the stairs.

EXT. CLIFF - DAWN

The storm has passed. Mara and Tom stand together.

NARRATOR: The light guided every ship home.
"""
AR = """مشهد 1: الفنار - ليلاً

الأمواج تضرب الصخور بعنف.

مريم (خائفة): الضوء ينطفئ يا طارق.
طارق: سأتبعك إلى الأعلى.
"""

def test_parser_english_and_fidelity():
    p = script.parse(EN)
    assert [s["location"] for s in p["scenes"]] == ["LIGHTHOUSE", "CLIFF"] and [s["time"] for s in p["scenes"]] == ["NIGHT", "DAWN"]
    assert [b["kind"] for b in p["scenes"][0]["beats"]] == ["action", "dialogue", "dialogue"] and [b["kind"] for b in p["scenes"][1]["beats"]] == ["action", "narration"]
    b = p["scenes"][0]["beats"]
    assert b[0]["visual"].startswith("a stormy sea") and b[1]["speaker"] == "MARA" and b[1]["emotion"] == "worried" and p["characters"] == ["MARA", "TOM"]
    assert script.coverage(EN, p) == []

def test_parser_arabic_and_fidelity():
    p = script.parse(AR)
    assert "الفنار" in p["scenes"][0]["location"] and p["scenes"][0]["time"] == "ليلاً"
    assert [b["speaker"] for b in p["scenes"][0]["beats"] if b["kind"] == "dialogue"] == ["مريم", "طارق"] and script.coverage(AR, p) == []

def test_parser_does_not_swallow_scenes_of_action():
    p = script.parse("Scenes of chaos fill the street. People run: everywhere around.")
    assert len(p["scenes"]) == 1 and p["scenes"][0]["beats"][0]["kind"] == "action"

def test_voices_distinct_gendered_and_emotional():
    v = voices.assign(["MARA", "TOM", "SAM"], "en", {"MARA": "female", "TOM": "male", "SAM": "male"})
    assert len({v["MARA"], v["TOM"], v["SAM"], v["NARRATOR"]}) == 4 and v["MARA"] in voices.CATALOG["en"]["female"]
    assert voices.assign(["مريم"], "ar", {"مريم": "female"})["مريم"].startswith("ar-")
    assert voices.prosody("angry")["volume"] == "+15%" and voices.prosody("???")["rate"] == "+0%" and voices.guess_gender("مريم", "ar") == "female"

def test_plan_identity_seeds_prompts_and_validation():
    pr = plan.build({"script": EN, "seed": 7})
    shots = [s for sc in pr["scenes"] for s in sc["shots"]]
    mara = [s for s in shots if s["speaker"] == "MARA"][0]
    assert plan.identity(pr["characters"]["MARA"]) in mara["prompt"] and looks.get("cinematic")["prompt"] in mara["prompt"] and "night" in mara["prompt"]
    assert mara["seed"] == pr["characters"]["MARA"]["seed"] and pr["voices"]["MARA"] != pr["voices"]["TOM"]
    ar = plan.build({"script": AR})
    assert all(plan.ascii_only(s["prompt"]) for sc in ar["scenes"] for s in sc["shots"]) and ar["warnings"]
    for bad in ({"script": ""}, {"script": EN, "look": "zzz"}, {"script": EN, "engine": "x"}, {"script": EN, "resolution": "8k"}, {"script": EN, "voices": "yes"}):
        with pytest.raises(plan.ProdError):
            plan.build(bad)
    with pytest.raises(plan.ProdError):
        plan.build({"prompt": "hi"}, "short")

@ff
@pytest.mark.parametrize("lk", sorted(looks.LOOKS))
def test_every_look_chain_runs_in_ffmpeg(lk, tmp_path):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x336699:s=320x180:r=10:d=1", "-vf", ",".join(looks.chain(lk)) + ",format=yuv420p", "-t", "1", str(tmp_path / "o.mp4")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr

def fake_synth(text, voice, out, emotion=None, **kw):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=%.2f" % max(1.0, min(5.0, len(text.split()) * 0.4)), "-f", "wav", str(out)], check=True, timeout=60)

@pytest.fixture
def env(tmp_path, monkeypatch):
    jpg = tmp_path / "i.jpg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=1", "-frames:v", "1", "-q:v", "3", str(jpg)], check=True, timeout=60)
    state = {"ok": [], "urls": [], "fail_third": False, "heal": False}
    def http(url, timeout=120):
        if url not in state["urls"]:
            state["urls"].append(url)
        if state["fail_third"] and not state["heal"] and state["urls"].index(url) == 2:
            return 503, "", b""
        state["ok"].append(url)
        return 200, "image/jpeg", jpg.read_bytes()
    monkeypatch.setattr(voices, "synth", fake_synth)
    monkeypatch.setattr(visuals, "http_get", http)
    monkeypatch.setitem(visuals.PACING, "min_gap", 0)
    monkeypatch.setitem(visuals.PACING, "retry_wait", 0)
    st = store.Store(tmp_path)
    return dict(st=st, pr=pipeline.Producer(tmp_path, st, reserve_mb=1), state=state, tmp=tmp_path)

def film(env, **kw):
    req = {"script": EN, "resolution": "144p", "title": "T"}
    req.update(kw)
    return plan.create(env["st"], req)["id"]

@ff
def test_full_film_voices_subtitles_music_and_validation(env):
    pid = film(env)
    assert env["pr"].run(pid) is True
    p = env["st"].get(pid)
    assert p["state"] == "done", p["error"]
    shots = [s for sc in p["scenes"] for s in sc["shots"]]
    assert len(shots) == 5 and all(s["state"] == "done" and s["engine_used"] == "image_motion" for s in shots)
    out = env["st"].path(pid) / "output"
    info = check.probe(out / "film.mp4")
    assert info["has_audio"] and abs(info["duration"] - sum(s["duration"] for s in shots)) < 1.5
    assert max(check.motion(out / "film.mp4", info["duration"], 12)) > 0.6
    srt = (out / "film.srt").read_text()
    assert "light is failing" in srt and "-->" in srt and "(worried)" not in srt
    assert (out / "manifest.json").is_file() and not (env["st"].path(pid) / "work").exists()
    assert len(env["state"]["ok"]) == 5

@ff
def test_failed_shot_is_retried_alone_and_nothing_is_refetched(env):
    env["state"]["fail_third"] = True
    pid = film(env)
    env["pr"].run(pid)
    p = env["st"].get(pid)
    failed = [s["id"] for sc in p["scenes"] for s in sc["shots"] if s["state"] == "failed"]
    assert p["state"] == "failed" and len(failed) == 1 and "image service" in [s for sc in p["scenes"] for s in sc["shots"] if s["state"] == "failed"][0]["error"]
    assert not (env["st"].path(pid) / "clips" / (failed[0] + ".mp4")).exists()
    env["state"]["heal"] = True
    env["pr"].retry_failed(pid)
    env["pr"].run(pid)
    assert env["st"].get(pid)["state"] == "done"
    assert len(env["state"]["ok"]) == len(set(env["state"]["ok"])) == 5

@ff
def test_cards_engine_needs_no_network_and_fallback_is_explicit(env):
    pid = film(env, engine="cards", voices=False, music=False, script="INT. ROOM - DAY\n\nA door opens slowly.")
    env["pr"].run(pid)
    p = env["st"].get(pid)
    assert p["state"] == "done" and env["state"]["urls"] == [] and p["scenes"][0]["shots"][0]["engine_used"] == "cards"
    env["state"]["fail_third"] = True
    env["state"]["urls"] = ["a", "b"]
    strict = film(env, script="A man walks.\n\nA dog runs.\n\nA bird flies.", voices=False, music=False)
    env["pr"].run(strict)
    assert env["st"].get(strict)["state"] == "failed"
    lenient = film(env, script="A man walks.\n\nA dog runs.\n\nA bird flies.", voices=False, music=False, allow_fallback=True)
    env["state"]["urls"] = ["a", "b"]
    env["pr"].run(lenient)
    q = env["st"].get(lenient)
    assert q["state"] == "done" and any("fallback" in (s["engine_used"] or "") for sc in q["scenes"] for s in sc["shots"])

@ff
def test_short_video(env):
    pid = plan.create(env["st"], {"prompt": "a red fox running through a snowy forest", "seconds": 4, "resolution": "144p", "music": True}, "short")["id"]
    env["pr"].run(pid)
    p = env["st"].get(pid)
    assert p["state"] == "done" and abs(p["output"]["duration"] - 4) < 1.0 and check.probe(env["st"].path(pid) / "output" / "film.mp4")["has_audio"]

@ff
def test_cancel_and_storage_guard(env, monkeypatch):
    pid = film(env)
    calls = []
    def cancelling(text, voice, out, emotion=None, **kw):
        fake_synth(text, voice, out); calls.append(1)
        env["pr"].cancel(pid)
    monkeypatch.setattr(voices, "synth", cancelling)
    env["pr"].run(pid)
    p = env["st"].get(pid)
    assert p["state"] == "cancelled" and len(calls) == 1 and p["output"] is None
    other = film(env)
    class U: free = 5 * 1048576
    monkeypatch.setattr(pipeline.shutil, "disk_usage", lambda p: U())
    env["pr"].run(other)
    q = env["st"].get(other)
    assert q["state"] == "failed" and "insufficient storage" in q["error"]

@pytest.mark.skipif(not PATCHED, reason="production routes were not registered in app.py")
def test_api(tmp_path, monkeypatch):
    from studio.app import create_app
    monkeypatch.setenv("CINEMA_FILM_TICKER", "0")
    monkeypatch.setattr(pipeline.Producer, "start", lambda self, pid: None)
    app = create_app(tmp_path); app.testing = True
    c = app.test_client()
    assert c.get("/produce").status_code == 200 and c.get("/static/produce.js").status_code == 200
    caps = c.get("/api/prod/capabilities").get_json()
    assert {x["id"] for x in caps["engines"]} == {"image_motion", "cards"} and "NOT generative" in caps["engines"][0]["note"]
    assert c.post("/api/prod/projects", json={"script": ""}).status_code == 400
    r = c.post("/api/prod/projects", json={"script": EN, "resolution": "144p"})
    assert r.status_code == 201 and r.get_json()["totals"]["shots"] == 5
    pid = r.get_json()["id"]
    assert c.get("/api/prod/projects/" + pid).get_json()["characters"]["MARA"]["gender"] == "female"
    assert c.get("/api/prod/projects/" + pid + "/output").status_code == 404 and c.get("/api/prod/projects/abc").status_code == 404
    assert c.post("/api/prod/projects/" + pid + "/start", json={}).status_code == 202
    assert c.post("/api/prod/projects/" + pid + "/cancel", json={}).get_json()["state"] == "cancelled"
    assert c.post("/api/prod/short", json={"prompt": "a fox", "seconds": 99}).status_code == 400
    assert len(c.get("/api/prod/projects").get_json()) == 1
