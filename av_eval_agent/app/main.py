from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

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
from app.services.kpi_runner import prepare_kpi_execution_plan, run_kpi_execution_plan
from app.services.opencda_runner import prepare_opencda_execution_plan, run_opencda_execution_plan
from app.services.experiment_history import append_event, get_run_record, list_run_records, read_events, upsert_run_record
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


def _public_urls(run_id: str) -> Dict[str, str]:
    return {
        "status": f"http://127.0.0.1:8010/pipeline/status/{run_id}",
        "run_status": f"http://127.0.0.1:8010/run/status/{run_id}",
        "run_result": f"http://127.0.0.1:8010/run/result/{run_id}",
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
        append_event(
            PROJECT_ROOT,
            run_id,
            "pipeline_worker_finished",
            status=result.get("status", "unknown"),
            payload={"status": result.get("status")},
        )
        upsert_run_record(
            PROJECT_ROOT,
            run_id,
            {
                "pipeline_status": result.get("status", "unknown"),
                "scenario_alignment_decision": (result.get("scenario_alignment") or {}).get("decision"),
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
            "dashboard": artifacts.get("dashboard"),
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
    """run_id를 만들고 시나리오 정의, manifest, preview dashboard를 저장한다."""
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
            "final_dashboard": artifacts.get("final_dashboard"),
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
