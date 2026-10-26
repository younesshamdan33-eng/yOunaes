"use strict";
const $ = (s, r = document) => r.querySelector(s);
let I18N = {}, FALLBACK = {}, META = { langs: [], profiles: [], max_script: 20000 }, LANG = "ar";
const UI_LANGS = { ar: "العربية", en: "English" };
const t = (k) => I18N[k] ?? FALLBACK[k] ?? k;
const ICONS = {
  home: '<path d="M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  save: '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v6h7V3M8 21v-7h8v7"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
  play: '<path d="M6 4l14 8-14 8z"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
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
  route();
}
function renderNav() {
  const cur = location.hash || "#/";
  const items = [["#/", "nav_dashboard", "home"], ["#/new", "nav_new", "plus"], ["#/features", "nav_features", "grid"]];
  $("#nav").replaceChildren(...items.map(([href, k, ic]) =>
    h("a", { href, "aria-current": cur === href ? "page" : null }, icon(ic), h("span", {}, t(k)))));
}
function hue(s) { let x = 0; for (const c of s || "x") x = (x * 31 + c.codePointAt(0)) % 360; return x; }
function poster(title) {
  const el = h("div", { class: "poster" }, h("span", { class: "mark" }, [...(title || "?")][0]));
  el.style.setProperty("--h", String(hue(title)));
  return el;
}
const fmtDur = (s) => Math.floor(s / 60) + ":" + String(Math.round(s % 60)).padStart(2, "0");
function scenesOf(text) {
  const s = text.trim();
  if (!s) return [];
  let parts = s.split(/\n\s*\n/).map((x) => x.trim()).filter(Boolean);
  if (parts.length === 1) parts = s.split(/(?<=[.!?؟…])\s+/).map((x) => x.trim()).filter(Boolean);
  return parts.map((x) => ({ text: x, sec: Math.max(2, x.split(/\s+/).length / 2.5) }));
}
const stat = (k, v, extra) => h("div", { class: "stat" }, h("span", { class: "k" }, k), h("b", { class: "v" }, v), extra);
const skeleton = () => h("div", {}, h("div", { class: "skel" }), h("div", { class: "skel" }), h("div", { class: "skel" }));

function card(p) {
  const date = new Date(p.updated * 1000).toLocaleDateString(LANG);
  return h("a", { class: "card pcard", href: "#/p/" + p.id }, poster(p.title),
    h("div", { class: "body" }, h("h3", { dir: "auto" }, p.title), h("p", { class: "muted small" }, t("lang_" + p.script_lang) + " · " + date)));
}
async function dashboard() {
  const [projects, jobs, sys] = await Promise.all([api("/api/projects"), api("/api/jobs"), api("/api/system")]);
  const low = sys.free_mb - sys.min_free_mb < 500;
  const fill = h("i");
  fill.style.width = Math.min(100, Math.round((1 - sys.free_mb / sys.total_mb) * 100)) + "%";
  const bar = h("div", { class: "bar" + (low ? " warn" : "") }, fill);
  const queue = jobs.length
    ? h("ul", { class: "jobs" }, jobs.map((j) => {
        const f = h("i"); f.style.width = (j.progress || 0) + "%";
        return h("li", {}, j.kind + " · " + j.state + " · " + (j.progress || 0) + "%", h("div", { class: "bar" }, f));
      }))
    : h("p", { class: "empty" }, t("queue_empty"));
  return h("div", {},
    h("section", { class: "hero" }, h("h1", {}, t("hero_title")), h("p", {}, t("hero_sub")),
      h("a", { class: "btn primary", href: "#/new" }, icon("plus"), t("dash_new"))),
    h("div", { class: "stats" },
      stat(t("stat_projects"), String(sys.projects)),
      stat(t("stat_jobs"), String(sys.jobs_active)),
      stat(t("stat_storage"), (sys.free_mb / 1024).toFixed(1) + " " + t("storage_free"), bar)),
    low ? h("p", { class: "error small", role: "alert" }, t("storage_low")) : null,
    h("h2", {}, t("dash_title")),
    projects.length ? h("div", { class: "grid" }, projects.map(card)) : h("p", { class: "empty" }, t("dash_empty")),
    h("h2", {}, t("queue_title")), queue);
}
function select(id, options, value) {
  const s = h("select", { id, name: id }, options.map(([v, l]) => h("option", { value: v }, l)));
  s.value = value;
  return s;
}
const field = (id, label, ...c) => h("div", { class: "field" }, h("label", { for: id }, label), ...c);
const STEPS = [["story", "step_story"], ["voice", "step_voice"], ["look", "step_look"], ["render", "step_render"]];

