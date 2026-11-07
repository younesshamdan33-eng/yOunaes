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
