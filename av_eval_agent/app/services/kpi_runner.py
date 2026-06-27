from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


STANDARD_KPI_CONTRACT: dict[str, list[str]] = {
    "perception": ["MOTA", "MOTP"],
    "traffic_impact": ["ProgressAdjustedDelay", "FlowEfficiency"],
    "driving_safety": ["Min2DTTC", "PET", "RequiredDeceleration"],
    "control": ["AccelerationVarianceMax", "YawRateResidualRMS"],
}

UNIVERSAL_KPI_SCRIPT = "scripts/extract_scenario_kpis.py"

SCENARIO_CONFIG_PATTERNS: dict[str, list[str]] = {
    "scenario_1": [
        "opencda/scenario_testing/config_yaml/scenario_1_v2x.yaml",
        "opencda/scenario_testing/config_yaml/scenario_1_no_v2x.yaml",
    ],
    "scenario_2": [
        "opencda/scenario_testing/config_yaml/scenario2_v2x.yaml",
        "opencda/scenario_testing/config_yaml/scenario2.yaml",
    ],
}


def get_standard_kpi_contract() -> dict[str, list[str]]:
    """Return the KPI list that is applied to every scenario."""

    return STANDARD_KPI_CONTRACT


def get_config_patterns(scenario_id: str) -> list[str]:
    """Select input YAML files only; KPI definitions never change by scenario."""

    return SCENARIO_CONFIG_PATTERNS.get(
        scenario_id,
        ["opencda/scenario_testing/config_yaml/scenario*.yaml"],
    )


def _build_universal_kpi_command(
    project_root: Path,
    run_id: str,
    scenario_id: str,
    *,
    python_executable: str,
) -> dict[str, Any]:
    script_path = project_root / UNIVERSAL_KPI_SCRIPT
    output_dir = project_root / "av_eval_agent" / "data" / "runs" / run_id / "kpi"
    data_root = project_root / "data_dumping"

    command: list[str] = [
        python_executable,
        str(script_path),
        "--data-root",
        str(data_root),
        "--output-dir",
        str(output_dir),
    ]

    config_patterns = get_config_patterns(scenario_id)
    for pattern in config_patterns:
        command.extend(["--config", str(project_root / pattern)])

    return {
        "kind": "standard_kpi_calculation",
        "axis": "all",
        "metrics": STANDARD_KPI_CONTRACT,
        "script": str(script_path),
        "valid": script_path.exists(),
        "config_patterns": [str(project_root / pattern) for pattern in config_patterns],
        "command": command,
        "output_dir": str(output_dir),
        "log_path": str(project_root / "av_eval_agent" / "data" / "runs" / run_id / "logs" / "kpi_standard_all.log"),
    }


def prepare_kpi_execution_plan(
    project_root: Path,
    run_id: str,
    scenario_id: str,
    *,
    python_executable: str | None = None,
) -> Dict[str, Any]:
    log_dir = project_root / "av_eval_agent" / "data" / "runs" / run_id / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    python_executable = python_executable or sys.executable
    command = _build_universal_kpi_command(
        project_root,
        run_id,
        scenario_id,
        python_executable=python_executable,
    )

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_id": run_id,
        "scenario_id": scenario_id,
        "standard_kpi_contract": STANDARD_KPI_CONTRACT,
        "commands": [command],
        "notes": [
            "KPI 목록과 계산 축은 시나리오와 무관하게 동일합니다.",
            "scenario_id는 어떤 YAML/로그를 읽을지 고르는 입력 선택에만 사용합니다.",
            "동일 KPI contract를 유지해야 시나리오 간 결과를 같은 radar plot과 점수표로 비교할 수 있습니다.",
        ],
    }


def run_kpi_execution_plan(project_root: Path, kpi_plan: Dict[str, Any]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []

    for command_record in kpi_plan.get("commands", []):
        if not command_record.get("valid", False):
            results.append({**command_record, "status": "skipped_missing_script"})
            continue

        command = command_record["command"]
        log_path = Path(command_record["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()

        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.run(
                command,
                cwd=str(project_root),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                env=env,
            )

        results.append(
            {
                **command_record,
                "returncode": process.returncode,
                "status": "completed" if process.returncode == 0 else "failed",
            }
        )

    if not results:
        status = "no_commands"
    elif all(item.get("status") == "completed" for item in results):
        status = "completed"
    elif any(item.get("status") == "completed" for item in results):
        status = "partial"
    else:
        status = "failed"

    return {
        "run_id": kpi_plan.get("run_id"),
        "scenario_id": kpi_plan.get("scenario_id"),
        "standard_kpi_contract": kpi_plan.get("standard_kpi_contract", STANDARD_KPI_CONTRACT),
        "status": status,
        "results": results,
    }
