import asyncio, json, time

TTL = 86400

class VoicesError(Exception):
    pass

def fetch_remote():
    import edge_tts
    async def go():
        return await asyncio.wait_for(edge_tts.list_voices(), 20)
    return asyncio.run(go())

def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

def get_voices(cfg, lang=None):
    cache = cfg.root / "var" / "cache" / "voices.json"
    data = None
    if cache.exists() and time.time() - cache.stat().st_mtime < TTL:
        data = _read(cache)
    if data is None:
        try:
            raw = fetch_remote()
            data = [{"name": v["ShortName"], "locale": v["Locale"], "gender": v.get("Gender", "")} for v in raw]
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
        except ImportError:
            raise VoicesError("edge-tts is not installed")
        except Exception:
            data = _read(cache)
            if data is None:
                raise VoicesError("voice service unavailable (check the internet connection)")
    if lang:
        data = [v for v in data if v["locale"].lower().startswith(lang + "-")]
    return data
