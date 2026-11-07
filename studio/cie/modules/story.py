"""Story Intelligence — idea → structured script (rule-based, offline-capable)."""
from dataclasses import dataclass, field
import re, os
from pathlib import Path

@dataclass
class Scene:
    id: str; location: str; time_of_day: str; summary: str
    dialogue: list = field(default_factory=list)
    characters: list = field(default_factory=list)
    duration_seconds: float = 5.0

@dataclass
class Script:
    title: str; logline: str; genre: str
    scenes: list = field(default_factory=list)
    characters: list = field(default_factory=list)
    locations: list = field(default_factory=list)

class StoryIntelligence:
    def analyze(self, idea: str) -> Script:
        from .character import CharacterIntelligence as _CI
        words = re.findall(r"\w+", idea)
        title = " ".join(words[:6]) or "Untitled"
        genre = self._genre(idea)
        scenes = [
            Scene("S01","INT. SETUP","DAY",f"Establish: {idea[:80]}",duration_seconds=5),
            Scene("S02","EXT. EVENT","DUSK","Inciting incident.",duration_seconds=5),
            Scene("S03","INT. CONFLICT","NIGHT","Rising obstacle.",duration_seconds=5),
            Scene("S04","EXT. CLIMAX","DAWN","Climax + resolution.",duration_seconds=5),
        ]
        store = Path(os.environ.get("CW_CHAR_STORE","var/characters"))
        chars = _CI(store).cast(idea)[:6]
        locs = [{"name":s.location} for s in scenes]
        return Script(title, idea[:300], genre, scenes, chars, locs)

    def _genre(self, idea):
        low = idea.lower()
        table = {
            "sci-fi":["space","robot","future","alien","starship"],
            "thriller":["chase","murder","detective","escape","mystery","letter","police","investigation"],
            "fantasy":["magic","dragon","kingdom"],
            "comedy":["funny","laugh","joke"],
        }
        for g,kws in table.items():
            if any(k in low for k in kws): return g
        return "drama"
