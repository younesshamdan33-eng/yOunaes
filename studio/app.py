import os, shutil, threading
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from cinema_core import config, jobs
from . import i18n, voices, render, runner, magichour, providers, film
from .cie import engine as cie_engine, learn as cie_learn, looks as cie_looks, quality as cie_quality
from .cie.errors import CieError
from .projects import LANGS, MAX_SCRIPT, PROFILES, NotFound, ProjectError, ProjectStore
from .cinema_api import cinema_bp

PUBLIC = ("/health", "/ready")
PROXY_HEADERS = ("Cf-Connecting-Ip", "Cf-Ray", "Cf-Visitor", "X-Forwarded-For", "X-Forwarded-Host")
LOCAL_HOSTS = ("127.0.0.1", "localhost")

def create_app(root=None):
    cfg = config.load(root)
    allow_suffix = tuple(x.strip() for x in os.environ.get("CINEMA_ALLOW_HOST_SUFFIX", "").split(",") if x.strip())
    store = ProjectStore(cfg)
    jobstore = jobs.JobStore(cfg)
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.json.ensure_ascii = False
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

    @app.before_request
    def guard():
        if request.path in PUBLIC:
            return None
        host = request.host.rsplit(":", 1)[0]
        trusted = bool(allow_suffix) and host.endswith(allow_suffix)
        if not trusted and (host not in LOCAL_HOSTS or any(h in request.headers for h in PROXY_HEADERS)):
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
    def list_studio_projects():
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

    @app.get("/api/system")
    def api_system():
        du = shutil.disk_usage(cfg.root)
        js = jobstore.list()
        return jsonify(projects=len(store.list()),
                       jobs_active=sum(1 for j in js if j["state"] in ("queued", "running")),
                       free_mb=du.free // 1048576, total_mb=du.total // 1048576, min_free_mb=cfg.min_free_mb)


    @app.post("/api/projects/<pid>/render")
    def render_project_endpoint(pid):
        project = store.get(pid)
        try:
            scenes = render.validate_for_render(project)
        except render.RenderError as e:
            return jsonify(error=str(e)), 400

        for existing in jobstore.list():
            if (
                existing.get("kind") == "render"
                and existing.get("params", {}).get("project_id") == pid
                and existing.get("state") in ("queued", "running")
            ):
                return jsonify(error="render already active", job=existing), 409

        try:
            need_mb = render.estimate_mb(project, scenes)
            job = jobstore.create(
                "render", {"project_id": pid}, need_mb=need_mb
            )
        except jobs.JobError as e:
            return jsonify(error=str(e)), 409

        try:
            thread = threading.Thread(
                target=runner.run_job,
                args=(cfg, jobstore, store, job["id"]),
                daemon=True,
            )
            thread.start()
        except Exception:
            try:
                jobstore.transition(
                    job["id"], "failed", error="could not start render worker"
                )
            except jobs.JobError:
                pass
            return jsonify(error="could not start render worker"), 500

        return jsonify(job), 202

    @app.get("/api/jobs/<jid>")
    def get_job(jid):
        try:
            return jsonify(jobstore.get(jid))
        except jobs.JobError:
            return jsonify(error="job not found"), 404

    @app.post("/api/jobs/<jid>/cancel")
    def cancel_job(jid):
        try:
            job = jobstore.get(jid)
        except jobs.JobError:
            return jsonify(error="job not found"), 404

        if job.get("state") not in ("queued", "running"):
            return jsonify(error="job is not active"), 409

        try:
            return jsonify(jobstore.cancel(jid))
        except jobs.JobError:
            return jsonify(error="job cannot be cancelled"), 409

    @app.get("/api/jobs/<jid>/output")
    def get_job_output(jid):
        try:
            job = jobstore.get(jid)
        except jobs.JobError:
            return jsonify(error="job not found"), 404

        output_dir = cfg.jobs_dir / jid / "output"
        film = output_dir / "film.mp4"
        if job.get("state") != "completed" or not film.is_file():
            return jsonify(error="output not found"), 404

        return send_from_directory(
            str(output_dir), "film.mp4", as_attachment=True,
            download_name="film.mp4",
        )

    @app.get("/api/ai/status")
    def ai_status():
        return jsonify(magichour.status())

    @app.post("/api/ai/generate")
    def ai_generate():
        d = body()
        if not magichour.api_key():
            return jsonify(error="Magic Hour is not configured: set MAGIC_HOUR_API_KEY and restart the server", code="not_configured"), 503
        if d.get("confirm_cost") is not True:
            return jsonify(error="this is a paid generation: confirm_cost=true is required", code="confirmation_required"), 400
        try:
            params = magichour.validate(d)
        except magichour.MagicHourError as e:
            return jsonify(error=str(e), code=e.code), 400
        blocked = magichour.guard(jobstore.list())
        if blocked:
            return jsonify(error=blocked[1]), blocked[0]
        try:
            job = jobstore.create("aigen", params, need_mb=120)
        except jobs.JobError as e:
            return jsonify(error=str(e)), 409
        try:
            threading.Thread(target=magichour.run_job, args=(cfg, jobstore, job["id"]), daemon=True).start()
        except Exception:
            try:
                jobstore.transition(job["id"], "failed", error="could not start generation worker")
            except jobs.JobError:
                pass
            return jsonify(error="could not start generation worker"), 500
        return jsonify(job), 202

    films = film.FilmStore(cfg)
    fr = film.FilmRunner(cfg, films)
    films.recover()
    if os.environ.get("CINEMA_FILM_TICKER", "1") == "1":
        fr.start_ticker()

    @app.errorhandler(film.FilmNotFound)
    def _fnf(e):
        return jsonify(error=str(e)), 404

    @app.errorhandler(film.FilmError)
    def _fbad(e):
        return jsonify(error=str(e)), 400

    @app.errorhandler(providers.ProviderError)
    def _perr(e):
        return jsonify(error=str(e), code=e.code), 400

    def obj():
        d = body()
        if not isinstance(d, dict):
            raise film.FilmError("body must be an object")
        return d

    def film_view(f):
        v = dict(f)
        v["summary"], v["estimate"], v["running"] = film.summary(f), film.estimate(f), f["id"] in fr.active
        return v

    cie_stats = cie_learn.Stats(cfg.root / "var" / "cie_stats.json")

    @app.errorhandler(CieError)
    def _cie_err(e):
        return jsonify(error=str(e), reasons=e.reasons), e.status

    @app.get("/api/cie/looks")
    def cie_looks_list():
        return jsonify(cie_looks.listing())

    @app.get("/api/cie/engines")
    def cie_engines():
        return jsonify(cie_engine.engines_view(list(providers.REGISTRY.values()), cie_stats))

    @app.post("/api/cie/plan")
    def cie_plan():
        d = obj()
        return jsonify(cie_engine.plan(d, cie_engine.limits_for(list(providers.REGISTRY.values()), d, cie_stats)))

    @app.post("/api/cie/films")
    def cie_create_film():
        return jsonify(film_view(cie_engine.create_film(films, film, providers.REGISTRY, obj(), cie_stats))), 201

    @app.post("/api/cie/films/<fid>/review")
    def cie_review(fid):
        return jsonify(cie_quality.review_film(films, fid, cie_stats))

    @app.post("/api/cie/films/<fid>/shots/<sid>/recycle")
    def cie_recycle(fid, sid):
        d = obj()
        prov = providers.get(films.get(fid)["provider"])
        cie_quality.recycle(films, fid, sid, bool(getattr(prov, "free", False)), d.get("confirm_cost"))
        f = film.resume(films, fid)
        fr.start(fid)
        return jsonify(film_view(f)), 202

    from .prod import api as prod_api
    prod_api.register(app, cfg)

    @app.get("/api/vidgen/status")
    def vidgen_status():
        from . import vidgen
        st = vidgen.status()
        return jsonify(state=st["state"], ready=st["ready"], reason=st["reason"], model=(st.get("caps") or {}).get("model"))

    @app.get("/api/providers")
    def api_providers():
        return jsonify([p.describe() for p in providers.REGISTRY.values()])

    @app.post("/api/films/plan")
    def films_plan():
        return jsonify(film_view(film.plan_film(obj())))

    @app.post("/api/films")
    def films_create():
        return jsonify(film_view(film.create(films, obj()))), 201

    @app.get("/api/films")
    def films_list():
        keys = ("id", "title", "state", "provider", "model", "created", "updated")
        return jsonify([dict({k: f.get(k) for k in keys}, summary=film.summary(f)) for f in films.list()])

    @app.get("/api/films/<fid>")
    def films_get(fid):
        return jsonify(film_view(films.get(fid)))

    @app.post("/api/films/<fid>/start")
    def films_start(fid):
        d = obj()
        prov = providers.get(films.get(fid)["provider"])
        if not prov.configured():
            return jsonify(error="provider %s is not configured" % prov.label, code="not_configured"), 503
        f = film.arm(films, fid, d.get("confirm_cost"), d.get("daily_cap"), d.get("total_cap"), d.get("auto_resume") is True)
        fr.start(fid)
        return jsonify(film_view(f)), 202

    @app.post("/api/films/<fid>/cancel")
    def films_cancel(fid):
        return jsonify(film_view(film.cancel(films, fid)))

    @app.post("/api/films/<fid>/resume")
    def films_resume(fid):
        f = film.resume(films, fid)
        fr.start(fid)
        return jsonify(film_view(f)), 202

    @app.post("/api/films/<fid>/shots/<sid>/retry")
    def films_retry(fid, sid):
        d = obj()
        film.retry_shot(films, fid, sid, d.get("confirm_cost"), d.get("resubmit") is True, d.get("acknowledge_possible_charge") is True)
        f = film.resume(films, fid)
        fr.start(fid)
        return jsonify(film_view(f)), 202

    @app.post("/api/films/<fid>/retry-failed")
    def films_retry_failed(fid):
        d = obj()
        film.retry_failed(films, fid, d.get("confirm_cost"), d.get("acknowledge_possible_charge") is True)
        f = film.resume(films, fid)
        fr.start(fid)
        return jsonify(film_view(f)), 202

    @app.post("/api/films/<fid>/assemble")
    def films_assemble(fid):
        fr.assemble_bg(fid, obj().get("allow_partial") is True)
        return jsonify(film_view(films.get(fid))), 202

    @app.get("/api/films/<fid>/output")
    def films_output(fid):
        f = films.get(fid)
        p = films.path(fid) / "output" / "film.mp4"
        if not f.get("output") or not p.is_file():
            return jsonify(error="output not found"), 404
        return send_from_directory(str(p.parent), "film.mp4", as_attachment=request.args.get("dl") == "1", download_name="film.mp4")

    @app.get("/api/films/<fid>/shots/<sid>/clip")
    def films_clip(fid, sid):
        films.get(fid)
        p = films.path(fid) / "clips" / (sid + ".mp4")
        if not film.SID_RE.match(sid) or not p.is_file():
            return jsonify(error="clip not found"), 404
        return send_from_directory(str(p.parent), sid + ".mp4")

    app.register_blueprint(cinema_bp)
    return app
