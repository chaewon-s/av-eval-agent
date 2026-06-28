from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from langgraph.graph import END, StateGraph

from app.services.scenario_definition_autofill import collect_definition_autofill_values
from app.services.scenario_spec_gpt import generate_gpt_definition_autofill
from app.services.scenario_definition_template import build_scenario_definition_form
from app.state import AgentState


DEFAULT_KPIS = [
    "MOTA",
    "MOTP",
    "ProgressAdjustedDelay",
    "FlowEfficiency",
    "Min2DTTC",
    "PET",
    "RequiredDeceleration",
    "AccelerationVarianceMax",
    "YawRateResidualRMS",
]


def _detect_scenario_type(text: str) -> str:
    lowered = text.lower()
    if any(
        keyword in lowered or keyword in text
        for keyword in [
            "시나리오2",
            "시나리오 2",
            "scenario 2",
            "scenario2",
            "차선변경",
            "차로변경",
            "차선 변경",
            "차로 변경",
            "고속",
            "2차로",
            "cut",
            "cut-out",
            "cut out",
            "highway",
            "overtake",
        ]
    ):
        return "highway_cutout"

    if any(
        keyword in lowered or keyword in text
        for keyword in [
            "시나리오1",
            "시나리오 1",
            "scenario 1",
            "scenario1",
            "교차로",
            "정지선",
            "좌측",
            "비신호",
            "occlusion",
            "시야",
            "음영",
        ]
    ):
        return "intersection_occlusion"

    return "custom"


def _extract_speed_hint(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:km/h|kmh|kph|km)", text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _extract_comm_range_hint(text: str) -> float | None:
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*m", text, re.IGNORECASE):
        context = text[max(0, match.start() - 30) : match.end() + 30]
        if any(keyword in context for keyword in ["통신", "V2X", "v2x", "반경", "범위"]):
            return float(match.group(1))
    return None


def _extract_lane_count_hint(text: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:차로|lane|lanes)", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _extract_lidar_range_hint(text: str) -> float | None:
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*m", text, re.IGNORECASE):
        context = text[max(0, match.start() - 35) : match.end() + 35]
        if any(keyword in context.lower() for keyword in ["lidar", "라이다", "센서", "탐지"]):
            return float(match.group(1))
    return None


def _extract_lidar_channels_hint(text: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:채널|channel|channels)", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _extract_sensor_frequency_hint(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hz|Hz|헤르츠)", text)
    return float(match.group(1)) if match else None


def _extract_weather_hint(text: str) -> str | None:
    if any(keyword in text for keyword in ["눈", "snow"]):
        return "눈"
    if any(keyword in text for keyword in ["안개", "fog"]):
        return "안개"
    if any(keyword in text for keyword in ["우천", "rain", "비 오는", "비가", "비 내리는"]):
        return "비"
    if any(keyword in text for keyword in ["맑음", "clear"]):
        return "맑음"
    return None


def _extract_day_night_hint(text: str) -> str | None:
    if any(keyword in text for keyword in ["야간", "밤", "night"]):
        return "야간"
    if any(keyword in text for keyword in ["주간", "낮", "day"]):
        return "주간"
    return None


