/* DANZA-OS dashboard — vanilla JS, no build step. One linear journey:
   Connect -> Describe -> Approve -> Build -> Done, driven by /api/flow.
   Completed stages collapse to a summary row; the current stage stays open;
   future stages stay locked. Advanced/rarely-used controls live behind the
   one Advanced drawer. */
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

async function post(path, body) {
  const res = await fetch(path, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} on ${path}`);
  return data;
}

/* ---------- shared render helpers ---------- */
const row = (k, v) => `<tr><td>${esc(k)}</td><td>${v}</td></tr>`;

const panel = (title, bodyHTML) =>
  `<div class="panel"><h2 class="panel-title">${esc(title)}</h2>${bodyHTML}</div>`;

function logLine(e) {
  const rest = Object.fromEntries(Object.entries(e)
    .filter(([k]) => k !== "ts" && k !== "event"));
  return `<div class="log-line">
    <span class="dim">${esc(e.ts || "")}</span>
    <b>${esc(e.event || "")}</b>
    <span class="dim">${esc(JSON.stringify(rest))}</span>
  </div>`;
}

/* ---------- the one merged team list (/api/flow team) ----------
   Single source of truth for who's on the team, who's live, and whose turn
   it is — no separate active/waiting widgets, no duplicate runner-name map.
   friendlyEvent() below looks runner display names up here too. */
let flowData = null;   // last /api/flow payload

function teamDisplayName(runnerId) {
  const member = (flowData?.team || []).find((m) => m.runner === runnerId);
  return member ? member.display_name : (runnerId || "the next AI");
}

function teamStripHTML(team) {
  if (!team || !team.length)
    return `<p class="dim">No team confirmed yet — connect and verify an AI
      client to build one.</p>`;
  return `<ul class="team-list">${team.map((m) => `
    <li class="team-member ${m.active ? "team-active" : "team-waiting"}">
      <span class="team-dot ${m.live ? "team-live" : ""}" title="${m.live ? "live" : "not connected"}"></span>
      <b>${esc(m.display_name)}</b>
      <span class="mono dim">${m.active ? "taking this turn" : "waiting"}</span>
    </li>`).join("")}</ul>`;
}

/* ---------- one merged feature-list editor ----------
   Both Approve's product scope and Build's additions edit the same shape:
   [{id, summary, acceptance_criteria, status}]. One card renderer, one
   collector, one seed function — no duplicate editors. */
function blankFeature(id) {
  return { id, summary: "", acceptance_criteria: [""], status: "pending" };
}

function featureCardHTML(feature, editable, canRemove) {
  const remove = editable && canRemove
    ? `<button type="button" class="chip remove-feature"
       data-feature-id="${esc(feature.id)}">Remove</button>` : "";
  const summary = editable
    ? `<input type="text" name="summary" maxlength="300"
       value="${esc(feature.summary)}" placeholder="One or two concise sentences">`
    : `<p>${esc(feature.summary)}</p>`;
  const criteria = editable
    ? `<textarea name="criteria" rows="3" placeholder="One acceptance criterion per line">${esc(feature.acceptance_criteria.join("\n"))}</textarea>`
    : `<ul>${feature.acceptance_criteria.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`;
  return `<article class="feature-card" data-feature-id="${esc(feature.id)}"
    data-status="${esc(feature.status)}">
    <div class="feature-card-head"><b>Feature ${esc(feature.id)}</b>
      <span class="chip mono">${esc(feature.status)}</span>${remove}</div>
    <div class="field"><label>Concise product feature</label>${summary}</div>
    <details><summary>Acceptance criteria</summary>
      <div class="field">${criteria}</div></details></article>`;
}

function newFeatureEditor() {
  return { features: null, revision: null, dirty: false };
}

function seedFeatureEditor(ed, features, revision, blankId) {
  if (ed.features !== null && (ed.dirty || ed.revision === revision)) return;
  ed.features = features ? features.map((f) => ({ ...f,
    acceptance_criteria: [...f.acceptance_criteria] })) : [blankFeature(blankId)];
  ed.revision = revision;
  ed.dirty = false;
}

function collectFeatureEditor(containerEl) {
  return $$(".feature-card", containerEl).map((card) => ({
    id: Number(card.dataset.featureId),
    summary: $("[name=summary]", card).value.trim(),
    acceptance_criteria: $("[name=criteria]", card).value.split("\n")
      .map((line) => line.trim()).filter(Boolean),
    status: card.dataset.status,
  }));
}

function featureEditorHTML(ed, editable) {
  return ed.features.map((f) =>
    featureCardHTML(f, editable, ed.features.length > 1)).join("");
}

/* ---------- flow rail + stage shells ---------- */
const STAGES = [
  { id: "connect", title: "Connect", blurb: "Confirm the AI clients on your team." },
  { id: "describe", title: "Describe", blurb: "Tell DANZABOSS what you're building." },
  { id: "approve", title: "Approve", blurb: "Review and approve the product scope." },
  { id: "build", title: "Build", blurb: "Your AI team builds the approved plan." },
  { id: "done", title: "Done", blurb: "Every product feature is complete." },
];
const stageIndex = (id) => STAGES.findIndex((s) => s.id === id);

const ui = { expanded: new Set(), lastCurrent: null, stagesBuilt: false };

function ensureStageShells() {
  if (ui.stagesBuilt) return;
  $("#stages").innerHTML = STAGES.map((s, i) => `
    <section class="stage-card" id="stage-${s.id}" data-stage="${s.id}">
      <button type="button" class="stage-header" data-toggle="${s.id}">
        <span class="stage-num">${i + 1}</span>
        <span class="stage-title-group">
          <span class="stage-title">${esc(s.title)}</span>
          <span class="stage-blurb dim">${esc(s.blurb)}</span>
        </span>
        <span class="stage-chip chip mono" id="stage-chip-${s.id}"></span>
        <span class="stage-chevron" aria-hidden="true">&#9662;</span>
      </button>
      <div class="stage-summary dim" id="stage-summary-${s.id}"></div>
      <div class="stage-body" id="stage-body-${s.id}" hidden></div>
    </section>`).join("");
  ui.stagesBuilt = true;
  $$('[data-toggle]').forEach((btn) => btn.addEventListener("click", () =>
    toggleStage(btn.dataset.toggle)));
}

function toggleStage(id) {
  const idx = stageIndex(id);
  const currentIdx = stageIndex(flowData.current);
  if (idx > currentIdx) return;               // locked — nothing to open
  if (idx === currentIdx) return;              // current stage is always open
  if (ui.expanded.has(id)) {
    ui.expanded.delete(id);
    renderStageState(id);
    return;
  }
  ui.expanded.add(id);
  renderStageState(id);
  loadStageDetail(id);
}

function stageSummaryHTML(stage) {
  const s = flowData.stages.find((x) => x.id === stage.id);
  switch (stage.id) {
    case "connect":
      return s.complete ? "Team confirmed and connected." : "Not connected yet.";
    case "describe":
      return s.complete ? "Project brief written." : "Describing the project…";
    case "approve":
      return s.complete
        ? `Scope revision ${esc(s.revision)} approved · build plan ready.`
        : s.scope_state ? `Scope ${esc(s.scope_state)} — not approved yet.`
        : "No scope drafted yet.";
    case "build":
      return s.complete
        ? `All ${esc(s.total)} product features complete.`
        : s.total ? `${esc(s.completed)} / ${esc(s.total)} product features complete.`
        : "Waiting for an approved plan.";
    case "done":
      return "Build complete.";
    default:
      return "";
  }
}

function renderStageState(id) {
  const idx = stageIndex(id);
  const currentIdx = stageIndex(flowData.current);
  const card = $(`#stage-${id}`);
  const complete = flowData.stages.find((x) => x.id === id)?.complete
    || (id === "done" && flowData.current === "done");
  const isCurrent = idx === currentIdx;
  const locked = idx > currentIdx;
  const open = isCurrent || ui.expanded.has(id);
  card.classList.toggle("stage-locked", locked);
  card.classList.toggle("stage-current", isCurrent);
  card.classList.toggle("stage-done", complete && !isCurrent);
  card.classList.toggle("stage-open", open);
  $(`#stage-chip-${id}`).textContent =
    locked ? "Locked" : complete ? "Done" : isCurrent ? "In progress" : "Pending";
  $(`#stage-summary-${id}`).innerHTML = locked
    ? `Finish ${esc(STAGES[currentIdx] ? STAGES[currentIdx].title : "the previous stage")} first.`
    : stageSummaryHTML(STAGES[idx]);
  $(`#stage-summary-${id}`).hidden = open;
  const body = $(`#stage-body-${id}`);
  body.hidden = !open;
}

function renderFlow() {
  const currentIdx = stageIndex(flowData.current);
  $("#flow-rail").innerHTML = STAGES.map((s, i) => {
    const cls = i < currentIdx || flowData.current === "done" ? "done"
      : i === currentIdx ? "active" : "";
    return `<div class="rail-step ${cls}"><span>${i + 1}</span><b>${esc(s.title)}</b></div>`;
  }).join("");
  $("#team-strip").innerHTML = teamStripHTML(flowData.team);
  ensureStageShells();
  STAGES.forEach((s) => renderStageState(s.id));
  if (ui.lastCurrent !== flowData.current) {
    ui.expanded.add(ui.lastCurrent);           // leaving a stage keeps it reviewable
    ui.lastCurrent = flowData.current;
    loadStageDetail(flowData.current);
  } else {
    loadCurrentStageDetail();
  }
}

function loadStageDetail(id) {
  switch (id) {
    case "connect": return loadConnect();
    case "describe": return loadDescribe();
    case "approve": return loadApprove();
    case "build": return loadBuild();
    case "done": return loadDone();
  }
}

// the current stage polls on every refresh tick (SSE or interval); a
// manually expanded past stage loads once on click and is left alone
function loadCurrentStageDetail() {
  return loadStageDetail(flowData.current);
}

/* ================= CONNECT — confirm your AI team ================= */
let setupData = null;
const setup = { pick: null, error: "", notice: "", fallback: "", busy: false };

function initPick(s) {
  return { lineup: Array.isArray(s.lineup) ? [...s.lineup] : [],
    features_per_turn: s.features_per_turn };
}

function agentChip(a) {
  const labels = {
    verified: ["Ready", "chip-ok"],
    needs_sign_in: ["Needs sign-in", "chip-bad"],
    verification_unavailable: ["Check unavailable", "chip-dim"],
    not_installed: ["Not installed", "dim"],
  };
  const [label, cls] = labels[a.state] || ["Not checked", "chip-dim"];
  return `<span class="chip mono ${cls}">${label}</span>`;
}

function agentInstruction(a) {
  switch (a.state) {
    case "verified": return "Verified. You can add this client to the boss order.";
    case "needs_sign_in": return "Open it, complete the provider sign-in, then press Verify.";
    case "verification_unavailable": return "Installed, but this provider has no safe status check yet.";
    case "not_installed": return "Install this client first, then refresh this page.";
    default: return "DANZABOSS has not checked this client yet.";
  }
}

function agentCard(a, pick) {
  const selected = pick.lineup.includes(a.name);
  const canSelect = a.state === "verified";
  const launch = a.detected
    ? `<button class="connect-button" data-launch-boss="${esc(a.name)}">Connect</button>` : "";
  const verify = a.detected
    ? `<button class="chip" data-verify-boss="${esc(a.name)}">${a.state === "verified" ? "Verify again" : "Verify"}</button>` : "";
  return `<div class="agent-card state-${esc(a.state || "unknown")}${a.detected ? "" : " dim"}">
    <div class="agent-head"><b>${esc(a.display_name)}</b>${agentChip(a)}</div>
    <p class="dim">${esc(a.strengths || "")}</p>
    <p class="agent-instruction">${agentInstruction(a)}</p>
    <div class="agent-actions">
      <label class="boss-toggle">
        <input type="checkbox" data-boss-select="${esc(a.name)}"
          ${selected ? "checked" : ""}${canSelect ? "" : " disabled"}>
        ${selected ? "In boss order" : "Add to boss order"}
      </label><div class="boss-actions">${launch}${verify}</div>
    </div></div>`;
}

function agentDisplay(name, agents) {
  return (agents.find((a) => a.name === name) || { display_name: name }).display_name;
}

function lineupPickerHTML(pick, agents) {
  if (!pick.lineup.length)
    return `<div class="boss-empty"><b>No clients chosen yet.</b>
      <span>Verify an AI client above, then add it to the order.</span></div>`;
  return `<ol class="boss-lineup">${pick.lineup.map((name, index) => `
    <li class="boss-card">
      <div class="boss-rank">${index + 1}</div>
      <div class="boss-card-copy"><b>${esc(agentDisplay(name, agents))}</b></div>
      <div class="boss-controls">
        <button class="chip" data-move-boss="up" data-boss-name="${esc(name)}"
          ${index === 0 ? "disabled" : ""}>&uarr;</button>
        <button class="chip" data-move-boss="down" data-boss-name="${esc(name)}"
          ${index === pick.lineup.length - 1 ? "disabled" : ""}>&darr;</button>
      </div>
    </li>`).join("")}</ol>`;
}

function workspacePanel(s) {
  const w = s.workspace || { host: "unconfigured", order: [] };
  const order = Array.isArray(w.order) ? w.order : [];
  if (w.host === "unconfigured")
    return panel("Shared workspace", `<p class="dim">Connect a client to
      open one shared terminal for your whole team.</p>`);
  const rows = order.map((name, index) => `<li class="workspace-pane
      ${name === w.active_runner ? "workspace-active" : "workspace-waiting"}">
      <b>${index + 1}. ${esc(agentDisplay(name, s.agents))}</b></li>`).join("");
  const open = w.host === "tmux"
    ? `<button id="open-workspace" class="chip">Open workspace</button>
       <code class="workspace-attach">${esc(w.attach_command || "")}</code>`
    : `<span class="workspace-fallback">Native terminals — no shared panes.</span>`;
  return panel("Shared workspace", `<div class="workspace-panel">
    <div class="workspace-head"><b>${esc(w.session || "")}</b></div>
    <ol class="workspace-panes">${rows}</ol>
    <div class="workspace-actions">${open}</div></div>`);
}

function renderConnect() {
  const s = setupData;
  const pick = setup.pick;
  const agentsPanel = panel("Connect and verify AI clients",
    `<div class="agent-grid">${s.agents.map((a) => agentCard(a, pick)).join("")}</div>
     <p class="setup-help"><b>Do this first:</b> press Connect, finish
       sign-in in the client's own window, return here, and press Verify.</p>`);
  const liveMessage = setup.error
    ? `<p class="warn mono">${esc(setup.error)}</p>`
    : setup.notice ? `<p class="ok">${esc(setup.notice)}</p>`
    : setup.busy ? `<p class="dim">Working…</p>`
    : `<p class="dim">Waiting for your first connection.</p>`;
  const fallback = setup.fallback
    ? `<details class="connection-fallback"><summary>Terminal fallback</summary><code>${esc(setup.fallback)}</code></details>` : "";
  const live = `<div class="setup-live-status ${setup.error ? "is-error" : ""}">
      ${liveMessage}${fallback}
      ${s.routing_error ? `<p class="warn mono">${esc(s.routing_error)}</p>` : ""}</div>`;
  const hasOrder = pick.lineup.length > 0;
  const lineup = panel("Choose the boss order",
    `<div id="boss-lineup">${lineupPickerHTML(pick, s.agents)}</div>
     <p class="setup-order-note">Use the arrows to set the turn order — the
       first client builds first; the rest wait their turn.</p>
     <div class="boss-feature-choice">
       <label for="features-per-turn">Features per turn</label>
       <select id="features-per-turn">
         <option value="2"${pick.features_per_turn === 2 ? " selected" : ""}>2 recommended</option>
         <option value="3"${pick.features_per_turn === 3 ? " selected" : ""}>3</option>
         <option value="4"${pick.features_per_turn === 4 ? " selected" : ""}>4</option>
         <option value="5"${pick.features_per_turn === 5 ? " selected" : ""}>5</option>
       </select>
       <span>Choose 2-5 verified features per turn.</span>
     </div>
     <button id="confirm-team" class="boss-confirm"${hasOrder ? "" : " disabled"}>Save boss order and continue</button>`);
  $("#stage-body-connect").innerHTML = agentsPanel + live + workspacePanel(s) + lineup;
  wireConnect();
}

async function connectAction(fn) {
  if (setup.busy) return;
  setup.busy = true;
  setup.error = "";
  setup.notice = "";
  renderConnect();
  try {
    const out = await fn();
    setupData = out.setup;
    setup.pick = initPick(setupData);
    if (!setup.notice) setup.notice = "Boss order saved.";
  } catch (e) {
    setup.error = e.message;
  }
  setup.busy = false;
  renderConnect();
}

function wireConnect() {
  const pick = setup.pick;
  const features = $("#features-per-turn");
  if (features) features.addEventListener("change", () => {
    pick.features_per_turn = Number(features.value);
    renderConnect();
  });
  $$('[data-boss-select]').forEach((box) => box.addEventListener("change", () => {
    const name = box.dataset.bossSelect;
    if (box.checked && !pick.lineup.includes(name)) pick.lineup.push(name);
    if (!box.checked) pick.lineup = pick.lineup.filter((item) => item !== name);
    renderConnect();
  }));
  $$('[data-move-boss]').forEach((button) => button.addEventListener("click", () => {
    const index = pick.lineup.indexOf(button.dataset.bossName);
    const next = button.dataset.moveBoss === "up" ? index - 1 : index + 1;
    if (index < 0 || next < 0 || next >= pick.lineup.length) return;
    [pick.lineup[index], pick.lineup[next]] = [pick.lineup[next], pick.lineup[index]];
    renderConnect();
  }));
  const launchRunner = (runner) => connectAction(async () => {
    const out = await post("api/connection/launch", { runner });
    setupData = out.setup;
    setup.pick = initPick(setupData);
    const agent = setupData.agents.find((a) => a.name === runner);
    const name = agent ? agent.display_name : runner;
    setup.notice = out.launch.terminal && out.launch.terminal.opened
      ? `${name} is open in a new terminal. Finish sign-in there, then return and press Verify.`
      : `${name} is ready. Open the client in your terminal, finish sign-in, then return and press Verify.`;
    setup.fallback = out.launch.terminal && !out.launch.terminal.opened
      ? (out.launch.attach_command || "") : "";
    return { setup: setupData };
  });
  const verifyRunner = (runner) => connectAction(async () => {
    const out = await post("api/connection/verify", { runner });
    setupData = await api("api/setup");
    setup.pick = initPick(setupData);
    setup.notice = out.installation && out.installation.status === "verified"
      ? "Installation verified — UI, CORTEX, project, and AI connection are working."
      : "AI connection verified.";
    return { setup: setupData };
  });
  $$('[data-launch-boss]').forEach((button) => button.addEventListener("click", () =>
    launchRunner(button.dataset.launchBoss)));
  $$('[data-verify-boss]').forEach((button) => button.addEventListener("click", () =>
    verifyRunner(button.dataset.verifyBoss)));
  const confirm = $("#confirm-team");
  if (confirm) confirm.addEventListener("click", () => {
    if (!pick.lineup.length) {
      setup.error = "pick at least one agent before confirming";
      return renderConnect();
    }
    if (pick.lineup.length > 4) {
      setup.error = "the boss rotation holds at most 4 models";
      return renderConnect();
    }
    connectAction(() => post("api/setup",
      { lineup: pick.lineup, features_per_turn: pick.features_per_turn }));
  });
  const openWorkspace = $("#open-workspace");
  if (openWorkspace) openWorkspace.addEventListener("click", () =>
    connectAction(async () => {
      const out = await post("api/workspace/open", {});
      setup.notice = out.terminal.opened
        ? "Workspace opened."
        : `Use ${out.workspace.attach_command || "the terminal fallback"}.`;
      return { setup: out.setup };
    }));
}

async function loadConnect() {
  const bodyEl = $("#stage-body-connect");
  if (setup.busy || (bodyEl && bodyEl.contains(document.activeElement))) return;
  setupData = await api("api/setup");
  if (!setup.pick) setup.pick = initPick(setupData);
  renderConnect();
}

/* ================= DESCRIBE — discovery, interview, project brief ===== */
let onboardData = null;
let projectData = null;
const onboard = { edit: null, error: "", busy: false };
const describeUI = { error: "", notice: "", busy: false };

function showIfMet(q, values) {
  return (q.show_if || []).every(([qid, ok]) => ok.includes(values[qid]));
}

function liveValues(step) {
  const values = {};
  for (const q of step.questions) if (q.value != null) values[q.id] = q.value;
  return values;
}

function fieldHTML(q) {
  const val = q.value ?? q.default ?? "";
  const opt = q.required ? "" : ' <span class="dim">(optional)</span>';
  let control;
  if (q.kind === "choice") {
    const opts = q.options.map((o) =>
      `<option value="${esc(o)}"${o === val ? " selected" : ""}>${esc(o)}</option>`).join("");
    control = `<select name="${esc(q.id)}">${val ? ""
      : '<option value="" selected disabled>choose…</option>'}${opts}</select>`;
  } else if (q.kind === "multi") {
    const set = Array.isArray(q.value) ? q.value : [];
    control = q.options.map((o) => `<label class="check">
      <input type="checkbox" name="${esc(q.id)}" value="${esc(o)}"
      ${set.includes(o) ? "checked" : ""}> ${esc(o)}</label>`).join("");
  } else if (q.kind === "longtext") {
    control = `<textarea name="${esc(q.id)}" rows="3">${esc(val)}</textarea>`;
  } else if (q.kind === "list" || q.kind === "uploads") {
    const text = Array.isArray(q.value) ? q.value.join("\n") : "";
    control = `<textarea name="${esc(q.id)}" rows="3"
      placeholder="one per line">${esc(text)}</textarea>`;
  } else {
    control = `<input type="text" name="${esc(q.id)}" value="${esc(val)}">`;
  }
  return `<div class="field"><label>${esc(q.prompt)}${opt}</label>${control}</div>`;
}

function collectAnswers(step) {
  const values = {};
  const form = $("#onboard-form");
  for (const q of step.questions) {
    const els = $$(`[name="${q.id}"]`, form);
    if (!els.length) continue;                 // hidden by show_if
    if (q.kind === "multi") {
      const picked = els.filter((e) => e.checked).map((e) => e.value);
      if (picked.length || q.required) values[q.id] = picked;
    } else if (q.kind === "list" || q.kind === "uploads") {
      const items = els[0].value.split("\n").map((s) => s.trim()).filter(Boolean);
      if (items.length) values[q.id] = items;
    } else if (els[0].value !== "") {
      values[q.id] = els[0].value;
    }
  }
  return values;
}

function formPanel(step) {
  const values = liveValues(step);
  const fields = step.questions.filter((q) => showIfMet(q, values))
    .map(fieldHTML).join("");
  return panel(step.title, `<form id="onboard-form" data-step="${esc(step.id)}">
    ${fields}<button type="submit" class="chip">Submit ${esc(step.id)}</button></form>`);
}

function grillChip(rec) {
  if (!rec) return "";
  const label = rec.resolution ? "you decided" : rec.degraded ? "not AI-checked"
    : rec.needs_user_decision ? "needs you" : rec.clear ? "clear"
    : `round ${rec.rounds.length}/3`;
  const tone = rec.clear || rec.resolution ? "" : " warn-chip";
  return ` <span class="chip mono${tone}">${esc(label)}</span>`;
}

function interviewPanel(step) {
  const rec = step.interview;
  const last = rec.rounds[rec.rounds.length - 1]
    || { ambiguities: [], follow_up_questions: [] };
  const ambis = last.ambiguities.map((a) => `<li>${esc(a)}</li>`).join("");
  if (rec.needs_user_decision) {
    return panel(`Follow-up questions — ${step.title} needs your decision`, `
      <p class="warn">Still unclear after ${rec.rounds.length} rounds.
      What is still open:</p><ul>${ambis}</ul>
      <form id="resolve-form" data-step="${esc(step.id)}">
        <div class="field"><label>Your decision (final — the build follows
        it verbatim)</label><textarea name="decision" rows="3"></textarea></div>
        <button type="submit" class="chip">Decide</button></form>`);
  }
  const qs = last.follow_up_questions.length
    ? last.follow_up_questions.map((q) => `
      <div class="field"><label>${esc(q)}</label>
      <textarea data-fq="${esc(q)}" rows="2"></textarea></div>`).join("")
    : `<div class="field"><label>Your response to the points above</label>
      <textarea data-fq="response" rows="2"></textarea></div>`;
  return panel(`Follow-up questions — ${step.title} (round ${rec.rounds.length}/3)`, `
    ${ambis ? `<p class="dim">Still unclear:</p><ul>${ambis}</ul>` : ""}
    <form id="followup-form" data-step="${esc(step.id)}">${qs}
    <button type="submit" class="chip">Answer follow-ups</button></form>`);
}

function researchPanel(step) {
  const d = step.result;
  let body;
  if (d && d.skipped) {
    body = `<p class="warn">Skipped: ${esc(d.summary || d.reason)}</p>`;
  } else if (d) {
    const comp = (d.competitors || []).map((c) => `<li><b>${esc(c.name)}</b>
      <span class="dim">${esc(c.note || "")}</span></li>`).join("");
    body = `<table class="kv">
      ${row("verdict", `<span class="chip mono">${esc(d.verdict)}</span>`)}
      ${row("summary", esc(d.summary))}
      ${row("differentiation", esc(d.differentiation || ""))}</table>
      ${comp ? `<ul>${comp}</ul>` : ""}`;
  } else {
    body = `<p class="dim">Not run yet. Running searches the live market —
      your click is the approval.</p>`;
  }
  return panel(step.title,
    `${body}<button id="run-research" class="chip">Run reality check</button>`);
}

function checkpointPanel(step) {
  const v = step.result;
  let body = `<p class="dim">No review yet.</p>`;
  if (v) {
    const concerns = (v.concerns || []).map((c) => `<li>${esc(c)}</li>`).join("");
    const qs = (v.follow_up_questions || []).map((q) => `<li>${esc(q)}</li>`).join("");
    body = `<table class="kv">
      ${row("verdict", `<span class="chip mono">${esc(v.verdict)}</span>`)}
      ${row("summary", esc(v.summary))}
      ${row("recommendation", esc(v.recommendation))}</table>
      ${v.degraded ? `<p class="warn">Not AI-checked:
        ${esc(v.degraded_reason || "the AI agent could not be reached")}</p>` : ""}
      ${concerns ? `<p class="dim">Concerns</p><ul>${concerns}</ul>` : ""}
      ${qs ? `<p class="dim">Questions for you</p><ul>${qs}</ul>` : ""}`;
  }
  return panel(step.title, `${body}
    <button id="run-checkpoint" class="chip" data-step="${esc(step.id)}">Run AI review</button>
    ${v ? `<button id="approve-checkpoint" class="chip"
           data-step="${esc(step.id)}">Approve — proceed</button>` : ""}`);
}

function finishPanel(o) {
  if (!o.app_project) return panel("Finish",
    `<p class="dim">Your idea is saved — idea projects don't need a
     build brief.</p>`);
  return panel("Finish the project interview", `
    <p>All steps complete. Continue to write the interview evidence to
    <span class="mono">.danza/spec.md</span> — the next stage reviews the
    concise product scope before any internal build units are created.</p>
    <button id="finish-onboarding" class="chip">Create project brief</button>`);
}

function activeStep(o) {
  if (onboard.edit) return o.steps.find((s) => s.id === onboard.edit);
  if (o.blocking_phase) return o.steps.find((s) => s.id === o.blocking_phase);
  return o.steps.find((s) => s.id === o.current_step);
}

function projectChoices() {
  return `<div class="project-choices">
    <button class="project-choice" data-project-mode="new">
      <b>Create New</b>
      <span>Interview the idea, write a brief, and approve a concise scope.</span>
    </button>
    <button class="project-choice" data-project-mode="existing">
      <b>Continue Existing</b>
      <span>Audit this repository before describing the work to continue.</span>
    </button>
  </div>`;
}

function evidenceSummary(value) {
  if (Array.isArray(value)) return `${value.length} found`;
  if (!value || typeof value !== "object") return String(value ?? "none");
  if (value.percent != null) return `${esc(value.percent)}% covered`;
  if (value.tracked_files != null) return `${esc(value.tracked_files)} tracked files`;
  if (value.nodes) return `${esc(value.nodes.length)} files · ${esc((value.edges || []).length)} links`;
  return `${Object.keys(value).length} checks`;
}

function auditPanel(audit) {
  if (!audit) return "";
  const results = Object.entries(audit.evidence || {}).map(([name, value]) => `
    <div class="audit-result"><span class="mono dim">${esc(name.replaceAll("_", " "))}</span>
    <b>${evidenceSummary(value)}</b></div>`).join("");
  return panel("Audit results", `<p class="mono dim">HEAD ${esc(audit.head || "unavailable")}</p>
    <div class="audit-grid">${results}</div>`);
}

function renderDescribe() {
  if (!onboardData) return;
  const o = onboardData;
  if (!o.setup_complete) {
    $("#stage-body-describe").innerHTML = `<div class="locked">
      <p class="dim">Describing the project unlocks once your team is
      confirmed in Connect.</p></div>`;
    return;
  }
  if (!projectData || projectData.mode === null) {
    $("#stage-body-describe").innerHTML =
      `${describeUI.error ? `<p class="warn mono">${esc(describeUI.error)}</p>` : ""}
       ${describeUI.busy ? `<p class="dim">${esc(describeUI.notice)}</p>` : ""}
       ${panel("Choose how to begin", projectChoices())}`;
    wireProjectChoices();
    return;
  }
  const audit = projectData.mode === "existing" ? auditPanel(projectData.audit) : "";
  const step = activeStep(o);
  let main;
  if (o.blocking_phase && !onboard.edit) main = interviewPanel(step);
  else if (step && step.kind === "phase") main = formPanel(step);
  else if (step && step.kind === "research") main = researchPanel(step);
  else if (step && step.kind === "checkpoint") main = checkpointPanel(step);
  else if (o.complete) main = finishPanel(o);
  else main = `<p class="dim">Choose a project type to begin.</p>`;
  const steps = o.steps.map((s) => `<tr>
      <td class="mono dim">${esc(s.id)}</td><td>${esc(s.title)}</td>
      <td class="mono dim">${esc(s.kind)}</td>
      <td><span class="chip mono">${esc(s.status)}</span>${grillChip(s.interview)}
        ${s.kind === "phase" && s.status !== "pending"
          ? `<button class="chip edit-step" data-step="${esc(s.id)}">edit</button>`
          : ""}</td></tr>`).join("");
  const banner = [
    describeUI.error ? `<p class="warn mono">${esc(describeUI.error)}</p>` : "",
    onboard.error ? `<p class="warn mono">${esc(onboard.error)}</p>` : "",
    onboard.busy ? `<p class="dim">working — your AI team is thinking…</p>` : "",
    o.boss_available ? "" : `<p class="warn">No AI agent is connected —
      reviews and follow-up questions will be skipped.</p>`].join("");
  $("#stage-body-describe").innerHTML = `${audit}<table class="kv">
    ${row("project type", esc(o.project_type ?? "not chosen yet"))}
    ${row("answers stored", esc(o.answered))}
  </table>${banner}
  <table class="sessions-table"><thead>
    <tr><th>step</th><th>title</th><th>kind</th><th>status</th></tr></thead>
    <tbody>${steps}</tbody></table>${main}`;
  wireDescribe(step, o);
}

async function describeAction(notice, fn) {
  if (describeUI.busy) return;
  describeUI.busy = true;
  describeUI.error = "";
  describeUI.notice = notice;
  renderDescribe();
  try {
    const out = await fn();
    if (out.project) projectData = out.project;
    describeUI.notice = out.notice || "Saved.";
  } catch (e) {
    describeUI.error = e.message;
    describeUI.notice = "";
  }
  describeUI.busy = false;
  renderDescribe();
}

function wireProjectChoices() {
  $$('[data-project-mode]').forEach((button) => button.addEventListener("click", () => {
    const mode = button.dataset.projectMode;
    const notice = mode === "existing" ? "Auditing repository…" : "Starting a new project…";
    describeAction(notice, async () => {
      const out = await post("api/project/discover", { mode });
      out.notice = mode === "existing" ? "Repository audit complete." : "New project started.";
      return out;
    });
  }));
}

async function onboardAction(fn) {
  if (onboard.busy) return;
  onboard.busy = true;
  onboard.error = "";
  renderDescribe();
  try {
    const out = await fn();
    onboard.edit = null;
    onboardData = out.onboarding;
    if (out.project) projectData = out.project;
  } catch (e) {
    onboard.error = e.message;
  }
  onboard.busy = false;
  renderDescribe();
}

function wireDescribe(step, o) {
  $$(".edit-step").forEach((b) => b.addEventListener("click", () => {
    onboard.edit = b.dataset.step;
    renderDescribe();
  }));
  const form = $("#onboard-form");
  if (form) {
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      onboardAction(() => post("api/onboard/submit",
        { step_id: form.dataset.step, answers: collectAnswers(step) }));
    });
    $$("select", form).forEach((sel) => sel.addEventListener("change", () => {
      const live = collectAnswers(step);
      step.questions.forEach((q) => {
        if (live[q.id] !== undefined) q.value = live[q.id];
      });
      renderDescribe();
    }));
  }
  const followup = $("#followup-form");
  if (followup) followup.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const answers = {};
    $$("[data-fq]", followup).forEach((t) => {
      if (t.value.trim()) answers[t.dataset.fq] = t.value.trim();
    });
    if (!Object.keys(answers).length) {
      onboard.error = "answer at least one follow-up";
      renderDescribe();
      return;
    }
    onboardAction(() => post("api/onboard/followup",
      { step_id: followup.dataset.step, answers }));
  });
  const resolveForm = $("#resolve-form");
  if (resolveForm) resolveForm.addEventListener("submit", (ev) => {
    ev.preventDefault();
    onboardAction(() => post("api/onboard/resolve",
      { step_id: resolveForm.dataset.step,
        decision: resolveForm.decision.value }));
  });
  const research = $("#run-research");
  if (research) research.addEventListener("click", () =>
    onboardAction(() => post("api/onboard/research", {})));
  const cp = $("#run-checkpoint");
  if (cp) cp.addEventListener("click", () =>
    onboardAction(() => post("api/onboard/checkpoint", { step_id: cp.dataset.step })));
  const approve = $("#approve-checkpoint");
  if (approve) approve.addEventListener("click", () =>
    onboardAction(() => post("api/onboard/approve", { step_id: approve.dataset.step })));
  const finish = $("#finish-onboarding");
  if (finish) finish.addEventListener("click", () =>
    onboardAction(() => post("api/onboard/finish", {})));
}

