import argparse, subprocess, sys
from . import backup, config, doctor, jobs, lifecycle

PLANNED = ["setup", "update-check", "online", "offline"]
CMDS = ["doctor", "start", "stop", "restart", "status", "logs", "test", "backup", "restore", "jobs"]

def build_parser():
    p = argparse.ArgumentParser(prog="cinema", description="CINEMA CORE server manager")
    sub = p.add_subparsers(dest="cmd", metavar="command")
    for c in CMDS + PLANNED:
        sp = sub.add_parser(c, help="not implemented yet" if c in PLANNED else None)
        if c == "logs":
            sp.add_argument("-n", type=int, default=30)
        if c == "jobs":
            sp.add_argument("--recover", action="store_true")
        if c == "restore":
            sp.add_argument("file", nargs="?")
            sp.add_argument("--yes", action="store_true")
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
    if a.cmd == "backup":
        try:
            path, n = backup.create(cfg)
        except backup.BackupError as e:
            print(f"backup failed: {e}")
            return 1
        print(f"backup OK, verified: {path} ({n} files)")
        return 0
    if a.cmd == "restore":
        if not a.file:
            for f in sorted(cfg.backup_dir.glob("cinema-*.tar.gz")):
                print(f)
            print("usage: cinema restore FILE [--yes]")
            return 2
        try:
            code, msg = backup.restore(cfg, a.file, a.yes)
        except backup.BackupError as e:
            print(f"restore failed: {e}")
            return 1
        print(msg)
        return code
    if a.cmd == "jobs":
        store = jobs.JobStore(cfg)
        if a.recover:
            print(f"recovered {store.recover()} interrupted job(s)")
        for j in store.list():
            print(f"{j['id']} {j['state']:<9} {j['progress']:>3}% {j['kind']}")
        return 0
    if a.cmd == "test":
        return subprocess.call([sys.executable, "-m", "pytest", "-q", "tests"], cwd=cfg.root)
    return 2
