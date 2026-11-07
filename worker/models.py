from . import hardware, registry

def installed(cfg, mid):
    return (cfg.models_dir / mid / "READY").is_file()

def status(cfg, gpu_list=None):
    gl = hardware.gpus() if gpu_list is None else gpu_list
    best = max((g["vram_total_mb"] for g in gl), default=0) / 1000  # nominal GB: a "24 GB" card reports about 24.5
    out = {}
    for mid, m in registry.visible(cfg).items():
        reasons = []
        if m["status"] == "planned":
            reasons.append("not integrated yet: " + m["note"])
        else:
            if m.get("needs_gpu", True):
                if not gl:
                    reasons.append("no NVIDIA GPU detected on this machine")
                elif m.get("min_vram_gb") and best < m["min_vram_gb"]:
                    reasons.append("needs %s GB VRAM, the largest GPU has %.0f GB" % (m["min_vram_gb"], best))
            if m["status"] != "test_only" and not installed(cfg, mid):
                reasons.append("weights not installed (run scripts/download_models.sh %s)" % mid)
            for dep in m.get("python", ()):
                if not hardware.has_module(dep):
                    reasons.append("python package missing: " + dep)
        caps = {k: m.get(k) for k in ("label", "status", "license", "repo", "min_vram_gb", "disk_gb", "t2v", "i2v", "fps", "max_seconds", "res_label", "note")}
        caps["aspect_ratios"] = list(m["dims"]) if m.get("dims") else []
        caps["seconds"] = list(range(1, m["max_seconds"] + 1)) if m.get("max_seconds") else []
        out[mid] = dict(caps, ready=not reasons, reasons=reasons)
    return out
