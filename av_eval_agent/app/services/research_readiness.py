from __future__ import annotations

import json
import platform
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.artifact_store import read_run_manifest, save_run_manifest, sha256_file, write_json, write_text
from app.services.experiment_history import append_event, upsert_run_record


def _status_from_checks(checks: list[dict[str, Any]]) -> str:
    if any(check["status"] == "fail" for check in checks):
        return "research_blocked"
    if any(check["status"] == "review" for check in checks):
        return "research_review_required"
    return "research_ready"


def _artifact_check(name: str, path_text: str | None, *, required: bool = True) -> dict[str, Any]:
    if not path_text:
        return {
            "name": name,
            "status": "fail" if required else "review",
            "detail": "artifact path missing",
        }
    path = Path(path_text)
    if not path.exists():
        return {
            "name": name,
            "status": "fail" if required else "review",
            "detail": f"missing: {path}",
        }
    return {"name": name, "status": "pass", "detail": str(path)}


def _hash_artifacts(paths: list[str | None]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path_text in paths:
        if not path_text:
            continue
        path = Path(path_text)
        if not path.exists() or not path.is_file():
            continue
        records.append(
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return records


def _collect_stability_patches(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((run_dir / "generated" / "config_yaml").glob("*.stability_patch.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"parse_error": True}
        records.append({"path": str(path), "payload": payload})
    return records


def _build_submission_summary(
    *,
    run_id: str,
    manifest: dict[str, Any],
    readiness: dict[str, Any],
    artifact_hashes: list[dict[str, Any]],
    stability_patches: list[dict[str, Any]],
) -> str:
    artifacts = manifest.get("artifacts") or {}
    execution = manifest.get("execution_results") or {}
    opencda = execution.get("opencda") or {}
    kpi = execution.get("kpi") or {}
    data_dumps = opencda.get("data_dumps") or artifacts.get("data_dumps") or []
    diagnosis = manifest.get("failure_diagnosis") or {}
    quality_gate = manifest.get("quality_gate") or {}

    lines = [
        f"# 연구기관 제출용 실행 검증 요약: {run_id}",
        "",
        "## 1. 제출 판정",
        "",
        f"- 판정: `{readiness['status']}`",
        f"- 권고: {readiness['recommendation']}",
        f"- 생성 시각: {readiness['created_at']}",
        "",
        "## 2. 실행 체인",
        "",
        "| 단계 | 상태 | 근거 |",
        "| --- | --- | --- |",
        f"| OpenCDA/CARLA 실행 | {(opencda or {}).get('status', '-')} | `execution_result.json` |",
        f"| KPI 계산 | {(kpi or {}).get('status', '-')} | `kpi/` 산출물 |",
        f"| 실패 진단 | {diagnosis.get('status', '-')} | error={diagnosis.get('error_count', 0)}, warning={diagnosis.get('warning_count', 0)} |",
        f"| 품질 게이트 | {quality_gate.get('status', '-')} | `quality_gate.json` |",
        "",
        "## 3. 고정된 data dump",
        "",
        "| 조건 | run folder | frame count | KPI ready |",
        "| --- | --- | ---: | --- |",
    ]
    if data_dumps:
        for dump in data_dumps:
            lines.append(
                f"| {dump.get('test_scenario', '-')} | `{dump.get('path', '-')}` | "
                f"{dump.get('total_actor_frames', '-')} | {dump.get('kpi_ready', '-')} |"
            )
    else:
        lines.append("| - | - | - | - |")

    lines.extend(
        [
            "",
            "## 4. ResearchReadinessAgent 점검",
            "",
            "| 점검 항목 | 상태 | 상세 |",
            "| --- | --- | --- |",
        ]
    )
    for check in readiness["checks"]:
        lines.append(f"| {check['name']} | {check['status']} | {check['detail']} |")

    lines.extend(
        [
            "",
            "## 5. 재현성 정보",
            "",
            f"- Python: `{platform.python_version()}`",
            f"- OS: `{platform.platform()}`",
            f"- 시나리오 ID: `{manifest.get('scenario_id', '-')}`",
            f"- 시나리오 정의서: `{manifest.get('scenario_definition', '-')}`",
            f"- 실행 계획: `{artifacts.get('execution_plan', '-')}`",
            f"- KPI 결과 폴더: `{((kpi.get('results') or [{}])[0]).get('output_dir') if kpi.get('results') else '-'}`",
            "",
            "## 6. 파일 해시",
            "",
            "| 파일 | sha256 | size bytes |",
            "| --- | --- | ---: |",
        ]
    )
    for record in artifact_hashes:
        lines.append(f"| `{record['path']}` | `{record['sha256']}` | {record['size_bytes']} |")
    if not artifact_hashes:
        lines.append("| - | - | - |")

    lines.extend(["", "## 7. Run-local 안정화 패치", ""])
    if stability_patches:
        for patch in stability_patches:
            lines.append(f"- `{patch['path']}`")
            for change in (patch.get("payload") or {}).get("changes", []):
                lines.append(
                    f"  - {change.get('field')}: {change.get('from')} -> {change.get('to')}"
                )
    else:
        lines.append("- 적용된 run-local 안정화 패치 없음")

    lines.extend(
        [
            "",
            "## 8. 운영 원칙",
            "",
            "- 원본 OpenCDA 파일은 직접 수정하지 않고 run-local generated YAML/PY를 사용한다.",
            "- fatal error는 `research_blocked`, 경고 또는 충돌 warning은 `research_review_required`로 분류한다.",
            "- 연구자는 Slack/HITL에서 approve/revise/rerun/reject 중 하나를 선택한다.",
            "- 동일 KPI contract를 모든 시나리오에 적용하고, 시나리오별로 입력 YAML과 event horizon만 달라진다.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_research_readiness_agent(project_root: Path, run_id: str) -> dict[str, Any]:
    manifest = read_run_manifest(project_root, run_id)
    if not manifest:
        return {
            "agent": "ResearchReadinessAgent",
            "run_id": run_id,
            "status": "not_found",
            "checks": [{"name": "run_manifest", "status": "fail", "detail": "manifest not found"}],
        }

    run_dir = project_root / "av_eval_agent" / "data" / "runs" / run_id
    artifacts = manifest.get("artifacts") or {}
    execution = manifest.get("execution_results") or {}
    opencda = execution.get("opencda") or {}
    kpi = execution.get("kpi") or {}
    alignment = manifest.get("scenario_alignment") or {}
    diagnosis = manifest.get("failure_diagnosis") or {}
    quality_gate = manifest.get("quality_gate") or {}
    data_dumps = opencda.get("data_dumps") or artifacts.get("data_dumps") or []

    checks: list[dict[str, Any]] = [
        _artifact_check("run_manifest", str(run_dir / "run_manifest.json")),
        _artifact_check("scenario_definition_json", manifest.get("scenario_definition")),
        _artifact_check("scenario_definition_form_csv", artifacts.get("scenario_definition_form_csv")),
        _artifact_check("execution_plan_json", artifacts.get("execution_plan")),
        _artifact_check("execution_result_json", artifacts.get("execution_result")),
        _artifact_check("failure_diagnosis_json", artifacts.get("failure_diagnosis")),
        _artifact_check("quality_gate_json", artifacts.get("quality_gate")),
    ]

    checks.append(
        {
            "name": "opencda_execution",
            "status": "pass" if opencda.get("status") == "completed" else "fail",
            "detail": opencda.get("status", "missing"),
        }
    )
    checks.append(
        {
            "name": "kpi_calculation",
            "status": "pass" if kpi.get("status") == "completed" else "fail",
            "detail": kpi.get("status", "missing"),
        }
    )
    checks.append(
        {
            "name": "scenario_alignment",
            "status": "pass" if alignment.get("decision") == "aligned" else "review",
            "detail": alignment.get("decision", "missing"),
        }
    )
    checks.append(
        {
            "name": "failure_diagnosis",
            "status": (
                "fail"
                if diagnosis.get("error_count", 0) > 0
                else "review"
                if diagnosis.get("warning_count", 0) > 0
                else "pass"
            ),
            "detail": f"{diagnosis.get('status', 'not_run')} "
            f"(errors={diagnosis.get('error_count', 0)}, warnings={diagnosis.get('warning_count', 0)})",
        }
    )
    checks.append(
        {
            "name": "quality_gate",
            "status": "pass" if quality_gate.get("status") == "pass" else "review",
            "detail": quality_gate.get("status", "not_run"),
        }
    )

    if not data_dumps:
        checks.append({"name": "data_dump_pin", "status": "fail", "detail": "no data dump pinned"})
    else:
        for dump in data_dumps:
            status = "pass" if dump.get("kpi_ready") and dump.get("matched_current_execution") else "review"
            checks.append(
                {
                    "name": f"data_dump:{dump.get('test_scenario', dump.get('dump_title', '-'))}",
                    "status": status,
                    "detail": f"frames={dump.get('total_actor_frames', '-')}, path={dump.get('path', '-')}",
                }
            )

    artifact_hashes = _hash_artifacts(
        [
            str(run_dir / "run_manifest.json"),
            manifest.get("scenario_definition"),
            artifacts.get("scenario_definition_form_csv"),
            artifacts.get("execution_plan"),
            artifacts.get("execution_result"),
            artifacts.get("scenario_alignment_review"),
            artifacts.get("failure_diagnosis"),
            artifacts.get("quality_gate"),
        ]
    )
    stability_patches = _collect_stability_patches(run_dir)

    status = _status_from_checks(checks)
    recommendation = {
        "research_ready": "제출 가능. 단, 최종 책임자는 생성 산출물과 평가 의도를 승인해야 합니다.",
        "research_review_required": "연구자 검토 후 제출 가능. 경고/충돌/시나리오 의도 일치 여부를 HITL에서 승인해야 합니다.",
        "research_blocked": "제출 보류. 실행 실패, KPI 누락, data dump 누락 등 차단 이슈를 먼저 해결해야 합니다.",
    }[status]

    readiness = {
        "agent": "ResearchReadinessAgent",
        "run_id": run_id,
        "status": status,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "recommendation": recommendation,
        "checks": checks,
        "summary": {
            "pass": sum(1 for check in checks if check["status"] == "pass"),
            "review": sum(1 for check in checks if check["status"] == "review"),
            "fail": sum(1 for check in checks if check["status"] == "fail"),
        },
        "artifact_hashes": artifact_hashes,
        "stability_patches": stability_patches,
    }

    readiness_path = run_dir / "research_readiness.json"
    summary_path = run_dir / "report" / "research_submission_summary_ko.md"
    write_json(readiness_path, readiness)
    write_text(
        summary_path,
        _build_submission_summary(
            run_id=run_id,
            manifest=manifest,
            readiness=readiness,
            artifact_hashes=artifact_hashes,
            stability_patches=stability_patches,
        ),
    )

    artifacts["research_readiness"] = str(readiness_path)
    artifacts["research_submission_summary"] = str(summary_path)
    manifest["artifacts"] = artifacts
    manifest["research_readiness"] = {
        "status": status,
        "summary": readiness["summary"],
        "recommendation": recommendation,
        "checks": checks,
    }
    save_run_manifest(project_root, run_id, manifest)

    append_event(
        project_root,
        run_id,
        "research_readiness_agent_finished",
        status=status,
        payload=readiness["summary"],
    )
    upsert_run_record(
        project_root,
        run_id,
        {
            "research_readiness": status,
            "research_review_count": readiness["summary"]["review"],
            "research_fail_count": readiness["summary"]["fail"],
        },
    )
    return readiness
