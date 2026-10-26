"use strict";
const $ = (s, r = document) => r.querySelector(s);
let I18N = {}, FALLBACK = {}, META = { langs: [], profiles: [], max_script: 20000 }, LANG = "ar";
const UI_LANGS = { ar: "العربية", en: "English" };
const t = (k) => I18N[k] ?? FALLBACK[k] ?? k;

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
  if (o.body !== undefined) {
    o.headers["Content-Type"] = "application/json";
    o.body = JSON.stringify(o.body);
  }
  let r;
  try { r = await fetch(path, o); } catch { throw new Error(t("err_network")); }
  let d = null;
  try { d = await r.json(); } catch {}
  if (!r.ok) throw new Error((d && d.error) || String(r.status));
  return d;
}

async function setLang(lang) {
  const d = await api("/api/i18n/" + lang);
  I18N = d.strings;
  LANG = lang;
  document.documentElement.lang = lang;
  document.documentElement.dir = d.dir;
  try { localStorage.setItem("ui_lang", lang); } catch {}
  for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  $("#ui-lang").value = lang;
  route();
}

function renderNav() {
  const cur = location.hash || "#/";
  const items = [["#/", "nav_dashboard"], ["#/new", "nav_new"], ["#/features", "nav_features"]];
  $("#nav").replaceChildren(...items.map(([href, k]) =>
    h("a", { href, "aria-current": cur === href ? "page" : null }, t(k))));
}

function card(p) {
  const date = new Date(p.updated * 1000).toLocaleDateString(LANG);
  return h("a", { class: "card", href: "#/p/" + p.id },
    h("h3", { dir: "auto" }, p.title),
    h("p", { class: "muted" }, t("lang_" + p.script_lang) + " · " + date));
}

async function dashboard() {
  const [projects, jobs] = await Promise.all([api("/api/projects"), api("/api/jobs")]);
  const list = projects.length
    ? h("div", { class: "grid" }, projects.map(card))
    : h("p", { class: "empty" }, t("dash_empty"));
  const queue = jobs.length
    ? h("ul", { class: "jobs" }, jobs.map((j) => h("li", {}, j.kind + " · " + j.state + " · " + j.progress + "%")))
    : h("p", { class: "empty" }, t("queue_empty"));
  return h("div", {},
    h("div", { class: "row" }, h("h1", {}, t("dash_title")), h("a", { class: "btn primary", href: "#/new" }, t("dash_new"))),
    list, h("h2", {}, t("queue_title")), queue);
}

function select(id, options, value) {
  const s = h("select", { id, name: id }, options.map(([v, l]) => h("option", { value: v }, l)));
  s.value = value;
  return s;
}
const field = (id, label, control) => h("div", { class: "field" }, h("label", { for: id }, label), control);

function projectView(p) {
  const d = p || { title: "", script: "", script_lang: "ar", subtitle_lang: "ar", voice: "", profile: "480p" };
  const langs = META.langs.map((c) => [c, t("lang_" + c)]);
  const title = h("input", { id: "title", name: "title", maxlength: "100", required: true, value: d.title, autocomplete: "off", dir: "auto" });
  const script = h("textarea", { id: "script", rows: "12", maxlength: String(META.max_script), dir: "auto" }, d.script);
  const scriptLang = select("script_lang", langs, d.script_lang);
  const subLang = select("subtitle_lang", [["none", t("subtitle_none")], ...langs], d.subtitle_lang);
  const profile = select("profile", META.profiles.map((x) => [x, t("profile_" + x)]), d.profile);
  const voice = select("voice", [["", t("voice_auto")], ...(d.voice ? [[d.voice, d.voice]] : [])], d.voice);
  const stats = h("p", { class: "stats" });
  const upd = () => {
    const s = script.value.trim();
    stats.textContent = (s ? s.split(/\s+/).length : 0) + " " + t("words") + " · " + script.value.length + " " + t("chars");
  };
  script.addEventListener("input", upd);
  upd();
  const loadBtn = h("button", { type: "button", class: "btn", onclick: async () => {
    loadBtn.disabled = true;
    loadBtn.textContent = t("voices_loading");
    try {
      const list = await api("/api/voices?lang=" + scriptLang.value);
      const keep = voice.value;
      voice.replaceChildren(h("option", { value: "" }, t("voice_auto")),
        ...list.map((v) => h("option", { value: v.name }, v.name + " (" + v.gender + ")")));
      voice.value = list.some((v) => v.name === keep) ? keep : "";
      toast(t("voices_loaded"));
    } catch (e) { toast(e.message, true); }
    loadBtn.disabled = false;
    loadBtn.textContent = t("voices_load");
  } }, t("voices_load"));
  const actions = h("div", { class: "actions" },
    h("button", { type: "submit", class: "btn primary" }, p ? t("save") : t("create")),
    h("button", { type: "button", class: "btn", disabled: true }, t("render_btn")));
  if (p) actions.append(h("button", { type: "button", class: "btn danger", onclick: async () => {
    if (!confirm(t("confirm_delete"))) return;
    try { await api("/api/projects/" + p.id, { method: "DELETE" }); toast(t("deleted")); location.hash = "#/"; }
    catch (e) { toast(e.message, true); }
  } }, t("delete")));
  const form = h("form", { class: "panel", onsubmit: async (ev) => {
    ev.preventDefault();
    const body = { title: title.value, script: script.value, script_lang: scriptLang.value,
      subtitle_lang: subLang.value, voice: voice.value, profile: profile.value };
    try {
      const r = p ? await api("/api/projects/" + p.id, { method: "PUT", body })
                  : await api("/api/projects", { method: "POST", body });
      toast(t("saved"));
      location.hash = "#/p/" + r.id;
    } catch (e) { toast(e.message, true); }
  } },
    field("title", t("lbl_title"), title),
    field("script", t("lbl_script"), [script, stats]),
    field("script_lang", t("lbl_script_lang"), scriptLang),
    field("voice", t("lbl_voice"), [voice, h("div", { class: "actions" }, loadBtn)]),
    field("subtitle_lang", t("lbl_subtitle_lang"), subLang),
    field("profile", t("lbl_profile"), profile),
    h("p", { class: "muted" }, t("lang_note")),
    actions,
    h("p", { class: "muted" }, t("render_planned")));
  return h("div", {}, h("h1", {}, p ? t("edit_title") : t("new_title")), h("br"), form);
}

const FEATURES = [["projects", 1], ["script_ed", 1], ["i18n", 1], ["voices", 1], ["render", 0], ["subs", 0],
  ["assets", 0], ["scenes", 0], ["music", 0], ["accounts", 0], ["billing", 0], ["youtube", 0]];

function features() {
  return h("div", {}, h("h1", {}, t("features_title")), h("p", { class: "muted" }, t("features_note")),
    h("ul", { class: "features" }, FEATURES.map(([id, ok]) =>
      h("li", {}, h("span", {}, t("f_" + id)),
        h("span", { class: "badge " + (ok ? "ok" : "plan") }, t(ok ? "status_ok" : "status_planned"))))));
}

async function route() {
  renderNav();
  const main = $("#main");
  main.replaceChildren(h("p", { class: "muted" }, t("loading")));
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
    FALLBACK = en.strings;
    META = meta;
    await setLang(saved in UI_LANGS ? saved : "ar");
  } catch (e) { $("#main").textContent = e.message; }
})();
