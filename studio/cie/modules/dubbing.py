"""Dubbing Intelligence — lang swap via TTS. Lip sync: honest UNSUPPORTED."""
class DubbingIntelligence:
    def __init__(self, voice): self.voice = voice
    def dub(self, dialogue, target_lang, out_dir):
        clips = []
        for i,line in enumerate(dialogue):
            r = self.voice.synth(line["text"], f"{target_lang}-female", f"{out_dir}/dub_{i:03d}.mp3")
            clips.append({"line":line,"audio":r})
        return {"clips":clips,"lip_sync":"UNSUPPORTED (no verified tool wired)"}
