/* CORTEX dashboard — vanilla JS, no build step. Read-only over the store. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

const state = { view: "feed", q: "", type: "", items: [], knownIds: new Set(), firstLoad: true };

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

/* ---------- navigation ---------- */
$$(".nav-btn").forEach((b) => b.addEventListener("click", () => {
  $$(".nav-btn").forEach((x) => x.classList.toggle("active", x === b));
  state.view = b.dataset.view;
  $$(".view").forEach((v) => (v.hidden = v.id !== `view-${state.view}`));
  $("#drawer").hidden = true;
  refresh();
}));

/* ---------- feed ---------- */
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
      <span class="type-chip t-${esc(o.type)}">${esc(o.type).replace(/_/g, " ")}</span>
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
      <span>${esc(o.id)}</span><span>${timeago(o.updated)}</span>
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
$("#filters").addEventListener("click", (ev) => {
  const chip = ev.target.closest(".chip");
  if (!chip) return;
  $$(".chip").forEach((c) => c.classList.toggle("active", c === chip));
  state.type = chip.dataset.type;
  loadFeed();
});

let searchTimer;
$("#search").addEventListener("input", (ev) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = ev.target.value.trim();
    if (state.view !== "feed") $$(".nav-btn")[0].click();
    else loadFeed();
  }, 250);
});

async function loadFeed() {
  const params = new URLSearchParams({ limit: 100 });
  if (state.q) params.set("q", state.q);
  if (state.type) params.set("type", state.type);
  const data = await api(`/api/observations?${params}`);
  renderFeed(data.items);
}

/* ---------- drawer ---------- */
async function openDrawer(id) {
  const o = await api(`/api/observations/${id}`);
  const kv = (dt, dd) => dd ? `<dt>${dt}</dt><dd>${dd}</dd>` : "";
  const list = (arr, cls) => (arr && arr.length)
    ? `<ul class="${cls}">${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  const rel = (arr, cls) => (arr || []).map((x) => `<span class="rel-chip ${cls}">${esc(x)}</span>`).join("");
  const history = (o.history || []).map((h) =>
    `<div class="history-item"><span class="mono">${esc(h.ts || "")}</span> —
     ${esc(h.event || "")}${h.confidence ? ` (confidence → ${h.confidence})` : ""}</div>`).join("");
  $("#drawer-body").innerHTML = `
    <span class="type-chip t-${esc(o.type)}">${esc(o.type).replace(/_/g, " ")}</span>
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
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#drawer").hidden = true; });

/* ---------- explain playground ---------- */
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
    const t = await api(`/api/explain?${new URLSearchParams({ prompt, budget })}`);
    $("#explain-out").innerHTML = explainHTML(t);
  } catch (e) {
    $("#explain-out").innerHTML = `<p class="dim">explain failed: ${esc(e.message)}</p>`;
  }
});

/* ---------- sessions ---------- */
async function loadSessions() {
  const data = await api("/api/sessions");
  $("#sessions-body").innerHTML = data.items.map((s) => `<tr>
    <td>${esc(s.id).slice(0, 18)}…</td>
    <td class="status-${esc(s.status)}">${esc(s.status)}</td>
    <td>${timeago(s.started_at)}</td>
    <td class="num">${s.observations_written ? "" : ""}${esc(String(s.prompt_count ?? 0))}</td>
    <td class="num">${esc(String(s.observations_written ?? 0))}</td>
    <td>${s.gate_blocked ? "blocked once" : "—"}</td>
  </tr>`).join("");
}

/* ---------- stats ---------- */
function bars(el, counts, crimsonKeys = []) {
  const max = Math.max(1, ...Object.values(counts));
  el.innerHTML = Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, v]) =>
    `<div class="bar-row${crimsonKeys.includes(k) ? " crimson" : ""}">
      <span class="bar-name">${esc(k).replace(/_/g, " ")}</span>
      <div class="bar-track"><div class="bar-fill" style="transform:scaleX(${v / max})"></div></div>
      <span class="bar-count">${v}</span>
    </div>`).join("");
}

async function loadStats() {
  const s = await api("/api/stats");
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
  const s = await api("/api/settings");
  const f = $("#settings-form");
  f.max_full.value = s.max_full;
  f.token_ceiling.value = s.token_ceiling;
  f.port.value = s.port;
  f.show_economics.checked = !!s.show_economics;
}
$("#settings-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  await api("/api/settings", {
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

/* ---------- graph explorer (C4) ---------- */
const gstate = { mode: "neighborhood", center: null };

$$("#graph-form .mode-btn").forEach((b) => b.addEventListener("click", () => {
  $$("#graph-form .mode-btn").forEach((x) => x.classList.toggle("active", x === b));
  gstate.mode = b.dataset.gmode;
  if (gstate.center) exploreNode(gstate.center);
}));

$("#graph-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const text = $("#graph-node").value.trim();
  if (!text) return;
  const data = await api(`/api/graph?${new URLSearchParams({ q: text })}`);
  $("#graph-matches").innerHTML = (data.matches || []).map((m) =>
    `<button type="button" class="tag graph-match" data-id="${esc(m.id)}">
       ${esc(m.kind)}: ${esc(m.name)}</button>`).join(" ") ||
    '<span class="dim">no matching nodes — run <code>danza cortex index</code></span>';
});

