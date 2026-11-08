"""Cinema Engine Integration — API routes for AI video generation."""
import os, sys, json, time, threading, subprocess, shutil, tarfile, base64, uuid
from pathlib import Path
from flask import Blueprint, jsonify, request, send_from_directory

BASE = Path(__file__).parent.parent.resolve()
GENERATED = BASE / "static" / "cinema_videos"
GENERATED.mkdir(parents=True, exist_ok=True)

cinema_bp = Blueprint("cinema_api", __name__, url_prefix="/api/cinema")

# File-backed job store (persists across server restarts)
_JOBS = {}
_JOBS_LOCK = threading.Lock()
_WORKER_STARTED = False
_STORE_DIR = BASE / "var" / "cinema_jobs"
_STORE_DIR.mkdir(parents=True, exist_ok=True)


def _load_persisted_jobs():
    """Load existing jobs from disk at startup."""
    with _JOBS_LOCK:
        for f in _STORE_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "id" in data:
                    _JOBS[data["id"]] = data
            except Exception:
                pass


_load_persisted_jobs()


def _save_job_file(job_id: str):
    """Save a job dictionary to a file atomically."""
    job_data = _JOBS.get(job_id)
    if not job_data:
        return
    p = _STORE_DIR / f"{job_id}.json"
    tmp = p.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(job_data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def _new_job(prompt, style, lighting, camera, duration=5):
    job_id = uuid.uuid4().hex[:10]
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id, "prompt": prompt, "style": style,
            "lighting": lighting, "camera": camera,
            "duration": duration,
            "status": "queued", "message": "في الانتظار",
            "video_file": "", "kaggle_url": "",
            "created_at": time.time(), "updated_at": time.time()
        }
        _save_job_file(job_id)
    return job_id


def _update(job_id, **kw):
    with _JOBS_LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(kw, updated_at=time.time())
            _save_job_file(job_id)


def _get(job_id):
    with _JOBS_LOCK:
        return dict(_JOBS[job_id]) if job_id in _JOBS else None


