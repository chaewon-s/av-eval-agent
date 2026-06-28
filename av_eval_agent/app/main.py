from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.graph import agent_graph, requirement_understanding_node, scenario_specification_node, scenario_validate_node
from app.services.artifact_store import (
    list_run_manifests,
    manifest_path_for,
    persist_agent_run,
    read_run_manifest,
    save_run_manifest,
    write_json,
)
from app.services.autotune_agent import run_autotune_agent
from app.services.kpi_runner import prepare_kpi_execution_plan, run_kpi_execution_plan
from app.services.opencda_runner import prepare_opencda_execution_plan, run_opencda_execution_plan
from app.services.experiment_history import append_event, get_run_record, list_run_records, read_events, upsert_run_record
from app.services.ops_agents import run_failure_diagnosis_agent, run_preflight_agent, run_quality_gate_agent
from app.services.research_readiness import run_research_readiness_agent
from app.services.result_publisher import publish_run_outputs
from app.services.scenario_alignment import evaluate_scenario_alignment


app = FastAPI(title="AV Evaluation Agent", version="0.2.0")

RUN_STORE: Dict[str, Dict[str, Any]] = {}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
UI_DIR = Path(__file__).resolve().parent / "ui"


class ScenarioRequest(BaseModel):
    user_request: str = Field(..., description="자연어 시나리오/평가 요청")


class ValidateRequest(BaseModel):
    scenario_definition: Dict[str, Any]


class PrepareRunRequest(BaseModel):
    include_kpis: bool = True
    apply_ml: bool = False
    record: bool = False


class ExecuteRunRequest(BaseModel):
    execute_simulation: bool = False
    run_kpis: bool = False
    apply_ml: bool = False
    record: bool = False


class AutoTuneRequest(BaseModel):
    enabled: bool = True
    apply_patches: bool = False
    max_iterations: int = 1
    model: str = "gpt-4.1-mini"
    temperature: float = 0.2
    seed: int | None = 20260628
    model_version_note: str = "Pinned by request for reproducible research logging."
    notes: str | None = None


class PipelineSubmitRequest(BaseModel):
    user_request: str = Field(..., description="자연어 시나리오/평가 요청")
    execute_simulation: bool = False
    run_kpis: bool = True
    apply_ml: bool = False
    record: bool = False
    background: bool = True


def _load_scenario_id(manifest: Dict[str, Any]) -> str:
    definition_path = manifest.get("scenario_definition")
    if definition_path and Path(definition_path).exists():
        try:
            definition = json.loads(Path(definition_path).read_text(encoding="utf-8"))
            return definition.get("scenario_id", "custom")
        except json.JSONDecodeError:
            return "custom"
    return manifest.get("scenario_id", "custom")


def _write_execution_plan(project_root: Path, run_id: str, plan: Dict[str, Any]) -> Path:
    execution_plan_path = project_root / "av_eval_agent" / "data" / "runs" / run_id / "execution_plan.json"
    write_json(execution_plan_path, plan)
    return execution_plan_path


def _new_run_id() -> str:
    return f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"


def _load_definition_from_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    definition_path = manifest.get("scenario_definition")
    if definition_path and Path(definition_path).exists():
        return json.loads(Path(definition_path).read_text(encoding="utf-8"))
    return {}


def _public_urls(run_id: str) -> Dict[str, str]:
    return {
        "status": f"http://127.0.0.1:8010/pipeline/status/{run_id}",
        "run_status": f"http://127.0.0.1:8010/run/status/{run_id}",
        "run_result": f"http://127.0.0.1:8010/run/result/{run_id}",
        "scenario_validation_agent": f"http://127.0.0.1:8010/agent/scenario-validation/{run_id}",
        "experiment_build_agent": f"http://127.0.0.1:8010/agent/experiment-build/{run_id}",
        "simulation_run_agent": f"http://127.0.0.1:8010/agent/simulation-run/{run_id}",
        "kpi_agent": f"http://127.0.0.1:8010/agent/kpi/{run_id}",
        "report_agent_v2": f"http://127.0.0.1:8010/agent/report/{run_id}",
        "memory_agent_v2": f"http://127.0.0.1:8010/agent/memory/{run_id}",
        "autotune_agent": f"http://127.0.0.1:8010/agent/autotune/{run_id}",
        "research_readiness_agent": f"http://127.0.0.1:8010/agent/research-readiness/{run_id}",
        "report_agent": f"http://127.0.0.1:8010/report/generate/{run_id}",
        "memory_agent": f"http://127.0.0.1:8010/memory/recommend/{run_id}",
        "api_docs": "http://127.0.0.1:8010/docs",
    }


