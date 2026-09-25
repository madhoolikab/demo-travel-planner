// Agentic Trip Planner Workshop -- frontend logic.
// No build step, no framework: fetch, DOM, and native EventSource (SSE).

const state = {
  config: null,
  selectedStage: null,
  selectedRequest: null,
  eventSource: null,
  counters: { modelCalls: 0, toolCalls: 0, tokens: 0, seconds: 0 },
};

const el = (id) => document.getElementById(id);

const TRACE_ICONS = {
  thought: "…", // …
  action: "→", // →
  observation: "←", // ←
  model_call: "◆", // ◆
  marker: "·", // ·
  error: "!",
  run_start: "▸", // ▸
};

// ---------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------

async function init() {
  const res = await fetch("/api/config");
  state.config = await res.json();
  state.selectedStage = state.config.stages[0].name;
  state.selectedRequest = state.config.requests[0].name;

  renderStagePicker();
  renderFlow();
  renderRequestSelect();

  el("run-btn").addEventListener("click", runSelectedStage);
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => activateTab(btn.dataset.tab));
  });

  loadHistory();
}

// ---------------------------------------------------------------------
// Stage picker + flow diagram
// ---------------------------------------------------------------------

function renderStagePicker() {
  const container = el("stage-picker");
  container.innerHTML = "";
  state.config.stages.forEach((stage) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "stage-card" + (stage.name === state.selectedStage ? " selected" : "");
    card.innerHTML = `
      <span class="stage-num">${stage.title}</span>
      <p class="stage-title">${stage.pattern}</p>
      <p class="stage-desc">${stage.one_liner}</p>
      <div class="stage-fixes">${renderFixChips(stage.fixes)}</div>
    `;
    card.addEventListener("click", () => {
      state.selectedStage = stage.name;
      renderStagePicker();
      renderFlow();
    });
    container.appendChild(card);
  });
}

function renderFixChips(fixes) {
  if (!fixes || fixes.length === 0) {
    return `<span class="chip" style="opacity:0.6;">fixes nothing yet</span>`;
  }
  const labels = {
    unknowable_facts: "unknowable facts",
    budget_overshoot: "budget overshoot",
    time_window: "time window",
    age_group: "age group",
    logistics: "logistics",
  };
  return fixes.map((f) => `<span class="chip">fixes: ${labels[f] || f}</span>`).join("");
}

function renderFlow() {
  const stage = state.config.stages.find((s) => s.name === state.selectedStage);
  const container = el("stage-flow");
  container.innerHTML = "";
  stage.flow.forEach((step, i) => {
    if (i > 0) {
      const arrow = document.createElement("span");
      arrow.className = "flow-arrow";
      arrow.textContent = "→";
      container.appendChild(arrow);
    }
    const box = document.createElement("span");
    box.className = "flow-step" + (step.loop ? " loop" : "");
    box.textContent = step.loop ? `${step.label} ↻` : step.label;
    container.appendChild(box);
  });
}

function renderRequestSelect() {
  const select = el("request-select");
  select.innerHTML = "";
  state.config.requests.forEach((req) => {
    const opt = document.createElement("option");
    opt.value = req.name;
    opt.textContent = `${req.destination} — ${req.summary.split("|")[1]?.trim() || ""}`;
    select.appendChild(opt);
  });
  select.value = state.selectedRequest;
  select.addEventListener("change", () => {
    state.selectedRequest = select.value;
  });
}

// ---------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------

