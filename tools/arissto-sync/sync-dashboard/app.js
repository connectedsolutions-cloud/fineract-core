const state = { runs: [], selected: null, detail: null, page: 1, pageSize: 75, launch: null };
const $ = (selector) => document.querySelector(selector);

const escapeHtml = (value = "") => String(value).replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
})[char]);

function localTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function duration(start, end) {
  if (!start) return "—";
  const seconds = Math.max(0, Math.round((new Date(end || Date.now()) - new Date(start)) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${seconds % 60}s`;
  return `${seconds}s`;
}

function compactId(value = "") { return value ? `${value.slice(0, 8)}…` : "—"; }

function itemCount(value) {
  return Number.isInteger(value) ? new Intl.NumberFormat().format(value) : "—";
}

async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function launchError(message) {
  const target = $("#launchError");
  if (target) target.innerHTML = `<div class="error-banner">${escapeHtml(message)}</div>`;
}

function renderLaunchSetup() {
  const options = state.launch.options;
  const hasActiveRun = (options.active_runs || []).length > 0;
  const suggested = options.suggested_cycle || {};
  const existingRequest = state.launch.request || {};
  $("#launchContent").innerHTML = `
    <div class="launch-step"><span>1</span><div><strong>Set up a fresh/clean run</strong><p>This mode requires a newly restored local Fineract baseline and a new sync cycle.</p></div></div>
    <div class="launch-form">
      <label><span>Workflow</span><select id="launchWorkflow">${options.workflows.map((workflow) => `<option value="${escapeHtml(workflow.id)}" ${workflow.ready ? "" : "disabled"} ${workflow.default && workflow.ready ? "selected" : ""}>${escapeHtml(workflow.id)}${workflow.ready ? "" : " — not ready"}</option>`).join("")}</select></label>
      <p id="workflowDescription" class="field-help"></p>
      <fieldset class="service-fieldset"><legend>Include in this run</legend><p>Choose the outcomes you want. Required prerequisites are added automatically and cannot be removed while a dependent service is checked.</p><div id="servicePicker" class="service-picker"></div><div id="serviceSelectionSummary" class="selection-summary"></div></fieldset>
      <label><span>Fresh/clean sync cycle</span><input id="launchCycle" value="${escapeHtml(existingRequest.cycle_id || suggested.id)}" ${state.launch.cycleCreated ? "disabled" : ""} /><small>Creates new tracking state after the target baseline is restored. Creating the cycle alone does not clean Fineract.</small></label>
      <label><span>Baseline reference</span><input id="launchBaseline" value="${escapeHtml(existingRequest.baseline_ref || suggested.baseline_ref)}" ${state.launch.cycleCreated ? "disabled" : ""} /><small>Name the snapshot or restore point currently loaded in local Fineract.</small></label>
      <label><span>Accounting cutoff <em>optional</em></span><input id="launchCutoff" type="date" /><small>Leave blank to use the plan creation date in America/El_Salvador.</small></label>
      <label><span>Ledger source period <em>optional</em></span><input id="launchAccountingPeriod" value="${escapeHtml(existingRequest.accounting_period || "")}" placeholder="Leave blank for full ledger" /><small>When the planned ledger service is selected, blank runs the complete pre-cutoff ledger; enter a period only to narrow the test.</small></label>
      <div class="reset-option">
        <label class="baseline-confirm"><input id="resetTarget" type="checkbox" ${existingRequest.reset_target ? "checked" : ""} ${state.launch.cycleCreated ? "disabled" : ""} /><span><strong>Restore the local Fineract baseline now</strong><small>Use this unless the whole disposable tenant was already restored immediately before this fresh/clean run.</small></span></label>
        <div id="resetFields" class="reset-fields ${existingRequest.reset_target ? "" : "hidden"}">
          <label><span>Disposable tenant</span><input id="resetTenant" value="${escapeHtml(existingRequest.reset_tenant || "sandbox")}" ${state.launch.cycleCreated ? "disabled" : ""} /></label>
          <label><span>Reset confirmation</span><input id="resetConfirmation" placeholder="sandbox:fineract_sandbox" value="${escapeHtml(existingRequest.reset_confirmation || "")}" autocomplete="off" ${state.launch.cycleCreated ? "disabled" : ""} /><small>Enter the exact TENANT:DATABASE value required by the reset tool.</small></label>
        </div>
      </div>
      <label id="baselineConfirmRow" class="baseline-confirm"><input id="baselineConfirm" type="checkbox" ${state.launch.cycleCreated ? "checked disabled" : ""} /><span>${state.launch.cycleCreated ? "Fresh/clean cycle created for this verified baseline." : "I confirm the whole disposable Fineract tenant was restored immediately before this run and contains no earlier sync data."}</span></label>
    </div>
    ${hasActiveRun ? '<div class="warning-banner"><strong>A workflow is already active.</strong><span>Wait for it to finish before starting a fresh/clean cycle.</span></div>' : ""}
    <div class="launch-safety"><strong>Review before launch.</strong><span>We create the cycle and prepare the local plan first. Approving that reviewed plan immediately launches the sync. Arissto remains read-only.</span></div>
    <div id="launchError"></div>
    <div class="dialog-actions"><button class="secondary-button" value="cancel">Cancel</button><button id="preparePlanButton" class="primary-button" type="button" disabled>${state.launch.cycleCreated ? "Prepare plan" : "Create cycle & prepare plan"}</button></div>`;

  const updateWorkflow = () => {
    const workflow = options.workflows.find((item) => item.id === $("#launchWorkflow").value);
    $("#workflowDescription").textContent = workflow?.description || "";
    if (!state.launch.requestedServices || state.launch.workflowId !== workflow?.id) {
      state.launch.requestedServices = new Set();
      state.launch.workflowId = workflow?.id;
    }
    renderServicePicker(workflow);
  };
  const updateResetChoice = () => {
    const resetting = $("#resetTarget").checked;
    $("#resetFields").classList.toggle("hidden", !resetting);
    $("#baselineConfirmRow").classList.toggle("hidden", resetting);
    $("#baselineConfirm").disabled = resetting || state.launch.cycleCreated;
    ["#resetTenant", "#resetConfirmation"].forEach((selector) => {
      const input = $(selector);
      if (input) input.disabled = !resetting || state.launch.cycleCreated;
    });
    updatePrepareAvailability();
  };
  $("#launchWorkflow").addEventListener("change", updateWorkflow);
  $("#baselineConfirm").addEventListener("change", updatePrepareAvailability);
  $("#resetTarget").addEventListener("change", updateResetChoice);
  $("#resetTenant").addEventListener("input", updatePrepareAvailability);
  $("#resetConfirmation").addEventListener("input", updatePrepareAvailability);
  $("#launchAccountingPeriod").addEventListener("input", updatePrepareAvailability);
  updateWorkflow();
  updateResetChoice();
  $("#preparePlanButton").addEventListener("click", preparePlan);
}

function dependencyClosure(workflow, requested) {
  const byId = new Map((workflow?.services || []).map((service) => [service.id, service]));
  const included = new Set();
  const include = (serviceId) => {
    if (included.has(serviceId)) return;
    const service = byId.get(serviceId);
    if (!service) return;
    (service.depends_on || []).forEach(include);
    included.add(serviceId);
  };
  requested.forEach(include);
  return included;
}

function updatePrepareAvailability() {
  const workflow = state.launch.options.workflows.find((item) => item.id === $("#launchWorkflow")?.value);
  const included = dependencyClosure(workflow, state.launch.requestedServices || new Set());
  const resetting = $("#resetTarget")?.checked;
  const tenant = $("#resetTenant")?.value.trim() || "";
  const resetConfirmation = $("#resetConfirmation")?.value.trim() || "";
  const confirmed = resetting
    ? tenant !== "default" && /^[A-Za-z][A-Za-z0-9_-]*$/.test(tenant) && resetConfirmation.startsWith(`${tenant}:`)
    : $("#baselineConfirm")?.checked;
  const active = (state.launch.options.active_runs || []).length > 0;
  const ledgerPeriod = $("#launchAccountingPeriod")?.value.trim() || "";
  const ledgerPeriodReady = !ledgerPeriod || /^[0-9A-Za-z_-]{1,64}$/.test(ledgerPeriod);
  if ($("#preparePlanButton")) $("#preparePlanButton").disabled = !included.size || !confirmed || active || !ledgerPeriodReady;
}

function renderServicePicker(workflow) {
  const requested = state.launch.requestedServices;
  const included = dependencyClosure(workflow, requested);
  const services = workflow?.services || [];
  $("#servicePicker").innerHTML = services.map((service) => {
    const selected = included.has(service.id);
    const required = selected && !requested.has(service.id);
    return `<label class="service-option ${selected ? "selected" : ""} ${required ? "required" : ""}">
      <input type="checkbox" value="${escapeHtml(service.id)}" ${selected ? "checked" : ""} ${required ? "disabled" : ""} />
      <span class="check-visual">✓</span><span class="service-option-copy"><strong>${escapeHtml(service.name)}</strong><small>${required ? "Required prerequisite" : service.status !== "available" ? "Executable with readiness warning" : "Optional outcome"}</small></span>
    </label>`;
  }).join("");
  document.querySelectorAll("#servicePicker input:not(:disabled)").forEach((input) => input.addEventListener("change", () => {
    if (input.checked) requested.add(input.value); else requested.delete(input.value);
    renderServicePicker(workflow);
  }));
  const requestedNames = services.filter((service) => requested.has(service.id)).map((service) => service.name);
  const prerequisiteCount = included.size - requested.size;
  $("#serviceSelectionSummary").innerHTML = included.size
    ? `<strong>${included.size} services will run</strong><span>${escapeHtml(requestedNames.join(", "))}${prerequisiteCount ? ` + ${prerequisiteCount} prerequisite${prerequisiteCount === 1 ? "" : "s"}` : ""}</span>`
    : '<strong>Nothing selected</strong><span>Check at least one service to continue.</span>';
  updatePrepareAvailability();
}

async function openLaunchDialog() {
  const dialog = $("#launchDialog");
  dialog.showModal();
  $("#launchContent").innerHTML = '<div class="dialog-loading">Checking open cycles and workflows…</div>';
  try {
    state.launch = { options: await api("/api/launch/options"), plan: null, cycleCreated: false };
    renderLaunchSetup();
  } catch (error) {
    $("#launchContent").innerHTML = `<div class="error-banner">${escapeHtml(error.message)}</div>`;
  }
}

async function preparePlan() {
  const button = $("#preparePlanButton");
  button.disabled = true;
  button.textContent = "Preparing plan…";
  const request = {
    workflow_id: $("#launchWorkflow").value,
    cycle_id: $("#launchCycle").value,
    baseline_ref: $("#launchBaseline").value,
    cutoff_date: $("#launchCutoff").value,
    accounting_period: $("#launchAccountingPeriod").value.trim(),
    services: Array.from(state.launch.requestedServices),
    reset_target: $("#resetTarget").checked,
    reset_tenant: $("#resetTenant").value.trim(),
    reset_confirmation: $("#resetConfirmation").value.trim(),
  };
  try {
    state.launch.request = request;
    if (!state.launch.cycleCreated) {
      button.textContent = request.reset_target ? "Resetting Fineract…" : "Creating cycle…";
      await api("/api/sync-cycles", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Launch-Token": state.launch.options.launch_token },
        body: JSON.stringify({
          cycle_id: request.cycle_id,
          baseline_ref: request.baseline_ref,
          confirmation: state.launch.options.cycle_confirmation,
          reset_target: request.reset_target,
          reset_tenant: request.reset_tenant,
          reset_confirmation: request.reset_confirmation,
        }),
      });
      state.launch.cycleCreated = true;
      button.textContent = "Preparing plan…";
    }
    const plan = await api("/api/workflow-plans", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Launch-Token": state.launch.options.launch_token },
      body: JSON.stringify(request),
    });
    state.launch.plan = plan;
    renderPlanReview();
  } catch (error) {
    launchError(`${state.launch.cycleCreated ? "The fresh cycle was created, but the plan was not prepared. " : ""}${error.message}`);
    button.disabled = false;
    button.textContent = state.launch.cycleCreated ? "Retry plan" : "Create cycle & prepare plan";
  }
}

function renderPlanReview() {
  const { plan } = state.launch;
  const warnings = plan.readiness?.warnings || [];
  $("#launchContent").innerHTML = `
    <div class="launch-step"><span>2</span><div><strong>Review and launch</strong><p>The plan passed preflight and is saved. Approving it starts the detached workflow immediately against local Fineract.</p></div></div>
    <div class="plan-review">
      <div><span>Workflow</span><strong>${escapeHtml(plan.workflow_id)}</strong></div>
      <div><span>Cycle</span><strong>${escapeHtml(state.launch.request.cycle_id)}</strong></div>
      <div><span>Cutoff</span><strong>${escapeHtml(plan.accounting_cutoff?.date || "—")}</strong></div>
      <div><span>Target</span><strong>Local only</strong></div>
      <div><span>Baseline reset</span><strong>${state.launch.request.reset_target ? `Completed · ${escapeHtml(state.launch.request.reset_tenant)}` : "Already restored"}</strong></div>
    </div>
    <div class="service-sequence"><span>Service sequence</span><div>${(plan.ordered_services || []).map((service, index) => `<span><b>${index + 1}</b>${escapeHtml(service)}</span>`).join("")}</div></div>
    <p class="selection-note">Requested: ${(plan.definition?.selection?.requested_services || plan.ordered_services || []).map(escapeHtml).join(", ")}. Prerequisites are frozen into this plan.</p>
    ${warnings.length ? `<div class="warning-banner"><strong>${warnings.length} readiness warning${warnings.length === 1 ? "" : "s"}</strong><span>${warnings.map((warning) => `${escapeHtml(warning.service_id)}: ${escapeHtml(warning.code)}`).join(" · ")}</span></div>` : '<div class="success-banner">No workflow readiness warnings.</div>'}
    <label class="confirm-row"><input id="launchConfirm" type="checkbox" /><span>I understand this will write synchronized records to the selected <strong>local</strong> Fineract target.</span></label>
    <div id="launchError"></div>
    <div class="dialog-actions"><button id="backToSetup" class="secondary-button" type="button">Back</button><button id="startRunButton" class="danger-button" type="button" disabled>Launch local sync</button></div>`;
  $("#backToSetup").addEventListener("click", renderLaunchSetup);
  $("#launchConfirm").addEventListener("change", (event) => { $("#startRunButton").disabled = !event.target.checked; });
  $("#startRunButton").addEventListener("click", startRun);
}

async function startRun() {
  const button = $("#startRunButton");
  button.disabled = true;
  button.textContent = "Launching…";
  try {
    const result = await api("/api/workflow-runs", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Launch-Token": state.launch.options.launch_token },
      body: JSON.stringify({
        cycle_id: state.launch.request.cycle_id,
        workflow_plan_id: state.launch.plan.workflow_plan_id,
        confirmation: state.launch.options.confirmation,
      }),
    });
    state.launch.result = result;
    $("#launchContent").innerHTML = `
      <div class="launch-success-mark">✓</div><div class="launch-success"><p class="eyebrow">Workflow queued</p><h3>${escapeHtml(state.launch.plan.workflow_id)}</h3><p>The detached local runner has started. Progress and failures will appear here as they are recorded.</p><code>${escapeHtml(result.workflow_run_id)}</code></div>
      <div class="dialog-actions"><button class="secondary-button" value="cancel">Close</button><button id="viewNewRun" class="primary-button" type="button">View fresh/clean run</button></div>`;
    $("#viewNewRun").addEventListener("click", async () => {
      await loadRuns(false);
      const run = state.runs.find((item) => item.id === result.workflow_run_id);
      if (run) await selectRun(run.cycle_id, run.id);
      $("#launchDialog").close();
    });
  } catch (error) {
    launchError(error.message);
    button.disabled = false;
    button.textContent = "Launch local sync";
  }
}

function renderRuns() {
  const query = $("#runSearch").value.trim().toLowerCase();
  const runs = state.runs.filter((run) => `${run.workflow_id} ${run.id} ${run.cycle_id}`.toLowerCase().includes(query));
  $("#runCount").textContent = runs.length;
  $("#runList").innerHTML = runs.length ? runs.map((run) => `
    <button class="run-card ${state.selected?.id === run.id ? "active" : ""}" data-run="${escapeHtml(run.id)}" data-cycle="${escapeHtml(run.cycle_id)}">
      <div class="run-card-top"><span class="status-dot ${escapeHtml(run.status)}"></span><span class="run-name">${escapeHtml(run.workflow_id)}</span></div>
      <p class="run-time">${localTime(run.created_at)}</p>
      <div class="run-meta"><span class="mini-tag">${escapeHtml(run.status)}</span><span class="mini-tag">${escapeHtml(run.cycle_id.replace("sandbox-", ""))}</span></div>
    </button>`).join("") : '<div class="loading-card">No runs match that search.</div>';

  document.querySelectorAll("[data-run]").forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.cycle, button.dataset.run)));
}

function countLatest(status) {
  return (state.detail?.failure_summary || []).filter((item) => !status || item.item_status === status).reduce((sum, item) => sum + item.count, 0);
}

function renderDetail() {
  const { run, cycle, latest_steps: steps } = state.detail;
  const failedEntities = state.detail.failure_summary.filter((x) => x.item_status === "failed").reduce((sum, x) => sum + x.distinct_source_keys, 0);
  const analysis = state.detail.retry_analysis || {};
  const executions = state.detail.execution_summary || {};
  const nonRetryable = (analysis.structural || 0) + (analysis.persistent || 0);
  const needsReview = (analysis.unknown || 0) + (analysis.aggregate || 0);
  $("#detailPanel").innerHTML = `
    <div class="detail-header">
      <div class="detail-title"><p class="eyebrow">${escapeHtml(cycle.id)} · ${escapeHtml(cycle.status)} cycle</p><h2>${escapeHtml(run.workflow_id)}</h2><p>Run <span class="mono">${escapeHtml(run.id)}</span> · ${localTime(run.created_at)}</p></div>
      <span class="status-label ${escapeHtml(run.status)}"><span class="status-dot ${escapeHtml(run.status)}"></span>${escapeHtml(run.status)}</span>
    </div>
    <div class="metrics">
      <article class="metric"><div class="metric-label">Duration</div><div class="metric-value">${duration(run.started_at, run.finished_at)}</div></article>
      <article class="metric"><div class="metric-label">Services</div><div class="metric-value">${steps.length}</div></article>
      <article class="metric"><div class="metric-label">Failed entities</div><div class="metric-value">${failedEntities}</div></article>
      <article class="metric"><div class="metric-label">Failure records</div><div class="metric-value">${countLatest()}</div></article>
    </div>
    <section class="assessment">
      <div class="assessment-copy">
        <p class="eyebrow">Retry assessment</p>
        <h3>${nonRetryable} records need a change before retry</h3>
        <p>Execution numbers belong to the whole service. This workflow was resumed ${executions.workflow_resumes || 0} times and recorded ${executions.automatic_recoveries || 0} automatic system recoveries. A repeated structural failure will not clear just by running it again.</p>
      </div>
      <div class="assessment-counts">
        <div><strong>${analysis.retryable || 0}</strong><span>Retryable system</span></div>
        <div><strong>${nonRetryable}</strong><span>Structural / persistent</span></div>
        <div><strong>${analysis.dependency || 0}</strong><span>Dependency blocked</span></div>
        <div><strong>${needsReview}</strong><span>Aggregate / review</span></div>
      </div>
    </section>
    <section class="section">
      <div class="section-head"><div><p class="eyebrow">Latest attempt per service</p><h3>Workflow path</h3></div></div>
      <div class="step-grid">${steps.map((step) => `
        <article class="step-card ${escapeHtml(step.status)}">
          <div class="step-name">${escapeHtml(step.service_id)}</div><div class="step-phase">${escapeHtml(step.phase)}</div>
          <div class="step-items"><strong>${itemCount(step.sync_item_count)}</strong><span>sync items</span>${Number.isInteger(step.processed_item_count) && step.processed_item_count !== step.sync_item_count ? `<small>${itemCount(step.processed_item_count)} recorded so far</small>` : ""}</div>
          <div class="step-bottom"><span class="step-status">${escapeHtml(step.status)}</span><span class="step-attempt">Service execution ${step.attempt}</span></div>
        </article>`).join("")}</div>
    </section>
    <section class="section">
      <div class="section-head"><div><p class="eyebrow">Recorded evidence</p><h3>Failures and gates</h3></div><span id="failureTotal" class="count-pill">—</span></div>
      <div class="failure-toolbar">
        <input id="failureSearch" type="search" placeholder="Search source keys or errors" aria-label="Search failures" />
        <select id="serviceFilter" aria-label="Filter by service"><option value="">All services</option>${steps.map((step) => `<option value="${escapeHtml(step.service_id)}">${escapeHtml(step.service_id)}</option>`).join("")}</select>
        <select id="statusFilter" aria-label="Filter by status"><option value="">All statuses</option><option>failed</option><option>blocked</option><option>quarantined</option><option>planned-failure</option></select>
        <select id="attemptFilter" aria-label="Select attempts"><option value="latest">Latest attempts</option><option value="all">All attempts</option></select>
      </div>
      <div id="failureResults"><div class="loading-card">Loading failure records…</div></div>
    </section>`;

  ["#serviceFilter", "#statusFilter", "#attemptFilter"].forEach((selector) => $(selector).addEventListener("change", () => { state.page = 1; loadFailures(); }));
  let timer;
  $("#failureSearch").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { state.page = 1; loadFailures(); }, 180); });
  loadFailures();
}

async function loadFailures() {
  const params = new URLSearchParams({ cycle: state.selected.cycle_id, page: state.page, page_size: state.pageSize, attempt: $("#attemptFilter").value });
  const service = $("#serviceFilter").value;
  const status = $("#statusFilter").value;
  const search = $("#failureSearch").value.trim();
  if (service) params.set("service_id", service);
  if (status) params.set("item_status", status);
  if (search) params.set("search", search);
  try {
    const data = await api(`/api/runs/${encodeURIComponent(state.selected.id)}/failures?${params}`);
    $("#failureTotal").textContent = data.total;
    const start = data.total ? (data.page - 1) * data.page_size + 1 : 0;
    const end = Math.min(data.total, data.page * data.page_size);
    $("#failureResults").innerHTML = data.items.length ? `
      <div class="table-wrap"><table><thead><tr><th>Service</th><th>Source</th><th>Status</th><th>Retry posture</th><th>Reason</th></tr></thead><tbody>
      ${data.items.map((item) => `<tr><td>${escapeHtml(item.service_id)}<br><span class="mini-tag">execution ${item.attempt || "—"}</span></td><td class="source-key">${escapeHtml(item.source_key || "workflow-level")}${item.source_key && item.seen_in_executions > 1 ? `<span class="recurrence">Seen in ${item.seen_in_executions} executions</span>` : ""}</td><td><span class="status-chip ${escapeHtml(item.item_status)}">${escapeHtml(item.item_status)}</span></td><td><span class="posture-chip ${escapeHtml(item.failure_class)}">${escapeHtml(item.failure_class)}</span><div class="posture-advice">${escapeHtml(item.retry_advice)}</div></td><td><div class="failure-message" title="${escapeHtml(item.error_code || item.error_message || "No message")}"><strong>${escapeHtml(item.class_reason)}</strong><span>${escapeHtml(item.error_code || item.error_message || "No message")}</span></div></td></tr>`).join("")}
      </tbody></table></div>
      <div class="pager"><span>Showing ${start}–${end} of ${data.total}</span><div class="pager-buttons"><button class="small-button" id="prevPage" ${data.page <= 1 ? "disabled" : ""}>Previous</button><button class="small-button" id="nextPage" ${end >= data.total ? "disabled" : ""}>Next</button></div></div>` : '<div class="loading-card">No failure records match these filters.</div>';
    $("#prevPage")?.addEventListener("click", () => { state.page -= 1; loadFailures(); });
    $("#nextPage")?.addEventListener("click", () => { state.page += 1; loadFailures(); });
  } catch (error) {
    $("#failureResults").innerHTML = `<div class="error-banner">${escapeHtml(error.message)}</div>`;
  }
}

async function selectRun(cycleId, runId) {
  state.selected = { cycle_id: cycleId, id: runId };
  state.page = 1;
  renderRuns();
  $("#detailPanel").innerHTML = '<div class="empty-state"><div class="empty-glyph">↻</div><h2>Reading run state</h2><p>Loading preserved workflow evidence…</p></div>';
  try {
    state.detail = await api(`/api/runs/${encodeURIComponent(runId)}?cycle=${encodeURIComponent(cycleId)}`);
    renderDetail();
  } catch (error) {
    $("#detailPanel").innerHTML = `<div class="error-banner">${escapeHtml(error.message)}</div>`;
  }
}

async function loadRuns(preserveSelection = true) {
  $("#refreshButton").disabled = true;
  try {
    const data = await api("/api/runs");
    state.runs = data.runs;
    renderRuns();
    const selection = preserveSelection && state.selected ? state.runs.find((run) => run.id === state.selected.id) : state.runs[0];
    if (selection) selectRun(selection.cycle_id, selection.id);
  } catch (error) {
    $("#runList").innerHTML = `<div class="error-card">${escapeHtml(error.message)}</div>`;
  } finally {
    $("#refreshButton").disabled = false;
  }
}

$("#runSearch").addEventListener("input", renderRuns);
$("#refreshButton").addEventListener("click", () => loadRuns(true));
$("#launchButton").addEventListener("click", openLaunchDialog);
loadRuns(false);
