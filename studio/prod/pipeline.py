"""Producer: runs a planned project shot by shot (speech -> visual -> clip -> validation), then assembles, mixes music and validates the film.
Finished shots are never redone; failed shots can be retried alone; the project survives restarts."""
import json, os, shutil, subprocess, threading
from pathlib import Path
from studio import render
from . import check, compose, music, visuals, voices
from .plan import ProdError
from .store import set_shot

def _srt_time(t):
    ms = int(round(t * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)

class Producer:
    def __init__(self, root, store, reserve_mb=None):
        self.root, self.st = Path(root), store
        self.reserve = int(os.environ.get("CINEMA_PROD_RESERVE_MB", "150")) if reserve_mb is None else reserve_mb
        self.active, self.lk, self.sem = set(), threading.Lock(), threading.Semaphore(1)
    def start(self, pid):
        t = threading.Thread(target=self.run, args=(pid,), daemon=True)
        t.start()
        return t
    def _space(self, path, need_mb):
        free = shutil.disk_usage(path).free // 1048576
        if free - need_mb < self.reserve:
            raise ProdError("insufficient storage (%d MB free, %d MB reserved for the phone): free some space and resume" % (free, self.reserve))
    def _stopped(self, pid):
        return self.st.get(pid)["state"] == "cancelled"
    def _set(self, pid, state, error=None):
        self.st.update(pid, lambda x: x.update(state=state, error=error) if x["state"] != "cancelled" else None)
    def run(self, pid):
        with self.lk:
            if pid in self.active:
                return False
            self.active.add(pid)
        try:
            with self.sem:
                self._run(pid)
        except Exception as e:
            self._set(pid, "failed", ("%s" % e)[:300] or e.__class__.__name__)
        finally:
            with self.lk:
                self.active.discard(pid)
        return True
    def _run(self, pid):
        p = self.st.update(pid, lambda x: x.update(state="running", error=None) if x["state"] in ("planned", "interrupted", "failed", "cancelled") else None)
        if p["state"] != "running":
            return
        d = self.st.path(pid)
        for sub in ("audio", "clips", "work", "output"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        self._space(d, 30)
        for sc in p["scenes"]:
            for sh in sc["shots"]:
                if self._stopped(pid):
                    return
                if sh["state"] != "done":
                    self._shot(pid, p, sc, sh)
        if self._stopped(pid):
            return
        p = self.st.get(pid)
        bad = [sh["id"] for s in p["scenes"] for sh in s["shots"] if sh["state"] != "done"]
        if bad:
            return self._set(pid, "failed", "%d shot(s) failed (%s): retry them, only failed shots are redone" % (len(bad), ", ".join(bad[:5])))
        self._assemble(pid)
    def _speak(self, sh, path):
        last = None
        for v in [sh["voice"]] + list(sh.get("voice_alt") or []):
            try:
                voices.synth(sh["text"], v, path, emotion=sh.get("emotion"))
                return v
            except Exception as e:
                last = e
        raise ProdError("speech failed for every candidate voice (%s): voices need an internet connection" % (str(last) or "unknown"))
    def _shot(self, pid, p, sc, sh):
        s, d, sid = p["settings"], self.st.path(pid), sh["id"]
        work = d / "work" / sid
        try:
            self._space(d, 20)
            work.mkdir(parents=True, exist_ok=True)
            audio, adur, voice = None, None, sh["voice"]
            if s["voices"] and (sh["kind"] in ("dialogue", "narration") or s["narrate_actions"]):
                audio = d / "audio" / (sid + ".mp3")
                if not (audio.is_file() and audio.stat().st_size > 0):
                    voice = self._speak(sh, audio)
                adur = render.probe_duration(audio)
                if adur > 39.5:
                    raise ProdError("this line is %.0f s long: split it into shorter lines" % adur)
            dur = round(max(2.0, adur + 0.5), 2) if adur else float(s["action_seconds"])
            w, h = visuals.dims(s["resolution"], s["aspect_ratio"])
            n, used = int(dur * 24) + 1, "image_motion"
            try:
                if s["engine"] == "image_motion":
                    iw, ih = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1024, 1024)}[s["aspect_ratio"]]
                    img = visuals.fetch_image(sh["prompt"], iw, ih, sh["seed"], self.st.dir / "_cache")
                else:
                    used, img = "cards", visuals.gradient_image(work / "bg.ppm", s["look"], sid, w, h)
            except visuals.VisualError as e:
                if not s["allow_fallback"]:
                    raise ProdError(str(e))
                used, img = "cards (fallback: image service failed)", visuals.gradient_image(work / "bg.ppm", s["look"], sid, w, h)
            first, last = sc["shots"][0]["id"] == sid, sc["shots"][-1]["id"] == sid
            subs = (sh["text"], adur or dur) if (s["subtitles"] and audio and sh["kind"] in ("dialogue", "narration")) else None
            clip = d / "clips" / (sid + ".mp4")
            compose.clip(work, clip, img, visuals.zoom_head(sid, w, h, n), s["look"], w, h, dur, audio, subs, p["language"], first, last)
            bad = check.issues(clip, dur, need_motion=used == "image_motion")
            if bad:
                clip.unlink(missing_ok=True)
                raise ProdError("clip failed validation: " + "; ".join(bad))
            self.st.update(pid, lambda x: set_shot(x, sid, state="done", error=None, duration=dur, audio_duration=adur, clip="clips/%s.mp4" % sid, engine_used=used, voice=voice))
        except Exception as e:
            msg = (str(e) or e.__class__.__name__)[:300]
            self.st.update(pid, lambda x: set_shot(x, sid, state="failed", error=msg, attempts=sh.get("attempts", 0) + 1))
        finally:
            shutil.rmtree(work, ignore_errors=True)
    def _assemble(self, pid):
        p, d = self.st.get(pid), self.st.path(pid)
        s = p["settings"]
        shots = [sh for sc in p["scenes"] for sh in sc["shots"]]
        clips = [d / sh["clip"] for sh in shots]
        self._space(d, int(sum(c.stat().st_size for c in clips) * 2 / 1048576) + 20)
        lst, raw, final = d / "work" / "list.txt", d / "work" / "film_raw.mp4", d / "output" / "film.mp4"
        lst.write_text("".join("file '%s'\n" % c for c in clips))
        r = subprocess.run(["ffmpeg", "-y", "-nostats", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(raw)], capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            return self._set(pid, "failed", "concat failed: " + (r.stderr or "")[-200:])
        if s["music"]:
            bed = d / "work" / "bed.m4a"
            music.make_bed(bed, 90, music.mood_for(s["look"]))
            fc = ("[0:a]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[v1][v2];[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=0.30[m];"
                  "[m][v2]sidechaincompress=threshold=0.03:ratio=10:attack=20:release=400[md];[v1][md]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
            r = subprocess.run(["ffmpeg", "-y", "-nostats", "-loglevel", "error", "-i", str(raw), "-stream_loop", "-1", "-i", str(bed), "-filter_complex", fc, "-map", "0:v:0", "-map", "[a]",
                                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(final)], capture_output=True, text=True, timeout=3600)
            if r.returncode != 0:
                return self._set(pid, "failed", "music mix failed: " + (r.stderr or "")[-200:])
        else:
            shutil.copy(raw, final)
        total = sum(sh["duration"] for sh in shots)
        bad = []
        try:
            info = check.probe(final)
            if abs(info["duration"] - total) > max(1.0, total * 0.03):
                bad.append("duration %.1fs, expected about %.1fs" % (info["duration"], total))
            if not info["has_audio"]:
                bad.append("no audio stream")
            if s["engine"] == "image_motion" and not any("fallback" in (sh["engine_used"] or "") for sh in shots):
                mo = check.motion(final, info["duration"], 12)
                if mo is None or max(mo) < 0.6:
                    bad.append("final film shows no real motion")
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as e:
            bad.append("final file unreadable: %s" % e)
        if bad:
            final.unlink(missing_ok=True)
            return self._set(pid, "failed", "final validation failed: " + "; ".join(bad))
        t, lines = 0.0, []
        for sh in shots:
            if sh["audio_duration"] and s["subtitles"] and sh["kind"] in ("dialogue", "narration"):
                for a, b, txt in render.timed_chunks(sh["text"], sh["audio_duration"]):
                    lines.append("%d\n%s --> %s\n%s\n" % (len(lines) + 1, _srt_time(t + a), _srt_time(t + b), txt))
            t += sh["duration"]
        (d / "output" / "film.srt").write_text("\n".join(lines), encoding="utf-8")
        (d / "output" / "manifest.json").write_text(json.dumps({"settings": s, "voices": p["voices"], "characters": p["characters"], "engine_notes": {
            "visuals": "AI-generated still per shot (Pollinations) animated by camera motion; NOT generative video" if s["engine"] == "image_motion" else "procedural gradient + camera motion; NOT AI",
            "music": "procedural ambient bed (not composed music)" if s["music"] else None, "voices": "edge-tts Neural voices (free online service)" if s["voices"] else None},
            "shots": [{k: sh[k] for k in ("id", "kind", "speaker", "duration", "engine_used", "voice", "seed", "prompt")} for sh in shots]}, ensure_ascii=False, indent=1))
        shutil.rmtree(d / "work", ignore_errors=True)
        self.st.update(pid, lambda x: x.update(state="done", error=None, output={"path": "output/film.mp4", "duration": round(info["duration"], 2), "size_bytes": info["size"],
                                                                               "width": info["width"], "height": info["height"]}))
    def retry_failed(self, pid):
        def fn(x):
            if x["state"] == "running":
                raise ProdError("project is running")
            n = 0
            for sc in x["scenes"]:
                for sh in sc["shots"]:
                    if sh["state"] == "failed":
                        sh.update(state="pending", error=None); n += 1
            if not n:
                raise ProdError("no failed shots")
            x["state"], x["error"] = "interrupted", None
        return self.st.update(pid, fn)
    def cancel(self, pid):
        def fn(x):
            if x["state"] not in ("running", "interrupted", "planned"):
                raise ProdError("project is not active")
            x["state"] = "cancelled"
        return self.st.update(pid, fn)
