"""Voice Intelligence — narration plan (text). TTS is separate (audio.tts)."""
DEFAULT_VOICE = "en-US-JennyNeural"

def narrate(plan, **kw):
    out = []
    for s in (plan or {}).get("scenes",[]):
        out.append({
            "scene_id": s.get("id",""),
            "text": f'We see: {s.get("location","")} at {s.get("time_of_day","day")}.'
        })
    return out
def voices_for(cast, **kw):
    return [{"name":c.get("name",""), "voice":DEFAULT_VOICE} for c in (cast or [])]
def voice_for(character, **kw): return DEFAULT_VOICE
