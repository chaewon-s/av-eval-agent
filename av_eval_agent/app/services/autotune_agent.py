from __future__ import annotations

import csv
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from app.services.artifact_store import read_run_manifest, save_run_manifest, write_json
from app.services.opencda_runner import generated_config_path


ALLOWED_PATCH_PATHS: set[str] = {
    "scenario.max_ticks",
    "scenario.actor_start_delay_ticks",
    "scenario.ego_start_delay_ticks",
    "scenario.v2x_communication_range_m",
    "scenario.single_cav_list[0].v2x.communication_range",
    "scenario.single_cav_list[1].v2x.communication_range",
    "scenario.single_cav_list[2].v2x.communication_range",
    "scenario.single_cav_list[0].behavior.max_speed",
    "scenario.single_cav_list[1].behavior.max_speed",
    "scenario.single_cav_list[2].behavior.max_speed",
}


def _read_json(path: str | Path | None, default: Any) -> Any:
    if not path:
        return default
    target = Path(path)
    if not target.exists():
        return default
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_csv_rows(path: Path, limit: int = 50) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))[:limit]
    except OSError:
        return []


def _load_kpi_snapshot(project_root: Path, run_id: str) -> dict[str, Any]:
    kpi_dir = project_root / "av_eval_agent" / "data" / "runs" / run_id / "kpi"
    return {
        "kpi_dir": str(kpi_dir),
        "kpi_summary": _read_csv_rows(kpi_dir / "kpi_summary.csv"),
        "score_summary": _read_csv_rows(kpi_dir / "score_summary.csv"),
    }


