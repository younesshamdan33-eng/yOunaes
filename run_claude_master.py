#!/usr/bin/env python3
import os, sys, json, time, shutil, subprocess, re
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_claude_master.py \"Your cinematic prompt\"")
        sys.exit(1)
    
    user_prompt = sys.argv[1]
    print(f"🎬 البرومبت الخاص بك: {user_prompt}")

    claude_file = Path("claude_master.py")
    if not claude_file.exists():
        print("❌ لم يتم العثور على claude_master.py. تأكد من حفظ كود Claude أولاً.")
        sys.exit(1)

    kfile = Path.home() / ".kaggle" / "kaggle.json"
    username = json.load(open(kfile))["username"]
    job_id = int(time.time())
    kernel_slug = f"{username}/cinema-master-{job_id}"
    kdir = Path("var/cloud_job_master")
    
    if kdir.exists(): shutil.rmtree(kdir)
    kdir.mkdir(parents=True, exist_ok=True)

    # 1. قراءة كود Claude واستبدال البرومبت الافتراضي ببرومبت المستخدم
    print("📦 جاري تجهيز الكود وحقن البرومبت...")
    code = claude_file.read_text(encoding="utf-8")
    
    # استبدال سطر البرومبت داخل ملف Claude
    # الكود الأصلي يحتوي على: "prompt": "A lone astronaut walks across red desert dunes at sunset, dust blowing in the wind",
    code = re.sub(
        r'"prompt":\s*".*?",', 
        f'"prompt": {json.dumps(user_prompt)},', 
        code, 
        count=1
    )
    
    (kdir / "script.py").write_text(code, encoding="utf-8")

    # 2. إعدادات المهمة (تأكد من تفعيل GPU)
    meta = {
        "id": kernel_slug, 
        "title": f"Cinema Master {job_id}", 
        "code_file": "script.py", 
        "language": "python", 
        "kernel_type": "script", 
        "is_private": True, 
        "enable_gpu": True, 
        "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": []
    }
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    
    print("🚀 جاري إرسال المهمة إلى Kaggle...")
    subprocess.run(["kaggle", "kernels", "push", "-p", str(kdir)], check=True)
    print(f"✅ تم الإرسال: https://www.kaggle.com/code/{kernel_slug}")
    print("⏳ ننتظر الانتهاء (قد يستغرق 20-30 دقيقة لأن الكود يشغل 4 نماذج)...")
    
    # 3. المراقبة
    while True:
        r = subprocess.run(["kaggle", "kernels", "status", kernel_slug], capture_output=True, text=True)
        status = r.stdout.strip()
        if "complete" in status.lower():
            print("✅ اكتمل التوليد والمعالجة!")
            break
        elif "error" in status.lower() or "fail" in status.lower():
            print(f"❌ فشل! افحص السجلات هنا: https://www.kaggle.com/code/{kernel_slug}")
            sys.exit(1)
        time.sleep(30)
    
    # 4. التنزيل
    print("📥 جاري تنزيل الفيديو النهائي...")
    out_dir = Path("var/generated_master")
    if out_dir.exists(): shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    subprocess.run(["kaggle", "kernels", "output", kernel_slug, "-p", str(out_dir)])
    
    # البحث عن الفيديو النهائي (final_cinematic.mp4)
    mp4s = list(out_dir.rglob("final_cinematic.mp4"))
    if not mp4s:
        # البحث عن أي فيديو آخر كاحتياط
        mp4s = list(out_dir.rglob("*.mp4"))
        
    if not mp4s:
        print("❌ لم يتم العثور على أي فيديو في مخرجات Kaggle.")
        sys.exit(1)
        
    target = Path("static/master_cinematic.mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(mp4s[0], target)
    
    print("="*60)
    print(f"🎉 SUCCESS! الفيديو الخارق جاهز: {target}")
    print(f"🌐 شاهده على موقعك: http://127.0.0.1:8750/static/master_cinematic.mp4")
    print("="*60)

if __name__ == "__main__":
    main()
