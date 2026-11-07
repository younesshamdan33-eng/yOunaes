import json, re, threading, time, uuid
from pathlib import Path

ID_RE = re.compile(r"^[0-9a-f]{32}$")

def set_shot(p, sid, **kw):
    for sc in p["scenes"]:
        for sh in sc["shots"]:
            if sh["id"] == sid:
                sh.update(kw)
                return

class Store:
    def __init__(self, root):
        self.dir = Path(root) / "var" / "prod"
        self.lock = threading.RLock()
    def path(self, pid):
        if not isinstance(pid, str) or not ID_RE.match(pid):
            raise KeyError("project not found")
        return self.dir / pid
    def get(self, pid):
        try:
            return json.loads((self.path(pid) / "project.json").read_text())
        except FileNotFoundError:
            raise KeyError("project not found")
    def _save(self, p):
        d = self.path(p["id"]); d.mkdir(parents=True, exist_ok=True)
        p["updated"] = time.time()
        tmp = d / "project.json.tmp"
        tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1))
        tmp.replace(d / "project.json")
    def create(self, p):
        p["id"], p["created"] = uuid.uuid4().hex, time.time()
        with self.lock:
            self._save(p)
        return p
    def update(self, pid, fn):
        with self.lock:
            p = self.get(pid)
            fn(p)
            self._save(p)
            return p
    def list(self):
        out = []
        for d in (sorted(self.dir.iterdir()) if self.dir.is_dir() else []):
            if ID_RE.match(d.name) and not d.is_symlink():
                try:
                    out.append(self.get(d.name))
                except (KeyError, ValueError):
                    pass
        return sorted(out, key=lambda p: p["created"])
    def recover(self):
        n = 0
        for p in self.list():
            if p["state"] == "running":
                self.update(p["id"], lambda x: x.update(state="interrupted", error="server restarted: resume to continue (finished shots are kept)"))
                n += 1
        return n
