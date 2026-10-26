import json
from pathlib import Path

LOCALES = Path(__file__).resolve().parent / "locales"
RTL = {"ar"}

def available():
    return sorted(p.stem for p in LOCALES.glob("*.json"))

def load(lang):
    if lang not in available():
        return None
    strings = json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
    return {"lang": lang, "dir": "rtl" if lang in RTL else "ltr", "strings": strings}
