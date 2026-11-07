import json, random, string, time, shutil, subprocess
from pathlib import Path

job_id = "cinema-audit-" + str(int(time.time())) + "-" + "".join(
    random.choices(string.ascii_lowercase + string.digits, k=6)
)

kdir = Path("var/kpush_audit")
if kdir.exists():
    shutil.rmtree(kdir)
kdir.mkdir(parents=True)

shutil.copy("environment_check.py", kdir / "script.py")

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

with open(kdir / "kernel-metadata.json", "w") as f:
    json.dump(meta, f, indent=2)

print("Sending environment audit to Kaggle...")
result = subprocess.run(
    ["kaggle", "kernels", "push", "-p", str(kdir)]
)

if result.returncode != 0:
    raise SystemExit("Kaggle push failed. Check the error above.")

Path("last_audit_slug.txt").write_text(job_id)
print("AUDIT SLUG:", job_id)
print("KAGGLE URL: https://www.kaggle.com/code/younaeshamdane/" + job_id)
