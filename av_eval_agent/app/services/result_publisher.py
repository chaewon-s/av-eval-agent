from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any


def _run_dir(project_root: Path, run_id: str) -> Path:
    return project_root / "av_eval_agent" / "data" / "runs" / run_id


def _artifact_link(path: str | None) -> str:
    if not path:
        return "-"
    return f"`{path}`"


def _status_badge(status: str | None) -> str:
    value = status or "-"
    if value in {"pass", "completed", "ok", "clean", "report_generated", "research_ready"}:
        return f"<span class='badge pass'>{escape(value)}</span>"
    if value in {
        "human_review_required",
        "review",
        "completed_with_warnings",
        "execution_finished_needs_review",
        "research_review_required",
    }:
        return f"<span class='badge review'>{escape(value)}</span>"
    if value in {"failed", "fail", "failed_needs_recovery", "research_blocked"}:
        return f"<span class='badge fail'>{escape(value)}</span>"
    return f"<span class='badge neutral'>{escape(value)}</span>"


def _quality_gate_rows(quality_gate: dict[str, Any]) -> str:
    gates = quality_gate.get("gates") or []
    if not gates:
        return "<tr><td colspan='3'>QualityGateAgent 결과가 없습니다.</td></tr>"
    rows = []
    for gate in gates:
        rows.append(
            "<tr>"
            f"<td>{escape(str(gate.get('name', '-')))}</td>"
            f"<td>{_status_badge(str(gate.get('status', '-')))}</td>"
            f"<td>{escape(str(gate.get('detail', '-')))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _research_readiness_rows(readiness: dict[str, Any]) -> str:
    checks = readiness.get("checks") or []
    if not checks:
        return "<tr><td colspan='3'>ResearchReadinessAgent 결과가 없습니다.</td></tr>"
    rows = []
    for check in checks:
        rows.append(
            "<tr>"
            f"<td>{escape(str(check.get('name', '-')))}</td>"
            f"<td>{_status_badge(str(check.get('status', '-')))}</td>"
            f"<td>{escape(str(check.get('detail', '-')))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _data_dump_table_rows(data_dumps: list[dict[str, Any]]) -> list[str]:
    if not data_dumps:
        return ["| - | - | - | - | - | - |"]
    rows = []
    for item in data_dumps:
        rows.append(
            "| "
            f"{item.get('test_scenario', '-')} | "
            f"{item.get('dump_title', '-')} | "
            f"`{item.get('path', '-')}` | "
            f"{item.get('total_actor_frames', '-')} | "
            f"{item.get('completeness', '-')} | "
            f"{item.get('kpi_ready', '-')} |"
        )
    return rows


def build_final_report_markdown(manifest: dict[str, Any]) -> str:
    run_id = manifest.get("run_id", "unknown")
    artifacts = manifest.get("artifacts") or {}
    alignment = manifest.get("scenario_alignment") or {}
    execution = manifest.get("execution_results") or {}
    opencda = execution.get("opencda") or {}
    kpi = execution.get("kpi") or {}
    data_dumps = opencda.get("data_dumps") or artifacts.get("data_dumps") or []
    diagnosis = manifest.get("failure_diagnosis") or {}
    quality_gate = manifest.get("quality_gate") or {}
    research_readiness = manifest.get("research_readiness") or {}
    autotune = manifest.get("autotune") or {}
    autotune_decision = autotune.get("decision") or {}

    lines = [
        f"# 자율주행 평가 Agent 실행 결과: {run_id}",
        "",
        "## 1. 실행 상태 요약",
        "",
        f"- 최종 상태: `{manifest.get('status', 'unknown')}`",
        f"- 시나리오 ID: `{manifest.get('scenario_id', 'unknown')}`",
        f"- OpenCDA 실행 상태: `{opencda.get('status', '-')}`",
        f"- KPI 계산 상태: `{kpi.get('status', '-')}`",
        f"- 시나리오 적합성 판단: `{alignment.get('decision', '-')}`",
        f"- 실패 진단 상태: `{diagnosis.get('status', '-')}`",
        f"- 품질 게이트 상태: `{quality_gate.get('status', '-')}`",
        f"- 연구 제출 준비도: `{research_readiness.get('status', '-')}`",
        f"- AutoTune 판단: `{autotune_decision.get('decision', '-')}`",
        "",
        "## 2. 산출물",
        "",
        f"- 시나리오 정의서 JSON: {_artifact_link(manifest.get('scenario_definition'))}",
        f"- 정의서 표 CSV: {_artifact_link(artifacts.get('scenario_definition_form_csv'))}",
        f"- 실행 계획 JSON: {_artifact_link(artifacts.get('execution_plan'))}",
        f"- 실행 결과 JSON: {_artifact_link(artifacts.get('execution_result'))}",
        f"- 시나리오 적합성 검토 JSON: {_artifact_link(artifacts.get('scenario_alignment_review'))}",
        f"- 실패 진단 JSON: {_artifact_link(artifacts.get('failure_diagnosis'))}",
        f"- 품질 게이트 JSON: {_artifact_link(artifacts.get('quality_gate'))}",
        f"- 연구 준비도 JSON: {_artifact_link(artifacts.get('research_readiness'))}",
        f"- 연구 제출 요약 MD: {_artifact_link(artifacts.get('research_submission_summary'))}",
        f"- AutoTune 판단 JSON: {_artifact_link(artifacts.get('autotune_decision'))}",
        f"- KPI 결과 폴더: {_artifact_link(((kpi.get('results') or [{}])[0]).get('output_dir') if kpi.get('results') else None)}",
        "",
        "## 3. 고정된 데이터 로그",
        "",
        "| 조건 | dump title | run folder | frame count | completeness | KPI ready |",
        "| --- | --- | --- | ---: | --- | --- |",
        *_data_dump_table_rows(data_dumps),
        "",
        "## 4. 품질 게이트",
        "",
        "| 게이트 | 상태 | 상세 |",
        "| --- | --- | --- |",
    ]

    gates = quality_gate.get("gates") or []
    if gates:
        for gate in gates:
            lines.append(f"| {gate.get('name', '-')} | {gate.get('status', '-')} | {gate.get('detail', '-')} |")
    else:
        lines.append("| - | - | - |")

    lines.extend(
        [
            "",
            "## 5. 연구 제출 준비도",
            "",
            f"- 판정: `{research_readiness.get('status', '-')}`",
            f"- 권고: `{research_readiness.get('recommendation', '-')}`",
            "",
            "| 점검 항목 | 상태 | 상세 |",
            "| --- | --- | --- |",
        ]
    )
    checks = research_readiness.get("checks") or []
    if checks:
        for check in checks:
            lines.append(f"| {check.get('name', '-')} | {check.get('status', '-')} | {check.get('detail', '-')} |")
    else:
        lines.append("| - | - | - |")

    lines.extend(
        [
            "",
            "## 6. 실패 진단",
            "",
            f"- error count: `{diagnosis.get('error_count', 0)}`",
            f"- warning count: `{diagnosis.get('warning_count', 0)}`",
        ]
    )
    diagnosis_path = artifacts.get("failure_diagnosis")
    if diagnosis_path:
        lines.append(f"- 상세 진단 파일: `{diagnosis_path}`")

    issues = alignment.get("issues") or []
    if issues:
        lines.extend(["", "### 시나리오 적합성 이슈"])
        for issue in issues:
            lines.append(f"- [{issue.get('severity', 'info')}] {issue.get('message', '')}")
    else:
        lines.append("- 시나리오 적합성 이슈 없음")

    questions = (alignment.get("human_in_the_loop") or {}).get("questions") or []
    if questions:
        lines.extend(["", "## 7. Human-in-the-loop 질문", ""])
        for question in questions:
            lines.append(f"- {question}")

    lines.extend(
        [
            "",
            "## 8. 다음 액션",
            "",
            "- 연구 제출 전에는 `ResearchReadinessAgent` 결과가 `research_ready` 또는 명확한 검토 사유가 있는 `research_review_required`인지 확인합니다.",
            "- 경고가 남은 경우에는 Slack/HITL에서 연구자가 `approve`, `revise`, `rerun_simulation`, `reject` 중 하나를 선택하도록 합니다.",
            "- canonical OpenCDA 파일은 직접 수정하지 않고 run-local generated YAML/PY와 manifest 기준으로 추적합니다.",
            "- n8n workflow는 PreflightAgent -> ScenarioSpecAgent -> Validation -> Build -> SimulationRun -> KPI -> FailureDiagnosis -> QualityGate -> ResearchReadiness -> Report -> Memory/AutoTune/HITL 순서로 동작합니다.",
        ]
    )
    return "\n".join(lines) + "\n"


def publish_run_outputs(project_root: Path, run_id: str, manifest: dict[str, Any]) -> dict[str, str]:
    run_dir = _run_dir(project_root, run_id)
    report_path = run_dir / "report" / "final_run_report.md"
    artifacts = manifest.setdefault("artifacts", {})
    artifacts.pop("dashboard", None)
    artifacts.pop("final_dashboard", None)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_final_report_markdown(manifest), encoding="utf-8-sig")
    return {
        "final_report": str(report_path),
    }
