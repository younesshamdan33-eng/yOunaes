"""Real-device smoke test: real edge-tts (needs internet) + real FFmpeg. Run: cinema smoke [voice]"""
import sys
from cinema_core import config
from . import render

def main():
    cfg = config.load()
    voice = sys.argv[1] if len(sys.argv) > 1 else "ar-MA-JamalNeural"
    project = {"title": "Smoke", "script": "مرحباً بكم في ستوديو سينما. هذا فيلم تجريبي قصير.",
               "script_lang": "ar", "subtitle_lang": "ar", "voice": voice, "profile": "preview"}
    base = cfg.root / "var" / "smoke"
    work, out = base / "work", base / "out"
    try:
        info = render.render_project(cfg, project, work, out, lambda p: print(f"  {p}%"), None, print)
    except render.RenderError as e:
        print(f"SMOKE FAILED: {e}")
        return 1
    finally:
        render.cleanup_work(work, base)
    print(f"SMOKE OK: {out / 'film.mp4'} {info}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
