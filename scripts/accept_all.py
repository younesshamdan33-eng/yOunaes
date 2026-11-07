#!/usr/bin/env python3
"""Runs BOTH acceptance tests. Emits machine-readable JSON + human summary."""
import os, sys, json, subprocess, time
sys.path.insert(0, ".")
from worker.adapters_hf import HFAdapter
from worker.hf_spaces import SPACES, pick_best
from pipeline.film import FilmPipeline

def emit(phase, status, **kw):
    rec = {"phase":phase,"status":status,"ts":time.time(),**kw}
    print(json.dumps(rec, default=str))
    return rec

def validate(path):
    r = subprocess.run([sys.executable,"scripts/validate_video.py",path],
                      capture_output=True,text=True)
    try: return json.loads(r.stdout)
    except: return {"ok":False,"raw":r.stdout+r.stderr}

def main():
    report = {"tests":[], "env":{"token":bool(os.environ.get("HF_TOKEN"))}}

    # ===== TEST 1: Video Studio =====
    if not os.environ.get("HF_TOKEN"):
        report["tests"].append(emit("video_studio","BLOCKED",
            reason="HF_TOKEN not set — no verified GPU worker"))
    else:
        ad = HFAdapter()
        key, spec = pick_best()
        probe = ad.probe(key)
        if not probe["ok"]:
            report["tests"].append(emit("video_studio","BLOCKED",
                reason=f"Space unreachable: {probe['error']}"))
        else:
            prompt = ("cinematic wide shot, lone astronaut walking across red dunes "
                      "at sunset, volumetric light, 24fps, film grain")
            try:
                gen = ad.generate(key, prompt, duration=5.0)
                v = validate(gen["path"])
                st = "PASS" if v.get("is_real_video") else "FAIL"
                report["tests"].append(emit("video_studio",st,
                    model=key, space=spec["space"], generation=gen, validation=v))
            except Exception as e:
                report["tests"].append(emit("video_studio","FAIL",error=str(e)[:400]))

    # ===== TEST 2: Film Studio =====
    idea = "A detective finds a mysterious letter in a rainy alley that changes his life."
    fp = FilmPipeline()
    plan = fp.create(idea)
    base = {"film_id":plan["film_id"],"scenes":len(plan["scenes"]),
            "shots_planned":len(plan["shots"]),"characters":len(plan["characters"]),
            "genre":plan["genre"],"direction":plan["direction"]}
    if not os.environ.get("HF_TOKEN"):
        report["tests"].append(emit("film_studio","BLOCKED",
            reason="HF_TOKEN missing — cannot generate real shots", plan=base))
    else:
        ad = HFAdapter(); key, _ = pick_best()
        results = fp.generate_shots(plan, ad, key, max_shots=4)
        done = [r for r in results if r["status"] in ("done","resumed")]
        if not done:
            report["tests"].append(emit("film_studio","FAIL",
                reason="all shots failed", results=results, plan=base))
        else:
            asm = fp.assemble(plan, results)
            v = validate(asm.get("path","")) if asm.get("ok") else {}
            st = "PASS" if asm.get("ok") and v.get("is_real_video") else "PASS_PARTIAL"
            report["tests"].append(emit("film_studio",st,
                plan=base, shots_ok=len(done), assembly=asm, validation=v, results=results))

    # ===== Aggregate =====
    statuses = [t["status"] for t in report["tests"]]
    if "FAIL" in statuses: report["overall"] = "FAIL"
    elif all(s=="PASS" for s in statuses): report["overall"] = "PASS"
    else: report["overall"] = "BLOCKED" if all(s in ("BLOCKED","PASS_PARTIAL") for s in statuses) else "PARTIAL"

    print("\n=== JSON REPORT ===")
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["overall"]=="PASS" else (1 if report["overall"]=="FAIL" else 2)

if __name__=="__main__":
    sys.exit(main())
