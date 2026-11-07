"""python -m worker.cli status | download <model> | selftest --yes [--model ID]"""
import argparse, json, sys, time, urllib.request
from . import hardware, models, registry, validate
from .config import Cfg

def cmd_status(cfg):
    print("GPUs:", json.dumps(hardware.gpus()))
    print("disk free GB: %.1f" % hardware.disk_free_gb(cfg.home))
    for mid, m in models.status(cfg).items():
        print("%-24s %-22s ready=%s %s" % (mid, m["status"], m["ready"], "; ".join(m["reasons"])))

def cmd_download(cfg, mid):
    spec = registry.visible(cfg).get(mid)
    if not spec or spec["status"] not in ("integrated", "integrated_unverified"):
        sys.exit("model is not integrated: %s" % mid)
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        sys.exit("huggingface_hub is missing: run scripts/setup_worker.sh")
    free = hardware.disk_free_gb(cfg.home)
    if free < spec["disk_gb"] + 5:
        sys.exit("only %.0f GB free, need about %d GB" % (free, spec["disk_gb"] + 5))
    target = cfg.models_dir / mid
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=spec["repo"], local_dir=str(target))
    total = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    if not (target / "model_index.json").is_file() or total < spec["disk_gb"] * 0.4 * 1024 ** 3:
        sys.exit("download looks incomplete (%.1f GB, model_index.json present: %s)" % (total / 1024 ** 3, (target / "model_index.json").is_file()))
    (target / "READY").write_text(json.dumps({"repo": spec["repo"], "bytes": total, "time": time.time()}))
    print("READY: %s (%.1f GB)" % (mid, total / 1024 ** 3))

def _call(cfg, method, path, body=None, raw=False):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (cfg.port, path), data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": "Bearer " + cfg.token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = r.read()
        return d if raw else json.loads(d)

def cmd_selftest(cfg, mid, yes):
    if not yes:
        sys.exit("selftest runs a real generation on this GPU (minutes of GPU time). Re-run with --yes")
    ready = [k for k, v in models.status(cfg).items() if v["ready"] and v["status"] in ("integrated", "integrated_unverified")]
    mid = mid or (ready[0] if ready else None)
    if not mid:
        sys.exit("no ready model: run status to see why")
    j = _call(cfg, "POST", "/v1/jobs", {"model": mid, "prompt": "a red fox running through a snowy forest, cinematic, natural motion", "seconds": 2, "steps": 20})
    print("job", j["id"])
    while True:
        time.sleep(5)
        j = _call(cfg, "GET", "/v1/jobs/" + j["id"])
        print(" ", j["state"], j.get("progress"))
        if j["state"] in ("completed", "failed", "cancelled"):
            break
    if j["state"] != "completed":
        sys.exit("NOT VERIFIED: %s (%s)" % (j.get("error"), j.get("error_code")))
    out = cfg.home / "selftest.mp4"
    out.write_bytes(_call(cfg, "GET", "/v1/jobs/%s/output" % j["id"], raw=True))
    rep = validate.validate(out, j["params"])
    print(json.dumps(rep, indent=1))
    print("REAL GPU GENERATION VERIFIED: %s" % out if rep["ok"] else "NOT VERIFIED: %s" % rep["issues"])

def main():
    ap = argparse.ArgumentParser(prog="worker.cli")
    ap.add_argument("cmd", choices=["status", "download", "selftest"])
    ap.add_argument("model", nargs="?")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    cfg = Cfg()
    if a.cmd == "status":
        cmd_status(cfg)
    elif a.cmd == "download":
        cmd_download(cfg, a.model or sys.exit("usage: download <model>"))
    else:
        cmd_selftest(cfg, a.model, a.yes)

if __name__ == "__main__":
    main()
