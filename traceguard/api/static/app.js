const state = { presets: [], selectedPreset: null, activeRunId: null, aggregate: null };
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
const pretty = (value) => escapeHtml(JSON.stringify(value, null, 2));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" }, ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || "Request failed safely.");
  return data;
}

function showMessage(message, isError = true) {
  const box = $("message");
  box.hidden = !message;
  box.textContent = message || "";
  box.style.borderColor = isError ? "var(--amber)" : "var(--teal)";
}

async function loadPresets() {
  const data = await api("/api/presets");
  state.presets = data.presets;
  const container = $("preset-list");
  container.replaceChildren();
  for (const preset of state.presets) {
    const button = document.createElement("button");
    button.className = "preset";
    button.dataset.presetId = preset.preset_id;
    const title = document.createElement("strong");
    title.textContent = preset.preset_id.replaceAll("_", " ");
    const detail = document.createElement("span");
    detail.textContent = preset.mock_erp_behavior;
    button.append(title, detail);
    button.addEventListener("click", () => selectPreset(preset));
    container.append(button);
  }
  selectPreset(state.presets[0]);
}

function selectPreset(preset) {
  state.selectedPreset = preset;
  $("order-text").value = preset.order_request_text;
  $("erp-behavior").value = preset.mock_erp_behavior;
  document.querySelectorAll(".preset").forEach((button) => {
    button.classList.toggle("active", button.dataset.presetId === preset.preset_id);
  });
  showMessage("");
}

async function runWorkflow() {
  showMessage("");
  try {
    const created = await api("/api/runs", {
      method: "POST",
      body: JSON.stringify({
        order_request_text: $("order-text").value,
        preset_id: state.selectedPreset?.preset_id || null,
        mock_erp_behavior: $("erp-behavior").value,
        extraction_provider_mode: $("extraction-mode").value,
      }),
    });
    state.activeRunId = created.run_id;
    await refreshRun();
  } catch (error) { showMessage(error.message); }
}

async function investigate() {
  try {
    await api(`/api/runs/${state.activeRunId}/investigate`, {
      method: "POST",
      body: JSON.stringify({ investigation_provider_mode: $("investigation-mode").value }),
    });
    await refreshRun();
  } catch (error) { showMessage(error.message); await refreshRun(); }
}

async function evaluateRecovery() {
  try {
    await api(`/api/runs/${state.activeRunId}/recovery/evaluate`, {
      method: "POST", body: "{}",
    });
    await refreshRun();
  } catch (error) { showMessage(error.message); }
}

async function executeRecovery() {
  try {
    await api(`/api/runs/${state.activeRunId}/recover`, {
      method: "POST", body: "{}",
    });
    await refreshRun();
  } catch (error) { showMessage(error.message); await refreshRun(); }
}

async function refreshRun() {
  if (!state.activeRunId) return;
  state.aggregate = await api(`/api/runs/${state.activeRunId}`);
  $("workspace").hidden = false;
  render(state.aggregate);
}

function render(data) {
  const run = data.run;
  $("run-id").textContent = run.run_id;
  $("workflow-state").textContent = run.workflow_state;
  $("investigation-state").textContent = run.investigation_state;
  $("recovery-state").textContent = run.recovery_state;
  $("run-facts").innerHTML = [
    ["Extraction", run.extraction_provider_mode],
    ["Investigator", run.investigation_provider_mode || "NOT RUN"],
    ["Canonical error", run.canonical_failure_code || "NONE"],
    ["Failure stage", run.failure_stage || "NONE"],
    ["ERP attempts", run.erp_attempt_count],
  ].map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
  renderActions(run);
  renderEvents(data.events);
  renderArtifacts(data.artifacts);
  renderTools(data.investigation_tool_calls, run.investigation_provider_mode);
  renderReport(data.investigation_report);
  renderPolicy(data);
}

function renderActions(run) {
  const actions = $("actions");
  actions.replaceChildren();
  if (run.investigation_state === "PENDING") addAction("Investigate failure", investigate, "primary");
  if (run.investigation_state === "COMPLETED" && run.recovery_state === "NONE") {
    addAction("Evaluate deterministic policy", evaluateRecovery, "secondary");
  }
  if (run.recovery_state === "ALLOW") addAction("Execute controlled retry", executeRecovery, "primary");
}

function addAction(label, handler, style) {
  const button = document.createElement("button");
  button.textContent = label;
  button.className = style;
  button.addEventListener("click", handler);
  $("actions").append(button);
}