def _pipeline_execute_task(run_id: str, payload: ExecuteRunRequest) -> None:
    append_event(
        PROJECT_ROOT,
        run_id,
        "pipeline_worker_started",
        status="running",
        payload=payload.model_dump(),
    )
    upsert_run_record(PROJECT_ROOT, run_id, {"pipeline_status": "running"})
    try:
        result = execute_run(run_id, payload)
        diagnosis = run_failure_diagnosis_agent(PROJECT_ROOT, run_id)
        quality_gate = run_quality_gate_agent(PROJECT_ROOT, run_id)
        readiness = run_research_readiness_agent(PROJECT_ROOT, run_id)
        report = generate_report(run_id)
        append_event(
            PROJECT_ROOT,
            run_id,
            "pipeline_worker_finished_with_ops",
            status=readiness.get("status", result.get("status", "unknown")),
            payload={
                "execution_status": result.get("status"),
                "failure_diagnosis": diagnosis.get("status"),
                "quality_gate": quality_gate.get("status"),
                "research_readiness": readiness.get("status"),
                "report_status": report.get("status"),
            },
        )
        upsert_run_record(
            PROJECT_ROOT,
            run_id,
            {
                "pipeline_status": readiness.get("status", result.get("status", "unknown")),
                "scenario_alignment_decision": (result.get("scenario_alignment") or {}).get("decision"),
                "failure_diagnosis": diagnosis.get("status"),
                "quality_gate": quality_gate.get("status"),
                "research_readiness": readiness.get("status"),
                "final_report": (report.get("artifacts") or {}).get("final_report"),
            },
        )
    except Exception as exc:  # Background task must persist failures for the UI.
        append_event(
            PROJECT_ROOT,
            run_id,
            "pipeline_worker_failed",
            status="failed",
            payload={"error": str(exc)},
        )
        upsert_run_record(PROJECT_ROOT, run_id, {"pipeline_status": "failed", "error": str(exc)})


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "av-evaluation-agent"}


@app.post("/scenario/parse")
def parse_scenario(payload: ScenarioRequest) -> Dict[str, Any]:
    state = requirement_understanding_node({"user_request": payload.user_request})
    state = scenario_specification_node(state)
    return state


@app.post("/scenario/validate")
def validate_scenario(payload: ValidateRequest) -> Dict[str, Any]:
    state = scenario_validate_node({"scenario_definition": payload.scenario_definition})
    return state


@app.post("/agent/plan")
def create_agent_plan(payload: ScenarioRequest) -> Dict[str, Any]:
    """n8n 또는 외부 UI가 가장 먼저 호출하는 Agent 계획 생성 endpoint."""
    result = agent_graph.invoke({"user_request": payload.user_request})
    return result


@app.get("/agent/tools")
def list_agent_tools() -> Dict[str, Any]:
    """n8n AI Agent가 tool로 호출할 수 있는 도메인 Agent 목록."""
    return {
        "service": "AV Evaluation Agent",
        "base_url": "http://127.0.0.1:8010",
        "tools": [
            {
                "agent": "ScenarioSpecAgent",
                "method": "POST",
                "path": "/agent/scenario-spec",
                "input": {"user_request": "string"},
                "output": ["run_id", "scenario_definition", "persisted_artifacts"],
            },
            {
                "agent": "PreflightAgent",
                "method": "GET",
                "path": "/agent/preflight",
                "input": {"scenario_id": "optional string"},
                "output": ["CARLA/n8n/backend/file readiness checks"],
            },
            {
                "agent": "ScenarioValidationAgent",
                "method": "POST",
                "path": "/agent/scenario-validation/{run_id}",
                "input": {"run_id": "string"},
                "output": ["validation_errors", "validation_warnings", "validation_result"],
            },
            {
                "agent": "ExperimentBuildAgent",
                "method": "POST",
                "path": "/agent/experiment-build/{run_id}",
                "input": {"include_kpis": "bool", "apply_ml": "bool", "record": "bool"},
                "output": ["execution_plan", "execution_plan_path"],
            },
            {
                "agent": "SimulationRunAgent",
                "method": "POST",
                "path": "/agent/simulation-run/{run_id}",
                "input": {"execute_simulation": "bool", "apply_ml": "bool", "record": "bool"},
                "output": ["OpenCDA result", "logs", "failure detection"],
            },
            {
                "agent": "KPIAgent",
                "method": "POST",
                "path": "/agent/kpi/{run_id}",
                "input": {"run_kpis": "bool"},
                "output": ["standard KPI result artifacts"],
            },
            {
                "agent": "FailureDiagnosisAgent",
                "method": "POST",
                "path": "/agent/failure-diagnosis/{run_id}",
                "input": {"run_id": "string"},
                "output": ["fatal log pattern classification", "recovery recommendations"],
            },
            {
                "agent": "RunQualityGateAgent",
                "method": "POST",
                "path": "/agent/quality-gate/{run_id}",
                "input": {"run_id": "string"},
                "output": ["pass/review/fail gate summary"],
            },
            {
                "agent": "ResearchReadinessAgent",
                "method": "POST",
                "path": "/agent/research-readiness/{run_id}",
                "input": {"run_id": "string"},
                "output": ["research_ready/research_review_required/research_blocked", "submission summary"],
            },
            {
                "agent": "ReportAgent",
                "method": "POST",
                "path": "/agent/report/{run_id}",
                "input": {"run_id": "string"},
                "output": ["final_report"],
            },
            {
                "agent": "MemoryAgent",
                "method": "GET",
                "path": "/agent/memory/{run_id}",
                "input": {"run_id": "string"},
                "output": ["similar_runs", "recommendations", "next_experiment_candidates"],
            },
            {
                "agent": "AutoTuneAgent",
                "method": "POST",
                "path": "/agent/autotune/{run_id}",
                "input": {
                    "enabled": "bool",
                    "apply_patches": "bool",
                    "model": "string",
                    "notes": "string",
                },
                "output": ["decision", "allowed YAML patches", "human-review flag", "next_step"],
            },
            {
                "agent": "KnowledgePackAgent",
                "method": "GET",
                "path": "/agent/knowledge-packs",
                "input": {},
                "output": ["scenario_definition_pack", "kpi_standard_pack"],
            },
        ],
    }


