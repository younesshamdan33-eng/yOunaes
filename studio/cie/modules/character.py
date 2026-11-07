"""Character Intelligence — role detection + identity design."""
import hashlib, json, re
from pathlib import Path

ROLES = {'nurse', 'brother', 'detective', 'hunter', 'teacher', 'pilot', 'villain', 'thief', 'heroine', 'officer', 'mother', 'stranger', 'actor', 'warrior', 'monk', 'knight', 'waiter', 'artist', 'friend', 'priest', 'police', 'astronaut', 'merchant', 'student', 'lawyer', 'chef', 'scientist', 'prince', 'president', 'hero', 'king', 'actress', 'son', 'witch', 'doctor', 'mayor', 'wizard', 'princess', 'agent', 'writer', 'musician', 'enemy', 'daughter', 'sister', 'queen', 'father', 'soldier', 'robot'}

class CharacterIntelligence:
    def __init__(self, storage):
        self.dir = Path(storage); self.dir.mkdir(parents=True, exist_ok=True)
    def detect_roles(self, text):
        low = (text or "").lower(); out = []
        for r in ROLES:
            if r in low: out.append(r.title())
        for m in re.finditer(r"\b([A-Z][a-z]{2,})\b", text or ""):
            n = m.group(1)
            if n.lower() not in {"the","and","but","when","where","after","with","from"}:
                out.append(n)
        seen=set(); unique=[]
        for n in out:
            if n.lower() not in seen: seen.add(n.lower()); unique.append(n)
        return unique or ["Protagonist"]
    def design(self, name, role="supporting", traits=None):
        traits = traits or {}
        h = hashlib.sha1(f"{name}|{role}".encode()).hexdigest()[:12]
        ident = {"name":name,"role":role,"identity_hash":h,
                 "age_range":traits.get("age","30s"),
                 "appearance":traits.get("appearance","unremarkable"),
                 "wardrobe":traits.get("wardrobe","contemporary"),
                 "voice_hint":traits.get("voice","neutral adult")}
        (self.dir/f"{h}.json").write_text(json.dumps(ident,indent=2))
        return ident
    def cast(self, idea):
        return [self.design(n, "lead" if i==0 else "supporting") for i,n in enumerate(self.detect_roles(idea))]
