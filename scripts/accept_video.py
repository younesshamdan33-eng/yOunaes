#!/usr/bin/env python3
"""ACCEPTANCE TEST 1 — AI Video Studio.
Status: PASS/FAIL/BLOCKED. Never claims success without a real MP4 + motion check."""
import os, sys, json, subprocess
sys.path.insert(0, ".")
from worker.adapters_hf import HFAdapter

def report(status, **kw):
    print(json.dumps({"test":"ACCEPTANCE_VIDEO_STUDIO","status":status,**kw}, indent=2, default=str))
    return 0 if status=="PASS" else (1 if status=="FAIL" else 2)

def main():
    if not os.environ.get("HF_TOKEN"):
        return report("BLOCKED", reason="HF_TOKEN not set — no verified GPU worker available",
                      next_step="set HF_TOKEN then rerun")
    ad = HFAdapter()
    probe = ad.probe("ltx-video-hf")
    if not probe.get("ok"):
        return report("BLOCKED", reason=f"Space unreachable: {probe.get('error')}")
    prompt = "cinematic wide shot, lone astronaut on red dunes at sunset, volumetric light, 24fps"
    try:
        gen = ad.generate("ltx-video-hf", prompt, duration=5)
    except Exception as e:
        return report("FAIL", error=str(e)[:500], probe=probe)
    v = subprocess.run([sys.executable,"scripts/validate_video.py",gen["path"]],
                      capture_output=True,text=True)
    info = json.loads(v.stdout) if v.stdout else {"ok":False}
    if not info.get("ok") or not info.get("is_motion"):
        return report("FAIL", reason="generated file failed motion check", video=info, generation=gen)
    return report("PASS", model="ltx-video-hf", space=gen["space"],
                  generation=gen, video=info)

if __name__=="__main__": sys.exit(main())
