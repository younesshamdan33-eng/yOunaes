"""Scene Intelligence — scene descriptions + shot plans."""
LIGHT = {"DAY":"natural soft","DUSK":"golden rim","NIGHT":"moody low-key","DAWN":"cool blue-gold"}

def build(scene, direction=None, **kw):
    s = scene or {}; d = direction or {}
    tod = s.get("time_of_day","DAY")
    return {
        "id": s.get("id",""), "scene_id": s.get("id",""),
        "location": s.get("location",""), "time_of_day": tod,
        "palette": d.get("palette",""), "lighting": LIGHT.get(tod,"balanced"),
        "env_prompt": f'{s.get("location","")}, {tod.lower()}, {d.get("palette","")}, {d.get("tone","")}',
    }
def describe(scene, **kw): return build(scene, **kw)
def plan(scenes, direction=None, **kw): return [build(s, direction, **kw) for s in (scenes or [])]
def from_story(story, direction=None, **kw): return plan((story or {}).get("scenes",[]), direction, **kw)
