from cinema_core.jobs import JobError
from . import render

def _fail(store, jid, msg):
    try:
        store.transition(jid, "failed", error=msg)
    except JobError:
        pass

def run_job(cfg, store, pstore, jid):
    try:
        store.transition(jid, "running")
    except JobError:
        return
    work = cfg.jobs_dir / jid / "work"
    out = cfg.jobs_dir / jid / "output"

    def prog(p):
        try:
            store.set_progress(jid, p)
        except JobError:
            pass

    def cancelled():
        return store.get(jid)["state"] == "cancelled"

    try:
        project = pstore.get(store.get(jid)["params"]["project_id"])
        render.render_project(cfg, project, work, out, prog, cancelled, lambda m: store.log(jid, m))
        store.transition(jid, "completed")
        try:
            render.cleanup_work(work, cfg.jobs_dir)
        except OSError as e:
            store.log(jid, f"cleanup skipped: {e}")
    except render.Cancelled:
        store.log(jid, "cancelled by user")
        try:
            render.cleanup_work(work, cfg.jobs_dir)
        except OSError:
            pass
    except render.RenderError as e:
        _fail(store, jid, str(e))
    except Exception as e:
        _fail(store, jid, f"unexpected error: {e.__class__.__name__}: {e}")
