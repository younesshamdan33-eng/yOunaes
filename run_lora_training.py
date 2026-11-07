#!/usr/bin/env python3
import os, sys, json, time, shutil, subprocess, re
from pathlib import Path

def main():
    claude_file = Path("claude_lora_trainer.py")
    if not claude_file.exists():
        print("❌ لم يتم العثور على claude_lora_trainer.py. تأكد من حفظ كود Claude أولاً.")
        sys.exit(1)

    kfile = Path.home() / ".kaggle" / "kaggle.json"
    username = json.load(open(kfile))["username"]
    job_id = int(time.time())
    kernel_slug = f"{username}/lora-trainer-{job_id}"
    kdir = Path("var/cloud_job_lora")
    
    if kdir.exists(): shutil.rmtree(kdir)
    kdir.mkdir(parents=True, exist_ok=True)

    print("📦 جاري تجهيز الكود وبناء مجموعة البيانات...")
    code = claude_file.read_text(encoding="utf-8")
    
    # 1. إضافة كود تجهيز البيانات + تثبيت torchao في بداية السكريبت
    dataset_setup = '''
import os, sys, urllib.request
os.makedirs("/kaggle/working/dataset/clips", exist_ok=True)
os.makedirs("/kaggle/working/dataset/captions", exist_ok=True)
urls = [
    "https://github.com/intel-iot-devkit/sample-videos/raw/master/car-detection.mp4",
    "https://github.com/intel-iot-devkit/sample-videos/raw/master/people-detection.mp4",
    "https://github.com/intel-iot-devkit/sample-videos/raw/master/store-aisle-detection.mp4"
]
for i, url in enumerate(urls):
    path = f"/kaggle/working/dataset/clips/clip_{i}.mp4"
    if not os.path.exists(path):
        print(f"Downloading dummy dataset clip {i}...")
        urllib.request.urlretrieve(url, path)
    with open(f"/kaggle/working/dataset/captions/clip_{i}.txt", "w") as f:
        f.write("cinematic street scene, highly detailed, 8k resolution, photorealistic")
'''
    # حقن الكود في البداية
    code = dataset_setup + "\n\n" + code

    # 2. استبدال سطر pip install الأصلي ليشمل torchao==0.16.0
    # السطر الأصلي في كود Claude هو:
    # run([sys.executable, "-m", "pip", "install", "-q", "diffusers>=0.33.0", "transformers>=4.49",
    #      "accelerate", "peft>=0.14.0", "bitsandbytes", "ftfy", "sentencepiece", "imageio", "imageio-ffmpeg"])
    # سنقوم بإضافة torchao==0.16.0 إليه
    code = code.replace(
        '"imageio-ffmpeg"])',
        '"imageio-ffmpeg", "torchao==0.16.0"])'
    )
    
    (kdir / "script.py").write_text(code, encoding="utf-8")

    meta = {
        "id": kernel_slug, 
        "title": f"LoRA Trainer {job_id}", 
        "code_file": "script.py", 
        "language": "python", 
        "kernel_type": "script", 
        "is_private": True, 
        "enable_gpu": True, 
        "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": []
    }
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    
    print("🚀 جاري إرسال مهمة التدريب إلى Kaggle...")
    subprocess.run(["kaggle", "kernels", "push", "-p", str(kdir)], check=True)
    print(f"✅ تم الإرسال: https://www.kaggle.com/code/{kernel_slug}")
    print("⏳ ننتظر انتهاء التدريب (قد يستغرق 20-40 دقيقة)...")
    
    while True:
        r = subprocess.run(["kaggle", "kernels", "status", kernel_slug], capture_output=True, text=True)
        status = r.stdout.strip()
        if "complete" in status.lower():
            print("✅ اكتمل التدريب!")
            break
        elif "error" in status.lower() or "fail" in status.lower():
            print(f"❌ فشل! افحص السجلات: https://www.kaggle.com/code/{kernel_slug}")
            sys.exit(1)
        time.sleep(30)
    
    print("📥 جاري تنزيل النتائج (ملفات LoRA وفيديوهات الاختبار)...")
    out_dir = Path("var/lora_results")
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["kaggle", "kernels", "output", kernel_slug, "-p", str(out_dir)])
    
    mp4s = list(out_dir.rglob("test*_BASE_vs_LORA.mp4"))
    if mp4s:
        target = Path("static/lora_test_comparison.mp4")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(mp4s[0], target)
        print("="*60)
        print(f"🎉 SUCCESS! فيديو المقارنة (قبل وبعد) جاهز: {target}")
        print(f"🌐 شاهده على موقعك: http://127.0.0.1:8750/static/lora_test_comparison.mp4")
        print("="*60)
    else:
        print("⚠️ اكتمل التدريب لكن لم يتم العثور على فيديو المقارنة. افحص مجلد var/lora_results")

if __name__ == "__main__":
    main()