@app.get("/agent/knowledge-packs")
def get_agent_knowledge_packs() -> Dict[str, Any]:
    """Single source of truth for n8n knowledge-pack nodes.

    The n8n workflow should fetch these packs instead of hardcoding a second
    copy. This keeps the orchestration layer and backend KPI/scenario contract
    from drifting apart.
    """

    return {
        "agent": "KnowledgePackAgent",
        "status": "ok",
        "scenario_definition_pack": {
            "source": "scenario definition form: 6-layer autonomous driving test format",
            "required_sections": [
                "road geometry",
                "traffic infrastructure",
                "temporary modifications",
                "dynamic actors",
                "environment",
                "digital/V2X layer",
            ],
            "actor_fields": [
                "role",
                "vehicle_type",
                "spawn_position",
                "destination",
                "speed",
                "lane",
                "movement",
                "v2x.enabled",
                "sensing.perception.activate",
            ],
            "default_policy": (
                "If a natural-language scenario omits a value, fill it with a "
                "conservative normal value and mark it as inferred."
            ),
        },
        "kpi_standard_pack": {
            "perception": ["MOTA", "MOTP"],
            "traffic_impact": ["Progress-adjusted Delay", "Flow Efficiency"],
            "driving_safety": ["min 2D TTC", "PET", "Required Deceleration"],
            "control": ["Acceleration Variance max-window", "Yaw-rate Residual RMS"],
            "score_direction": {
                "higher_is_better": ["MOTA", "Flow Efficiency", "TTC", "PET"],
                "lower_is_better": [
                    "MOTP",
                    "Delay",
                    "Required Deceleration",
                    "Acceleration Variance",
                    "Yaw-rate Residual RMS",
                ],
            },
            "observation_policy": {
                "perception": "Evaluate algorithm performance over matched observation horizons, not V2X labels.",
                "control": "Use event-bounded or equal-length windows to avoid post-event dilution.",
                "traffic": "Use progress-adjusted delay and route completion for incomplete trips.",
                "safety": "Use scenario-appropriate 1D/2D TTC, PET, and recognition-time required deceleration.",
            },
        },
    }


@app.get("/agent/preflight")
def agent_preflight(scenario_id: str | None = None) -> Dict[str, Any]:
    """PreflightAgent: check runtime readiness before expensive CARLA execution."""

    return run_preflight_agent(PROJECT_ROOT, scenario_id)


@app.post("/agent/scenario-spec")
def agent_scenario_spec(payload: ScenarioRequest) -> Dict[str, Any]:
    """ScenarioSpecAgent: 자연어 요청을 정의서 JSON으로 변환하고 run manifest를 만든다."""
    state = requirement_understanding_node({"user_request": payload.user_request})
    state = scenario_specification_node(state)
    run_id = _new_run_id()
    state["run_id"] = run_id
    state["status"] = "scenario_specified"
    persisted = persist_agent_run(state, PROJECT_ROOT)
    RUN_STORE[run_id] = state

    append_event(
        PROJECT_ROOT,
        run_id,
        "scenario_spec_agent_finished",
        status="scenario_specified",
        payload={"scenario_id": state.get("scenario_definition", {}).get("scenario_id")},
    )
    upsert_run_record(
        PROJECT_ROOT,
        run_id,
        {
            "pipeline_status": "scenario_specified",
            "scenario_id": state.get("scenario_definition", {}).get("scenario_id"),
            "user_request": payload.user_request,
            "manifest": persisted.get("manifest"),
        },
    )

    return {
        "agent": "ScenarioSpecAgent",
        "run_id": run_id,
        "status": "scenario_specified",
        "scenario_definition": state.get("scenario_definition"),
        "persisted_artifacts": persisted,
        "urls": _public_urls(run_id),
    }


