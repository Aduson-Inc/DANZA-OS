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

/* ---------- onboard (Phase 3: live forms + the grill) ---------- */
let onboardData = null;                       // last /api/onboarding payload
const onboard = { edit: null, error: "", busy: false };

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
  const label = rec.resolution ? "user-decided" : rec.degraded ? "degraded"
    : rec.needs_user_decision ? "escalated" : rec.clear ? "clear"
    : `grill ${rec.rounds.length}/3`;
  const tone = rec.clear || rec.resolution ? "" : " warn-chip";
  return ` <span class="chip mono${tone}">${esc(label)}</span>`;
}

function interviewPanel(step) {
  const rec = step.interview;
  const last = rec.rounds[rec.rounds.length - 1]
    || { ambiguities: [], follow_up_questions: [] };
  const ambis = last.ambiguities.map((a) => `<li>${esc(a)}</li>`).join("");
  if (rec.needs_user_decision) {
    return panel(`The grill — ${step.title} needs your decision`, `
      <p class="warn">Still unclear after ${rec.rounds.length} rounds.
      Open ambiguities:</p><ul>${ambis}</ul>
      <form id="resolve-form" data-step="${esc(step.id)}">
        <div class="field"><label>Your decision (final — the build follows
        it verbatim)</label><textarea name="decision" rows="3"></textarea></div>
        <button type="submit" class="chip">Decide</button></form>`);
  }
  const qs = last.follow_up_questions.map((q) => `
    <div class="field"><label>${esc(q)}</label>
    <textarea data-fq="${esc(q)}" rows="2"></textarea></div>`).join("");
  return panel(`The grill — ${step.title} (round ${rec.rounds.length}/3)`, `
    ${ambis ? `<p class="dim">Ambiguities found:</p><ul>${ambis}</ul>` : ""}
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
      ${v.degraded ? `<p class="warn">Degraded:
        ${esc(v.degraded_reason || "boss CLI unreachable")}</p>` : ""}
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
    `<p class="dim">Seed idea captured — seed projects do not compile a
     build spec.</p>`);
  return panel("Finish — compile spec + plan", `
    <p>All steps complete. Compiling writes <span class="mono">.danza/spec.md</span>
    and asks the boss for a validated task plan (may take a few minutes).</p>
    <button id="finish-onboarding" class="chip">Compile spec + plan</button>`);
}

function activeStep(o) {
  if (onboard.edit) return o.steps.find((s) => s.id === onboard.edit);
  if (o.blocking_phase) return o.steps.find((s) => s.id === o.blocking_phase);
  return o.steps.find((s) => s.id === o.current_step);
}

function renderOnboard() {
  const o = onboardData;
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
    onboard.busy ? `<p class="dim">working — the boss is thinking…</p>` : "",
    o.boss_available ? "" : `<p class="warn">No headless boss runner
      configured — AI review and the grill run degraded. Run
      <code>danza runners .</code></p>`].join("");
  $("#onboard-panel").innerHTML = `<table class="kv">
    ${row("project type", esc(o.project_type ?? "not chosen yet"))}
    ${row("answers stored", esc(o.answered))}
    ${row("complete", o.complete ? "yes" : "no")}
  </table>${banner}
  <table class="sessions-table"><thead>
    <tr><th>step</th><th>title</th><th>kind</th><th>status</th></tr></thead>
    <tbody>${steps}</tbody></table>${main}`;
  wireOnboard(step, o);
}

async function onboardAction(fn) {
  if (onboard.busy) return;
  onboard.busy = true;
  onboard.error = "";
  renderOnboard();
  try {
    const out = await fn();
    onboard.edit = null;
    onboardData = out.onboarding;
  } catch (e) {
    onboard.error = e.message;
  }
  onboard.busy = false;
  renderOnboard();
}

function wireOnboard(step, o) {
  $$(".edit-step").forEach((b) => b.addEventListener("click", () => {
    onboard.edit = b.dataset.step;
    renderOnboard();
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
      renderOnboard();
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
      renderOnboard();
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
    onboardAction(async () => {
      const out = await post("api/onboard/finish", {});
      $$(".tab[data-view]").find((b) => b.dataset.view === "build")?.click();
      return out;
    }));
}

async function loadOnboard() {
  onboardData = await api("api/onboarding");
  renderOnboard();
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
    else if (state.view === "onboard") {
      const panelEl = $("#onboard-panel");
      // an SSE tick must never wipe a form mid-typing or mid-AI-call
      if (onboard.busy || (panelEl && panelEl.contains(document.activeElement))) return;
      await loadOnboard();
    }
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
