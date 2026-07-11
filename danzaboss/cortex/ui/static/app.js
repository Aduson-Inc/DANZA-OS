/* CORTEX dashboard — vanilla JS, no build step. Read-only over the store.
   C4.5 redesign: memory-first feed, console for the extras, n8n-style workflow. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

const state = { view: "feed", q: "", type: "", project: "", env: "",
                items: [], knownIds: new Set(), firstLoad: true,
                consolePanel: "events" };

/* Plain-language type badges — users read "Bug Fix", not "impl_detail". */
const TYPE_LABEL = {
  decision: "Decision", bug_fix: "Bug Fix", security: "Security",
  limitation: "Limitation", milestone: "Milestone", convention: "Convention",
  impl_detail: "Change", root_cause: "Root Cause", lesson: "Discovery",
  perf: "Performance", dependency: "Dependency", api: "API",
  prompt: "Prompt", session: "Session Summary",
};
const typeLabel = (t) => TYPE_LABEL[t] || String(t || "").replace(/_/g, " ");

/* ---------- utilities ---------- */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function timeago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${res.status} on ${path}`);
  return res.json();
}

/* Mounted under the DANZA dashboard (/cortex/*)? Reveal the way back (D4). */
if (location.pathname.startsWith("/cortex")) $("#danza-link").hidden = false;

/* ---------- navigation (top bar tabs) ---------- */
$$(".tab").forEach((b) => b.addEventListener("click", () => {
  $$(".tab").forEach((x) => x.classList.toggle("active", x === b));
  state.view = b.dataset.view;
  $$(".view").forEach((v) => (v.hidden = v.id !== `view-${state.view}`));
  $("#drawer").hidden = true;
  refresh();
}));

/* ---------- memory feed ---------- */
function bladeHTML(confidence, source) {
  const c = Math.max(0, Math.min(100, Number(confidence) || 0));
  const hot = c >= 90 ? " hot" : "";
  return `<div class="blade-row">
    <div class="blade${hot}"><div class="blade-fill" style="transform:scaleX(${c / 100})"></div></div>
    <span class="blade-meta"><b>${c}</b> confidence · ${esc(source).replace(/_/g, " ")}</span>
  </div>`;
}

function factsHTML(o) {
  const evidence = (o.evidence || []).slice(0, 4)
    .map((e) => `<li class="mono dim">${esc(e)}</li>`).join("");
  return `<div class="card-body">
    <ul><li>${esc(o.summary)}</li>${evidence}</ul>
  </div>`;
}

function narrativeHTML(o) {
  const why = o.reasoning
    ? `<p class="why"><b>Why it matters:</b> ${esc(o.reasoning)}</p>` : "";
  return `<div class="card-body"><p>${esc(o.summary)}</p>${why}</div>`;
}

function cardHTML(o, fresh) {
  const draft = o.confidence_source === "speculation" ? " draft" : "";
  const superseded = o.superseded_by ? " superseded" : "";
  const freshCls = fresh ? " fresh" : "";
  const tags = (o.concepts || []).slice(0, 5)
    .map((t) => `<span class="tag">#${esc(t)}</span>`).join(" ");
  return `<article class="card imp-${esc(o.importance)}${draft}${superseded}${freshCls}"
      data-id="${esc(o.id)}" data-mode="facts" tabindex="0">
    <div class="card-head">
      <span class="card-num mono">#${o.num || "—"}</span>
      <span class="type-chip t-${esc(o.type)}">${esc(typeLabel(o.type))}</span>
      <span class="imp-label">${esc(o.importance)}</span>
      <div class="mode-toggle" role="group" aria-label="View mode">
        <button class="mode-btn active" data-mode="facts">facts</button>
        <button class="mode-btn" data-mode="narrative">narrative</button>
      </div>
    </div>
    <h3 class="card-title">${esc(o.title)}</h3>
    <div class="body-slot">${factsHTML(o)}</div>
    ${bladeHTML(o.confidence, o.confidence_source)}
    <div class="card-foot">
      <span>${timeago(o.updated)}</span>
      <span>~${o.read_tokens}t read</span>
      ${o.usage_count ? `<span>used ${o.usage_count}×</span>` : ""}
      ${tags}
    </div>
  </article>`;
}

