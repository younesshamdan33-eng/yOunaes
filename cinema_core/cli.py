import argparse, subprocess, sys
from . import config, doctor, lifecycle

PLANNED = ["setup", "update-check", "backup", "restore", "online", "offline"]
CMDS = ["doctor", "start", "stop", "restart", "status", "logs", "test"]

def build_parser():
    p = argparse.ArgumentParser(prog="cinema", description="CINEMA CORE server manager")
    sub = p.add_subparsers(dest="cmd", metavar="command")
    for c in CMDS + PLANNED:
        sp = sub.add_parser(c, help="not implemented yet" if c in PLANNED else None)
        if c == "logs":
            sp.add_argument("-n", type=int, default=30)
    sub.add_parser("help")
    return p

def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if a.cmd in (None, "help"):
        p.print_help()
        return 0
    if a.cmd in PLANNED:
        print(f"'{a.cmd}' is not implemented yet.")
        return 2
    try:
        cfg = config.load()
    except config.ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    if a.cmd == "doctor":
        res = doctor.run(cfg)
        for n, ok, d in res:
            print(f"[{'OK' if ok else 'FAIL'}] {n}: {d}")
        return 0 if all(ok for _, ok, _ in res) else 1
    if a.cmd in ("start", "stop", "restart"):
        if a.cmd == "restart":
            lifecycle.stop(cfg)
        code, msg = (lifecycle.stop if a.cmd == "stop" else lifecycle.start)(cfg)
        print(msg)
        return code
    if a.cmd == "status":
        s = lifecycle.status(cfg)
        print(f"running={s['running']} pid={s['pid']} responding={s['responding']} url={s['url']}")
        return 0 if s["running"] else 1
    if a.cmd == "logs":
        for name in ("cinema.log", "server.out"):
            f = cfg.log_dir / name
            print(f"== {name} ==")
            if f.exists():
                print("\n".join(f.read_text(errors="replace").splitlines()[-a.n:]))
            else:
                print("(none yet)")
        return 0
    if a.cmd == "test":
        return subprocess.call([sys.executable, "-m", "pytest", "-q", "tests"], cwd=cfg.root)
    return 2
