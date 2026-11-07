#!/usr/bin/env python3
import os, sys, json, time, shutil, subprocess
from pathlib import Path

def main():
    # مسار كود كلود الذي قمت بحفظه
    claude_file = Path("claude_quality.py")
    if not claude_file.exists():
        print("❌ لم يتم العثور على claude_quality.py. تأكد من حفظه أولاً.")
        sys.exit(1)

    print("📦 قراءة كود Claude وإرساله إلى Kaggle...")

    kfile = Path.home() / ".kaggle" / "kaggle.json"
    username = json.load(open(kfile))["username"]
    job_id = int(time.time())
    kernel_slug = f"{username}/claude-quality-{job_id}"
    
    kdir = Path("var/cloud_job_claude")
    kdir.mkdir(parents=True, exist_ok=True)
    
    # 1. نسخ كود Claude ليكون هو السكريبت الرئيسي في Kaggle
    shutil.copy(claude_file, kdir / "script.py")
    
    # 2. إعدادات المهمة (تأكد من تفعيل GPU)
    meta = {
        "id": kernel_slug, 
        "title": f"Claude Quality {job_id}", 
        "code_file": "script.py", 
        "language": "python", 
        "kernel_type": "script", 
        "is_private": True, 
        "enable_gpu": True, 
        "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": []
    }
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    
    print("🚀 جاري إرسال المهمة...")
    subprocess.run(["kaggle", "kernels", "push", "-p", str(kdir)], check=True)
    print(f"✅ تم الإرسال: https://www.kaggle.com/code/{kernel_slug}")
    print("⏳ ننتظر الانتهاء (10-20 دقيقة)...")
    
    # 3. المراقبة
    while True:
        r = subprocess.run(["kaggle", "kernels", "status", kernel_slug], capture_output=True, text=True)
        status = r.stdout.strip()
        if "complete" in status.lower():
            print("✅ اكتمل التوليد!")
            break
        elif "error" in status.lower() or "fail" in status.lower():
            print(f"❌ فشل! افحص السجلات: https://www.kaggle.com/code/{kernel_slug}")
            sys.exit(1)
        time.sleep(20)
    
    # 4. التنزيل
    print("📥 جاري تنزيل النتيجة...")
    out_dir = Path("var/generated_claude")
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["kaggle", "kernels", "output", kernel_slug, "-p", str(out_dir)])
    
    # 5. البحث عن أي فيديو mp4 في المخرجات ونقله للموقع
    mp4s = list(out_dir.rglob("*.mp4"))
    if not mp4s:
        print("❌ لم يتم العثور على أي فيديو MP4 في مخرجات Kaggle.")
        sys.exit(1)
        
    target = Path("static/final_quality_video.mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(mp4s[0], target)
    
    print("="*60)
    print(f"🎉 SUCCESS! الفيديو الجديد جاهز: {target}")
    print(f"🌐 شاهده على موقعك: http://127.0.0.1:8750/static/final_quality_video.mp4")
    print("="*60)

if __name__ == "__main__":
    main()
