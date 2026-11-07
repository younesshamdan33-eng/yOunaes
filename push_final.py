#!/usr/bin/env python3
import os, sys, json, time, subprocess, shutil, random, string
from pathlib import Path

def main():
    # 1. توليد slug جديد تماماً
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    job_id = f"micro-{int(time.time())}-{suffix}"
    
    # 2. تجهيز المجلد
    kdir = Path("var/kpush_final")
    if kdir.exists(): shutil.rmtree(kdir)
    kdir.mkdir(parents=True, exist_ok=True)
    
    # 3. نسخ السكريبت
    shutil.copy("train_micro.py", kdir / "script.py")
    
    # 4. كتابة metadata مع عنوان يطابق الـ slug تماماً
    # Kaggle يتوقع أن يكون العنوان هو نفس الـ slug (مع استبدال - بمسافة)
    title = job_id.replace("-", " ").title()  # مثال: Micro 1793665876 Abcdefgh
    
    meta = {
        "id": f"younaeshamdane/{job_id}",
        "title": title,
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
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    
    print(f"📤 جاري الإرسال إلى: https://www.kaggle.com/code/younaeshamdane/{job_id}")
    
    # 5. المحاولة 3 مرات
    for i in range(3):
        r = subprocess.run(["kaggle", "kernels", "push", "-p", str(kdir)], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"✅ تم الإرسال بنجاح في المحاولة {i+1}")
            print(f"🔗 الرابط: https://www.kaggle.com/code/younaeshamdane/{job_id}")
            return
        print(f"⚠️ فشلت المحاولة {i+1}: {r.stderr[-200:] if r.stderr else 'unknown'}")
        time.sleep(5)
    
    print("❌ فشل الإرسال بعد 3 محاولات")
    sys.exit(1)

if __name__ == "__main__":
    main()
