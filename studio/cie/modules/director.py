"""Director Intelligence — tone, palette, camera philosophy per genre."""
class DirectorIntelligence:
    TABLE = {
        "sci-fi":   ("cold epic","cyan/steel","wide + slow push-in","measured"),
        "thriller": ("tense","desat amber","handheld + tight OTS","accelerating"),
        "drama":    ("intimate","warm neutrals","static + slow dolly","lyrical"),
        "fantasy":  ("mythic","saturated","sweeping crane","epic"),
        "comedy":   ("bright","high-key","snap zooms","brisk"),
    }
    def decide(self, script):
        t = self.TABLE.get(getattr(script,"genre","drama"), ("neutral","natural","medium","steady"))
        return {"tone":t[0],"palette":t[1],"camera":t[2],"pacing":t[3]}
