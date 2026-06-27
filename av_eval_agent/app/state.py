from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class AgentState(TypedDict, total=False):
    run_id: str
    user_request: str
    intent: Dict[str, Any]
    scenario_definition: Dict[str, Any]
    validation_errors: List[str]
    validation_warnings: List[str]
    experiment_plan: Dict[str, Any]
    kpi_plan: Dict[str, Any]
    approval_required: bool
    approval_reason: str
    status: str
    artifacts: Dict[str, Any]
    next_actions: List[str]
