"""REAL end-to-end test. SPENDS Magic Hour credits. Run: .venv/bin/python -m studio.live_test --yes"""
import argparse, hashlib, json, sys, time, urllib.error, urllib.request
from pathlib import Path
from studio import magichour as mh
B = "http://127.0.0.1:8750"

def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--seconds", type=int, default=3)
    ap.add_argument("--prompt", default="a golden retriever puppy running through a sunny meadow, cinematic, shallow depth of field")
    a = ap.parse_args()
    if not a.yes:
        print("Refusing: this spends real credits. Re-run with --yes."); return 2
    st = call("GET", "/api/ai/status")[1]
    if not st.get("configured"):
        print("MAGIC_HOUR_API_KEY is not set in the server. REAL AI VIDEO GENERATION IS NOT YET VERIFIED."); return 1
    code, job = call("POST", "/api/ai/generate", {"prompt": a.prompt, "model": "ltx-2.5", "seconds": a.seconds,
                     "resolution": "480p", "aspect_ratio": "16:9", "audio": False, "confirm_cost": True})
    print("submit:", code, job.get("id"), job.get("error"))
    if code != 202:
        print("REAL AI VIDEO GENERATION IS NOT YET VERIFIED."); return 1
    jid, t0, d = job["id"], time.time(), {}
    while time.time() - t0 < 1500:
        time.sleep(10)
        d = call("GET", "/api/jobs/" + jid)[1]
        print("  %4ds state=%s error=%s" % (time.time() - t0, d.get("state"), d.get("error")))
        if d.get("state") in ("completed", "failed", "cancelled"):
            break
    jdir = Path("var/jobs") / jid
    for f in ("provider.json", "job.log"):
        if (jdir / f).exists():
            print("---", f, "---"); print((jdir / f).read_text()[-900:])
    if d.get("state") != "completed":
        print("REAL AI VIDEO GENERATION IS NOT YET VERIFIED."); return 1
    out = Path("var/live_test"); out.mkdir(parents=True, exist_ok=True)
    f = out / (jid + ".mp4")
    with urllib.request.urlopen(B + "/api/jobs/" + jid + "/output", timeout=120) as r:
        f.write_bytes(r.read())
    same = hashlib.sha256(f.read_bytes()).digest() == hashlib.sha256((jdir / "output" / "film.mp4").read_bytes()).digest()
    try:
        info = mh.probe(f, a.seconds)
    except mh.MagicHourError as e:
        print("validation failed:", e); print("REAL AI VIDEO GENERATION IS NOT YET VERIFIED."); return 1
    print("endpoint served file:", f, info, "identical_to_job_output=", same)
    print("REAL AI VIDEO GENERATION VERIFIED" if same else "REAL AI VIDEO GENERATION IS NOT YET VERIFIED.")
    return 0 if same else 1

if __name__ == "__main__":
    sys.exit(main())
