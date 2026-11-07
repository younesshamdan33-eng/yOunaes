from pathlib import Path
def write_srt(lines, out_path):
    """lines: [{'start':sec,'end':sec,'text':str}]"""
    def fmt(t):
        h=int(t//3600); m=int((t%3600)//60); s=t%60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".",",")
    buf = []
    for i,l in enumerate(lines,1):
        buf.append(f"{i}\n{fmt(l['start'])} --> {fmt(l['end'])}\n{l['text']}\n")
    Path(out_path).write_text("\n".join(buf),encoding="utf-8")
    return str(out_path)
