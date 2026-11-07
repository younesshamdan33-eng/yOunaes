"use strict";
const $ = (s, r = document) => r.querySelector(s);
let I18N = {}, FALLBACK = {}, META = { langs: [], profiles: [], max_script: 20000 };
let LANG = "ar", DIRTY = false, SEQ = 0, lastHash = location.hash || "#/", guard = false;
const UI_LANGS = { ar: "العربية", en: "English" };
const t = (k) => I18N[k] ?? FALLBACK[k] ?? k;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clampPct = (v) => Math.max(0, Math.min(100, Number(v) || 0));
const ICONS = {
  send: '<path d="M4 12l16-8-6 16-3-7z"/>',
  home: '<path d="M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  save: '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v6h7V3M8 21v-7h8v7"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
  play: '<path d="M6 4l14 8-14 8z"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  download: '<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>',
  redo: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M17 9h4M3 15h4M17 15h4"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
  alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>',
};
function icon(n) {
  const s = document.createElement("span");
  s.className = "ico";
  s.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[n] || "") + "</svg>";
  return s;
}
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null) el.append(c);
  return el;
}
function toast(msg, bad) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = bad ? "show bad" : "show";
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.className = ""), 3500);
}
async function api(path, opts = {}) {
  const o = { headers: {}, ...opts };
  if (o.body !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(o.body); }
  let r;
  try { r = await fetch(path, o); } catch { throw new Error(t("err_network")); }
  let d = null;
  try { d = await r.json(); } catch {}
  if (!r.ok) throw new Error((d && d.error) || String(r.status));
  return d;
}
async function setLang(lang) {
  const d = await api("/api/i18n/" + lang);
  I18N = d.strings; LANG = lang;
  document.documentElement.lang = lang;
  document.documentElement.dir = d.dir;
  try { localStorage.setItem("ui_lang", lang); } catch {}
  for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  $("#ui-lang").value = lang;
  await route();
}
function renderNav() {
  const cur = location.hash || "#/";
  const on = (href) => (href === "#/new" ? cur === "#/new" || cur.startsWith("#/p/") : cur === href);
  const items = [["#/", "nav_dashboard", "home"], ["#/studio", "nav_studio", "sparkle"], ["#/new", "nav_new", "film"], ["#/ai", "nav_ai", "play"], ["#/preview", "معاينة التوليد", "film"], ["#/queue", "nav_queue", "list"]];
  const nav = $("#nav");
  nav.setAttribute("aria-label", t("nav_label"));
  nav.replaceChildren(...items.map(([href, k, ic]) => h("a", { href, "aria-current": on(href) ? "page" : null }, icon(ic), h("span", {}, t(k)))));
}
function hue(s) { let x = 0; for (const c of s || "x") x = (x * 31 + c.codePointAt(0)) % 360; return x; }
function poster(title) {
  const el = h("div", { class: "poster" }, h("span", { class: "mark" }, [...(title || "?")][0]));
  el.style.setProperty("--h", String(hue(title)));
  return el;
}
const fmtDur = (s) => Math.floor(s / 60) + ":" + String(Math.round(s % 60)).padStart(2, "0");
function fmtTime(sec) {
  try { return new Date(sec * 1000).toLocaleString(LANG, { dateStyle: "medium", timeStyle: "short" }); } catch { return ""; }
}
function scenesOf(text) {
  const s = text.trim();
  if (!s) return [];
  let parts = s.split(/\n\s*\n/).map((x) => x.trim()).filter(Boolean);
  if (parts.length === 1) parts = s.split(/(?<=[.!?؟…])\s+/).map((x) => x.trim()).filter(Boolean);
  return parts.map((x) => ({ text: x.replace(/\s+/g, " "), sec: Math.max(2, x.split(/\s+/).length / 2.5) }));
}
const stat = (k, v, extra) => h("div", { class: "stat" }, h("span", { class: "k" }, k), h("b", { class: "v" }, v), extra);
const skeleton = () => h("div", {}, h("div", { class: "skel" }), h("div", { class: "skel" }), h("div", { class: "skel" }));
const STATE_CLS = { queued: "warn", running: "info", completed: "ok", failed: "err", cancelled: "mute", corrupt: "err" };
const badge = (s) => h("span", { class: "pill " + (STATE_CLS[s] || "mute") }, h("i", { class: "dot" }), t("state_" + s));
function meter(pct) {
  const f = h("i");
  if (pct != null) f.style.width = pct + "%";
  return h("div", { class: "meter" + (pct == null ? " ind" : ""), role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": pct == null ? null : String(pct) }, f);
}
function whileMounted(root, fn, ms) {
  const id = setInterval(async () => {
    if (!root.isConnected) return clearInterval(id);
    try { await fn(); } catch {}
  }, ms);
}
async function recentJobs(n = 12) {
  const list = await api("/api/jobs");
  const out = await Promise.all(list.slice(-n).map((j) => api("/api/jobs/" + j.id).catch(() => null)));
  return out.filter(Boolean);
}
function jobRow(j, titles) {
  const pid = j.params && j.params.project_id;
  const name = titles.get(pid);
  const active = j.state === "running" || j.state === "queued";
  const pct = clampPct(j.progress);
  return h("li", { class: "jrow" },
    h("div", { class: "jmain" },
      name ? h("a", { href: "#/p/" + pid, dir: "auto", class: "jname" }, name) : h("span", { class: "jname muted" }, t("q_unknown")),
      h("span", { class: "muted small" }, fmtTime(j.created))),
    h("div", { class: "jside" }, badge(j.state), active ? h("span", { class: "small muted" }, pct + "%") : null),
    active ? meter(j.state === "running" && pct > 0 ? pct : null) : null);
}
function card(p, job) {
  const date = new Date(p.updated * 1000).toLocaleDateString(LANG);
  return h("a", { class: "pcard", href: "#/p/" + p.id }, poster(p.title),
    h("div", { class: "pbody" }, h("h3", { dir: "auto" }, p.title || "…"),
      h("div", { class: "pmeta" }, h("span", { class: "muted small" }, t("lang_" + p.script_lang) + " · " + date), job ? badge(job.state) : null)));
}
async function dashboard() {
  const [projects, jobs, sys] = await Promise.all([api("/api/projects"), recentJobs(20).catch(() => []), api("/api/system")]);
  projects.sort((a, b) => (b.updated || 0) - (a.updated || 0));
  const titles = new Map(projects.map((p) => [p.id, p.title]));
  const latest = new Map();
  for (const j of jobs) { const k = j.params && j.params.project_id; if (k) latest.set(k, j); }
  const low = sys.free_mb - sys.min_free_mb < 500;
  const fill = h("i");
  fill.style.width = Math.min(100, Math.round((1 - sys.free_mb / sys.total_mb) * 100)) + "%";
  const grid = h("div", { class: "grid" });
  const search = h("input", { type: "search", class: "search", placeholder: t("dash_search"), "aria-label": t("dash_search"), autocomplete: "off" });
  const paint = () => {
    const q = search.value.trim().toLowerCase();
    const list = projects.filter((p) => !q || (p.title || "").toLowerCase().includes(q));
    grid.replaceChildren(...(list.length ? list.map((p) => card(p, latest.get(p.id)))
      : [projects.length ? h("p", { class: "empty" }, t("dash_none_found"))
        : h("div", { class: "empty empty-box" }, h("span", {}, t("dash_empty")), h("a", { class: "btn primary", href: "#/new" }, icon("plus"), t("dash_new")))]));
  };
  search.addEventListener("input", paint); paint();
  const recent = jobs.slice().reverse().slice(0, 5);
  return h("div", {},
    h("section", { class: "hero" }, h("h1", {}, t("hero_title")), h("p", { class: "muted" }, t("hero_sub")),
      h("a", { class: "btn primary", href: "#/new" }, icon("plus"), t("dash_new"))),
    h("div", { class: "stats" }, stat(t("stat_projects"), String(sys.projects)), stat(t("stat_jobs"), String(sys.jobs_active)),
      stat(t("stat_storage"), (sys.free_mb / 1024).toFixed(1) + " " + t("storage_free"), h("div", { class: "meter" + (low ? " low" : "") }, fill))),
    low ? h("p", { class: "error small", role: "alert" }, t("storage_low")) : null,
    h("div", { class: "sec-h" }, h("h2", {}, t("dash_title")), search),
    grid,
    h("div", { class: "sec-h" }, h("h2", {}, t("queue_title")), h("a", { class: "link", href: "#/queue" }, t("q_all"))),
    recent.length ? h("ul", { class: "jobs" }, recent.map((j) => jobRow(j, titles))) : h("p", { class: "empty" }, t("queue_empty")));
}
async function queuePage() {
  const root = h("div", {});
  const list = h("ul", { class: "jobs" });
  async function load() {
    const [projects, jobs] = await Promise.all([api("/api/projects"), recentJobs(30)]);
    const titles = new Map(projects.map((p) => [p.id, p.title]));
    const rows = jobs.slice().reverse();
    list.replaceChildren(...(rows.length ? rows.map((j) => jobRow(j, titles)) : [h("li", { class: "empty" }, t("queue_empty"))]));
  }
  root.append(h("div", { class: "head" }, h("h1", {}, t("queue_title"))), list);
  await load();
  whileMounted(root, load, 3000);
  return root;
}
function select(id, options, value) {
  const s = h("select", { id, name: id }, options.map(([v, l]) => h("option", { value: v }, l)));
  s.value = value;
  return s;
}
const field = (id, label, ...c) => h("div", { class: "field" }, h("label", { for: id }, label), ...c);
const PANES = [["story", "step_story", "layers"], ["monitor", "pane_monitor", "film"], ["settings", "pane_settings", "sliders"]];

function workspace(p, jobs) {
  let pid = p ? p.id : null, busy = false, job = null, sel = 0;
  const d = p || { title: "", script: "", script_lang: "ar", subtitle_lang: "none", voice: "", profile: "480p" };
  const langs = META.langs.map((c) => [c, t("lang_" + c)]);
  const subOpts = (l) => [["none", t("subtitle_none")], [l, t("lang_" + l)]];
  const title = h("input", { id: "title", name: "title", maxlength: "100", value: d.title, autocomplete: "off", dir: "auto" });
  const script = h("textarea", { id: "script", rows: "10", maxlength: String(META.max_script), dir: "auto" }, d.script);
  const scriptLang = select("script_lang", langs, d.script_lang);
  const subLang = select("subtitle_lang", subOpts(d.script_lang), d.subtitle_lang === d.script_lang ? d.script_lang : "none");
  const profile = select("profile", META.profiles.map((x) => [x, t("profile_" + x)]), d.profile);
  const voice = select("voice", [["", t("voice_auto")], ...(d.voice ? [[d.voice, d.voice]] : [])], d.voice);
  const voiceNote = h("span", { class: "muted small" });
  const loadBtn = h("button", { type: "button", class: "btn sm", onclick: () => loadVoices(false) }, icon("mic"), t("voices_load"));
  const stats = h("p", { class: "muted small" });
  const strip = h("div", { class: "strip" });
  const sceneList = h("ol", { class: "scenelist" });
  const sceneHead = h("div", { class: "sc-head" });
  const monitor = h("div", { class: "monitor" });
  const readout = h("div", { class: "readout" });
  const rbox = h("div", { class: "rbox" });
  const heading = h("h1", { dir: "auto" });
  const status = h("span", { class: "pill" });
  const saveBtn = h("button", { type: "button", class: "btn", onclick: save }, icon("save"), t("save"));
  const renderBtn = h("button", { type: "button", class: "btn primary", onclick: startRender }, icon("play"), t("render_btn"));
  const delBtn = h("button", { type: "button", class: "btn danger", onclick: del }, icon("trash"), t("delete"));
  const ptabs = h("div", { class: "ptabs", role: "tablist" }, PANES.map(([id, k, ic]) =>
    h("button", { type: "button", role: "tab", "data-id": id, onclick: () => setPane(id) }, icon(ic), t(k))));
  const root = h("div", { class: "ws", "data-pane": "story" });
  const active = () => job && (job.state === "queued" || job.state === "running");

  function setPane(n) {
    root.dataset.pane = n;
    for (const b of ptabs.children) b.setAttribute("aria-selected", String(b.dataset.id === n));
  }
  function markDirty() { DIRTY = true; paintBar(); }
  function paintBar() {
    heading.textContent = title.value.trim() || (pid ? t("edit_title") : t("new_title"));
    status.textContent = DIRTY ? t("st_unsaved") : pid ? t("saved") : t("st_new");
    status.className = "pill " + (DIRTY ? "warn" : pid ? "ok" : "mute");
    delBtn.hidden = !pid;
  }
  function pick(i) { sel = i; paintScenes(); }
  function paintScenes() {
    const txt = script.value.trim();
    stats.textContent = (txt ? txt.split(/\s+/).length : 0) + " " + t("words") + " · " + script.value.length + " " + t("chars");
    const sc = scenesOf(script.value);
    if (sel >= sc.length) sel = Math.max(0, sc.length - 1);
    const total = sc.reduce((a, x) => a + x.sec, 0);
    sceneHead.replaceChildren(h("b", {}, t("timeline_title")), h("span", { class: "muted small" }, sc.length + " " + t("scene") + " · " + t("est_total") + " " + fmtDur(total)));
    strip.replaceChildren(...sc.map((x, i) => {
      const b = h("button", { type: "button", class: "seg" + (i === sel ? " on" : ""), "aria-label": t("scene") + " " + (i + 1), onclick: () => pick(i) });
      b.style.flexGrow = String(x.sec);
      return b;
    }));
    sceneList.replaceChildren(...(sc.length ? sc.map((x, i) => h("li", {},
      h("button", { type: "button", class: "scn" + (i === sel ? " on" : ""), onclick: () => pick(i) },
        h("span", { class: "n" }, String(i + 1)), h("span", { class: "tx", dir: "auto" }, x.text), h("span", { class: "d" }, fmtDur(x.sec)))))
      : [h("li", { class: "empty" }, t("timeline_empty"))]));
    paintMonitor();
  }
  function emptyMon(icn, text, hint, cap) {
    return h("div", { class: "empty-mon" }, icon(icn), h("b", {}, text), hint ? h("span", {}, hint) : null, cap ? h("em", { class: "cap", dir: "auto" }, cap) : null);
  }
  function paintMonitor() {
    const sc = scenesOf(script.value);
    readout.replaceChildren(h("span", {}, "16:9"), h("span", {}, t("profile_" + profile.value)), h("span", {}, t("est_total") + " " + fmtDur(sc.reduce((a, x) => a + x.sec, 0))));
    if (job && job.state === "completed") {
      if (monitor.dataset.err === job.id) { monitor.replaceChildren(emptyMon("alert", t("mon_video_err"))); return; }
      if (monitor.dataset.vid === job.id) return;
      monitor.dataset.vid = job.id;
      const id = job.id;
      monitor.replaceChildren(h("video", { controls: true, playsinline: true, preload: "metadata", src: "/api/jobs/" + id + "/output",
        onerror: () => { monitor.dataset.err = id; delete monitor.dataset.vid; monitor.replaceChildren(emptyMon("alert", t("mon_video_err"))); } }));
      return;
    }
    delete monitor.dataset.vid;
    monitor.style.setProperty("--h", String(hue(title.value)));
    monitor.replaceChildren(emptyMon("film", t("mon_empty_title"), t("mon_empty_hint"), sc.length ? sc[Math.min(sel, sc.length - 1)].text : null));
  }
  function paintRender(net) {
    renderBtn.disabled = busy || !!active();
    const kids = [];
    if (!job && !busy) kids.push(h("p", { class: "muted small" }, t("render_hint")));
    if (!job && busy) kids.push(h("div", { class: "rhead" }, h("span", { class: "muted small" }, t("render_preparing"))), meter(null));
    if (job) {
      const st = job.state, pct = clampPct(job.progress);
      const label = { queued: t("render_queued"), running: t("render_running") + (pct ? " · " + pct + "%" : ""), completed: t("render_done"), failed: t("render_failed"), cancelled: t("render_cancelled") }[st] || st;
      kids.push(h("div", { class: "rhead" }, badge(st), h("span", { class: "muted small" }, label)));
      if (st === "queued" || st === "running") kids.push(meter(st === "running" && pct > 0 ? pct : null));
      if (st === "failed") kids.push(h("p", { class: "error", role: "alert", dir: "auto" }, job.error || t("render_failed")));
      const acts = [];
      if (active()) acts.push(h("button", { type: "button", class: "btn danger sm", onclick: cancelJob }, icon("stop"), t("render_cancel")));
      if (st === "failed" || st === "cancelled") acts.push(h("button", { type: "button", class: "btn sm", onclick: startRender, disabled: busy }, icon("redo"), t("render_retry")));
      if (st === "completed") acts.push(h("a", { class: "btn primary sm", href: "/api/jobs/" + job.id + "/output", download: "film.mp4" }, icon("download"), t("render_download")));
      if (acts.length) kids.push(h("div", { class: "acts" }, acts));
    }
    if (net) kids.push(h("p", { class: "warn small", role: "status" }, t("render_net")));
    rbox.replaceChildren(...kids);
  }
  async function loadVoices(silent) {
    loadBtn.disabled = true;
    voiceNote.textContent = t("voices_loading");
    try {
      const list = await api("/api/voices?lang=" + encodeURIComponent(scriptLang.value));
      const keep = voice.value;
      voice.replaceChildren(h("option", { value: "" }, t("voice_auto")), ...list.map((v) => h("option", { value: v.name }, v.name + " (" + v.gender + ")")));
      voice.value = list.some((v) => v.name === keep) ? keep : "";
      if (silent && !voice.value && list.length) { voice.value = list[0].name; if (pid) markDirty(); }
      voiceNote.textContent = list.length + " · " + t("voices_loaded");
    } catch (e) {
      voiceNote.textContent = t("voices_fail");
      if (!silent) toast(e.message, true);
    }
    loadBtn.disabled = false;
  }
  async function persist() {
    const body = { title: title.value, script: script.value, script_lang: scriptLang.value, subtitle_lang: subLang.value, voice: voice.value, profile: profile.value };
    const r = pid ? await api("/api/projects/" + encodeURIComponent(pid), { method: "PUT", body }) : await api("/api/projects", { method: "POST", body });
    if (!pid) { pid = r.id; lastHash = "#/p/" + pid; history.replaceState(null, "", lastHash); renderNav(); }
    DIRTY = false; paintBar();
    return r;
  }
  async function save() {
    if (!title.value.trim()) { setPane("story"); title.focus(); toast(t("err_title"), true); return; }
    saveBtn.disabled = true;
    try { await persist(); toast(t("saved")); } catch (e) { toast(e.message, true); }
    saveBtn.disabled = false;
  }
  async function del() {
    if (!pid || !confirm(t("confirm_delete"))) return;
    try { await api("/api/projects/" + encodeURIComponent(pid), { method: "DELETE" }); DIRTY = false; toast(t("deleted")); location.hash = "#/"; }
    catch (e) { toast(e.message, true); }
  }
  function precheck() {
    if (!title.value.trim()) return { pane: "story", el: title, msg: t("err_title") };
    if (!script.value.trim()) return { pane: "story", el: script, msg: t("err_script") };
    if (!voice.value) return { pane: "settings", el: voice, msg: t("err_voice") };
    return null;
  }
  async function startRender() {
    if (busy || active()) return;
    const bad = precheck();
    if (bad) { setPane(bad.pane); bad.el.focus(); toast(bad.msg, true); return; }
    busy = true; job = null; setPane("monitor"); paintRender(); paintMonitor();
    try {
      await persist();
      let j;
      try { j = await api("/api/projects/" + encodeURIComponent(pid) + "/render", { method: "POST", body: {} }); }
      catch (e) {
        if (e.message !== "render already active") throw e;
        j = (await recentJobs(10)).reverse().find((x) => x.params && x.params.project_id === pid && (x.state === "queued" || x.state === "running"));
        if (!j) throw e;
      }
      await track(j);
    } catch (e) {
      job = null; busy = false; paintRender(); paintMonitor();
      toast(e.message, true);
      rbox.append(h("p", { class: "error small", role: "alert", dir: "auto" }, e.message));
    }
  }
  async function track(j0) {
    job = j0; busy = true; paintRender(); paintMonitor();
    let fails = 0;
    while (root.isConnected) {
      await sleep(1200);
      if (!root.isConnected) break;
      try { job = await api("/api/jobs/" + job.id); fails = 0; }
      catch { fails++; paintRender(true); if (fails >= 12) break; continue; }
      paintRender();
      if (!active()) break;
    }
    busy = false;
    paintRender(); paintMonitor();
    if (fails >= 12) rbox.append(h("p", { class: "error small", role: "alert" }, t("render_lost")));
    else if (job && job.state === "completed") toast(t("render_done"));
  }
  async function cancelJob() {
    if (!job) return;
    try { job = await api("/api/jobs/" + job.id + "/cancel", { method: "POST", body: {} }); paintRender(); }
    catch (e) { toast(e.message, true); }
  }

  [title, script].forEach((e) => e.addEventListener("input", () => { markDirty(); paintScenes(); }));
  scriptLang.addEventListener("change", () => {
    const keepSub = subLang.value !== "none";
    subLang.replaceChildren(...subOpts(scriptLang.value).map(([v, l]) => h("option", { value: v }, l)));
    subLang.value = keepSub ? scriptLang.value : "none";
    voice.replaceChildren(h("option", { value: "" }, t("voice_auto")));
    markDirty(); loadVoices(true);
  });
  [subLang, voice].forEach((e) => e.addEventListener("change", markDirty));
  profile.addEventListener("change", () => { markDirty(); paintMonitor(); });

  const paneStory = h("section", { class: "pane pane-story" },
    h("div", { class: "panel" }, field("title", t("lbl_title"), title), field("script", t("lbl_script"), script, stats)),
    h("div", { class: "panel" }, sceneHead, strip, sceneList));
  const paneMon = h("section", { class: "pane pane-monitor" }, monitor, readout, h("div", { class: "panel" }, rbox));
  const paneSet = h("section", { class: "pane pane-settings" },
    h("div", { class: "panel" },
      field("script_lang", t("lbl_script_lang"), scriptLang),
      field("voice", t("lbl_voice"), voice, h("div", { class: "vrow" }, loadBtn, voiceNote)),
      field("subtitle_lang", t("lbl_subtitle_lang"), subLang),
      field("profile", t("lbl_profile"), profile)),
    h("p", { class: "muted small" }, t("lang_note")));
  root.append(
    h("div", { class: "wsbar" }, h("div", { class: "wtitle" }, heading, status), h("div", { class: "wact" }, saveBtn, renderBtn, delBtn)),
    ptabs, h("div", { class: "wsgrid" }, paneStory, paneMon, paneSet));

  const mine = (jobs || []).filter((x) => x.params && x.params.project_id === pid);
  if (mine.length) job = mine[mine.length - 1];
  setPane("story"); paintBar(); paintScenes(); paintRender();
  if (active()) track(job);
  loadVoices(true);
  return root;
}
async function aiStudio() {
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

  const previewBox = h("section", {
    id: "cinema-preview-box",
    style:
      "width:100%;box-sizing:border-box;margin-top:22px;padding:16px;" +
      "background:#12121a;border:1px solid #34344a;border-radius:16px;" +
      "overflow:hidden",
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
            "width:100%;min-height:260px;aspect-ratio:16/9;" +
            "box-sizing:border-box;background:#050509;" +
            "border:2px solid #4a9eff;border-radius:12px;" +
            "overflow:hidden;" +
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
            "display:block;width:100%;min-height:260px;" +
            "max-height:620px;aspect-ratio:16/9;" +
            "object-fit:contain;background:#000;" +
            "border:2px solid #4a9eff;border-radius:12px"
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
            "width:100%;min-height:240px;aspect-ratio:16/9;background:#08080d;border:2px solid #4a9eff;border-radius:12px;box-sizing:border-box;" +
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
          "width:100%;min-height:240px;aspect-ratio:16/9;background:#08080d;border:2px solid #4a9eff;border-radius:12px;box-sizing:border-box;" +
          "display:flex;align-items:center;justify-content:center;" +
          "flex-direction:column;gap:18px;padding:20px;box-sizing:border-box"
      },
        h("div", {
          style:
            "width:54px;height:54px;flex:0 0 54px;" +
            "box-sizing:border-box;border:5px solid #29293c;" +
            "border-top-color:#4a9eff;border-right-color:#4a9eff;" +
            "border-radius:50%;animation:cinemaSpin .8s linear infinite"
        }),
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
        }, "المهمة قيد التنفيذ. سيظهر الفيديو الحقيقي هنا بعد اكتمال التوليد.")
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

      renderPreview(ordered);
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
    previewBox,
    jobsBox
  );

  // Initial load; polling starts only if the server reports active jobs.
  await refresh();
  return root;
}

