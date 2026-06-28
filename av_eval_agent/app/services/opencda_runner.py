from __future__ import annotations

import subprocess
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml

from app.services.run_artifact_tracker import (
    datadump_title_for_scenario,
    find_latest_data_dump,
    scan_log_for_failures,
)


SCENARIO_TEST_REGISTRY: dict[str, list[str]] = {
    "scenario_1": ["scenario_1_v2x", "scenario_1_no_v2x"],
    "scenario_2": ["scenario2_v2x", "scenario2"],
}


def infer_test_scenarios(manifest: Dict[str, Any]) -> list[str]:
    scenario_id = "custom"
    scenario_definition_path = manifest.get("scenario_definition")
    if scenario_definition_path:
        try:
            import json

            definition = json.loads(Path(scenario_definition_path).read_text(encoding="utf-8"))
            scenario_id = definition.get("scenario_id", scenario_id)
        except (OSError, ValueError):
            scenario_id = manifest.get("scenario_id", scenario_id)
    return SCENARIO_TEST_REGISTRY.get(scenario_id, [])


def build_opencda_command(
    project_root: Path,
    test_scenario: str,
    *,
    apply_ml: bool = False,
    record: bool = False,
    config_path: str | Path | None = None,
) -> List[str]:
    """OpenCDA 실행 명령을 구성한다.

    `opencda.py`는 파일 경로가 아니라 `scenario_1_v2x` 같은 scenario module 이름을 받는다.
    """

    command = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(project_root / "run_opencda_0914.ps1"),
        "-TestScenario",
        test_scenario,
    ]
    if apply_ml:
        command.append("-ApplyMl")
    if record:
        command.append("-Record")
    if config_path:
        command.extend(["-Config", str(config_path)])
    return command


def scenario_module_path(project_root: Path, test_scenario: str) -> Path:
    return project_root / "opencda" / "scenario_testing" / f"{test_scenario}.py"


def scenario_config_path(project_root: Path, test_scenario: str) -> Path:
    return project_root / "opencda" / "scenario_testing" / "config_yaml" / f"{test_scenario}.yaml"


def generated_config_dir(project_root: Path, run_id: str) -> Path:
    return project_root / "av_eval_agent" / "data" / "runs" / run_id / "generated" / "config_yaml"


def generated_config_path(project_root: Path, run_id: str, test_scenario: str) -> Path:
    return generated_config_dir(project_root, run_id) / f"{test_scenario}.yaml"


def _walk_lidar_configs(node: Any) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if isinstance(node.get("lidar"), dict):
            configs.append(node["lidar"])
        for value in node.values():
            configs.extend(_walk_lidar_configs(value))
    elif isinstance(node, list):
        for item in node:
            configs.extend(_walk_lidar_configs(item))
    return configs


def _apply_run_local_stability_patch(target: Path, test_scenario: str) -> dict[str, Any]:
    """Clamp unstable sensor settings in generated YAML only.

    Scenario 2 uses very dense semantic LiDAR settings for visualization. In
    repeated CARLA/OpenCDA runs this can produce a semantic point/label length
    mismatch inside perception_manager.py. The canonical scenario YAML stays
    untouched; only the copied run-local YAML is reduced to a stable evaluation
    profile.
    """

    if test_scenario not in {"scenario2", "scenario2_v2x"}:
        return {"applied": False, "reason": "not_scenario2"}

    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    changes: list[dict[str, Any]] = []
    for lidar in _walk_lidar_configs(data):
        old_pps = lidar.get("points_per_second")
        old_freq = lidar.get("rotation_frequency")
        if isinstance(old_pps, (int, float)) and old_pps > 1_000_000:
            lidar["points_per_second"] = 1_000_000
            changes.append({"field": "points_per_second", "from": old_pps, "to": 1_000_000})
        if isinstance(old_freq, (int, float)) and old_freq > 20:
            lidar["rotation_frequency"] = 20
            changes.append({"field": "rotation_frequency", "from": old_freq, "to": 20})

    if changes:
        target.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {
        "applied": bool(changes),
        "reason": "scenario2_semantic_lidar_stability",
        "changes": changes,
    }