$("#graph-matches").addEventListener("click", (ev) => {
  const b = ev.target.closest(".graph-match");
  if (b) exploreNode(b.dataset.id);
});

async function exploreNode(id) {
  gstate.center = id;
  const depth = +$("#graph-depth").value || 2;
  const data = await api(`/api/graph?${new URLSearchParams(
    { node: id, depth, mode: gstate.mode })}`);
  $("#graph-meta").textContent = gstate.mode === "impact"
    ? `${data.nodes.length - 1} nodes break if ${id} changes (depth ${depth})`
    : `${data.nodes.length} nodes · ${data.edges.length} edges (depth ${depth})`;
  renderGraph(data);
}

function layoutGraph(nodes, edges, w, h) {
  // deterministic: seeded on a circle, relaxed with repulsion + springs
  nodes.forEach((n, i) => {
    const a = (2 * Math.PI * i) / nodes.length;
    n.x = w / 2 + Math.cos(a) * h / 3;
    n.y = h / 2 + Math.sin(a) * h / 3;
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  for (let it = 0; it < 200; it++) {
    for (const a of nodes) {                       // pairwise repulsion
      for (const b of nodes) {
        if (a === b) continue;
        const dx = a.x - b.x, dy = a.y - b.y;
        const d2 = Math.max(64, dx * dx + dy * dy);
        a.x += (dx / d2) * 900; a.y += (dy / d2) * 900;
      }
    }
    for (const e of edges) {                       // spring along edges
      const s = byId.get(e.src), t = byId.get(e.dst);
      if (!s || !t) continue;
      const dx = t.x - s.x, dy = t.y - s.y;
      const d = Math.max(1, Math.hypot(dx, dy));
      const f = (d - 110) / d * 0.02;
      s.x += dx * f; s.y += dy * f; t.x -= dx * f; t.y -= dy * f;
    }
    for (const n of nodes) {                       // gravity + bounds
      n.x += (w / 2 - n.x) * 0.005; n.y += (h / 2 - n.y) * 0.005;
      n.x = Math.min(w - 30, Math.max(30, n.x));
      n.y = Math.min(h - 20, Math.max(20, n.y));
    }
  }
}

function renderGraph(data) {
  const svg = $("#graph-svg");
  const w = svg.clientWidth || 900, h = 640;
  const nodes = data.nodes.map((n) => ({ ...n }));
  layoutGraph(nodes, data.edges, w, h);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const lines = data.edges.map((e) => {
    const s = byId.get(e.src), t = byId.get(e.dst);
    if (!s || !t) return "";
    return `<line class="gedge r-${esc(e.relation)}" x1="${s.x}" y1="${s.y}"
      x2="${t.x}" y2="${t.y}"><title>${esc(e.src)} —${esc(e.relation)}→ ${esc(e.dst)}</title></line>`;
  }).join("");
  const dots = nodes.map((n) => {
    const center = n.id === data.center ? " center" : "";
    const label = n.name.length > 28 ? "…" + n.name.slice(-27) : n.name;
    return `<g class="gnode k-${esc(n.kind)}${center}" data-id="${esc(n.id)}"
        transform="translate(${n.x},${n.y})">
      <circle r="${n.id === data.center ? 9 : 6}"><title>${esc(n.id)}</title></circle>
      <text x="10" y="4">${esc(label)}</text></g>`;
  }).join("");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.innerHTML = lines + dots;
}

$("#graph-svg").addEventListener("click", (ev) => {
  const g = ev.target.closest(".gnode");
  if (g) exploreNode(g.dataset.id);
});

async function loadGraph() {
  if (gstate.center) return;                       // keep the current view
  const data = await api("/api/graph");
  $("#graph-meta").textContent =
    `${data.stats.nodes} nodes · ${data.stats.edges} edges — search above, or click a hub`;
  $("#graph-matches").innerHTML = (data.top || []).map((m) =>
    `<button type="button" class="tag graph-match" data-id="${esc(m.id)}">
       ${esc(m.kind)}: ${esc(m.name)} (${m.degree})</button>`).join(" ");
}

/* ---------- live (SSE) ---------- */
function pulse() {
  const mark = $("#mark");
  mark.classList.remove("pulse");
  void mark.offsetWidth; // restart animation
  mark.classList.add("pulse");
}

function connectLive() {
  const es = new EventSource("/api/events?stream=1");
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
  ({ feed: loadFeed, sessions: loadSessions, stats: loadStats,
     settings: loadSettings, explain: () => {},
     graph: loadGraph }[state.view] || loadFeed)();
}

(async function boot() {
  try {
    const s = await api("/api/stats");
    $("#project-name").textContent = s.project || "";
  } catch { /* stats are cosmetic at boot */ }
  refresh();
  connectLive();
})();