const lf = (label, el) => h("label", { class: "lf" }, h("span", { class: "muted small" }, label), el);
const kv = (k, v) => h("div", { class: "kv" }, h("span", { class: "muted small" }, k), h("b", {}, v));
const fmtLong = (sec) => { const m = Math.floor(sec / 60); return m >= 60 ? Math.floor(m / 60) + "h " + (m % 60) + "m" : m + "m " + Math.round(sec % 60) + "s"; };
const FS_CLS = { draft: "mute", running: "info", waiting_budget: "warn", interrupted: "warn", cancelled: "mute", failed: "err", generated: "ok", assembled: "ok" };
const SS_CLS = { pending: "mute", retrying: "warn", running: "info", completed: "ok", failed: "err" };
const fbadge = (s) => h("span", { class: "pill " + (FS_CLS[s] || "mute") }, h("i", { class: "dot" }), t("fs_" + s));
const sbadge = (s) => h("span", { class: "pill " + (SS_CLS[s] || "mute") }, h("i", { class: "dot" }), t("ss_" + s));
function sel(label, options, value) {
  const s = h("select", { "aria-label": label }, options.map(([v, l, dis]) => h("option", { value: v, disabled: !!dis }, l)));
  s.value = value;
  return s;
}
const safe = (fn) => async () => { try { await fn(); } catch (e) { toast(e.message, true); } };