async function loadDescribe() {
  const bodyEl = $("#stage-body-describe");
  if (onboard.busy || describeUI.busy
      || (bodyEl && bodyEl.contains(document.activeElement))) return;
  const [onboarding, project] = await Promise.all(
    [api("api/onboarding"), api("api/project")]);
  onboardData = onboarding;
  projectData = project;
  renderDescribe();
}

/* ================= APPROVE — review and approve product scope ========= */
const scopeEditor = newFeatureEditor();
const approveUI = { error: "", notice: "", busy: false, acknowledged: new Set() };

function gapsPanel(audit) {
  const gaps = audit?.gaps || [];
  if (!gaps.length) return audit ? `<p class="ok">No material analyzer coverage gaps.</p>` : "";
  return `<h3>Material coverage gaps</h3>
    <p class="dim">Acknowledge every current gap before saving scope.</p>
    ${gaps.map((gap) => `<label class="gap-check"><input type="checkbox"
      data-gap-id="${esc(gap.id)}"${approveUI.acknowledged.has(gap.id) ? " checked" : ""}>
      <span><b>${esc(gap.id)}</b><br>${esc(gap.detail)}</span></label>`).join("")}`;
}

function renderApprove() {
  if (!projectData || !projectData.mode) {
    $("#stage-body-approve").innerHTML = `<div class="locked">
      <p class="dim">Finish Describe before reviewing product scope.</p></div>`;
    return;
  }
  const scope = projectData.scope;
  const audit = projectData.mode === "existing" ? projectData.audit : null;
  const gapIds = (audit?.gaps || []).map((gap) => gap.id);
  const gapsReady = gapIds.every((id) => approveUI.acknowledged.has(id));
  const editable = !scope || scope.approval.state === "draft";
  seedFeatureEditor(scopeEditor, scope?.features, scope?.revision ?? null, 1);
  const cards = featureEditorHTML(scopeEditor, editable);
  let actions = "";
  if (editable) {
    actions = `<div class="scope-actions">
      <button type="button" id="add-scope-feature" class="chip">Add feature</button>
      <button type="button" id="save-project-scope" class="chip"
        ${gapsReady ? "" : "disabled"}>Save draft scope</button></div>`;
    if (scope) actions += `<p><button type="button" id="approve-project-scope"
      class="chip" ${scopeEditor.dirty ? "disabled" : ""}>Approve exact revision ${esc(scope.revision)}</button>
      <span class="dim">Approval applies only to the revision shown above.</span></p>`;
  } else {
    actions = `<p class="ok">Revision ${esc(scope.revision)} is approved exactly.</p>
      <button type="button" id="decompose-project" class="chip">Create internal build units</button>`;
  }
  const revision = scope ? `revision ${esc(scope.revision)} · ${esc(scope.approval.state)}`
    : "not saved";
  const banner = [
    approveUI.error ? `<p class="warn mono">${esc(approveUI.error)}</p>` : "",
    approveUI.busy ? `<p class="dim">${esc(approveUI.notice || "Working…")}</p>` : "",
  ].join("");
  $("#stage-body-approve").innerHTML = banner +
    panel("Draft product scope", `<p class="dim">Internal A/B/C build units
      are created only after approval.</p>
      <p class="mono">${revision}</p>
      ${audit ? gapsPanel(audit) : ""}
      <div class="scope-list">${cards}</div>${actions}`);
  wireApprove();
}

