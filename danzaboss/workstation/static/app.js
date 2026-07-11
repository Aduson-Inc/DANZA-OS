/* DANZA-OS dashboard — vanilla JS, no build step. Read-only over product
   state in Phase 2: OVERVIEW is live; ONBOARD / MODELS / BUILD render the
   real state files and gain their interactive surfaces in Phases 3-4. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path) {
  const res = await fetch(path);   // origin-relative: no leading slash
  if (!res.ok) throw new Error(`${res.status} on ${path}`);
  return res.json();
}

/* ---------- navigation ---------- */
const state = { view: "overview" };
$$(".tab[data-view]").forEach((b) => b.addEventListener("click", () => {
  $$(".tab").forEach((x) => x.classList.toggle("active", x === b));
  state.view = b.dataset.view;
  $$(".view").forEach((v) => (v.hidden = v.id !== `view-${state.view}`));
  refresh();
}));

/* ---------- shared render helpers ---------- */
const row = (k, v) => `<tr><td>${esc(k)}</td><td>${v}</td></tr>`;

const panel = (title, bodyHTML) =>
  `<div class="panel"><h2 class="panel-title">${esc(title)}</h2>${bodyHTML}</div>`;

/* ---------- overview ---------- */
function projectPanel(o) {
  return panel("Project", `<table class="kv">
    ${row("name", `<b>${esc(o.project)}</b>`)}
    ${row("root", `<span class="mono dim">${esc(o.root)}</span>`)}
    ${row("profile", `<span class="chip mono">${esc(o.profile.name)}</span>`)}
    ${row("spec", o.spec_exists ? "spec.md present"
                                : '<span class="dim">no spec.md yet</span>')}
  </table>`);
}

function teamPanel(o) {
  const t = o.team_state;
  if (!t) {
    const err = o.team_state_error
      ? `<p class="warn mono">${esc(o.team_state_error)}</p>` : "";
    return panel("Team state", `<p class="dim">Not activated — no
      team-state.json. Run <code>danza init</code> in this repo.</p>${err}`);
  }
  return panel("Team state", `<table class="kv">
    ${row("boss", `<b>${esc(t.current_boss)}</b>`)}
    ${row("turn", esc(t.turn_number))}
    ${row("status", `<span class="chip mono">${esc(t.status)}</span>`)}
    ${row("features this turn",
          `${esc(t.features_completed_this_turn)} / ${esc(t.max_features_per_turn)}`)}
    ${row("handoff required", t.handoff_required ? "yes" : "no")}
  </table>`);
}

function planPanel(o) {
  const p = o.plan;
  if (!p) return panel("Plan", `<p class="dim">No plan.json yet — finish
    onboarding and planning to arm the build.</p>`);
  if (p.error) return panel("Plan", `<p class="warn mono">${esc(p.error)}</p>`);
  return panel("Plan", `<table class="kv">
    ${row("spec", `<span class="mono dim">${esc(p.spec_ref)}</span>`)}
    ${row("tasks", esc(p.tasks))}
    ${row("dispatchable leaves", esc(p.leaves))}
    ${row("build order",
          `<span class="mono dim">${esc((p.order || []).join(" → "))}</span>`)}
  </table>`);
}

function cortexPanel(o) {
  const c = o.cortex;
  return panel("CORTEX memory", `<table class="kv">
    ${row("observations", `<b>${esc(c.observations_stored)}</b>`)}
    ${row("read tokens", `~${esc(c.read_tokens)}t`)}
    ${row("sessions", esc(c.sessions))}
    ${row("pending events", esc(c.pending_events))}
  </table>
  <p><a class="chip" href="cortex/">open CORTEX →</a></p>`);
}

function logLine(e) {
  const rest = Object.fromEntries(Object.entries(e)
    .filter(([k]) => k !== "ts" && k !== "event"));
  return `<div class="log-line">
    <span class="dim">${esc(e.ts || "")}</span>
    <b>${esc(e.event || "")}</b>
    <span class="dim">${esc(JSON.stringify(rest))}</span>
  </div>`;
}

async function loadOverview() {
  const o = await api("api/overview");
  $("#profile-chip").textContent = o.profile.name;
  $("#overview-grid").innerHTML =
    projectPanel(o) + teamPanel(o) + planPanel(o) + cortexPanel(o);
  const log = await api("api/conductor?limit=40");
  $("#conductor-log").innerHTML = log.items.length
    ? log.items.map(logLine).join("")
    : `<p class="dim">No conductor activity yet — start the relay with
       <code>danza conduct</code>.</p>`;
}

