import os
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from cinema_core import config, jobs
from . import i18n, voices
from .projects import LANGS, MAX_SCRIPT, PROFILES, NotFound, ProjectError, ProjectStore

PUBLIC = ("/health", "/ready")
PROXY_HEADERS = ("Cf-Connecting-Ip", "Cf-Ray", "Cf-Visitor", "X-Forwarded-For", "X-Forwarded-Host")
LOCAL_HOSTS = ("127.0.0.1", "localhost")

def create_app(root=None):
    cfg = config.load(root)
    store = ProjectStore(cfg)
    jobstore = jobs.JobStore(cfg)
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.json.ensure_ascii = False
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

    @app.before_request
    def guard():
        if request.path in PUBLIC:
            return None
        if request.host.rsplit(":", 1)[0] not in LOCAL_HOSTS or any(h in request.headers for h in PROXY_HEADERS):
            return jsonify(error="local access only"), 403
        if request.method in ("POST", "PUT") and not request.is_json:
            return jsonify(error="Content-Type must be application/json"), 415
        return None

    @app.after_request
    def secure(r):
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["X-Frame-Options"] = "DENY"
        r.headers["Referrer-Policy"] = "no-referrer"
        r.headers["Content-Security-Policy"] = "default-src 'self'"
        return r

    @app.errorhandler(NotFound)
    def _nf(e):
        return jsonify(error=str(e)), 404

    @app.errorhandler(ProjectError)
    def _bad(e):
        return jsonify(error=str(e)), 400

    @app.errorhandler(HTTPException)
    def _http(e):
        return jsonify(error=e.name), e.code

    def body():
        d = request.get_json(silent=True)
        if d is None:
            raise ProjectError("invalid JSON body")
        return d

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="cinema-core", pid=os.getpid())

    @app.get("/ready")
    def ready():
        return jsonify(ready=True, service="cinema-core", pid=os.getpid())

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/meta")
    def meta():
        return jsonify(langs=list(LANGS), profiles=list(PROFILES), max_script=MAX_SCRIPT)

    @app.get("/api/i18n/<lang>")
    def api_i18n(lang):
        d = i18n.load(lang)
        if d is None:
            return jsonify(error="unsupported language"), 404
        return jsonify(d)

    @app.get("/api/projects")
    def list_projects():
        keys = ("id", "title", "script_lang", "updated")
        return jsonify([{k: p[k] for k in keys} for p in store.list()])

    @app.post("/api/projects")
    def create_project():
        return jsonify(store.create(body())), 201

    @app.get("/api/projects/<pid>")
    def get_project(pid):
        return jsonify(store.get(pid))

    @app.put("/api/projects/<pid>")
    def update_project(pid):
        return jsonify(store.update(pid, body()))

    @app.delete("/api/projects/<pid>")
    def delete_project(pid):
        store.delete(pid)
        return jsonify(deleted=True)

    @app.get("/api/voices")
    def api_voices():
        lang = request.args.get("lang")
        if lang and lang not in LANGS:
            raise ProjectError("unsupported language")
        try:
            return jsonify(voices.get_voices(cfg, lang))
        except voices.VoicesError as e:
            return jsonify(error=str(e)), 503

    @app.get("/api/jobs")
    def api_jobs():
        keys = ("id", "kind", "state", "progress", "created")
        return jsonify([{k: j.get(k) for k in keys} for j in jobstore.list()])

    return app
