import asyncio
from pathlib import Path
class TTS:
    VOICES = {"en":"en-US-JennyNeural","ar":"ar-EG-SalmaNeural","fr":"fr-FR-DeniseNeural"}
    def synth(self, text, out_path, lang="en"):
        try: import edge_tts
        except ImportError: return {"ok":False,"error":"edge-tts missing"}
        async def _(): await edge_tts.Communicate(text, self.VOICES.get(lang,"en-US-JennyNeural")).save(out_path)
        try: asyncio.run(_()); return {"ok":True,"path":out_path}
        except Exception as e: return {"ok":False,"error":str(e)}
