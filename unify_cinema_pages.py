from pathlib import Path
from datetime import datetime
import shutil
import sys

app = Path("studio/static/app.js")
html = Path("studio/static/index.html")

if not app.exists() or not html.exists():
    sys.exit("ERROR: project files not found")

s = app.read_text()
h = html.read_text()

old_nav = '["#/ai", "nav_ai", "play"], ["#/preview", "معاينة التوليد", "film"]'
new_nav = '["#/ai", "توليد ومعاينة الفيديو", "play"]'

old_route = 'else if (hash === "#/preview") view = await cinemaPreviewPage();'
new_route = 'else if (hash === "#/preview") view = await aiStudio();'

if s.count(old_nav) != 1:
    sys.exit("STOP: navigation pattern does not match exactly once")

if s.count(old_route) != 1:
    sys.exit("STOP: preview route does not match exactly once")

backup = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(app, str(app) + ".backup." + backup)
shutil.copy2(html, str(html) + ".backup." + backup)

s = s.replace(old_nav, new_nav, 1)
s = s.replace(old_route, new_route, 1)

app.write_text(s)

old_version = "app.js?v=cinema-independent-preview-20261103"
if h.count(old_version) == 1:
    h = h.replace(old_version, "app.js?v=unified-cinema-studio-20261104", 1)
    html.write_text(h)

print("PATCH SUCCESS")
print("Backup:", backup)