@app.post("/agent/scenario-validation/{run_id}")
def agent_scenario_validation(run_id: str) -> Dict[str, Any]:
    """ScenarioValidationAgent: 정의서 누락/단위/물리조건을 검증한다."""
    manifest = read_run_manifest(PROJECT_ROOT, run_id)
    if not manifest:
        return {"agent": "ScenarioValidationAgent", "run_id": run_id, "status": "not_found"}

    definition = _load_definition_from_manifest(manifest)
    validation_state = scenario_validate_node({"scenario_definition": definition})
    artifacts = manifest.get("artifacts", {})
    validation_path = PROJECT_ROOT / "av_eval_agent" / "data" / "runs" / run_id / "validation_result.json"
    write_json(
        validation_path,
        {
            "run_id": run_id,
            "validation_errors": validation_state.get("validation_errors", []),
            "validation_warnings": validation_state.get("validation_warnings", []),
            "status": validation_state.get("status"),
        },
    )
    if manifest.get("scenario_definition"):
        write_json(Path(manifest["scenario_definition"]), validation_state.get("scenario_definition", definition))

    artifacts["validation_result"] = str(validation_path)
    manifest.update(
        {
            "status": validation_state.get("status"),
            "validation_errors": validation_state.get("validation_errors", []),
            "validation_warnings": validation_state.get("validation_warnings", []),
            "artifacts": artifacts,
        }
    )
    save_run_manifest(PROJECT_ROOT, run_id, manifest)
    append_event(
        PROJECT_ROOT,
        run_id,
        "scenario_validation_agent_finished",
        status=validation_state.get("status", "validated"),
        payload={
            "error_count": len(validation_state.get("validation_errors", [])),
            "warning_count": len(validation_state.get("validation_warnings", [])),
        },
    )
    upsert_run_record(
        PROJECT_ROOT,
        run_id,
        {
            "pipeline_status": validation_state.get("status"),
            "scenario_id": manifest.get("scenario_id"),
            "manifest": str(manifest_path_for(PROJECT_ROOT, run_id)),
            "validation_result": str(validation_path),
        },
    )

    return {
        "agent": "ScenarioValidationAgent",
        "run_id": run_id,
        "status": validation_state.get("status"),
        "validation_errors": validation_state.get("validation_errors", []),
        "validation_warnings": validation_state.get("validation_warnings", []),
        "validation_result": str(validation_path),
        "urls": _public_urls(run_id),
    }


@app.post("/agent/experiment-build/{run_id}")
def agent_experiment_build(run_id: str, payload: PrepareRunRequest) -> Dict[str, Any]:
    """ExperimentBuildAgent: 정의서 JSON을 OpenCDA 실행 계획으로 변환한다."""
    result = prepare_run(run_id, payload)
    result["agent"] = "ExperimentBuildAgent"
    append_event(
        PROJECT_ROOT,
        run_id,
        "experiment_build_agent_finished",
        status=result.get("status", "unknown"),
        payload={},
    )
    return result


@app.post("/agent/simulation-run/{run_id}")
def agent_simulation_run(run_id: str, payload: ExecuteRunRequest) -> Dict[str, Any]:
    """SimulationRunAgent: CARLA/OpenCDA 실행, 로그 저장, 실패 감지를 담당한다."""
    run_payload = ExecuteRunRequest(
        execute_simulation=payload.execute_simulation,
        run_kpis=False,
        apply_ml=payload.apply_ml,
        record=payload.record,
    )
    result = execute_run(run_id, run_payload)
    result["agent"] = "SimulationRunAgent"
    append_event(
        PROJECT_ROOT,
        run_id,
        "simulation_run_agent_finished",
        status=result.get("status", "unknown"),
        payload={},
    )
    return result


@app.post("/agent/kpi/{run_id}")
def agent_kpi(run_id: str, payload: ExecuteRunRequest) -> Dict[str, Any]:
    """KPIAgent: 공통 KPI 계산을 담당한다."""
    run_payload = ExecuteRunRequest(
        execute_simulation=False,
        run_kpis=payload.run_kpis,
        apply_ml=payload.apply_ml,
        record=payload.record,
    )
    result = execute_run(run_id, run_payload)
    result["agent"] = "KPIAgent"
    append_event(PROJECT_ROOT, run_id, "kpi_agent_finished", status=result.get("status", "unknown"), payload={})
    return result


@app.post("/agent/failure-diagnosis/{run_id}")
def agent_failure_diagnosis(run_id: str) -> Dict[str, Any]:
    """FailureDiagnosisAgent: classify OpenCDA/CARLA logs into actionable causes."""

    return run_failure_diagnosis_agent(PROJECT_ROOT, run_id)


