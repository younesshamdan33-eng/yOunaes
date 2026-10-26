"""Stable integration surface for the CINEMA web app. Import ONLY from here.
All methods return plain dicts/lists. Errors: JobError, ConfigError."""
from . import config, doctor, jobs, lifecycle
from .config import ConfigError
from .jobs import JobError

API_VERSION = 1
__all__ = ["Core", "API_VERSION", "JobError", "ConfigError"]

class Core:
    def __init__(self, root=None):
        self.cfg = config.load(root)
        self._jobs = jobs.JobStore(self.cfg)

    def status(self):
        return lifecycle.status(self.cfg)

    def diagnostics(self):
        return [{"name": n, "ok": ok, "detail": d} for n, ok, d in doctor.run(self.cfg)]

    # --- app side: submit and observe jobs ---
    def submit_job(self, kind, params=None, need_mb=50):
        return self._jobs.create(kind, params, need_mb)

    def get_job(self, job_id):
        return self._jobs.get(job_id)

    def list_jobs(self):
        return self._jobs.list()

    def cancel_job(self, job_id):
        return self._jobs.cancel(job_id)

    # --- runner side: the app's worker reports through these ---
    def start_job(self, job_id):
        return self._jobs.transition(job_id, "running")

    def report_progress(self, job_id, pct):
        return self._jobs.set_progress(job_id, pct)

    def finish_job(self, job_id):
        return self._jobs.transition(job_id, "completed")

    def fail_job(self, job_id, error):
        return self._jobs.transition(job_id, "failed", error=error)

    def is_cancelled(self, job_id):
        return self._jobs.get(job_id)["state"] == "cancelled"

    def job_output_dir(self, job_id):
        self._jobs.get(job_id)
        return str(self.cfg.jobs_dir / job_id / "output")
