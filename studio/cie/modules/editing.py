"""Editing Intelligence — ffmpeg concat + subtitle burn + audio mix."""
import subprocess
from pathlib import Path
class EditingIntelligence:
    def concat(self, videos, out_path, extra_audio=None):
        lst = Path(out_path).with_suffix(".txt")
        lst.write_text("\n".join(f"file '{Path(p).resolve()}'" for p in videos))
        cmd = ["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst)]
        if extra_audio and Path(extra_audio).exists():
            cmd += ["-i",str(extra_audio),"-c:v","copy","-c:a","aac","-shortest"]
        else: cmd += ["-c","copy"]
        cmd.append(out_path)
        r = subprocess.run(cmd, capture_output=True, text=True)
        return {"ok":r.returncode==0,"path":out_path,"err":r.stderr[-400:] if r.returncode else None}
    def burn_subs(self, video, srt, out):
        r = subprocess.run(["ffmpeg","-y","-i",video,"-vf",f"subtitles={srt}","-c:a","copy",out],
                           capture_output=True, text=True)
        return {"ok":r.returncode==0,"path":out,"err":r.stderr[-400:] if r.returncode else None}