async function approveAction(notice, fn) {
  if (approveUI.busy) return;
  approveUI.busy = true;
  approveUI.error = "";
  approveUI.notice = notice;
  renderApprove();
  try {
    const out = await fn();
    if (out.project) {
      projectData = out.project;
      scopeEditor.features = null;
      scopeEditor.revision = null;
      scopeEditor.dirty = false;
    }
    approveUI.notice = out.notice || "Saved.";
  } catch (e) {
    approveUI.error = e.message;
    approveUI.notice = "";
  }
  approveUI.busy = false;
  renderApprove();
}

function wireApprove() {
  const container = $("#stage-body-approve");
  $$(".feature-card input, .feature-card textarea", container).forEach((input) =>
    input.addEventListener("input", () => {
      scopeEditor.dirty = true;
      const approve = $("#approve-project-scope");
      if (approve) approve.disabled = true;
    }));
  $$('[data-gap-id]', container).forEach((box) => box.addEventListener("change", () => {
    if (box.checked) approveUI.acknowledged.add(box.dataset.gapId);
    else approveUI.acknowledged.delete(box.dataset.gapId);
    scopeEditor.features = collectFeatureEditor(container);
    renderApprove();
  }));
  const add = $("#add-scope-feature");
  if (add) add.addEventListener("click", () => {
    scopeEditor.features = collectFeatureEditor(container);
    const nextId = Math.max(0, ...scopeEditor.features.map((f) => f.id)) + 1;
    scopeEditor.features.push(blankFeature(nextId));
    scopeEditor.dirty = true;
    renderApprove();
  });
  $$(".remove-feature", container).forEach((button) => button.addEventListener("click", () => {
    scopeEditor.features = collectFeatureEditor(container)
      .filter((f) => f.id !== Number(button.dataset.featureId));
    scopeEditor.dirty = true;
    renderApprove();
  }));
  const save = $("#save-project-scope");
  if (save) save.addEventListener("click", () => {
    const features = collectFeatureEditor(container);
    const scope = projectData.scope;
    const body = { features };
    if (scope) body.expected_revision = scope.revision;
    if (projectData.mode === "existing") {
      const audit = projectData.audit;
      const gapIds = (audit.gaps || []).map((gap) => gap.id);
      Object.assign(body, { audit_fingerprint: audit.fingerprint, acknowledged_gaps: gapIds });
    }
    approveAction("Saving draft scope…", () => post("api/project/scope", body));
  });
  const approve = $("#approve-project-scope");
  if (approve) approve.addEventListener("click", () => {
    const scope = projectData.scope;
    approveAction(`Approving exact revision ${scope.revision}…`, () =>
      post("api/project/approve", { expected_revision: scope.revision }));
  });
  const decompose = $("#decompose-project");
  if (decompose) decompose.addEventListener("click", () =>
    approveAction("Creating internal build units…", async () => {
      const out = await post("api/project/decompose", {});
      out.notice = "Approved scope decomposed into build units.";
      return out;
    }));
}