function renderFeed(items) {
  const feed = $("#feed");
  const fresh = state.firstLoad ? new Set() :
    new Set(items.filter((o) => !state.knownIds.has(o.id)).map((o) => o.id));
  feed.innerHTML = items.map((o) => cardHTML(o, fresh.has(o.id))).join("");
  $("#feed-empty").hidden = items.length > 0;
  items.forEach((o) => state.knownIds.add(o.id));
  state.items = items;
  state.firstLoad = false;
  if (fresh.size) pulse();
}

$("#feed").addEventListener("click", (ev) => {
  const modeBtn = ev.target.closest(".mode-btn");
  const card = ev.target.closest(".card");
  if (!card) return;
  const o = state.items.find((x) => x.id === card.dataset.id);
  if (modeBtn && o) {
    const mode = modeBtn.dataset.mode;
    $$(".mode-btn", card).forEach((b) => b.classList.toggle("active", b === modeBtn));
    $(".body-slot", card).innerHTML = mode === "facts" ? factsHTML(o) : narrativeHTML(o);
    ev.stopPropagation();
    return;
  }
  openDrawer(card.dataset.id);
});

/* filters + search */
$("#type-filter").addEventListener("change", (ev) => {
  state.type = ev.target.value;
  loadFeed();
});

let searchTimer;
$("#search").addEventListener("input", (ev) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = ev.target.value.trim();
    if (state.view !== "feed") $$(".tab")[0].click();
    else loadFeed();
  }, 250);
});

async function loadFeed() {
  const params = new URLSearchParams({ limit: 100 });
  if (state.q) params.set("q", state.q);
  if (state.type) params.set("type", state.type);
  if (state.project) params.set("project", state.project);
  const data = await api(`api/observations?${params}`);
  renderFeed(data.items);
}

/* ---------- top-bar dropdowns ---------- */
async function loadMeta() {
  try {
    const m = await api("api/meta");
    const opt = (v, sel) => `<option value="${esc(v)}"${v === sel ? " selected" : ""}>${esc(v)}</option>`;
    $("#project-select").innerHTML = m.projects.map((p) => opt(p, m.project)).join("");
    $("#env-select").innerHTML = m.environments.map((e) => opt(e, state.env)).join("");
    state.project = m.project;
  } catch { /* dropdowns are cosmetic at boot */ }
}
$("#project-select").addEventListener("change", (ev) => {
  state.project = ev.target.value; loadFeed();
});
$("#env-select").addEventListener("change", (ev) => {
  state.env = ev.target.value;
  if (state.view === "console") loadConsole();
});

