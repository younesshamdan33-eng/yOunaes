#!/usr/bin/env python3
import os, time, subprocess, shutil
from pathlib import Path

def main():
    kernel_slug = "younaeshamdane/lora-trainer-1793559464"
    out_dir = Path("var/lora_results")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print("⏳ جاري محاولة تنزيل النتائج (سيظل يحاول حتى ينجح)...")
    
    for attempt in range(1, 20): # محاولة 20 مرة
        print(f"🔄 المحاولة {attempt}...")
        r = subprocess.run(["kaggle", "kernels", "output", kernel_slug, "-p", str(out_dir)], 
                           capture_output=True, text=True)
        
        if r.returncode == 0:
            videos = list(out_dir.rglob("test*_BASE_vs_LORA.mp4"))
            if videos:
                print("✅ اكتمل التنزيل بنجاح!")
                target = Path("static/lora_comparison.mp4")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(videos[0], target)
                print("="*60)
                print(f"🎉 الفيديو جاهز: {target}")
                print(f"🌐 شاهده على موقعك: http://127.0.0.1:8750/static/lora_comparison.mp4")
                print("="*60)
                return
        print("⚠️ انقطع الاتصال، جاري المحاولة مرة أخرى بعد 5 ثوانٍ...")
        time.sleep(5)
        
    print("❌ فشل التنزيل بعد كل المحاولات. قد تحتاج إلى شبكة إنترنت أقوى.")

if __name__ == "__main__":
    main()
