"""Error Recovery — retries individual shots without re-running the whole film."""
class ErrorRecovery:
    def __init__(self, max_retries=2): self.max_retries = max_retries
    def run(self, shot, generate_fn, state):
        for attempt in range(self.max_retries+1):
            try:
                result = generate_fn(shot)
                if result.get("ok"): return result
            except Exception as e:
                state.setdefault("errors",[]).append({"shot":shot.id,"attempt":attempt,"err":str(e)})
        return {"ok":False,"shot":shot.id,"attempts":self.max_retries+1}