/* ---------- drawer ---------- */
async function openDrawer(id) {
  const o = await api(`api/observations/${id}`);
  const kv = (dt, dd) => dd ? `<dt>${dt}</dt><dd>${dd}</dd>` : "";
  const list = (arr, cls) => (arr && arr.length)
    ? `<ul class="${cls}">${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  const rel = (arr, cls) => (arr || []).map((x) => `<span class="rel-chip ${cls}">${esc(x)}</span>`).join("");
  const history = (o.history || []).map((h) =>
    `<div class="history-item"><span class="mono">${esc(h.ts || "")}</span> —
     ${esc(h.event || "")}${h.confidence ? ` (confidence → ${h.confidence})` : ""}</div>`).join("");
  $("#drawer-body").innerHTML = `
    <span class="type-chip t-${esc(o.type)}">${esc(typeLabel(o.type))}</span>
    <h2>${esc(o.title)}</h2>
    ${bladeHTML(o.confidence, o.confidence_source)}
    <h3 class="section-label">Summary</h3><p>${esc(o.summary)}</p>
    ${o.reasoning ? `<h3 class="section-label">Why</h3><p>${esc(o.reasoning)}</p>` : ""}
    ${o.lessons ? `<h3 class="section-label">Lessons</h3><p>${esc(o.lessons)}</p>` : ""}
    ${(o.when_relevant?.length || o.when_not_relevant?.length)
      ? `<h3 class="section-label">Relevance triggers</h3>
         <div>${rel(o.when_relevant, "yes")}${rel(o.when_not_relevant, "no")}</div>` : ""}
    ${o.evidence?.length ? `<h3 class="section-label">Evidence</h3>${list(o.evidence, "evidence")}` : ""}
    ${o.files?.length ? `<h3 class="section-label">Files</h3>${list(o.files, "files")}` : ""}
    <h3 class="section-label">Record</h3>
    <dl class="kv">
      ${kv("id", `<span class="mono">${esc(o.id)}</span>`)}
      ${kv("importance", esc(o.importance))}
      ${kv("layer", `L${o.layer}`)}
      ${kv("created", esc(o.created))}
      ${kv("updated", esc(o.updated))}
      ${kv("expires", o.expires ? esc(o.expires) : "never")}
      ${kv("used", `${o.usage_count}×`)}
      ${kv("supersedes", o.supersedes ? `<span class="mono">${esc(o.supersedes)}</span>` : "")}
      ${kv("superseded by", o.superseded_by ? `<span class="mono">${esc(o.superseded_by)}</span>` : "")}
    </dl>
    ${history ? `<h3 class="section-label">Evolution</h3>${history}` : ""}`;
  $("#drawer").hidden = false;
}
$("#drawer-close").addEventListener("click", () => ($("#drawer").hidden = true));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { $("#drawer").hidden = true; $("#node-panel").hidden = true; }
});

/* ---------- console ---------- */
$("#console-subtabs").addEventListener("click", (ev) => {
  const chip = ev.target.closest(".chip");
  if (!chip) return;
  $$(".chip", $("#console-subtabs")).forEach((c) => c.classList.toggle("active", c === chip));
  state.consolePanel = chip.dataset.panel;
  $$(".console-panel").forEach((p) => (p.hidden = p.id !== `panel-${state.consolePanel}`));
  loadConsole();
});

function consoleRow(r) {
  const t = (r.ts || "").replace("T", " ").replace("+00:00", "");
  const sid = (r.session || "").slice(0, 8);
  return `<div class="clog-row k-${esc(r.kind)}">
    <span class="clog-ts">${esc(t)}</span>
    <span class="clog-kind">${esc(r.kind)}</span>
    <span class="clog-sid dim">${esc(sid)}</span>
    <span class="clog-tool">${esc(r.tool)}</span>
    <span class="clog-detail">${esc(r.detail)}</span>
  </div>`;
}

async function loadConsole() {
  if (state.consolePanel === "sessions") return loadSessions();
  if (state.consolePanel !== "events") return;
  const data = await api("api/console?limit=200");
  $("#console-log").innerHTML = data.items.map(consoleRow).join("") ||
    '<p class="dim">no events captured yet</p>';
}

/* ---------- explain playground (console › retrieval trace) ---------- */
function sigRowHTML(name, ids, titles) {
  const chips = ids.slice(0, 4).map((id) =>
    `<span class="sig-chip" title="${esc(id)}">${esc((titles[id] || id).slice(0, 34))}</span>`).join("");
  const more = ids.length > 4 ? `<span class="dim mono">+${ids.length - 4}</span>` : "";
  return `<div class="sig-row"><span class="sig-name mono">${esc(name)}</span>
    ${ids.length ? chips + more : '<span class="dim">—</span>'}</div>`;
}

function explainHTML(t) {
  const titles = t.titles || {};
  const maxFinal = Math.max(1e-9, ...t.fusion.map((r) => r.final));
  const fusion = t.fusion.slice(0, 12).map((r, i) => `<div class="fuse-row">
      <span class="fuse-rank mono">${i + 1}</span>
      <span class="fuse-title">${esc(r.title)}</span>
      <div class="bar-track"><div class="bar-fill" style="transform:scaleX(${r.final / maxFinal})"></div></div>
      <span class="mono dim">${r.final.toFixed(4)}</span>
      <span class="fuse-sigs mono dim">${Object.entries(r.signal_ranks)
        .map(([s, k]) => `${s}#${k}`).join(" ")}</span>
    </div>`).join("");
  const kills = t.killed.map((k) => `<div class="kill-row">
      <span class="kill-title">${esc(k.title)}</span>
      <span class="kill-trigger mono">killed by "${esc(k.trigger)}"</span>
    </div>`).join("");
  const items = t.package.items.map((it) => `<div class="pkg-row">
      <span class="type-chip">${esc(it.category)}</span>
      <span class="pkg-title">${esc(it.title)}</span>
      <span class="mono dim">${it.tokens}t${it.compressed ? " · compressed" : ""}</span>
      <div class="pkg-reasons dim">${it.reasons.map(esc).join(" · ")}</div>
    </div>`).join("");
  const dropped = t.package.dropped.map((d) =>
    `<div class="kill-row"><span class="kill-title">${esc(d.title)}</span>
     <span class="kill-trigger mono">${esc(d.reason)}</span></div>`).join("");
  const q = t.quality;
  const qBlade = (label, v) => `<div class="blade-row">
      <div class="blade"><div class="blade-fill" style="transform:scaleX(${v})"></div></div>
      <span class="blade-meta">${label} <b>${(v * 100).toFixed(0)}</b></span></div>`;
  return `
    <div class="explain-intent">
      <span class="type-chip t-decision">intent: ${esc(t.intent.name)}</span>
      <span class="dim">${t.intent.matched.map(esc).join(" · ")}</span>
    </div>
    <h2 class="section-label">Signal rankings</h2>
    ${Object.entries(t.signals).map(([n, ids]) => sigRowHTML(n, ids, titles)).join("")}
    ${kills ? `<h2 class="section-label">Anti-relevance kills</h2>${kills}` : ""}
    <h2 class="section-label">RRF fusion — final ranking</h2>
    ${fusion || '<p class="dim">nothing retrieved</p>'}
    <h2 class="section-label">Package — ${t.package.used}t of ${t.package.budget}t
      ${t.replanned ? " · re-planned once" : ""}</h2>
    ${items || '<p class="dim">empty package</p>'}
    ${dropped}
    <h2 class="section-label">Quality — overall ${(q.overall * 100).toFixed(0)}
      ${q.passed ? "PASS" : "BELOW THRESHOLD"}</h2>
    ${qBlade("relevance", q.relevance)}${qBlade("coverage", q.coverage)}
    ${qBlade("redundancy", q.redundancy)}${qBlade("efficiency", q.efficiency)}
    ${t.notes.length ? `<p class="dim">${t.notes.map(esc).join(" · ")}</p>` : ""}`;
}

$("#explain-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const prompt = $("#explain-prompt").value.trim();
  if (!prompt) return;
  const budget = +$("#explain-budget").value || 1500;
  $("#explain-out").innerHTML = '<p class="dim">running the pipeline…</p>';
  try {
    const t = await api(`api/explain?${new URLSearchParams({ prompt, budget })}`);
    $("#explain-out").innerHTML = explainHTML(t);
  } catch (e) {
    $("#explain-out").innerHTML = `<p class="dim">explain failed: ${esc(e.message)}</p>`;
  }
});

/* ---------- sessions (console › sessions) ---------- */
async function loadSessions() {
  const data = await api("api/sessions");
  const rows = state.env
    ? data.items.filter((s) => !s.environment || s.environment === state.env)
    : data.items;
  $("#sessions-body").innerHTML = rows.map((s) => `<tr>
    <td>${esc(s.id).slice(0, 18)}…</td>
    <td class="status-${esc(s.status)}">${esc(s.status)}</td>
    <td>${timeago(s.started_at)}</td>
    <td class="num">${esc(String(s.prompt_count ?? 0))}</td>
    <td class="num">${esc(String(s.observations_written ?? 0))}</td>
    <td>${s.gate_blocked ? "blocked once" : "—"}</td>
  </tr>`).join("");
}

/* ---------- stats ---------- */
function bars(el, counts, crimsonKeys = []) {
  const max = Math.max(1, ...Object.values(counts));
  el.innerHTML = Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, v]) =>
    `<div class="bar-row${crimsonKeys.includes(k) ? " crimson" : ""}">
      <span class="bar-name">${esc(typeLabel(k))}</span>
      <div class="bar-track"><div class="bar-fill" style="transform:scaleX(${v / max})"></div></div>
      <span class="bar-count">${v}</span>
    </div>`).join("");
}

async function loadStats() {
  const s = await api("api/stats");
  const cards = [
    [s.observations_stored, "observations"],
    [s.sessions, "sessions"],
    [s.events, "events captured"],
    [s.pending_events, "pending distillation"],
    [`~${(s.read_tokens / 1000).toFixed(1)}k`, "tokens to read all"],
  ];
  $("#stat-grid").innerHTML = cards.map(([v, l]) =>
    `<div class="stat-card"><div class="value">${v}</div><div class="label">${l}</div></div>`).join("");
  bars($("#type-bars"), s.by_type || {}, ["security", "root_cause"]);
  bars($("#importance-bars"), s.by_importance || {}, ["critical", "high"]);
}

/* ---------- settings ---------- */
async function loadSettings() {
  const s = await api("api/settings");
  const f = $("#settings-form");
  f.max_full.value = s.max_full;
  f.token_ceiling.value = s.token_ceiling;
  f.port.value = s.port;
  f.show_economics.checked = !!s.show_economics;
}
$("#settings-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  await api("api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      max_full: +f.max_full.value,
      token_ceiling: +f.token_ceiling.value,
      port: +f.port.value,
      show_economics: f.show_economics.checked,
    }),
  });
  $("#save-note").textContent = "saved";
  setTimeout(() => ($("#save-note").textContent = ""), 2500);
});

/* ---------- workflow view (n8n-style blocks over the knowledge graph) ---------- */
const wf = { data: null, vb: null, drag: null };

function wfLayers(nodes, edges) {
  /* deterministic layered layout: entry points (nothing imports them) sit on
     the left; foundations everything depends on drift right — reads as a flow */
  const ids = nodes.map((n) => n.id);
  const idset = new Set(ids);
  const into = new Map(ids.map((id) => [id, new Set()]));
  const outof = new Map(ids.map((id) => [id, new Set()]));
  edges.forEach((e) => {
    if (idset.has(e.src) && idset.has(e.dst)) {
      into.get(e.dst).add(e.src);
      outof.get(e.src).add(e.dst);
    }
  });
  const layer = new Map();
  const indeg = new Map(ids.map((id) => [id, into.get(id).size]));
  const queue = ids.filter((id) => indeg.get(id) === 0).sort();
  queue.forEach((id) => layer.set(id, 0));
  while (queue.length) {
    const id = queue.shift();
    for (const nxt of [...outof.get(id)].sort()) {
      layer.set(nxt, Math.max(layer.get(nxt) ?? 0, (layer.get(id) ?? 0) + 1));
      indeg.set(nxt, indeg.get(nxt) - 1);
      if (indeg.get(nxt) === 0) queue.push(nxt);
    }
  }
  ids.filter((id) => !layer.has(id)).sort()      // cycles / isolated blocks
     .forEach((id, i) => layer.set(id, 0));
  return layer;
}

const WF = { w: 200, h: 68, gapX: 300, gapY: 100, padX: 60, padY: 50 };

function wfLayout(data) {
  const layer = wfLayers(data.nodes, data.edges);
  const cols = new Map();
  data.nodes.forEach((n) => {
    const l = layer.get(n.id) ?? 0;
    if (!cols.has(l)) cols.set(l, []);
    cols.get(l).push(n);
  });
  [...cols.values()].forEach((col) => col.sort((a, b) => a.id.localeCompare(b.id)));
  for (const [l, col] of cols) {
    col.forEach((n, i) => {
      n.x = WF.padX + l * WF.gapX;
      n.y = WF.padY + i * WF.gapY;
    });
  }
  const maxL = Math.max(0, ...cols.keys());
  const maxRows = Math.max(1, ...[...cols.values()].map((c) => c.length));
  return { width: WF.padX * 2 + maxL * WF.gapX + WF.w,
           height: WF.padY * 2 + (maxRows - 1) * WF.gapY + WF.h };
}

function wfRender() {
  const svg = $("#workflow-svg");
  const data = wf.data;
  if (!data || !data.nodes.length) {
    $("#workflow-meta").innerHTML =
      'no graph yet — run <code>danza cortex index</code> first';
    svg.innerHTML = "";
    return;
  }
  const dims = wfLayout(data);
  if (!wf.vb) wf.vb = { x: 0, y: 0, w: dims.width, h: Math.max(dims.height, 400) };
  const byId = new Map(data.nodes.map((n) => [n.id, n]));
  const paths = data.edges.map((e) => {
    const s = byId.get(e.src), t = byId.get(e.dst);
    if (!s || !t) return "";
    const x1 = s.x + WF.w, y1 = s.y + WF.h / 2;
    const x2 = t.x, y2 = t.y + WF.h / 2;
    const dx = Math.max(40, (x2 - x1) / 2);
    const width = Math.min(5, 1 + Math.log2(e.weight + 1));
    return `<path class="wf-edge" style="stroke-width:${width}"
      d="M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}">
      <title>${esc(e.src)} → ${esc(e.dst)} · ${e.weight} imports</title></path>`;
  }).join("");
  const blocks = data.nodes.map((n) => `
    <g class="wf-node" data-id="${esc(n.id)}" transform="translate(${n.x},${n.y})">
      <rect width="${WF.w}" height="${WF.h}" rx="8"></rect>
      <rect class="wf-accent" width="4" height="${WF.h}" rx="2"></rect>
      <text class="wf-title" x="16" y="28">${esc(n.label)}</text>
      <text class="wf-sub" x="16" y="50">${n.file_count} files${
        n.observations ? ` · ${n.observations} memories` : ""}</text>
    </g>`).join("");
  svg.setAttribute("viewBox", `${wf.vb.x} ${wf.vb.y} ${wf.vb.w} ${wf.vb.h}`);
  svg.innerHTML = paths + blocks;
  $("#workflow-meta").textContent =
    `${data.nodes.length} blocks · ${data.edges.length} flows — ` +
    `scroll to zoom, drag to pan, click a block for its files`;
}

async function loadWorkflow() {
  if (!wf.data) wf.data = await api("api/workflow");
  wfRender();
}

/* zoom (wheel) + pan (drag) on the workflow canvas */
$("#workflow-svg").addEventListener("wheel", (ev) => {
  if (!wf.vb) return;
  ev.preventDefault();
  const svg = $("#workflow-svg");
  const rect = svg.getBoundingClientRect();
  const mx = wf.vb.x + (ev.clientX - rect.left) / rect.width * wf.vb.w;
  const my = wf.vb.y + (ev.clientY - rect.top) / rect.height * wf.vb.h;
  const k = ev.deltaY > 0 ? 1.15 : 1 / 1.15;
  wf.vb = { x: mx - (mx - wf.vb.x) * k, y: my - (my - wf.vb.y) * k,
            w: wf.vb.w * k, h: wf.vb.h * k };
  svg.setAttribute("viewBox", `${wf.vb.x} ${wf.vb.y} ${wf.vb.w} ${wf.vb.h}`);
}, { passive: false });

$("#workflow-svg").addEventListener("mousedown", (ev) => {
  if (ev.target.closest(".wf-node")) return;
  wf.drag = { x: ev.clientX, y: ev.clientY, vb: { ...wf.vb } };
});
window.addEventListener("mousemove", (ev) => {
  if (!wf.drag) return;
  const svg = $("#workflow-svg");
  const rect = svg.getBoundingClientRect();
  wf.vb.x = wf.drag.vb.x - (ev.clientX - wf.drag.x) / rect.width * wf.vb.w;
  wf.vb.y = wf.drag.vb.y - (ev.clientY - wf.drag.y) / rect.height * wf.vb.h;
  svg.setAttribute("viewBox", `${wf.vb.x} ${wf.vb.y} ${wf.vb.w} ${wf.vb.h}`);
});
window.addEventListener("mouseup", () => (wf.drag = null));

$("#workflow-reset").addEventListener("click", () => { wf.vb = null; wfRender(); });

$("#workflow-svg").addEventListener("click", (ev) => {
  const g = ev.target.closest(".wf-node");
  if (!g || !wf.data) return;
  const n = wf.data.nodes.find((x) => x.id === g.dataset.id);
  if (!n) return;
  $("#node-panel-body").innerHTML = `
    <h2>${esc(n.label)}</h2>
    <p class="dim mono">${esc(n.id)}</p>
    <p>${n.file_count} files${n.observations ? ` · ${n.observations} attached memories` : ""}</p>
    <h3 class="section-label">Files in this block</h3>
    <ul class="files">${n.files.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>`;
  $("#node-panel").hidden = false;
});
$("#node-panel-close").addEventListener("click", () => ($("#node-panel").hidden = true));

/* ---------- live (SSE) ---------- */
function pulse() {
  const mark = $("#mark");
  mark.classList.remove("pulse");
  void mark.offsetWidth; // restart animation
  mark.classList.add("pulse");
}

function connectLive() {
  const es = new EventSource("api/events?stream=1");
  es.onopen = () => $("#live-dot").classList.add("connected");
  es.onmessage = () => refresh();
  es.onerror = () => {
    $("#live-dot").classList.remove("connected");
    es.close();
    setTimeout(connectLive, 5000);
  };
}

/* ---------- boot ---------- */
function refresh() {
  ({ feed: loadFeed, console: loadConsole, workflow: loadWorkflow,
     stats: loadStats, settings: loadSettings }[state.view] || loadFeed)();
}

(async function boot() {
  await loadMeta();
  refresh();
  connectLive();
})();
