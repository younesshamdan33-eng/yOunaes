from pathlib import Path
import re
import sys

p = Path("cinema_trainer.py")
src = p.read_text(encoding="utf-8")

a = src.find("class CheckpointManager:")
b = src.find("# ============================================================ كاش الـ latents", a)

if a < 0 or b < 0 or b <= a:
    sys.exit("ERROR: CheckpointManager boundaries not found. No changes made.")

checkpoint = r'''
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
        import torch
        return torch.load(p, map_location="cpu", weights_only=False)

    @staticmethod
    def _step_number(path):
        m = re.search(r"ckpt_(\d+)\.pt$", Path(path).name)
        return int(m.group(1)) if m else -1

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

'''

src = src[:a] + checkpoint + src[b:]

a = src.find("class LatentCache:")
b = src.find("def crop_latent(", a)

if a < 0 or b < 0 or b <= a:
    sys.exit("ERROR: LatentCache boundaries not found. No changes made.")

cache = r'''
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


'''

src = src[:a] + cache + src[b:]

tmp = p.with_name("cinema_trainer.py.patchtmp")
tmp.write_text(src, encoding="utf-8")
tmp.replace(p)

print("PATCH APPLIED")
print("Checkpoint auto-pruning: disabled")
print("Checkpoint ordering: numeric step")
print("Latent cache checksum validation: enabled")
print("Latent cache accounting: active cache key only")
print("Latent cache auto-eviction: disabled")
