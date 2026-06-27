from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


ERROR_PATTERNS = [
    "traceback (most recent call last)",
    "modulenotfounderror",
    "filenotfounderror",
    "importerror",
    "runtimeerror",
    "timeouterror",
    "failed to connect",
    "connection refused",
    "address already in use",
]


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def scenario_config_path(project_root: Path, test_scenario: str) -> Path:
    return project_root / "opencda" / "scenario_testing" / "config_yaml" / f"{test_scenario}.yaml"


def datadump_title_for_scenario(project_root: Path, test_scenario: str) -> str:
    config = read_yaml(scenario_config_path(project_root, test_scenario))
    vehicle_base = config.get("vehicle_base") or {}
    datadump = vehicle_base.get("datadump") or {}
    title = datadump.get("title")
    if title:
        return str(title)
    return {
        "scenario_1_v2x": "scenario1_v2x",
        "scenario_1_no_v2x": "scenario1_no_v2x",
        "scenario2_v2x": "scenario2_v2x",
        "scenario2": "scenario2_no_v2x",
    }.get(test_scenario, test_scenario)


def _latest_write_time(path: Path) -> datetime | None:
    if not path.exists():
        return None
    latest = datetime.fromtimestamp(path.stat().st_mtime)
    if path.is_dir():
        for child in path.rglob("*"):
            try:
                child_time = datetime.fromtimestamp(child.stat().st_mtime)
            except OSError:
                continue
            if child_time > latest:
                latest = child_time
    return latest


def summarize_data_dump(run_dir: Path) -> dict[str, Any]:
    actor_dirs = [
        item
        for item in run_dir.iterdir()
        if item.is_dir() and item.name != "topview_screen"
    ] if run_dir.exists() else []
    actor_yaml_counts = {
        item.name: len(list(item.glob("*.yaml")))
        for item in actor_dirs
    }
    topview_dir = run_dir / "topview_screen"
    topview_files = []
    if topview_dir.exists():
        topview_files = [
            str(path)
            for path in sorted(topview_dir.iterdir())
            if path.is_file()
        ]

    protocol_path = run_dir / "data_protocol.yaml"
    total_actor_frames = sum(actor_yaml_counts.values())
    if total_actor_frames > 0:
        completeness = "vehicle_frame_logs"
    elif topview_files:
        completeness = "recording_only"
    elif protocol_path.exists():
        completeness = "protocol_only"
    else:
        completeness = "empty"

    latest_write = _latest_write_time(run_dir)
    return {
        "path": str(run_dir),
        "name": run_dir.name,
        "exists": run_dir.exists(),
        "data_protocol": str(protocol_path) if protocol_path.exists() else None,
        "actor_dirs": [item.name for item in actor_dirs],
        "actor_yaml_counts": actor_yaml_counts,
        "total_actor_frames": total_actor_frames,
        "topview_files": topview_files,
        "completeness": completeness,
        "kpi_ready": total_actor_frames > 0,
        "latest_write_time": latest_write.isoformat(timespec="seconds") if latest_write else None,
    }


def find_latest_data_dump(
    project_root: Path,
    test_scenario: str,
    *,
    started_at: datetime | None = None,
) -> dict[str, Any] | None:
    title = datadump_title_for_scenario(project_root, test_scenario)
    title_dir = project_root / "data_dumping" / title
    if not title_dir.exists():
        return None

    candidates = [item for item in title_dir.iterdir() if item.is_dir()]
    if not candidates:
        return None

    grace_start = started_at - timedelta(seconds=30) if started_at else None
    scored: list[tuple[datetime, Path, bool]] = []
    for candidate in candidates:
        latest_write = _latest_write_time(candidate)
        if latest_write is None:
            continue
        matched_current_execution = bool(grace_start and latest_write >= grace_start)
        scored.append((latest_write, candidate, matched_current_execution))

    if not scored:
        return None

    current_matches = [item for item in scored if item[2]]
    latest_write, latest_dir, matched_current_execution = max(
        current_matches or scored,
        key=lambda item: item[0],
    )
    summary = summarize_data_dump(latest_dir)
    summary.update(
        {
            "test_scenario": test_scenario,
            "dump_title": title,
            "matched_current_execution": matched_current_execution,
            "selected_by": "latest_after_command_start" if matched_current_execution else "latest_available",
        }
    )
    return summary


def scan_log_for_failures(log_path: Path, *, max_chars: int = 300_000) -> dict[str, Any]:
    if not log_path.exists():
        return {
            "log_path": str(log_path),
            "exists": False,
            "fatal": True,
            "matches": ["log file missing"],
        }

    text = log_path.read_text(encoding="utf-8", errors="replace")[-max_chars:]
    lowered = text.lower()
    matches = [pattern for pattern in ERROR_PATTERNS if pattern in lowered]
    return {
        "log_path": str(log_path),
        "exists": True,
        "fatal": bool(matches),
        "matches": matches,
    }


def collect_data_dump_summary(project_root: Path, execution_results: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for item in execution_results.get("results", []):
        data_dump = item.get("data_dump")
        if data_dump:
            summaries.append(data_dump)
    return summaries
