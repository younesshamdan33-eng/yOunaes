"""Film Memory: persistent characters, locations, events and per-scene states. The identity text is what every prompt must carry."""
import zlib

PALETTES = ["navy blue and orange", "forest green and cream", "crimson and charcoal", "teal and sand", "violet and silver",
            "mustard yellow and brown", "white and sky blue", "burgundy and gold"]

def new_memory():
    return {"characters": {}, "locations": {}, "events": [], "relations": []}

def add_character(mem, name, role="person", look="", age="adult", gender=None, en_name=None, aliases=None, voice=None):
    cid = "c%d" % (len(mem["characters"]) + 1)
    mem["characters"][cid] = {"id": cid, "name": name, "en_name": en_name, "role": role or "person", "look": look, "age": age, "gender": gender,
                              "palette": PALETTES[zlib.crc32((name or role or cid).encode()) % len(PALETTES)], "voice": voice,
                              "aliases": [a for a in (aliases or []) if a], "refs": [], "states": {}}
    return cid

def add_location(mem, name, kind, look, aliases=None):
    lid = "l%d" % (len(mem["locations"]) + 1)
    mem["locations"][lid] = {"id": lid, "name": name, "kind": kind, "look": look, "aliases": [a for a in (aliases or []) if a], "refs": []}
    return lid

def core(ch):
    art = "an" if ch["age"][0] in "aeiou" else "a"
    s = "%s %s %s" % (art, ch["age"], ch["role"])
    if ch.get("look"):
        s += " " + ch["look"]
    s += ", " + ch["palette"] + " color accents"
    return ((ch["en_name"] + ", ") if ch.get("en_name") else "") + s

def _num(scene_id):
    try:
        return int(str(scene_id).lstrip("s"))
    except ValueError:
        return 0

def set_state(mem, cid, scene_id, note):
    mem["characters"][cid]["states"][str(_num(scene_id))] = note

def identity(mem, cid, scene_id=None):
    ch = mem["characters"][cid]
    text = core(ch)
    if scene_id is not None:
        keys = [int(k) for k in ch["states"] if int(k) <= _num(scene_id)]
        if keys:
            text += ", " + ch["states"][str(max(keys))]
    return text

def record_event(mem, scene_id, text):
    mem["events"].append({"scene": scene_id, "text": text[:200]})
