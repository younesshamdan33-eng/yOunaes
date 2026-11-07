from pathlib import Path
from datetime import datetime
import shutil
import sys

app = Path("studio/static/app.js")
index = Path("studio/static/index.html")

if not app.exists() or not index.exists():
    sys.exit("ERROR: Required files not found.")

src = app.read_text(encoding="utf-8")
html = index.read_text(encoding="utf-8")

patches = [
    ('["#/ai", "nav_ai", "play"], ["#/queue", "nav_queue", "list"]',
     '["#/ai", "nav_ai", "play"], ["#/preview", "معاينة التوليد", "film"], ["#/queue", "nav_queue", "list"]'),
    ('else if (hash === "#/ai") view = await aiStudio();',
     'else if (hash === "#/ai") view = await aiStudio();\n    else if (hash === "#/preview") view = await cinemaPreviewPage();'),
]

for old, new in patches:
    if src.count(old) != 1:
        sys.exit("STOP: Navigation/router anchor mismatch: " + old)

marker = "const FEATURES ="
if src.count(marker) != 1:
    sys.exit("STOP: Page insertion anchor mismatch.")

old_version = 'app.js?v=cinema-preview-20261103'
if html.count(old_version) != 1:
    sys.exit("STOP: Script version anchor mismatch.")

