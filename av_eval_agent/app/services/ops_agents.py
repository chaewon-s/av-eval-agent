from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.artifact_store import read_run_manifest, save_run_manifest, write_json
from app.services.experiment_history import append_event, upsert_run_record
from app.services.kpi_runner import get_config_patterns


def _tcp_check(host: str, port: int, timeout_s: float = 1.0) -> dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return {"name": f"{host}:{port}", "status": "ok", "detail": "tcp port reachable"}
    except OSError as exc:
        return {"name": f"{host}:{port}", "status": "failed", "detail": str(exc)}


def run_preflight_agent(project_root: Path, scenario_id: str | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = [
        {"name": "project_root", "status": "ok" if project_root.exists() else "failed", "detail": str(project_root)},
        _tcp_check("127.0.0.1", 2000),
        _tcp_check("127.0.0.1", 5678),
        {
            "name": "opencda.py",
            "status": "ok" if (project_root / "opencda.py").exists() else "failed",
            "detail": str(project_root / "opencda.py"),
        },
        {
            "name": "run_opencda_0914.ps1",
            "status": "ok" if (project_root / "run_opencda_0914.ps1").exists() else "failed",
            "detail": str(project_root / "run_opencda_0914.ps1"),
        },
        {
            "name": "data_dumping",
            "status": "ok" if (project_root / "data_dumping").exists() else "warning",
            "detail": str(project_root / "data_dumping"),
        },
    ]

    if scenario_id:
        for pattern in get_config_patterns(scenario_id):
            path = project_root / pattern
            checks.append(
                {
                    "name": f"config:{path.name}",
                    "status": "ok" if path.exists() else "failed",
                    "detail": str(path),
                }
            )

    failed = [check for check in checks if check["status"] == "failed"]
    warnings = [check for check in checks if check["status"] == "warning"]
    if failed:
        status = "failed"
    elif warnings:
        status = "warning"
    else:
        status = "ok"

    return {
        "agent": "PreflightAgent",
        "status": status,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "scenario_id": scenario_id,
        "checks": checks,
        "summary": {
            "ok": sum(1 for check in checks if check["status"] == "ok"),
            "warning": len(warnings),
            "failed": len(failed),
        },
    }


def _read_text_tail(path: Path, max_chars: int = 20000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]


def _diagnose_log(log_name: str, text: str) -> list[dict[str, Any]]:
    lower = text.lower()
    findings: list[dict[str, Any]] = []

    if "boolean index did not match indexed array" in lower:
        findings.append(
            {
                "severity": "error",
                "code": "semantic_lidar_point_label_mismatch",
                "log": log_name,
                "message": "Semantic LiDAR point cloud and semantic label arrays had different lengths.",
                "recommended_action": (
                    "Retry with lower LiDAR points_per_second/rotation_frequency in the run-local YAML, "
                    "or use a stable perception dump mode for KPI extraction."
                ),
            }
        )

    if "traceback (most recent call last)" in lower:
        findings.append(
            {
                "severity": "error",
                "code": "python_traceback",
                "log": log_name,
                "message": "OpenCDA Python execution raised an exception.",
                "recommended_action": "Inspect the preceding traceback and run a retry after applying a run-local recovery patch.",
            }
        )

    if "'collision': true" in lower or '"collision": true' in lower:
        findings.append(
            {
                "severity": "warning",
                "code": "collision_warning",
                "log": log_name,
                "message": "CARLA safety manager reported collision=True.",
                "recommended_action": "Check whether this collision is intentional for the scenario or indicates timing/tuning failure.",
            }
        )

    if "sensor object went out of the scope" in lower:
        findings.append(
            {
                "severity": "warning",
                "code": "sensor_lifecycle_warning",
                "log": log_name,
                "message": "CARLA sensor lifecycle warning detected after scenario shutdown.",
                "recommended_action": "Usually non-fatal, but cleanup should be reviewed if repeated.",
            }
        )

    if "connection refused" in lower or "failed to connect" in lower:
        findings.append(
            {
                "severity": "error",
                "code": "carla_connection_failure",
                "log": log_name,
                "message": "The runner could not connect to CARLA.",
                "recommended_action": "Start CARLA server before SimulationRunAgent or add an automated CARLA launcher node.",
            }
        )

    return findings


def run_failure_diagnosis_agent(project_root: Path, run_id: str) -> dict[str, Any]:
    manifest = read_run_manifest(project_root, run_id) or {}
    run_dir = project_root / "av_eval_agent" / "data" / "runs" / run_id
    logs_dir = run_dir / "logs"
    findings: list[dict[str, Any]] = []
    log_summaries: list[dict[str, Any]] = []

    for log_path in sorted(logs_dir.glob("*.log")):
        text = _read_text_tail(log_path)
        log_findings = _diagnose_log(log_path.name, text)
        findings.extend(log_findings)
        log_summaries.append(
            {
                "name": log_path.name,
                "path": str(log_path),
                "size_bytes": log_path.stat().st_size,
                "finding_count": len(log_findings),
                "tail_excerpt": text[-1200:],
            }
        )

    error_count = sum(1 for item in findings if item.get("severity") == "error")
    warning_count = sum(1 for item in findings if item.get("severity") == "warning")
    if error_count:
        status = "failed_needs_recovery"
    elif warning_count:
        status = "completed_with_warnings"
    else:
        status = "clean"

    diagnosis = {
        "agent": "FailureDiagnosisAgent",
        "run_id": run_id,
        "status": status,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "finding_count": len(findings),
        "error_count": error_count,
        "warning_count": warning_count,
        "findings": findings,
        "log_summaries": log_summaries,
        "recommended_next_node": "AutoTuneAgent" if error_count else "QualityGateAgent",
    }

    diagnosis_path = run_dir / "failure_diagnosis.json"
    write_json(diagnosis_path, diagnosis)
    artifacts = manifest.get("artifacts", {})
    artifacts["failure_diagnosis"] = str(diagnosis_path)
    manifest["artifacts"] = artifacts
    manifest["failure_diagnosis"] = {
        "status": status,
        "error_count": error_count,
        "warning_count": warning_count,
    }
    save_run_manifest(project_root, run_id, manifest)
    append_event(
        project_root,
        run_id,
        "failure_diagnosis_agent_finished",
        status=status,
        payload={"error_count": error_count, "warning_count": warning_count},
    )
    upsert_run_record(project_root, run_id, {"failure_diagnosis": status})
    return diagnosis


def run_quality_gate_agent(project_root: Path, run_id: str) -> dict[str, Any]:
    manifest = read_run_manifest(project_root, run_id) or {}
    artifacts = manifest.get("artifacts", {})
    results = manifest.get("execution_results", {})
    alignment = manifest.get("scenario_alignment", {})
    diagnosis = manifest.get("failure_diagnosis", {})

    gates = [
        {
            "name": "OpenCDA execution",
            "status": "pass" if (results.get("opencda") or {}).get("status") == "completed" else "review",
            "detail": (results.get("opencda") or {}).get("status", "missing"),
        },
        {
            "name": "KPI calculation",
            "status": "pass" if (results.get("kpi") or {}).get("status") == "completed" else "fail",
            "detail": (results.get("kpi") or {}).get("status", "missing"),
        },
        {
            "name": "Scenario alignment",
            "status": "pass" if alignment.get("decision") not in {"human_review_required", "failed"} else "review",
            "detail": alignment.get("decision", "missing"),
        },
        {
            "name": "Failure diagnosis",
            "status": (
                "pass"
                if diagnosis.get("error_count", 0) == 0 and diagnosis.get("warning_count", 0) == 0
                else "review"
            ),
            "detail": diagnosis.get("status", "not_run"),
        },
    ]

    if any(gate["status"] == "fail" for gate in gates):
        status = "fail"
    elif any(gate["status"] == "review" for gate in gates):
        status = "human_review_required"
    else:
        status = "pass"

    quality_gate = {
        "agent": "RunQualityGateAgent",
        "run_id": run_id,
        "status": status,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "gates": gates,
        "summary": {
            "pass": sum(1 for gate in gates if gate["status"] == "pass"),
            "review": sum(1 for gate in gates if gate["status"] == "review"),
            "fail": sum(1 for gate in gates if gate["status"] == "fail"),
        },
    }

    run_dir = project_root / "av_eval_agent" / "data" / "runs" / run_id
    quality_gate_path = run_dir / "quality_gate.json"
    write_json(quality_gate_path, quality_gate)
    artifacts["quality_gate"] = str(quality_gate_path)
    manifest["artifacts"] = artifacts
    manifest["quality_gate"] = quality_gate
    save_run_manifest(project_root, run_id, manifest)
    append_event(project_root, run_id, "quality_gate_agent_finished", status=status, payload=quality_gate["summary"])
    upsert_run_record(project_root, run_id, {"quality_gate": status})
    return quality_gate