def _generated_config_records(project_root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    run_id = str(manifest.get("run_id", ""))
    for command in manifest.get("commands") or []:
        test_scenario = command.get("test_scenario")
        if not test_scenario:
            continue
        path = command.get("generated_config_path") or str(generated_config_path(project_root, run_id, test_scenario))
        records.append(
            {
                "test_scenario": test_scenario,
                "path": path,
                "exists": Path(path).exists(),
            }
        )
    return records


def _extract_json_object(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _openai_autotune_decision(
    prompt_payload: dict[str, Any],
    *,
    model: str,
    temperature: float | None = None,
    timeout_s: int = 60,
) -> dict[str, Any] | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key or api_key in {"여기에_API_KEY", "YOUR_API_KEY"}:
        return None

    system_prompt = (
        "You are AutoTuneAgent for an autonomous-driving CARLA/OpenCDA evaluation system. "
        "Inspect scenario definition, run logs/KPI summaries, and objective alignment. "
        "Return only strict JSON. Do not overwrite canonical scenario files. "
        "Allowed patch paths are limited to timing, max_ticks, communication range, and max_speed. "
        "Prefer human review when collision/near-crash intent is ambiguous."
    )
    user_prompt = json.dumps(
        {
            "task": "Recommend the next experiment adjustment.",
            "allowed_patch_paths": sorted(ALLOWED_PATCH_PATHS),
            "required_output_schema": {
                "decision": "accept | rerun_with_adjustments | needs_human_review",
                "confidence": "0..1",
                "reason": "short Korean explanation",
                "patches": [
                    {
                        "test_scenario": "scenario module name",
                        "path": "dot path from allowed_patch_paths",
                        "new": "new value",
                        "reason": "why this change is expected to help",
                    }
                ],
                "expected_effect": "Korean explanation",
                "requires_human_approval": True,
            },
            "context": prompt_payload,
        },
        ensure_ascii=False,
    )
    request_payload: dict[str, Any] = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if temperature is not None:
        request_payload["temperature"] = temperature
    request_body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    output_text = payload.get("output_text")
    if not output_text:
        chunks: list[str] = []
        for item in payload.get("output", []) or []:
            for content in item.get("content", []) or []:
                text = content.get("text")
                if text:
                    chunks.append(text)
        output_text = "\n".join(chunks)
    return _extract_json_object(output_text or "")


def _fallback_decision(
    *,
    scenario_id: str,
    alignment: dict[str, Any],
    execution_results: dict[str, Any],
    kpi_snapshot: dict[str, Any],
) -> dict[str, Any]:
    decision = alignment.get("decision") or "needs_human_review"
    issues = alignment.get("issues") or []
    opencda_status = (execution_results.get("opencda") or {}).get("status")
    kpi_status = (execution_results.get("kpi") or {}).get("status")

    if decision == "aligned" and opencda_status in {None, "completed"}:
        return {
            "decision": "accept",
            "confidence": 0.65,
            "reason": "시나리오 정의와 KPI 결과가 현재 기준에서 정합하므로 추가 조정 없이 수용합니다.",
            "patches": [],
            "expected_effect": "현재 설정을 유지하면 동일 조건에서 재현 가능한 KPI 산출이 가능합니다.",
            "requires_human_approval": False,
            "source": "rule_fallback",
        }

    if opencda_status in {"failed", "no_commands"} or kpi_status == "failed":
        return {
            "decision": "needs_human_review",
            "confidence": 0.8,
            "reason": "OpenCDA 실행 또는 KPI 계산이 실패하여 자동 조정보다 원인 진단과 사람 검토가 우선입니다.",
            "patches": [],
            "expected_effect": "실패 원인을 확인한 뒤 재실행 조건을 제한적으로 수정할 수 있습니다.",
            "requires_human_approval": True,
            "source": "rule_fallback",
            "issues": issues,
        }

    patches: list[dict[str, Any]] = []
    if scenario_id == "scenario_1":
        patches = [
            {
                "test_scenario": "scenario_1_v2x",
                "path": "scenario.v2x_communication_range_m",
                "new": 20,
                "reason": "연구 기준의 20m V2X 통신 반경을 명시하여 조기 인지 조건을 일관되게 유지합니다.",
            },
            {
                "test_scenario": "scenario_1_no_v2x",
                "path": "scenario.actor_start_delay_ticks",
                "new": 0,
                "reason": "No V2X 조건에서 시각 인지 이후 near-crash 흐름이 나타나도록 actor 출발 지연을 보정합니다.",
            },
        ]
    elif scenario_id == "scenario_2":
        patches = [
            {
                "test_scenario": "scenario2_v2x",
                "path": "scenario.single_cav_list[1].v2x.communication_range",
                "new": 20,
                "reason": "ego 바로 앞 차량의 통신 범위를 명시하여 cooperative perception 조건을 재현합니다.",
            },
            {
                "test_scenario": "scenario2_v2x",
                "path": "scenario.single_cav_list[1].v2x.enabled",
                "new": True,
                "reason": "V2X 조건에서는 선행 차량이 협력 인지 메시지를 제공해야 하므로 통신을 활성화합니다.",
            },
        ]

    return {
        "decision": "rerun_with_adjustments" if patches else "needs_human_review",
        "confidence": 0.55,
        "reason": "GPT API를 사용할 수 없어 규칙 기반 fallback으로 제한된 조정안을 생성했습니다.",
        "patches": patches,
        "expected_effect": "대표 시나리오 조건을 보정하여 V2X와 No V2X의 비교 흐름을 더 명확히 할 수 있습니다.",
        "requires_human_approval": True,
        "source": "rule_fallback",
        "kpi_snapshot_available": bool(kpi_snapshot.get("kpi_summary") or kpi_snapshot.get("score_summary")),
    }

def _parse_path_token(token: str) -> tuple[str, int | None]:
    match = re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", token)
    if not match:
        return token, None
    return match.group(1), int(match.group(2)) if match.group(2) is not None else None


def _set_by_dot_path(data: dict[str, Any], path: str, value: Any) -> None:
    current: Any = data
    parts = path.split(".")
    for part in parts[:-1]:
        key, index = _parse_path_token(part)
        current = current.setdefault(key, {})
        if index is not None:
            current = current[index]
    key, index = _parse_path_token(parts[-1])
    if index is None:
        current[key] = value
    else:
        current[key][index] = value


def _get_by_dot_path(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        key, index = _parse_path_token(part)
        current = current[key]
        if index is not None:
            current = current[index]
    return current


def _apply_yaml_patches(
    project_root: Path,
    run_id: str,
    decision: dict[str, Any],
) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for patch in decision.get("patches") or []:
        path = str(patch.get("path", ""))
        test_scenario = str(patch.get("test_scenario", ""))
        if path not in ALLOWED_PATCH_PATHS:
            applied.append({**patch, "applied": False, "reason": "patch path is not allow-listed"})
            continue
        yaml_path = generated_config_path(project_root, run_id, test_scenario)
        if not yaml_path.exists():
            applied.append({**patch, "applied": False, "reason": "generated YAML does not exist"})
            continue
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        try:
            old_value = _get_by_dot_path(data, path)
        except (KeyError, IndexError, TypeError):
            old_value = None
        _set_by_dot_path(data, path, patch.get("new"))
        yaml_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        applied.append(
            {
                **patch,
                "applied": True,
                "old": old_value,
                "generated_config_path": str(yaml_path),
            }
        )
    return applied


def run_autotune_agent(project_root: Path, run_id: str, request: dict[str, Any]) -> dict[str, Any]:
    manifest = read_run_manifest(project_root, run_id)
    if not manifest:
        return {"agent": "AutoTuneAgent", "run_id": run_id, "status": "not_found"}

    scenario_definition = _read_json(manifest.get("scenario_definition"), {})
    execution_results = manifest.get("execution_results") or {}
    alignment = manifest.get("scenario_alignment") or {}
    scenario_id = manifest.get("scenario_id") or scenario_definition.get("scenario_id") or "custom"
    kpi_snapshot = _load_kpi_snapshot(project_root, run_id)
    config_records = _generated_config_records(project_root, manifest)

    reproducibility = {
        "model": request.get("model") or "gpt-4.1-mini",
        "temperature": request.get("temperature", 0.2),
        "seed": request.get("seed"),
        "model_version_note": request.get("model_version_note"),
        "note": (
            "The Responses API model snapshot is recorded for audit. "
            "The seed is logged as an experiment control value; if the upstream model "
            "does not support deterministic seeding, repeatability is enforced by "
            "bounded patches and human approval rather than exact token-level replay."
        ),
    }

    prompt_payload = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_definition": scenario_definition,
        "execution_results_summary": execution_results,
        "scenario_alignment": alignment,
        "kpi_snapshot": kpi_snapshot,
        "generated_configs": config_records,
        "human_notes": request.get("notes"),
        "reproducibility": reproducibility,
    }

    model = str(request.get("model") or "gpt-4.1-mini")
    temperature = request.get("temperature", 0.2)
    try:
        temperature_value = float(temperature) if temperature is not None else None
    except (TypeError, ValueError):
        temperature_value = 0.2
    decision = _openai_autotune_decision(prompt_payload, model=model, temperature=temperature_value)
    if decision is None:
        decision = _fallback_decision(
            scenario_id=str(scenario_id),
            alignment=alignment,
            execution_results=execution_results,
            kpi_snapshot=kpi_snapshot,
        )
    else:
        decision.setdefault("source", "openai_responses_api")

    allowed_patches = []
    rejected_patches = []
    for patch in decision.get("patches") or []:
        if patch.get("path") in ALLOWED_PATCH_PATHS:
            allowed_patches.append(patch)
        else:
            rejected_patches.append({**patch, "rejected_reason": "patch path is not allow-listed"})
    decision["patches"] = allowed_patches
    decision["rejected_patches"] = rejected_patches

    applied: list[dict[str, Any]] = []
    apply_patches = bool(request.get("apply_patches", False))
    if apply_patches and not decision.get("requires_human_approval", True):
        applied = _apply_yaml_patches(project_root, run_id, decision)

    result = {
        "agent": "AutoTuneAgent",
        "run_id": run_id,
        "status": "autotune_decision_ready",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "reproducibility": reproducibility,
        "enabled": bool(request.get("enabled", True)),
        "apply_patches_requested": apply_patches,
        "decision": decision,
        "applied_patches": applied,
        "generated_configs": config_records,
        "next_step": (
            "human_review"
            if decision.get("requires_human_approval", True)
            else ("rerun_simulation" if decision.get("decision") == "rerun_with_adjustments" else "accept")
        ),
    }

    run_dir = project_root / "av_eval_agent" / "data" / "runs" / run_id
    path = run_dir / "autotune_decision.json"
    write_json(path, result)

    artifacts = manifest.get("artifacts", {})
    artifacts["autotune_decision"] = str(path)
    manifest["artifacts"] = artifacts
    manifest["autotune"] = result
    save_run_manifest(project_root, run_id, manifest)
    return result
