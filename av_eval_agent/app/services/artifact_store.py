from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable


def _json_default(value: Any) -> str:
    return str(value)


def run_dir_for(project_root: Path, run_id: str) -> Path:
    return project_root / "av_eval_agent" / "data" / "runs" / run_id


def manifest_path_for(project_root: Path, run_id: str) -> Path:
    return run_dir_for(project_root, run_id) / "run_manifest.json"


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    human_readable_suffixes = {".md", ".csv"}
    encoding = "utf-8-sig" if path.suffix.lower() in human_readable_suffixes else "utf-8"
    path.write_text(text, encoding=encoding)


def write_definition_form_csv(path: Path, definition_form: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = definition_form.get("table_columns") or ["레이어", "항목", "요소", "설명", "시험 시나리오"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for row in definition_form.get("rows", []):
            writer.writerow({column: row.get(column, "") for column in columns})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_source(project_root: Path, source_text: str) -> Path:
    source = Path(source_text)
    if source.is_absolute():
        return source
    return project_root / source


def copy_template_files(project_root: Path, template_files: Iterable[str], run_dir: Path) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    generated_dir = run_dir / "generated_files"
    generated_dir.mkdir(parents=True, exist_ok=True)

    for source_text in template_files:
        source = _resolve_source(project_root, source_text)
        record: dict[str, Any] = {
            "source": str(source),
            "exists": source.exists(),
        }
        if source.exists() and source.is_file():
            target = generated_dir / source.name
            shutil.copy2(source, target)
            record.update({"copied_to": str(target), "sha256": sha256_file(target)})
        copied.append(record)

    return copied


def _format_warning_lines(items: list[str]) -> list[str]:
    if not items:
        return ["- 없음"]
    return [f"- {item}" for item in items]


def build_report_markdown(state: Dict[str, Any], copied_files: list[dict[str, Any]]) -> str:
    scenario = state.get("scenario_definition", {})
    definition_form = scenario.get("definition_form", {})
    intent = state.get("intent", {})
    warnings = state.get("validation_warnings", [])
    errors = state.get("validation_errors", [])

    lines = [
        "# AV Evaluation Agent 실행 계획 보고서",
        "",
        "## 1. 요청 요약",
        "",
        f"- 사용자 요청: {state.get('user_request', '')}",
        f"- 감지된 시나리오: {scenario.get('scenario_id', 'unknown')}",
        f"- 시나리오 유형: {scenario.get('scenario_type', 'unknown')}",
        f"- 현재 상태: {state.get('status', 'unknown')}",
        "",
        "## 2. 정의서 형식",
        "",
        f"- 형식: {scenario.get('definition_format', 'unknown')}",
        f"- 기준 PDF: {definition_form.get('source_pdf', '-')}",
        "- 표 컬럼: 레이어 / 항목 / 요소 / 설명 / 시험 시나리오",
        "- 모든 시나리오는 같은 정의서 표 구조를 사용하고, `시험 시나리오` 값만 시나리오별로 채웁니다.",
        "",
        "## 3. Agent 판단 결과",
        "",
        f"- 실험 실행 요청 감지: {intent.get('requested_actions', {}).get('run_simulation', False)}",
        f"- KPI 계산 요청 감지: {intent.get('requested_actions', {}).get('calculate_kpis', False)}",
        f"- 보고서 생성 요청 감지: {intent.get('requested_actions', {}).get('generate_report', False)}",
        "",
        "## 4. 검증 결과",
        "",
        "### 오류",
        "",
        *_format_warning_lines(errors),
        "",
        "### 경고",
        "",
        *_format_warning_lines(warnings),
        "",
        "## 5. 복사된 OpenCDA 템플릿 파일",
        "",
        "| 원본 | 존재 여부 | 복사본 |",
        "| --- | --- | --- |",
    ]

    for item in copied_files:
        lines.append(f"| `{item.get('source')}` | {item.get('exists')} | `{item.get('copied_to', '-')}` |")

    lines.extend(
        [
            "",
            "## 6. 다음 단계",
            "",
            "- `POST /run/prepare/{run_id}`: OpenCDA 실행 명령과 공통 KPI 계산 명령을 `execution_plan.json`에 저장합니다.",
            "- `POST /run/execute/{run_id}`: 승인된 경우 실제 OpenCDA/CARLA 실험 또는 KPI 계산을 수행합니다.",
            "- 원본 OpenCDA 파일은 직접 수정하지 않고, run별 복사본과 manifest 기준으로 추적합니다.",
        ]
    )
    return "\n".join(lines) + "\n"


def persist_agent_run(state: Dict[str, Any], project_root: Path) -> Dict[str, Any]:
    run_id = state["run_id"]
    run_dir = run_dir_for(project_root, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    copied_files = copy_template_files(project_root, state.get("experiment_plan", {}).get("template_files", []), run_dir)
    scenario_definition = state.get("scenario_definition", {})
    definition_form = scenario_definition.get("definition_form")

    scenario_path = run_dir / "scenario_definition.json"
    form_json_path = run_dir / "scenario_definition_form.json"
    form_csv_path = run_dir / "scenario_definition_form.csv"
    manifest_path = run_dir / "run_manifest.json"
    agent_state_path = run_dir / "agent_state.json"
    experiment_plan_path = run_dir / "experiment_plan.json"
    kpi_plan_path = run_dir / "kpi_plan.json"
    report_path = run_dir / "report" / "evaluation_agent_plan.md"

    write_json(scenario_path, scenario_definition)
    if definition_form:
        write_json(form_json_path, definition_form)
        write_definition_form_csv(form_csv_path, definition_form)
    write_json(experiment_plan_path, state.get("experiment_plan", {}))
    write_json(kpi_plan_path, state.get("kpi_plan", {}))
    write_json(agent_state_path, state)

    artifacts = {
        "agent_state": str(agent_state_path),
        "experiment_plan": str(experiment_plan_path),
        "kpi_plan": str(kpi_plan_path),
        "report": str(report_path),
    }
    if definition_form:
        artifacts["scenario_definition_form"] = str(form_json_path)
        artifacts["scenario_definition_form_csv"] = str(form_csv_path)

    manifest = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": state.get("status"),
        "scenario_id": scenario_definition.get("scenario_id"),
        "definition_format": scenario_definition.get("definition_format"),
        "scenario_definition": str(scenario_path),
        "generated_files": copied_files,
        "commands": [],
        "artifacts": artifacts,
        "approval": {
            "required": state.get("approval_required", False),
            "reason": state.get("approval_reason", ""),
        },
    }
    write_json(manifest_path, manifest)
    write_text(report_path, build_report_markdown(state, copied_files))

    return {
        "run_dir": str(run_dir),
        "manifest": str(manifest_path),
        "report": str(report_path),
        "scenario_definition_form": str(form_json_path) if definition_form else None,
        "scenario_definition_form_csv": str(form_csv_path) if definition_form else None,
        "copied_files": copied_files,
    }


def read_run_manifest(project_root: Path, run_id: str) -> Dict[str, Any] | None:
    manifest = manifest_path_for(project_root, run_id)
    if not manifest.exists():
        return None
    return json.loads(manifest.read_text(encoding="utf-8"))


def save_run_manifest(project_root: Path, run_id: str, manifest: Dict[str, Any]) -> Path:
    manifest_path = manifest_path_for(project_root, run_id)
    write_json(manifest_path, manifest)
    return manifest_path


def update_run_manifest(project_root: Path, run_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    manifest = read_run_manifest(project_root, run_id)
    if manifest is None:
        raise FileNotFoundError(f"run manifest를 찾을 수 없습니다: {run_id}")
    manifest.update(updates)
    save_run_manifest(project_root, run_id, manifest)
    return manifest


def list_run_manifests(project_root: Path) -> list[Dict[str, Any]]:
    runs_dir = project_root / "av_eval_agent" / "data" / "runs"
    if not runs_dir.exists():
        return []
    manifests: list[Dict[str, Any]] = []
    for manifest in sorted(runs_dir.glob("*/run_manifest.json"), reverse=True):
        try:
            manifests.append(json.loads(manifest.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return manifests
