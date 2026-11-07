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