/* ---------- onboard (read-only until Phase 3) ---------- */
async function loadOnboard() {
  const o = await api("api/onboarding");
  const steps = o.steps.map((s) => `<tr>
      <td class="mono dim">${esc(s.id)}</td>
      <td>${esc(s.title)}</td>
      <td class="mono dim">${esc(s.kind)}</td>
      <td><span class="chip mono">${esc(s.status)}</span></td>
    </tr>`).join("");
  $("#onboard-panel").innerHTML = `<table class="kv">
    ${row("project type", esc(o.project_type ?? "not chosen yet"))}
    ${row("answers stored", esc(o.answered))}
    ${row("complete", o.complete ? "yes" : "no")}
  </table>
  <table class="sessions-table"><thead>
    <tr><th>step</th><th>title</th><th>kind</th><th>status</th></tr></thead>
    <tbody>${steps}</tbody></table>
  <p class="dim">Read-only view — dashboard onboarding forms land in Phase 3.</p>`;
}

/* ---------- models (read-only until Phase 4) ---------- */
async function loadModels() {
  const r = (await api("api/runners")).runners;
  if (!r) {
    $("#models-panel").innerHTML = `<p class="dim">No runner registry yet —
      run <code>danza runners .</code> to detect installed AI CLIs.</p>`;
    return;
  }
  if (r.error) {
    $("#models-panel").innerHTML = `<p class="warn mono">${esc(r.error)}</p>`;
    return;
  }
  $("#models-panel").innerHTML = `<table class="kv">
    ${row("boss", `<b>${esc(r.boss ?? "none detected")}</b>`)}
    ${row("session host", esc(r.session_host))}
    ${row("detected", r.detected.length
        ? r.detected.map((n) => `<span class="chip mono">${esc(n)}</span>`).join(" ")
        : '<span class="dim">none</span>')}
  </table>
  <p class="dim">Read-only view — lineup selection and the routing table land in Phase 4.</p>`;
}

/* ---------- build (read-only until Phase 4) ---------- */
function taskHTML(t) {
  const meta = [t.kind, t.size_est ? `${t.size_est}m` : "",
                (t.writes || []).join(", ")].filter(Boolean).map(esc).join(" · ");
  const verify = t.verified_by
    ? `<span class="dim mono">verify: ${esc(t.verified_by)}</span>` : "";
  const subs = (t.subtasks || []).map(taskHTML).join("");
  return `<li><span class="mono">${esc(t.id)}</span> ${esc(t.description)}
    <span class="dim">${meta}</span> ${verify}
    ${subs ? `<ul>${subs}</ul>` : ""}</li>`;
}

async function loadBuild() {
  const p = await api("api/plan");
  if (!p.plan) {
    $("#build-panel").innerHTML = `<p class="dim">No plan yet — the BUILD tab
      arms once onboarding compiles spec.md and planning writes plan.json.</p>`;
    return;
  }
  if (p.plan.error) {
    $("#build-panel").innerHTML = `<p class="warn mono">${esc(p.plan.error)}</p>`;
    return;
  }
  const tree = p.tree.length
    ? `<ul class="plan-tree">${p.tree.map(taskHTML).join("")}</ul>` : "";
  const md = p.plan_md ? `<h2 class="section-label">plan.md</h2>
    <pre class="plan-md mono">${esc(p.plan_md)}</pre>` : "";
  $("#build-panel").innerHTML = tree + md +
    `<p class="dim">Read-only view — relay start/stop controls land in Phase 4.</p>`;
}

/* ---------- refresh + SSE ---------- */
async function refresh() {
  try {
    if (state.view === "overview") await loadOverview();
    else if (state.view === "onboard") await loadOnboard();
    else if (state.view === "models") await loadModels();
    else if (state.view === "build") await loadBuild();
  } catch (e) {
    console.error(e);   // a failed poll must never kill the page
  }
}

function connectSSE() {
  const es = new EventSource("api/events");
  es.onopen = () => $("#live-dot").classList.add("connected");
  es.onerror = () => $("#live-dot").classList.remove("connected");
  es.onmessage = () => refresh();
}

refresh();
connectSSE();
