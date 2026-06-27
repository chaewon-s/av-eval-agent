from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


AGENT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = AGENT_ROOT.parent
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from app.services.artifact_store import list_run_manifests, read_run_manifest  # noqa: E402
from app.services.doc_index import search_documents  # noqa: E402
from app.services.experiment_history import list_run_records, read_events  # noqa: E402


SERVER_NAME = "av-eval-agent-mcp"
SERVER_VERSION = "0.1.0"


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _text_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _safe_slug(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", text.strip()).strip("-").lower()
    return slug[:80] or "agent-task"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def tool_search_docs(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    limit = int(arguments.get("limit", 8))
    roots = arguments.get("roots")
    if isinstance(roots, str):
        roots = [roots]
    results = search_documents(PROJECT_ROOT, query, limit=limit, roots=roots)
    return _text_result(_json({"query": query, "results": results}))


def tool_create_agent_task(arguments: dict[str, Any]) -> dict[str, Any]:
    title = str(arguments.get("title", "")).strip()
    if not title:
        raise ValueError("title is required")
    body = str(arguments.get("body", "")).strip()
    labels = arguments.get("labels") or ["agent-design"]
    if isinstance(labels, str):
        labels = [labels]
    acceptance_criteria = arguments.get("acceptance_criteria") or []
    if isinstance(acceptance_criteria, str):
        acceptance_criteria = [acceptance_criteria]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = AGENT_ROOT / "data" / "issue_drafts" / f"{timestamp}_{_safe_slug(title)}.md"
    criteria_text = "\n".join(f"- [ ] {item}" for item in acceptance_criteria) or "- [ ] 구현 범위와 검증 방법을 명시한다."
    labels_text = ", ".join(labels)
    issue_body = f"""# {title}

## 배경

{body or "Codex Agent workflow에서 생성된 작업 초안입니다."}

## 작업 범위

- 요구사항/문서 근거 확인
- 코드 또는 설정 변경
- eval 또는 dry-run 검증
- 결과 문서화

## 완료 기준

{criteria_text}

## Labels

{labels_text}
"""
    _write_text(path, issue_body)
    return _text_result(_json({"title": title, "labels": labels, "draft_path": str(path), "body": issue_body}))


def tool_run_agent_eval(arguments: dict[str, Any]) -> dict[str, Any]:
    cases = arguments.get("cases")
    fail_on_fail = bool(arguments.get("fail_on_fail", False))
    report_path = AGENT_ROOT / "data" / "eval_reports" / "mcp_agent_eval_report.json"
    command = [
        sys.executable,
        str(AGENT_ROOT / "evals" / "run_agent_evals.py"),
        "--json",
        "--report",
        str(report_path),
    ]
    if cases:
        command.extend(["--cases", str(cases)])
    if fail_on_fail:
        command.append("--fail-on-fail")

    env = os.environ.copy()
    site_packages = AGENT_ROOT / ".venv" / "Lib" / "site-packages"
    if site_packages.exists():
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = f"{site_packages};{existing}" if existing else str(site_packages)

    process = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    payload = {
        "returncode": process.returncode,
        "report_path": str(report_path),
        "stdout": process.stdout,
        "stderr": process.stderr,
    }
    return _text_result(_json(payload))


def tool_query_logs(arguments: dict[str, Any]) -> dict[str, Any]:
    run_id = arguments.get("run_id")
    limit = int(arguments.get("limit", 50))
    payload: dict[str, Any] = {
        "run_id": run_id,
        "events": read_events(PROJECT_ROOT, run_id=run_id, limit=limit),
    }
    if run_id:
        payload["manifest"] = read_run_manifest(PROJECT_ROOT, str(run_id))
    else:
        payload["runs"] = list_run_records(PROJECT_ROOT, limit=limit)
    return _text_result(_json(payload))


def tool_get_scenario(arguments: dict[str, Any]) -> dict[str, Any]:
    run_id = arguments.get("run_id")
    scenario_id = arguments.get("scenario_id")
    if run_id:
        manifest = read_run_manifest(PROJECT_ROOT, str(run_id))
        if not manifest:
            return _text_result(_json({"status": "not_found", "run_id": run_id}))
        scenario_path = manifest.get("scenario_definition")
        scenario = None
        if scenario_path and Path(scenario_path).exists():
            scenario = json.loads(Path(scenario_path).read_text(encoding="utf-8"))
        return _text_result(_json({"run_id": run_id, "manifest": manifest, "scenario": scenario}))

    manifests = list_run_manifests(PROJECT_ROOT)
    if scenario_id:
        manifests = [manifest for manifest in manifests if manifest.get("scenario_id") == scenario_id]
    return _text_result(_json({"scenario_id": scenario_id, "runs": manifests[:10]}))


def tool_save_design_decision(arguments: dict[str, Any]) -> dict[str, Any]:
    title = str(arguments.get("title", "")).strip()
    decision = str(arguments.get("decision", "")).strip()
    if not title or not decision:
        raise ValueError("title and decision are required")
    context = str(arguments.get("context", "")).strip()
    consequences = arguments.get("consequences") or []
    if isinstance(consequences, str):
        consequences = [consequences]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = AGENT_ROOT / "docs" / "design_decisions" / f"{timestamp}_{_safe_slug(title)}.md"
    consequence_text = "\n".join(f"- {item}" for item in consequences) or "- 후속 구현과 eval에서 이 결정을 기준으로 삼는다."
    text = f"""# {title}

## Context

{context or "No additional context recorded."}

## Decision

{decision}

## Consequences

{consequence_text}
"""
    _write_text(path, text)
    return _text_result(_json({"path": str(path), "title": title}))


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


TOOL_HANDLERS: dict[str, ToolHandler] = {
    "search_docs": tool_search_docs,
    "create_agent_task": tool_create_agent_task,
    "run_agent_eval": tool_run_agent_eval,
    "query_logs": tool_query_logs,
    "get_scenario": tool_get_scenario,
    "save_design_decision": tool_save_design_decision,
}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_docs",
        "description": "Search AV Evaluation Agent and OpenCDA documentation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
                "roots": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_agent_task",
        "description": "Create a GitHub issue draft for an Agent design or implementation task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title"],
        },
    },
    {
        "name": "run_agent_eval",
        "description": "Run deterministic natural-language routing evals for the AV Evaluation Agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cases": {"type": "string"},
                "fail_on_fail": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "query_logs",
        "description": "Read run history, event logs, and optional run manifest data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "get_scenario",
        "description": "Fetch a scenario definition by run_id or recent manifests by scenario_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "scenario_id": {"type": "string"},
            },
        },
    },
    {
        "name": "save_design_decision",
        "description": "Save an architecture/design decision note into av_eval_agent docs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "context": {"type": "string"},
                "decision": {"type": "string"},
                "consequences": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "decision"],
        },
    },
]


def _response(message_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    message_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if method == "initialize":
        return _response(
            message_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "tools/list":
        return _response(message_id, {"tools": TOOLS})
    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if tool_name not in TOOL_HANDLERS:
            return _error(message_id, -32602, f"Unknown tool: {tool_name}")
        try:
            return _response(message_id, TOOL_HANDLERS[str(tool_name)](arguments))
        except Exception as exc:  # Keep MCP server alive and surface the tool error.
            return _error(message_id, -32000, str(exc))
    if isinstance(method, str) and method.startswith("notifications/"):
        return None
    return _error(message_id, -32601, f"Unknown method: {method}")


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = handle_message(message)
        except Exception as exc:
            response = _error(None, -32700, str(exc))
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
