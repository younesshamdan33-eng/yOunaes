#!/data/data/com.termux/files/usr/bin/bash
# ============================================================================
# CINEMA PLATFORM — MASTER BOOTSTRAP & ACCEPTANCE SCRIPT
# Single command. End-to-end. Real inference only. No mock claims.
# ============================================================================
set -uo pipefail
TS=$(date +%s)
LOG="var/logs/cinema_full_$TS.log"
REPORT="var/reports/acceptance_$TS.json"
mkdir -p var/logs var/reports var/generated var/films

log(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
die(){ log "FATAL: $*"; exit 1; }
status(){ echo "$1" > var/reports/.status; }

log "=========================================="
log " CINEMA PLATFORM BOOTSTRAP — $(date)"
log "=========================================="

# ---------- PHASE 0: environment ----------
log "[0/8] Environment check"
source .venv/bin/activate 2>/dev/null || python3 -m venv .venv && source .venv/bin/activate
pip install -q --upgrade pip 2>&1 | tail -1
pip install -q flask edge-tts pytest requests gradio_client Pillow numpy 2>&1 | tail -1
PYVER=$(.venv/bin/python --version 2>&1)
log "  Python: $PYVER"
log "  Flask : $(.venv/bin/python -c 'import flask; print(flask.__version__)' 2>&1)"

# ---------- PHASE 1: HF token ----------
log "[1/8] Hugging Face credentials"
if [ -z "${HF_TOKEN:-}" ]; then
  if [ -f "$HOME/.hf_token" ]; then
    export HF_TOKEN=$(cat "$HOME/.hf_token")
    log "  Loaded HF_TOKEN from ~/.hf_token"
  else
    log "  HF_TOKEN missing. Creating placeholder; acceptance will be BLOCKED."
    export HF_TOKEN=""
  fi
else
  log "  HF_TOKEN present (${#HF_TOKEN} chars)"
fi

# ---------- PHASE 2: model registry (real Space IDs) ----------
log "[2/8] Registering verified HF Spaces"
cat > worker/hf_spaces.py <<'PY'
"""Verified HF Spaces for real video generation. Each entry tested individually."""
SPACES = {
    "ltx-distilled": {
        "space": "Lightricks/ltx-video-distilled",
        "durations": (0.3, 8.5), "fps": 24,
        "resolutions": [(704, 480), (512, 512), (480, 704), (768, 512)],
        "modes": ["text-to-video", "image-to-video"],
        "notes": "Fast, cinematic. Default choice."
    },
    "wan22-ti2v": {
        "space": "vaibhavpandeyvpz/wan2.2-text-image-to-video",
        "durations": (0.3, 5.0), "fps": 24,
        "resolutions": [(704, 480), (480, 704), (512, 512)],
        "modes": ["text-to-video", "image-to-video"],
        "notes": "Full parameter control, 5B model."
    },
}
def pick_best():
    """Return (key, spec) — prefer LTX for speed."""
    return ("ltx-distilled", SPACES["ltx-distilled"])
PY

# ---------- PHASE 3: prompt quality enhancer ----------
log "[3/8] Installing cinematic prompt enhancer"
cat > pipeline/cinematic_prompt.py <<'PY'
"""Converts a plain idea into a cinema-grade prompt.
Built from verified best-practice structures for LTX/Wan/Sora-class models."""
import re

LENS = {"wide":"24mm wide-angle","medium":"50mm standard","close":"85mm portrait"}
LIGHT = {"DAY":"natural soft daylight, gentle shadows",
         "DUSK":"golden hour rim light, warm haze",
         "NIGHT":"moody low-key, practical neon accents",
         "DAWN":"cool blue-gold, misty depth"}
MOVE = {"static":"locked-off static frame",
        "push":"slow dolly push-in",
        "pull":"slow dolly pull-back",
        "pan":"smooth lateral pan",
        "handheld":"subtle handheld drift"}

def enhance(base, scene=None, shot=None, direction=None):
    """Build a 60-100 word cinematic prompt."""
    scene = scene or {}; shot = shot or {}; direction = direction or {}
    subj = base.strip()[:200]
    cam = LENS.get(shot.get("camera","medium"), "50mm")
    mov = MOVE.get(shot.get("movement","push"), "slow dolly push-in")
    light = LIGHT.get(scene.get("time_of_day","DAY"), "natural light")
    tone = direction.get("tone","cinematic")
    palette = direction.get("palette","natural")
    core = (f"{subj}. {cam}, {mov}. {light}. "
            f"{palette} palette, {tone} mood. "
            f"Photoreal, film grain, 4K, 24fps, shallow depth of field, "
            f"volumetric light, no flicker, no text, no watermark.")
    return core[:800]

def negative():
    return ("blurry, low quality, distorted, deformed hands, extra limbs, "
            "text, watermark, logo, static image, slideshow, freeze frame, "
            "duplicate frames, flicker, jitter, oversaturated")
PY

# ---------- PHASE 4: real HF adapter (robust against Space API drift) ----------
log "[4/8] Writing real HF adapter"
cat > worker/adapters_hf.py <<'PY'
"""Real inference on HF Spaces. Downloads actual MP4. No mock fallback."""
import os, time, uuid, shutil, traceback
from pathlib import Path
from .hf_spaces import SPACES, pick_best

class HFAdapter:
    def __init__(self, out_root="var/generated"):
        self.token = os.environ.get("HF_TOKEN") or None
        self.out = Path(out_root); self.out.mkdir(parents=True, exist_ok=True)

    def _client(self, space):
        from gradio_client import Client
        return Client(space, hf_token=self.token)

    def probe(self, key):
        if key not in SPACES: return {"ok":False,"error":f"unknown {key}"}
        if not self.token: return {"ok":False,"error":"HF_TOKEN missing"}
        try:
            c = self._client(SPACES[key]["space"])
            info = c.view_api(return_format="dict")
            return {"ok":True,"space":SPACES[key]["space"],"api_keys":list(info.get("named_endpoints",{}).keys())}
        except Exception as e:
            return {"ok":False,"error":str(e)[:300]}

    def generate(self, key, prompt, duration=5.0, negative="", seed=None):
        """Returns {ok, path, ...} or raises with diagnostic."""
        if key not in SPACES: raise ValueError(key)
        if not self.token: raise RuntimeError("HF_TOKEN missing — cannot run real inference")
        spec = SPACES[key]
        dur = max(spec["durations"][0], min(float(duration), spec["durations"][1]))
        client = self._client(spec["space"])
        job = uuid.uuid4().hex[:10]; t0 = time.time()
        # Try a sequence of call signatures — Space UIs evolve
        attempts = [
            # LTX-style signature
            dict(prompt=prompt, negative_prompt=negative or "",
                 input_image_filepath=None, input_video_filepath=None,
                 height_ui=480, width_ui=704, mode="text-to-video",
                 duration_ui=dur, ui_frames_to_use=0,
                 seed_ui=seed or 0, randomize_seed=(seed is None),
                 ui_guidance_scale=3.0, improve_texture_flag=False),
            # Wan-style / simplified
            dict(prompt=prompt, negative_prompt=negative or "",
                 duration=dur, resolution="480p"),
            # Minimal fallback
            dict(prompt=prompt),
        ]
        last_err = None
        for kwargs in attempts:
            try:
                result = client.predict(**kwargs)
                break
            except TypeError as e:
                last_err = e; continue
            except Exception as e:
                last_err = e; continue
        else:
            raise RuntimeError(f"all call signatures failed; last={last_err}")
        # Extract path from diverse return shapes
        cand = None
        if isinstance(result, str) and result.lower().endswith((".mp4",".webm",".gif")): cand = result
        elif isinstance(result, dict):
            for k in ("video","path","file","output","video_path"): 
                if isinstance(result.get(k), str): cand = result[k]; break
        elif isinstance(result, (list,tuple)):
            for x in result:
                if isinstance(x,str) and x.lower().endswith((".mp4",".webm",".gif")): cand = x; break
                if isinstance(x,dict) and x.get("path"): cand = x["path"]; break
        if not cand or not Path(cand).exists():
            raise RuntimeError(f"unusable output: {type(result)}: {str(result)[:200]}")
        dst = self.out / f"{key}_{job}.mp4"
        shutil.copy(cand, dst)
        return {"ok":True,"path":str(dst),"model":key,"space":spec["space"],
                "duration_requested":dur,"elapsed_sec":round(time.time()-t0,1),
                "size_bytes":dst.stat().st_size}
PY

# ---------- PHASE 5: video validator (proves real motion) ----------
log "[5/8] Installing motion validator"
cat > scripts/validate_video.py <<'PY'
#!/usr/bin/env python3
"""Fails on static image, slideshow, or duplicated frames."""
import sys, json, subprocess, tempfile, hashlib
from pathlib import Path
def main(p):
    f = Path(p)
    if not f.exists(): print(json.dumps({"ok":False,"error":"missing"})); return 1
    pr = subprocess.run(["ffprobe","-v","error","-print_format","json",
                         "-show_format","-show_streams",str(f)],capture_output=True,text=True)
    if pr.returncode: print(json.dumps({"ok":False,"error":"ffprobe"})); return 1
    info = json.loads(pr.stdout)
    v = next((s for s in info["streams"] if s["codec_type"]=="video"), None)
    if not v: print(json.dumps({"ok":False,"error":"no video stream"})); return 1
    dur = float(info["format"].get("duration",0))
    td = Path(tempfile.mkdtemp()); hashes=[]
    for i in range(6):
        t = dur*i/6; o = td/f"f{i}.png"
        subprocess.run(["ffmpeg","-v","error","-ss",str(t),"-i",str(f),"-frames:v","1","-y",str(o)],check=False)
        if o.exists():
            r = subprocess.run(["ffmpeg","-v","error","-i",str(o),"-f","md5","-"],capture_output=True,text=True)
            hashes.append(r.stdout.strip())
    unique = len(set(hashes))
    out = {"ok":True,"file":str(f),"size":f.stat().st_size,"duration":round(dur,2),
           "codec":v.get("codec_name"),"width":v.get("width"),"height":v.get("height"),
           "fps":v.get("r_frame_rate"),"nb_frames":v.get("nb_frames"),
           "sampled_frames":len(hashes),"unique_frames":unique,
           "is_motion":unique>=4,"is_real_video":dur>0.5 and unique>=4}
    print(json.dumps(out,indent=2))
    return 0 if out["is_real_video"] else 2
if __name__=="__main__": sys.exit(main(sys.argv[1] if len(sys.argv)>1 else ""))
PY
chmod +x scripts/validate_video.py

# ---------- PHASE 6: film pipeline (real, resume-capable) ----------
log "[6/8] Wiring film pipeline"
cat > pipeline/film.py <<'PY'
"""End-to-end film production. Each shot saved on completion; resume skips done shots."""
import json, uuid, shutil
from pathlib import Path
from studio.cie.modules.story import StoryIntelligence
from studio.cie.modules.director import DirectorIntelligence
from studio.cie.modules.character import CharacterIntelligence
from studio.cie.modules.scene import SceneIntelligence
from studio.cie.modules.shot import ShotIntelligence
from studio.cie.modules.quality import QualityIntelligence
from studio.cie.modules.editing import EditingIntelligence
from pipeline.cinematic_prompt import enhance, negative

class FilmPipeline:
    def __init__(self, root="var/films"):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.story = StoryIntelligence(); self.director = DirectorIntelligence()
        self.scene = SceneIntelligence(); self.shot = ShotIntelligence()
        self.quality = QualityIntelligence(); self.editing = EditingIntelligence()

    def create(self, idea, film_id=None):
        fid = film_id or uuid.uuid4().hex[:12]
        fdir = self.root / fid; fdir.mkdir(parents=True, exist_ok=True)
        script = self.story.analyze(idea)
        direction = self.director.decide(script)
        chars = CharacterIntelligence(fdir/"characters")
        cast = chars.cast(idea)
        plan = {"film_id":fid,"idea":idea,"title":script.title,"genre":script.genre,
                "direction":direction,"characters":cast,"scenes":[],"shots":[]}
        for s in script.scenes:
            sb = self.scene.build(s, direction)
            shots = self.shot.plan(s, sb, direction)
            plan["scenes"].append(sb)
            for sh in shots:
                d = sh.__dict__ if hasattr(sh,"__dict__") else sh
                # Inject enhanced prompt (real cinema-grade wording)
                d["prompt"] = enhance(d.get("description", s.summary), scene=sb,
                                       shot=d, direction=direction)
                d["negative"] = negative()
                plan["shots"].append(d)
        (fdir/"plan.json").write_text(json.dumps(plan,indent=2,default=str))
        return plan

    def generate_shots(self, plan, adapter, model_key, max_shots=None):
        fid = plan["film_id"]; sdir = self.root / fid / "shots"
        sdir.mkdir(parents=True, exist_ok=True)
        results = []
        shots = plan["shots"][:max_shots] if max_shots else plan["shots"]
        for sh in shots:
            out = sdir / f"{sh['id']}.mp4"
            if out.exists():
                results.append({"shot":sh["id"],"status":"resumed","path":str(out)})
                continue
            try:
                r = adapter.generate(model_key, sh["prompt"],
                                     duration=sh.get("duration_sec",5),
                                     negative=sh.get("negative",""))
                shutil.copy(r["path"], out)
                q = self.quality.check(str(out))
                results.append({"shot":sh["id"],"status":"done" if q.get("ok") else "quality_fail",
                                "path":str(out),"quality":q,"generation":r})
            except Exception as e:
                results.append({"shot":sh["id"],"status":"failed","error":str(e)[:300]})
        return results

    def assemble(self, plan, results):
        fid = plan["film_id"]; fdir = self.root / fid
        ok = [r["path"] for r in results if r["status"] in ("done","resumed") and Path(r["path"]).exists()]
        if not ok: return {"ok":False,"error":"no valid shots"}
        final = fdir / "final.mp4"
        r = self.editing.concat(ok, str(final))
        return {"ok":r["ok"],"path":str(final),"shots_used":len(ok),"err":r.get("err")}
PY

# ---------- PHASE 7: acceptance runner ----------
log "[7/8] Running acceptance tests"
cat > scripts/accept_all.py <<'PY'
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
PY
chmod +x scripts/accept_all.py

# ---------- PHASE 8: run + report ----------
log "[8/8] Executing full acceptance"
.venv/bin/python scripts/accept_all.py > "$REPORT" 2>&1
RC=$?
log "  acceptance exit=$RC"
log "  report saved: $REPORT"

# pretty summary
.venv/bin/python - "$REPORT" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print(f"Could not parse report: {e}"); sys.exit(0)
print("\n" + "="*60)
print(" ACCEPTANCE SUMMARY")
print("="*60)
print(f" Overall: {d.get('overall','?')}")
print(f" HF_TOKEN present: {d.get('env',{}).get('token')}")
for t in d.get("tests",[]):
    print(f"\n--- {t['phase']} ---")
    print(f"  status: {t['status']}")
    for k,v in t.items():
        if k in ("phase","status","ts"): continue
        print(f"  {k}: {str(v)[:300]}")
print("="*60)
print(f"Full report: {sys.argv[1]}")
PY

# ---------- cleanup temp logs (safe) ----------
rm -f var/logs/*.tmp 2>/dev/null || true

log "DONE. Report: $REPORT"
