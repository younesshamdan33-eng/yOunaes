import json, logging, os, signal, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from .config import load, ConfigError

log = logging.getLogger("cinema")

class Handler(BaseHTTPRequestHandler):
    timeout = 10
    server_version = "CinemaCore"

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._send(200, {"status": "ok", "service": "cinema-core", "pid": os.getpid()})
        elif path == "/ready":
            self._send(200, {"ready": True, "service": "cinema-core", "pid": os.getpid()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        self._send(405, {"error": "method not allowed"})
    do_PUT = do_DELETE = do_PATCH = do_POST

    def log_message(self, fmt, *args):
        log.info("http %s", fmt % args)

def main():
    try:
        cfg = load()
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(cfg.log_dir / "cinema.log", maxBytes=512 * 1024, backupCount=3)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    try:
        srv = ThreadingHTTPServer((cfg.host, cfg.port), Handler)
    except OSError as e:
        log.error("cannot bind %s:%s: %s", cfg.host, cfg.port, e)
        print(f"cannot bind {cfg.host}:{cfg.port}: {e}", file=sys.stderr)
        return 3
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=srv.shutdown).start())
    log.info("ready on %s:%s pid=%s", cfg.host, cfg.port, os.getpid())
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        log.info("stopped")
    return 0

if __name__ == "__main__":
    sys.exit(main())