async function loadApprove() {
  const bodyEl = $("#stage-body-approve");
  if (approveUI.busy || (bodyEl && bodyEl.contains(document.activeElement))) return;
  projectData = await api("api/project");
  if (projectData.ready_for_scope && projectData.audit) {
    approveUI.acknowledged = new Set((projectData.audit.gaps || []).map((gap) => gap.id));
  }
  renderApprove();
}

/* ================= BUILD — relay controls + live product progress ===== */
let buildData = null;              // { live }
const build = { error: "", busy: false };
const additionsEditor = newFeatureEditor();

function friendlyEvent(e) {
  switch (e.event) {
    case "ignite":
      return `Handed the baton to ${teamDisplayName(e.runner)} (turn ${e.turn_number}).`;
    case "session_end":
      return e.orphaned_turn
        ? `A session died mid-turn (turn ${e.turn_number}) — Tony-D will reassess it.`
        : `Turn ${e.turn_number} wrapped up and its session closed.`;
    case "stall":
      return `Nothing has moved for ${e.minutes} minutes — the crew may be stuck.`;
    case "state_error":
      return `Team state file problem: ${e.error}`;
    case "routing_fallback":
      return `Seat routing unavailable — taking turns in order. (${e.reason})`;
    case "halt_blocked":
      return "The build hit a hard stop and needs you — check the team state.";
    case "stop_done":
      return "The build finished — every task is done.";
    case "stop_valve":
      return "The relay stopped itself: sessions kept dying without progress.";
    default:
      return e.event || "event";
  }
}

