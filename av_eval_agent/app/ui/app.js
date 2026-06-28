const API_BASE = "";

const state = {
  selectedRunId: null,
  history: [],
  selectedScenario: "scenario_1",
  selectedNode: "spec",
  startedAt: Date.now(),
};

const nodeDetails = {
  spec: {
    title: "1. ScenarioSpecAgent",
    purpose: "사용자 자연어 요청을 시나리오 정의서 형식의 JSON으로 변환합니다. 명시되지 않은 값은 일반적인 기본값과 가정을 분리해 기록합니다.",
    input: "user_request, scenario intent, optional reference files",
    output: "scenario_definition.json, scenario_definition_form.csv",
    risk: "정의서에 없는 값을 임의 확정하지 않고 assumption으로 남겨 검증 단계에서 확인합니다.",
  },
  validation: {
    title: "2. ScenarioValidationAgent",
    purpose: "필수값 누락, 단위 오류, 물리적으로 불가능한 조건, 정의서 형식 불일치를 점검합니다.",
    input: "scenario_definition JSON",
    output: "validation pass/warn/fail, missing-field list",
    risk: "속도·거리·시간 단위가 섞이면 KPI 결과가 왜곡되므로 단위 정규화가 핵심입니다.",
  },
  build: {
    title: "3. ExperimentBuildAgent",
    purpose: "검증된 JSON을 OpenCDA YAML/PY 실행 파일과 KPI 실행 계획으로 변환합니다.",
    input: "validated definition, scenario template, KPI contract",
    output: "OpenCDA YAML/PY copy, execution_plan.json, command list",
    risk: "원본 실험 파일은 보존하고 run_id별 복사본/manifest 기준으로 추적합니다.",
  },
  simulation: {
    title: "4. SimulationRunAgent",
    purpose: "CARLA/OpenCDA 실행, 로그 저장, data_dump 고정, 실패 패턴 감지를 담당합니다.",
    input: "execution_plan.json, execute_simulation option",
    output: "stdout/stderr log, latest data dump path, failure status",
    risk: "CARLA 서버 상태와 포트 충돌을 감지하고 실패 시 run 기록에 남겨야 합니다.",
  },
  kpi: {
    title: "5. KPIAgent",
    purpose: "인지, 제어, 교통 영향성, 주행 안전성 KPI를 동일 계약으로 계산합니다.",
    input: "data dump, GT/prediction logs, vehicle states",
    output: "MOTA/MOTP, accel variance, delay/flow, TTC/PET/RD",
    risk: "시나리오별 비교가 아니라 알고리즘/조건별 의미가 맞도록 observation horizon을 고정해야 합니다.",
  },
  report: {
    title: "6. ReportAgent",
    purpose: "KPI 결과와 실행 근거를 모아 최종 Markdown 보고서를 생성합니다.",
    input: "KPI results, manifest, artifacts",
    output: "final report",
    risk: "점수화 방향이 다른 KPI는 높을수록 좋게 역정규화한 뒤 통합해야 합니다.",
  },
  memory: {
    title: "7. MemoryAgent",
    purpose: "이전 실험과 비교하고, 다음 실험 조건과 개선 방향을 추천합니다.",
    input: "current run record, previous run DB, KPI summary",
    output: "comparison summary, recommendations, next experiment candidates",
    risk: "같은 시나리오/같은 KPI 기준끼리만 비교하도록 run metadata를 확인합니다.",
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
  if (status.includes("memory_recommended")) return 96;
  if (status.includes("report_generated")) return 90;
  if (status.includes("finished") && !status.includes("review")) return 82;
  if (status.includes("review")) return 66;
  if (status.includes("queued") || status.includes("running")) return 58;
  if (status.includes("prepared") || status.includes("ready")) return 48;
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
    addMessage("system", "WARN", `실험 이력을 불러오지 못했습니다: ${error.message}`);
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
    addMessage("system", "WARN", `run 상태를 불러오지 못했습니다: ${error.message}`);
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
    "report",
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
    prepared_only: 3,
    ready_for_execution: 3,
    queued: 4,
    running: 4,
    execution_finished: 5,
    execution_finished_needs_review: 5,
    report_generated: 6,
    memory_recommended: 7,
  };
  const doneCount = doneMap[status] || (String(status).includes("prepared") ? 3 : 1);
  const stages = $$(".stage");
  stages.forEach((stage, index) => {
    stage.classList.toggle("done", index < doneCount);
    stage.classList.toggle("active", index === Math.min(doneCount, stages.length - 1));
  });

  const nodeOrder = ["spec", "validation", "build", "simulation", "kpi", "report", "memory"];
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
  const detail = nodeDetails[id] || nodeDetails.spec;
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
  addMessage("assistant", "AGENT", "ScenarioSpecAgent → ScenarioValidationAgent → ExperimentBuildAgent → SimulationRunAgent → KPIAgent → ReportAgent → MemoryAgent 순서의 n8n 노드 그래프로 실행합니다.");
  setText("#runState", "BUSY");
  selectNode("spec");

  try {
    const result = await apiPost("/pipeline/submit", body);
    addMessage("assistant", "AGENT", `run_id ${result.run_id} 등록 완료. 현재 상태: ${statusLabel(result.status)}`);
    await loadHistory();
    await selectRun(result.run_id);
    selectNode("build");
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
  selectNode("spec");
  await checkHealth();
  await loadHistory();
  setInterval(updateClock, 1000);
  setInterval(async () => {
    if (state.selectedRunId) await selectRun(state.selectedRunId);
  }, 8000);
}

init();
