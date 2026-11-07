import threading, time
from . import hardware, models, registry, validate
from .adapters import Cancelled

class Runner:
    """Single-GPU queue: one job at a time. Jobs survive restarts (see JobStore.recover)."""
    def __init__(self, cfg, store, adapters, poll=1.0):
        self.cfg, self.store, self.adapters, self.poll = cfg, store, adapters, poll
        self._stop, self._thread = threading.Event(), None
    def start(self):
        self.store.recover()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
    def stop(self):
        self._stop.set()
    def _loop(self):
        last_clean = 0.0
        while not self._stop.is_set():
            try:
                did = self.run_next()
                if time.time() - last_clean > 3600:
                    self.store.cleanup(self.cfg.keep_days); last_clean = time.time()
            except Exception:
                did = False
            if not did:
                self._stop.wait(self.poll)
    def run_next(self):
        j = self.store.next_queued()
        if not j:
            return False
        self.run_job(j["id"])
        return True
    def _finish(self, jid, state, error=None, code=None, report=None):
        def fn(x):
            if x["state"] == "cancelled":
                return
            x["state"], x["finished"], x["error"], x["error_code"] = state, time.time(), error, code
            if report is not None:
                x["report"] = report
        self.store.update(jid, fn)
    def run_job(self, jid):
        def start(x):
            if x["state"] == "queued":
                x["state"], x["started"], x["attempts"] = "running", time.time(), x["attempts"] + 1
        j = self.store.update(jid, start)
        if j["state"] != "running":
            return
        spec = registry.visible(self.cfg).get(j["model"])
        out = self.store.output(jid)
        try:
            st = models.status(self.cfg).get(j["model"])
            if not spec or not st or not st["ready"]:
                return self._finish(jid, "failed", "model not ready: " + "; ".join((st or {}).get("reasons", ["unknown model"])), "model_not_ready")
            if spec.get("needs_gpu", True) and spec.get("min_vram_gb") and hardware.free_vram_gb() < spec["min_vram_gb"] * 0.9:
                return self._finish(jid, "failed", "not enough free VRAM (another process is using the GPU)", "insufficient_vram")
            cancelled = lambda: self.store.get(jid)["state"] == "cancelled"
            def progress(step, total):
                self.store.update(jid, lambda x: x.update(progress={"step": step, "total": total}) if x["state"] == "running" else None)
            self.adapters[spec["adapter"]].generate(dict(j["params"], model=j["model"]), out, progress, cancelled)
            if cancelled():
                out.unlink(missing_ok=True)
                return
            report = validate.validate(out, j["params"])
            if not report["ok"]:
                out.unlink(missing_ok=True)
                return self._finish(jid, "failed", "output failed validation: " + "; ".join(report["issues"]), "validation_failed", report)
            self._finish(jid, "completed", report=report)
        except Cancelled:
            out.unlink(missing_ok=True)
        except Exception as e:
            msg = str(e) or e.__class__.__name__
            out.unlink(missing_ok=True)
            self._finish(jid, "failed", msg[:400], "gpu_oom" if "out of memory" in msg.lower() else "inference_error")
