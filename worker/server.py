import hmac, os, sys, time
from types import SimpleNamespace
from flask import Flask, jsonify, request, send_file
from . import hardware, models, registry
from .adapters import default_adapters
from .config import Cfg
from .jobs import JobStore
from .runner import Runner

def create_app(cfg=None, adapters=None, start_runner=True):
    cfg = cfg or Cfg()
    if len(cfg.token) < 24:
        raise RuntimeError("worker token missing or shorter than 24 characters (set CW_TOKEN or write <home>/token)")
    store = JobStore(cfg)
    runner = Runner(cfg, store, adapters or default_adapters(cfg))
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
    app.cfg, app.store, app.runner = cfg, store, runner

    @app.before_request
    def guard():
        if request.path == "/v1/health":
            return None
        h = request.headers.get("Authorization", "")
        tok = h[7:] if h.startswith("Bearer ") else ""
        if not hmac.compare_digest(tok.encode(), cfg.token.encode()):
            return jsonify(error="unauthorized"), 401
        if request.method == "POST" and not request.is_json:
            return jsonify(error="Content-Type must be application/json"), 415
        return None

    @app.errorhandler(KeyError)
    def _nf(e):
        return jsonify(error="not found"), 404

    @app.errorhandler(ValueError)
    def _bad(e):
        return jsonify(error=str(e)), 400

    @app.get("/v1/health")
    def health():
        return jsonify(status="ok", service="cinema-worker")

    @app.get("/v1/capabilities")
    def caps():
        jl = store.list()
        return jsonify(worker={"version": 1, "time": time.time()}, gpus=hardware.gpus(), disk_free_gb=round(hardware.disk_free_gb(cfg.home), 1),
                       queue={"queued": sum(1 for j in jl if j["state"] == "queued"), "running": sum(1 for j in jl if j["state"] == "running")},
                       models=models.status(cfg))

    @app.post("/v1/jobs")
    def create_job():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("invalid JSON body")
        mid = body.get("model")
        st = models.status(cfg).get(mid) if isinstance(mid, str) else None
        if st is None:
            raise ValueError("unknown model")
        if not st["ready"]:
            return jsonify(error="model not ready", reasons=st["reasons"]), 409
        params = registry.normalize(registry.visible(cfg)[mid], body)
        if store.active() >= cfg.max_queue:
            return jsonify(error="queue is full"), 429
        return jsonify(store.create(mid, params)), 202

    @app.get("/v1/jobs")
    def list_jobs():
        return jsonify([{k: j[k] for k in ("id", "state", "model", "progress", "created")} for j in store.list()][-50:])

    @app.get("/v1/jobs/<jid>")
    def get_job(jid):
        return jsonify(store.get(jid))

    @app.post("/v1/jobs/<jid>/cancel")
    def cancel(jid):
        def fn(x):
            if x["state"] not in ("queued", "running"):
                raise ValueError("job is not active")
            x["state"], x["finished"] = "cancelled", time.time()
        return jsonify(store.update(jid, fn))

    @app.get("/v1/jobs/<jid>/output")
    def output(jid):
        j, p = store.get(jid), store.output(jid)
        if j["state"] != "completed" or not p.is_file():
            return jsonify(error="output not found"), 404
        return send_file(str(p), mimetype="video/mp4", conditional=True)

    if start_runner:
        runner.start()
    return app

def main():
    cfg = Cfg()
    if cfg.host not in ("127.0.0.1", "localhost", "::1") and os.environ.get("CW_ALLOW_PUBLIC") != "1":
        sys.exit("refusing to bind %s: the worker must stay on 127.0.0.1 and be reached through an SSH tunnel (set CW_ALLOW_PUBLIC=1 only behind your own TLS proxy)" % cfg.host)
    create_app(cfg).run(host=cfg.host, port=cfg.port, threaded=True)

if __name__ == "__main__":
    main()