function controlsHTML(live) {
  const ready = !live.build_error && !!live.scope;
  const banner = [
    build.error ? `<p class="warn mono">${esc(build.error)}</p>` : "",
    build.busy ? `<p class="dim">working…</p>` : "",
  ].join("");
  const buttons = live.running
    ? `<p class="ok">The build crew is running.</p>
       <button id="stop-build" class="chip">Stop build</button>`
    : `<button id="start-build" class="chip"${ready ? "" : " disabled"}>
       Start build</button>${ready ? ""
       : ` <span class="dim">Finish Approve to start building.</span>`}`;
  const tail = live.session.alive
    ? `<h2 class="section-label">Live session — ${esc(live.session.name)}</h2>
       <pre class="session-tail mono">${esc(live.session.tail)}</pre>` : "";
  const events = live.conductor.length
    ? `<h2 class="section-label">Build activity</h2>
       ${live.conductor.map((e) => `<div class="log-line">
         <span class="dim">${esc(e.ts || "")}</span> ${esc(friendlyEvent(e))}</div>`).join("")}`
    : `<p class="dim">No build activity yet.</p>`;
  return banner + buttons + tail + events;
}

async function buildAction(fn) {
  if (build.busy) return;
  build.busy = true;
  build.error = "";
  renderBuild();
  try {
    await fn();
    buildData.live = await api("api/build");
  } catch (e) {
    build.error = e.message;
  }
  build.busy = false;
  renderBuild();
}