def _extract_actor_count_hint(text: str) -> int | None:
    match = re.search(r"(?:actor|액터|위험\s*객체|대상\s*차량)\s*(\d+)\s*(?:대|개)?", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _extract_road_alignment_hint(text: str) -> str | None:
    if any(keyword in text for keyword in ["곡선", "커브", "curve"]):
        return "곡선부"
    if any(keyword in text for keyword in ["교차로", "intersection"]):
        return "직선부 + 교차로"
    if any(keyword in text for keyword in ["직선", "straight"]):
        return "직선부"
    return None


def _extract_run_request(text: str, lowered: str) -> bool:
    negative_patterns = [
        "실행은 하지",
        "실행하지 말",
        "실행 하지 말",
        "실행 없이",
        "돌리지 말",
        "do not run",
        "don't run",
        "without running",
    ]
    if any(pattern in lowered or pattern in text for pattern in negative_patterns):
        return False
    return any(keyword in lowered or keyword in text for keyword in ["돌려", "실행", "run", "실험"])


def requirement_understanding_node(state: AgentState) -> AgentState:
    text = state.get("user_request", "")
    lowered = text.lower()
    scenario_type = _detect_scenario_type(text)
    wants_report = any(
        keyword in lowered or keyword in text
        for keyword in ["대시보드", "dashboard", "그래프", "보고서", "레이더", "report"]
    )
    intent = {
        "scenario_type": scenario_type,
        "requested_actions": {
            "create_definition": True,
            "validate_definition": True,
            "build_experiment_files": True,
            "run_simulation": _extract_run_request(text, lowered),
            "calculate_kpis": any(keyword in lowered or keyword in text for keyword in ["kpi", "지표", "계산", "평가"]),
            "generate_dashboard": wants_report,
            "generate_report": wants_report,
        },
        "detected_values": {
            "speed_kmh": _extract_speed_hint(text),
            "communication_range_m": _extract_comm_range_hint(text),
            "lane_count": _extract_lane_count_hint(text),
            "sensor_detection_range_m": _extract_lidar_range_hint(text),
            "lidar_channels": _extract_lidar_channels_hint(text),
            "sensor_frequency_hz": _extract_sensor_frequency_hint(text),
            "weather": _extract_weather_hint(text),
            "day_night": _extract_day_night_hint(text),
            "actor_count": _extract_actor_count_hint(text),
            "road_alignment_kind": _extract_road_alignment_hint(text),
            "v2x_mentioned": "v2x" in lowered or "통신" in text or "협력" in text,
            "occlusion_mentioned": any(keyword in text for keyword in ["음영", "가림", "시야", "occlusion", "차폐"]),
        },
    }
    return {**state, "intent": intent, "status": "intent_understood"}


def _scenario_id_for_type(scenario_type: str) -> str:
    if scenario_type == "highway_cutout":
        return "scenario_2"
    if scenario_type == "intersection_occlusion":
        return "scenario_1"
    return "custom"


def _apply_gpt_definition_autofill(
    definition_form: dict[str, Any],
    gpt_autofill: dict[str, Any],
) -> None:
    values = gpt_autofill.get("values") or {}
    if not isinstance(values, dict) or not values:
        definition_form["gpt_autofill"] = gpt_autofill
        return

    value_column = "시험 시나리오"
    for row in definition_form.get("rows", []):
        key = row.get("value_key")
        if key in values and values[key] not in (None, ""):
            row[value_column] = str(values[key])
            row["value_source"] = gpt_autofill.get("source", "gpt_autofill")
    definition_form["gpt_autofill"] = gpt_autofill


def scenario_specification_node(state: AgentState) -> AgentState:
    text = state.get("user_request", "")
    intent = state.get("intent", {})
    scenario_type = intent.get("scenario_type") or _detect_scenario_type(text)
    scenario_id = _scenario_id_for_type(scenario_type)
    reference_speed = 115.0 if scenario_id == "scenario_2" else 30.0
    detected = intent.get("detected_values", {})
    project_root = Path(__file__).resolve().parents[2]
    autofill = collect_definition_autofill_values(project_root, scenario_id)

    definition_form = build_scenario_definition_form(
        scenario_id=scenario_id,
        scenario_type=scenario_type,
        natural_language_request=text,
        reference_speed_kmh=reference_speed,
        detected_values=detected,
        autofill_values=autofill.get("values", {}),
        autofill_sources=autofill,
    )
    gpt_autofill = generate_gpt_definition_autofill(
        scenario_id=scenario_id,
        scenario_type=scenario_type,
        natural_language_request=text,
        reference_speed_kmh=reference_speed,
        detected_values=detected,
        definition_rows=definition_form.get("rows", []),
        existing_values=autofill.get("values", {}),
    )
    _apply_gpt_definition_autofill(definition_form, gpt_autofill)

    scenario_definition: Dict[str, Any] = {
        "schema_version": "0.2.0",
        "scenario_id": scenario_id,
        "scenario_type": scenario_type,
        "natural_language_request": text,
        "definition_format": definition_form["definition_format"],
        "definition_form": definition_form,
        "gpt_value_autofill": gpt_autofill,
        "road": {
            "map_name": "OpenCDA/CARLA",
            "road_type": "highway_or_2lane" if scenario_id == "scenario_2" else "unsignalized_intersection",
            "lanes": 2 if scenario_id == "scenario_2" else 1,
            "reference_speed_kmh": reference_speed,
        },
        "actors": [
            {
                "name": "ego",
                "role": "ego",
                "vehicle_type": "passenger_car",
                "initial_state": {
                    "lane": 1,
                    "speed_kmh": detected.get("speed_kmh"),
                    "movement": "straight_or_lane_change",
                },
                "v2x": {
                    "enabled": detected.get("v2x_mentioned"),
                    "communication_range_m": detected.get("communication_range_m"),
                    "message_provider": False,
                },
                "sensing": {
                    "perception_enabled": True,
                    "lidar_enabled": True,
                    "camera_enabled": True,
                },
            }
        ],
        "occlusion": {
            "enabled": bool(detected.get("occlusion_mentioned")),
            "cause_actor": None,
            "location": None,
        },
        "evaluation": {
            "kpis": DEFAULT_KPIS,
            "observation_horizon": {
                "start_s": 0.0,
                "end_policy": "event_time_if_exists_else_scenario_end",
                "window_s": 1.0,
                "stride_s": 0.1,
            },
        },
    }

    return {
        **state,
        "scenario_definition": scenario_definition,
        "status": "scenario_specified",
        "next_actions": ["정의서 표 검토", "미정 값 보완", "YAML/PY 실행 계획 생성"],
    }


def scenario_validate_node(state: AgentState) -> AgentState:
    definition = state.get("scenario_definition", {})
    errors: List[str] = []
    warnings: List[str] = []

    scenario_id = definition.get("scenario_id")
    if not scenario_id:
        errors.append("scenario_id가 없습니다.")
    if scenario_id == "custom":
        warnings.append("시나리오 1/2로 자동 분류되지 않았습니다. 실행 전 YAML 매핑을 확인해야 합니다.")
    if not definition.get("road", {}).get("reference_speed_kmh"):
        warnings.append("기준속도(reference_speed_kmh)가 명확하지 않습니다.")

    actors = definition.get("actors", [])
    if not any(actor.get("role") == "ego" for actor in actors):
        errors.append("ego 차량 정의가 없습니다.")

    for actor in actors:
        if (
            actor.get("role") == "ego"
            and actor.get("v2x", {}).get("enabled")
            and actor.get("v2x", {}).get("communication_range_m") is None
        ):
            actor["v2x"]["communication_range_m"] = 20.0

    open_items = definition.get("definition_form", {}).get("open_items", [])
    if open_items:
        warnings.append(f"정의서 표에서 후속 보완이 필요한 항목 {len(open_items)}개가 있습니다.")

    return {
        **state,
        "validation_errors": errors,
        "validation_warnings": warnings,
        "status": "validated" if not errors else "validation_failed",
    }


def experiment_planning_node(state: AgentState) -> AgentState:
    definition = state.get("scenario_definition", {})
    scenario_id = definition.get("scenario_id", "custom")
    scenario_type = definition.get("scenario_type", "custom")

    if scenario_id == "scenario_1":
        template_files = [
            "opencda/scenario_testing/scenario_1_v2x.py",
            "opencda/scenario_testing/scenario_1_no_v2x.py",
            "opencda/scenario_testing/config_yaml/scenario_1_v2x.yaml",
            "opencda/scenario_testing/config_yaml/scenario_1_no_v2x.yaml",
        ]
    elif scenario_id == "scenario_2":
        template_files = [
            "opencda/scenario_testing/scenario2.py",
            "opencda/scenario_testing/scenario2_v2x.py",
            "opencda/scenario_testing/config_yaml/scenario2.yaml",
            "opencda/scenario_testing/config_yaml/scenario2_v2x.yaml",
        ]
    else:
        template_files = []

    experiment_plan = {
        "scenario_id": scenario_id,
        "scenario_type": scenario_type,
        "strategy": "copy_original_files_to_run_workspace_then_execute_canonical_modules",
        "template_files": template_files,
        "expected_outputs": [
            "scenario_definition.json",
            "scenario_definition_form.json",
            "scenario_definition_form.csv",
            "run_manifest.json",
            "generated OpenCDA YAML/PY files",
            "OpenCDA/CARLA logs",
            "KPI result JSON/CSV",
            "evaluation_report.md",
        ],
        "runner_policy": {
            "requires_carla_running": True,
            "run_in_background_worker": True,
            "n8n_should_poll_status": True,
            "simulation_run_agent": {
                "enabled": True,
                "responsibilities": [
                    "OpenCDA/CARLA command execution",
                    "stdout/stderr log persistence",
                    "latest data_dumping folder pinning",
                    "fatal log-pattern detection",
                    "KPI-readiness classification",
                    "scenario objective alignment review",
                    "human-in-the-loop request on mismatch",
                ],
            },
        },
    }
    return {**state, "experiment_plan": experiment_plan, "status": "experiment_planned"}


def kpi_planning_node(state: AgentState) -> AgentState:
    kpi_plan = {
        "standard_version": "final_kpi_v2",
        "axes": {
            "perception": ["MOTA", "MOTP"],
            "traffic_impact": ["ProgressAdjustedDelay", "FlowEfficiency"],
            "driving_safety": ["Min2DTTC", "PET", "RequiredDeceleration"],
            "control": ["AccelerationVarianceMax", "YawRateResidualRMS"],
        },
        "normalization": {
            "higher_is_better": ["MOTA", "FlowEfficiency", "Min2DTTC", "PET"],
            "lower_is_better": [
                "MOTP",
                "ProgressAdjustedDelay",
                "RequiredDeceleration",
                "AccelerationVarianceMax",
                "YawRateResidualRMS",
            ],
            "pet_inf_policy": "map_to_zero_for_total_score_unless_reported_as_no_conflict",
        },
        "calculation_policy": {
            "perception": "same ego camera/LiDAR input; algorithm-level score; not V2X condition score",
            "control": "window-based maximum acceleration variance; yaw-rate residual against planned trajectory",
            "traffic": "route completion based on spawn-to-destination projection",
            "safety": "critical object selected by planned path conflict and minimum TTC/clearance",
        },
    }
    return {**state, "kpi_plan": kpi_plan, "status": "kpi_planned"}


def approval_gate_node(state: AgentState) -> AgentState:
    errors = state.get("validation_errors", [])
    warnings = state.get("validation_warnings", [])
    wants_run = state.get("intent", {}).get("requested_actions", {}).get("run_simulation", False)

    approval_required = bool(errors or warnings or wants_run)
    if errors:
        reason = "검증 오류가 있어 자동 실행을 중단합니다."
    elif warnings:
        reason = "정의서에 보완 항목이 있어 실행 전 검토가 필요합니다."
    elif wants_run:
        reason = "CARLA/OpenCDA 실행은 시간이 걸리므로 실행 승인이 필요합니다."
    else:
        reason = "설계/계획 단계이므로 즉시 시뮬레이션을 실행하지 않습니다."

    return {
        **state,
        "approval_required": approval_required,
        "approval_reason": reason,
        "status": "approval_required" if approval_required else "ready_for_build",
    }


def artifact_planning_node(state: AgentState) -> AgentState:
    run_id = state.get("run_id") or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    scenario_id = state.get("scenario_definition", {}).get("scenario_id", "custom")
    artifacts = {
        "run_id": run_id,
        "planned_run_dir": f"av_eval_agent/data/runs/{run_id}",
        "scenario_definition": f"av_eval_agent/data/runs/{run_id}/scenario_definition.json",
        "scenario_definition_form": f"av_eval_agent/data/runs/{run_id}/scenario_definition_form.json",
        "scenario_definition_form_csv": f"av_eval_agent/data/runs/{run_id}/scenario_definition_form.csv",
        "run_manifest": f"av_eval_agent/data/runs/{run_id}/run_manifest.json",
        "execution_plan": f"av_eval_agent/data/runs/{run_id}/execution_plan.json",
        "kpi_result": f"av_eval_agent/data/runs/{run_id}/kpi/kpi_result.json",
        "report": f"av_eval_agent/data/runs/{run_id}/report/evaluation_report.md",
        "note": "Agent가 정의서 표, 실행 계획, KPI 계획, 산출물 구조를 생성합니다. 실제 OpenCDA/CARLA 실행은 worker endpoint 승인 후 수행합니다.",
    }
    return {
        **state,
        "run_id": run_id,
        "artifacts": artifacts,
        "status": "agent_plan_created",
        "next_actions": [
            f"{scenario_id} 기준 YAML/PY 복사본 생성",
            "OpenCDA 실행 명령 연결",
            "공통 KPI 계산 스크립트 연결",
        ],
    }


def create_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("understand", requirement_understanding_node)
    graph.add_node("specify", scenario_specification_node)
    graph.add_node("validate", scenario_validate_node)
    graph.add_node("plan_experiment", experiment_planning_node)
    graph.add_node("plan_kpis", kpi_planning_node)
    graph.add_node("approval_gate", approval_gate_node)
    graph.add_node("plan_artifacts", artifact_planning_node)
    graph.set_entry_point("understand")
    graph.add_edge("understand", "specify")
    graph.add_edge("specify", "validate")
    graph.add_edge("validate", "plan_experiment")
    graph.add_edge("plan_experiment", "plan_kpis")
    graph.add_edge("plan_kpis", "approval_gate")
    graph.add_edge("approval_gate", "plan_artifacts")
    graph.add_edge("plan_artifacts", END)
    return graph.compile()


agent_graph = create_agent_graph()
