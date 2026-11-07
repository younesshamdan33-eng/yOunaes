import json, re, shutil, threading, time, uuid
from pathlib import Path

ID_RE = re.compile(r"^[0-9a-f]{32}$")

class JobStore:
    def __init__(self, cfg):
        self.dir = cfg.jobs_dir
        self.lock = threading.RLock()
        self.dir.mkdir(parents=True, exist_ok=True)
    def _p(self, jid):
        if not isinstance(jid, str) or not ID_RE.match(jid):
            raise KeyError("job not found")
        return self.dir / jid
    def get(self, jid):
        try:
            return json.loads((self._p(jid) / "job.json").read_text())
        except FileNotFoundError:
            raise KeyError("job not found")
    def _save(self, j):
        d = self._p(j["id"]); d.mkdir(parents=True, exist_ok=True)
        tmp = d / "job.json.tmp"
        tmp.write_text(json.dumps(j, indent=1))
        tmp.replace(d / "job.json")
    def create(self, model, params):
        j = {"id": uuid.uuid4().hex, "state": "queued", "model": model, "params": params, "created": time.time(), "started": None,
             "finished": None, "progress": None, "attempts": 0, "error": None, "error_code": None, "report": None}
        with self.lock:
            self._save(j)
        return j
    def update(self, jid, fn):
        with self.lock:
            j = self.get(jid)
            fn(j)
            self._save(j)
            return j
    def list(self):
        out = []
        for d in sorted(self.dir.iterdir()) if self.dir.is_dir() else []:
            if ID_RE.match(d.name) and not d.is_symlink():
                try:
                    out.append(self.get(d.name))
                except (KeyError, ValueError):
                    pass
        return sorted(out, key=lambda j: j["created"])
    def next_queued(self):
        for j in self.list():
            if j["state"] == "queued":
                return j
        return None
    def active(self):
        return sum(1 for j in self.list() if j["state"] in ("queued", "running"))
    def output(self, jid):
        return self._p(jid) / "output.mp4"
    def recover(self):
        n = 0
        for j in self.list():
            if j["state"] != "running":
                continue
            def fn(x):
                if x["attempts"] < 2:
                    x["state"], x["error"] = "queued", "worker restarted: job re-queued"
                else:
                    x["state"], x["finished"] = "failed", time.time()
                    x["error"], x["error_code"] = "worker restarted twice while running this job", "worker_restarted"
            self.update(j["id"], fn)
            n += 1
        return n
    def cleanup(self, days):
        cut, n = time.time() - days * 86400, 0
        for j in self.list():
            if j["state"] in ("completed", "failed", "cancelled") and (j["finished"] or j["created"]) < cut:
                d = self._p(j["id"])
                if not d.is_symlink() and d.parent == self.dir:
                    shutil.rmtree(d, ignore_errors=True); n += 1
        return n
