const API_BASE = "";

const state = {
  selectedRunId: null,
  history: [],
  selectedScenario: "scenario_1",
  selectedNode: "webhook",
  startedAt: Date.now(),
};

const nodeDetails = {
  webhook: {
    title: "Scenario Request Webhook",
    purpose: "사용자 자연어 요청을 받아 평가 파이프라인의 입력으로 정규화합니다.",
    input: "user_request, execute_simulation, run_kpis, record",
    output: "normalized request payload",
    risk: "요청이 모호하면 기본값과 가정을 분리해서 기록해야 합니다.",
  },
  parse: {
    title: "Scenario Understanding",
    purpose: "LangGraph가 시나리오 유형, 도로 환경, ego/actor/neighboring 역할을 추론합니다.",
    input: "normalized natural-language request",
    output: "scenario_id, ODD/OEDR, actor-role candidates",
    risk: "정의서에 없는 값은 임의 확정하지 않고 assumption으로 표시합니다.",
  },
  definition: {
    title: "Definition JSON Builder",
    purpose: "정의서 형식에 맞춰 차량, 도로, 센서, 통신, 초기 상대거리 항목을 구조화합니다.",
    input: "scenario intent + YAML/PY evidence",
    output: "scenario_definition.json, scenario_definition_form.csv",
    risk: "YAML과 자연어가 충돌하면 검증 노드로 넘깁니다.",
  },
  validate: {
    title: "Validation Agent",
    purpose: "누락값, 서로 충돌하는 설정, KPI 산출에 필요한 로그 준비 여부를 점검합니다.",
    input: "definition JSON + source files",
    output: "pass/warn/fail checklist",
    risk: "실험 목적과 파일 설정이 다르면 human review가 필요합니다.",
  },
  plan: {
    title: "YAML/PY + KPI Plan",
    purpose: "OpenCDA 실행 명령과 공통 KPI 계산 명령을 run_id 폴더에 고정합니다.",
    input: "validated definition",
    output: "execution_plan.json, command list",
    risk: "CARLA 실행은 무겁기 때문에 n8n에서는 승인/큐 등록까지만 담당합니다.",
  },
  queue: {
    title: "Execution Queue",
    purpose: "n8n이 run_id 기준으로 실험 요청을 큐에 넣고 상태를 추적합니다.",
    input: "run_id + execution options",
    output: "queued/prepared/running status",
    risk: "동시에 여러 CARLA 실행을 시작하지 않도록 rate limit이 필요합니다.",
  },
  status: {
    title: "Status / Artifact API",
    purpose: "manifest, 로그, 정의서, KPI 결과, 보고서 경로를 외부 UI와 n8n에 제공합니다.",
    input: "run_id",
    output: "pipeline/status response",
    risk: "결과가 없을 때는 점수를 만들지 않고 준비 상태만 표시해야 합니다.",
  },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function setText(selector, value) {
  const el = $(selector);
  if (el) el.textContent = value;
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function addMessage(kind, label, text) {
  const stack = $("#messageStack");
  const item = document.createElement("div");
  item.className = `message ${kind}`;
  item.innerHTML = `<span class="message-label">${escapeHtml(label)}</span>${escapeHtml(text)}`;
  stack.appendChild(item);
  stack.scrollTop = stack.scrollHeight;
}

function shortPath(path) {
  if (!path) return "-";
  const text = String(path);
  const parts = text.split(/[\\/]/);
  if (parts.length <= 3) return text;
  return `${parts.at(-3)} / ${parts.at(-2)} / ${parts.at(-1)}`;
}

function statusLabel(status) {
  if (!status) return "unknown";
  return String(status).replaceAll("_", " ");
}

function readinessScore(record, manifestStatus) {
  const status = record?.pipeline_status || manifestStatus || "";
  if (status.includes("finished") && !status.includes("review")) return 88;
  if (status.includes("review")) return 64;
  if (status.includes("queued") || status.includes("running")) return 58;
  if (status.includes("prepared") || status.includes("ready")) return 46;
  if (status.includes("failed")) return 12;
  return null;
}

function updateClock() {
  const seconds = Math.floor((Date.now() - state.startedAt) / 1000);
  const hh = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const mm = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");
  setText("#clockText", `${hh}:${mm}:${ss}`);
}

async function apiGet(path) {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function apiPost(path, body) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function checkHealth() {
  try {
    const health = await apiGet("/health");
    $("#healthDot").className = "status-dot ok";
    setText("#healthText", `${health.service} connected`);
    setText("#runState", "READY");
  } catch (error) {
    $("#healthDot").className = "status-dot fail";
    setText("#healthText", "Agent server disconnected");
    setText("#runState", "OFF");
  }
}

async function loadHistory() {
  try {
    const data = await apiGet("/pipeline/history?limit=5");
    state.history = data.runs || [];
    renderRunList();
    if (!state.selectedRunId && state.history.length) {
      await selectRun(state.history[0].run_id);
    }
  } catch (error) {
    addMessage("system", "WARN", `실험 이력을 불러오지 못했습니다. ${error.message}`);
  }
}

function renderRunList() {
  const list = $("#runList");
  list.innerHTML = "";
  if (!state.history.length) {
    list.innerHTML = `<div class="empty-state">등록된 run이 없습니다.</div>`;
    return;
  }

  for (const run of state.history) {
    const item = document.createElement("div");
    item.className = "run-item";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(run.run_id)}</strong>
        <span>${escapeHtml(statusLabel(run.pipeline_status))} · ${escapeHtml(run.scenario_id || "-")}</span>
      </div>
      <button type="button" data-run-id="${escapeHtml(run.run_id)}">View</button>
    `;
    list.appendChild(item);
  }

  $$("#runList button").forEach((button) => {
    button.addEventListener("click", () => selectRun(button.dataset.runId));
  });
}

async function selectRun(runId) {
  if (!runId) return;
  state.selectedRunId = runId;
  try {
    const data = await apiGet(`/pipeline/status/${encodeURIComponent(runId)}`);
    renderRunStatus(data);
  } catch (error) {
    addMessage("system", "WARN", `run 상태를 불러오지 못했습니다. ${error.message}`);
  }
}

function renderRunStatus(data) {
  const record = data.record || {};
  const artifacts = data.artifacts || {};
  const status = record.pipeline_status || data.manifest_status || "unknown";
  const scenario = record.scenario_id || "-";
  const score = readinessScore(record, data.manifest_status);

  setText("#selectedRun", data.run_id || "No run selected");
  setText("#runState", status.includes("running") ? "RUN" : status.includes("failed") ? "FAIL" : "READY");
  setText("#scoreNumber", score == null ? "--" : String(score.toFixed(0)));
  const verdict = score == null ? "PENDING" : score >= 75 ? "READY" : score >= 45 ? "REVIEW" : "BLOCKED";
  const verdictRow = document.querySelector(".verdict-row");
  verdictRow.classList.toggle("review", verdict === "REVIEW");
  verdictRow.classList.toggle("fail", verdict === "BLOCKED");
  setText("#verdictText", verdict);

  const details = $("#detailList");
  details.innerHTML = `
    <div><dt>Scenario</dt><dd>${escapeHtml(scenario)}</dd></div>
    <div><dt>Status</dt><dd>${escapeHtml(statusLabel(status))}</dd></div>
    <div><dt>Manifest</dt><dd>${escapeHtml(shortPath(record.manifest))}</dd></div>
    <div><dt>Alignment</dt><dd>${escapeHtml(data.scenario_alignment?.decision || "not reviewed yet")}</dd></div>
  `;

  renderArtifacts(artifacts);
  updateStages(status);
  if (scenario === "scenario_2") setScenario("scenario_2");
  if (scenario === "scenario_1") setScenario("scenario_1");
}

function renderArtifacts(artifacts) {
  const list = $("#artifactList");
  const entries = Object.entries(artifacts || {}).filter(([, value]) => value);
  if (!entries.length) {
    list.innerHTML = `<div class="empty-state">생성된 artifact가 없습니다.</div>`;
    return;
  }

  const preferred = [
    "scenario_definition_form",
    "execution_plan",
    "dashboard",
    "report",
    "final_dashboard",
    "final_report",
    "execution_result",
    "scenario_alignment_review",
  ];
  const ordered = [
    ...preferred.filter((key) => artifacts[key]),
    ...entries.map(([key]) => key).filter((key) => !preferred.includes(key)),
  ];

  list.innerHTML = "";
  for (const key of ordered.slice(0, 8)) {
    const value = artifacts[key];
    const item = document.createElement("div");
    item.className = "artifact-item";
    item.innerHTML = `<strong>${escapeHtml(key)}</strong><span>${escapeHtml(shortPath(value))}</span>`;
    list.appendChild(item);
  }
}

function updateStages(status) {
  const doneMap = {
    prepared_only: 4,
    ready_for_execution: 5,
    queued: 6,
    running: 6,
    execution_finished: 6,
    execution_finished_needs_review: 6,
  };
  const doneCount = doneMap[status] || (String(status).includes("prepared") ? 4 : 1);
  $$(".stage").forEach((stage, index) => {
    stage.classList.toggle("done", index < doneCount);
    stage.classList.toggle("active", index === Math.min(doneCount, $$(".stage").length - 1));
  });

  const nodeOrder = ["webhook", "parse", "definition", "validate", "plan", "queue", "status"];
  $$(".flow-node").forEach((node) => {
    const index = nodeOrder.indexOf(node.dataset.node);
    node.classList.toggle("done", index > -1 && index < doneCount);
  });
}

function setScenario(id) {
  state.selectedScenario = id;
  $$(".scenario-tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.scenario === id);
  });
  document.body.dataset.scenario = id;
}

function selectNode(id) {
  const detail = nodeDetails[id] || nodeDetails.webhook;
  state.selectedNode = id;
  $$(".flow-node").forEach((node) => node.classList.toggle("active", node.dataset.node === id));
  setText("#selectedNode", detail.title);
  setText("#nodePurpose", detail.purpose);
  $("#nodeIo").innerHTML = `
    <div><dt>Input</dt><dd>${escapeHtml(detail.input)}</dd></div>
    <div><dt>Output</dt><dd>${escapeHtml(detail.output)}</dd></div>
    <div><dt>Risk</dt><dd>${escapeHtml(detail.risk)}</dd></div>
  `;
}

async function submitPrompt(event) {
  event.preventDefault();
  const requestText = $("#promptInput").value.trim();
  if (!requestText) return;

  const body = {
    user_request: requestText,
    execute_simulation: $("#executeSimulation").checked,
    run_kpis: $("#runKpis").checked,
    apply_ml: false,
    record: $("#recordVideo").checked,
    background: true,
  };

  addMessage("user", "USER", requestText);
  addMessage("assistant", "AGENT", "n8n Webhook → LangGraph → 정의서 JSON → 검증 → 실행계획 순서로 run을 등록합니다.");
  setText("#runState", "BUSY");
  selectNode("webhook");

  try {
    const result = await apiPost("/pipeline/submit", body);
    addMessage("assistant", "AGENT", `run_id ${result.run_id} 등록 완료. 상태: ${statusLabel(result.status)}`);
    await loadHistory();
    await selectRun(result.run_id);
    selectNode("status");
  } catch (error) {
    addMessage("system", "ERROR", `pipeline 등록 실패: ${error.message}`);
    setText("#runState", "FAIL");
  }
}

function bindEvents() {
  $("#promptForm").addEventListener("submit", submitPrompt);
  $("#refreshButton").addEventListener("click", async () => {
    await checkHealth();
    await loadHistory();
    if (state.selectedRunId) await selectRun(state.selectedRunId);
  });
  $("#openLatestButton").addEventListener("click", () => {
    if (state.selectedRunId) {
      window.open(`/pipeline/status/${encodeURIComponent(state.selectedRunId)}`, "_blank");
    }
  });
  $$(".quick-prompts button").forEach((button) => {
    button.addEventListener("click", () => {
      $("#promptInput").value = button.dataset.prompt;
    });
  });
  $$(".scenario-tabs button").forEach((button) => {
    button.addEventListener("click", () => setScenario(button.dataset.scenario));
  });
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".nav-item").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
    });
  });
  $$(".flow-node").forEach((node) => {
    node.addEventListener("click", () => selectNode(node.dataset.node));
  });
}

async function init() {
  bindEvents();
  setScenario("scenario_1");
  selectNode("webhook");
  await checkHealth();
  await loadHistory();
  setInterval(updateClock, 1000);
  setInterval(async () => {
    if (state.selectedRunId) await selectRun(state.selectedRunId);
  }, 8000);
}

init();