def ensure_generated_config(project_root: Path, run_id: str, test_scenario: str) -> Path:
    """Copy canonical YAML into the run folder once, then execute that copy.

    AutoTuneAgent can safely patch this generated YAML without touching the
    canonical OpenCDA scenario files.
    """

    source = scenario_config_path(project_root, test_scenario)
    target_dir = generated_config_dir(project_root, run_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    default_source = source.parent / "default.yaml"
    default_target = target_dir / "default.yaml"
    if default_source.exists() and not default_target.exists():
        shutil.copy2(default_source, default_target)

    target = generated_config_path(project_root, run_id, test_scenario)
    if not target.exists():
        shutil.copy2(source, target)
        patch_result = _apply_run_local_stability_patch(target, test_scenario)
        if patch_result.get("applied"):
            patch_meta = target.with_suffix(".stability_patch.json")
            import json

            patch_meta.write_text(
                json.dumps(patch_result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    return target


def validate_runner_target(project_root: Path, test_scenario: str) -> None:
    scenario_py = scenario_module_path(project_root, test_scenario)
    scenario_yaml = scenario_config_path(project_root, test_scenario)
    if not scenario_py.exists():
        raise FileNotFoundError(f"OpenCDA scenario module이 없습니다: {scenario_py}")
    if not scenario_yaml.exists():
        raise FileNotFoundError(f"OpenCDA scenario yaml이 없습니다: {scenario_yaml}")


def prepare_opencda_execution_plan(
    project_root: Path,
    manifest: Dict[str, Any],
    *,
    apply_ml: bool = False,
    record: bool = False,
) -> Dict[str, Any]:
    run_id = manifest["run_id"]
    run_dir = project_root / "av_eval_agent" / "data" / "runs" / run_id
    log_dir = run_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    commands: list[dict[str, Any]] = []
    missing: list[str] = []
    for test_scenario in infer_test_scenarios(manifest):
        config_path: Path | None = None
        try:
            validate_runner_target(project_root, test_scenario)
            config_path = ensure_generated_config(project_root, run_id, test_scenario)
            valid = True
        except FileNotFoundError as exc:
            valid = False
            missing.append(str(exc))

        log_path = log_dir / f"opencda_{test_scenario}.log"
        commands.append(
            {
                "kind": "opencda_simulation",
                "test_scenario": test_scenario,
                "valid": valid,
                "expected_data_dump_title": datadump_title_for_scenario(project_root, test_scenario)
                if valid
                else None,
                "canonical_config_path": str(scenario_config_path(project_root, test_scenario)) if valid else None,
                "generated_config_path": str(config_path) if config_path else None,
                "command": build_opencda_command(
                    project_root,
                    test_scenario,
                    apply_ml=apply_ml,
                    record=record,
                    config_path=config_path,
                ),
                "log_path": str(log_path),
            }
        )

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_id": run_id,
        "apply_ml": apply_ml,
        "record": record,
        "commands": commands,
        "missing": missing,
        "notes": [
            "CARLA 서버가 먼저 실행되어 있어야 합니다.",
            "명령은 opencda.py -t <scenario_name> 구조로 실행됩니다.",
            "현재 단계에서는 canonical OpenCDA module을 실행 대상으로 둡니다. run별 generated_files는 감사/검토용 사본입니다.",
        ],
    }


def run_opencda_execution_plan(project_root: Path, execution_plan: Dict[str, Any]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for command_record in execution_plan.get("commands", []):
        if not command_record.get("valid", False):
            results.append({**command_record, "status": "skipped_invalid_target"})
            continue

        command = command_record["command"]
        log_path = Path(command_record["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.pop("PYTHONPATH", None)

        started_at = datetime.now()
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

        finished_at = datetime.now()
        log_scan = scan_log_for_failures(log_path)
        data_dump = find_latest_data_dump(
            project_root,
            command_record["test_scenario"],
            started_at=started_at,
        )

        if process.returncode != 0 or log_scan.get("fatal"):
            status = "failed"
        elif not data_dump:
            status = "completed_missing_datadump"
        elif not data_dump.get("matched_current_execution"):
            status = "completed_with_stale_datadump"
        elif not data_dump.get("kpi_ready"):
            status = "completed_data_dump_not_kpi_ready"
        else:
            status = "completed"

        results.append(
            {
                **command_record,
                "returncode": process.returncode,
                "started_at": started_at.isoformat(timespec="seconds"),
                "finished_at": finished_at.isoformat(timespec="seconds"),
                "duration_s": round((finished_at - started_at).total_seconds(), 3),
                "log_scan": log_scan,
                "data_dump": data_dump,
                "status": status,
            }
        )

    failed = [item for item in results if item.get("status") == "failed"]
    warning_statuses = {
        "completed_missing_datadump",
        "completed_with_stale_datadump",
        "completed_data_dump_not_kpi_ready",
    }
    warned = [item for item in results if item.get("status") in warning_statuses]

    if results and not failed and not warned:
        overall = "completed"
    elif results and not failed:
        overall = "completed_with_warnings"
    else:
        overall = "failed"
    if not results:
        overall = "no_commands"
    return {
        "run_id": execution_plan.get("run_id"),
        "status": overall,
        "results": results,
        "data_dumps": [item["data_dump"] for item in results if item.get("data_dump")],
    }
