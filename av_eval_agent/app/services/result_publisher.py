from __future__ import annotations

from pathlib import Path
from typing import Any


def _run_dir(project_root: Path, run_id: str) -> Path:
    return project_root / "av_eval_agent" / "data" / "runs" / run_id


def _artifact_link(path: str | None) -> str:
    if not path:
        return "-"
    return f"`{path}`"


def build_final_report_markdown(manifest: dict[str, Any]) -> str:
    run_id = manifest.get("run_id", "unknown")
    artifacts = manifest.get("artifacts") or {}
    alignment = manifest.get("scenario_alignment") or {}
    execution = manifest.get("execution_results") or {}
    opencda = execution.get("opencda") or {}
    kpi = execution.get("kpi") or {}
    data_dumps = opencda.get("data_dumps") or artifacts.get("data_dumps") or []

    lines = [
        f"# 자율주행 평가 Agent 실행 결과: {run_id}",
        "",
        "## 1. 실행 상태",
        "",
        f"- 최종 상태: `{manifest.get('status', 'unknown')}`",
        f"- 시나리오 ID: `{manifest.get('scenario_id', 'unknown')}`",
        f"- OpenCDA 실행 상태: `{opencda.get('status', '-')}`",
        f"- KPI 계산 상태: `{kpi.get('status', '-')}`",
        f"- 목적 적합성 판단: `{alignment.get('decision', '-')}`",
        "",
        "## 2. 생성 산출물",
        "",
        f"- 시나리오 정의서 JSON: {_artifact_link(manifest.get('scenario_definition'))}",
        f"- 실행 계획: {_artifact_link(artifacts.get('execution_plan'))}",
        f"- 실행 결과 JSON: {_artifact_link(artifacts.get('execution_result'))}",
        f"- 목적 적합성 검토: {_artifact_link(artifacts.get('scenario_alignment_review'))}",
        f"- KPI 폴더: {_artifact_link(((kpi.get('results') or [{}])[0]).get('output_dir') if kpi.get('results') else None)}",
        "",
        "## 3. 최신 데이터 로그 고정 결과",
        "",
        "| 조건 | dump title | run folder | completeness | KPI ready |",
        "| --- | --- | --- | --- | --- |",
    ]
    if data_dumps:
        for item in data_dumps:
            lines.append(
                "| "
                f"{item.get('test_scenario', '-')} | "
                f"{item.get('dump_title', '-')} | "
                f"`{item.get('path', '-')}` | "
                f"{item.get('completeness', '-')} | "
                f"{item.get('kpi_ready', '-')} |"
            )
    else:
        lines.append("| - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## 4. 검토 필요 사항",
            "",
        ]
    )
    issues = alignment.get("issues") or []
    if issues:
        for issue in issues:
            lines.append(f"- [{issue.get('severity', 'info')}] {issue.get('message', '')}")
    else:
        lines.append("- 없음")

    questions = (alignment.get("human_in_the_loop") or {}).get("questions") or []
    if questions:
        lines.extend(["", "## 5. Human-in-the-loop 질문", ""])
        for question in questions:
            lines.append(f"- {question}")

    return "\n".join(lines) + "\n"


def build_final_dashboard_html(manifest: dict[str, Any]) -> str:
    run_id = manifest.get("run_id", "unknown")
    artifacts = manifest.get("artifacts") or {}
    alignment = manifest.get("scenario_alignment") or {}
    execution = manifest.get("execution_results") or {}
    opencda = execution.get("opencda") or {}
    kpi = execution.get("kpi") or {}
    data_dumps = opencda.get("data_dumps") or artifacts.get("data_dumps") or []

    dump_rows = "\n".join(
        "<tr>"
        f"<td>{item.get('test_scenario', '-')}</td>"
        f"<td>{item.get('dump_title', '-')}</td>"
        f"<td>{item.get('name', '-')}</td>"
        f"<td>{item.get('completeness', '-')}</td>"
        f"<td>{item.get('kpi_ready', '-')}</td>"
        "</tr>"
        for item in data_dumps
    ) or "<tr><td colspan='5'>No pinned data dump</td></tr>"

    issues = alignment.get("issues") or []
    issue_items = "\n".join(
        f"<li><b>{issue.get('severity', 'info')}</b> {issue.get('message', '')}</li>"
        for issue in issues
    ) or "<li>No review issue</li>"

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AV Evaluation Run {run_id}</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #eef3f8; color: #182234; }}
    header {{ background: #76001f; color: white; padding: 22px 32px; }}
    main {{ padding: 24px 32px; display: grid; gap: 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }}
    .card {{ background: white; border: 1px solid #d9e0e8; border-radius: 8px; padding: 16px; box-shadow: 0 6px 18px rgba(18,34,52,.08); }}
    .value {{ font-size: 24px; font-weight: 700; margin-top: 8px; }}
    table {{ border-collapse: collapse; width: 100%; background: white; }}
    th, td {{ border: 1px solid #d9e0e8; padding: 10px; text-align: left; font-size: 14px; }}
    th {{ background: #f6f8fb; }}
    code {{ background: #eef2f7; padding: 2px 5px; border-radius: 4px; }}
  </style>
</head>
<body>
  <header>
    <h1>AV Evaluation Agent Run</h1>
    <p>{run_id}</p>
  </header>
  <main>
    <section class="grid">
      <div class="card"><b>Scenario</b><div class="value">{manifest.get('scenario_id', '-')}</div></div>
      <div class="card"><b>Run Status</b><div class="value">{manifest.get('status', '-')}</div></div>
      <div class="card"><b>OpenCDA</b><div class="value">{opencda.get('status', '-')}</div></div>
      <div class="card"><b>KPI</b><div class="value">{kpi.get('status', '-')}</div></div>
    </section>
    <section class="card">
      <h2>Latest Data Dumps</h2>
      <table>
        <thead><tr><th>Condition</th><th>Dump title</th><th>Run folder</th><th>Completeness</th><th>KPI ready</th></tr></thead>
        <tbody>{dump_rows}</tbody>
      </table>
    </section>
    <section class="card">
      <h2>Scenario Alignment Review</h2>
      <p><b>Decision:</b> {alignment.get('decision', '-')}</p>
      <ul>{issue_items}</ul>
    </section>
    <section class="card">
      <h2>Artifacts</h2>
      <p><b>Execution result:</b> <code>{artifacts.get('execution_result', '-')}</code></p>
      <p><b>Final report:</b> <code>{artifacts.get('final_report', '-')}</code></p>
    </section>
  </main>
</body>
</html>
"""


def publish_run_outputs(project_root: Path, run_id: str, manifest: dict[str, Any]) -> dict[str, str]:
    run_dir = _run_dir(project_root, run_id)
    report_path = run_dir / "report" / "final_run_report.md"
    dashboard_path = run_dir / "dashboard" / "final_index.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_final_report_markdown(manifest), encoding="utf-8")
    dashboard_path.write_text(build_final_dashboard_html(manifest), encoding="utf-8")
    return {
        "final_report": str(report_path),
        "final_dashboard": str(dashboard_path),
    }
