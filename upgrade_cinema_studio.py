from pathlib import Path
from datetime import datetime
import shutil
import sys

p = Path("studio/static/app.js")
s = p.read_text()

def replace_once(old, new, label):
    global s
    count = s.count(old)
    if count != 1:
        print(f"STOP: {label}: expected 1 match, found {count}")
        sys.exit(1)
    s = s.replace(old, new, 1)
    print("OK:", label)

# تأكيد أن صفحة المعاينة المستقلة تعرض واجهة التوليد
route_old = 'else if (hash === "#/preview") view = await aiStudio();'
if s.count(route_old) != 1:
    print("STOP: preview route is not connected to aiStudio")
    sys.exit(1)

# 1. جعل مساحة المعاينة واضحة وثابتة
replace_once(
'''  const previewBox = h("section", {
    style:
      "margin-top:22px;padding:15px;background:#12121a;" +
      "border:1px solid #34344a;border-radius:14px",
    "aria-live": "polite"
  });''',
'''  const previewBox = h("section", {
    style:
      "width:100%;box-sizing:border-box;margin-top:22px;padding:16px;" +
      "background:#12121a;border:1px solid #34344a;border-radius:16px;" +
      "overflow:hidden",
    "aria-live": "polite"
  });''',
"preview panel layout"
)

# 2. إطار ثابت حتى قبل أول عملية توليد
replace_once(
'''            "width:100%;aspect-ratio:16/9;background:#050509;" +
            "border:2px solid #4a9eff;border-radius:12px;" +''',
'''            "width:100%;min-height:260px;aspect-ratio:16/9;" +
            "box-sizing:border-box;background:#050509;" +
            "border:2px solid #4a9eff;border-radius:12px;" +
            "overflow:hidden;" +''',
"permanent empty video frame"
)

# 3. إطار الفيديو النهائي
replace_once(
'''            "display:block;width:100%;max-height:620px;" +
            "aspect-ratio:16/9;object-fit:contain;" +
            "background:#000;border-radius:10px"''',
'''            "display:block;width:100%;min-height:260px;" +
            "max-height:620px;aspect-ratio:16/9;" +
            "object-fit:contain;background:#000;" +
            "border:2px solid #4a9eff;border-radius:12px"''',
"final video player dimensions"
)

# 4. دائرة انتظار واضحة
replace_once(
'''        h("div", {
          style:"font-size:44px;animation:cinemaSpin 1.5s linear infinite"
        }, "◌"),''',
'''        h("div", {
          style:
            "width:54px;height:54px;flex:0 0 54px;" +
            "box-sizing:border-box;border:5px solid #29293c;" +
            "border-top-color:#4a9eff;border-right-color:#4a9eff;" +
            "border-radius:50%;animation:cinemaSpin .8s linear infinite"
        }),''',
"visible circular generation indicator"
)

# 5. توضيح أن مؤشر الانتظار ليس نسبة مئوية
replace_once(
'''        }, "ستظهر نتيجة الفيديو هنا عند اكتمال التوليد")''',
'''        }, "المهمة قيد التنفيذ. سيظهر الفيديو الحقيقي هنا بعد اكتمال التوليد.")''',
"generation status explanation"
)

# 6. ضمان أن الصفحة الجديدة تحتوي على prompt ومشغل الفيديو
if 'const prompt = h("textarea"' not in s:
    sys.exit("STOP: prompt input not found")

if 'form,\n    previewBox,\n    jobsBox' not in s:
    sys.exit("STOP: prompt and preview are not in the same page")

backup = p.with_name(
    p.name + ".backup.studio_" +
    datetime.now().strftime("%Y%m%d_%H%M%S")
)
shutil.copy2(p, backup)

p.write_text(s)

print("\nPATCH SUCCESS")
print("Backup:", backup)
print("Prompt + settings + permanent video frame + player verified")
