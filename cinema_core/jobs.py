"""File-backed job store. One JSON file per job under var/jobs/<id>/.
Guarantees: atomic state writes; strict transitions; storage-aware admission;
concurrency limit. NOT guaranteed: survival of a running job across restarts
(recover() marks such jobs failed). cancel() of a running job only records the
state; a runner must poll get() and stop itself. Single-writer assumption."""
import json, os, re, shutil, time, uuid
from pathlib import Path
from .lifecycle import _alive

TRANSITIONS = {
    "queued": {"running", "cancelled", "failed"},
    "running": {"completed", "failed", "cancelled"},
    "completed": set(), "failed": set(), "cancelled": set(),
}
ID_RE = re.compile(r"^[0-9a-f]{32}$")
KIND_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
MAX_QUEUED = 10

class JobError(Exception):
    pass

class JobStore:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dir = cfg.jobs_dir

    def _path(self, jid):
        if not isinstance(jid, str) or not ID_RE.match(jid):
            raise JobError("invalid job id")
        return self.dir / jid

    def _write(self, job):
        d = self._path(job["id"])
        tmp = d / "job.json.tmp"
        tmp.write_text(json.dumps(job, indent=1))
        tmp.replace(d / "job.json")

    def get(self, jid):
        f = self._path(jid) / "job.json"
        try:
            return json.loads(f.read_text())
        except FileNotFoundError:
            raise JobError("job not found")
        except (OSError, ValueError):
            raise JobError("job file unreadable")

    def list(self):
        out = []
        if not self.dir.is_dir():
            return out
        for d in sorted(self.dir.iterdir()):
            if not ID_RE.match(d.name):
                continue
            try:
                out.append(self.get(d.name))
            except JobError:
                out.append({"id": d.name, "state": "corrupt", "progress": 0, "kind": "?", "created": 0})
        return sorted(out, key=lambda j: j.get("created", 0))

    def log(self, jid, msg):
        with open(self._path(jid) / "job.log", "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")

    def create(self, kind, params=None, need_mb=50):
        if not isinstance(kind, str) or not KIND_RE.match(kind):
            raise JobError("invalid job kind")
        params = params or {}
        if not isinstance(params, dict):
            raise JobError("params must be a dict")
        try:
            json.dumps(params)
        except (TypeError, ValueError):
            raise JobError("params must be JSON-serializable")
        self.dir.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.dir).free // (1024 * 1024)
        if free - need_mb < self.cfg.min_free_mb:
            raise JobError(f"insufficient storage ({free} MB free, need {need_mb} MB + {self.cfg.min_free_mb} MB reserve)")
        if sum(1 for j in self.list() if j["state"] == "queued") >= MAX_QUEUED:
            raise JobError("queue is full")
        jid = uuid.uuid4().hex
        (self._path(jid) / "output").mkdir(parents=True)
        job = {"id": jid, "kind": kind, "params": params, "state": "queued", "progress": 0,
               "created": time.time(), "started": None, "finished": None, "error": None, "pid": None}
        self._write(job)
        self.log(jid, f"created kind={kind}")
        return job

    def transition(self, jid, new, error=None):
        job = self.get(jid)
        if new not in TRANSITIONS.get(job["state"], set()):
            raise JobError(f"invalid transition {job['state']} -> {new}")
        if new == "running":
            if sum(1 for j in self.list() if j["state"] == "running") >= self.cfg.max_concurrent_jobs:
                raise JobError("concurrency limit reached")
            job["started"], job["pid"] = time.time(), os.getpid()
        if new in ("completed", "failed", "cancelled"):
            job["finished"] = time.time()
        if new == "completed":
            job["progress"] = 100
        if error:
            job["error"] = str(error)[:500]
        job["state"] = new
        self._write(job)
        self.log(jid, f"state -> {new}" + (f" ({job['error']})" if error else ""))
        return job

    def set_progress(self, jid, pct):
        job = self.get(jid)
        if job["state"] != "running":
            raise JobError("progress only applies to running jobs")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not 0 <= pct <= 100:
            raise JobError("progress must be 0-100")
        job["progress"] = pct
        self._write(job)
        return job

    def cancel(self, jid):
        return self.transition(jid, "cancelled")

    def recover(self):
        n = 0
        for j in self.list():
            if j["state"] != "running":
                continue
            pid = j.get("pid")
            if isinstance(pid, int) and pid > 1 and _alive(pid):
                continue
            self.transition(j["id"], "failed", error="interrupted: runner process is gone")
            n += 1
        return n