function taskHTML(t) {
  const meta = [t.kind, t.size_est ? `${t.size_est}m` : "",
                (t.writes || []).join(", ")].filter(Boolean).map(esc).join(" · ");
  const verify = t.verified_by ? `<span class="dim mono">verify: ${esc(t.verified_by)}</span>` : "";
  const subs = (t.subtasks || []).map(taskHTML).join("");
  return `<li><span class="mono">${esc(t.id)}</span> ${esc(t.description)}
    <span class="dim">${meta}</span> ${verify}
    ${subs ? `<ul>${subs}</ul>` : ""}</li>`;
}

function savingsHTML(savings) {
  // P4.1 T9: evidence for the core pitch — memory briefs replace re-reading.
  // Every number here comes straight from recorded telemetry (server-side
  // savings_stats); the zero-state below is the honest "nothing recorded
  // yet" case, never a fabricated number.
  if (!savings || !savings.briefed_turns) {
    return panel("Token savings", `<div class="build-row">
      <b>Tokens saved by memory briefs</b><span class="dim">No brief data yet</span></div>`);
  }
  const { briefed_turns: turns, known_turns: known,
    injected_tokens: injected, replaced_tokens: replaced,
    saved_tokens: saved } = savings;
  const percent = replaced > 0
    ? Math.max(0, Math.min(100, Math.round(saved * 100 / replaced))) : 0;
  const coverage = known < turns
    ? `${esc(known)} of ${esc(turns)} briefed turns have a recorded baseline`
    : `${esc(turns)} briefed turn${turns === 1 ? "" : "s"}`;
  const detail = `${esc(replaced)}t replaced − ${esc(injected)}t injected · ${coverage}`;
  return panel("Token savings", `<div class="savings-block" title="${esc(detail)}">
    <div class="build-row"><b>Tokens saved by memory briefs</b>
      <span class="mono">${esc(saved)}t saved</span></div>
    <div class="quota-meter" aria-label="${esc(detail)}">
      <span style="width:${percent}%"></span></div>
    <p class="dim mono">${detail}</p></div>`);
}

