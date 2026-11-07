"""Quality Intelligence — ffprobe validation of generated clips."""
import subprocess, json
from pathlib import Path
class QualityIntelligence:
    def check(self, path):
        p = Path(path)
        if not p.exists(): return {"ok":False,"error":"missing"}
        r = subprocess.run(["ffprobe","-v","error","-print_format","json",
                            "-show_format","-show_streams",str(p)],capture_output=True,text=True)
        if r.returncode: return {"ok":False,"error":"ffprobe failed"}
        info = json.loads(r.stdout)
        v = next((s for s in info["streams"] if s["codec_type"]=="video"), None)
        if not v: return {"ok":False,"error":"no video stream"}
        d = float(info["format"].get("duration",0))
        return {"ok":d>=0.5,"duration":d,"width":v.get("width"),"height":v.get("height"),
                "fps":v.get("r_frame_rate"),"codec":v.get("codec_name")}
