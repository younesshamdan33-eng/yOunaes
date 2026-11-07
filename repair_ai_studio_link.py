from pathlib import Path
from datetime import datetime
import re
import shutil
import sys

ROOT = Path.cwd()
APP = ROOT / "studio/static/app.js"
PRODUCE = ROOT / "studio/static/produce.js"

for p in (APP, PRODUCE):
    if not p.is_file():
        sys.exit(f"ERROR: missing file: {p}")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

def replace_once(text, pattern, replacement, label, flags=0):
    updated, count = re.subn(pattern, lambda _: replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    return updated

app_text = APP.read_text(encoding="utf-8")
produce_text = PRODUCE.read_text(encoding="utf-8")

# Replace the complete AI Studio view, preserving the rest of app.js.
new_ai_studio = r'''async function aiStudio() {
  const prompt = h("textarea", {
    rows: "4",
    maxlength: "500",
    placeholder: "Describe your cinematic scene...",
    "aria-label": "وصف المشهد"
  });
  prompt.style.cssText =
    "width:100%;box-sizing:border-box;background:#0a0a0f;color:#e0e0e0;" +
    "border:1px solid #2a2a3e;padding:12px;border-radius:8px;" +
    "font-family:inherit;min-height:100px;resize:vertical";

  const styleSel = select("ai_style", [
    ["dramatic","درامي"],["natural","طبيعي"],["warm","دافئ"],
    ["cold","بارد"],["sci_fi","خيال علمي"],["epic","ملحمي"],
    ["documentary","وثائقي"]
  ], "dramatic");

  const lightSel = select("ai_light", [
    ["dramatic","درامية"],["natural","طبيعية"],["night","ليلية"],
    ["volumetric","حجمية"],["studio","استوديو"],["backlight","إضاءة خلفية"]
  ], "dramatic");

  const camSel = select("ai_cam", [
    ["dolly_in","اقتراب"],["static","ثابتة"],["tracking","تتبع"],
    ["orbit","دائرية"],["pan","تحريك جانبي"],["handheld","محمولة"]
  ], "dolly_in");

  const jobsBox = h("div", {
    style: "margin-top:24px",
    "aria-live": "polite"
  });

  let polling = null;
  let submitting = false;
  let refreshBusy = false;

  const activeStatuses = ["queued","pushing","generating","downloading"];

  const stopPoll = () => {
    if (polling) {
      clearInterval(polling);
      polling = null;
    }
  };

  const startPoll = () => {
    if (!polling) polling = setInterval(refresh, 4000);
  };

  async function refresh() {
    if (refreshBusy) return;
    refreshBusy = true;

    try {
      const jobs = await api("/api/cinema/jobs");
      const ordered = Array.isArray(jobs)
        ? jobs.slice().sort((a,b) => (b.created_at || 0) - (a.created_at || 0))
        : [];

      jobsBox.replaceChildren();

      if (!ordered.length) {
        jobsBox.append(
          h("div", { class: "field" },
            h("label", {}, "المهام"),
            h("p", { class: "muted small" }, "لا توجد مهام حتى الآن. اكتب وصف المشهد واضغط توليد الفيديو.")
          )
        );
        stopPoll();
        return;
      }

      jobsBox.append(
        h("h3", { style: "margin:0 0 14px;color:#e0e0e0" },
          "مهام توليد الفيديو (" + ordered.length + ")")
      );

      const labels = {
        queued: "في الانتظار",
        pushing: "إرسال المهمة إلى Kaggle",
        generating: "توليد الفيديو على Kaggle",
        downloading: "تنزيل الفيديو إلى الموقع",
        done: "اكتمل التوليد",
        failed: "فشل التوليد"
      };

      const colors = {
        queued: "#d1a94b",
        pushing: "#4a9eff",
        generating: "#4a9eff",
        downloading: "#4a9eff",
        done: "#10b981",
        failed: "#ef4444"
      };

      for (const j of ordered) {
        const status = j.status || "unknown";
        const time = j.created_at
          ? new Date(j.created_at * 1000).toLocaleString("ar")
          : "";

        const card = h("article", {
          style:
            "background:#12121a;border:1px solid #29293c;" +
            "border-radius:12px;padding:16px;margin-bottom:14px"
        });

        card.append(
          h("div", {
            style: "display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:10px"
          },
            h("strong", {
              style: "color:" + (colors[status] || "#aaa") + ";font-size:14px"
            }, labels[status] || status),
            h("span", {
              style: "color:#777;font-size:11px"
            }, time)
          ),
          h("p", {
            style: "color:#ddd;font-size:13px;line-height:1.6;white-space:pre-wrap"
          }, j.prompt || ""),
          j.message ? h("p", {
            style: "color:#999;font-size:12px;line-height:1.5"
          }, j.message) : null
        );

        if (j.kaggle_url) {
          card.append(
            h("a", {
              href: j.kaggle_url,
              target: "_blank",
              rel: "noopener noreferrer",
              style: "display:inline-block;color:#4a9eff;font-size:12px;margin:5px 0"
            }, "عرض سجل المهمة على Kaggle")
          );
        }

        if (j.video_file) {
          const videoUrl =
            "/api/cinema/videos/" + encodeURIComponent(j.video_file);

          const video = h("video", {
            controls: true,
            playsinline: true,
            preload: "metadata",
            style:
              "display:block;width:100%;max-height:560px;" +
              "border-radius:9px;margin-top:12px;background:#000",
            src: videoUrl
          });

          video.addEventListener("error", () => {
            const warning = h("p", {
              class: "error small",
              role: "alert"
            }, "تعذر تشغيل الفيديو. تحقق من وجود الملف واستجابة مسار الفيديو.");
            card.append(warning);
          });

          card.append(
            h("h4", {
              style: "color:#10b981;margin:12px 0 6px"
            }, "الفيديو الناتج"),
            video,
            h("div", {
              style: "display:flex;gap:10px;flex-wrap:wrap;margin-top:12px"
            },
              h("a", {
                class: "btn primary",
                href: videoUrl,
                download: j.video_file,
                style: "text-decoration:none"
              }, "تنزيل الفيديو MP4"),
              h("a", {
                class: "btn",
                href: videoUrl,
                target: "_blank",
                rel: "noopener noreferrer",
                style: "text-decoration:none"
              }, "فتح الفيديو منفصلًا")
            )
          );
        }

        if (j.status === "failed") {
          card.append(
            h("p", {
              class: "error small",
              role: "alert"
            }, "لم تكتمل المهمة. راجع رسالة الخطأ وسجل Kaggle إن توفر.")
          );
        }

        jobsBox.append(card);
      }

      const hasActive = ordered.some(j => activeStatuses.includes(j.status));
      if (hasActive) startPoll();
      else stopPoll();

    } catch (e) {
      console.error("AI Studio refresh failed:", e);
      if (!jobsBox.childElementCount) {
        jobsBox.append(
          h("p", { class: "error small", role: "alert" },
            "تعذر تحميل المهام: " + e.message)
        );
      }
    } finally {
      refreshBusy = false;
    }
  }

  const btn = h("button", {
    type: "button",
    class: "btn primary",
    onclick: async () => {
      const pr = prompt.value.trim();

      if (!pr) {
        toast("اكتب وصف المشهد أولاً", true);
        prompt.focus();
        return;
      }

      if (pr.length > 500) {
        toast("الحد الأقصى للوصف هو 500 حرف", true);
        return;
      }

      if (submitting) return;

      submitting = true;
      btn.disabled = true;
      btn.textContent = "⏳ جاري إرسال الطلب...";

      try {
        const data = await api("/api/cinema/generate", {
          method: "POST",
          body: {
            prompt: pr,
            style: styleSel.value,
            lighting: lightSel.value,
            camera: camSel.value
          }
        });

        if (!data || !data.job_id) {
          throw new Error("لم يُرجع الخادم رقم المهمة");
        }

        prompt.value = "";
        toast("تم تسجيل المهمة. ستظهر حالتها هنا.");
        await refresh();
        startPoll();

      } catch (e) {
        toast("تعذر إرسال طلب التوليد: " + e.message, true);
      } finally {
        submitting = false;
        btn.disabled = false;
        btn.textContent = "🎥 توليد الفيديو";
      }
    }
  }, "🎥 توليد الفيديو");

  const form = h("section", {
    style:
      "background:#12121a;border:1px solid #29293c;" +
      "border-radius:12px;padding:18px"
  },
    h("div", { class: "field" },
      h("label", {}, "وصف المشهد (الإنجليزية غالبًا تعطي نتائج أفضل)"),
      prompt
    ),
    h("div", {
      style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-top:14px"
    },
      h("div", {}, h("label", {}, "الأسلوب"), styleSel),
      h("div", {}, h("label", {}, "الإضاءة"), lightSel),
      h("div", {}, h("label", {}, "الكاميرا"), camSel)
    ),
    h("p", {
      class: "muted small",
      style: "margin:12px 0"
    }, "يرسل الطلب إلى محرك الفيديو عبر Kaggle GPU. مدة التنفيذ تعتمد على توفر GPU ووقت تشغيل المهمة."),
    btn
  );

  const root = h("div", { class: "wrap" },
    h("div", {
      style: "display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:18px"
    },
      h("div", {},
        h("h2", {
          style: "margin:0 0 5px;color:#e0e0e0;font-size:21px"
        }, "AI Video Studio"),
        h("p", {
          class: "muted small",
          style: "margin:0"
        }, "إنشاء الفيديو ومتابعة النتيجة داخل الموقع")
      ),
      h("button", {
        type: "button",
        class: "btn",
        onclick: refresh
      }, "تحديث المهام")
    ),
    form,
    jobsBox
  );

  // Initial load; polling starts only if the server reports active jobs.
  await refresh();
  return root;
}
'''

app_new = replace_once(
    app_text,
    r"async function aiStudio\(\) \{[\s\S]*?\n\}\nconst lf =",
    new_ai_studio + "\nconst lf =",
    "AI Studio replacement"
)

# The standalone production page should open directly in AI video mode.
produce_new = replace_once(
    produce_text,
    r'let mode = "film", caps = null, timer = null;',
    'let mode = "short", caps = null, timer = null;',
    "default production mode"
)

# Remove the obsolete screenplay form on this standalone page.
# The main website's #/studio route remains the screenplay/film workspace.
produce_new = replace_once(
    produce_new,
    r"function draw\(\) \{[\s\S]*?\n\}\nfunction show\(out, p\)",
    "function draw() { drawAI(); }\nfunction show(out, p)",
    "standalone draw replacement"
)

# The film tab must lead to the actual main film workspace.
old_tab = 'onclick: () => { mode = k; draw(); }'
if produce_new.count(old_tab) != 1:
    raise RuntimeError(
        "Expected exactly one remaining tab handler in drawAI; found "
        + str(produce_new.count(old_tab))
    )

produce_new = produce_new.replace(
    old_tab,
    'onclick: () => { if (k === "film") { location.href = "/#/studio"; return; } mode = "short"; draw(); }',
    1
)

# Ensure no stale undefined variable remains in the standalone page.
if "promptInput" in produce_new:
    raise RuntimeError("Obsolete promptInput reference remains in produce.js")

# Back up both files before writing either one.
for p in (APP, PRODUCE):
    backup = p.with_name(p.name + ".backup." + stamp)
    shutil.copy2(p, backup)
    print("BACKUP:", backup)

APP.write_text(app_new, encoding="utf-8")
PRODUCE.write_text(produce_new, encoding="utf-8")

print("PATCHED:", APP)
print("PATCHED:", PRODUCE)
print("PATCH COMPLETE")