function quotaHTML(quota) {
  const completed = quota?.completed ?? 0;
  const limit = quota?.limit;
  const remaining = quota?.remaining;
  const percent = limit ? Math.min(100, Math.round(completed * 100 / limit)) : 0;
  const label = limit == null
    ? `${esc(completed)} completed · turn quota starts with the build`
    : `${esc(completed)} / ${esc(limit)} · ${esc(remaining)} remaining`;
  return `<div class="quota-block"><div class="build-row">
    <b>Quota this turn</b><span class="mono dim">${label}</span></div>
    <div class="quota-meter" aria-label="Quota this turn: ${esc(label)}">
      <span style="width:${percent}%"></span></div></div>`;
}

function unitHTML(unit) {
  const hardStop = unit.status !== "completed" && (unit.flags || []).length
    ? `<span class="chip warn-chip">Hard stop · ${esc(unit.flags.join(", "))}</span>` : "";
  const blocked = unit.status === "blocked"
    ? `<p class="build-alert"><b>Blocked</b> · ${esc(unit.blocker_reason || "No reason recorded")}</p>` : "";
  const timing = unit.actual_minutes == null ? `${esc(unit.size_est)}m estimate`
    : `${esc(unit.actual_minutes)}m actual · ${esc(unit.size_est)}m estimate`;
  return `<li class="build-unit ${esc(unit.status)}">
    <div class="build-row"><span><b class="mono">${esc(unit.id)}</b>
      ${esc(unit.description)}</span><span class="chip mono">${esc(unit.status)}</span></div>
    <p class="dim mono">${esc(unit.kind)} · ${timing}</p>${hardStop}${blocked}</li>`;
}

function buildFeatureHTML(feature) {
  const completed = feature.status === "completed";
  const title = completed ? `<s>${esc(feature.summary)}</s>` : esc(feature.summary);
  const criteria = (feature.acceptance_criteria || [])
    .map((item) => `<li>${esc(item)}</li>`).join("");
  const units = (feature.units || []).map(unitHTML).join("");
  return `<article class="build-feature ${esc(feature.status)}">
    <div class="build-feature-head"><span class="mono">${esc(feature.id)}</span>
      <b>${title}</b><span class="chip mono">${esc(feature.status)}</span></div>
    <details><summary>Acceptance criteria · Atomic build units</summary>
      <h3>Acceptance criteria</h3><ul>${criteria}</ul>
      <h3>Atomic build units</h3><ul class="build-units">${units}</ul>
    </details></article>`;
}

function buildAlertsHTML(features) {
  const units = features.flatMap((feature) => feature.units || []);
  const blocked = units.filter((unit) => unit.status === "blocked");
  const hardStops = units.filter((unit) => unit.status !== "completed"
    && (unit.flags || []).length);
  return `${blocked.length ? `<div class="build-alert"><b>Blocked</b> ·
      ${blocked.map((unit) => `${esc(unit.id)}: ${esc(unit.blocker_reason || "reason not recorded")}`).join(" · ")}</div>` : ""}
    ${hardStops.length ? `<div class="build-alert hard-stop"><b>Hard stop</b> ·
      ${hardStops.map((unit) => `${esc(unit.id)} (${esc(unit.flags.join(", "))})`).join(" · ")}</div>` : ""}`;
}

function nextAdditionId(live) {
  const ids = [...(live.features || []).map((feature) => feature.id),
    ...(live.additions?.features || []).map((feature) => feature.id)];
  return Math.max(0, ...ids) + 1;
}

function additionsHTML(live) {
  seedFeatureEditor(additionsEditor, live.additions?.features,
    live.additions?.revision ?? null, nextAdditionId(live));
  const additions = live.additions;
  if (live.next_handoff) return panel("Approved additions", `
    <p class="ok">Exact additions revision ${esc(additions?.revision)} is approved.</p>
    <p><b>Next handoff:</b> scope revision ${esc(live.next_handoff.scope_revision)} ·
      ${esc(live.next_handoff.unit_count)} atomic units queued. Active work is unchanged
      until the safe handoff boundary.</p>`);
  const cards = featureEditorHTML(additionsEditor, true);
  const revision = additions
    ? `revision ${esc(additions.revision)} · ${esc(additions.approval.state)}`
    : "no additions draft saved";
  const approve = additions?.approval.state === "draft"
    ? `<button type="button" id="approve-build-additions" class="chip"
       ${additionsEditor.dirty ? "disabled" : ""}>Approve exact additions revision ${esc(additions.revision)}</button>` : "";
  return panel("Add to the approved product", `<p class="dim">New product outcomes
    are drafted separately. Approval replans pending work for the next safe handoff.</p>
    <p class="mono">${revision}</p><div class="addition-list">${cards}</div>
    <div class="scope-actions"><button type="button" id="add-build-addition"
      class="chip">Add product feature</button><button type="button"
      id="save-build-additions" class="chip">Save additions draft</button>${approve}</div>`);
}

