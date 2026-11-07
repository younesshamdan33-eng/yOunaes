"""Provider registry for AI video generation. A provider turns a validated request into a clip.
Only providers whose integration was verified are registered (today: magic_hour).
Adding one = subclass Provider + register(). Never register a provider you have not tested live."""
from . import magichour as mh

Cancelled = mh.Cancelled
# Observed on THIS account: these returned plan_upgrade_required (free plan).
PAID_ONLY = {"kling-3.0": "rejected with plan_upgrade_required on this account",
             "veo3.1-lite": "rejected with plan_upgrade_required on this account"}
# Credits per second. ONLY values with evidence; anything else -> no estimate (None), never a guess.
RATES = {("ltx-2.5", "480p"): 24, ("ltx-2.5", "720p"): 48, ("ltx-2.5", "1080p"): 72,
         ("wan-2.2", "480p"): 24, ("ltx-2.3", "480p"): 24}

class ProviderError(Exception):
    def __init__(self, code, message, retryable=False, ambiguous=False):
        super().__init__(message)
        self.code, self.retryable, self.ambiguous = code, retryable, ambiguous

class Provider:
    name, label = "base", "Base"
    cancel_supported = False
    progress_supported = False
    def configured(self): return False
    def models(self): return {}
    def validate(self, req): raise NotImplementedError
    def estimate_credits(self, req): return None
    def submit(self, req): raise NotImplementedError      # -> {"id": str, "credits": int|None}
    def poll(self, pid): raise NotImplementedError        # -> {"state": queued|running|complete|error, "url": str|None, "error": str|None}
    def download(self, url, dest, cancelled=lambda: False): raise NotImplementedError
    def describe(self):
        return {"name": self.name, "label": self.label, "configured": bool(self.configured()), "models": self.models(),
                "cancel_supported": self.cancel_supported, "progress_supported": self.progress_supported}

class MagicHourProvider(Provider):
    name, label = "magic_hour", "Magic Hour"
    def configured(self): return bool(mh.api_key())
    def models(self):
        out = {}
        for m, spec in mh.status()["models"].items():
            out[m] = dict(spec, plan_note=PAID_ONLY.get(m))
        return out
    def validate(self, req):
        try:
            return mh.validate(req)
        except mh.MagicHourError as e:
            raise ProviderError(e.code, str(e))
    def estimate_credits(self, req):
        r = RATES.get((req["model"], req["resolution"]))
        return r * req["seconds"] if r else None
    def submit(self, req):
        try:
            d = mh.submit(req)
        except mh.MagicHourError as e:
            ambiguous = e.code == "network" or ((e.http or 0) >= 500 and e.http != 502)
            raise ProviderError(e.code, str(e), retryable=e.http in (429, 502), ambiguous=ambiguous)
        return {"id": d["id"], "credits": d.get("credits_charged")}
    def poll(self, pid):
        try:
            d = mh.fetch(pid)
        except mh.MagicHourError as e:
            raise ProviderError(e.code, str(e), retryable=e.retryable)
        st = d.get("status")
        if st == "complete":
            dl = d.get("downloads")
            url = dl[0].get("url") if isinstance(dl, list) and dl and isinstance(dl[0], dict) else None
            if not url:
                return {"state": "error", "url": None, "error": "provider finished but returned no download URL"}
            return {"state": "complete", "url": url, "error": None}
        if st == "error":
            err = d.get("error") if isinstance(d.get("error"), dict) else {}
            return {"state": "error", "url": None, "error": "%s: %s" % (err.get("code") or "provider_error", err.get("message") or "provider reported an error")}
        if st == "canceled":
            return {"state": "error", "url": None, "error": "canceled on the provider side"}
        return {"state": "queued" if st == "queued" else "running", "url": None, "error": None}
    def download(self, url, dest, cancelled=lambda: False):
        try:
            mh.download(url, dest, cancelled)
        except mh.MagicHourError as e:
            raise ProviderError(e.code, str(e), retryable=e.retryable)

REGISTRY = {}
def register(p):
    REGISTRY[p.name] = p
def get(name):
    if name not in REGISTRY:
        raise ProviderError("unknown_provider", "unknown provider: %s" % (name,))
    return REGISTRY[name]
register(MagicHourProvider())

try:  # self-hosted GPU worker (studio/vidgen.py): optional, must never break the platform
    from . import vidgen as _vidgen
    register(_vidgen.CinemaWorkerProvider())
except Exception as _e:
    import logging
    logging.getLogger("cinema").warning("cinema_worker provider not loaded: %s", _e)
