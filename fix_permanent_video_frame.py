from pathlib import Path
from datetime import datetime
import shutil
import re

app = Path("studio/static/app.js")
html = Path("studio/static/index.html")

s = app.read_text(encoding="utf-8")

def replace_once(source, old, new, label):
    n = source.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected 1 match, found {n}")
    return source.replace(old, new, 1)

# Add a permanent preview frame after jobsBox.
old = '''  const jobsBox = h("div", {
    style: "margin-top:24px",
    "aria-live": "polite"
  });'''

new = '''  const previewBox = h("section", {
    style:
      "margin-top:22px;padding:15px;background:#12121a;" +
      "border:1px solid #34344a;border-radius:14px",
    "aria-live": "polite"
  });

  // This frame always exists, even before the first generation.
  function renderPreview(jobs) {
    previewBox.replaceChildren();

    previewBox.append(
      h("h3", {
        style: "margin:0 0 13px;color:#eee;font-size:18px"
      }, "🎬 معاينة الفيديو")
    );

    const active = jobs.find(j =>
      ["queued","pushing","generating","downloading"].includes(j.status)
    );

    const completed = [...jobs].reverse().find(j =>
      j.video_file && j.status === "done"
    );

    const current = active || completed || jobs[0];

    if (!current) {
      previewBox.append(
        h("div", {
          style:
            "width:100%;aspect-ratio:16/9;background:#050509;" +
            "border:1px dashed #414158;border-radius:10px;" +
            "display:flex;align-items:center;justify-content:center;" +
            "flex-direction:column;gap:12px;color:#aaa"
        },
          h("div", { style:"font-size:48px" }, "🎥"),
          h("strong", {}, "مكان ظهور الفيديو"),
          h("span", { style:"font-size:12px" },
            "سيظهر الفيديو هنا بعد التوليد")
        )
      );
      return;
    }

    if (current.video_file && current.status === "done") {
      const url =
        "/api/cinema/videos/" + encodeURIComponent(current.video_file);

      previewBox.append(
        h("div", {
          style:"color:#10b981;margin-bottom:10px;font-weight:600"
        }, "✓ الفيديو جاهز"),
        h("video", {
          controls:true,
          playsinline:true,
          preload:"metadata",
          src:url,
          style:
            "display:block;width:100%;max-height:620px;" +
            "aspect-ratio:16/9;object-fit:contain;" +
            "background:#000;border-radius:10px"
        }),
        h("a", {
          class:"btn primary",
          href:url,
          download:current.video_file,
          style:"display:inline-block;margin-top:12px;text-decoration:none"
        }, "تنزيل الفيديو MP4")
      );
      return;
    }

    if (current.status === "failed") {
      previewBox.append(
        h("div", {
          style:
            "aspect-ratio:16/9;background:#08080d;border-radius:10px;" +
            "display:flex;align-items:center;justify-content:center;" +
            "flex-direction:column;gap:12px;color:#ef4444"
        },
          h("div", {style:"font-size:42px"}, "⚠️"),
          h("strong", {}, "فشل توليد الفيديو"),
          h("span", {style:"font-size:12px;text-align:center"},
            current.message || "راجع تفاصيل المهمة")
        )
      );
      return;
    }

    const stages = {
      queued:"المهمة في قائمة الانتظار",
      pushing:"إرسال المهمة إلى Kaggle",
      generating:"النموذج يولّد الفيديو",
      downloading:"جارٍ تنزيل الفيديو إلى الموقع"
    };

    previewBox.append(
      h("div", {
        style:
          "aspect-ratio:16/9;background:#08080d;border-radius:10px;" +
          "display:flex;align-items:center;justify-content:center;" +
          "flex-direction:column;gap:18px;padding:20px;box-sizing:border-box"
      },
        h("div", {
          style:"font-size:44px;animation:cinemaSpin 1.5s linear infinite"
        }, "◌"),
        h("strong", {
          style:"color:#eee;text-align:center"
        }, stages[current.status] || "المهمة قيد التنفيذ"),
        h("div", {
          style:
            "width:90%;max-width:400px;height:8px;" +
            "background:#29293c;border-radius:20px;overflow:hidden"
        },
          h("div", {
            style:
              "height:100%;width:35%;background:#4a9eff;" +
              "border-radius:20px;animation:cinemaBar 1.5s ease-in-out infinite"
          })
        ),
        h("span", {
          style:"color:#999;font-size:12px;text-align:center"
        }, "ستظهر نتيجة الفيديو هنا عند اكتمال التوليد")
      )
    );
  }

  if (!document.getElementById("cinema-preview-animation")) {
    const style = document.createElement("style");
    style.id = "cinema-preview-animation";
    style.textContent =
      "@keyframes cinemaSpin{to{transform:rotate(360deg)}}" +
      "@keyframes cinemaBar{0%{transform:translateX(-120%)}" +
      "100%{transform:translateX(300%)}}";
    document.head.appendChild(style);
  }

  const jobsBox = h("div", {
    style: "margin-top:24px",
    "aria-live": "polite"
  });'''

s = replace_once(s, old, new, "permanent preview insertion")

# Render the preview every time the jobs API is refreshed.
old = '''      jobsBox.replaceChildren();

      if (!ordered.length) {'''

new = '''      renderPreview(ordered);
      jobsBox.replaceChildren();

      if (!ordered.length) {'''

s = replace_once(s, old, new, "preview refresh connection")

# Put the permanent preview between the form and job history.
old = '''    form,
    jobsBox
  );'''

new = '''    form,
    previewBox,
    jobsBox
  );'''

s = replace_once(s, old, new, "preview page placement")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = app.with_name(app.name + ".backup." + stamp)
shutil.copy2(app, backup)

html_backup = None
if html.exists():
    html_backup = html.with_name(html.name + ".backup." + stamp)
    shutil.copy2(html, html_backup)

app.write_text(s, encoding="utf-8")

# Change the app.js URL to prevent the browser from using an old cached copy.
if html.exists():
    page = html.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'app\.js(?:\?[^"\' ]*)?',
        'app.js?v=cinema-preview-20261103',
        page,
        count=1
    )
    if count:
        html.write_text(updated, encoding="utf-8")
        print("CACHE VERSION UPDATED:", html)
    else:
        print("NOTICE: app.js reference not found in index.html")

print("BACKUP:", backup)
if html_backup:
    print("HTML BACKUP:", html_backup)
print("PATCH COMPLETE")
