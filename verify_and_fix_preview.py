from pathlib import Path
from datetime import datetime
import re
import shutil
import subprocess
import sys

BASE = Path.cwd()
APP = BASE / "studio/static/app.js"
HTML = BASE / "studio/static/index.html"
CSS = BASE / "studio/static/style.css"

for p in (APP, HTML, CSS):
    if not p.is_file():
        sys.exit(f"ERROR: missing file: {p}")

app = APP.read_text(encoding="utf-8")
html = HTML.read_text(encoding="utf-8")
css = CSS.read_text(encoding="utf-8")

checks = {
    "preview renderer exists": "function renderPreview(jobs)" in app,
    "preview refresh is connected": "renderPreview(ordered);" in app,
    "preview is mounted in page": "    previewBox,\n    jobsBox" in app,
    "preview route exists": 'hash === "#/preview"' in app,
    "route mounts page": "main.replaceChildren(view);" in app,
    "HTML has main container": 'id="main"' in html,
    "element helper exists": "function h(tag, attrs, ...kids)" in app,
}

for name, ok in checks.items():
    print(("OK: " if ok else "FAIL: ") + name)

if not all(checks.values()):
    sys.exit("STOP: structural verification failed. No changes made.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
for p in (APP, HTML, CSS):
    backup = p.with_name(p.name + ".backup.final_" + stamp)
    shutil.copy2(p, backup)
    print("BACKUP:", backup)

# Give the preview container a stable ID.
old = 'const previewBox = h("section", {\n    style:'
new = 'const previewBox = h("section", {\n    id: "cinema-preview-box",\n    style:'

if 'id: "cinema-preview-box"' not in app:
    if app.count(old) != 1:
        sys.exit("STOP: preview container pattern is not unique.")
    app = app.replace(old, new, 1)

# Explicitly force the preview frame to remain visible.
marker = "/* CINEMA PREVIEW VISIBILITY FIX */"
if marker not in css:
    css += """

/* CINEMA PREVIEW VISIBILITY FIX */
#cinema-preview-box {
  display: block !important;
  width: 100% !important;
  min-height: 300px;
  box-sizing: border-box !important;
  visibility: visible !important;
  opacity: 1 !important;
}
#cinema-preview-box > div {
  display: flex !important;
  visibility: visible !important;
  opacity: 1 !important;
  min-height: 260px !important;
  width: 100% !important;
  box-sizing: border-box !important;
}
#cinema-preview-box video {
  display: block !important;
  width: 100% !important;
  min-height: 260px;
  background: #000 !important;
}
"""

# Force the browser to request the latest JavaScript.
matches = re.findall(r'/static/app\.js\?v=[^"]+', html)
if len(matches) != 1:
    sys.exit(f"STOP: expected one app.js script reference, found {len(matches)}.")

html = html.replace(matches[0], "/static/app.js?v=preview-final-" + stamp, 1)

APP.write_text(app, encoding="utf-8")
HTML.write_text(html, encoding="utf-8")
CSS.write_text(css, encoding="utf-8")

print("\nPATCHES APPLIED")
print("Preview ID:", 'cinema-preview-box' in app)
print("Cache version:", "preview-final-" + stamp in html)
print("Visibility CSS:", marker in css)
