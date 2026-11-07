#!/usr/bin/env python3
import os, sys, json, time, shutil, subprocess
from pathlib import Path

def main():
    kernel_slug = "younaeshamdane/cinema-master-1793550332"
    kfile = Path.home() / ".kaggle" / "kaggle.json"
    username = json.load(open(kfile))["username"]
    
    print(f"🔍 فحص حالة المهمة: {kernel_slug}...")
    
    while True:
        r = subprocess.run(["kaggle", "kernels", "status", kernel_slug], capture_output=True, text=True)
        status = r.stdout.strip()
        
        if "complete" in status.lower():
            print("✅ اكتمل التوليد في السحابة! جاري التنزيل...")
            break
        elif "error" in status.lower() or "fail" in status.lower():
            print(f"❌ فشل Kaggle. افحص السجلات: https://www.kaggle.com/code/{kernel_slug}")
            sys.exit(1)
        else:
            print("⏳ لا يزال يعمل على كرت الشاشة (T4 بطيء جداً مع هذه النماذج)... ننتظر 60 ثانية.")
            time.sleep(60)
    
    out_dir = Path("var/generated_master")
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["kaggle", "kernels", "output", kernel_slug, "-p", str(out_dir)])
    
    mp4s = list(out_dir.rglob("*.mp4"))
    if mp4s:
        target = Path("static/master_cinematic.mp4")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(mp4s[0], target)
        print("="*60)
        print(f"🎉 SUCCESS! الفيديو جاهز في هاتفك: {target}")
        print(f"🌐 شاهده على: http://127.0.0.1:8750/static/master_cinematic.mp4")
        print("="*60)
    else:
        print("❌ لم يتم العثور على فيديو في المخرجات.")

if __name__ == "__main__":
    main()