function projectView(p) {
  const d = p || { title: "", script: "", script_lang: "ar", subtitle_lang: "ar", voice: "", profile: "480p" };
  const langs = META.langs.map((c) => [c, t("lang_" + c)]);
  const title = h("input", { id: "title", name: "title", maxlength: "100", value: d.title, autocomplete: "off", dir: "auto" });
  const script = h("textarea", { id: "script", rows: "12", maxlength: String(META.max_script), dir: "auto" }, d.script);
  const scriptLang = select("script_lang", langs, d.script_lang);
  const subLang = select("subtitle_lang", [["none", t("subtitle_none")], ...langs], d.subtitle_lang);
  const profile = select("profile", META.profiles.map((x) => [x, t("profile_" + x)]), d.profile);
  const voice = select("voice", [["", t("voice_auto")], ...(d.voice ? [[d.voice, d.voice]] : [])], d.voice);
  const stats = h("p", { class: "stats-line" });
  const tl = h("div", { class: "timeline" });
  const pvTitle = h("div", { class: "pv-title", dir: "auto" });
  const pvCap = h("div", { class: "pv-cap", dir: "auto" });
  const pv = h("div", { class: "preview" }, pvTitle, pvCap);
  const summary = h("dl", { class: "sum" });

  function refresh() {
    const s = script.value.trim();
    stats.textContent = (s ? s.split(/\s+/).length : 0) + " " + t("words") + " · " + script.value.length + " " + t("chars");
    const sc = scenesOf(script.value);
    const total = sc.reduce((a, x) => a + x.sec, 0);
    tl.replaceChildren(
      h("div", { class: "tl-head" }, h("b", {}, t("timeline_title")),
        h("span", { class: "muted small" }, sc.length + " " + t("scene") + " · " + t("est_total") + " " + fmtDur(total))),
      sc.length ? h("div", { class: "strip" }, sc.slice(0, 60).map((x, i) => { const e = h("i", { title: "#" + (i + 1) }); e.style.flexGrow = String(x.sec); return e; }))
                : h("p", { class: "empty" }, t("timeline_empty")),
      sc.length ? h("ol", { class: "scenes" }, sc.slice(0, 12).map((x, i) =>
        h("li", {}, h("span", { class: "n" }, String(i + 1)), h("span", { class: "tx", dir: "auto" }, x.text.slice(0, 90)), h("span", { class: "d" }, fmtDur(x.sec))))) : null,
      h("p", { class: "muted small" }, t("timeline_note")));
    pv.style.setProperty("--h", String(hue(title.value)));
    pvTitle.textContent = title.value || "…";
    pvCap.textContent = sc.length ? sc[0].text.slice(0, 80) : "";
    pvCap.hidden = !sc.length;
  }
  function buildSummary() {
    const row = (k, v) => h("div", {}, h("dt", {}, k), h("dd", {}, v));
    summary.replaceChildren(
      row(t("lbl_script_lang"), t("lang_" + scriptLang.value)),
      row(t("lbl_voice"), voice.value || t("voice_auto")),
      row(t("lbl_subtitle_lang"), subLang.value === "none" ? t("subtitle_none") : t("lang_" + subLang.value)),
      row(t("lbl_profile"), t("profile_" + profile.value)));
  }
  [title, script].forEach((e) => e.addEventListener("input", refresh));

  const loadBtn = h("button", { type: "button", class: "btn", onclick: async () => {
    loadBtn.disabled = true; loadBtn.textContent = t("voices_loading");
    try {
      const list = await api("/api/voices?lang=" + scriptLang.value);
      const keep = voice.value;
      voice.replaceChildren(h("option", { value: "" }, t("voice_auto")),
        ...list.map((v) => h("option", { value: v.name }, v.name + " (" + v.gender + ")")));
      voice.value = list.some((v) => v.name === keep) ? keep : "";
      toast(t("voices_loaded"));
    } catch (e) { toast(e.message, true); }
    loadBtn.disabled = false; loadBtn.textContent = t("voices_load");
  } }, icon("mic"), t("voices_load"));

  const sections = {
    story: h("section", { "data-step": "story" }, field("title", t("lbl_title"), title), field("script", t("lbl_script"), script, stats), tl),
    voice: h("section", { "data-step": "voice" }, field("script_lang", t("lbl_script_lang"), scriptLang),
      field("voice", t("lbl_voice"), voice, h("div", { style: null, class: "field" }, loadBtn)),
      field("subtitle_lang", t("lbl_subtitle_lang"), subLang), h("p", { class: "muted small" }, t("lang_note"))),
    look: h("section", { "data-step": "look" }, field("profile", t("lbl_profile"), profile), pv, h("p", { class: "muted small" }, t("preview_note"))),
    render: h("section", { "data-step": "render" }, h("h2", {}, t("render_summary")), summary,
      h("button", { type: "button", class: "btn primary", disabled: true }, icon("play"), t("render_btn")),
      h("p", { class: "muted small" }, t("render_planned"))),
  };
  const stepBtns = STEPS.map(([id, k], i) =>
    h("button", { type: "button", role: "tab", class: "step", "data-id": id, onclick: () => go(id) }, h("i", {}, String(i + 1)), t(k)));
  function go(id) {
    for (const [sid, el] of Object.entries(sections)) el.hidden = sid !== id;
    for (const b of stepBtns) b.setAttribute("aria-selected", String(b.dataset.id === id));
    if (id === "render") buildSummary();
  }
  async function save(ev) {
    ev.preventDefault();
    if (!title.value.trim()) { go("story"); title.focus(); toast(t("err_title"), true); return; }
    const body = { title: title.value, script: script.value, script_lang: scriptLang.value,
      subtitle_lang: subLang.value, voice: voice.value, profile: profile.value };
    try {
      const r = p ? await api("/api/projects/" + p.id, { method: "PUT", body }) : await api("/api/projects", { method: "POST", body });
      toast(t("saved")); location.hash = "#/p/" + r.id;
    } catch (e) { toast(e.message, true); }
  }
  const bar = h("div", { class: "actionbar" },
    h("button", { type: "submit", class: "btn primary" }, icon("save"), p ? t("save") : t("create")));
  if (p) bar.append(h("button", { type: "button", class: "btn danger", onclick: async () => {
    if (!confirm(t("confirm_delete"))) return;
    try { await api("/api/projects/" + p.id, { method: "DELETE" }); toast(t("deleted")); location.hash = "#/"; }
    catch (e) { toast(e.message, true); }
  } }, icon("trash"), t("delete")));
  const form = h("form", { novalidate: true, onsubmit: save },
    h("div", { class: "steps", role: "tablist" }, stepBtns), Object.values(sections), bar);
  refresh(); go("story");
  return h("div", {}, h("h1", {}, p ? t("edit_title") : t("new_title")), h("br"), form);
}
const FEATURES = [["projects", 1], ["script_ed", 1], ["i18n", 1], ["voices", 1], ["render", 0], ["subs", 0],
  ["assets", 0], ["scenes", 0], ["music", 0], ["accounts", 0], ["billing", 0], ["youtube", 0]];