def _build_kaggle_script(job_id, prompt, style, lighting, camera):
    engine_dir = BASE / "cinematic_engine"
    if not engine_dir.exists():
        raise RuntimeError("cinematic_engine not found")
    tar_path = BASE / f"var/engine_{job_id}.tar.gz"
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(engine_dir, arcname="cinematic_engine")
    with open(tar_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    tar_path.unlink()
    return f'''
import os, subprocess, sys, tarfile, base64
os.environ["HF_HOME"] = "/kaggle/temp/hf"
os.environ["TRANSFORMERS_CACHE"] = "/kaggle/temp/hf"
print("Installing...")
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "torch", "torchvision", "diffusers>=0.35.0", "transformers>=4.46.0",
    "accelerate", "safetensors", "sentencepiece", "protobuf",
    "opencv-python-headless", "imageio[ffmpeg]", "numpy", "Pillow",
    "huggingface_hub", "tqdm", "--use-deprecated=legacy-resolver"], check=False)
encoded = """{encoded}"""
with open("engine.tar.gz", "wb") as f:
    f.write(base64.b64decode(encoded))
with tarfile.open("engine.tar.gz", "r:gz") as tar:
    tar.extractall(".")
os.chdir("cinematic_engine")
sys.path.insert(0, os.getcwd())
from config import CinematicConfig
cfg = CinematicConfig(
    model_id="Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
    cache_dir="/kaggle/temp/model_cache",
    output_dir="/kaggle/working/out",
    look="{style}", lighting="{lighting}",
    shot_type="medium", camera_motion="{camera}",
    num_frames=49, height=480, width=832,
    enable_upscale=False, enable_frame_interpolation=False,
    preserve_original=False
)
os.makedirs(cfg.output_dir, exist_ok=True)
from pipeline import run_cinematic_engine
final_path = run_cinematic_engine({repr(prompt)}, cfg, output_name="{job_id}")
if not os.path.isfile(final_path) or os.path.getsize(final_path) < 1024:
    raise RuntimeError("Final video missing or empty: " + str(final_path))
print("FINAL_VIDEO=" + str(final_path), flush=True)
print("DONE", flush=True)
'''


def _push_to_kaggle(job):
    job_id = job["id"]
    kfile = Path.home() / ".kaggle" / "kaggle.json"
    if not kfile.exists():
        return None, "kaggle.json not found"
    username = json.load(open(kfile))["username"]
    slug = f"{username}/ui-{job_id}"
    kdir = BASE / "var" / f"ui_{job_id}"
    kdir.mkdir(parents=True, exist_ok=True)
    try:
        script = _build_kaggle_script(job_id, job["prompt"], job["style"], job["lighting"], job["camera"])
    except Exception as e:
        return None, f"build failed: {e}"
    (kdir / "script.py").write_text(script)
    meta = {
        "id": slug, "title": f"UI {job_id}", "code_file": "script.py",
        "language": "python", "kernel_type": "script", "is_private": True,
        "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": []
    }
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    r = subprocess.run(["kaggle", "kernels", "push", "-p", str(kdir)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return None, f"push failed: {(r.stderr or r.stdout)[:300]}"
    return slug, None


def _poll(slug, max_min=20):
    deadline = time.time() + max_min * 60
    while time.time() < deadline:
        r = subprocess.run(["kaggle", "kernels", "status", slug],
                           capture_output=True, text=True, timeout=60)
        s = (r.stdout or "").lower()
        if "complete" in s: return True, "complete"
        if "error" in s or "fail" in s: return False, "kaggle failure"
        time.sleep(30)
    return False, "timeout"


def _valid_mp4(path):
    path = Path(path)

    if not path.is_file() or path.stat().st_size < 1024:
        return False

    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=codec_type,width,height",
                    "-show_entries", "format=duration",
                    "-of", "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return False

            data = json.loads(result.stdout or "{}")
            streams = data.get("streams") or []
            fmt = data.get("format") or {}

            return bool(
                streams
                and streams[0].get("codec_type") == "video"
                and int(streams[0].get("width") or 0) > 0
                and int(streams[0].get("height") or 0) > 0
                and float(fmt.get("duration") or 0) > 0
            )

        except Exception as exc:
            print(f"[cinema-worker] ffprobe validation error: {exc}")
            return False

    try:
        import cv2

        cap = cv2.VideoCapture(str(path))
        try:
            if not cap.isOpened():
                return False
            ok, frame = cap.read()
            return bool(ok and frame is not None and frame.size > 0)
        finally:
            cap.release()

    except Exception:
        return False


def _download(slug, job_id):
    tmp = BASE / "var" / f"dl_{job_id}"
    tmp.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            ["kaggle", "kernels", "output", slug, "-p", str(tmp)],
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            return None, (
                "Kaggle output download failed: "
                + (result.stderr or result.stdout or "")[:500]
            )

        vids = [
            p for p in tmp.rglob("*")
            if p.is_file() and p.suffix.lower() == ".mp4"
        ]

        if not vids:
            return None, "Kaggle completed but returned no MP4 files"

        expected_name = f"{job_id}_cinematic.mp4"

        def priority(path):
            name = path.name.lower()

            if name == expected_name.lower():
                return 0
            if name.endswith("_cinematic.mp4"):
                return 1
            if not any(
                marker in name
                for marker in ("_raw.mp4", "_original.mp4", "_interp.mp4")
            ):
                return 2
            return 3

        vids.sort(key=lambda p: (priority(p), -p.stat().st_size))

        source = next(
            (p for p in vids if priority(p) < 3 and _valid_mp4(p)),
            None,
        )

        if source is None:
            return None, "No valid final MP4 found in Kaggle output"

        dest = GENERATED / f"{job_id}.mp4"
        partial = GENERATED / f".{job_id}.part.mp4"

        if partial.exists():
            partial.unlink()

        shutil.copy2(source, partial)

        if not _valid_mp4(partial):
            partial.unlink(missing_ok=True)
            return None, "Downloaded MP4 failed local validation"

        os.replace(partial, dest)

        if not _valid_mp4(dest):
            dest.unlink(missing_ok=True)
            return None, "Final video failed validation after installation"

        print(
            f"[cinema-worker] validated video: {dest} "
            f"({dest.stat().st_size} bytes)",
            flush=True,
        )

        return dest.name, None

    except Exception as exc:
        return None, f"Video download/validation error: {exc}"

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def _worker():
    print("[cinema-worker] started", flush=True)
    while True:
        try:
            queued = None
            with _JOBS_LOCK:
                for j in _JOBS.values():
                    if j["status"] == "queued":
                        queued = dict(j); break
            if not queued:
                time.sleep(5); continue

            jid = queued["id"]
            _update(jid, status="pushing", message="يُرسَل إلى Kaggle...")
            slug, err = _push_to_kaggle(queued)
            if err:
                _update(jid, status="failed", message=err); continue

            _update(jid, status="generating",
                    message="يُولِّد على Kaggle (5-7 دقائق)...",
                    kaggle_url=f"https://www.kaggle.com/code/{slug}")

            ok, msg = _poll(slug)
            if not ok:
                _update(jid, status="failed", message=msg); continue

            _update(jid, status="downloading", message="يُنزِّل الفيديو...")
            vname, err = _download(slug, jid)
            if err:
                _update(jid, status="failed", message=err); continue

            _update(jid, status="done", message="الفيديو جاهز", video_file=vname)
            shutil.rmtree(BASE / "var" / f"ui_{jid}", ignore_errors=True)
            print(f"[cinema-worker] {jid} done", flush=True)
        except Exception as e:
            print(f"[cinema-worker] err: {e}", flush=True)
            time.sleep(10)


def _ensure_worker():
    global _WORKER_STARTED
    if _WORKER_STARTED: return
    _WORKER_STARTED = True
    threading.Thread(target=_worker, daemon=True, name="cinema-worker").start()


# ============================ ROUTES ============================
@cinema_bp.route("/generate", methods=["POST"])
def generate():
    _ensure_worker()
    data = request.get_json() or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt required"}), 400
    if len(prompt) > 500:
        return jsonify({"error": "too long"}), 400
    try:
        dur = int(data.get("duration", 5))
    except (TypeError, ValueError):
        dur = 5
    dur = max(5, min(dur, 30))

    jid = _new_job(
        prompt,
        data.get("style", "cinematic_realistic"),
        data.get("lighting", "natural"),
        data.get("camera", "static"),
        duration=dur,
    )
    return jsonify({"job_id": jid, "status": "queued"}), 202


@cinema_bp.route("/job/<job_id>", methods=["GET"])
def job(job_id):
    j = _get(job_id)
    if not j:
        return jsonify({"error": "not found"}), 404
    return jsonify(j)


@cinema_bp.route("/jobs", methods=["GET"])
def jobs_list():
    with _JOBS_LOCK:
        return jsonify(list(_JOBS.values()))


@cinema_bp.route("/videos/<path:filename>")
def serve_video(filename):
    return send_from_directory(str(GENERATED), filename)


@cinema_bp.route("/health")
def health():
    engine = (BASE / "cinematic_engine").exists()
    kaggle = (Path.home() / ".kaggle" / "kaggle.json").exists()
    return jsonify({
        "engine_present": engine,
        "kaggle_configured": kaggle,
        "active_jobs": sum(1 for j in _JOBS.values() if j["status"] in ("queued","pushing","generating","downloading")),
        "total_jobs": len(_JOBS),
    })
