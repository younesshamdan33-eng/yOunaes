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
