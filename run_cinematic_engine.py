import os, sys, json, time, shutil, subprocess, tarfile, base64
from pathlib import Path

def main():
    engine_dir = Path("cinematic_engine")
    if not engine_dir.exists():
        print("❌ لم يتم العثور على مجلد cinematic_engine")
        sys.exit(1)

    print("📦 جاري ضغط المحرك السينمائي...")
    tar_path = "engine.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(engine_dir, arcname="cinematic_engine")

    with open(tar_path, "rb") as f:
        encoded_engine = base64.b64encode(f.read()).decode('utf-8')
    
    os.remove(tar_path)
    print(f"✅ تم تشفير المحرك (حجم النص: {len(encoded_engine)} حرف)")

    kfile = Path.home() / ".kaggle" / "kaggle.json"
    username = json.load(open(kfile))["username"]
    job_id = int(time.time())
    kernel_slug = f"{username}/cinematic-test-{job_id}"
    kdir = Path("var/cloud_job_cinematic")
    
    if kdir.exists(): shutil.rmtree(kdir)
    kdir.mkdir(parents=True, exist_ok=True)

    # هذا هو السكريبت الذي سيعمل داخل Kaggle
    kaggle_script = f'''
import os, subprocess, sys, tarfile, base64

print("🔧 Installing dependencies...")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "torch", "torchvision", "diffusers>=0.35.0", "transformers>=4.46.0", "accelerate", "safetensors", "sentencepiece", "protobuf", "opencv-python-headless", "imageio[ffmpeg]", "numpy", "Pillow", "huggingface_hub", "tqdm", "--use-deprecated=legacy-resolver"], check=False)

print("📦 Extracting engine...")
encoded_engine = """{encoded_engine}"""
with open("engine.tar.gz", "wb") as f:
    f.write(base64.b64decode(encoded_engine))

with tarfile.open("engine.tar.gz", "r:gz") as tar:
    tar.extractall(".")

os.chdir("cinematic_engine")
os.makedirs("outputs", exist_ok=True)

print("🚀 Running benchmark...")
subprocess.run([sys.executable, "benchmark.py"], check=True)
print("SUCCESS")
'''
    (kdir / "script.py").write_text(kaggle_script)
    
    meta = {
        "id": kernel_slug, "title": f"Cinematic Test {job_id}",
        "code_file": "script.py", "language": "python",
        "kernel_type": "script", "is_private": True,
        "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": []
    }
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    
    print("🚀 جاري الإرسال إلى Kaggle...")
    subprocess.run(["kaggle", "kernels", "push", "-p", str(kdir)], check=True)
    print(f"✅ تم الإرسال: https://www.kaggle.com/code/{kernel_slug}")
    
if __name__ == "__main__":
    main()
