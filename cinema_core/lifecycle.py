import json, os, signal, subprocess, sys, time, urllib.request
from pathlib import Path

PKG_PARENT = str(Path(__file__).resolve().parent.parent)

def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        st = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        if st == "Z":
            return False
    except (OSError, IndexError):
        pass
    return True

def _cmdline(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return None

def health(cfg, timeout=1.5):
    try:
        with urllib.request.urlopen(f"http://{cfg.host}:{cfg.port}/health", timeout=timeout) as r:
            d = json.loads(r.read(4096))
        return d if d.get("service") == "cinema-core" else None
    except Exception:
        return None

def read_pid(cfg):
    try:
        return int(cfg.pid_file.read_text().strip())
    except (OSError, ValueError):
        return None

def owned_pid(cfg):
    pid = read_pid(cfg)
    if pid is None or not _alive(pid):
        return None
    cmd = _cmdline(pid)
    if cmd is not None:
        return pid if "cinema_core.server" in cmd else None
    h = health(cfg)
    return pid if h and h.get("pid") == pid else None

def _rm_pid(cfg):
    try:
        cfg.pid_file.unlink()
    except OSError:
        pass

def _tail(path, n=10):
    try:
        return "\n".join(Path(path).read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""

def start(cfg):
    pid = owned_pid(cfg)
    if pid:
        return 0, f"already running (pid {pid})"
    if cfg.pid_file.exists():
        _rm_pid(cfg)
    if health(cfg):
        return 1, f"a cinema server answers on port {cfg.port} but is not owned by this install"
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    outf = cfg.log_dir / "server.out"
    if outf.exists() and outf.stat().st_size > 1_000_000:
        outf.replace(cfg.log_dir / "server.out.1")
    env = dict(os.environ, CINEMA_ROOT=str(cfg.root), PYTHONPATH=PKG_PARENT)
    with open(outf, "ab") as out:
        p = subprocess.Popen([sys.executable, "-m", "cinema_core.server"], cwd=cfg.root, env=env,
                             stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
    cfg.pid_file.write_text(str(p.pid))
    deadline = time.monotonic() + cfg.start_timeout
    while time.monotonic() < deadline:
        if p.poll() is not None:
            _rm_pid(cfg)
            return 1, f"server exited with code {p.returncode}:\n{_tail(outf)}"
        if health(cfg):
            return 0, f"started (pid {p.pid}) on http://{cfg.host}:{cfg.port}"
        time.sleep(0.25)
    p.terminate()
    try:
        p.wait(3)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    _rm_pid(cfg)
    return 1, "startup timed out; process stopped"

def stop(cfg):
    pid = owned_pid(cfg)
    if pid is None:
        stale = cfg.pid_file.exists()
        _rm_pid(cfg)
        return 0, "not running" + (" (stale pid file removed)" if stale else "")
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + cfg.stop_timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            _rm_pid(cfg)
            return 0, "stopped"
        time.sleep(0.2)
    os.kill(pid, signal.SIGKILL)
    time.sleep(0.5)
    _rm_pid(cfg)
    return (0, "stopped (forced)") if not _alive(pid) else (1, "could not stop process")

def status(cfg):
    pid = owned_pid(cfg)
    h = health(cfg) if pid else None
    return {"running": bool(pid and h), "pid": pid, "responding": bool(h),
            "url": f"http://{cfg.host}:{cfg.port}"}
