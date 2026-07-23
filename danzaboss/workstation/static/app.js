/* DANZA-OS dashboard — vanilla JS, no build step. OVERVIEW is live;
   SETUP confirms the AI team; PROJECT owns discovery, interview, takeover
   audit, and product-scope approval; BUILD starts/stops the relay and shows
   live team state over the plan. */
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
    ${row("workspace", `<span class="chip mono">DANZA-OS</span>`)}
    ${row("project brief", o.spec_exists ? "ready (spec.md)"
                                : '<span class="dim">not written yet</span>')}
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
    ${row("taking this turn", `<b>${esc(t.current_boss)}</b>`)}
    ${row("turn", esc(t.turn_number))}
    ${row("status", `<span class="chip mono">${esc(t.status)}</span>`)}
    ${row("verified units this turn",
          `${esc(t.features_completed_this_turn)} / ${esc(t.max_features_per_turn)}`)}
    ${row("handoff required", t.handoff_required ? "yes" : "no")}
  </table>`);
}

function planPanel(o) {
  const p = o.plan;
  if (!p) return panel("Plan", `<p class="dim">No build plan yet — finish
    Project scope approval and decomposition to create one.</p>`);
  if (p.error) return panel("Plan", `<p class="warn mono">${esc(p.error)}</p>`);
  return panel("Plan", `<table class="kv">
    ${row("brief", `<span class="mono dim">${esc(p.spec_ref)}</span>`)}
    ${row("tasks", esc(p.tasks))}
    ${row("ready-to-build tasks", esc(p.leaves))}
    ${row("build order",
          `<span class="mono dim">${esc((p.order || []).join(" → "))}</span>`)}
  </table>`);
}

function cortexPanel(o) {
  const c = o.cortex;
  return panel("CORTEX memory", `<table class="kv">
    ${row("memories", `<b>${esc(c.observations_stored)}</b>`)}
    ${row("memory size", `~${esc(c.read_tokens)}t`)}
    ${row("sessions", esc(c.sessions))}
    ${row("waiting to process", esc(c.pending_events))}
  </table>
  <p><a class="chip" href="cortex/">open CORTEX →</a></p>`);
}

/* Character identity for CORTEX read accounting comes from canonical prompts. */
function driverName(id, roster) {
  const character = (roster || []).find((item) => item.id === id);
  if (character) return `${character.name} — ${character.role}`;
  const parts = String(id).split("-");
  const role = parts.pop();
  const name = parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
  return name ? `${name} (${role})` : role;
}

function tokensPanel(o) {
  const c = o.cortex;
  const agents = Object.entries(c.per_agent || {});
  const spent = agents.reduce((n, [, t]) => n + t.tokens, 0);
  const agentRows = agents.map(([id, t]) =>
    row(esc(driverName(id, o.roster)),
        `<b>~${esc(t.tokens)}t</b> <span class="dim">· ${esc(t.reads)}
         read${t.reads === 1 ? "" : "s"}</span>`)).join("");
  const turnRows = Object.entries(c.per_turn || {}).map(([turn, n]) =>
    row(`turn ${esc(turn)}`,
        `${esc(n)} agent start${n === 1 ? "" : "s"}`)).join("");
  return panel("Tokens", `<table class="kv">
    ${row("your team read",
          `<b>~${esc(spent)}t</b> <span class="dim">— full memory is
           ~${esc(c.read_tokens)}t; each agent gets only its slice</span>`)}
    ${agentRows ||
      row("agents", `<span class="dim">no memory reads yet</span>`)}
    ${turnRows}
  </table>`);
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
  $("#profile-chip").textContent = "DANZA-OS";
  $("#profile-chip").title = "DANZA-OS workspace";
  $("#overview-grid").innerHTML =
    projectPanel(o) + teamPanel(o) + planPanel(o) + cortexPanel(o) +
    tokensPanel(o);
  const log = await api("api/conductor?limit=40");
  $("#conductor-log").innerHTML = log.items.length
    ? log.items.map(logLine).join("")
    : `<p class="dim">Nothing has happened yet — start a build from the
       Build tab.</p>`;
}

/* ---------- project (Phase 4.1: discovery + interview + scope) ---------- */
let onboardData = null;                       // last /api/onboarding payload
let projectData = null;                       // last /api/project payload
const onboard = { edit: null, error: "", busy: false };
const projectUI = { error: "", notice: "", busy: false,
  features: null, scopeRevision: null, acknowledged: new Set(), dirty: false };

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
  // a round can list ambiguities without follow-up questions — offer a
  // generic response field so the grill never dead-ends
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
    <span class="mono">.danza/spec.md</span>, then review the concise product
    scope before any internal build units are created.</p>
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
  const gaps = audit.gaps || [];
  const gapHTML = gaps.length ? `<h3>Material coverage gaps</h3>
    <p class="dim">Acknowledge every current gap before saving scope. The
    acknowledgement is tied to this audit fingerprint.</p>
    ${gaps.map((gap) => `<label class="gap-check"><input type="checkbox"
      data-gap-id="${esc(gap.id)}"${projectUI.acknowledged.has(gap.id) ? " checked" : ""}>
      <span><b>${esc(gap.id)}</b><br>${esc(gap.detail)}</span></label>`).join("")}`
    : `<p class="ok">No material analyzer coverage gaps.</p>`;
  return panel("Audit results", `<p class="mono dim">HEAD ${esc(audit.head || "unavailable")}</p>
    <div class="audit-grid">${results}</div>${gapHTML}`);
}

function blankFeature(id) {
  return { id, summary: "", acceptance_criteria: [""], status: "pending" };
}

function seedScopeEditor(scope) {
  if (projectUI.features !== null && projectUI.scopeRevision === (scope?.revision ?? null)) return;
  projectUI.features = scope ? scope.features.map((feature) => ({
    ...feature, acceptance_criteria: [...feature.acceptance_criteria],
  })) : [blankFeature(1)];
  projectUI.scopeRevision = scope?.revision ?? null;
}

function collectScopeFeatures() {
  return $$(".scope-feature", $("#project-panel")).map((card) => ({
    id: Number(card.dataset.featureId),
    summary: $("[name=summary]", card).value.trim(),
    acceptance_criteria: $("[name=criteria]", card).value.split("\n")
      .map((line) => line.trim()).filter(Boolean),
    status: card.dataset.status,
  }));
}

function featureEditorHTML(feature, editable) {
  const remove = editable && projectUI.features.length > 1
    ? `<button type="button" class="chip remove-feature"
       data-feature-id="${esc(feature.id)}">Remove</button>` : "";
  const summary = editable
    ? `<input type="text" name="summary" maxlength="300"
       value="${esc(feature.summary)}" placeholder="One or two concise sentences">`
    : `<p>${esc(feature.summary)}</p>`;
  const criteria = editable
    ? `<textarea name="criteria" rows="3" placeholder="One acceptance criterion per line">${esc(feature.acceptance_criteria.join("\n"))}</textarea>`
    : `<ul>${feature.acceptance_criteria.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`;
  return `<article class="scope-feature" data-feature-id="${esc(feature.id)}"
    data-status="${esc(feature.status)}">
    <div class="scope-feature-head"><b>Feature ${esc(feature.id)}</b>
      <span class="chip mono">${esc(feature.status)}</span>${remove}</div>
    <div class="field"><label>Concise product feature</label>${summary}</div>
    <details><summary>Acceptance criteria</summary>
      <div class="field">${criteria}</div></details></article>`;
}

function scopePanel(project) {
  const scope = project.scope;
  seedScopeEditor(scope);
  const editable = !scope || scope.approval.state === "draft";
  const audit = project.audit;
  const gapIds = (audit?.gaps || []).map((gap) => gap.id);
  const gapsReady = gapIds.every((id) => projectUI.acknowledged.has(id));
  const features = projectUI.features.map((feature) =>
    featureEditorHTML(feature, editable)).join("");
  let actions = "";
  if (editable) {
    actions = `<div class="scope-actions">
      <button type="button" id="add-scope-feature" class="chip">Add feature</button>
      <button type="button" id="save-project-scope" class="chip"
        ${gapsReady ? "" : "disabled"}>Save draft scope</button></div>`;
    if (scope) actions += `<p><button type="button" id="approve-project-scope"
      class="chip" ${projectUI.dirty ? "disabled" : ""}>Approve exact revision ${esc(scope.revision)}</button>
      <span class="dim">Approval applies only to the revision shown above.</span></p>`;
  } else {
    actions = `<p class="ok">Revision ${esc(scope.revision)} is approved exactly.</p>
      <button type="button" id="decompose-project" class="chip">Create internal build units</button>`;
  }
  const revision = scope
    ? `revision ${esc(scope.revision)} · ${esc(scope.approval.state)}`
    : "not saved";
  return panel("Draft product scope", `<p class="dim">Review product outcomes here.
    Internal A/B/C build units are created only after approval.</p>
    <p class="mono">${revision}</p><div class="scope-list">${features}</div>${actions}`);
}

function renderProjectLifecycle() {
  const audit = projectData.mode === "existing" ? auditPanel(projectData.audit) : "";
  $("#project-panel").innerHTML = `${projectUI.notice ? `<p class="ok">${esc(projectUI.notice)}</p>` : ""}
    ${projectUI.error ? `<p class="warn mono">${esc(projectUI.error)}</p>` : ""}
    ${projectUI.busy ? `<p class="dim">${esc(projectUI.notice || "Working…")}</p>` : ""}
    ${audit}${scopePanel(projectData)}`;
  wireProjectLifecycle();
}

function renderProject() {
  if (!onboardData) return;
  if (!onboardData.setup_complete) {
    renderOnboard();
    return;
  }
  if (!projectData || projectData.mode === null) {
    $("#project-panel").innerHTML = `${projectUI.error ? `<p class="warn mono">${esc(projectUI.error)}</p>` : ""}
      ${projectUI.busy ? `<p class="dim">${esc(projectUI.notice)}</p>` : ""}
      ${panel("Choose how to begin", projectChoices())}`;
    wireProjectChoices();
    return;
  }
  if (projectData.mode === "new" && (!onboardData.complete || !projectData.briefReady)) {
    renderOnboard();
    $("#project-panel").insertAdjacentHTML("afterbegin",
      `<p class="dim">Continue the project interview before drafting scope.</p>`);
    return;
  }
  renderProjectLifecycle();
}

function renderOnboard() {
  const o = onboardData;
  // Hard setup-first gate (Phase 4 Decision 1): the server 409s every
  // onboarding write until the team is confirmed — render that honestly.
  if (!o.setup_complete) {
    $("#project-panel").innerHTML = `<div class="locked">
      <h3>Set up your AI team first</h3>
      <p class="dim">Project discovery unlocks once your team is confirmed —
        pick who plans, builds and tests on the Setup tab.</p>
      <button id="goto-setup" class="chip">Go to Setup</button></div>`;
    $("#goto-setup").addEventListener("click", () =>
      $$(".tab[data-view]").find((b) => b.dataset.view === "setup")?.click());
    return;
  }
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
    onboard.error ? `<p class="warn mono">${esc(onboard.error)}</p>` : "",
    onboard.busy ? `<p class="dim">working — your AI team is thinking…</p>` : "",
    o.boss_available ? "" : `<p class="warn">No AI agent is connected —
      reviews and follow-up questions will be skipped. Open Setup to
      connect one.</p>`].join("");
  $("#project-panel").innerHTML = `<table class="kv">
    ${row("project type", esc(o.project_type ?? "not chosen yet"))}
    ${row("answers stored", esc(o.answered))}
    ${row("complete", o.complete ? "yes" : "no")}
  </table>${banner}
  <table class="sessions-table"><thead>
    <tr><th>step</th><th>title</th><th>kind</th><th>status</th></tr></thead>
    <tbody>${steps}</tbody></table>${main}`;
  wireOnboard(step, o);
}

async function projectAction(notice, fn) {
  if (projectUI.busy) return;
  projectUI.busy = true;
  projectUI.error = "";
  projectUI.notice = notice;
  renderProject();
  try {
    const out = await fn();
    if (out.project) {
      const briefReady = projectData?.briefReady || false;
      projectData = { ...out.project, briefReady };
      projectUI.scopeRevision = null;
      projectUI.dirty = false;
    }
    projectUI.notice = out.notice || "Saved.";
  } catch (e) {
    projectUI.error = e.message;
    projectUI.notice = "";
  }
  projectUI.busy = false;
  renderProject();
}

function wireProjectChoices() {
  $$('[data-project-mode]').forEach((button) => button.addEventListener("click", () => {
    const mode = button.dataset.projectMode;
    const notice = mode === "existing" ? "Auditing repository…" : "Starting a new project…";
    projectAction(notice, async () => {
      const out = await post("api/project/discover", { mode });
      out.notice = mode === "existing" ? "Repository audit complete." : "New project started.";
      return out;
    });
  }));
}

function wireProjectLifecycle() {
  $$(".scope-feature input, .scope-feature textarea").forEach((input) =>
    input.addEventListener("input", () => {
      projectUI.dirty = true;
      const approve = $("#approve-project-scope");
      if (approve) approve.disabled = true;
    }));
  $$('[data-gap-id]').forEach((box) => box.addEventListener("change", () => {
    if (box.checked) projectUI.acknowledged.add(box.dataset.gapId);
    else projectUI.acknowledged.delete(box.dataset.gapId);
    projectUI.features = collectScopeFeatures();
    renderProjectLifecycle();
  }));
  const add = $("#add-scope-feature");
  if (add) add.addEventListener("click", () => {
    projectUI.features = collectScopeFeatures();
    const nextId = Math.max(0, ...projectUI.features.map((feature) => feature.id)) + 1;
    projectUI.features.push(blankFeature(nextId));
    projectUI.dirty = true;
    renderProjectLifecycle();
  });
  $$(".remove-feature").forEach((button) => button.addEventListener("click", () => {
    projectUI.features = collectScopeFeatures()
      .filter((feature) => feature.id !== Number(button.dataset.featureId));
    projectUI.dirty = true;
    renderProjectLifecycle();
  }));
  const save = $("#save-project-scope");
  if (save) save.addEventListener("click", () => {
    const features = collectScopeFeatures();
    const scope = projectData.scope;
    const body = { features };
    if (scope) body.expected_revision = scope.revision;
    if (projectData.mode === "existing") {
      const audit = projectData.audit;
      const gapIds = (audit.gaps || []).map((gap) => gap.id);
      Object.assign(body, { audit_fingerprint: audit.fingerprint,
        acknowledged_gaps: gapIds });
    }
    projectAction("Saving draft scope…", () => post("api/project/scope", body));
  });
  const approve = $("#approve-project-scope");
  if (approve) approve.addEventListener("click", () => {
    const scope = projectData.scope;
    projectAction(`Approving exact revision ${scope.revision}…`, () =>
      post("api/project/approve", { expected_revision: scope.revision }));
  });
  const decompose = $("#decompose-project");
  if (decompose) decompose.addEventListener("click", () =>
    projectAction("Creating internal build units…", async () => {
      const out = await post("api/project/decompose", {});
      $$(".tab[data-view]").find((button) => button.dataset.view === "build")?.click();
      out.notice = "Approved scope decomposed into build units.";
      return out;
    }));
}

async function onboardAction(fn) {
  if (onboard.busy) return;
  onboard.busy = true;
  onboard.error = "";
  renderProject();
  try {
    const out = await fn();
    onboard.edit = null;
    onboardData = out.onboarding;
    if (out.project) {
      projectData = { ...out.project, scope: out.project.scope || null,
        briefReady: true };
      projectUI.features = null;
      projectUI.scopeRevision = null;
    }
  } catch (e) {
    onboard.error = e.message;
  }
  onboard.busy = false;
  renderProject();
}

function wireOnboard(step, o) {
  $$(".edit-step").forEach((b) => b.addEventListener("click", () => {
    onboard.edit = b.dataset.step;
    renderProject();
  }));
  const form = $("#onboard-form");
  if (form) {
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      onboardAction(() => post("api/onboard/submit",
        { step_id: form.dataset.step, answers: collectAnswers(step) }));
    });
    // choice answers drive show_if branches — re-render with live values,
    // preserving everything typed so far
    $$("select", form).forEach((sel) => sel.addEventListener("change", () => {
      const live = collectAnswers(step);
      step.questions.forEach((q) => {
        if (live[q.id] !== undefined) q.value = live[q.id];
      });
      renderProject();
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
      renderProject();
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
    onboardAction(() => post("api/onboard/checkpoint",
      { step_id: cp.dataset.step })));
  const approve = $("#approve-checkpoint");
  if (approve) approve.addEventListener("click", () =>
    onboardAction(() => post("api/onboard/approve",
      { step_id: approve.dataset.step })));
  const finish = $("#finish-onboarding");
  if (finish) finish.addEventListener("click", () =>
    onboardAction(() => post("api/onboard/finish", {})));
}

async function loadProject() {
  const [onboarding, project, overview] = await Promise.all(
    [api("api/onboarding"), api("api/project"), api("api/overview")]);
  onboardData = onboarding;
  projectData = { ...project, briefReady: !!overview.spec_exists };
  if (project.ready_for_scope && project.audit) {
    projectUI.acknowledged = new Set(
      (project.audit.gaps || []).map((gap) => gap.id));
  }
  renderProject();
}

/* ---------- setup (Phase 4: confirm your AI team) ---------- */
let setupData = null;                    // last /api/setup payload
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
    case "verified":
      return "Verified. You can add this client to the boss order.";
    case "needs_sign_in":
      return "Open it, complete the provider sign-in, then press Verify.";
    case "verification_unavailable":
      return "Installed, but this provider has no safe status check yet.";
    case "not_installed":
      return "Install this client first, then refresh this page.";
    default:
      return "DANZABOSS has not checked this client yet.";
  }
}

function agentCard(a, pick) {
  const selected = pick.lineup.includes(a.name);
  const canSelect = a.state === "verified";
  const launch = a.detected
    ? `<button class="connect-button" data-launch-boss="${esc(a.name)}">Connect</button>`
    : "";
  const verify = a.detected
    ? `<button class="chip" data-verify-boss="${esc(a.name)}">${a.state === "verified" ? "Verify again" : "Verify"}</button>`
    : "";
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

function bossLineup(pick, agents, activeName) {
  if (!pick.lineup.length)
    return `<div class="boss-empty"><b>No bosses chosen yet.</b>
      <span>Connect and verify an AI client above, then choose
      “Add to boss order”.</span></div>`;
  return `<ol class="boss-lineup">${pick.lineup.map((name, index) => {
    const active = name === (activeName || pick.lineup[0]);
    return `<li class="boss-card ${active ? "boss-active" : "boss-waiting"}">
      <div class="boss-rank">${index + 1}</div>
      <div class="boss-card-copy"><b>${esc(agentDisplay(name, agents))}</b>
        <span class="mono">${active ? "ACTIVE TONY-D" : "WAITING FOR ITS TURN"}</span></div>
      <div class="boss-controls">
        <button class="chip" data-move-boss="up" data-boss-name="${esc(name)}"
          ${index === 0 ? "disabled" : ""}>↑</button>
        <button class="chip" data-move-boss="down" data-boss-name="${esc(name)}"
          ${index === pick.lineup.length - 1 ? "disabled" : ""}>↓</button>
      </div>
    </li>`;
  }).join("")}</ol>`;
}

function workspacePanel(s) {
  const w = s.workspace || { host: "unconfigured", order: [] };
  const order = Array.isArray(w.order) ? w.order : [];
  if (w.host === "unconfigured")
    return panel("AI WORKSPACE", `<div class="workspace-panel workspace-empty">
      <b>ONE SHARED TERMINAL</b><span>Connect a client to open it.</span></div>`);
  const rows = order.map((name, index) => {
    const active = name === w.active_runner;
    return `<li class="workspace-pane ${active ? "workspace-active" : "workspace-waiting"}">
      <b>${index + 1}. ${esc(agentDisplay(name, s.agents))}</b>
      <span class="mono">${active ? "ACTIVE TONY-D" : "WAITING FOR ITS TURN"}</span></li>`;
  }).join("");
  const open = w.host === "tmux"
    ? `<button id="open-workspace" class="chip">OPEN WORKSPACE</button>
       <code class="workspace-attach">${esc(w.attach_command || "")}</code>`
    : `<span class="workspace-fallback">Native terminals — no shared panes.</span>`;
  return panel("AI WORKSPACE", `<div class="workspace-panel">
    <div class="workspace-head"><b>${w.host === "tmux" ? "ONE SHARED TMUX SESSION" : "NATIVE TERMINALS"}</b>
      <span class="mono">${esc(w.session || "")}</span></div>
    <ol class="workspace-panes">${rows}</ol><div class="workspace-actions">${open}</div>
  </div>`);
}

function renderSetup() {
  const s = setupData;
  const pick = setup.pick;
  const activeBoss = s.active_boss || pick.lineup[0];
  const waitingBosses = Array.isArray(s.waiting_bosses)
    ? s.waiting_bosses : pick.lineup.slice(1);
  const verified = s.agents.filter((a) => a.state === "verified").length;
  const hasOrder = pick.lineup.length > 0;
  const steps = `<div class="setup-steps" aria-label="Setup progress">
    <div class="setup-step ${verified ? "done" : "active"}"><span>1</span><b>1. Connect</b><small>Open an AI client and sign in there.</small></div>
    <div class="setup-step ${verified ? "done" : ""}"><span>2</span><b>2. Verify</b><small>Return here and confirm the connection.</small></div>
    <div class="setup-step ${hasOrder ? "done" : verified ? "active" : ""}"><span>3</span><b>3. Choose order</b><small>Pick who becomes Tony-D first.</small></div>
  </div>`;
  const hero = `<section class="boss-hero">
    <div class="boss-kicker mono">YOUR AI TEAM</div>
    <h1>WHO’S THE BOSS?</h1>
    <p class="boss-lede">Connect <b>1–4 AI clients</b>, verify them, and put
      them in order. Follow the three steps below. Only a verified client can
      become Tony-D.</p>
    ${steps}
  </section>`;
  const agents = panel("1. Connect and verify",
    `<div class="agent-grid">${s.agents.map((a) => agentCard(a, pick)).join("")}</div>
     <p class="setup-help"><b>Do this first:</b> press Connect, finish sign-in
       in the provider’s own window, return here, and press Verify. The order
       controls stay locked until a client is verified.</p>`);
  const liveMessage = setup.error
    ? `<p class="warn mono">${esc(setup.error)}</p>`
    : setup.notice
      ? `<p class="ok">${esc(setup.notice)}</p>`
      : setup.busy
        ? `<p class="dim">Working… keep this page open.</p>`
        : `<p class="dim">Waiting for your first connection.</p>`;
  const fallback = setup.fallback
    ? `<details class="connection-fallback"><summary>Terminal fallback</summary><code>${esc(setup.fallback)}</code></details>`
    : "";
  const live = `<section class="setup-live-status ${setup.error ? "is-error" : ""}"
      aria-live="polite"><div class="setup-live-label mono">LIVE UPDATE</div>
      <div class="setup-live-message">${liveMessage}${fallback}
      ${s.routing_error ? `<p class="warn mono">${esc(s.routing_error)}</p>` : ""}</div></section>`;
  const workspace = workspacePanel(s);
  const lineup = panel("2. Choose boss order", `
    <div id="boss-lineup">${bossLineup(pick, s.agents, s.active_boss)}</div>
    <p class="setup-order-note">Use the arrows to set the turn order. The
      active Tony-D model runs the specialist work; waiting models do nothing
      until their turn.</p>`);
  const team = panel("3. Save your team", `
    ${s.setup_complete ? `<p class="ok">Team confirmed — Project is
      unlocked. Confirm again any time to change it.</p>` : ""}
    <div class="ready-summary"><b>${activeBoss ? esc(agentDisplay(activeBoss, s.agents)) : "No active boss yet"}</b>
      <span>${activeBoss ? "will be Tony-D first." : "Choose at least one verified AI client above."}</span>
      <span>${waitingBosses.length ? `${waitingBosses.length} waiting in order.` : "No waiting bosses."}</span></div>
    <div class="boss-feature-choice">
      <label for="features-per-turn">Features per turn</label>
      <select id="features-per-turn">
        <option value="2"${pick.features_per_turn === 2 ? " selected" : ""}>2 recommended</option>
        <option value="3"${pick.features_per_turn === 3 ? " selected" : ""}>3</option>
        <option value="4"${pick.features_per_turn === 4 ? " selected" : ""}>4</option>
        <option value="5"${pick.features_per_turn === 5 ? " selected" : ""}>5</option>
      </select>
      <span>Choose 2–5 verified features per turn.</span>
    </div>
    <button id="confirm-team" class="boss-confirm"${hasOrder ? "" : " disabled"}>Save boss order and continue</button>`);
  $("#setup-panel").innerHTML = hero + agents + live + workspace + lineup + team;
  wireSetup();
}

async function setupAction(fn) {
  if (setup.busy) return;
  setup.busy = true;
  setup.error = "";
  setup.notice = "";
  renderSetup();
  try {
    const out = await fn();
    setupData = out.setup;
    setup.pick = initPick(setupData);
    if (!setup.notice) setup.notice = "Boss order saved.";
  } catch (e) {
    setup.error = e.message;
  }
  setup.busy = false;
  renderSetup();
}

function wireSetup() {
  const pick = setup.pick;
  const features = $("#features-per-turn");
  if (features) features.addEventListener("change", () => {
    pick.features_per_turn = Number(features.value);
    renderSetup();
  });
  $$('[data-boss-select]').forEach((box) => box.addEventListener("change", () => {
    const name = box.dataset.bossSelect;
    if (box.checked && !pick.lineup.includes(name)) pick.lineup.push(name);
    if (!box.checked) pick.lineup = pick.lineup.filter((item) => item !== name);
    renderSetup();
  }));
  $$('[data-move-boss]').forEach((button) => button.addEventListener("click", () => {
    const index = pick.lineup.indexOf(button.dataset.bossName);
    const next = button.dataset.moveBoss === "up" ? index - 1 : index + 1;
    if (index < 0 || next < 0 || next >= pick.lineup.length) return;
    [pick.lineup[index], pick.lineup[next]] = [pick.lineup[next], pick.lineup[index]];
    renderSetup();
  }));
  const confirm = $("#confirm-team");
  const launchRunner = (runner) => setupAction(async () => {
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
  const verifyRunner = (runner) => setupAction(async () => {
    const out = await post("api/connection/verify", { runner });
    setupData = await api("api/setup");
    setup.pick = initPick(setupData);
    setup.notice = out.installation && out.installation.status === "verified"
      ? "Installation verified — UI, CORTEX, project, and AI connection are working."
      : "AI connection verified. Onboarding is now available.";
    return { setup: setupData };
  });
  $$('[data-launch-boss]').forEach((button) => button.addEventListener("click", () =>
    launchRunner(button.dataset.launchBoss)));
  $$('[data-verify-boss]').forEach((button) => button.addEventListener("click", () => {
    verifyRunner(button.dataset.verifyBoss);
  }));
  if (confirm) confirm.addEventListener("click", () => {
    // 1-4 bosses (the server re-validates — it stays authoritative)
    if (!pick.lineup.length) {
      setup.error = "pick at least one agent before confirming";
      return renderSetup();
    }
    if (pick.lineup.length > 4) {
      setup.error = "the boss rotation holds at most 4 models";
      return renderSetup();
    }
    setupAction(() => post("api/setup", { lineup: pick.lineup,
      features_per_turn: pick.features_per_turn }));
  });
  const openWorkspace = $("#open-workspace");
  if (openWorkspace) openWorkspace.addEventListener("click", () =>
    setupAction(async () => {
      const out = await post("api/workspace/open", {});
      setup.notice = out.terminal.opened
        ? "Workspace opened."
        : `Use ${out.workspace.attach_command || "the terminal fallback"}.`;
      return { setup: out.setup };
    }));
}

async function loadSetup() {
  setupData = await api("api/setup");
  if (!setup.pick) setup.pick = initPick(setupData);
  renderSetup();
}

/* ---------- build (Phase 4.1: live product progress + relay controls) ---------- */
let buildData = null;              // {plan, tree, plan_md, live, setup_complete}
const build = { error: "", busy: false, advanced: false,
  additions: null, additionsRevision: null, additionsDirty: false };

// Runner ids -> plain names for event lines. The event API retains its
// internal implementation name; the catalog name is what a human reads.
const RUNNER_NAMES = { claude: "Claude Code", codex: "Codex",
  gemini: "Gemini CLI", grok: "Grok CLI", hermes: "Hermes Agent",
  opencode: "OpenCode" };
const runnerName = (n) => RUNNER_NAMES[n] || n || "the next AI";

// One friendly sentence per runtime event; raw JSONL stays under Advanced.
function friendlyEvent(e) {
  switch (e.event) {
    case "ignite":
      return `Handed the baton to ${runnerName(e.runner)} (turn ${e.turn_number}).`;
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

function teamStripHTML(live) {
  const t = live.team_state;
  if (!t) {
    const err = live.team_state_error
      ? ` <span class="warn mono">${esc(live.team_state_error)}</span>` : "";
    return `<p class="dim">No team state yet — this strip lights up once a
      build runs.${err}</p>`;
  }
  return `<div class="team-strip">
    <span><span class="dim">taking this turn</span>
      <b>${esc(runnerName(t.current_boss))}</b></span>
    <span><span class="dim">turn</span> <b>${esc(t.turn_number)}</b></span>
    <span class="chip mono">${esc(t.status)}</span>
    <span><span class="dim">verified units this turn</span>
      ${esc(t.features_completed_this_turn)} / ${esc(t.max_features_per_turn)}</span>
  </div>`;
}

function controlsHTML(live) {
  const planReady = !!(buildData.plan && !buildData.plan.error);
  const ready = !!buildData.setup_complete && planReady;
  const banner = [
    build.error ? `<p class="warn mono">${esc(build.error)}</p>` : "",
    build.busy ? `<p class="dim">working…</p>` : "",
  ].join("");
  const buttons = live.running
    ? `<p class="ok">The build crew is running.</p>
       <button id="stop-build" class="chip">Stop build</button>`
    : `<button id="start-build" class="chip"${ready ? "" : " disabled"}>
       Start build</button>${ready ? ""
       : ` <span class="dim">Finish Setup and Project to start building.</span>`}`;
  const tail = live.session.alive
    ? `<h2 class="section-label">Live session — ${esc(live.session.name)}</h2>
       <pre class="session-tail mono">${esc(live.session.tail)}</pre>`
    : "";
  const events = live.conductor.length
    ? `<h2 class="section-label">Build activity</h2>
       ${live.conductor.map((e) => `<div class="log-line">
         <span class="dim">${esc(e.ts || "")}</span> ${esc(friendlyEvent(e))}</div>`).join("")}
       <details class="advanced" id="build-advanced"${build.advanced ? " open" : ""}>
         <summary class="dim">Advanced — raw event log</summary>
         <div class="console-log mono">${live.conductor.map(logLine).join("")}</div>
       </details>`
    : `<p class="dim">No build activity yet.</p>`;
  return banner + buttons + teamStripHTML(live) + tail + events;
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

function wireBuild() {
  const start = $("#start-build");
  if (start) start.addEventListener("click", () =>
    buildAction(() => post("api/build/start", {})));
  const stop = $("#stop-build");
  if (stop) stop.addEventListener("click", () => {
    if (!window.confirm(
        "Stop the build crew? The current turn finishes safely.")) return;
    buildAction(() => post("api/build/stop", {}));
  });
  // the Advanced toggle survives SSE re-renders via the state object
  const adv = $("#build-advanced");
  if (adv) adv.addEventListener("toggle", () => { build.advanced = adv.open; });
  $$(".addition-feature input, .addition-feature textarea").forEach((input) =>
    input.addEventListener("input", () => {
      build.additions = collectBuildAdditions();
      build.additionsDirty = true;
      const approve = $("#approve-build-additions");
      if (approve) approve.disabled = true;
    }));
  const add = $("#add-build-addition");
  if (add) add.addEventListener("click", () => {
    build.additions = collectBuildAdditions();
    const nextId = Math.max(0, ...build.additions.map((feature) => feature.id),
      ...(buildData.live.features || []).map((feature) => feature.id)) + 1;
    build.additions.push(blankBuildAddition(nextId));
    build.additionsDirty = true;
    renderBuild();
  });
  $$(".remove-addition").forEach((button) => button.addEventListener("click", () => {
    build.additions = collectBuildAdditions().filter(
      (feature) => feature.id !== Number(button.dataset.featureId));
    build.additionsDirty = true;
    renderBuild();
  }));
  const save = $("#save-build-additions");
  if (save) save.addEventListener("click", () => {
    const features = collectBuildAdditions();
    const additions = buildData.live.additions;
    const body = { additions: features };
    if (additions) body.expected_revision = additions.revision;
    buildAction(async () => {
      const out = await post("api/build/additions", body);
      build.additions = null;
      build.additionsRevision = null;
      build.additionsDirty = false;
      return out;
    });
  });
  const approve = $("#approve-build-additions");
  if (approve) approve.addEventListener("click", () => {
    const additions = buildData.live.additions;
    buildAction(async () => {
      const out = await post("api/build/approve", {
        expected_revision: additions.revision,
      });
      build.additions = null;
      build.additionsRevision = null;
      build.additionsDirty = false;
      return out;
    });
  });
}

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

function blankBuildAddition(id) {
  return { id, summary: "", acceptance_criteria: [""], status: "pending" };
}

function seedBuildAdditions(live) {
  const revision = live.additions?.revision ?? null;
  if (build.additions !== null && (build.additionsDirty
      || build.additionsRevision === revision)) return;
  build.additions = live.additions
    ? live.additions.features.map((feature) => ({ ...feature,
      acceptance_criteria: [...feature.acceptance_criteria] }))
    : [blankBuildAddition(nextAdditionId(live))];
  build.additionsRevision = revision;
  build.additionsDirty = false;
}

function collectBuildAdditions() {
  return $$(".addition-feature", $("#build-panel")).map((card) => ({
    id: Number($("[name=addition-id]", card).value),
    summary: $("[name=addition-summary]", card).value.trim(),
    acceptance_criteria: $("[name=addition-criteria]", card).value
      .split("\n").map((line) => line.trim()).filter(Boolean),
    status: "pending",
  }));
}

function additionFeatureHTML(feature) {
  const remove = build.additions.length > 1
    ? `<button type="button" class="chip remove-addition"
       data-feature-id="${esc(feature.id)}">Remove</button>` : "";
  return `<article class="addition-feature" data-feature-id="${esc(feature.id)}">
    <div class="build-row"><b>Add product feature</b>${remove}</div>
    <div class="field"><label>Feature id</label><input type="number"
      name="addition-id" min="1" value="${esc(feature.id)}"></div>
    <div class="field"><label>Concise product feature</label><input type="text"
      name="addition-summary" maxlength="300" value="${esc(feature.summary)}"></div>
    <div class="field"><label>Acceptance criteria</label><textarea
      name="addition-criteria" rows="3">${esc(feature.acceptance_criteria.join("\n"))}</textarea></div>
    </article>`;
}

function additionsHTML(live) {
  seedBuildAdditions(live);
  const additions = live.additions;
  if (live.next_handoff) return panel("Approved additions", `
    <p class="ok">Exact additions revision ${esc(additions?.revision)} is approved.</p>
    <p><b>Next handoff:</b> scope revision ${esc(live.next_handoff.scope_revision)} ·
      ${esc(live.next_handoff.unit_count)} atomic units queued. Active work is unchanged
      until the safe handoff boundary.</p>`);
  const cards = build.additions.map(additionFeatureHTML).join("");
  const revision = additions
    ? `revision ${esc(additions.revision)} · ${esc(additions.approval.state)}`
    : "no additions draft saved";
  const approve = additions?.approval.state === "draft"
    ? `<button type="button" id="approve-build-additions" class="chip"
       ${build.additionsDirty ? "disabled" : ""}>Approve exact additions revision ${esc(additions.revision)}</button>` : "";
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
  const approval = live.scope.approval || {};
  const progress = live.progress || {};
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
  $("#build-controls").innerHTML = controlsHTML(buildData.live);
  let planHTML;
  if (buildData.live.scope && buildData.live.features) {
    const tree = buildData.tree.length
      ? `<ul class="plan-tree">${buildData.tree.map(taskHTML).join("")}</ul>` : "";
    const md = buildData.plan_md ? `<h2 class="section-label">plan.md</h2>
      <pre class="plan-md mono">${esc(buildData.plan_md)}</pre>` : "";
    const internals = tree || md ? `<details class="advanced build-internals">
      <summary class="dim">Advanced — internal plan artifacts</summary>${tree}${md}</details>` : "";
    planHTML = productProgressHTML(buildData.live) + internals;
  } else if (!buildData.plan) {
    planHTML = `<p class="dim">No plan yet — it appears here once
      Project scope is approved and decomposed.</p>`;
  } else if (buildData.plan.error) {
    planHTML = `<p class="warn mono">${esc(buildData.plan.error)}</p>`;
  } else {
    planHTML = productProgressHTML(buildData.live);
  }
  $("#build-panel").innerHTML = planHTML;
  wireBuild();
}

async function loadBuild() {
  const [p, live, o] = await Promise.all(
    [api("api/plan"), api("api/build"), api("api/onboarding")]);
  buildData = { plan: p.plan, tree: p.tree || [], plan_md: p.plan_md,
                live, setup_complete: !!o.setup_complete };
  renderBuild();
}

/* ---------- refresh + SSE ---------- */
async function refresh() {
  try {
    if (state.view === "overview") await loadOverview();
    else if (state.view === "project") {
      const panelEl = $("#project-panel");
      // an SSE tick must never wipe a form mid-typing or mid-AI-call
      if (onboard.busy || projectUI.busy
          || (panelEl && panelEl.contains(document.activeElement))) return;
      await loadProject();
    }
    else if (state.view === "setup") {
      const panelEl = $("#setup-panel");
      // same rule as PROJECT: a poll never wipes a half-picked team
      if (setup.busy || (panelEl && panelEl.contains(document.activeElement))) return;
      await loadSetup();
    }
    else if (state.view === "build") {
      // a poll never races a mutation or wipes a half-written addition
      const panelEl = $("#build-panel");
      if (build.busy || (panelEl && panelEl.contains(document.activeElement))) return;
      await loadBuild();
    }
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
