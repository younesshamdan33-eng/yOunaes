#!/usr/bin/env python3
"""ACCEPTANCE TEST 2 — AI Film Studio pipeline (short film, 4 shots)."""
import os, sys, json
sys.path.insert(0, ".")
from pipeline.film import FilmPipeline
from worker.adapters_hf import HFAdapter

def report(status, **kw):
    print(json.dumps({"test":"ACCEPTANCE_FILM_STUDIO","status":status,**kw}, indent=2, default=str))
    return 0 if status=="PASS" else 1

def main():
    idea = "A detective finds a mysterious letter in a rainy alley that changes his life."
    fp = FilmPipeline()
    plan = fp.create(idea)
    steps = {"script_scenes":len(plan["scenes"]),"shots":len(plan["shots"]),
             "characters":len(plan["characters"]),"genre":plan["genre"]}
    if not os.environ.get("HF_TOKEN"):
        return report("BLOCKED", reason="No HF_TOKEN — cannot generate real shots",
                      plan=steps, film_id=plan["film_id"])
    ad = HFAdapter(); results=[]
    try:
        results = fp.generate_shots(plan, ad, "ltx-video-hf")
    except Exception as e:
        return report("FAIL", error=str(e)[:400], plan=steps, partial=results)
    done = [r for r in results if r["status"] in ("done","resumed")]
    if not done:
        return report("FAIL", reason="all shots failed", results=results, plan=steps)
    asm = fp.assemble(plan, results)
    if not asm.get("ok"):
        return report("FAIL", reason="assembly failed", assembly=asm, shots=len(done))
    status = "PASS" if len(done)==len(plan["shots"]) else "PASS_PARTIAL"
    return report(status, film_id=plan["film_id"], plan=steps,
                  shots_ok=len(done), final=asm, results=results)

if __name__=="__main__": sys.exit(main())