async function studio() {
  const [prov, list0] = await Promise.all([api("/api/providers"), api("/api/films").catch(() => [])]);
  const mh = { name: "kaggle", label: "Kaggle (Wan 2.2)", free: true };
  if (!mh) throw new Error("no providers available");
  const pdef = (n) => prov.find((p) => p.name === n);
  const lsGet = () => { try { return localStorage.getItem("studio_film"); } catch { return null; } };
  const lsSet = (v) => { try { localStorage.setItem("studio_film", v); } catch {} };
  const put = (el, kids) => el.replaceChildren(...kids.flat().filter((x) => x != null && x !== false));
  const kv2 = (k, v) => h("div", { class: "kv" }, h("span", { class: "muted small" }, k), h("b", { dir: "auto" }, v));
  const narrow = () => window.matchMedia("(max-width: 1099px)").matches;
  const clipUrl = (fid, sid) => "/api/films/" + encodeURIComponent(fid) + "/shots/" + encodeURIComponent(sid) + "/clip";
  const allShots = (f) => f.scenes.flatMap((sc) => sc.shots);
  const sceneState = (shots) => {
    if (!shots.length) return "pending";
    if (shots.every((s) => s.state === "completed")) return "completed";
    if (shots.some((s) => s.state === "failed")) return "failed";
    if (shots.some((s) => s.state === "running")) return "running";
    if (shots.some((s) => s.state === "retrying")) return "retrying";
    return "pending";
  };
  const root = h("div", { class: "wx", "data-pane": "chat" });
  const rail = h("div", { class: "rail", role: "list", "aria-label": t("st_films") });
  const thread = h("div", { class: "thread" });
  const quick = h("div", { class: "quick" });
  const input = h("textarea", { class: "composer-in", rows: "1", maxlength: "4000", dir: "auto", placeholder: t("st_ph"), "aria-label": t("st_ph"), enterkeyhint: "send" });
  const titleEl = h("h1", { dir: "auto" }), statusEl = h("span", {});
  const scenesBox = h("div", { class: "wx-scroll" }), viewBox = h("div", { class: "wx-body" });
  const cards = new Map(), last = new Map();
  let current = null, film = null, selSid = null, rtab = "preview", showFinal = false, sbMore = false, ss = "", vs = "";
  const grow = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; };
  const curShot = () => (film && allShots(film).find((s) => s.id === selSid)) || null;
  const curScene = () => (film && film.scenes.find((sc) => sc.shots.some((s) => s.id === selSid))) || null;

  const seg = h("div", { class: "wx-seg wx-panes", role: "tablist" }, [["chat", "wx_chat", "sparkle"], ["scenes", "wx_scenes", "layers"], ["view", "wx_preview", "film"]]
    .map(([id, k, ic]) => h("button", { type: "button", role: "tab", "data-id": id, onclick: () => setPane(id) }, icon(ic), t(k))));
  function setPane(n) {
    root.dataset.pane = n;
    for (const b of seg.children) b.setAttribute("aria-selected", String(b.dataset.id === n));
  }
  const rtabs = h("div", { class: "wx-seg", role: "tablist" }, [["preview", "wx_preview"], ["board", "wx_storyboard"], ["details", "wx_details"]]
    .map(([id, k]) => h("button", { type: "button", role: "tab", "data-id": id, onclick: () => { rtab = id; paintView(); } }, t(k))));

  function say(who, ...kids) {
    const bub = h("div", { class: "bub", dir: "auto" }, ...kids);
    const el = h("div", { class: "msg " + who }, who === "bot" ? h("span", { class: "av", "aria-hidden": "true" }, icon("sparkle")) : null, bub);
    thread.append(el);
    el.scrollIntoView({ block: "end", behavior: "smooth" });
    return el;
  }
  const warn = (e) => say("bot", h("span", { class: "error", role: "alert", dir: "auto" }, e.message));

  async function refreshRail() {
    let l = [];
    try { l = await api("/api/films"); } catch {}
    l.sort((a, b) => (b.updated || 0) - (a.updated || 0));
    put(rail, l.length ? l.slice(0, 12).map((f) => h("button", { type: "button", role: "listitem", class: "chip" + (f.id === current ? " on" : ""), onclick: () => attach(f.id) }, h("span", { dir: "auto" }, f.title), fbadge(f.state)))
      : [h("span", { class: "muted small" }, t("st_no_films"))]);
  }
  function paintQuick() {
    put(quick, current ? [["resume", "st_q_resume"], ["retry", "st_q_retry"], ["export", "st_q_export"], ["cancel", "st_q_cancel"]]
      .map(([k, l]) => h("button", { type: "button", class: "chip sm", onclick: () => runIntent(k) }, t(l))) : []);
  }

  /* ---------- top bar + scenes pane ---------- */
  function paintTop() {
    titleEl.textContent = film ? film.title : t("wx_new_film");
    put(statusEl, film ? [fbadge(film.state)] : []);
  }
  function pickShot(id) {
    selSid = id; showFinal = false; rtab = "preview";
    paintScenes(); paintView();
    if (narrow()) setPane("view");
  }
  function paintScenes() {
    if (!film) { ss = ""; put(scenesBox, [h("p", { class: "empty" }, t("wx_no_film"))]); return; }
    const s2 = JSON.stringify([film.id, selSid, film.scenes.map((sc) => sc.shots.map((s) => s.state))]);
    if (s2 === ss) return;
    ss = s2;
    const done = film.scenes.filter((sc) => sc.shots.length && sc.shots.every((s) => s.state === "completed")).length;
    const cs = curScene();
    put(scenesBox, [
      h("div", { class: "wx-ph" }, h("b", {}, t("wx_scenes")), h("span", { class: "muted small" }, done + " / " + film.scenes.length)),
      meter(100 * done / film.scenes.length),
      h("div", { class: "srows" }, film.scenes.map((sc, i) => {
        const sh = sc.shots, d = sh.filter((s) => s.state === "completed").length, dur = sh.reduce((a, s) => a + s.seconds, 0);
        return h("button", { type: "button", class: "srow" + (cs && cs.id === sc.id ? " on" : ""), onclick: () => pickShot((sh.find((s) => s.state === "completed") || sh[0]).id) },
          h("span", { class: "n" }, String(i + 1)),
          h("span", { class: "sm" }, h("span", { class: "tx", dir: "auto" }, sc.title), h("span", { class: "muted small" }, d + "/" + sh.length + " \u00b7 " + fmtLong(dur))),
          sbadge(sceneState(sh)));
      }))]);
  }

  /* ---------- right pane: preview / storyboard / details ---------- */
  async function retryShot(s, ack) {
    const paid = !(pdef(film.provider) || {}).free;
    if (!ack && paid && !confirm(t("st_retry_confirm"))) return;
    try {
      await api("/api/films/" + encodeURIComponent(film.id) + "/shots/" + encodeURIComponent(s.id) + "/retry", { method: "POST", body: { confirm_cost: true, acknowledge_possible_charge: !!ack } });
      toast(t("st_done"));
    } catch (e) {
      if (!ack && /acknowledge_possible_charge/.test(e.message) && confirm(t("st_ack_charge"))) return retryShot(s, true);
      throw e;
    }
  }
  function emptyMon(text, hint, cap) {
    return h("div", { class: "empty-mon" }, icon("film"), h("b", {}, text), hint ? h("span", {}, hint) : null, cap ? h("em", { class: "cap", dir: "auto" }, cap) : null);
  }
  function paintPreview() {
    const kids = [], sh = curShot(), sc = curScene();
    const final = film && film.state === "assembled" && film.output;
    if (final) kids.push(h("div", { class: "wx-seg sm" }, [["shot", "wx_shot"], ["final", "wx_final"]]
      .map(([id, k]) => h("button", { type: "button", role: "tab", "aria-selected": String((id === "final") === showFinal), onclick: () => { showFinal = id === "final"; vs = ""; paintView(); } }, t(k)))));
    const mon = h("div", { class: "monitor" });
    let src = null;
    if (final && showFinal) src = "/api/films/" + encodeURIComponent(film.id) + "/output";
    else if (film && sh && sh.state === "completed") src = clipUrl(film.id, sh.id);
    if (src) {
      const v = h("video", { controls: true, playsinline: true, preload: "metadata", src });
      v.addEventListener("error", () => mon.replaceChildren(emptyMon(t("mon_video_err"))));
      mon.append(v);
    } else mon.append(emptyMon(film ? t("mon_empty_title") : t("wx_no_film"), film ? t(sh ? "wx_not_ready" : "wx_pick") : "", sh && sh.caption ? sh.caption : ""));
    kids.push(mon);
    if (film && sh && sc) {
      const p = pdef(film.provider) || {}, c = film.continuity || {};
      const rows = [[t("wx_scene"), sc.title], [t("wx_shot"), sh.id + " \u00b7 " + sh.seconds + "s"], [t("wx_text"), sh.caption || sc.text],
        [t("st_method"), (p.label || film.provider) + " \u00b7 " + film.model], [t("st_res"), film.resolution + " \u00b7 " + film.aspect_ratio],
        [t("wx_chars"), (c.characters || []).join(", ") || "\u2014"], [t("st_loc"), c.location || "\u2014"], [t("st_style"), c.style || "\u2014"],
        [t("st_credits_spent"), sh.credits == null ? "\u2014" : String(sh.credits)]];
      kids.push(h("div", { class: "panel" },
        h("div", { class: "fhead" }, h("b", {}, t("wx_info")), sbadge(sh.state)),
        h("div", { class: "plansum" }, rows.map(([k, v]) => kv2(k, v))),
        sh.error ? h("p", { class: "error small", role: "alert", dir: "auto" }, sh.error) : null,
        sh.state === "failed" ? h("div", { class: "acts" }, h("button", { type: "button", class: "btn sm primary", onclick: safe(() => retryShot(sh)) }, icon("redo"), t("st_retry"))) : null));
    }
    return kids;
  }
  function paintBoard() {
    if (!film) return [h("p", { class: "empty" }, t("wx_no_film"))];
    const shots = allShots(film), lim = sbMore ? shots.length : 36;
    let thumbs = 0;
    const tiles = shots.slice(0, lim).map((s) => {
      let th;
      if (s.state === "completed" && thumbs < 12) { thumbs++; th = h("video", { class: "sb-v", muted: true, playsinline: true, preload: "metadata", tabindex: "-1", "aria-hidden": "true", src: clipUrl(film.id, s.id) + "#t=0.2" }); }
      else th = h("div", { class: "sb-v sb-e" }, h("span", {}, s.id));
      return h("button", { type: "button", class: "sb-t" + (s.id === selSid ? " on" : ""), onclick: () => pickShot(s.id) }, th, h("div", { class: "sb-m" }, h("span", {}, s.id + " \u00b7 " + s.seconds + "s"), sbadge(s.state)));
    });
    return [h("div", { class: "sb" }, tiles),
      shots.length > lim ? h("button", { type: "button", class: "btn sm ghost", onclick: () => { sbMore = true; paintView(); } }, t("wx_more") + " (" + (shots.length - lim) + ")") : null];
  }
  function paintDetails() {
    if (!film) return [h("p", { class: "empty" }, t("wx_no_film"))];
    const p = pdef(film.provider) || {}, sm = film.summary, est = film.estimate, b = film.budget || {};
    const rows = [[t("st_method"), (p.label || film.provider) + " \u2014 " + t(p.free ? "st_free" : "st_credits_tag")], [t("st_model"), film.model],
      [t("st_res"), film.resolution + " \u00b7 " + film.aspect_ratio], ["FPS", String(film.fps)], [t("st_shot_len"), film.shot_seconds + "s"],
      [t("st_target"), film.target_seconds ? fmtLong(film.target_seconds) : t("st_t_none")], [t("st_shots"), String(sm.shots)], [t("st_len"), fmtLong(sm.seconds_total)],
      [t("st_credits_spent"), String(sm.credits_spent)],
      [t("st_est_left"), est.credits == null ? t("st_unknown") : "\u2248 " + est.credits + (est.days ? " \u00b7 \u2248 " + est.days + " " + t("st_days") : "")]];
    if (!p.free) rows.push([t("st_cap_daily"), b.daily_cap ? String(b.daily_cap) : "\u2014"], [t("st_cap_total"), b.total_cap ? String(b.total_cap) : "\u2014"]);
    return [h("div", { class: "panel" }, h("div", { class: "plansum" }, rows.map(([k, v]) => kv2(k, v)))), p.note ? h("p", { class: "muted small", dir: "auto" }, p.note) : null];
  }
  function paintView() {
    for (const b of rtabs.children) b.setAttribute("aria-selected", String(b.dataset.id === rtab));
    const sh = film && curShot();
    const extra = !film ? 0 : rtab === "details" ? film.updated : rtab === "board" ? allShots(film).map((s) => s.state).join("") : 0;
    const v2 = JSON.stringify([film && film.id, rtab, showFinal, selSid, sbMore, sh && [sh.state, sh.error, sh.credits], film && [film.state, film.output && film.output.path], extra]);
    if (v2 === vs) return;
    vs = v2;
    put(viewBox, rtab === "board" ? paintBoard() : rtab === "details" ? paintDetails() : paintPreview());
  }
  function paintAll() { paintTop(); paintScenes(); paintView(); }

  function onFilm(f) {
    const prev = last.get(f.id);
    last.set(f.id, f);
    if (f.id !== current) return;
    film = f;
    const shots = allShots(f);
    if (!selSid || !shots.some((s) => s.id === selSid)) selSid = (shots.find((s) => s.state === "completed") || shots[0] || {}).id || null;
    if (f.state === "assembled" && (!prev || prev.state !== "assembled")) { showFinal = true; rtab = "preview"; }
    paintAll();
  }
  function attach(fid) {
    current = fid; lsSet(fid); film = last.get(fid) || null; selSid = null; showFinal = false; sbMore = false; ss = ""; vs = "";
    if (film) { const sh = allShots(film); selSid = (sh.find((s) => s.state === "completed") || sh[0] || {}).id || null; }
    if (cards.has(fid) && cards.get(fid).isConnected) cards.get(fid).scrollIntoView({ block: "center", behavior: "smooth" });
    else { const c = filmCard(fid); cards.set(fid, c); say("bot", c); }
    paintAll(); paintQuick(); refreshRail();
  }
  function newFilm() {
    current = null; film = null; selSid = null; ss = ""; vs = ""; lsSet("");
    paintAll(); paintQuick(); refreshRail(); setPane("chat");
    say("bot", t("wx_new_hint")); input.focus();
  }

  /* ---------- conversation ---------- */
  const INTENTS = [
    ["retry", /(retry|regenerate|redo|أعد|إعادة|اعد)/i, /(fail|فاشل|فشل)/i],
    ["resume", /(continue|resume|تابع|أكمل|اكمل|استكمل|كمل)/i],
    ["export", /(export|assemble|finali[sz]e|صدّر|صدر|جمّع|جمع|ركّب|ركب)/i],
    ["cancel", /(cancel|stop|ألغ|الغ|أوقف|اوقف)/i],
    ["status", /(status|progress|حالة|تقدم)/i],
  ];
  const intent = (txt) => {
    if (txt.length > 70 || txt.split(/\s+/).length > 6) return null;
    for (const [k, a, b] of INTENTS) if (a.test(txt) && (!b || b.test(txt))) return k;
    return null;
  };
  async function retryFailed(fid, ack) {
    if (!ack && !confirm(t("st_retry_confirm"))) return;
    try {
      await api("/api/films/" + encodeURIComponent(fid) + "/retry-failed", { method: "POST", body: { confirm_cost: true, acknowledge_possible_charge: !!ack } });
      say("bot", t("st_done"));
    } catch (e) {
      if (!ack && /acknowledge_possible_charge/.test(e.message) && confirm(t("st_ack_charge"))) return retryFailed(fid, true);
      throw e;
    }
  }
  async function runIntent(k) {
    if (!current) { say("bot", t("st_no_film")); return; }
    const id = encodeURIComponent(current);
    const post = (p, b) => api("/api/films/" + id + p, { method: "POST", body: b || {} });
    try {
      if (k === "status") { attach(current); return; }
      if (k === "resume") { await post("/resume"); say("bot", t("st_done")); return; }
      if (k === "cancel") { if (!confirm(t("st_cancel_confirm"))) return; await post("/cancel"); say("bot", t("st_done")); return; }
      if (k === "export") {
        const f = await api("/api/films/" + id);
        const miss = f.summary.shots - (f.summary.by_state.completed || 0);
        if (miss > 0 && !confirm(t("st_partial_confirm").replace("{n}", String(miss)))) return;
        await post("/assemble", { allow_partial: miss > 0 });
        say("bot", t("st_assembling")); return;
      }
      if (k === "retry") await retryFailed(current);
    } catch (e) { warn(e); }
  }

  function planCard(idea) {
    const lang = /[\u0600-\u06FF]/.test(idea) ? "ar" : "en";
    const pv = sel(t("st_method"), prov.map((p) => [p.name, p.label + " \u2014 " + t(p.free ? "st_free" : "st_credits_tag")]), (prov.find((p) => p.free) || prov[0]).name);
    const pd = () => prov.find((p) => p.name === pv.value);
    const title = h("input", { value: idea.split("\n")[0].slice(0, 60), maxlength: "100", dir: "auto", "aria-label": t("lbl_title") });
    const model = sel(t("st_model"), [], ""), res = sel(t("st_res"), [], ""), ratio = sel(t("st_ratio"), [], ""), secs = sel(t("st_shot_len"), [], "");
    const target = sel(t("st_target"), [["0", t("st_t_none")], ...[1, 3, 5, 10, 20, 40].map((m) => [String(m * 60), m + " " + t("st_min")])], "0");
    const style = h("input", { maxlength: "200", dir: "auto", "aria-label": t("st_style") });
    const loc = h("input", { maxlength: "200", dir: "auto", "aria-label": t("st_loc") });
    const chars = h("input", { maxlength: "600", dir: "auto", "aria-label": t("st_chars") });
    const narId = "nar-" + Math.random().toString(36).slice(2, 8);
    const nar = h("input", { type: "checkbox", id: narId });
    const narRow = h("label", { class: "chk", for: narId }, nar, h("span", {}, t("st_narration")));
    const voice = sel(t("lbl_voice"), [["", t("voice_auto")]], "");
    const voiceLf = lf(t("lbl_voice"), voice);
    const note = h("p", { class: "muted small" });
    const out = h("div", { class: "plansum" });
    const create = h("button", { type: "button", class: "btn primary", disabled: true, onclick: safe(make) }, icon("film"), t("st_create"));
    const fill = (s, vals, keep) => { const l = vals.map(String); s.replaceChildren(...l.map((v) => h("option", { value: v }, v))); s.value = l.includes(keep) ? keep : l[0]; };
    function applyModel() { const m = pd().models[model.value]; fill(res, m.resolutions, res.value || "480p"); fill(ratio, m.aspect_ratios, ratio.value || "16:9"); fill(secs, m.seconds, secs.value || "5"); }
    function applyProvider() {
      const p = pd(), mm = p.models, names = Object.keys(mm);
      model.replaceChildren(...names.map((n) => h("option", { value: n, disabled: !!mm[n].plan_note }, n + (mm[n].plan_note ? " \u2014 " + t("st_paid") : ""))));
      model.value = "wan-2.2";
      note.textContent = t(p.free ? "st_note_free" : "st_note_ai");
      narRow.hidden = !p.free; nar.checked = false; voiceLf.hidden = true;
      applyModel();
    }
    async function loadVoices() {
      try {
        const l = await api("/api/voices?lang=" + lang);
        voice.replaceChildren(h("option", { value: "" }, t("voice_auto")), ...l.map((v) => h("option", { value: v.name }, v.name + " (" + v.gender + ")")));
        const pref = l.find((v) => /Jamal|Hamed|Guy|Aria/.test(v.name)) || l[0];
        voice.value = pref ? pref.name : "";
      } catch (e) { toast(t("voices_fail"), true); nar.checked = false; voiceLf.hidden = true; }
      sched();
    }
    const spec = () => ({
      title: title.value, script: idea, provider: pv.value, model: model.value, resolution: res.value, aspect_ratio: ratio.value,
      shot_seconds: Number(secs.value), target_seconds: Number(target.value) || undefined, audio: !!(pd().free && nar.checked),
      voice: voice.value || undefined, language: lang,
      continuity: { style: style.value, location: loc.value, characters: chars.value.split(",").map((x) => x.trim()).filter(Boolean) },
    });
    let timer;
    async function recalc() {
      out.replaceChildren(h("span", { class: "muted small" }, t("loading")));
      try {
        const f = await api("/api/films/plan", { method: "POST", body: spec() });
        out.replaceChildren(kv(t("st_scenes"), String(f.scenes.length)), kv(t("st_shots"), String(f.summary.shots)), kv(t("st_len"), fmtLong(f.summary.seconds_total)),
          kv(t("st_credits"), f.estimate.credits == null ? t("st_unknown") : (pd().free ? "0" : "\u2248 " + f.estimate.credits)));
        create.disabled = false;
      } catch (e) { out.replaceChildren(h("p", { class: "error small", role: "alert", dir: "auto" }, e.message)); create.disabled = true; }
    }
    const sched = () => { clearTimeout(timer); timer = setTimeout(recalc, 350); };
    async function make() {
      create.disabled = true;
      try {
        const f = await api("/api/films", { method: "POST", body: spec() });
        card.disabled = true;
        attach(f.id);
      } catch (e) { create.disabled = false; throw e; }
    }
    const card = h("fieldset", { class: "plan" },
      h("legend", { class: "sr" }, t("st_plan_title")),
      h("b", {}, t("st_plan_title")), h("p", { class: "muted small" }, t("st_plan_hint")),
      lf(t("lbl_title"), title), lf(t("st_method"), pv), note,
      h("div", { class: "plangrid" }, lf(t("st_model"), model), lf(t("st_res"), res), lf(t("st_ratio"), ratio), lf(t("st_shot_len"), secs), lf(t("st_target"), target)),
      narRow, voiceLf,
      h("details", { class: "more" }, h("summary", {}, t("st_continuity")), lf(t("st_style"), style), lf(t("st_loc"), loc), lf(t("st_chars"), chars)),
      out, h("div", { class: "acts" }, create));
    pv.addEventListener("change", () => { applyProvider(); sched(); });
    model.addEventListener("change", () => { applyModel(); sched(); });
    nar.addEventListener("change", () => { voiceLf.hidden = !nar.checked; if (nar.checked) loadVoices(); else sched(); });
    [res, ratio, secs, target, voice].forEach((e) => e.addEventListener("change", sched));
    [title, style, loc, chars].forEach((e) => e.addEventListener("input", sched));
    applyProvider(); recalc();
    return card;
  }

  function filmCard(fid) {
    const box = h("div", { class: "fcard" });
    const head = h("div", { class: "fhead" }), stat = h("div", { class: "fstat" }), body = h("div", { class: "fbody" });
    const cap = h("input", { type: "number", min: "1", step: "1", inputmode: "numeric", value: "100", "aria-label": t("st_cap_daily") });
    const tot = h("input", { type: "number", min: "1", step: "1", inputmode: "numeric", "aria-label": t("st_cap_total"), placeholder: t("st_optional") });
    const auto = h("input", { type: "checkbox", id: "auto-" + fid });
    const sure = h("input", { type: "checkbox", id: "sure-" + fid });
    const startBtn = h("button", { type: "button", class: "btn primary", disabled: true, onclick: safe(start) }, icon("play"), t("st_start"));
    sure.addEventListener("change", () => { startBtn.disabled = !sure.checked || !mh.configured; });
    const startForm = h("div", { class: "startform" },
      h("p", { class: "muted small" }, t("st_cost_note")),
      h("div", { class: "plangrid" }, lf(t("st_cap_daily"), cap), lf(t("st_cap_total"), tot)),
      h("label", { class: "chk", for: "auto-" + fid }, auto, h("span", {}, t("st_auto"))),
      h("label", { class: "chk", for: "sure-" + fid }, sure, h("span", {}, t("st_confirm_cb"))),
      h("div", { class: "acts" }, startBtn));
    let film = null, sig = "";
    const post = (p, b) => api("/api/films/" + encodeURIComponent(fid) + p, { method: "POST", body: b || {} });
    async function load(force) {
      film = await api("/api/films/" + encodeURIComponent(fid));
      onFilm(film);
      const s = JSON.stringify([film.updated, film.running, film.assembly, film.state]);
      if (!force && s === sig) return;
      sig = s; paint();
    }
    async function start() {
      const dc = cap.value ? Number(cap.value) : undefined, tc = tot.value ? Number(tot.value) : undefined;
      if (!dc && !tc) throw new Error(t("st_need_cap"));
      if (!confirm(t("st_confirm_start"))) return;
      await post("/start", { confirm_cost: true, daily_cap: dc, total_cap: tc, auto_resume: auto.checked });
      await load(true);
    }
    async function startFree() { await post("/start", {}); await load(true); }
    function paint() {
      const f = film, sm = f.summary, est = f.estimate, done = sm.by_state.completed || 0;
      const asm = f.assembly && f.assembly.state, assembling = asm === "running";
      put(head, [h("b", { dir: "auto", class: "ftitle" }, f.title), fbadge(f.state)]);
      const bits = [done + "/" + sm.shots + " " + t("st_shots"), fmtLong(sm.seconds_done) + " / " + fmtLong(sm.seconds_total), t("st_credits_spent") + " " + sm.credits_spent];
      if (est.credits) bits.push(t("st_est_left") + " \u2248 " + est.credits + (est.days ? " \u00b7 \u2248 " + est.days + " " + t("st_days") : ""));
      put(stat, [meter(f.running && sm.percent === 0 ? null : sm.percent), h("p", { class: "muted small" }, bits.join(" \u00b7 "))]);
      const kids = [], acts = [];
      const btn = (cls, ic, txt, fn) => h("button", { type: "button", class: "btn " + cls, onclick: safe(fn) }, icon(ic), txt);
      if (f.error) kids.push(h("p", { class: (f.state === "failed" ? "error" : "warn") + " small", role: "status", dir: "auto" }, f.error));
      if (f.state === "draft") {
        const pr = prov.find((x) => x.name === f.provider) || mh;
        if (!pr.configured) kids.push(h("p", { class: "error small", role: "alert" }, t("st_not_cfg")));
        if (pr.free) kids.push(h("p", { class: "muted small" }, t("st_free_note")),
          h("div", { class: "acts" }, h("button", { type: "button", class: "btn primary", disabled: !pr.configured, onclick: safe(startFree) }, icon("play"), t("st_start_free"))));
        else { startBtn.disabled = !sure.checked || !pr.configured; kids.push(startForm); }
      }
      if (f.state === "running") acts.push(btn("danger sm", "stop", t("st_cancel"), async () => { await post("/cancel"); await load(true); }));
      if (["waiting_budget", "interrupted", "cancelled"].includes(f.state)) acts.push(btn("primary sm", "play", t("st_resume"), async () => { await post("/resume"); await load(true); }));
      if (["waiting_budget", "interrupted"].includes(f.state)) acts.push(btn("danger sm", "stop", t("st_cancel"), async () => { await post("/cancel"); await load(true); }));
      if ((sm.by_state.failed || 0) > 0 && f.state === "failed") acts.push(btn("primary sm", "redo", t("st_retry_failed"), () => retryFailed(fid)));
      if (!assembling && done > 0 && ["waiting_budget", "interrupted", "cancelled", "failed"].includes(f.state)) acts.push(btn("sm", "film", t("st_assemble_partial"), async () => { await post("/assemble", { allow_partial: true }); await load(true); }));
      if (!assembling && f.state === "generated") acts.push(btn("primary sm", "film", t("st_assemble"), async () => { await post("/assemble", { allow_partial: false }); await load(true); }));
      if (assembling) kids.push(h("span", { class: "muted small" }, t("st_assembling")), meter(null));
      if (asm === "failed" && f.assembly.error) kids.push(h("p", { class: "error small", role: "alert", dir: "auto" }, f.assembly.error));
      if (f.state === "assembled" && f.output) {
        if (f.output.partial) kids.push(h("p", { class: "warn small" }, t("st_partial_note") + " (" + f.output.missing.length + ")"));
        acts.push(h("a", { class: "btn primary sm", href: "/api/films/" + encodeURIComponent(fid) + "/output?dl=1", download: "film.mp4" }, icon("download"), t("render_download")));
      }
      put(body, [kids, acts.length ? [h("div", { class: "acts" }, acts)] : []]);
    }
    box.append(head, stat, body);
    load(true).catch((e) => box.replaceChildren(h("p", { class: "error", role: "alert" }, e.message)));
    whileMounted(box, load, 4000);
    return box;
  }

  async function send() {
    const text = input.value.trim();
    if (!text) return;
    input.value = ""; grow();
    say("user", text);
    const k = intent(text);
    if (k) { await runIntent(k); return; }
    say("bot", t("st_plan_intro"));
    say("bot", planCard(text));
  }
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
  input.addEventListener("input", grow);

  const composer = h("div", { class: "composer" }, input, h("button", { type: "button", class: "send", "aria-label": t("st_send"), onclick: send }, icon("send")));
  const chatPane = h("section", { class: "wx-pane wx-chat", "aria-label": t("wx_chat") }, rail, thread, quick, composer);
  const scenesPane = h("section", { class: "wx-pane wx-scenes", "aria-label": t("wx_scenes") },
    h("div", { class: "panel wx-card" }, scenesBox),
    h("div", { class: "panel wx-card" }, h("div", { class: "acts" },
      h("button", { type: "button", class: "btn sm", onclick: newFilm }, icon("plus"), t("wx_new_film")),
      h("a", { class: "btn sm ghost", href: "#/queue" }, icon("list"), t("nav_queue")))));
  const viewPane = h("section", { class: "wx-pane wx-view", "aria-label": t("wx_preview") }, rtabs, viewBox);
  root.append(
    h("div", { class: "wx-top" }, h("div", { class: "wx-title" }, titleEl, statusEl)),
    seg, h("div", { class: "wx-grid" }, scenesPane, chatPane, viewPane));
  setPane("chat"); paintAll();
  say("bot", h("div", {}, h("b", {}, t("st_hello")), h("p", { class: "muted small" }, t("st_caps"))));
  const saved = lsGet();
  if (saved && list0.some((f) => f.id === saved)) attach(saved); else { refreshRail(); paintQuick(); }
  return root;
}


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