function activateTab(name) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    const active = btn.dataset.tab === name;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${name}`);
  });
  if (name === "history") loadHistory();
}

function markTabReady(name) {
  const dot = el(`dot-${name}`);
  if (dot) dot.classList.add("show");
}

function clearTabDots() {
  ["itinerary", "scorecard"].forEach((name) => {
    const dot = el(`dot-${name}`);
    if (dot) dot.classList.remove("show");
  });
}

// ---------------------------------------------------------------------
// Running a stage
// ---------------------------------------------------------------------

async function runSelectedStage() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }

  resetForNewRun();
  activateTab("trace");
  setRunning(true);

  let runId;
  try {
    const res = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage: state.selectedStage, request: state.selectedRequest }),
    });
    if (!res.ok) throw new Error(`Could not start run (HTTP ${res.status})`);
    const data = await res.json();
    runId = data.run_id;
  } catch (err) {
    appendTraceRow({ type: "error", message: `Failed to start: ${err.message}` });
    setRunning(false);
    return;
  }

  const source = new EventSource(`/api/runs/${runId}/stream`);
  state.eventSource = source;

  source.addEventListener("trace", (ev) => {
    const event = JSON.parse(ev.data);
    handleTraceEvent(event);
  });

  source.addEventListener("done", (ev) => {
    const payload = JSON.parse(ev.data);
    handleDone(payload);
    source.close();
    state.eventSource = null;
  });

  source.onerror = () => {
    appendTraceRow({ type: "error", message: "Connection to the server was lost." });
    setRunning(false);
    source.close();
    state.eventSource = null;
  };
}

function resetForNewRun() {
  state.counters = { modelCalls: 0, toolCalls: 0, tokens: 0, seconds: 0 };
  updateStatTiles();
  el("trace-log").innerHTML = "";
  el("itinerary-content").innerHTML = `<div class="empty-state">Running — the itinerary will appear here once the stage finishes.</div>`;
  el("scorecard-content").innerHTML = `<div class="empty-state">Running — the scorecard will appear here once the stage finishes.</div>`;
  clearTabDots();
}

function setRunning(running) {
  el("run-btn").disabled = running;
  el("spinner").classList.toggle("active", running);
  el("run-status-text").textContent = running ? `Running ${state.selectedStage}…` : "";
}

function handleTraceEvent(event) {
  if (event.type === "model_call") {
    state.counters.modelCalls += 1;
    state.counters.tokens += (event.prompt_tokens || 0) + (event.completion_tokens || 0);
  } else if (event.type === "action") {
    state.counters.toolCalls += 1;
  }
  if (typeof event.t === "number") {
    state.counters.seconds = event.t;
  }
  updateStatTiles();
  appendTraceRow(event);
}

function updateStatTiles() {
  el("stat-model-calls").textContent = state.counters.modelCalls;
  el("stat-tool-calls").textContent = state.counters.toolCalls;
  el("stat-tokens").textContent = state.counters.tokens.toLocaleString();
  el("stat-seconds").textContent = state.counters.seconds.toFixed(1);
}

function appendTraceRow(event) {
  const log = el("trace-log");
  const row = document.createElement("div");
  row.className = `trace-row ${event.type}`;

  const icon = document.createElement("span");
  icon.className = "trace-icon";
  icon.textContent = TRACE_ICONS[event.type] || "·";
  row.appendChild(icon);

  const body = document.createElement("div");
  body.className = "trace-body";
  body.innerHTML = traceRowHtml(event);
  row.appendChild(body);

  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

function traceRowHtml(event) {
  const t = typeof event.t === "number" ? `<span class="trace-meta">t+${event.t.toFixed(1)}s</span>` : "";
  switch (event.type) {
    case "run_start":
      return `<span class="trace-label">Run started</span> ${t}`;
    case "run_end":
      return `<span class="trace-label">Run finished</span> ${t}`;
    case "marker":
      return `<span>${escapeHtml(event.label || "")}</span> ${t}`;
    case "thought": {
      const day = event.day ? ` <span class="trace-meta">[${escapeHtml(event.day)}]</span>` : "";
      return `<span class="trace-label">Thought</span>${day} ${escapeHtml(event.text || "")} ${t}`;
    }
    case "action": {
      const day = event.day ? ` <span class="trace-meta">[${escapeHtml(event.day)}]</span>` : "";
      const args = escapeHtml(JSON.stringify(event.args || {}));
      return `<span class="trace-label">Action</span>${day} <code>${escapeHtml(event.tool || "")}(${args})</code> ${t}`;
    }
    case "observation": {
      const day = event.day ? ` <span class="trace-meta">[${escapeHtml(event.day)}]</span>` : "";
      const result = escapeHtml(truncate(JSON.stringify(event.result), 300));
      return `<span class="trace-label">Observation</span>${day} <code>${result}</code> ${t}`;
    }
    case "model_call": {
      const tokens = (event.prompt_tokens || 0) + (event.completion_tokens || 0);
      return `<span class="trace-label">Model call</span> <span class="trace-meta">${escapeHtml(
        event.node || ""
      )} · +${tokens} tokens</span> ${t}`;
    }
    case "error":
      return `<span class="trace-label">Error</span> ${escapeHtml(event.message || "")} ${t}`;
    default:
      return `<span>${escapeHtml(JSON.stringify(event))}</span>`;
  }
}

function handleDone(payload) {
  setRunning(false);
  if (payload.summary) {
    state.counters.modelCalls = payload.summary.model_calls;
    state.counters.toolCalls = payload.summary.tool_calls;
    state.counters.tokens = payload.summary.total_tokens;
    state.counters.seconds = payload.summary.seconds;
    updateStatTiles();
  }
  if (payload.status === "error") {
    appendTraceRow({ type: "error", message: payload.error || "Unknown error" });
    el("itinerary-content").innerHTML = `<div class="empty-state">The run failed before producing an itinerary.</div>`;
    el("scorecard-content").innerHTML = `<div class="empty-state">The run failed before it could be scored.</div>`;
    return;
  }
  renderItinerary(payload.itinerary);
  renderScorecard(payload.scorecard);
  markTabReady("itinerary");
  markTabReady("scorecard");
  loadHistory();
}

// ---------------------------------------------------------------------
// Itinerary rendering
// ---------------------------------------------------------------------

function renderItinerary(itinerary) {
  const container = el("itinerary-content");
  if (!itinerary || !itinerary.days) {
    container.innerHTML = `<div class="empty-state">No itinerary produced.</div>`;
    return;
  }
  container.innerHTML = "";

  itinerary.days.forEach((day) => {
    const dayTotal = day.slots.reduce((sum, s) => sum + (s.cost_inr || 0), 0);
    const card = document.createElement("div");
    card.className = "day-card";

    const header = document.createElement("div");
    header.className = "day-header";
    header.innerHTML = `<span>${formatDate(day.date)}</span><span class="day-total">₹${dayTotal.toLocaleString()}</span>`;
    card.appendChild(header);

    const slots = [...day.slots].sort((a, b) => (a.start > b.start ? 1 : -1));
    slots.forEach((slot) => {
      const row = document.createElement("div");
      row.className = "slot-row";
      const cost = slot.cost_inr ? `₹${slot.cost_inr.toLocaleString()}` : "free";
      row.innerHTML = `
        <div class="slot-time">${slot.start}–${slot.end}</div>
        <div><span class="kind-badge ${slot.kind}"><span class="dot"></span>${slot.kind}</span></div>
        <div>
          <div class="slot-place">${escapeHtml(slot.place_name)}</div>
          ${slot.note ? `<div class="slot-note">${escapeHtml(slot.note)}</div>` : ""}
        </div>
        <div class="slot-cost">${cost}</div>
      `;
      card.appendChild(row);
    });

    container.appendChild(card);
  });

  const totalRow = document.createElement("div");
  totalRow.className = "itinerary-total";
  totalRow.innerHTML = `<span>Total</span><span>₹${(itinerary.total_cost_inr || 0).toLocaleString()}</span>`;
  container.appendChild(totalRow);

  if (itinerary.assumptions && itinerary.assumptions.length) {
    const assumptions = document.createElement("div");
    assumptions.className = "itinerary-assumptions";
    assumptions.innerHTML =
      "Assumptions: " + itinerary.assumptions.map(escapeHtml).join(" · ");
    container.appendChild(assumptions);
  }
}

// ---------------------------------------------------------------------
// Scorecard rendering
// ---------------------------------------------------------------------

const FAILURE_ORDER = ["unknowable_facts", "budget_overshoot", "time_window", "age_group", "logistics"];

function renderScorecard(scorecard) {
  const container = el("scorecard-content");
  if (!scorecard) {
    container.innerHTML = `<div class="empty-state">No scorecard produced.</div>`;
    return;
  }
  container.innerHTML = "";

  FAILURE_ORDER.forEach((fid) => {
    const result = scorecard.failures[fid];
    if (!result) return;
    const row = document.createElement("div");
    row.className = "score-row";
    const pillClass = result.passed ? "pass" : "fail";
    const pillText = result.passed ? "✓ pass" : "✕ fail";
    const issues = result.issues && result.issues.length
      ? `<ul>${result.issues.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`
      : "";
    row.innerHTML = `
      <span class="status-pill ${pillClass}">${pillText}</span>
      <div class="score-body">
        <div class="score-label">${escapeHtml(result.label)}</div>
        ${issues}
      </div>
    `;
    container.appendChild(row);
  });

  const overall = document.createElement("div");
  overall.className = "score-overall";
  const pillClass = scorecard.overall_pass ? "pass" : "fail";
  const pillText = scorecard.overall_pass ? "✓ all checks pass" : "✕ not all checks pass";
  overall.innerHTML = `<span class="status-pill ${pillClass}">${pillText}</span>`;
  container.appendChild(overall);
}

// ---------------------------------------------------------------------
// History
// ---------------------------------------------------------------------

async function loadHistory() {
  const container = el("history-content");
  try {
    const res = await fetch("/api/history");
    const data = await res.json();
    renderHistory(data.runs || []);
  } catch (err) {
    container.innerHTML = `<div class="empty-state">Could not load history.</div>`;
  }
}

function renderHistory(runs) {
  const container = el("history-content");
  if (!runs.length) {
    container.innerHTML = `<div class="empty-state">No runs yet. Run a stage to see it here.</div>`;
    return;
  }
  const sorted = [...runs].sort((a, b) => (a.saved_at < b.saved_at ? 1 : -1));
  const rows = sorted
    .map((r) => {
      const s = r.summary || {};
      const sc = r.scorecard;
      const resultCell = sc
        ? `<span class="status-pill ${sc.overall_pass ? "pass" : "fail"}">${sc.overall_pass ? "✓ pass" : "✕ fail"}</span>`
        : "–";
      return `
        <tr>
          <td>${escapeHtml(r.stage || "")}</td>
          <td>${escapeHtml(r.request_name || "")}</td>
          <td>${formatTimestamp(r.saved_at)}</td>
          <td class="num">${s.model_calls ?? "–"}</td>
          <td class="num">${(s.total_tokens ?? 0).toLocaleString()}</td>
          <td class="num">${s.seconds != null ? s.seconds.toFixed(1) : "–"}</td>
          <td>${resultCell}</td>
        </tr>
      `;
    })
    .join("");

  container.innerHTML = `
    <table class="history-table">
      <thead>
        <tr>
          <th>Stage</th><th>Trip</th><th>Saved</th>
          <th>Calls</th><th>Tokens</th><th>Seconds</th><th>Result</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function truncate(str, n) {
  if (!str) return "";
  return str.length > n ? str.slice(0, n - 1) + "…" : str;
}

function formatDate(isoDate) {
  const d = new Date(`${isoDate}T00:00:00`);
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

function formatTimestamp(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

init();
