"""Remote GPU Worker adapter — HTTP client to a self-hosted worker.
Implements the same contract as HFAdapter. Enables private GPU deployment later."""
import os, requests, uuid, time
from pathlib import Path
class RemoteGPUAdapter:
    def __init__(self):
        self.url = os.environ.get("CW_REMOTE_URL"); self.token = os.environ.get("CW_REMOTE_TOKEN")
    def probe(self, model_key):
        if not self.url: return {"ok":False,"error":"CW_REMOTE_URL not set"}
        try: return {"ok":True,"info":requests.get(f"{self.url}/health", timeout=5).json()}
        except Exception as e: return {"ok":False,"error":str(e)}
    def generate(self, model_key, prompt, duration=5, **kw):
        if not self.url: raise RuntimeError("CW_REMOTE_URL not set")
        r = requests.post(f"{self.url}/generate", json={
            "model":model_key,"prompt":prompt,"duration":duration,**kw},
            headers={"Authorization":f"Bearer {self.token or ''}"}, timeout=1800)
        r.raise_for_status(); return r.json()