const FEATURES = [["projects", 1], ["script_ed", 1], ["i18n", 1], ["voices", 1], ["render", 1], ["subs", 0],
  ["assets", 0], ["scenes", 0], ["music", 0], ["accounts", 0], ["billing", 0], ["youtube", 0]];
function features() {
  return h("div", {}, h("h1", {}, t("features_title")), h("p", { class: "muted" }, t("features_note")),
    h("ul", { class: "features" }, FEATURES.map(([id, ok]) =>
      h("li", {}, h("span", {}, t("f_" + id)), h("span", { class: "pill " + (ok ? "ok" : "warn") }, t(ok ? "status_ok" : "status_planned"))))));
}
async function route() {
  const my = ++SEQ;
  renderNav();
  const main = $("#main");
  main.replaceChildren(skeleton());
  window.scrollTo(0, 0);
  const hash = location.hash || "#/";
  try {
    let view;
    if (hash === "#/") view = await dashboard();
    else if (hash === "#/new") view = workspace(null, []);
    else if (hash === "#/studio") view = await studio();
    else if (hash === "#/ai") view = await aiStudio();
    else if (hash === "#/preview") view = await aiStudio();
    else if (hash === "#/queue") view = await queuePage();
    else if (hash === "#/features") view = features();
    else if (hash.startsWith("#/p/")) {
      const id = decodeURIComponent(hash.slice(4));
      const [proj, jobs] = await Promise.all([api("/api/projects/" + encodeURIComponent(id)), recentJobs(15).catch(() => [])]);
      view = workspace(proj, jobs);
    } else view = h("p", { class: "empty" }, t("not_found"));
    if (my !== SEQ) return;
    main.replaceChildren(view);
  } catch (e) {
    if (my !== SEQ) return;
    main.replaceChildren(h("p", { class: "error", role: "alert" }, e.message === "project not found" ? t("not_found") : e.message));
  }
}
async function paintStatus() {
  const el = $("#status");
  if (!el) return;
  try {
    const [sys, pv] = await Promise.all([api("/api/system"), api("/api/providers")]);
    const mk = (ok, txt) => h("span", { class: "sitem" }, h("i", { class: "sdot " + (ok ? "ok" : "bad") }), txt);
    el.replaceChildren(
      h("span", { class: "sgrp2" }, mk(true, t("ft_ok")), ...pv.map((p) => mk(p.configured, p.label + (p.configured ? "" : " \u2014 " + t("ai_not_cfg"))))),
      h("span", { class: "sgrp2" }, mk(sys.free_mb - sys.min_free_mb >= 500, (sys.free_mb / 1024).toFixed(1) + " " + t("storage_free")), h("span", {}, t("stat_jobs") + " " + sys.jobs_active)));
  } catch { el.replaceChildren(h("span", { class: "sitem" }, h("i", { class: "sdot bad" }), t("err_network"))); }
}
(async function init() {
  let saved = null;
  try { saved = localStorage.getItem("ui_lang"); } catch {}
  const sel = $("#ui-lang");
  sel.replaceChildren(...Object.entries(UI_LANGS).map(([c, n]) => h("option", { value: c }, n)));
  sel.addEventListener("change", async () => {
    if (DIRTY && !confirm(t("confirm_leave"))) { sel.value = LANG; return; }
    DIRTY = false;
    try { await setLang(sel.value); } catch (e) { toast(e.message, true); sel.value = LANG; }
  });
  $(".skip").addEventListener("click", (e) => { e.preventDefault(); $("#main").focus(); });
  window.addEventListener("hashchange", () => {
    if (guard) { guard = false; return; }
    if (DIRTY && !confirm(t("confirm_leave"))) { guard = true; location.hash = lastHash; return; }
    DIRTY = false; lastHash = location.hash || "#/"; route();
  });
  try {
    const [en, meta] = await Promise.all([api("/api/i18n/en"), api("/api/meta")]);
    FALLBACK = en.strings; META = meta;
    await setLang(saved in UI_LANGS ? saved : "ar");
    paintStatus(); setInterval(paintStatus, 20000);
  } catch (e) { $("#main").textContent = e.message; }
})();