page = r'''
async function cinemaPreviewPage() {
  const activeStates = ["queued", "pushing", "generating", "downloading"];

  const styleId = "cinema-independent-preview-style";
  if (!document.getElementById(styleId)) {
    const style = document.createElement("style");
    style.id = styleId;
    style.textContent =
      "@keyframes cinemaPreviewScan{" +
      "0%{transform:translateX(-120%)}" +
      "100%{transform:translateX(350%)}}" +
      "@keyframes cinemaPreviewPulse{" +
      "0%,100%{opacity:.45}50%{opacity:1}}";
    document.head.appendChild(style);
  }

  const frame = h("div", {
    style:
      "position:relative;width:100%;min-height:260px;" +
      "aspect-ratio:16/9;overflow:hidden;box-sizing:border-box;" +
      "background:#050509;border:2px solid #414158;" +
      "border-radius:16px;display:flex;align-items:center;" +
      "justify-content:center;color:#eee"
  });

  const status = h("div", {
    style:"margin-top:14px;color:#bbb;font-size:14px",
    "aria-live":"polite"
  }, "جارٍ تحميل المهام...");

  const detail = h("div", {
    style:"margin-top:8px;color:#888;font-size:12px;word-break:break-word"
  });

  const refreshButton = h("button", {
    type:"button",
    class:"btn",
    onclick: refresh
  }, "تحديث المعاينة");

  const root = h("div", {class:"wrap"},
    h("h2", {
      style:"color:#eee;margin:0 0 8px;font-size:24px"
    }, "🎬 معاينة التوليد"),
    h("p", {
      class:"muted small",
      style:"margin:0 0 20px"
    }, "تابع توليد الفيديو هنا حتى اكتماله وظهور النتيجة النهائية."),
    frame,
    status,
    detail,
    h("div", {style:"margin-top:18px"}, refreshButton)
  );

  function showWaiting(job) {
    frame.replaceChildren();
    frame.style.borderColor = "#398be8";

    const scanner = h("div", {
      style:
        "position:absolute;left:0;top:50%;width:32%;height:5px;" +
        "border-radius:10px;background:#4a9eff;" +
        "box-shadow:0 0 22px #398be8;" +
        "animation:cinemaPreviewScan 1.8s ease-in-out infinite"
    });

    frame.append(
      h("div", {
        style:
          "display:flex;flex-direction:column;align-items:center;" +
          "justify-content:center;gap:17px;width:100%;height:100%;" +
          "min-height:260px;padding:20px;box-sizing:border-box"
      },
        h("div", {
          style:"font-size:52px;animation:cinemaPreviewPulse 1.5s infinite"
        }, "🎥"),
        h("strong", {
          style:"font-size:18px;text-align:center"
        }, "النموذج يولّد الفيديو"),
        h("span", {
          style:"font-size:13px;color:#aaa;text-align:center"
        }, job.message || "يرجى الانتظار حتى اكتمال التوليد")
      ),
      scanner
    );
  }

  function showEmpty() {
    frame.replaceChildren(
      h("div", {
        style:
          "display:flex;flex-direction:column;align-items:center;" +
          "justify-content:center;gap:14px;min-height:260px;text-align:center"
      },
        h("div", {style:"font-size:58px"}, "🎬"),
        h("strong", {style:"font-size:19px"}, "إطار معاينة الفيديو"),
        h("span", {style:"color:#999;font-size:13px"},
          "ابدأ توليد الفيديو من صفحة فيديو AI وسيظهر هنا")
      )
    );
    frame.style.borderColor = "#414158";
  }

  async function refresh() {
    try {
      const jobs = await api("/api/cinema/jobs");
      const ordered = Array.isArray(jobs)
        ? jobs.slice().sort(
            (a,b) => (b.created_at || 0) - (a.created_at || 0)
          )
        : [];

      const current =
        ordered.find(j => activeStates.includes(j.status)) ||
        ordered[0];

      if (!current) {
        showEmpty();
        status.textContent = "لا توجد مهمة توليد حتى الآن.";
        detail.textContent = "";
        return;
      }

      detail.textContent =
        "المهمة: " + (current.job_id || current.id || "—") +
        (current.prompt ? " — " + current.prompt.slice(0,140) : "");

      if (current.status === "done" && current.video_file) {
        frame.replaceChildren(
          h("video", {
            controls:true,
            playsinline:true,
            preload:"metadata",
            src:"/api/cinema/videos/" +
              encodeURIComponent(current.video_file),
            style:
              "display:block;width:100%;height:100%;min-height:260px;" +
              "max-height:75vh;object-fit:contain;background:#000"
          })
        );
        frame.style.borderColor = "#10b981";
        status.textContent = "✓ اكتمل التوليد — الفيديو جاهز للتشغيل.";
        return;
      }

      if (current.status === "failed" || current.status === "error") {
        frame.replaceChildren(
          h("div", {
            style:
              "display:flex;flex-direction:column;align-items:center;" +
              "justify-content:center;gap:14px;min-height:260px;" +
              "padding:20px;text-align:center;color:#ff7777"
          },
            h("div", {style:"font-size:48px"}, "⚠️"),
            h("strong", {}, "فشل توليد الفيديو"),
            h("span", {}, current.message || "راجع سجل المهمة")
          )
        );
        frame.style.borderColor = "#ef4444";
        status.textContent = "انتهت المهمة بخطأ.";
        return;
      }

      showWaiting(current);

      const labels = {
        queued:"المهمة في قائمة الانتظار",
        pushing:"إرسال المهمة إلى Kaggle",
        generating:"النموذج يولّد الفيديو الآن",
        downloading:"اكتمل التوليد، جارٍ نقل الفيديو إلى الموقع"
      };

      status.textContent =
        labels[current.status] || current.message ||
        "المهمة قيد التنفيذ...";
    } catch (err) {
      status.textContent = "تعذّر تحديث حالة التوليد: " + err.message;
    }
  }

  let timer = null;
  await refresh();

  timer = setInterval(() => {
    if (!root.isConnected) {
      clearInterval(timer);
      timer = null;
      return;
    }
    refresh();
  }, 4000);

  return root;
}

'''

# Create backups only after every source anchor has been validated.
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
app_backup = app.with_name(app.name + ".backup." + stamp)
html_backup = index.with_name(index.name + ".backup." + stamp)
shutil.copy2(app, app_backup)
shutil.copy2(index, html_backup)

for old, new in patches:
    src = src.replace(old, new)

src = src.replace(marker, page + marker, 1)
html = html.replace(
    old_version,
    'app.js?v=cinema-independent-preview-20261103',
    1
)

app.write_text(src, encoding="utf-8")
index.write_text(html, encoding="utf-8")

print("SUCCESS: Independent preview page added.")
print("App backup:", app_backup)
print("HTML backup:", html_backup)
