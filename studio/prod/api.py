import importlib.util, shutil
from flask import jsonify, request, send_file, send_from_directory
from studio import render
from . import looks, plan
from .pipeline import Producer
from .store import Store

def register(app, cfg):
    st = Store(cfg.root)
    st.recover()
    pr = Producer(cfg.root, st)
    app.prod = (st, pr)

    def body():
        d = request.get_json(silent=True)
        if not isinstance(d, dict):
            raise plan.ProdError("invalid JSON body")
        return d
    def view(p, full=False):
        shots = [sh for sc in p["scenes"] for sh in sc["shots"]]
        v = {k: p.get(k) for k in ("id", "kind", "title", "state", "error", "language", "settings", "warnings", "output", "created", "updated")}
        v["totals"] = {"shots": len(shots), "done": sum(1 for s in shots if s["state"] == "done"), "failed": sum(1 for s in shots if s["state"] == "failed"),
                       "seconds_done": round(sum(s["duration"] or 0 for s in shots), 1)}
        v["running"] = p["id"] in pr.active
        if full:
            v["characters"], v["voices"] = p["characters"], p["voices"]
            v["scenes"] = [dict(id=sc["id"], heading=sc["heading"], shots=[{k: sh.get(k) for k in ("id", "kind", "speaker", "emotion", "text", "state", "error", "duration", "engine_used", "voice")} for sh in sc["shots"]]) for sc in p["scenes"]]
        return v
    def get(pid):
        try:
            return st.get(pid), None
        except KeyError:
            return None, (jsonify(error="project not found"), 404)

    @app.errorhandler(plan.ProdError)
    def _bad(e):
        return jsonify(error=str(e)), 400

    @app.get("/produce", endpoint="prod_produce_page")
    def produce_page():
        return send_from_directory(app.static_folder, "produce.html")

    @app.get("/api/prod/capabilities", endpoint="prod_caps")
    def caps():
        c = render.capabilities()
        ff = all(c.get(k) for k in ("ffmpeg", "ffprobe", "libx264", "aac", "ass"))
        free = shutil.disk_usage(cfg.root).free // 1048576
        return jsonify(ready=ff and free > pr.reserve + 30, ffmpeg=ff, free_mb=free, reserve_mb=pr.reserve, looks=looks.listing(),
                       engines=[{"id": "image_motion", "label": "AI images + camera motion", "available": ff, "needs_internet": True,
                                 "note": "A real AI image per shot (free Pollinations service, rate-limited, may add a watermark) animated by camera motion. NOT generative AI video."},
                                {"id": "cards", "label": "Procedural motion cards", "available": ff, "needs_internet": False, "note": "Animated gradient backgrounds. NOT AI visuals."}],
                       voices={"available": importlib.util.find_spec("edge_tts") is not None, "provider": "edge-tts (free online Microsoft Neural voices)"})

    @app.post("/api/prod/projects", endpoint="prod_create_film")
    def create_film():
        return jsonify(view(plan.create(st, body(), "film"), True)), 201

    @app.post("/api/prod/short", endpoint="prod_create_short")
    def create_short():
        return jsonify(view(plan.create(st, body(), "short"), True)), 201

    @app.get("/api/prod/projects", endpoint="prod_list_projects")
    def list_projects():
        return jsonify([view(p) for p in st.list()][-30:])

    @app.get("/api/prod/projects/<pid>", endpoint="prod_get_project")
    def get_project(pid):
        p, err = get(pid)
        return err or jsonify(view(p, True))

    @app.post("/api/prod/projects/<pid>/start", endpoint="prod_start")
    def start(pid):
        p, err = get(pid)
        if err:
            return err
        if p["state"] == "running" or pid in pr.active:
            return jsonify(error="project is already running"), 409
        if p["state"] == "done":
            return jsonify(error="project is already finished"), 409
        pr.start(pid)
        return jsonify(view(st.get(pid))), 202

    @app.post("/api/prod/projects/<pid>/retry-failed", endpoint="prod_retry")
    def retry(pid):
        p, err = get(pid)
        if err:
            return err
        pr.retry_failed(pid)
        pr.start(pid)
        return jsonify(view(st.get(pid))), 202

    @app.post("/api/prod/projects/<pid>/cancel", endpoint="prod_cancel")
    def cancel(pid):
        p, err = get(pid)
        return err or jsonify(view(pr.cancel(pid)))

    @app.get("/api/prod/projects/<pid>/output", endpoint="prod_output")
    def output(pid):
        p, err = get(pid)
        if err:
            return err
        f = st.path(pid) / "output" / "film.mp4"
        if p["state"] != "done" or not f.is_file():
            return jsonify(error="output not found"), 404
        return send_file(str(f), mimetype="video/mp4", conditional=True, as_attachment=request.args.get("dl") == "1", download_name="film.mp4")

    @app.get("/api/prod/projects/<pid>/subtitles", endpoint="prod_subtitles")
    def subtitles(pid):
        p, err = get(pid)
        f = st.path(pid) / "output" / "film.srt"
        return err or (send_file(str(f), mimetype="text/plain", as_attachment=True, download_name="film.srt") if f.is_file() else (jsonify(error="no subtitles"), 404))
