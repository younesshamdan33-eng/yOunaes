"""Optional public access via a cloudflared Quick Tunnel (layer 3).
Exposes ONLY what the local server serves (/health, /ready), no auth. Temporary URL."""
import os, re, shutil, signal, subprocess, time
from .lifecycle import _alive, _cmdline, _tail, health

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
NOT_A_TUNNEL = "https://api.trycloudflare.com"

WARNING = """PUBLIC ACCESS WARNING
- This creates a public https URL (trycloudflare.com) to your local server.
- Anyone who has the URL can reach it. There is NO authentication.
- Currently exposed: /health and /ready only. Do not add admin endpoints without auth.
- Traffic passes through Cloudflare. The URL is temporary and ends on: cinema offline / cinema stop.
- Android may kill the tunnel when the phone sleeps or Termux is closed.
To proceed, run: cinema online --yes"""

def _binary():
    exe = shutil.which("cloudflared")
    return [exe] if exe else None

def _files(cfg):
    return cfg.run_dir / "tunnel.pid", cfg.run_dir / "tunnel.url", cfg.log_dir / "tunnel.log"

def _rm(*paths):
    for p in paths:
        try:
            p.unlink()
        except OSError:
            pass

def _state(cfg):
    pidf, urlf, _ = _files(cfg)
    try:
        pid = int(pidf.read_text().strip())
    except (OSError, ValueError):
        return None, None, "none"
    if not _alive(pid):
        return pid, None, "stale"
    cmd = _cmdline(pid)
    if cmd is None:
        return pid, None, "unverified"
    if "cloudflared" not in cmd:
        return pid, None, "foreign"
    try:
        url = urlf.read_text().strip()
    except OSError:
        url = None
    return pid, url, "owned"

def _stop_proc(p):
    p.terminate()
    try:
        p.wait(3)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()

def online(cfg, confirmed=False):
    pid, url, st = _state(cfg)
    if st == "owned":
        return 0, f"already online: {url}"
    if st == "unverified":
        return 1, "cannot verify tunnel process ownership; not touching it"
    if not health(cfg):
        return 1, "local server is not running; run: cinema start"
    cmd = _binary()
    if not cmd:
        return 1, "cloudflared not found (pkg install cloudflared)"
    if not confirmed:
        return 1, WARNING
    pidf, urlf, logf = _files(cfg)
    _rm(pidf, urlf)
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    with open(logf, "wb") as out:
        p = subprocess.Popen(cmd + ["tunnel", "--no-autoupdate", "--url", f"http://{cfg.host}:{cfg.port}"],
                             stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
    pidf.write_text(str(p.pid))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if p.poll() is not None:
            _rm(pidf, urlf)
            return 1, f"cloudflared exited ({p.returncode}):\n{_tail(logf)}"
        try:
            found = [u for u in URL_RE.findall(logf.read_text(errors="replace")) if u != NOT_A_TUNNEL]
        except OSError:
            found = []
        if found:
            urlf.write_text(found[0])
            return 0, f"ONLINE (public, no auth): {found[0]}\nStop with: cinema offline"
        time.sleep(0.5)
    _stop_proc(p)
    _rm(pidf, urlf)
    return 1, f"timed out waiting for tunnel URL; tunnel stopped:\n{_tail(logf)}"

def offline(cfg):
    pid, _, st = _state(cfg)
    pidf, urlf, _ = _files(cfg)
    if st == "unverified":
        return 1, "cannot verify tunnel process ownership; not touching it"
    if st == "owned":
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and _alive(pid):
            time.sleep(0.2)
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
        if _alive(pid):
            return 1, "could not stop tunnel process"
        _rm(pidf, urlf)
        return 0, "offline (tunnel stopped)"
    _rm(pidf, urlf)
    return 0, "not online" + ("" if st == "none" else " (stale state removed)")
