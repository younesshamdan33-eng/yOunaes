"""Reference GPU Video Worker (contract v1). Run it on a SEPARATE machine with an NVIDIA GPU, never on the phone.
NOT tested by its author. Check the model's licence before any commercial use.
  pip install flask torch diffusers transformers accelerate sentencepiece imageio imageio-ffmpeg
  CINEMA_WORKER_TOKEN=<long random secret> python cinema_worker.py --host 127.0.0.1 --port 8800
Expose it only through an https tunnel or reverse proxy. A model is served only if its verified spec is in MODELS."""
import argparse, hmac, os, queue, re, shutil, subprocess, threading, time, uuid
from pathlib import Path
from flask import Flask, jsonify, request, send_file

MODELS = {
    "THUDM/CogVideoX-2b": {"frames": 49, "fps": 8, "steps": 50, "guidance": 6.0, "max_seconds": 6,
                           "profiles": {"480p": {"width": 720, "height": 480, "aspect_ratio": "3:2"}}},
}
MODEL = os.environ.get("CINEMA_MODEL", "THUDM/CogVideoX-2b")
OUT = Path(os.environ.get("CINEMA_WORKER_OUT", "worker_out"))
JOBS, LOCK, Q, PIPE = {}, threading.Lock(), queue.Queue(), {}
HEX = re.compile(r"^[0-9a-f]{32}$")

class Stop(Exception):
    pass

def gpu_ok():
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False

def load():
    if "pipe" not in PIPE:
        import torch
        from diffusers import CogVideoXPipeline
        pipe = CogVideoXPipeline.from_pretrained(MODEL, torch_dtype=torch.float16)
        pipe.enable_model_cpu_offload()
        pipe.vae.enable_tiling()
        PIPE["pipe"], PIPE["torch"] = pipe, torch
    return PIPE["pipe"], PIPE["torch"]

def finish(raw, out, seconds):
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-t", "%.2f" % seconds, "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-crf", "16", "-movflags", "+faststart", str(out)], check=True, timeout=300)
        raw.unlink()
    else:
        raw.replace(out)

def prune(max_age=48 * 3600):
    if not OUT.is_dir():
        return
    now = time.time()
    for f in OUT.iterdir():
        if f.is_file() and not f.is_symlink() and HEX.match(f.name.split(".")[0]) and now - f.stat().st_mtime > max_age:
            f.unlink()

def work():
    while True:
        jid = Q.get()
        job = JOBS[jid]
        if job["state"] == "cancelled":
            continue
        job["state"] = "running"
        try:
            from diffusers.utils import export_to_video
            pipe, torch = load()
            m, s = MODELS[MODEL], job["spec"]
            seed = s["seed"] if isinstance(s.get("seed"), int) else int(time.time())

            def cb(p, i, t, kw):
                if job["cancel"]:
                    raise Stop()
                job["progress"] = int(100 * (i + 1) / m["steps"])
                return kw

            frames = pipe(prompt=s["prompt"], num_frames=m["frames"], num_inference_steps=m["steps"], guidance_scale=m["guidance"],
                          generator=torch.Generator(device="cpu").manual_seed(seed), callback_on_step_end=cb).frames[0]
            OUT.mkdir(parents=True, exist_ok=True)
            raw, out = OUT / ("%s.raw.mp4" % jid), OUT / ("%s.mp4" % jid)
            export_to_video(frames, str(raw), fps=m["fps"])
            finish(raw, out, min(s["seconds"], m["frames"] / m["fps"]))
            job["path"], job["progress"], job["state"] = str(out), 100, "done"
        except Stop:
            job["state"] = "cancelled"
        except Exception as e:
            job["state"], job["error"] = "failed", ("%s: %s" % (e.__class__.__name__, e))[:300]

def create_app(token):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

    @app.before_request
    def auth():
        if token is None:
            return None
        if not hmac.compare_digest(request.headers.get("Authorization", "").encode(), ("Bearer " + token).encode()):
            return jsonify(error="unauthorized"), 401

    @app.get("/capabilities")
    def caps():
        m = MODELS[MODEL]
        return jsonify(api=1, gpu=gpu_ok(), model=MODEL, modes=["text_to_video"], profiles=m["profiles"],
                       max_seconds=m["max_seconds"], fps=m["fps"])

    @app.post("/jobs")
    def submit():
        d = request.get_json(silent=True)
        m = MODELS[MODEL]
        if not isinstance(d, dict) or d.get("mode") != "text_to_video" or d.get("profile") not in m["profiles"]:
            return jsonify(error="unsupported request"), 400
        p, sec = d.get("prompt"), d.get("seconds")
        if not isinstance(p, str) or not 1 <= len(p) <= 2000 or isinstance(sec, bool) or not isinstance(sec, (int, float)) or not 0 < sec <= m["max_seconds"]:
            return jsonify(error="invalid prompt or duration"), 400
        with LOCK:
            if sum(1 for j in JOBS.values() if j["state"] in ("queued", "running")) >= 2:
                return jsonify(error="worker busy"), 429
            jid = uuid.uuid4().hex
            JOBS[jid] = {"state": "queued", "progress": 0, "error": None, "cancel": False, "spec": d, "path": None}
        prune()
        Q.put(jid)
        return jsonify(id=jid), 202

    @app.get("/jobs/<jid>")
    def state(jid):
        j = JOBS.get(jid)
        return jsonify(error="not found"), 404 if not j else jsonify(state=j["state"], progress=j["progress"], error=j["error"])

    @app.post("/jobs/<jid>/cancel")
    def cancel(jid):
        j = JOBS.get(jid)
        if not j:
            return jsonify(error="not found"), 404
        j["cancel"] = True
        if j["state"] == "queued":
            j["state"] = "cancelled"
        return jsonify(ok=True)

    @app.get("/jobs/<jid>/video")
    def video(jid):
        j = JOBS.get(jid)
        if not j or j["state"] != "done":
            return jsonify(error="not ready"), 404
        return send_file(j["path"], mimetype="video/mp4")

    return app

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8800)
    a = ap.parse_args()
    if MODEL not in MODELS:
        raise SystemExit("unsupported model %s: add its verified spec to MODELS first" % MODEL)
    tok = os.environ.get("CINEMA_WORKER_TOKEN")
    if not tok and a.host not in ("127.0.0.1", "localhost"):
        raise SystemExit("refusing to listen on a non-local address without CINEMA_WORKER_TOKEN")
    threading.Thread(target=work, daemon=True).start()
    create_app(tok).run(host=a.host, port=a.port, threaded=True)
