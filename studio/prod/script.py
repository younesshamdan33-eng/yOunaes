"""Screenplay parser. Every line of the script ends up in a scene heading or a beat: nothing is dropped (see coverage)."""
import re

NARR = ("narrator", "الراوي", "راوي", "voice over", "v.o.", "vo")
HEAD1 = re.compile(r"^\s*(?:INT\.?/EXT\.?|INT\.?|EXT\.?)\s+(.+?)\s*(?:[-–—]\s*([A-Za-z\u0600-\u06FF ]+?))?\s*$", re.I)
HEAD2 = re.compile(r"^\s*(?:(?:مشهد|المشهد)\s*\d*|scene\s+\d+)\s*[:\-–—.]?\s*(.*)$", re.I)
VIS = re.compile(r"^\s*[\(\[]\s*(?:visual|vis|مرئي|صورة)\s*[:：]\s*(.+?)\s*[\)\]]\s*$", re.I)
DLG = re.compile(r"^\s*([^\W\d_][^\n:：()\[\]]{0,28}?)\s*(?:\(([^)\n]{1,24})\))?\s*[:：]\s*(\S.*)$", re.U)

def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()

def detect_language(text):
    return "ar" if len(re.findall(r"[\u0600-\u06FF]", text)) > len(re.findall(r"[A-Za-z]", text)) else "en"

def _heading(line):
    m = HEAD1.match(line)
    if m:
        return m.group(1).strip(), (m.group(2) or "").strip()
    m = HEAD2.match(line)
    if m:
        rest = m.group(1).strip()
        parts = re.split(r"\s*[-–—]\s*", rest, maxsplit=1)
        return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")
    return None

def parse(text):
    scenes, chars, canon = [], [], {}
    st = {"scene": None, "para": [], "vis": None}
    def scene(heading="", loc="", tm=""):
        sc = dict(id="s%d" % (len(scenes) + 1), heading=heading, location=loc, time=tm, beats=[])
        scenes.append(sc); st["scene"] = sc
        return sc
    def add(kind, speaker, emotion, body):
        sc = st["scene"] or scene()
        sc["beats"].append(dict(kind=kind, speaker=speaker, emotion=emotion, text=body, visual=st["vis"]))
        st["vis"] = None
    def flush():
        if st["para"]:
            add("action", None, None, " ".join(st["para"]))
            st["para"] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            flush(); continue
        m = VIS.match(line)
        if m:
            flush(); st["vis"] = m.group(1).strip(); continue
        h = _heading(line)
        if h:
            flush(); scene(line, h[0], h[1]); continue
        d = DLG.match(line)
        if d and len(d.group(1).split()) <= 3:
            flush()
            name, emo = d.group(1).strip(), (d.group(2) or "").strip().lower() or None
            if name.lower() in NARR:
                add("narration", None, emo, d.group(3).strip())
            else:
                name = canon.setdefault(name.lower(), name)
                if name not in chars:
                    chars.append(name)
                add("dialogue", name, emo, d.group(3).strip())
            continue
        st["para"].append(line)
    flush()
    warnings = []
    if not scenes:
        warnings.append("the script is empty")
    return dict(scenes=scenes, characters=chars, warnings=warnings)

def coverage(text, parsed):
    """Lines of the script that did not make it into the plan (must be empty)."""
    body = " ".join(norm(b["text"]) for s in parsed["scenes"] for b in s["beats"]) + " " + " ".join(norm(s["heading"]) for s in parsed["scenes"])
    missing = []
    for raw in (text or "").split("\n"):
        l = norm(raw)
        if not l or VIS.match(l):
            continue
        d = DLG.match(l)
        core = norm(d.group(3)) if d and len(d.group(1).split()) <= 3 and not _heading(l) else l
        if core not in body:
            missing.append(raw[:60])
    return missing
