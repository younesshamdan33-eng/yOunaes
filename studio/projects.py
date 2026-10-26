import json, re, time, uuid

ID_RE = re.compile(r"^[0-9a-f]{32}$")
VOICE_RE = re.compile(r"^[a-z]{2,3}-[A-Za-z]{2,4}-[A-Za-z0-9]+Neural$")
LANGS = ("ar", "en", "fr", "es", "de")
PROFILES = ("preview", "480p", "720p", "1080p")
MAX_SCRIPT = 20000
DEFAULTS = {"script": "", "script_lang": "ar", "subtitle_lang": "ar", "voice": "", "profile": "480p"}

class ProjectError(ValueError):
    pass

class NotFound(ProjectError):
    pass

def clean(data):
    if not isinstance(data, dict):
        raise ProjectError("body must be a JSON object")
    unknown = set(data) - (set(DEFAULTS) | {"title"})
    if unknown:
        raise ProjectError(f"unknown fields: {sorted(unknown)}")
    out = {}
    for k, v in data.items():
        if k == "title":
            if not isinstance(v, str) or not 1 <= len(v.strip()) <= 100 or not v.strip().isprintable():
                raise ProjectError("title must be 1-100 printable characters")
            out[k] = v.strip()
        elif k == "script":
            if not isinstance(v, str) or len(v) > MAX_SCRIPT:
                raise ProjectError(f"script must be text up to {MAX_SCRIPT} characters")
            out[k] = v
        elif k == "script_lang":
            if v not in LANGS:
                raise ProjectError("unsupported script language")
            out[k] = v
        elif k == "subtitle_lang":
            if v not in LANGS + ("none",):
                raise ProjectError("unsupported subtitle language")
            out[k] = v
        elif k == "voice":
            if not isinstance(v, str) or (v and not VOICE_RE.match(v)):
                raise ProjectError("invalid voice name")
            out[k] = v
        elif k == "profile":
            if v not in PROFILES:
                raise ProjectError("unsupported profile")
            out[k] = v
    return out

class ProjectStore:
    def __init__(self, cfg):
        self.dir = cfg.root / "var" / "projects"

    def _dir(self, pid):
        if not isinstance(pid, str) or not ID_RE.match(pid):
            raise NotFound("project not found")
        return self.dir / pid

    def _write(self, p):
        d = self._dir(p["id"])
        tmp = d / "project.json.tmp"
        tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(d / "project.json")

    def get(self, pid):
        try:
            return json.loads((self._dir(pid) / "project.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise NotFound("project not found")
        except (OSError, ValueError):
            raise ProjectError("project file unreadable")

    def list(self):
        out = []
        if self.dir.is_dir():
            for d in self.dir.iterdir():
                if ID_RE.match(d.name):
                    try:
                        out.append(self.get(d.name))
                    except ProjectError:
                        pass
        return sorted(out, key=lambda p: p.get("updated", 0), reverse=True)

    def create(self, data):
        fields = clean(data)
        if "title" not in fields:
            raise ProjectError("title is required")
        now = time.time()
        p = {**DEFAULTS, **fields, "id": uuid.uuid4().hex, "created": now, "updated": now}
        self._dir(p["id"]).mkdir(parents=True)
        self._write(p)
        return p

    def update(self, pid, data):
        p = self.get(pid)
        p.update(clean(data))
        p["updated"] = time.time()
        self._write(p)
        return p

    def delete(self, pid):
        d = self._dir(pid)
        if not d.is_dir():
            raise NotFound("project not found")
        kids = list(d.iterdir())
        if any(k.is_symlink() or not k.is_file() for k in kids):
            raise ProjectError("unexpected content in project folder; not deleted")
        for k in kids:
            k.unlink()
        d.rmdir()
