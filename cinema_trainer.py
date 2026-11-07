#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CINEMA TRAINER v0.2 — ملف واحد: بيانات + ذاكرة + تدريب LoRA قابل للاستئناف + جودة + تقييم + Kaggle.

من Termux (يلزم فقط:  pip install kaggle  +  ~/.kaggle/kaggle.json):
    python cinema_trainer.py kaggle-push --slug USERNAME/cinema-train --config cfg.json
    python cinema_trainer.py kaggle-status --slug USERNAME/cinema-train
    python cinema_trainer.py kaggle-output --slug USERNAME/cinema-train --dest out/

على Kaggle أو أي GPU:  python cinema_trainer.py --config cfg.json pipeline
اختبار ذاتي بلا GPU:    python cinema_trainer.py selftest

حالة التحقق (صريحة):
  [مختبر فعلياً بدون GPU] scan/dedup/captions/manifest، CheckpointManager (ذرّي + fallback)،
        Resources/tiers، enhance (مسار ffmpeg)، metrics/compare، plan.
  [غير مختبر — يحتاج GPU + diffusers] prepare (VAE/T5)، train، generate، Real-ESRGAN، RIFE، CLIP.
"""
from __future__ import annotations
import argparse, base64, dataclasses, fnmatch, gc, glob, gzip, hashlib, json, logging, math
import os, pickle, queue, random, shutil, signal, sqlite3, subprocess, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    import numpy as np
except ImportError:  # Termux الخفيف يكفيه kaggle-push
    np = None
try:
    import psutil
except ImportError:
    psutil = None

VERSION = "0.2.0"
PREP_VERSION = "prep-2"  # غيّره لإبطال الكاش القديم
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
log = logging.getLogger("cinema")
STOP = threading.Event()

# ============================================================ الإعدادات
@dataclasses.dataclass
class Config:
    work_dir: str = "./cinema_work"
    data_dirs: list = dataclasses.field(default_factory=list)
    resume_dirs: list = dataclasses.field(default_factory=list)   # يقبل glob
    fetch: list = dataclasses.field(default_factory=list)         # [{repo,pattern,max_gb,accept_license}]
    captions_files: list = dataclasses.field(default_factory=list)
    model_id: str = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
    shots_file: str = ""  # JSON project shots file
    stages: list = dataclasses.field(default_factory=lambda: [
        "fetch", "scan", "captions", "manifest", "prepare", "baseline", "train", "generate", "eval", "compare"])
    # بيانات
    workers: int = 2
    chunk: int = 128
    min_duration: float = 1.5
    min_side: int = 256
    min_quality: float = 0.35
    dup_hamming: int = 3
    windows: int = 1
    category: str = ""
    manifest_limit: int = 0
    # ذاكرة/كاش
    ram_limit: float = 0.85
    cache_gb: float = 8.0
    min_free_disk_gb: float = 2.0
    prefetch: int = 3
    tier: int = -1                 # -1 = تلقائي حسب VRAM
    fps: int = 16
    # تدريب
    max_steps: int = 2000
    grad_accum: int = 4
    lr: float = 1e-4
    wd: float = 1e-2
    warmup: int = 50
    lora_rank: int = 16
    lora_alpha: int = 16
    flow_shift: float = 3.0
    grad_ckpt: bool = True
    ckpt_every: int = 100
    keep_ckpts: int = 3
    max_hours: float = 10.5        # جلسة Kaggle ≈ 12 ساعة
    log_every: int = 10
    seed: int = 42
    # توليد/تقييم
    gen_steps: int = 30
    gen_frames: int = 33
    gen_h: int = 320
    gen_w: int = 576
    eval_n: int = 4
    eval_tol: float = 0.05
    use_clip: bool = False
    # جودة
    sr: str = "auto"               # auto|realesrgan|ffmpeg
    rife_cmd: str = ""             # مثال: "python /path/Practical-RIFE/inference_video.py --multi=2 --video={inp} --output={out}"

    @staticmethod
    def load(path=None, **over):
        c = Config()
        if path and Path(path).exists():
            d = json.loads(Path(path).read_text(encoding="utf-8"))
            for k, v in d.items():
                if hasattr(c, k):
                    setattr(c, k, v)
                else:
                    log.warning("مفتاح إعداد مجهول: %s", k)
        for k, v in over.items():
            if v is not None and hasattr(c, k):
                setattr(c, k, v)
        return c

    @property
    def wd_path(self):
        p = Path(self.work_dir); p.mkdir(parents=True, exist_ok=True); return p

# ============================================================ أدوات عامة
def ffmpeg_bin():
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise RuntimeError("ffmpeg غير موجود (pkg install ffmpeg / pip install imageio-ffmpeg)")

def sh(cmd, timeout=180):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)

def atomic_write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    with open(tmp, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def jdump(obj, path):
    atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=1, default=str))

def sha256_file(p, blk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(blk)
            if not b: break
            h.update(b)
    return h.hexdigest()

def setup_logging(cfg):
    fmt = "%(asctime)s %(levelname)s %(message)s"
    hs = [logging.StreamHandler(sys.stdout)]
    try:
        hs.append(logging.FileHandler(cfg.wd_path / "cinema.log", encoding="utf-8"))
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=hs, force=True)

# ============================================================ إدارة الموارد
TIERS = [(33, 480, 832), (25, 384, 672), (17, 320, 576), (13, 256, 448), (9, 192, 320)]  # frames=4k+1, أبعاد /16

class Resources:
    def __init__(self, cfg): self.cfg = cfg
    def snapshot(self):
        s = {"ts": time.time()}
        if psutil:
            vm = psutil.virtual_memory()
            s.update(ram_used_frac=vm.percent / 100, ram_total_gb=round(vm.total / 2**30, 1),
                     cpu=psutil.cpu_percent(None), cpus=psutil.cpu_count())
        try:
            du = shutil.disk_usage(self.cfg.wd_path); s["disk_free_gb"] = round(du.free / 2**30, 1)
        except Exception: pass
        try:
            import torch
            if torch.cuda.is_available():
                free, total = torch.cuda.mem_get_info()
                s.update(gpu=torch.cuda.get_device_name(0), vram_total_gb=round(total / 2**30, 1),
                         vram_free_gb=round(free / 2**30, 1), cc=list(torch.cuda.get_device_capability(0)))
        except Exception: pass
        return s
    def ram_high(self):
        return bool(psutil and psutil.virtual_memory().percent / 100 > self.cfg.ram_limit)
    def pick_tier(self):
        if self.cfg.tier >= 0:
            return min(self.cfg.tier, len(TIERS) - 1)
        v = self.snapshot().get("vram_total_gb", 0)
        return 0 if v >= 40 else 1 if v >= 22 else 2 if v >= 14 else 3 if v >= 8 else 4

class Status:
    def __init__(self, cfg): self.p = cfg.wd_path / "status.json"; self.d = {}
    def update(self, **kw):
        self.d.update(kw, updated=time.strftime("%Y-%m-%d %H:%M:%S")); jdump(self.d, self.p)

# ============================================================ الفيديو: probe + مقاييس
def probe(path):
    ff = shutil.which("ffprobe")
    if ff:
        r = sh([ff, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], 30)
        if r.returncode != 0: return None
        try: j = json.loads(r.stdout)
        except Exception: return None
        vs = [s for s in j.get("streams", []) if s.get("codec_type") == "video"]
        if not vs: return None
        v = vs[0]
        num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1").split("/")
        fps = float(num) / float(den) if float(den) else 0.0
        dur = float(v.get("duration") or j.get("format", {}).get("duration") or 0)
        return dict(duration=dur, fps=fps, width=int(v.get("width", 0)), height=int(v.get("height", 0)),
                    has_audio=int(any(s.get("codec_type") == "audio" for s in j["streams"])))
    import re
    r = sh([ffmpeg_bin(), "-hide_banner", "-i", str(path)], 30); t = r.stderr.decode("utf-8", "ignore")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", t); s = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", t)
    f = re.search(r"([\d.]+) fps", t)
    if not (m and s): return None
    return dict(duration=int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]), fps=float(f[1]) if f else 0.0,
                width=int(s[1]), height=int(s[2]), has_audio=int("Audio:" in t))

def read_gray(path, n, dur, size=(256, 144), dense=False):
    w, h = size
    if dense:
        vf, cnt, tlim = f"scale={w}:{h}", n, []
    else:
        span = max(0.5, min(dur, 60.0)); vf, cnt, tlim = f"fps={n / span:.6f},scale={w}:{h}", n, ["-t", f"{span}"]
    r = sh([ffmpeg_bin(), "-v", "error", *tlim, "-i", str(path), "-vf", vf, "-frames:v", str(cnt),
            "-f", "rawvideo", "-pix_fmt", "gray", "-"], 120)
    buf = r.stdout; k = len(buf) // (w * h)
    if k == 0: return None
    return np.frombuffer(buf[:k * w * h], dtype=np.uint8).reshape(k, h, w)

def frame_metrics(fr):
    f = fr.astype(np.float32)
    lap = 4 * f[:, 1:-1, 1:-1] - f[:, :-2, 1:-1] - f[:, 2:, 1:-1] - f[:, 1:-1, :-2] - f[:, 1:-1, 2:]
    d = dict(sharp=float(lap.var(axis=(1, 2)).mean()), bright=float(f.mean() / 255))
    if len(f) > 1:
        d["motion"] = float((np.abs(f[1:] - f[:-1]).mean(axis=(1, 2)) / 255).mean())
        d["flicker"] = float(np.abs(np.diff(f.mean(axis=(1, 2)) / 255)).mean())
    else:
        d["motion"] = d["flicker"] = 0.0
    return d

def dhash(g):
    g = g[:, :252].astype(np.float32)[:144].reshape(8, 18, 9, 28).mean((1, 3))
    bits = (g[:, 1:] > g[:, :-1]).flatten(); v = 0
    for b in bits: v = (v << 1) | int(b)
    return v  # 56 bits كافية (8x7)

def hamming(a, b): return bin(a ^ b).count("1")

def score_clip(r, cfg):
    res = min(1.0, min(r["width"], r["height"]) / 720)
    sh_s = min(1.0, math.log10(1 + r["sharp"]) / 2.5)
    mo = r["motion"]
    mo_s = 0.0 if mo < 0.002 else mo / 0.02 if mo < 0.02 else 1.0 if mo <= 0.25 else max(0.0, 1 - (mo - 0.25) / 0.25)
    ex = 1.0 if 0.12 <= r["bright"] <= 0.88 else 0.3
    fp_s = 1.0 if r["fps"] >= 16 else r["fps"] / 16
    q = 0.3 * res + 0.3 * sh_s + 0.2 * min(1.0, mo_s) + 0.1 * ex + 0.1 * fp_s
    why = []
    if min(r["width"], r["height"]) < cfg.min_side: why.append("low_resolution")
    if mo < 0.002: why.append("static")
    if q < cfg.min_quality: why.append(f"quality_{q:.2f}<{cfg.min_quality}")
    return round(q, 4), why

def fingerprint(path, size=None):
    """Full-file SHA-256, streamed with bounded memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def analyze(path, cfg):
    r = {"path": str(path), "status": "ok", "reason": ""}
    try:
        size = os.path.getsize(path); r["size"] = size; r["fp"] = fingerprint(path, size)
        info = probe(path)
        if not info or info["width"] <= 0:
            r.update(status="corrupt", reason="probe_failed"); return r
        r.update(info)
        fr = read_gray(path, 6, info["duration"])
        if fr is None or len(fr) < 2:
            r.update(status="corrupt", reason="decode_failed"); return r
        r.update(frame_metrics(fr)); r["phash"] = _s64(dhash(fr[len(fr) // 2]))
        if info["duration"] < cfg.min_duration:
            r.update(status="rejected", reason="too_short"); r["quality"] = 0.0; return r
        q, why = score_clip(r, cfg); r["quality"] = q
        if why: r.update(status="rejected", reason=",".join(why))
    except Exception as e:
        r.update(status="corrupt", reason=f"exception:{e!r}"[:200])
    return r

# ============================================================ قاعدة البيانات (Manifest)
CATEGORY_KW = {
    "anime": ["anime", "manga"], "cartoon": ["cartoon", "animation", "animated", "3d render", "pixar-style"],
    "human": ["man ", "woman", "person", "people", "girl", "boy", "face", "portrait", "walking", "dancing"],
    "nature": ["forest", "mountain", "ocean", "sea", "river", "sky", "nature", "wildlife", "beach"],
    "architecture": ["city", "building", "street", "skyline", "architecture", "interior", "room"],
    "cinematic": ["cinematic", "film", "movie", "dolly", "tracking shot", "anamorphic", "drone"],
}
def guess_category(caption, path):
    t = f"{caption or ''} {path}".lower()
    for cat, kws in CATEGORY_KW.items():
        if any(k in t for k in kws): return cat
    return "other"

class DB:
    def __init__(self, cfg):
        self.con = sqlite3.connect(str(cfg.wd_path / "dataset.db"), timeout=60, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS clips(id INTEGER PRIMARY KEY, path TEXT UNIQUE, size INT, mtime REAL, fp TEXT,
          status TEXT, reason TEXT, duration REAL, fps REAL, width INT, height INT, has_audio INT, quality REAL,
          sharp REAL, motion REAL, bright REAL, flicker REAL, caption TEXT, category TEXT, phash INT, prep TEXT);
        CREATE INDEX IF NOT EXISTS i_fp ON clips(fp); CREATE INDEX IF NOT EXISTS i_status ON clips(status);
        CREATE TABLE IF NOT EXISTS bands(band INT, val INT, clip_id INT);
        CREATE INDEX IF NOT EXISTS i_bands ON bands(band,val);
        CREATE TABLE IF NOT EXISTS captions(key TEXT PRIMARY KEY, caption TEXT);
        CREATE TABLE IF NOT EXISTS cache(clip_id INT, win INT, ckey TEXT, path TEXT, bytes INT, last_used REAL,
          PRIMARY KEY(clip_id,win,ckey));
        CREATE TABLE IF NOT EXISTS skip(clip_id INT, ckey TEXT, reason TEXT, PRIMARY KEY(clip_id,ckey));""")
    def stats(self):
        q = self.con.execute
        return {"status": dict(q("SELECT status,COUNT(*) FROM clips GROUP BY status").fetchall()),
                "ok_by_category": dict(q("SELECT category,COUNT(*) FROM clips WHERE status='ok' GROUP BY category").fetchall()),
                "captioned_ok": q("SELECT COUNT(*) FROM clips WHERE status='ok' AND caption IS NOT NULL AND caption!=''").fetchone()[0]}

def iter_videos(dirs):
    """Yield video files in deterministic order without materializing the tree."""
    roots = sorted({os.path.abspath(str(d)) for d in dirs})
    for root in roots:
        for current, subdirs, files in os.walk(root, topdown=True, followlinks=False):
            subdirs[:] = sorted(
                d for d in subdirs
                if not os.path.islink(os.path.join(current, d))
            )
            for name in sorted(files):
                if os.path.splitext(name)[1].lower() not in VIDEO_EXT:
                    continue
                path = os.path.join(current, name)
                try:
                    st = os.stat(path, follow_symlinks=False)
                    if not os.path.isfile(path):
                        continue
                    yield path, st.st_size, st.st_mtime
                except OSError:
                    continue

def _s64(v): return v - (1 << 64) if v >= (1 << 63) else v

def _store(db, r, cfg):
    c = db.con; ph = r.get("phash"); dup_of = None
    row = c.execute("SELECT id FROM clips WHERE path=?", (r["path"],)).fetchone(); own = row[0] if row else -1
    if r["status"] == "ok":
        d = c.execute("SELECT id FROM clips WHERE fp=? AND status='ok' AND id!=? LIMIT 1", (r["fp"], own)).fetchone()
        if d: dup_of = d[0]
        elif ph is not None:
            cands = set()
            for b in range(4):
                for (cid,) in c.execute("SELECT clip_id FROM bands WHERE band=? AND val=?", (b, (ph >> (14 * b)) & 0x3FFF)):
                    if cid != own: cands.add(cid)
            for cid in cands:
                o = c.execute("SELECT phash FROM clips WHERE id=? AND status='ok'", (cid,)).fetchone()
                if o and hamming(ph, o[0]) <= cfg.dup_hamming: dup_of = cid; break
        if dup_of: r["status"], r["reason"] = "dup", f"duplicate_of:{dup_of}"
    sidecar = Path(r["path"]).with_suffix(".txt"); cap = None
    if sidecar.exists():
        try: cap = sidecar.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError: pass
    cols = dict(size=r.get("size"), mtime=r["mtime"], fp=r.get("fp"), status=r["status"], reason=r["reason"],
                duration=r.get("duration"), fps=r.get("fps"), width=r.get("width"), height=r.get("height"),
                has_audio=r.get("has_audio"), quality=r.get("quality"), sharp=r.get("sharp"), motion=r.get("motion"),
                bright=r.get("bright"), flicker=r.get("flicker"), phash=ph, prep=PREP_VERSION)
    if cap: cols["caption"] = cap; cols["category"] = guess_category(cap, r["path"])
    if row:
        c.execute("DELETE FROM bands WHERE clip_id=?", (own,))
        c.execute(f"UPDATE clips SET {','.join(k + '=?' for k in cols)} WHERE id=?", (*cols.values(), own)); cid = own
    else:
        cols["path"] = r["path"]
        cur = c.execute(f"INSERT INTO clips({','.join(cols)}) VALUES({','.join('?' * len(cols))})", tuple(cols.values()))
        cid = cur.lastrowid
    if r["status"] == "ok" and ph is not None:
        for b in range(4): c.execute("INSERT INTO bands VALUES(?,?,?)", (b, (ph >> (14 * b)) & 0x3FFF, cid))

def scan(cfg, db=None):
    db = db or DB(cfg); t0 = time.time(); done = skipped = 0; batch = []
    def flush():
        nonlocal done, batch
        if not batch: return
        with ThreadPoolExecutor(max_workers=max(1, cfg.workers)) as ex:
            res = list(ex.map(lambda x: analyze(x[0], cfg), batch))
        for (p, sz, mt), r in zip(batch, res):
            r["mtime"] = mt; r.setdefault("size", sz); _store(db, r, cfg)
        db.con.commit(); done += len(batch); batch = []
        log.info("scan: معالَج=%d متخطّى=%d (%.0fs)", done, skipped, time.time() - t0)
    for p, sz, mt in iter_videos(cfg.data_dirs):
        if STOP.is_set(): break
        row = db.con.execute("SELECT size,mtime,prep FROM clips WHERE path=?", (p,)).fetchone()
        if row and row[0] == sz and abs(row[1] - mt) < 1e-3 and row[2] == PREP_VERSION:
            skipped += 1; continue
        batch.append((p, sz, mt))
        if len(batch) >= cfg.chunk:
            flush()
            if psutil and Resources(cfg).ram_high(): cfg.workers = max(1, cfg.workers - 1); gc.collect(); log.warning("ضغط RAM: workers=%d", cfg.workers)
    flush()
    s = db.stats(); log.info("scan انتهى: %s", s); return {"processed": done, "skipped": skipped, **s}

def import_captions(cfg, db, file):
    import csv
    keys_p = ["path", "file", "file_name", "filename", "video", "video_path", "name"]
    keys_c = ["caption", "text", "prompt", "description"]
    n = 0
    def rows():
        if str(file).endswith((".jsonl", ".ndjson")):
            with open(file, encoding="utf-8") as f:
                for ln in f:
                    if ln.strip(): yield json.loads(ln)
        else:
            with open(file, encoding="utf-8", newline="") as f:
                yield from csv.DictReader(f)
    for r in rows():
        k = next((r[x] for x in keys_p if r.get(x)), None); c = next((r[x] for x in keys_c if r.get(x)), None)
        if k and c:
            db.con.execute("INSERT OR REPLACE INTO captions VALUES(?,?)", (os.path.basename(str(k)).lower(), str(c))); n += 1
            if n % 5000 == 0: db.con.commit()
    db.con.commit(); log.info("captions: %d من %s", n, file); return n


def import_tom_jerry_captions(cfg, db):
    import os, json
    # ابحث عن captions.txt و videos.txt في كل مكان داخل data_dirs
    base = None
    for d in cfg.data_dirs:
        for root, dirs, files in os.walk(d):
            if 'captions.txt' in files and 'videos.txt' in files:
                base = Path(root)
                break
        if base: break
    if base is None:
        log.warning('captions.txt/videos.txt not found — using auto-captions')
        n = 0
        for row in db.con.execute("SELECT id FROM clips WHERE status='ok'").fetchall():
            db.con.execute("UPDATE clips SET caption=? WHERE id=?",
                           ("Tom and Jerry cartoon scene, animated, vibrant colors", row[0]))
            n += 1
        db.con.commit()
        log.info('Auto-generated captions for %d clips', n)
        return

    cap_file = base / 'captions.txt'
    vid_file = base / 'videos.txt'
    with open(cap_file, 'r', encoding='utf-8') as f:
        caps = [line.strip() for line in f if line.strip()]
    with open(vid_file, 'r', encoding='utf-8') as f:
        vids = [line.strip() for line in f if line.strip()]
    log.info('Tom & Jerry: %d captions, %d video paths', len(caps), len(vids))
    for cap, vid in zip(caps, vids):
        # key = اسم الملف فقط (بدون مسار)
        key = os.path.basename(vid).lower()
        db.con.execute('INSERT OR REPLACE INTO captions VALUES(?,?)', (key, cap))
    db.con.commit()
    log.info('Tom & Jerry captions imported: %d', len(caps))
    with open(cap_file, 'r', encoding='utf-8') as f:
        caps = [line.strip() for line in f if line.strip()]
    with open(vid_file, 'r', encoding='utf-8') as f:
        vids = [line.strip() for line in f if line.strip()]
    if len(caps) != len(vids):
        log.warning('Mismatch: %d captions vs %d videos', len(caps), len(vids))
    for cap, vid in zip(caps, vids):
        vpath = base / vid
        if not vpath.exists():
            continue
        key = os.path.basename(vid).lower()
        db.con.execute('INSERT OR REPLACE INTO captions VALUES(?,?)', (key, cap))
    db.con.commit()
    log.info('Tom & Jerry captions imported: %d', len(caps))

def apply_captions(db):
    last = 0; n = 0
    while True:
        rows = db.con.execute("SELECT id,path FROM clips WHERE id>? AND (caption IS NULL OR caption='') ORDER BY id LIMIT 1000", (last,)).fetchall()
        if not rows: break
        for cid, p in rows:
            last = cid; c = db.con.execute("SELECT caption FROM captions WHERE key=?", (os.path.basename(p).lower(),)).fetchone()
            if c:
                db.con.execute("UPDATE clips SET caption=?, category=? WHERE id=?", (c[0], guess_category(c[0], p), cid)); n += 1
        db.con.commit()
    log.info("captions طُبّقت على %d مقطع", n); return n

def make_manifest(cfg, db=None):
    db = db or DB(cfg)
    q = "SELECT id,path,caption,category,quality FROM clips WHERE status='ok' AND caption IS NOT NULL AND caption!=''"
    args = []
    if cfg.category: q += " AND category=?"; args.append(cfg.category)
    q += " AND quality>=? ORDER BY quality DESC, id"; args.append(cfg.min_quality)
    # فحص ما قبل التنفيذ: كم فيديو صالح؟ كم له caption؟
    diag = db.con.execute("SELECT status, COUNT(*) FROM clips GROUP BY status").fetchall()
    log.info("DIAG قبل manifest: %s", diag)
    no_cap = db.con.execute("SELECT COUNT(*) FROM clips WHERE status='ok' AND (caption IS NULL OR caption='')").fetchone()[0]
    log.info("DIAG مقاطع سليمة بدون caption: %d", no_cap)
    if cfg.manifest_limit: q += f" LIMIT {int(cfg.manifest_limit)}"
    rows = db.con.execute(q, args).fetchall()
    if not rows:
        diag2 = db.con.execute("SELECT status, COUNT(*) FROM clips GROUP BY status").fetchall()
        log.error("❌ manifest فارغ! تشخيص: %s", diag2)
        raise RuntimeError("manifest فارغ — لا توجد فيديوهات صالحة مع أوصاف. راجع DIAG أعلاه.")
    nocap = db.con.execute("SELECT COUNT(*) FROM clips WHERE status='ok' AND (caption IS NULL OR caption='')").fetchone()[0]
    if nocap: log.warning("%d مقطع سليم بلا caption مُستبعد (أضف captions أو .txt بجانب الفيديو)", nocap)
    ver = hashlib.sha1((PREP_VERSION + json.dumps([r[0] for r in rows])).encode()).hexdigest()[:12]
    d = cfg.wd_path / "manifests"; d.mkdir(exist_ok=True); p = d / f"manifest_{ver}.jsonl"
    atomic_write(p, "".join(json.dumps(dict(id=r[0], path=r[1], caption=r[2], category=r[3], quality=r[4]), ensure_ascii=False) + "\n" for r in rows))
    jdump({"version": ver, "path": str(p), "count": len(rows), "filters": {"category": cfg.category, "min_quality": cfg.min_quality}}, d / "current.json")
    log.info("manifest %s: %d مقطع", ver, len(rows)); return str(p), ver, len(rows)

def load_manifest(cfg):
    cur = json.loads((cfg.wd_path / "manifests" / "current.json").read_text())
    items = [json.loads(l) for l in open(cur["path"], encoding="utf-8")]
    return items, cur["version"]

# ============================================================ جلب بيانات مرخّصة (HF)
def fetch_hf(cfg, spec):
    from huggingface_hub import HfApi, hf_hub_download
    api = HfApi(); repo = spec["repo"]; info = api.dataset_info(repo)
    lic = getattr(info.card_data, "license", None) if getattr(info, "card_data", None) else None
    log.info("dataset %s | license=%s", repo, lic)
    if not spec.get("accept_license"):
        log.error("راجع الترخيص (%s) وضع accept_license=true للمتابعة. تخطّي %s", lic, repo); return 0
    pats = [spec.get("pattern", "*.mp4"), "captions.txt", "videos.txt"] + list(spec.get("extra_patterns", ["*.csv", "*.jsonl"]))
    tgt = cfg.wd_path / "data" / repo.replace("/", "__"); tgt.mkdir(parents=True, exist_ok=True)
    used = 0; limit = float(spec.get("max_gb", 5)) * 2**30; got = 0
    for f in api.list_repo_files(repo, repo_type="dataset"):
        if STOP.is_set() or not any(fnmatch.fnmatch(f, p) for p in pats): continue
        dest = tgt / f
        if dest.exists(): used += dest.stat().st_size; continue
        if used >= limit or shutil.disk_usage(tgt).free / 2**30 < cfg.min_free_disk_gb: log.warning("حدّ الحجم/القرص — توقّف"); break
        p = hf_hub_download(repo, f, repo_type="dataset", local_dir=str(tgt)); used += os.path.getsize(p); got += 1
    if str(tgt) not in cfg.data_dirs: cfg.data_dirs.append(str(tgt))
    for c in tgt.rglob("*"):
        if c.suffix in (".csv", ".jsonl") and str(c) not in cfg.captions_files: cfg.captions_files.append(str(c))
    log.info("fetch: %d ملف جديد (%.2f GB)", got, used / 2**30); return got

# ============================================================ النقاط المرجعية (ذرّية + fallback)

class CheckpointManager:
    def __init__(self, main_dir, extra_dirs=(), keep=3):
        self.dir = Path(main_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.extra = [Path(d) for d in extra_dirs]
        self.keep = max(1, int(keep))

    @staticmethod
    def _dump(obj, f):
        try:
            import torch
            torch.save(obj, f)
        except ImportError:
            pickle.dump(obj, f, protocol=4)

    @staticmethod
    def _load(p):
        try:
            import torch
        except ImportError:
            with open(p, "rb") as f:
                return pickle.load(f)
        return torch.load(p, map_location="cpu", weights_only=False)

    @staticmethod
    def _step_number(path):
        name = Path(path).name
        prefix = "ckpt_"
        suffix = ".pt"
        if not name.startswith(prefix) or not name.endswith(suffix):
            return -1
        number = name[len(prefix):-len(suffix)]
        return int(number) if number.isdigit() else -1

    def save(self, step, payload):
        final = self.dir / f"ckpt_{int(step):08d}.pt"
        tmp = final.with_name(final.name + f".tmp{os.getpid()}")
        with open(tmp, "wb") as f:
            self._dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        digest = sha256_file(tmp)
        os.replace(tmp, final)
        atomic_write(str(final) + ".sha256", digest)
        return final

    def valid(self, p):
        p = Path(p)
        sidecar = Path(str(p) + ".sha256")
        try:
            return (
                p.is_file()
                and sidecar.is_file()
                and sidecar.read_text(encoding="utf-8").strip()
                == sha256_file(p)
            )
        except OSError:
            return False

    def candidates(self):
        found = {}
        for d in [self.dir, *self.extra]:
            if not d.exists():
                continue
            for p in d.glob("ckpt_*.pt"):
                if p.is_file():
                    found[str(p.resolve())] = p
        return sorted(
            found.values(),
            key=lambda p: (self._step_number(p), p.stat().st_mtime),
            reverse=True
        )

    def load_latest(self):
        for p in self.candidates():
            if not self.valid(p):
                log.warning("نقطة غير صالحة/ناقصة checksum: %s", p)
                continue
            try:
                payload = self._load(p)
                if not isinstance(payload, dict) or "step" not in payload:
                    raise ValueError("checkpoint payload missing step")
                log.info("استئناف من %s", p)
                return int(payload["step"]), payload
            except Exception as e:
                log.warning("تعذّر تحميل %s: %r", p, e)
        return None, None

    def prune(self):
        log.info("SAFE RETENTION: automatic checkpoint deletion disabled")
        return 0

# ============================================================ كاش الـ latents

class LatentCache:
    def __init__(self, cfg, db, tier):
        self.cfg, self.db = cfg, db
        fr, h, w = TIERS[tier]
        identity = [cfg.model_id, fr, h, w, cfg.fps, PREP_VERSION]
        self.key = hashlib.sha1(
            json.dumps(identity, sort_keys=True).encode()
        ).hexdigest()[:10]
        self.dir = cfg.wd_path / "cache" / self.key
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, cid, win):
        return self.dir / f"{cid}_{win}.pt"

    def has(self, cid, win):
        row = self.db.con.execute(
            "SELECT path FROM cache WHERE clip_id=? AND win=? AND ckey=?",
            (cid, win, self.key)
        ).fetchone()
        if row is None:
            return False

        p = Path(row[0])
        if not p.is_file() or p.stat().st_size <= 0:
            return False

        sidecar = Path(str(p) + ".sha256")
        try:
            digest = sha256_file(p)
            if sidecar.exists():
                if sidecar.read_text(encoding="utf-8").strip() != digest:
                    log.warning("latent cache checksum mismatch: %s", p)
                    return False
            else:
                import torch
                obj = torch.load(p, map_location="cpu", weights_only=False)
                if not isinstance(obj, dict):
                    return False
                if "lat" not in obj or "emb" not in obj:
                    return False
                if not torch.is_tensor(obj["lat"]) or not torch.is_tensor(obj["emb"]):
                    return False
                atomic_write(str(sidecar), digest)
            return True
        except Exception as e:
            log.warning("latent cache validation failed %s: %r", p, e)
            return False

    def skipped(self, cid):
        return self.db.con.execute(
            "SELECT 1 FROM skip WHERE clip_id=? AND ckey=?",
            (cid, self.key)
        ).fetchone() is not None

    def add(self, cid, win, nbytes):
        self.db.con.execute(
            "INSERT OR REPLACE INTO cache VALUES(?,?,?,?,?,?)",
            (cid, win, self.key, str(self.path(cid, win)), nbytes, time.time())
        )

    def total_gb(self):
        n = self.db.con.execute(
            "SELECT COALESCE(SUM(bytes),0) FROM cache WHERE ckey=?",
            (self.key,)
        ).fetchone()[0]
        return n / 2**30

    def evict(self, limit_gb):
        log.info(
            "SAFE RETENTION: cache eviction disabled; current=%.2fGB limit=%.2fGB",
            self.total_gb(), limit_gb
        )
        return 0


def crop_latent(lat, tier):
    fr, h, w = TIERS[tier]; t, hh, ww = (fr - 1) // 4 + 1, h // 8, w // 8
    _, T, H, W = lat.shape; t0, y0, x0 = 0, (H - min(H, hh)) // 2, (W - min(W, ww)) // 2
    return lat[:, :min(T, t), y0:y0 + min(H, hh), x0:x0 + min(W, ww)]

def load_frames(path, start, tier, fps):
    fr, h, w = TIERS[tier]
    r = sh([ffmpeg_bin(), "-v", "error", "-ss", f"{start:.2f}", "-i", str(path), "-vf",
            f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}", "-frames:v", str(fr),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], 180)
    n = len(r.stdout) // (w * h * 3)
    if n < fr: return None
    return np.frombuffer(r.stdout[:fr * w * h * 3], np.uint8).reshape(fr, h, w, 3)

def prepare(cfg, db=None):  # [غير مختبر: يحتاج GPU + diffusers]
    import torch
    from diffusers import AutoencoderKLWan
    from transformers import AutoTokenizer, UMT5EncoderModel
    db = db or DB(cfg); items, _ = load_manifest(cfg); tier = Resources(cfg).pick_tier(); cache = LatentCache(cfg, db, tier)
    dev = "cuda"; tdt = torch.bfloat16 if torch.cuda.get_device_capability(0)[0] >= 8 else torch.float16
    vae = AutoencoderKLWan.from_pretrained(cfg.model_id, subfolder="vae", torch_dtype=torch.float32).to(dev); vae.enable_tiling()
    tok = AutoTokenizer.from_pretrained(cfg.model_id, subfolder="tokenizer")
    te = UMT5EncoderModel.from_pretrained(cfg.model_id, subfolder="text_encoder", torch_dtype=tdt).to(dev).eval()
    z = vae.config.z_dim
    mean = torch.tensor(vae.config.latents_mean).view(1, z, 1, 1, 1).to(dev)
    istd = (1.0 / torch.tensor(vae.config.latents_std)).view(1, z, 1, 1, 1).to(dev)
    made = 0
    for it in items:
        if STOP.is_set(): break
        cid = it["id"]
        if cache.skipped(cid): continue
        if cache.total_gb() >= cfg.cache_gb: log.warning("الكاش وصل %.1fGB — توقّف", cfg.cache_gb); break
        if shutil.disk_usage(cfg.wd_path).free / 2**30 < cfg.min_free_disk_gb: log.warning("القرص ممتلئ — توقّف"); break
        pr = probe(it["path"]); dur = pr["duration"] if pr else 0
        for win in range(cfg.windows):
            if cache.has(cid, win): continue
            span = TIERS[tier][0] / cfg.fps; start = max(0.0, (dur - span) * (0.5 if cfg.windows == 1 else win / max(1, cfg.windows - 1)))
            fr = load_frames(it["path"], start, tier, cfg.fps)
            if fr is None:
                db.con.execute("INSERT OR REPLACE INTO skip VALUES(?,?,?)", (cid, cache.key, "too_short_for_tier")); break
            with torch.no_grad():
                x = torch.from_numpy(fr).permute(3, 0, 1, 2).unsqueeze(0).float().div(127.5).sub(1).to(dev)
                lat = ((vae.encode(x).latent_dist.mode() - mean) * istd).squeeze(0).half().cpu()
                t = tok(it["caption"], max_length=512, padding="max_length", truncation=True, return_tensors="pt")
                L = int(t.attention_mask.sum()); emb = te(t.input_ids.to(dev), t.attention_mask.to(dev)).last_hidden_state[0, :L].half().cpu()
            p = cache.path(cid, win); tmp = p.with_suffix(".tmp"); torch.save({"lat": lat, "emb": emb}, tmp); os.replace(tmp, p)
            cache.add(cid, win, p.stat().st_size); made += 1
        if made % 20 == 0: db.con.commit(); cache.evict(cfg.cache_gb); gc.collect()
    db.con.commit(); log.info("prepare: %d عيّنة جديدة | الكاش %.2fGB | tier=%s", made, cache.total_gb(), TIERS[tier])
    del vae, te; gc.collect(); torch.cuda.empty_cache(); return made

# ============================================================ التدريب
class Sampler:
    def __init__(self, n, seed, epoch=0, pos=0): self.n, self.seed, self.epoch, self.pos = n, seed, epoch, pos
    def next(self):
        if self.pos >= self.n: self.epoch += 1; self.pos = 0
        i = int(np.random.RandomState(self.seed + self.epoch).permutation(self.n)[self.pos]); self.pos += 1; return i
    def state(self): return {"epoch": self.epoch, "pos": self.pos}

class Prefetcher(threading.Thread):
    def __init__(self, files, sampler, depth, res):
        super().__init__(daemon=True); self.f, self.s, self.q, self.res = files, sampler, queue.Queue(maxsize=max(1, depth)), res; self.halt = False
    def run(self):
        import torch
        while not self.halt:
            if self.res.ram_high(): time.sleep(2); continue
            i = self.s.next(); st = self.s.state()
            try: d = torch.load(self.f[i], map_location="cpu")
            except Exception as e: log.warning("ملف كاش تالف %s: %r", self.f[i], e); continue
            while not self.halt:
                try: self.q.put((d, st), timeout=1); break
                except queue.Full: pass
    def get(self): return self.q.get(timeout=600)

def _rng_state():
    import torch
    return {"py": random.getstate(), "np": np.random.get_state(), "torch": torch.get_rng_state(),
            "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None}
def _set_rng(s):
    import torch
    random.setstate(s["py"]); np.random.set_state(s["np"]); torch.set_rng_state(s["torch"])
    if s.get("cuda") is not None: torch.cuda.set_rng_state_all(s["cuda"])

def train(cfg, db=None):  # [غير مختبر: يحتاج GPU + diffusers + peft]
    import torch, torch.nn.functional as F
    from diffusers import WanTransformer3DModel
    from peft import LoraConfig, get_peft_model_state_dict, set_peft_model_state_dict
    assert torch.cuda.is_available(), "التدريب يحتاج GPU — LoRA لنموذج 1.3B على CPU غير عملي"
    db = db or DB(cfg); st = Status(cfg); res = Resources(cfg); t_start = time.time()
    items, dver = load_manifest(cfg)

    cm = CheckpointManager(
        cfg.wd_path / "ckpt",
        [g for pat in cfg.resume_dirs for g in glob.glob(pat)],
        cfg.keep_ckpts
    )
    step, pl = cm.load_latest()

    compatibility = {
        "model_id": cfg.model_id,
        "prep_version": PREP_VERSION,
        "dataset_version": dver,
        "windows": int(cfg.windows),
        "fps": int(cfg.fps),
        "lora_rank": int(cfg.lora_rank),
        "lora_alpha": int(cfg.lora_alpha),
        "flow_shift": float(cfg.flow_shift),
        "lr": float(cfg.lr),
        "wd": float(cfg.wd),
        "warmup": int(cfg.warmup),
        "max_steps": int(cfg.max_steps),
        "grad_accum": int(cfg.grad_accum),
        "seed": int(cfg.seed),
    }

    if pl is not None:
        if pl.get("compatibility") != compatibility:
            raise RuntimeError(
                "رفض الاستئناف: إعدادات أو إصدار البيانات لا يطابق Checkpoint. "
                "احتفظ بالنقطة القديمة واستخدم work_dir جديداً لتدريب مستقل."
            )
        if "tier" not in pl:
            raise RuntimeError("Checkpoint قديم بلا tier موثوق؛ لن يتم استئنافه تلقائياً.")
        tier = int(pl["tier"])
        if not 0 <= tier < len(TIERS):
            raise RuntimeError("Checkpoint يحتوي tier غير صالح.")
    else:
        step = 0
        tier = res.pick_tier()

    cache = LatentCache(cfg, db, tier)
    files = []
    fingerprint_records = []

    for item in items:
        for win in range(cfg.windows):
            if not cache.has(item["id"], win):
                continue
            path = cache.path(item["id"], win)
            digest = sha256_file(path)
            files.append(str(path))
            fingerprint_records.append({
                "id": item["id"],
                "window": win,
                "sha256": digest,
            })

    if not files:
        raise RuntimeError(
            f"الكاش فارغ للمستوى tier={tier}؛ نفّذ prepare لهذا المستوى أولاً."
        )

    data_fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_records,
            sort_keys=True,
            ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()

    if pl is not None:
        if pl.get("data_fingerprint") != data_fingerprint:
            raise RuntimeError(
                "رفض الاستئناف: ملفات الكاش أو ترتيب العينات تغيرت. "
                "لم يتم تعديل Checkpoint."
            )

    cc = torch.cuda.get_device_capability(0); dtype = torch.bfloat16 if cc[0] >= 8 else torch.float16; use_scaler = dtype == torch.float16
    log.info("GPU=%s cc=%s dtype=%s tier=%s عيّنات=%d", torch.cuda.get_device_name(0), cc, dtype, TIERS[tier], len(files))
    tr = WanTransformer3DModel.from_pretrained(cfg.model_id, subfolder="transformer", torch_dtype=dtype).to("cuda")
    tr.requires_grad_(False)
    lcfg = dict(r=cfg.lora_rank, lora_alpha=cfg.lora_alpha, init_lora_weights=True, target_modules=["to_q", "to_k", "to_v", "to_out.0"])
    tr.add_adapter(LoraConfig(**lcfg))
    for p in tr.parameters():
        if p.requires_grad: p.data = p.data.float()
    if cfg.grad_ckpt: tr.enable_gradient_checkpointing()
    params = [p for p in tr.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=cfg.lr, weight_decay=cfg.wd)
    lam = lambda s: min(1.0, (s + 1) / max(1, cfg.warmup)) * (0.5 * (1 + math.cos(math.pi * min(1.0, s / max(1, cfg.max_steps)))) * 0.9 + 0.1)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lam); scaler = torch.amp.GradScaler("cuda", enabled=use_scaler)
    sam = Sampler(len(files), cfg.seed); hist = []
    if pl:
        required = ("lora", "opt", "sched", "scaler", "sampler", "rng")
        missing = [key for key in required if key not in pl]
        if missing:
            raise RuntimeError(f"Checkpoint ناقص الحقول: {missing}")
        set_peft_model_state_dict(tr, pl["lora"])
        opt.load_state_dict(pl["opt"])
        sched.load_state_dict(pl["sched"])
        scaler.load_state_dict(pl["scaler"])
        sam = Sampler(len(files), cfg.seed, **pl["sampler"])
        _set_rng(pl["rng"])
        hist = pl.get("hist", [])
    # Exact recovery: sampler advances only in the training consumer.
    # Background prefetch is disabled until it can preserve consumed positions.
    consumed = sam.state()
    def save(tag=""):
        payload = dict(step=step, lora=get_peft_model_state_dict(tr), lora_config=lcfg, opt=opt.state_dict(), sched=sched.state_dict(),
                       scaler=scaler.state_dict(), sampler=consumed, rng=_rng_state(), cfg=dataclasses.asdict(cfg), model_id=cfg.model_id,
                       dataset_version=dver, prep_version=PREP_VERSION, tier=tier,
                       compatibility=compatibility, data_fingerprint=data_fingerprint,
                       hist=hist[-200:])
        p = cm.save(step, payload); log.info("checkpoint %s %s", p.name, tag); return payload

    if pl is None:
        save("initial")

    reason = "max_steps"; bad = 0; tr.train()
    while step < cfg.max_steps:
        if STOP.is_set(): reason = "signal"; break
        if time.time() - t_start > cfg.max_hours * 3600: reason = "time_limit"; break
        try:
            tot = 0.0
            for _ in range(cfg.grad_accum):
                d = None
                for attempt in range(len(files)):
                    sample_index = sam.next()
                    sample_path = files[sample_index]
                    try:
                        d = torch.load(sample_path, map_location="cpu", weights_only=False)
                        if not isinstance(d, dict) or "lat" not in d or "emb" not in d:
                            raise ValueError("invalid latent cache payload")
                    except Exception as e:
                        consumed = sam.state()
                        log.warning("تخطي عينة كاش تالفة %s: %r", sample_path, e)
                        continue
                    consumed = sam.state()
                    break
                if d is None:
                    raise RuntimeError("لا توجد عينة كاش سليمة بعد فحص جميع الملفات")
                lat = crop_latent(d["lat"].float(), tier).unsqueeze(0).cuda()
                emb = torch.zeros(1, 512, d["emb"].shape[-1]); emb[0, :d["emb"].shape[0]] = d["emb"].float(); emb = emb.cuda()
                u = torch.rand(1).item(); sig = cfg.flow_shift * u / (1 + (cfg.flow_shift - 1) * u)
                noise = torch.randn_like(lat); noisy = (1 - sig) * lat + sig * noise; target = noise - lat
                with torch.autocast("cuda", dtype=dtype):
                    pred = tr(hidden_states=noisy.to(dtype), timestep=torch.tensor([sig * 1000.0], device="cuda"),
                              encoder_hidden_states=emb.to(dtype), return_dict=False)[0]
                loss = F.mse_loss(pred.float(), target.float())
                if not torch.isfinite(loss):
                    opt.zero_grad(set_to_none=True)
                    raise RuntimeError(
                        "Loss غير منتهية؛ أُلغيت خطوة optimizer كاملة دون تحديث جزئي. "
                        "افحص FP16 وبيانات الكاش ومعدل التعلم."
                    )
                bad = 0; scaler.scale(loss / cfg.grad_accum).backward(); tot += loss.item() / cfg.grad_accum
            scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(params, 1.0)
            scaler.step(opt); scaler.update(); sched.step(); opt.zero_grad(set_to_none=True)
        except torch.cuda.OutOfMemoryError:
            opt.zero_grad(set_to_none=True)
            gc.collect()
            torch.cuda.empty_cache()
            reason = "oom"
            log.error(
                "OOM: إيقاف آمن عند step=%d دون تغيير tier. "
                "سيبقى آخر Checkpoint صالح هو مرجع الاستعادة.",
                step
            )
            break
        step += 1; hist.append(round(tot, 5))
        if step % cfg.log_every == 0:
            snap = res.snapshot(); snap.update(step=step, loss=tot, lr=sched.get_last_lr()[0], tier=list(TIERS[tier]))
            log.info("step %d/%d loss=%.4f vram_free=%sGB ram=%.0f%%", step, cfg.max_steps, tot, snap.get("vram_free_gb"), 100 * snap.get("ram_used_frac", 0))
            st.update(state="training", **snap)
            with open(cfg.wd_path / "metrics.jsonl", "a") as f: f.write(json.dumps(snap) + "\n")
        if step % cfg.ckpt_every == 0: save()
    if reason != "oom":
        payload = save("final")
        export_payload = {k: payload[k] for k in ("lora", "lora_config", "step", "model_id")}
        export_path = cfg.wd_path / "lora_latest.pt"
        tmp_export = export_path.with_name(export_path.name + f".tmp{os.getpid()}")
        torch.save(export_payload, tmp_export)
        with open(tmp_export, "rb") as f:
            os.fsync(f.fileno())
        os.replace(tmp_export, export_path)
    else:
        log.warning("لم يُحفظ وضع OOM الحالي؛ الاستعادة من آخر Checkpoint مكتمل.")

    st.update(state="done" if reason == "max_steps" else f"paused_{reason}", step=step, reason=reason)
    log.info("التدريب توقّف: %s عند step=%d", reason, step); return reason

# ============================================================ Prompt Engine v1
# ملفات تعريف مستقلة للأنماط الأربعة. هذه قوالب توجيه بصري وليست نموذج NLP.
STYLES = {
    "cinematic": (
        "cinematic live-action film, photorealistic environment, deliberate visual storytelling, "
        "natural physics, realistic motion, anamorphic composition, subtle 35mm film texture",
        "2d cartoon, anime, 3d cartoon, illustration, plastic skin, low quality, blurry, "
        "deformed anatomy, extra limbs, watermark, text, flicker, jitter"
    ),
    "realistic_human": (
        "photorealistic human subject, natural skin pores and texture, anatomically plausible face "
        "and hands, subtle facial expression, natural blinking, realistic body movement, "
        "physically plausible lighting, live-action cinematography",
        "cartoon, anime, illustration, artificial skin, waxy face, deformed face, bad hands, "
        "extra fingers, distorted anatomy, blurry, flicker, watermark, text"
    ),
    "cartoon3d": (
        "high-quality 3D animated family feature, appealing stylized character design, "
        "expressive readable facial features, dimensional shapes, detailed 3D environment, "
        "soft global illumination, polished materials, fluid character animation",
        "photorealistic live action, 2d flat illustration, anime, low quality, blurry, "
        "deformed character, broken anatomy, flicker, jitter, watermark, text"
    ),
    "cartoon2d": (
        "traditional 2D animated cartoon, clean expressive outlines, hand-drawn visual language, "
        "flat cel colors, controlled shape design, expressive poses, coherent illustrated backgrounds, "
        "smooth 2D animation",
        "photorealistic, 3d render, realistic skin pores, anime-specific styling, muddy outlines, "
        "inconsistent character design, low quality, blurry, flicker, jitter, watermark, text"
    ),
    "anime": (
        "Japanese anime visual style, precise clean line art, expressive character design, "
        "intentional cel shading, rich anime background art, controlled color palette, "
        "dynamic composition, fluid anime motion",
        "photorealistic live action, western 3d cartoon, realistic skin pores, muddy line art, "
        "low quality, blurry, deformed anatomy, flicker, jitter, watermark, text"
    ),
}

# أسماء بديلة لتسهيل الاستخدام دون كسر أسماء الأنماط القديمة.
STYLE_ALIASES = {
    "realistic": "realistic_human",
    "photo": "realistic_human",
    "cartoon": "cartoon2d",
    "2d": "cartoon2d",
    "3d": "cartoon3d",
}

CAMERA = {
    "dolly_in": "slow controlled dolly-in, camera gradually moves toward the subject",
    "tracking": "smooth tracking shot following the subject, stable subject framing",
    "drone": "aerial drone shot, gradual forward flight, wide spatial perspective",
    "handheld": "subtle handheld camera movement, restrained natural camera shake",
    "crane": "smooth rising crane shot, revealing the environment",
    "pan": "slow controlled horizontal camera pan",
    "close_up": "close-up shot, face and subject details clearly visible",
    "wide": "wide establishing shot, subject placed within the environment",
    "static": "locked-off static camera, stable composition",
}

LIGHT = {
    "golden_hour": "warm golden-hour sunlight, soft highlights, long natural shadows",
    "night_neon": "night scene, colored neon lights, reflections on wet surfaces",
    "overcast": "soft diffused overcast lighting, gentle shadows",
    "studio": "controlled studio lighting, soft key light and subtle rim light",
    "moody": "low-key cinematic lighting, controlled contrast, atmospheric haze",
}

def _prompt_parts(*values):
    """تنظيف أجزاء الـPrompt وإزالة الفراغات والتكرار الحرفي."""
    result = []
    seen = set()
    for value in values:
        if value is None:
            continue
        value = " ".join(str(value).split()).strip(" ,")
        if not value:
            continue
        key = value.casefold()
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result


@dataclasses.dataclass
class Shot:
    # حافظنا على ترتيب الحقول الأصلية لتظل EVAL_SHOTS والاستدعاءات القديمة متوافقة.
    subject: str
    action: str = ""
    setting: str = ""
    style: str = "cinematic"
    camera: str = "static"
    lighting: str = "overcast"
    mood: str = ""
    lens: str = "35mm"
    grade: str = ""

    # حقول إضافية اختيارية لبناء مشاهد أكثر تفصيلاً.
    composition: str = ""
    motion: str = ""
    atmosphere: str = ""
    visual_detail: str = ""

    def to_prompt(self):
        style = STYLE_ALIASES.get(self.style, self.style)
        if style not in STYLES:
            valid = ", ".join(STYLES)
            raise ValueError(f"Unknown style '{self.style}'. Available styles: {valid}")

        style_prompt, negative_prompt = STYLES[style]

        camera_prompt = CAMERA.get(self.camera, self.camera)
        light_prompt = LIGHT.get(self.lighting, self.lighting)

        lens_prompt = ""
        if self.lens:
            lens_prompt = f"{self.lens} lens"

        parts = _prompt_parts(
            f"Main subject: {self.subject}",
            f"Action: {self.action}" if self.action else "",
            f"Environment: {self.setting}" if self.setting else "",
            f"Camera: {camera_prompt}",
            f"Composition: {self.composition}" if self.composition else "",
            f"Motion: {self.motion}" if self.motion else "",
            f"Lighting: {light_prompt}",
            f"Atmosphere: {self.atmosphere}" if self.atmosphere else "",
            f"Mood: {self.mood}" if self.mood else "",
            lens_prompt,
            f"Visual details: {self.visual_detail}" if self.visual_detail else "",
            f"Color grade: {self.grade}" if self.grade else "",
            style_prompt,
        )

        return ", ".join(parts), negative_prompt

EVAL_SHOTS = [
    Shot("a lone astronaut", "walks across a dusty red plain", "distant research base", "cinematic", "tracking", "golden_hour", "epic, lonely"),
    Shot("a young woman with curly hair", "smiles and turns toward the window", "cozy apartment", "realistic_human", "close_up", "overcast", "warm"),
    Shot("a small fox character with big eyes", "jumps over a stream", "magical forest", "cartoon3d", "tracking", "golden_hour", "playful"),
    Shot("a young adventurer with expressive eyes", "runs through a colorful enchanted forest", "hand-drawn fantasy landscape", "cartoon2d", "tracking", "golden_hour", "playful and vibrant"),
    Shot("a swordswoman", "draws her blade as cherry blossoms fall", "temple courtyard", "anime", "dolly_in", "moody", "tense"),
    Shot("a futuristic city skyline", "glows as flying cars pass", "rainy night", "cinematic", "drone", "night_neon", "cyberpunk"),
    Shot("an old fisherman", "pulls a net from the sea", "foggy harbor at dawn", "realistic_human", "handheld", "overcast", "quiet"),
]

# ============================================================ توليد + تقييم
def _gen_dtype():
    import torch; return torch.bfloat16 if torch.cuda.get_device_capability(0)[0] >= 8 else torch.float16



def load_project_shots(cfg):
    project_file = getattr(cfg, "shots_file", "")
    if not project_file:
        return [(f"shot_{i+1:03d}", shot)
                for i, shot in enumerate(EVAL_SHOTS[:cfg.eval_n])]

    path = Path(project_file).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Project shots file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("shots") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise ValueError("JSON must contain a non-empty shots list.")

    allowed = {f.name for f in dataclasses.fields(Shot)}
    result, seen = [], set()

    for i, item in enumerate(rows, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Shot {i} must be an object.")
        sid = str(item.get("id") or f"shot_{i:03d}").strip()
        if not sid or sid in seen:
            raise ValueError(f"Duplicate or empty shot id: {sid!r}")
        seen.add(sid)
        values = {k: v for k, v in item.items() if k in allowed}
        if not isinstance(values.get("subject"), str) or not values["subject"].strip():
            raise ValueError(f"Shot {sid} requires a subject.")
        shot = Shot(**values)
        shot.to_prompt()
        result.append((sid, shot))

    return result

def generate(cfg, tag, lora=None):  # [غير مختبر: GPU]
    import torch
    from diffusers import AutoencoderKLWan, WanPipeline
    from diffusers.utils import export_to_video

    resources = Resources(cfg)
    tier_idx = resources.pick_tier()
    tier_frames, tier_h, tier_w = TIERS[tier_idx]
    gpu_state = resources.snapshot()
    log.info("GPU tier=%s resolution=%sx%s frames=%s GPU=%s VRAM=%s GB",
             tier_idx, tier_w, tier_h, tier_frames,
             gpu_state.get("gpu"), gpu_state.get("vram_total_gb"))
    vae = AutoencoderKLWan.from_pretrained(cfg.model_id, subfolder="vae", torch_dtype=torch.float32)
    pipe = WanPipeline.from_pretrained(cfg.model_id, vae=vae, torch_dtype=_gen_dtype())
    if lora:
        from peft import LoraConfig, set_peft_model_state_dict
        d = CheckpointManager._load(lora); pipe.transformer.add_adapter(LoraConfig(**d["lora_config"]))
        set_peft_model_state_dict(pipe.transformer, d["lora"]); log.info("LoRA step=%s", d.get("step"))
    pipe.enable_model_cpu_offload()
    if hasattr(pipe.vae, "enable_tiling"):
        pipe.vae.enable_tiling()
    else:
        print("VAE tiling unavailable; continuing without tiling.", flush=True)
    out = cfg.wd_path / "gen" / tag; out.mkdir(parents=True, exist_ok=True)
    for i, (shot_id, shot) in enumerate(load_project_shots(cfg)):
        f = out / f"{i:02d}_{shot.style}.mp4"
        if f.exists(): continue
        p, neg = shot.to_prompt(); g = torch.Generator("cpu").manual_seed(cfg.seed + i)
        fr = pipe(prompt=p, negative_prompt=neg, height=tier_h, width=tier_w, num_frames=tier_frames, guidance_scale=5.0,
                  num_inference_steps=cfg.gen_steps, generator=g).frames[0]
        export_to_video(fr, str(f), fps=cfg.fps); jdump({
            "prompt": p, "negative": neg, "seed": cfg.seed + i,
            "lora": str(lora), "tier": tier_idx,
            "width": tier_w, "height": tier_h, "frames": tier_frames,
            "steps": cfg.gen_steps, "fps": cfg.fps,
            "gpu": gpu_state.get("gpu"),
            "vram_total_gb": gpu_state.get("vram_total_gb")
        }, str(f) + ".json")
    del pipe; gc.collect(); torch.cuda.empty_cache(); return str(out)

def video_metrics(path):
    info = probe(path) or {}; fr = read_gray(path, 64, info.get("duration", 0), dense=True)
    if fr is None: return None
    m = frame_metrics(fr); m["sharp_n"] = min(1.0, math.log10(1 + m["sharp"]) / 2.5)
    return {**m, "width": info.get("width"), "height": info.get("height"), "frames": len(fr)}

def clip_scores(videos_dir):  # [غير مختبر] اختياري
    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor
    m = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").eval(); pr = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32"); out = {}
    for f in sorted(Path(videos_dir).glob("*.mp4")):
        meta = json.loads(Path(str(f) + ".json").read_text())
        r = sh([ffmpeg_bin(), "-v", "error", "-i", str(f), "-vf", "fps=2,scale=224:224", "-frames:v", "4", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
        n = len(r.stdout) // (224 * 224 * 3)
        if not n: continue
        ims = [Image.fromarray(np.frombuffer(r.stdout, np.uint8)[i * 224 * 224 * 3:(i + 1) * 224 * 224 * 3].reshape(224, 224, 3)) for i in range(n)]
        with torch.no_grad():
            x = pr(text=[meta["prompt"][:300]], images=ims, return_tensors="pt", padding=True, truncation=True)
            o = m(**x); out[f.name] = float(o.logits_per_image.mean())
    return out

def evaluate(cfg, vdir, report):
    per = {}
    for f in sorted(Path(vdir).glob("*.mp4")):
        mt = video_metrics(f)
        if mt: per[f.name] = mt
    if not per: raise SystemExit(f"لا فيديوهات في {vdir}")
    keys = ["sharp_n", "flicker", "motion", "bright"]; agg = {k: float(np.mean([v[k] for v in per.values()])) for k in keys}
    if cfg.use_clip:
        try: cs = clip_scores(vdir); agg["clip"] = float(np.mean(list(cs.values()))) if cs else None
        except Exception as e: log.warning("CLIP فشل: %r", e)
    jdump({"dir": str(vdir), "n": len(per), "aggregate": agg, "per_video": per, "note": "مقاييس آلية بسيطة؛ لا تغني عن مراجعة بشرية"}, report)
    log.info("eval: %s", agg); return agg

def compare(base_report, new_report, tol):
    b = json.loads(Path(base_report).read_text())["aggregate"]; n = json.loads(Path(new_report).read_text())["aggregate"]
    higher = {"sharp_n": True, "clip": True, "flicker": False}; rows = {}; ok = True
    for k, hb in higher.items():
        if b.get(k) is None or n.get(k) is None: continue
        rel = (n[k] - b[k]) / (abs(b[k]) + 1e-9); worse = (-rel if hb else rel) > tol
        rows[k] = {"base": round(b[k], 4), "new": round(n[k], 4), "rel_change": round(rel, 4), "regression": worse}; ok &= not worse
    return {"verdict": "ok" if ok else "regression", "metrics": rows, "tol": tol}

def promote(cfg, ckpt, verdict_file=None, force=False):
    d = cfg.wd_path / "stable"; d.mkdir(exist_ok=True); idx = d / "stable.json"
    hist = json.loads(idx.read_text()) if idx.exists() else {"versions": [], "current": None}
    if not force:
        v = json.loads(Path(verdict_file).read_text()) if verdict_file and Path(verdict_file).exists() else None
        if not v or v.get("verdict") != "ok": raise SystemExit("مرفوض: لا يوجد verdict=ok (استخدم --force وسيُسجَّل)")
    n = len(hist["versions"]) + 1; dst = d / f"stable_v{n:03d}.pt"; shutil.copy2(ckpt, dst)  # لا نحذف الإصدارات السابقة
    hist["versions"].append({"file": dst.name, "src": str(ckpt), "time": time.time(), "forced": force}); hist["current"] = dst.name
    jdump(hist, idx); log.info("تمت الترقية → %s", dst.name); return dst

def rollback(cfg):
    idx = cfg.wd_path / "stable" / "stable.json"; h = json.loads(idx.read_text()); names = [v["file"] for v in h["versions"]]
    i = names.index(h["current"])
    if i == 0: raise SystemExit("لا إصدار أقدم")
    h["current"] = names[i - 1]; jdump(h, idx); log.info("رجوع إلى %s", h["current"])

# ============================================================ تحسين الجودة (upscale/fps/grade)
GRADES = {"cinematic": "eq=contrast=1.10:saturation=1.05:gamma=0.96,colorbalance=rs=-.05:bs=.05:rh=.05:bh=-.05,vignette=PI/7",
          "anime": "eq=saturation=1.25:contrast=1.05", "cartoon3d": "eq=saturation=1.15:contrast=1.06",
          "natural": "eq=contrast=1.04:saturation=1.02", "none": ""}

def _realesrgan_pass(inp, outp, scale):  # [غير مختبر: GPU + realesrgan]
    import subprocess as sp
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer
    pr = probe(inp); w, h = pr["width"], pr["height"]; ow, oh = int(w * scale) // 2 * 2, int(h * scale) // 2 * 2
    net = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
    up = RealESRGANer(scale=4, model_path="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
                      model=net, tile=256, half=True)
    dec = sp.Popen([ffmpeg_bin(), "-v", "error", "-i", str(inp), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=sp.PIPE)
    enc = sp.Popen([ffmpeg_bin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{ow}x{oh}", "-r", f"{pr['fps']}", "-i", "-",
                    "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(outp)], stdin=sp.PIPE)
    while True:
        b = dec.stdout.read(w * h * 3)
        if len(b) < w * h * 3: break
        img = np.frombuffer(b, np.uint8).reshape(h, w, 3)[:, :, ::-1]
        o, _ = up.enhance(np.ascontiguousarray(img), outscale=scale)
        enc.stdin.write(np.ascontiguousarray(o[:, :, ::-1])[:oh, :ow].tobytes())
    enc.stdin.close(); enc.wait(); dec.wait()

def enhance(cfg, inp, outp, scale=2.0, fps=0, grade="cinematic"):
    ff = ffmpeg_bin(); pr = probe(inp); assert pr, "فيديو غير صالح"; used = []
    src = str(inp); tmp = Path(tempfile.mkdtemp()); filters = []
    if cfg.sr in ("auto", "realesrgan"):
        try:
            _realesrgan_pass(inp, tmp / "sr.mp4", scale); src = str(tmp / "sr.mp4"); used.append("realesrgan")
        except Exception as e:
            if cfg.sr == "realesrgan": raise
            log.warning("Real-ESRGAN غير متاح (%r) → ffmpeg lanczos (جودة أقل)", e)
    if not used:
        filters.append(f"scale=trunc(iw*{scale}/2)*2:trunc(ih*{scale}/2)*2:flags=lanczos,unsharp=5:5:0.6:5:5:0.0"); used.append("ffmpeg_lanczos+unsharp")
    if fps and fps > pr["fps"] + 0.5:
        if cfg.rife_cmd:
            r = subprocess.run(cfg.rife_cmd.format(inp=src, out=str(tmp / "rife.mp4")), shell=True)
            if r.returncode == 0: src = str(tmp / "rife.mp4"); used.append("rife")
            else: filters.append(f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"); used.append("ffmpeg_minterpolate(fallback)")
        else:
            filters.append(f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"); used.append("ffmpeg_minterpolate")
    if GRADES.get(grade): filters.append(GRADES[grade]); used.append(f"grade:{grade}")
    cmd = [ff, "-v", "error", "-y", "-i", src]
    if filters: cmd += ["-vf", ",".join(filters)]
    cmd += ["-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", str(outp)]
    r = sh(cmd, 3600); shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode: raise RuntimeError(r.stderr.decode()[-500:])
    log.info("enhance: %s → %s [%s]", inp, outp, " + ".join(used)); return used

# ============================================================ Kaggle (يعمل من Termux)
WRAPPER = '''import base64, gzip, os, subprocess, sys
W = "/kaggle/working"; os.makedirs(W, exist_ok=True)
open(W + "/cinema_trainer.py", "wb").write(gzip.decompress(base64.b64decode("__SRC__")))
open(W + "/cinema_config.json", "wb").write(base64.b64decode("__CFG__"))
try:
    from kaggle_secrets import UserSecretsClient
    os.environ["HF_TOKEN"] = UserSecretsClient().get_secret("HF_TOKEN")
except Exception as e:
    print("لا يوجد سر HF_TOKEN:", e)
subprocess.call([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers", "peft", "transformers", "accelerate",
                 "huggingface_hub", "imageio", "imageio-ffmpeg", "psutil", "sentencepiece", "ftfy"])
sys.exit(subprocess.call([sys.executable, W + "/cinema_trainer.py", "--config", W + "/cinema_config.json", "pipeline"]))
'''

def kaggle_push(slug, config_path, datasets=(), kernels=(), gpu=True):
    d = Path(tempfile.mkdtemp(prefix="kpush_")); cfgd = json.loads(Path(config_path).read_text()) if config_path else {}
    cfgd.setdefault("work_dir", "/kaggle/working/cinema_work"); cfgd.setdefault("resume_dirs", ["/kaggle/input/*/cinema_work/ckpt"])
    src = base64.b64encode(gzip.compress(Path(__file__).read_bytes())).decode(); cj = base64.b64encode(json.dumps(cfgd).encode()).decode()
    (d / "run.py").write_text(WRAPPER.replace("__SRC__", src).replace("__CFG__", cj), encoding="utf-8")
    meta = {"id": slug, "title": slug.split("/")[1], "code_file": "run.py", "language": "python", "kernel_type": "script", "is_private": "true",
            "enable_gpu": "true" if gpu else "false", "enable_internet": "true", "dataset_sources": list(datasets), "kernel_sources": list(kernels), "competition_sources": []}
    (d / "kernel-metadata.json").write_text(json.dumps(meta, indent=1))
    r = subprocess.run(["kaggle", "kernels", "push", "-p", str(d)]); log.info("kaggle push exit=%s dir=%s", r.returncode, d); return r.returncode

# ============================================================ Pipeline / واجهة الأوامر
def pipeline(cfg):
    db = DB(cfg); st = Status(cfg); st.update(state="starting", version=VERSION, resources=Resources(cfg).snapshot())
    reason = None
    for stage in cfg.stages:
        if STOP.is_set(): break
        st.update(stage=stage); log.info("===== مرحلة: %s =====", stage)
        try:
            if stage == "fetch":
                for s in cfg.fetch: fetch_hf(cfg, s)
            elif stage == "scan": scan(cfg, db)
            elif stage == "captions":
                for f in cfg.captions_files: import_captions(cfg, db, f)
                import_tom_jerry_captions(cfg, db)
                apply_captions(db)
            elif stage == "manifest": make_manifest(cfg, db)
            elif stage == "prepare": prepare(cfg, db)
            elif stage == "baseline":
                if not (cfg.wd_path / "baseline_report.json").exists():
                    evaluate(cfg, generate(cfg, "baseline"), cfg.wd_path / "baseline_report.json")
            elif stage == "train":
                reason = train(cfg, db)
                if reason != "max_steps": log.warning("التدريب لم يكتمل (%s) — أعد push لإكمال الاستئناف", reason); break
            elif stage == "generate":
                generate(cfg, "tuned", lora=str(cfg.wd_path / "lora_latest.pt"))
            elif stage == "eval": evaluate(cfg, cfg.wd_path / "gen" / "tuned", cfg.wd_path / "tuned_report.json")
            elif stage == "compare":
                v = compare(cfg.wd_path / "baseline_report.json", cfg.wd_path / "tuned_report.json", cfg.eval_tol)
                jdump(v, cfg.wd_path / "verdict.json"); log.info("verdict: %s", v)
            else: log.warning("مرحلة مجهولة: %s", stage)
        except Exception as e:
            log.exception("فشلت المرحلة %s", stage); st.update(state="error", stage=stage, error=repr(e)); raise
    if reason in (None, "max_steps"): st.update(state="finished")

def print_status(cfg):
    p = cfg.wd_path / "status.json"
    print(json.dumps(json.loads(p.read_text()) if p.exists() else {"state": "no status"}, ensure_ascii=False, indent=1))
    print("resources:", json.dumps(Resources(cfg).snapshot()))
    try: print("dataset:", json.dumps(DB(cfg).stats(), ensure_ascii=False))
    except Exception: pass
    print("checkpoints:", [p.name for p in CheckpointManager(cfg.wd_path / "ckpt").candidates()][:5])

# ============================================================ اختبار ذاتي (بلا GPU)
def selftest():
    assert np is not None, "يلزم numpy"
    tmp = Path(tempfile.mkdtemp(prefix="ct_")); data = tmp / "data"; data.mkdir(); ff = ffmpeg_bin(); results = []
    def ok(name, cond): results.append((name, bool(cond))); print(("PASS " if cond else "FAIL ") + name)
    def mk(name, src, dur=3, extra=()):
        sh([ff, "-v", "error", "-y", "-f", "lavfi", "-i", src, "-t", str(dur), "-pix_fmt", "yuv420p", *extra, str(data / name)])
    mk("a.mp4", "testsrc2=size=640x360:rate=16"); mk("b.mp4", "mandelbrot=size=640x360:rate=16")
    mk("static.mp4", "color=c=gray:size=640x360:rate=16"); mk("small.mp4", "testsrc2=size=64x64:rate=16")
    shutil.copy(data / "a.mp4", data / "a_copy.mp4"); (data / "broken.mp4").write_bytes(os.urandom(5000))
    (data / "a.txt").write_text("cinematic shot of a test pattern")
    (tmp / "caps.csv").write_text("file_name,caption\nb.mp4,a zooming fractal anime style\n")
    cfg = Config(work_dir=str(tmp / "work"), data_dirs=[str(data)], chunk=3, workers=2, ckpt_every=1); setup_logging(cfg); db = DB(cfg)
    r = scan(cfg, db)
    def S(n):
        return db.con.execute(
            "SELECT status,reason FROM clips WHERE path=?",
            (str(data / n),)
        ).fetchone()
    ok("scan: a.mp4 ok", S("a.mp4") is not None and S("a.mp4")[0] == "ok")
    ok("scan: b.mp4 ok", S("b.mp4")[0] == "ok"); ok("scan: static مرفوض", S("static.mp4")[0] == "rejected" and "static" in S("static.mp4")[1])
    ok("scan: small مرفوض (دقة)", S("small.mp4")[0] == "rejected"); ok("scan: broken corrupt", S("broken.mp4")[0] == "corrupt")
    ok("scan: الأصل محفوظ والنسخة dup",
       S("a.mp4") is not None and S("a.mp4")[0] == "ok"
       and S("a_copy.mp4") is not None and S("a_copy.mp4")[0] == "dup")
    r2 = scan(cfg, db); ok("scan: الاستئناف لا يعيد المعالجة", r2["processed"] == 0 and r2["skipped"] >= 6)
    db.con.execute("DELETE FROM clips WHERE path LIKE '%/a_copy.mp4'")
    db.con.execute("UPDATE clips SET status='ok' WHERE path LIKE '%/a.mp4'")
    db.con.commit()
    import_captions(cfg, db, tmp / "caps.csv"); apply_captions(db)
    p, ver, n = make_manifest(cfg, db); ok("manifest: a(sidecar)+b(csv) = 2", n == 2)
    items, v2 = load_manifest(cfg); ok("manifest: إصدار ثابت", v2 == ver and {i["category"] for i in items} >= {"anime"})
    cm = CheckpointManager(tmp / "ck", keep=2)
    for s in (1, 2, 3): cm.save(s, {"step": s, "w": [s] * 10})
    ok("ckpt: SAFE RETENTION يحتفظ بجميع النقاط", len(list((tmp / "ck").glob("ckpt_*.pt"))) == 3)
    last = sorted((tmp / "ck").glob("ckpt_*.pt"))[-1]; last.write_bytes(last.read_bytes()[:-10] + b"xxxxxxxxxx")
    s, pl = cm.load_latest(); ok("ckpt: تالف → رجوع للسابق (step=2)", s == 2 and pl["w"] == [2] * 10)
    (tmp / "ck" / "ckpt_00000009.pt").write_bytes(b"partial"); s, _ = cm.load_latest(); ok("ckpt: ملف بلا sha256 يُتجاهل", s == 2)
    sa = Sampler(5, 1); full = [sa.next() for _ in range(8)]; sb = Sampler(5, 1); [sb.next() for _ in range(6)]; stt = sb.state()
    sc = Sampler(5, 1, **stt); ok("sampler: الاستئناف يطابق التسلسل الكامل", [sc.next(), sc.next()] == full[6:8])
    ok("tiers: 16GB→tier2", (lambda r: (setattr(r, "snapshot", lambda: {"vram_total_gb": 15.0}), r.pick_tier())[1])(Resources(cfg)) == 2)
    ok("tiers: 4k+1 وأبعاد/16", all((f - 1) % 4 == 0 and h % 16 == 0 and w % 16 == 0 for f, h, w in TIERS))
    cache = LatentCache(cfg, db, 2)
    cp = cache.path(1, 0)
    cp.write_bytes(b"x" * 1000)
    atomic_write(str(cp) + ".sha256", sha256_file(cp))
    cache.add(1, 0, 1000)
    db.con.commit()
    ok("cache: checksum validation", cache.has(1, 0))
    cache.evict(0.0)
    ok("cache: SAFE RETENTION prevents eviction", cache.has(1, 0))
    outv = tmp / "enh.mp4"; used = enhance(Config(work_dir=cfg.work_dir, sr="ffmpeg"), data / "a.mp4", outv, 1.5, 24, "cinematic")
    pr = probe(outv); ok("enhance: دقة ×1.5 و24fps", pr and pr["width"] == 960 and abs(pr["fps"] - 24) < 1)
    ma, mb = video_metrics(data / "a.mp4"), video_metrics(outv); ok("metrics: صالحة", ma and mb and 0 <= ma["sharp_n"] <= 1)
    for nm, vals in (("b", {"sharp_n": .5, "flicker": .01}), ("n", {"sharp_n": .45, "flicker": .02})):
        jdump({"aggregate": vals}, tmp / f"{nm}.json")
    ok("compare: يكشف التراجع", compare(tmp / "b.json", tmp / "n.json", 0.05)["verdict"] == "regression")
    jdump({"aggregate": {"sharp_n": .55, "flicker": .009}}, tmp / "g.json"); v = compare(tmp / "b.json", tmp / "g.json", 0.05); jdump(v, tmp / "v.json")
    ok("compare: تحسّن = ok", v["verdict"] == "ok")
    try: promote(cfg, last, tmp / "n.json"); rej = False
    except SystemExit: rej = True
    ok("promote: يرفض بلا verdict ok", rej); d1 = promote(cfg, tmp / "ck" / "ckpt_00000002.pt", tmp / "v.json"); ok("promote: ينجح مع ok", d1.exists())
    p, neg = EVAL_SHOTS[0].to_prompt(); ok("plan: prompt منظّم", "tracking shot" in p and neg)
    print(f"\n{sum(1 for _, c in results if c)}/{len(results)} نجح | ملاحظة: prepare/train/generate تحتاج GPU ولم تُختبر هنا")
    shutil.rmtree(tmp, ignore_errors=True); return all(c for _, c in results)

def main():
    ap = argparse.ArgumentParser(description=f"cinema_trainer {VERSION}"); ap.add_argument("--config"); ap.add_argument("--work-dir")
    sp = ap.add_subparsers(dest="cmd", required=True)
    for n in ("selftest", "status", "scan", "manifest", "prepare", "train", "pipeline", "rollback", "captions", "fetch", "baseline", "generate", "eval"): sp.add_parser(n)
    sp.choices["captions"].add_argument("file"); e = sp.add_parser("enhance"); [e.add_argument(a) for a in ("inp", "out")]
    e.add_argument("--scale", type=float, default=2.0); e.add_argument("--fps", type=int, default=0); e.add_argument("--grade", default="cinematic")
    c = sp.add_parser("compare"); c.add_argument("base"); c.add_argument("new"); c.add_argument("--tol", type=float, default=0.05)
    pm = sp.add_parser("promote"); pm.add_argument("ckpt"); pm.add_argument("--verdict"); pm.add_argument("--force", action="store_true")
    pl = sp.add_parser("plan"); pl.add_argument("subject"); pl.add_argument("--action", default=""); pl.add_argument("--setting", default="")
    pl.add_argument("--style", default="cinematic", choices=list(STYLES)); pl.add_argument("--camera", default="static"); pl.add_argument("--lighting", default="overcast")
    for n in ("kaggle-push", "kaggle-status", "kaggle-output"):
        k = sp.add_parser(n); k.add_argument("--slug", required=True)
        if n == "kaggle-push": k.add_argument("--datasets", nargs="*", default=[]); k.add_argument("--kernels", nargs="*", default=[]); k.add_argument("--cpu", action="store_true")
        if n == "kaggle-output": k.add_argument("--dest", default="kaggle_out")
    a = ap.parse_args()
    if a.cmd == "selftest": logging.basicConfig(level=logging.WARNING); sys.exit(0 if selftest() else 1)
    cfg = Config.load(a.config, work_dir=a.work_dir); setup_logging(cfg)
    for s in (signal.SIGINT, signal.SIGTERM): signal.signal(s, lambda *_: STOP.set())
    if a.cmd == "kaggle-push": sys.exit(kaggle_push(a.slug, a.config, a.datasets, a.kernels, gpu=not a.cpu))
    if a.cmd == "kaggle-status": sys.exit(subprocess.call(["kaggle", "kernels", "status", a.slug]))
    if a.cmd == "kaggle-output": sys.exit(subprocess.call(["kaggle", "kernels", "output", a.slug, "-p", a.dest]))
    if a.cmd == "plan":
        p, n = Shot(a.subject, a.action, a.setting, a.style, a.camera, a.lighting).to_prompt(); print(json.dumps({"prompt": p, "negative": n}, ensure_ascii=False, indent=1)); return
    if a.cmd == "enhance": enhance(cfg, a.inp, a.out, a.scale, a.fps, a.grade); return
    if a.cmd == "compare": print(json.dumps(compare(a.base, a.new, a.tol), indent=1)); return
    if a.cmd == "promote": promote(cfg, a.ckpt, a.verdict, a.force); return
    if a.cmd == "rollback": rollback(cfg); return
    if a.cmd == "status": print_status(cfg); return
    if a.cmd == "captions": db = DB(cfg); import_captions(cfg, db, a.file); apply_captions(db); return
    if a.cmd == "fetch": [fetch_hf(cfg, s) for s in cfg.fetch]; return
    if a.cmd == "scan": scan(cfg); return
    if a.cmd == "manifest": make_manifest(cfg); return
    if a.cmd == "prepare": prepare(cfg); return
    if a.cmd == "train": train(cfg); return
    if a.cmd == "baseline": evaluate(cfg, generate(cfg, "baseline"), cfg.wd_path / "baseline_report.json"); return
    if a.cmd == "generate": generate(cfg, "tuned", lora=str(cfg.wd_path / "lora_latest.pt")); return
    if a.cmd == "eval": evaluate(cfg, cfg.wd_path / "gen" / "tuned", cfg.wd_path / "tuned_report.json"); return
    if a.cmd == "pipeline": pipeline(cfg); return

if __name__ == "__main__":
    main()