@app.post("/agent/quality-gate/{run_id}")
def agent_quality_gate(run_id: str) -> Dict[str, Any]:
    """RunQualityGateAgent: decide whether a run is report-ready or needs review."""

    return run_quality_gate_agent(PROJECT_ROOT, run_id)


@app.post("/agent/research-readiness/{run_id}")
def agent_research_readiness(run_id: str) -> Dict[str, Any]:
    """ResearchReadinessAgent: create an auditable research-submission readiness record."""

    return run_research_readiness_agent(PROJECT_ROOT, run_id)


@app.post("/agent/report/{run_id}")
def agent_report(run_id: str) -> Dict[str, Any]:
    """ReportAgent wrapper endpoint for n8n."""
    result = generate_report(run_id)
    result["agent"] = "ReportAgent"
    return result


@app.get("/agent/memory/{run_id}")
def agent_memory(run_id: str) -> Dict[str, Any]:
    """MemoryAgent wrapper endpoint for n8n."""
    result = recommend_next_steps(run_id)
    result["agent"] = "MemoryAgent"
    return result


@app.post("/agent/autotune/{run_id}")
def agent_autotune(run_id: str, payload: AutoTuneRequest) -> Dict[str, Any]:
    """AutoTuneAgent: KPI/로그를 보고 다음 실험 조정안을 만든다.

    원본 OpenCDA YAML/PY는 건드리지 않고, run별 generated YAML만 패치 대상으로 삼는다.
    기본값은 제안만 생성하며, 자동 적용은 `apply_patches=true`이고 모델 판단이
    human approval을 요구하지 않을 때만 수행한다.
    """

    result = run_autotune_agent(PROJECT_ROOT, run_id, payload.model_dump())
    append_event(
        PROJECT_ROOT,
        run_id,
        "autotune_agent_finished",
        status=result.get("status", "unknown"),
        payload={
            "decision": (result.get("decision") or {}).get("decision"),
            "source": (result.get("decision") or {}).get("source"),
            "next_step": result.get("next_step"),
            "patch_count": len((result.get("decision") or {}).get("patches") or []),
        },
    )
    upsert_run_record(
        PROJECT_ROOT,
        run_id,
        {
            "pipeline_status": "autotune_decision_ready",
            "autotune_decision": (result.get("decision") or {}).get("decision"),
            "autotune_next_step": result.get("next_step"),
        },
    )
    return result