function productProgressHTML(live) {
  if (live.build_error) return `<p class="warn mono">${esc(live.build_error)}</p>`;
  if (!live.scope || !live.features) return `<p class="dim">No approved product
    scope is ready for BUILD.</p>`;
  const progress = live.progress || {};
  const approval = live.scope.approval || {};
  const features = live.features.map(buildFeatureHTML).join("");
  return `${panel("Live product progress", `
    <div class="build-summary"><span><b>${esc(progress.completed)} / ${esc(progress.total)}</b>
      product features complete</span><span class="chip mono">${esc(progress.status)}</span></div>
    <p class="mono dim">Product scope revision ${esc(live.scope.revision)} ·
      ${esc(approval.state)}${approval.approved_revision == null ? "" : ` exactly at revision ${esc(approval.approved_revision)}`}</p>
    ${quotaHTML(live.quota)}${buildAlertsHTML(live.features)}
    <div class="build-feature-list">${features}</div>`)}${additionsHTML(live)}`;
}

function renderBuild() {
  const teamHTML = `<h2 class="section-label">Team</h2>${teamStripHTML(flowData.team)}`;
  // productProgressHTML() already degrades honestly when there's no plan
  // yet (build_error) or no approved scope — one render path, no dead
  // branches duplicating that logic here.
  $("#stage-body-build").innerHTML = teamHTML + savingsHTML(buildData.live.savings)
    + panel("Relay controls", controlsHTML(buildData.live))
    + productProgressHTML(buildData.live);
  wireBuild();
}

function wireBuild() {
  const container = $("#stage-body-build");
  const start = $("#start-build");
  if (start) start.addEventListener("click", () =>
    buildAction(() => post("api/build/start", {})));
  const stop = $("#stop-build");
  if (stop) stop.addEventListener("click", () => {
    if (!window.confirm("Stop the build crew? The current turn finishes safely.")) return;
    buildAction(() => post("api/build/stop", {}));
  });
  $$(".feature-card input, .feature-card textarea", container).forEach((input) =>
    input.addEventListener("input", () => {
      additionsEditor.features = collectFeatureEditor(container);
      additionsEditor.dirty = true;
      const approve = $("#approve-build-additions");
      if (approve) approve.disabled = true;
    }));
  const add = $("#add-build-addition");
  if (add) add.addEventListener("click", () => {
    additionsEditor.features = collectFeatureEditor(container);
    const nextId = Math.max(0, ...additionsEditor.features.map((f) => f.id),
      ...(buildData.live.features || []).map((f) => f.id)) + 1;
    additionsEditor.features.push(blankFeature(nextId));
    additionsEditor.dirty = true;
    renderBuild();
  });
  $$(".remove-feature", container).forEach((button) => button.addEventListener("click", () => {
    additionsEditor.features = collectFeatureEditor(container)
      .filter((f) => f.id !== Number(button.dataset.featureId));
    additionsEditor.dirty = true;
    renderBuild();
  }));
  const save = $("#save-build-additions");
  if (save) save.addEventListener("click", () => {
    const features = collectFeatureEditor(container);
    const additions = buildData.live.additions;
    const body = { additions: features };
    if (additions) body.expected_revision = additions.revision;
    buildAction(async () => {
      const out = await post("api/build/additions", body);
      additionsEditor.features = null;
      additionsEditor.revision = null;
      additionsEditor.dirty = false;
      return out;
    });
  });
  const approve = $("#approve-build-additions");
  if (approve) approve.addEventListener("click", () => {
    const additions = buildData.live.additions;
    buildAction(async () => {
      const out = await post("api/build/approve", { expected_revision: additions.revision });
      additionsEditor.features = null;
      additionsEditor.revision = null;
      additionsEditor.dirty = false;
      return out;
    });
  });
}

async function loadBuild() {
  const bodyEl = $("#stage-body-build");
  if (build.busy || (bodyEl && bodyEl.contains(document.activeElement))) return;
  const live = await api("api/build");
  buildData = { live };
  renderBuild();
}

/* ================= DONE ================= */
async function loadDone() {
  const live = buildData?.live || await api("api/build");
  const progress = live.progress || {};
  $("#stage-body-done").innerHTML = panel("Every product feature is complete", `
    <p class="ok">${esc(progress.completed ?? 0)} / ${esc(progress.total ?? 0)}
    product features complete.</p>
    <p class="dim">Add more product outcomes any time from the Build stage's
    "Add to the approved product" editor.</p>`);
}

/* ================= ADVANCED — CORTEX stats, raw log, plan internals ==== */
const advanced = { open: false, loaded: false };

function driverName(id, roster) {
  const character = (roster || []).find((item) => item.id === id);
  if (character) return `${character.name} — ${character.role}`;
  const parts = String(id).split("-");
  const role = parts.pop();
  const name = parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
  return name ? `${name} (${role})` : role;
}

function cortexPanel(o) {
  const c = o.cortex;
  const agents = Object.entries(c.per_agent || {});
  const agentRows = agents.map(([id, t]) =>
    row(esc(driverName(id, o.roster)),
        `<b>~${esc(t.tokens)}t</b> <span class="dim">· ${esc(t.reads)}
         read${t.reads === 1 ? "" : "s"}</span>`)).join("");
  return panel("CORTEX memory", `<table class="kv">
    ${row("memories", `<b>${esc(c.observations_stored)}</b>`)}
    ${row("memory size", `~${esc(c.read_tokens)}t`)}
    ${row("sessions", esc(c.sessions))}
    ${row("waiting to process", esc(c.pending_events))}
  </table>
  ${agentRows ? `<table class="kv">${agentRows}</table>` : ""}
  <p><a class="chip" href="cortex/">open CORTEX →</a></p>`);
}

function projectInfoPanel(o) {
  return panel("Project", `<table class="kv">
    ${row("name", `<b>${esc(o.project)}</b>`)}
    ${row("root", `<span class="mono dim">${esc(o.root)}</span>`)}
  </table>`);
}

function planInternalsPanel(p) {
  if (!p.plan) return "";
  if (p.plan.error) return panel("Internal build plan",
    `<p class="warn mono">${esc(p.plan.error)}</p>`);
  const tree = (p.tree || []).length
    ? `<ul class="plan-tree">${p.tree.map(taskHTML).join("")}</ul>` : "";
  const md = p.plan_md ? `<h2 class="section-label">plan.md</h2>
    <pre class="plan-md mono">${esc(p.plan_md)}</pre>` : "";
  return tree || md ? panel("Internal build plan", tree + md) : "";
}

async function loadAdvanced() {
  const [o, log, p] = await Promise.all(
    [api("api/overview"), api("api/conductor?limit=100"), api("api/plan")]);
  const activity = log.items.length
    ? `<div class="console-log mono">${log.items.map(logLine).join("")}</div>`
    : `<p class="dim">Nothing has happened yet.</p>`;
  $("#advanced-body").innerHTML = projectInfoPanel(o) + cortexPanel(o) +
    planInternalsPanel(p) + panel("Full activity log", activity);
  advanced.loaded = true;
}

function openAdvanced() {
  advanced.open = true;
  $("#advanced-drawer").hidden = false;
  $("#advanced-toggle").setAttribute("aria-expanded", "true");
  if (!advanced.loaded) loadAdvanced().catch((e) => console.error(e));
}

function closeAdvanced() {
  advanced.open = false;
  $("#advanced-drawer").hidden = true;
  $("#advanced-toggle").setAttribute("aria-expanded", "false");
}

$("#advanced-toggle").addEventListener("click", () =>
  advanced.open ? closeAdvanced() : openAdvanced());
$("#advanced-close").addEventListener("click", closeAdvanced);

/* ---------- refresh + SSE ---------- */
async function refresh() {
  try {
    flowData = await api("api/flow");
    renderFlow();
    if (advanced.open) advanced.loaded = false, loadAdvanced().catch((e) => console.error(e));
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
