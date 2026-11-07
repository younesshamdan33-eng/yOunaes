#!/usr/bin/env python3
import os, json, shutil, subprocess, tempfile

def main():
    print("🛑 جاري إيقاف المهمة الحالية وتحرير كرت الشاشة...")
    
    # اسم المهمة الذي نستخدمه
    slug = "younaeshamdane/cinema-v02"
    
    # إنشاء ملف وهمي فارغ
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "script.py"), "w") as f:
        f.write("print('Canceled to free GPU resources')\n")
    
    # إعدادات بدون كرت شاشة (CPU only) - هذا سيجبر Kaggle على قتل الجلسة
    meta = {
        "id": slug,
        "title": "cinema-v02",
        "code_file": "script.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": "true",
        "enable_gpu": "false", 
        "enable_internet": "false",
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": []
    }
    with open(os.path.join(d, "kernel-metadata.json"), "w") as f:
        json.dump(meta, f, indent=1)
    
    # رفع الملف الوهمي لإلغاء الجلسة القديمة
    subprocess.run(["kaggle", "kernels", "push", "-p", d], capture_output=True)
    shutil.rmtree(d)
    
    print("✅ تم إرسال أمر الإلغاء. انتظر 15 ثانية ليتم تحرير الموارد.")
    print("🚀 يمكنك الآن تشغيل مهمة Tom & Jerry.")

if __name__ == "__main__":
    main()