function features() {
  return h("div", {}, h("h1", {}, t("features_title")), h("p", { class: "muted" }, t("features_note")),
    h("ul", { class: "features" }, FEATURES.map(([id, ok]) =>
      h("li", {}, h("span", {}, t("f_" + id)), h("span", { class: "badge " + (ok ? "ok" : "plan") }, t(ok ? "status_ok" : "status_planned"))))));
}
async function route() {
  renderNav();
  const main = $("#main");
  main.replaceChildren(skeleton());
  window.scrollTo(0, 0);
  const hash = location.hash || "#/";
  try {
    let view;
    if (hash === "#/") view = await dashboard();
    else if (hash === "#/new") view = projectView(null);
    else if (hash === "#/features") view = features();
    else if (hash.startsWith("#/p/")) view = projectView(await api("/api/projects/" + encodeURIComponent(hash.slice(4))));
    else view = h("p", { class: "empty" }, t("not_found"));
    main.replaceChildren(view);
  } catch (e) {
    main.replaceChildren(h("p", { class: "error", role: "alert" }, e.message === "project not found" ? t("not_found") : e.message));
  }
}
(async function init() {
  let saved = null;
  try { saved = localStorage.getItem("ui_lang"); } catch {}
  const sel = $("#ui-lang");
  sel.replaceChildren(...Object.entries(UI_LANGS).map(([c, n]) => h("option", { value: c }, n)));
  sel.addEventListener("change", () => setLang(sel.value));
  window.addEventListener("hashchange", route);
  try {
    const [en, meta] = await Promise.all([api("/api/i18n/en"), api("/api/meta")]);
    FALLBACK = en.strings; META = meta;
    await setLang(saved in UI_LANGS ? saved : "ar");
  } catch (e) { $("#main").textContent = e.message; }
})();
