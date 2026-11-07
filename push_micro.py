#!/usr/bin/env python3
import os, sys, json, time, subprocess, tarfile, base64
from pathlib import Path

def main():
    d = Path.home() / ".kaggle" / "kaggle.json"
    username = json.load(open(d))["username"]
    job_id = int(time.time())
    slug = f"{username}/micro-clean-{job_id}"
    kdir = Path("var/kpush_micro")
    if kdir.exists():
        import shutil; shutil.rmtree(kdir)
    kdir.mkdir(parents=True, exist_ok=True)
    
    import shutil
    shutil.copy("train_micro.py", kdir / "script.py")
    
    meta = {
        "id": slug, "title": f"Micro Train {job_id}",
        "code_file": "script.py", "language": "python", "kernel_type": "script",
        "is_private": True, "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": []
    }
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    
    for i in range(3):
        r = subprocess.run(["kaggle", "kernels", "push", "-p", str(kdir)])
        if r.returncode == 0:
            print(f"✅ تم الإرسال: https://www.kaggle.com/code/{slug}")
            return
        time.sleep(5)
    print("❌ فشل الإرسال بعد 3 محاولات")
    sys.exit(1)

if __name__ == "__main__":
    main()
