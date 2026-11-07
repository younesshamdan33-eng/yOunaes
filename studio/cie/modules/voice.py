"""Voice Intelligence — edge-tts (free) TTS."""
import asyncio
class VoiceIntelligence:
    VOICES = {"en-male":"en-US-GuyNeural","en-female":"en-US-JennyNeural",
              "ar-male":"ar-EG-ShakirNeural","ar-female":"ar-EG-SalmaNeural",
              "fr-female":"fr-FR-DeniseNeural"}
    def synth(self, text, voice, out_path):
        try: import edge_tts
        except ImportError: return {"ok":False,"error":"edge-tts missing"}
        v = self.VOICES.get(voice, voice)
        async def _(): await edge_tts.Communicate(text, v).save(out_path)
        try: asyncio.run(_()); return {"ok":True,"path":out_path,"voice":v}
        except Exception as e: return {"ok":False,"error":str(e)}
