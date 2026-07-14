/* DANZA-OS dashboard — vanilla JS, no build step. OVERVIEW is live;
   SETUP confirms the AI team (Phase 4); ONBOARD runs the wizard + the
   grill (Phase 3, locked until setup completes); BUILD starts/stops the
   relay and shows live team state over the plan (Phase 4). */
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

/* P4 T11: plain name for a fixed driver id — "jonathan-builder" ->
   "Jonathan (builder)", "tony-d-orchestrator" -> "Tony D (orchestrator)". */
function driverName(id) {
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
    row(esc(driverName(id)),
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
  $("#profile-chip").textContent = o.profile.name;
  $("#overview-grid").innerHTML =
    projectPanel(o) + teamPanel(o) + planPanel(o) + cortexPanel(o) +
    tokensPanel(o);
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
  // a round can list ambiguities without follow-up questions — offer a
  // generic response field so the grill never dead-ends
  const qs = last.follow_up_questions.length
    ? last.follow_up_questions.map((q) => `
      <div class="field"><label>${esc(q)}</label>
      <textarea data-fq="${esc(q)}" rows="2"></textarea></div>`).join("")
    : `<div class="field"><label>Your response to the ambiguities above</label>
      <textarea data-fq="response" rows="2"></textarea></div>`;
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
  // Hard setup-first gate (Phase 4 Decision 1): the server 409s every
  // onboarding write until the team is confirmed — render that honestly.
  if (!o.setup_complete) {
    $("#onboard-panel").innerHTML = `<div class="locked">
      <h3>Set up your AI team first</h3>
      <p class="dim">Onboarding unlocks once your team is confirmed —
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

/* ---------- setup (Phase 4: confirm your AI team) ---------- */
let setupData = null;                    // last /api/setup payload
const setup = { pick: null, error: "", notice: "", busy: false };

// Seat work types -> plain-English names + one-sentence job descriptions
// (Phase 4 Decision 9: no jargon on the SETUP tab).
const SEAT_INFO = {
  conductor: ["Conductor", "Passes finished work to the next AI."],
  plan:      ["Planner", "Turns your idea into a build plan."],
  build:     ["Builder", "Writes the code."],
  map:       ["Mapper", "Keeps the map of your codebase current."],
  qa:        ["Tester", "Checks that finished features really work."],
  review:    ["Reviewer", "Tracks decisions and catches the team looping."],
  research:  ["Researcher", "Looks things up before the team commits."],
  design:    ["Designer", "Handles the look — colors, fonts, layout."],
  security:  ["Security Checker", "Reviews the work for security problems."],
};

const SEAT_VERBS = {
  plan: "plan", build: "build", map: "map the codebase", qa: "test",
  review: "review decisions", research: "research",
  design: "design", security: "check security",
};

function initPick(s) {
  return { seats: { conductor: "builtin", ...s.seats },
           dial: s.dial, overrides: { ...s.overrides } };
}

function agentChip(a) {
  if (a.detected && a.auth === "unauthenticated")
    return `<span class="chip mono chip-bad">Found, not logged in</span>`;
  if (a.detected && a.auth === "ok")
    return `<span class="chip mono chip-ok">Connected</span>`;
  if (a.detected) return `<span class="chip mono chip-dim">Found</span>`;
  return `<span class="chip mono dim">Not installed</span>`;
}

function agentCard(a) {
  return `<div class="agent-card${a.detected ? "" : " dim"}">
    <div class="agent-head"><b>${esc(a.display_name)}</b>${agentChip(a)}</div>
    <p class="dim">${esc((a.strengths || []).join(" · "))}</p></div>`;
}

// Seatable = detected and not known to be logged out ("unprobed" counts) —
// mirrors routing._connected so the pickers and the server agree.
const seatable = (agents) =>
  agents.filter((a) => a.detected && a.auth !== "unauthenticated");

function seatRow(seat, agents, pick) {
  const [label, blurb] = SEAT_INFO[seat];
  const current = pick.seats[seat] ?? "";
  const opts = seatable(agents).map((a) =>
    `<option value="${esc(a.name)}"${a.name === current ? " selected" : ""}>
     ${esc(a.display_name)}</option>`).join("");
  const builtin = seat === "conductor"
    ? `<option value="builtin"${current === "builtin" ? " selected" : ""}>
       Built-in (recommended)</option>` : "";
  return `<div class="seat-row">
    <div class="seat-name"><b>${esc(label)}</b>
      <span class="dim">${esc(blurb)}</span></div>
    <select data-seat="${esc(seat)}">${builtin}${current || builtin ? ""
      : '<option value="" selected disabled>choose…</option>'}${opts}</select>
  </div>`;
}

function dialCard(value, title, blurb, pick) {
  return `<button class="dial-card${pick.dial === value ? " active" : ""}"
    data-dial="${value}"><b>${title}</b><span>${blurb}</span></button>`;
}

function overrideRows(s, pick) {
  return Object.entries(s.floors).map(([driver, floor]) => `
    <div class="field"><label>${esc(driver)}
      <span class="dim">(minimum ${esc(floor)})</span></label>
    <input type="number" data-override="${esc(driver)}" min="${esc(floor)}"
      value="${esc(pick.overrides[driver] ?? "")}"
      placeholder="dial default"></div>`).join("");
}

// The confirm payload's lineup: every distinct agent holding a seat, in
// seat order (the server makes lineup[0] the boss, so the conductor —
// when it is a real runner — or the planner leads).
function pickLineup(pick) {
  const lineup = [];
  for (const seat of Object.keys(SEAT_INFO)) {
    const who = pick.seats[seat];
    if (who && who !== "builtin" && !lineup.includes(who)) lineup.push(who);
  }
  return lineup;
}

function teamSentences(pick, agents) {
  const nameOf = (n) =>
    (agents.find((a) => a.name === n) || { display_name: n }).display_name;
  const jobs = new Map();
  for (const [seat, verb] of Object.entries(SEAT_VERBS)) {
    const who = pick.seats[seat];
    if (!who) continue;
    if (!jobs.has(who)) jobs.set(who, []);
    jobs.get(who).push(verb);
  }
  const list = (v) => v.length > 1
    ? `${v.slice(0, -1).join(", ")} and ${v[v.length - 1]}` : v[0];
  const lines = [...jobs].map(([who, verbs]) =>
    `${nameOf(who)} will ${list(verbs)}.`);
  if (pick.seats.conductor === "builtin") {
    lines.push("The built-in conductor passes finished work to the next AI.");
  } else if (pick.seats.conductor) {
    lines.push(`${nameOf(pick.seats.conductor)} will conduct the relay.`);
  }
  return lines;
}

function renderSetup() {
  const s = setupData;
  const pick = setup.pick;
  const banner = [
    setup.error ? `<p class="warn mono">${esc(setup.error)}</p>` : "",
    setup.notice ? `<p class="ok">${esc(setup.notice)}</p>` : "",
    setup.busy ? `<p class="dim">saving your team…</p>` : "",
    s.routing_error ? `<p class="warn mono">${esc(s.routing_error)}</p>` : "",
    s.budgets_error ? `<p class="warn mono">${esc(s.budgets_error)}</p>` : "",
  ].join("");
  const agents = panel("Your AI agents",
    `<div class="agent-grid">${s.agents.map(agentCard).join("")}</div>
     <p class="dim">Log in to an agent in your terminal, then come back —
     this list updates on its own.</p>`);
  const seats = seatable(s.agents).length
    ? panel("Who does what",
        Object.keys(SEAT_INFO).map((k) => seatRow(k, s.agents, pick)).join(""))
    : panel("Who does what", `<p class="dim">No agents are connected yet —
        install and log in to at least one AI CLI above.</p>`);
  const dial = panel("Power", `<div class="dial-row">
    ${dialCard("normal", "Normal (recommended)",
               "Balanced memory for every seat — right for most projects.", pick)}
    ${dialCard("full_power", "Full Power",
               "Twice the memory for every seat — better recall, higher token cost.", pick)}
    </div>`);
  const advanced = `<details class="panel advanced"><summary>Advanced</summary>
    <p class="dim">Per-role memory budgets in tokens. Leave blank to use the
    dial. Per-seat model and effort overrides arrive with safe flags.</p>
    ${overrideRows(s, pick)}</details>`;
  const sentences = teamSentences(pick, s.agents);
  const team = panel("Your team", `
    ${s.setup_complete ? `<p class="ok">Team confirmed — onboarding is
      unlocked. Confirm again any time to change it.</p>` : ""}
    ${sentences.length
      ? sentences.map((t) => `<p>${esc(t)}</p>`).join("")
      : `<p class="dim">Pick at least one agent to see your team.</p>`}
    <button id="confirm-team" class="chip">Confirm team</button>`);
  $("#setup-panel").innerHTML = banner + agents + seats + dial + advanced + team;
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
    setup.notice = "Team saved.";
  } catch (e) {
    setup.error = e.message;
  }
  setup.busy = false;
  renderSetup();
}

function wireSetup() {
  const pick = setup.pick;
  $$("[data-seat]").forEach((sel) => sel.addEventListener("change", () => {
    pick.seats[sel.dataset.seat] = sel.value;
    renderSetup();                       // team sentences follow the seats
  }));
  $$("[data-dial]").forEach((b) => b.addEventListener("click", () => {
    pick.dial = b.dataset.dial;
    renderSetup();
  }));
  $$("[data-override]").forEach((inp) => inp.addEventListener("change", () => {
    const v = parseInt(inp.value, 10);
    if (Number.isFinite(v)) pick.overrides[inp.dataset.override] = v;
    else delete pick.overrides[inp.dataset.override];
  }));
  const confirm = $("#confirm-team");
  if (confirm) confirm.addEventListener("click", () => {
    const lineup = pickLineup(pick);
    // 1-5 agents (the server re-validates — it stays authoritative)
    if (!lineup.length) {
      setup.error = "pick at least one agent before confirming";
      return renderSetup();
    }
    if (lineup.length > 5) {
      setup.error = "a team holds at most 5 agents — share some seats";
      return renderSetup();
    }
    setupAction(() => post("api/setup", {
      lineup, seats: pick.seats, dial: pick.dial,
      overrides: pick.overrides }));
  });
}

async function loadSetup() {
  setupData = await api("api/setup");
  if (!setup.pick) setup.pick = initPick(setupData);
  renderSetup();
}

/* ---------- build (Phase 4: relay controls + live state) ---------- */
let buildData = null;              // {plan, tree, plan_md, live, setup_complete}
const build = { error: "", busy: false, advanced: false };

// Runner ids -> plain names for event lines (the conductor logs internal
// ids; the catalog's display_name is what a human should read).
const RUNNER_NAMES = { claude: "Claude Code", codex: "Codex",
  gemini: "Gemini CLI", grok: "Grok CLI", opencode: "OpenCode" };
const runnerName = (n) => RUNNER_NAMES[n] || n || "the next AI";

// One friendly sentence per conductor event (Phase 4 Decision 9: plain
// English first — the raw JSONL stays behind the Advanced toggle).
function friendlyEvent(e) {
  switch (e.event) {
    case "ignite":
      return `Handed the baton to ${runnerName(e.runner)} (turn ${e.turn_number}).`;
    case "session_end":
      return e.orphaned_turn
        ? `A session died mid-turn (turn ${e.turn_number}) — the conductor is watching.`
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
    <span><span class="dim">features this turn</span>
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
       : ` <span class="dim">Finish Setup and Onboarding to start building.</span>`}`;
  const tail = live.session.alive
    ? `<h2 class="section-label">Live session — ${esc(live.session.name)}</h2>
       <pre class="session-tail mono">${esc(live.session.tail)}</pre>`
    : "";
  const events = live.conductor.length
    ? `<h2 class="section-label">What the conductor did</h2>
       ${live.conductor.map((e) => `<div class="log-line">
         <span class="dim">${esc(e.ts || "")}</span> ${esc(friendlyEvent(e))}</div>`).join("")}
       <details class="advanced" id="build-advanced"${build.advanced ? " open" : ""}>
         <summary class="dim">Advanced — raw event log</summary>
         <div class="console-log mono">${live.conductor.map(logLine).join("")}</div>
       </details>`
    : `<p class="dim">No conductor activity yet.</p>`;
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

function renderBuild() {
  $("#build-controls").innerHTML = controlsHTML(buildData.live);
  // plan tree below the controls — rendering unchanged since Phase 2
  let planHTML;
  if (!buildData.plan) {
    planHTML = `<p class="dim">No plan yet — the BUILD tab
      arms once onboarding compiles spec.md and planning writes plan.json.</p>`;
  } else if (buildData.plan.error) {
    planHTML = `<p class="warn mono">${esc(buildData.plan.error)}</p>`;
  } else {
    const tree = buildData.tree.length
      ? `<ul class="plan-tree">${buildData.tree.map(taskHTML).join("")}</ul>` : "";
    const md = buildData.plan_md ? `<h2 class="section-label">plan.md</h2>
      <pre class="plan-md mono">${esc(buildData.plan_md)}</pre>` : "";
    planHTML = tree + md;
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
    else if (state.view === "onboard") {
      const panelEl = $("#onboard-panel");
      // an SSE tick must never wipe a form mid-typing or mid-AI-call
      if (onboard.busy || (panelEl && panelEl.contains(document.activeElement))) return;
      await loadOnboard();
    }
    else if (state.view === "setup") {
      const panelEl = $("#setup-panel");
      // same rule as ONBOARD: a poll never wipes a half-picked team
      if (setup.busy || (panelEl && panelEl.contains(document.activeElement))) return;
      await loadSetup();
    }
    else if (state.view === "build") {
      // a poll never races a start/stop click mid-flight
      if (build.busy) return;
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
