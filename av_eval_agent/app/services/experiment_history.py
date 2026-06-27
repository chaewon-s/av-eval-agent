from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _db_dir(project_root: Path) -> Path:
    path = project_root / "av_eval_agent" / "data" / "experiment_db"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _json_default(value: Any) -> str:
    return str(value)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def append_event(
    project_root: Path,
    run_id: str,
    event_type: str,
    *,
    status: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "run_id": run_id,
        "event_type": event_type,
        "status": status,
        "payload": payload or {},
    }
    event_path = _db_dir(project_root) / "events.jsonl"
    with event_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False, default=_json_default) + "\n")
    return event


def upsert_run_record(project_root: Path, run_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    index_path = _db_dir(project_root) / "runs_index.json"
    index = _read_json(index_path, {})
    now = datetime.now().isoformat(timespec="seconds")
    record = index.get(run_id, {"run_id": run_id, "created_at": now})
    record.update(updates)
    record["updated_at"] = now
    index[run_id] = record
    _write_json(index_path, index)
    return record


def get_run_record(project_root: Path, run_id: str) -> dict[str, Any] | None:
    return _read_json(_db_dir(project_root) / "runs_index.json", {}).get(run_id)


def list_run_records(project_root: Path, limit: int = 50) -> list[dict[str, Any]]:
    index = _read_json(_db_dir(project_root) / "runs_index.json", {})
    records = list(index.values())
    records.sort(key=lambda item: item.get("updated_at", item.get("created_at", "")), reverse=True)
    return records[:limit]


def read_events(project_root: Path, run_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    event_path = _db_dir(project_root) / "events.jsonl"
    if not event_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in event_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if run_id and event.get("run_id") != run_id:
            continue
        events.append(event)
    return events[-limit:]