@app.post("/pipeline/submit")
def submit_pipeline(payload: PipelineSubmitRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Register a natural-language AV evaluation request into the pipeline."""

    started = start_run(ScenarioRequest(user_request=payload.user_request))
    run_id = started["run_id"]
    append_event(
        PROJECT_ROOT,
        run_id,
        "pipeline_submitted",
        status="submitted",
        payload={
            "execute_simulation": payload.execute_simulation,
            "run_kpis": payload.run_kpis,
            "apply_ml": payload.apply_ml,
            "record": payload.record,
            "background": payload.background,
        },
    )

    prepared = prepare_run(
        run_id,
        PrepareRunRequest(include_kpis=True, apply_ml=payload.apply_ml, record=payload.record),
    )
    manifest = read_run_manifest(PROJECT_ROOT, run_id) or {}
    artifacts = manifest.get("artifacts") or {}
    upsert_run_record(
        PROJECT_ROOT,
        run_id,
        {
            "pipeline_status": "ready_for_execution",
            "scenario_id": manifest.get("scenario_id"),
            "user_request": payload.user_request,
            "manifest": str(manifest_path_for(PROJECT_ROOT, run_id)),
            "execution_plan": prepared.get("execution_plan_path"),
        },
    )
    append_event(PROJECT_ROOT, run_id, "pipeline_prepared", status="ready_for_execution", payload={})

    execution_requested = payload.execute_simulation or payload.run_kpis
    execute_payload = ExecuteRunRequest(
        execute_simulation=payload.execute_simulation,
        run_kpis=payload.run_kpis,
        apply_ml=payload.apply_ml,
        record=payload.record,
    )

    immediate_result: Dict[str, Any] | None = None
    if execution_requested and payload.background:
        background_tasks.add_task(_pipeline_execute_task, run_id, execute_payload)
        pipeline_status = "queued"
        append_event(PROJECT_ROOT, run_id, "pipeline_queued", status="queued", payload=execute_payload.model_dump())
        upsert_run_record(PROJECT_ROOT, run_id, {"pipeline_status": pipeline_status})
    elif execution_requested:
        immediate_result = execute_run(run_id, execute_payload)
        pipeline_status = immediate_result.get("status", "unknown")
        upsert_run_record(PROJECT_ROOT, run_id, {"pipeline_status": pipeline_status})
    else:
        pipeline_status = "prepared_only"
        upsert_run_record(PROJECT_ROOT, run_id, {"pipeline_status": pipeline_status})

    return {
        "run_id": run_id,
        "status": pipeline_status,
        "message": (
            "Pipeline registered. n8n can be connected later as an orchestration layer "
            "that calls this endpoint."
        ),
        "prepared": prepared,
        "result": immediate_result,
        "urls": _public_urls(run_id),
    }


@app.get("/pipeline/status/{run_id}")
def get_pipeline_status(run_id: str) -> Dict[str, Any]:
    manifest = read_run_manifest(PROJECT_ROOT, run_id)
    record = get_run_record(PROJECT_ROOT, run_id)
    return {
        "run_id": run_id,
        "record": record,
        "manifest_status": (manifest or {}).get("status"),
        "artifacts": (manifest or {}).get("artifacts", {}),
        "scenario_alignment": (manifest or {}).get("scenario_alignment"),
        "events": read_events(PROJECT_ROOT, run_id=run_id, limit=100),
        "urls": _public_urls(run_id),
    }


@app.get("/pipeline/history")
def get_pipeline_history(limit: int = 50) -> Dict[str, Any]:
    return {
        "runs": list_run_records(PROJECT_ROOT, limit=limit),
        "events": read_events(PROJECT_ROOT, limit=200),
    }


@app.post("/run/start")
def start_run(payload: ScenarioRequest) -> Dict[str, Any]:
    """run_id를 만들고 시나리오 정의, manifest, preview 보고서를 저장한다."""
    result = agent_graph.invoke({"user_request": payload.user_request})
    run_id = result["run_id"]
    persisted = persist_agent_run(result, PROJECT_ROOT)
    result["persisted_artifacts"] = persisted
    RUN_STORE[run_id] = result
    return {
        "run_id": run_id,
        "status": result["status"],
        "persisted_artifacts": persisted,
        "result": result,
    }


@app.post("/run/prepare/{run_id}")
def prepare_run(run_id: str, payload: PrepareRunRequest) -> Dict[str, Any]:
    """승인 후 실행할 OpenCDA/KPI 명령을 run 폴더에 고정한다."""
    manifest = read_run_manifest(PROJECT_ROOT, run_id)
    if not manifest:
        return {"run_id": run_id, "status": "not_found"}

    scenario_id = _load_scenario_id(manifest)
    opencda_plan = prepare_opencda_execution_plan(
        PROJECT_ROOT,
        manifest,
        apply_ml=payload.apply_ml,
        record=payload.record,
    )
    kpi_plan = prepare_kpi_execution_plan(PROJECT_ROOT, run_id, scenario_id) if payload.include_kpis else None
    execution_plan = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "opencda": opencda_plan,
        "kpi": kpi_plan,
        "simulation_run_agent": {
            "responsibilities": [
                "execute OpenCDA/CARLA command",
                "persist stdout/stderr log",
                "pin latest data_dumping folder",
                "scan log for fatal failure patterns",
                "classify data dump KPI readiness",
                "trigger scenario objective alignment review",
            ],
            "pin_latest_data_dump": True,
            "failure_detection": True,
            "human_in_loop_on_mismatch": True,
        },
    }
    execution_plan_path = _write_execution_plan(PROJECT_ROOT, run_id, execution_plan)

    artifacts = manifest.get("artifacts", {})
    artifacts["execution_plan"] = str(execution_plan_path)
    artifacts["logs_dir"] = str(PROJECT_ROOT / "av_eval_agent" / "data" / "runs" / run_id / "logs")
    manifest.update(
        {
            "status": "ready_for_execution",
            "scenario_id": scenario_id,
            "standard_kpi_contract": (kpi_plan or {}).get("standard_kpi_contract"),
            "commands": opencda_plan.get("commands", []),
            "kpi_commands": (kpi_plan or {}).get("commands", []),
            "simulation_run_agent": execution_plan["simulation_run_agent"],
            "artifacts": artifacts,
        }
    )
    save_run_manifest(PROJECT_ROOT, run_id, manifest)

    return {
        "run_id": run_id,
        "status": "ready_for_execution",
        "execution_plan": execution_plan,
        "execution_plan_path": str(execution_plan_path),
        "manifest": str(manifest_path_for(PROJECT_ROOT, run_id)),
    }


@app.post("/run/execute/{run_id}")
def execute_run(run_id: str, payload: ExecuteRunRequest) -> Dict[str, Any]:
    """실제 실행 worker endpoint.

    기본값은 dry-run이다. 실제 CARLA/OpenCDA 실행은 `execute_simulation=true`일 때만 수행한다.
    """
    prepared = prepare_run(
        run_id,
        PrepareRunRequest(include_kpis=True, apply_ml=payload.apply_ml, record=payload.record),
    )
    if prepared.get("status") == "not_found":
        return prepared

    execution_plan = prepared["execution_plan"]
    if not payload.execute_simulation and not payload.run_kpis:
        return {
            "run_id": run_id,
            "status": "dry_run_prepared",
            "message": "실제 시뮬레이션은 실행하지 않고 명령 계획만 저장했습니다.",
            "execution_plan_path": prepared["execution_plan_path"],
            "execution_plan": execution_plan,
        }

    existing_manifest = read_run_manifest(PROJECT_ROOT, run_id) or {}
    results: Dict[str, Any] = dict(existing_manifest.get("execution_results") or {})
    if payload.execute_simulation:
        results["opencda"] = run_opencda_execution_plan(PROJECT_ROOT, execution_plan["opencda"])
    if payload.run_kpis and execution_plan.get("kpi"):
        results["kpi"] = run_kpi_execution_plan(PROJECT_ROOT, execution_plan["kpi"])

    scenario_alignment = evaluate_scenario_alignment(PROJECT_ROOT, execution_plan["scenario_id"], results)

    manifest = read_run_manifest(PROJECT_ROOT, run_id) or {}
    artifacts = manifest.get("artifacts", {})
    artifacts["execution_result"] = str(PROJECT_ROOT / "av_eval_agent" / "data" / "runs" / run_id / "execution_result.json")
    artifacts["scenario_alignment_review"] = str(
        PROJECT_ROOT / "av_eval_agent" / "data" / "runs" / run_id / "scenario_alignment_review.json"
    )
    if results.get("opencda", {}).get("data_dumps"):
        artifacts["data_dumps"] = results["opencda"]["data_dumps"]
        artifacts["latest_data_dump_by_scenario"] = {
            item["test_scenario"]: item["path"]
            for item in results["opencda"]["data_dumps"]
            if item.get("test_scenario") and item.get("path")
        }

    final_status = (
        "execution_finished_needs_review"
        if scenario_alignment.get("human_in_the_loop", {}).get("required")
        else "execution_finished"
    )
    manifest.update(
        {
            "status": final_status,
            "execution_results": results,
            "scenario_alignment": scenario_alignment,
            "artifacts": artifacts,
        }
    )
    published_artifacts = publish_run_outputs(PROJECT_ROOT, run_id, manifest)
    artifacts.update(published_artifacts)
    manifest["artifacts"] = artifacts
    save_run_manifest(PROJECT_ROOT, run_id, manifest)
    write_json(Path(artifacts["execution_result"]), {"run_id": run_id, "results": results})
    write_json(Path(artifacts["scenario_alignment_review"]), scenario_alignment)
    append_event(
        PROJECT_ROOT,
        run_id,
        "run_execute_finished",
        status=final_status,
        payload={
            "opencda_status": (results.get("opencda") or {}).get("status"),
            "kpi_status": (results.get("kpi") or {}).get("status"),
            "alignment_decision": scenario_alignment.get("decision"),
        },
    )
    upsert_run_record(
        PROJECT_ROOT,
        run_id,
        {
            "pipeline_status": final_status,
            "scenario_id": manifest.get("scenario_id"),
            "manifest": str(manifest_path_for(PROJECT_ROOT, run_id)),
            "final_report": artifacts.get("final_report"),
            "scenario_alignment_decision": scenario_alignment.get("decision"),
        },
    )

    return {
        "run_id": run_id,
        "status": final_status,
        "results": results,
        "scenario_alignment": scenario_alignment,
        "published_artifacts": published_artifacts,
    }


@app.post("/report/generate/{run_id}")
def generate_report(run_id: str) -> Dict[str, Any]:
    """ReportAgent endpoint.

    It publishes the current run manifest into human-readable artifacts without
    re-running CARLA/OpenCDA. n8n can call this after KPIAgent finishes.
    """
    manifest = read_run_manifest(PROJECT_ROOT, run_id)
    if not manifest:
        return {"run_id": run_id, "status": "not_found"}

    manifest.setdefault("run_id", run_id)
    artifacts = manifest.get("artifacts", {})
    manifest["status"] = "report_generated"
    manifest["artifacts"] = artifacts
    published_artifacts = publish_run_outputs(PROJECT_ROOT, run_id, manifest)
    artifacts.update(published_artifacts)
    manifest["artifacts"] = artifacts
    save_run_manifest(PROJECT_ROOT, run_id, manifest)

    append_event(
        PROJECT_ROOT,
        run_id,
        "report_agent_finished",
        status="report_generated",
        payload={"published_artifacts": published_artifacts},
    )
    upsert_run_record(
        PROJECT_ROOT,
        run_id,
        {
            "pipeline_status": "report_generated",
            "scenario_id": manifest.get("scenario_id"),
            "manifest": str(manifest_path_for(PROJECT_ROOT, run_id)),
            "final_report": artifacts.get("final_report"),
        },
    )

    return {
        "run_id": run_id,
        "status": "report_generated",
        "published_artifacts": published_artifacts,
        "artifacts": artifacts,
        "urls": _public_urls(run_id),
    }


@app.get("/memory/recommend/{run_id}")
def recommend_next_steps(run_id: str) -> Dict[str, Any]:
    """MemoryAgent endpoint.

    It compares the current run with previous runs and returns practical next
    actions for the evaluation workflow.
    """
    manifest = read_run_manifest(PROJECT_ROOT, run_id)
    if not manifest:
        return {"run_id": run_id, "status": "not_found"}

    record = get_run_record(PROJECT_ROOT, run_id) or {}
    scenario_id = manifest.get("scenario_id") or record.get("scenario_id") or _load_scenario_id(manifest)
    artifacts = manifest.get("artifacts", {})
    execution_results = manifest.get("execution_results") or {}
    alignment = manifest.get("scenario_alignment") or {}

    previous_runs = [
        item
        for item in list_run_records(PROJECT_ROOT, limit=50)
        if item.get("run_id") != run_id and item.get("scenario_id") == scenario_id
    ][:5]

    recommendations: list[str] = []
    if not artifacts.get("execution_plan"):
        recommendations.append("ExperimentBuildAgent를 먼저 실행해 OpenCDA YAML/PY 실행 계획을 고정해야 합니다.")
    if not execution_results:
        recommendations.append("SimulationRunAgent 또는 KPIAgent 실행 결과가 아직 없어 KPI 기반 비교는 보류합니다.")
    else:
        if not execution_results.get("opencda"):
            recommendations.append("CARLA/OpenCDA 실험 로그가 필요하면 SimulationRunAgent를 execute_simulation=true로 실행합니다.")
        if not execution_results.get("kpi"):
            recommendations.append("공통 KPI 산출을 위해 KPIAgent를 run_kpis=true로 실행합니다.")
    if not artifacts.get("final_report"):
        recommendations.append("ReportAgent를 실행해 최종 보고서 산출물을 생성합니다.")
    if (alignment.get("human_in_the_loop") or {}).get("required"):
        recommendations.append("시나리오 정의서와 실제 실행 로그의 목적 일치성에 대해 human review가 필요합니다.")
    if previous_runs:
        recommendations.append("이전 동일 시나리오 run과 KPI, 데이터 dump 완전성, alignment decision을 비교합니다.")
    else:
        recommendations.append("동일 시나리오의 baseline run이 없으므로 현재 run을 기준 실험으로 저장합니다.")

    next_experiment_candidates = [
        "동일 시나리오에서 V2X/No V2X 조건만 바꾼 paired run 생성",
        "observation time horizon을 동일하게 고정한 KPI 재산출",
        "센서-only perception과 V2X-fusion perception을 분리한 보고서 생성",
    ]

    payload = {
        "run_id": run_id,
        "status": "memory_recommended",
        "scenario_id": scenario_id,
        "current_status": manifest.get("status"),
        "previous_runs_compared": len(previous_runs),
        "similar_runs": previous_runs,
        "recommendations": recommendations,
        "next_experiment_candidates": next_experiment_candidates,
        "urls": _public_urls(run_id),
    }

    append_event(
        PROJECT_ROOT,
        run_id,
        "memory_agent_finished",
        status="memory_recommended",
        payload={
            "previous_runs_compared": len(previous_runs),
            "recommendation_count": len(recommendations),
        },
    )
    upsert_run_record(
        PROJECT_ROOT,
        run_id,
        {
            "pipeline_status": "memory_recommended",
            "scenario_id": scenario_id,
            "memory_recommendation_count": len(recommendations),
        },
    )
    return payload


@app.get("/run/status/{run_id}")
def run_status(run_id: str) -> Dict[str, Any]:
    if run_id not in RUN_STORE:
        manifest = read_run_manifest(PROJECT_ROOT, run_id)
        if not manifest:
            return {"run_id": run_id, "status": "not_found"}
        return {
            "run_id": run_id,
            "status": manifest.get("status", "unknown"),
            "artifacts": manifest.get("artifacts", {}),
            "manifest": manifest,
        }
    return {
        "run_id": run_id,
        "status": RUN_STORE[run_id].get("status", "unknown"),
        "artifacts": RUN_STORE[run_id].get("artifacts", {}),
        "persisted_artifacts": RUN_STORE[run_id].get("persisted_artifacts", {}),
    }


@app.get("/run/result/{run_id}")
def run_result(run_id: str) -> Dict[str, Any]:
    if run_id not in RUN_STORE:
        manifest = read_run_manifest(PROJECT_ROOT, run_id)
        if not manifest:
            return {"run_id": run_id, "status": "not_found"}
        return {"run_id": run_id, "status": manifest.get("status", "unknown"), "manifest": manifest}
    return RUN_STORE[run_id]


@app.get("/run/list")
def run_list() -> Dict[str, Any]:
    return {"runs": list_run_manifests(PROJECT_ROOT)}


if UI_DIR.exists():
    app.mount("/console", StaticFiles(directory=str(UI_DIR), html=True), name="console")
