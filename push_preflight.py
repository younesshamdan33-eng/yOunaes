import json, time, subprocess, shutil, sys
from pathlib import Path

job_id = f"preflight-{int(time.time())}"
kdir = Path("var/kpush_preflight")

if kdir.exists():
    shutil.rmtree(kdir)

kdir.mkdir(parents=True)

shutil.copy("preflight.py", kdir / "script.py")

meta = {
    "id": f"younaeshamdane/{job_id}",
    "title": job_id.replace("-", " ").title(),
    "code_file": "script.py",
    "language": "python",
    "kernel_type": "script",
    "is_private": True,
    "enable_gpu": True,
    "enable_internet": True,
    "dataset_sources": [],
    "competition_sources": [],
    "kernel_sources": []
}

(kdir / "kernel-metadata.json").write_text(
    json.dumps(meta, indent=2)
)

result = subprocess.run(
    ["kaggle", "kernels", "push", "-p", str(kdir)]
)

if result.returncode:
    sys.exit("Kaggle push failed")

print("JOB:", job_id)
print("URL:", f"https://www.kaggle.com/code/younaeshamdane/{job_id}")