function renderEvents(events) {
  $("event-list").innerHTML = events.map((event) => `
    <li data-outcome="${escapeHtml(event.outcome)}">
      <header><h3>${escapeHtml(event.event_type)}</h3><span class="pill ${event.outcome.toLowerCase()}">${escapeHtml(event.outcome)}</span></header>
      <p><strong>${escapeHtml(event.severity)}</strong> / ${escapeHtml(event.workflow_stage)} &middot; ${escapeHtml(event.details)}</p>
    </li>`).join("");
}

function renderArtifacts(artifacts) {
  $("artifact-list").innerHTML = artifacts.length ? artifacts.map((artifact) => `
    <details><summary>${escapeHtml(artifact.artifact_type)}</summary><pre>${pretty(artifact.data)}</pre></details>`).join("")
    : '<div class="empty">No stage artifacts recorded.</div>';
}

function renderTools(calls, mode) {
  $("investigator-label").textContent = mode === "SCRIPTED"
    ? "SCRIPTED - deterministic/offline investigator"
    : mode === "LIVE" ? "LIVE - OpenAI investigator" : "No investigation has run.";
  $("tool-list").innerHTML = calls.length ? calls.map((call) => `
    <article class="tool-card">
      <small>#${escapeHtml(call.sequence_number)} / ${call.succeeded ? "SUCCESS" : "FAILED"}</small>
      <h3>${escapeHtml(call.tool_name)}</h3>
      <details><summary>Arguments</summary><pre>${pretty(call.arguments)}</pre></details>
      <details><summary>Bounded result</summary><pre>${pretty(call.result || call.failure_reason)}</pre></details>
    </article>`).join("") : '<div class="empty">Actual tool calls will appear here chronologically.</div>';
}

function renderReport(report) {
  if (!report) {
    $("report").className = "empty";
    $("report").textContent = "Run an investigation to produce an evidence-grounded report.";
    return;
  }
  $("report").className = "report-grid";
  $("report").innerHTML = `
    <div><h3>Diagnosed error / category</h3><p>${escapeHtml(report.diagnosed_error_code)} / ${escapeHtml(report.failure_category)}</p></div>
    <div><h3>Root cause</h3><p>${escapeHtml(report.root_cause)}</p></div>
    <div><h3>AI recommendation</h3><p><strong>${escapeHtml(report.recommended_action)}</strong> &middot; confidence ${escapeHtml(report.confidence)}</p></div>
    <div><h3>Rationale</h3><p>${escapeHtml(report.rationale)}</p></div>
    <div><h3>Uncertainties</h3><p>${escapeHtml(report.uncertainties.join(", ") || "None stated")}</p></div>
    <div><h3>Runbook references</h3><p>${escapeHtml(report.runbook_references.join(", ") || "None")}</p></div>
    <div><h3>Evidence</h3>${report.evidence.map((item) => `
      <div class="evidence ${item.role === "TERMINAL_CAUSE" ? "causal" : ""}">
        <strong>${escapeHtml(item.role)}</strong><br>${escapeHtml(item.observation)}<br><small>${escapeHtml(item.event_id)}</small>
      </div>`).join("")}</div>`;
}

function renderPolicy(data) {
  const decision = data.recovery_decisions.at(-1);
  const execution = data.recovery_executions.at(-1);
  const recommendation = data.investigation_report?.recommended_action || "AWAITING INVESTIGATION";
  if (!decision) {
    $("policy").className = "empty";
    $("policy").textContent = "Deterministic policy has not evaluated a recommendation.";
    return;
  }
  const executionText = execution
    ? `${execution.action} / ${execution.status}${execution.erp_attempt_number ? ` / attempt ${execution.erp_attempt_number}` : ""}`
    : "NO EXECUTION";
  const review = decision.decision === "REQUIRE_REVIEW"
    ? '<div class="review-note">Input correction or human review is required. Submit corrected text as a new run.</div>' : "";
  $("policy").className = "policy-flow";
  $("policy").innerHTML = `
    <div class="policy-node"><small>AI RECOMMENDATION</small><strong>${escapeHtml(recommendation)}</strong></div>
    <div class="flow-arrow">&#8595;</div>
    <div class="policy-node"><small>DETERMINISTIC POLICY</small><strong>${escapeHtml(decision.decision)}</strong><span>${escapeHtml(decision.reason_codes.join(", "))}</span></div>
    <div class="flow-arrow">&#8595;</div>
    <div class="policy-node"><small>CONTROLLED EXECUTION</small><strong>${escapeHtml(executionText)}</strong><span>Backoff: ${escapeHtml(decision.constraints.backoff_seconds ?? "n/a")}s &middot; Max attempts: ${escapeHtml(decision.constraints.max_total_erp_attempts ?? "n/a")}</span></div>
    ${review}`;
}

$("run-button").addEventListener("click", runWorkflow);
loadPresets().catch((error) => showMessage(error.message));
