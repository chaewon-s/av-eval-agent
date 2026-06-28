from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


def _extract_json_object(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _call_openai_for_definition_autofill(
    payload: dict[str, Any],
    *,
    model: str,
    timeout_s: int = 60,
) -> dict[str, Any] | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key or api_key in {"여기에_API_KEY", "YOUR_API_KEY"}:
        return None

    system_prompt = (
        "You are ScenarioSpecAgent for an autonomous-driving evaluation program. "
        "Convert natural-language scenario requests into the Korean scenario definition table values. "
        "If the user omits values, fill ordinary, conservative values suitable for CARLA/OpenCDA testing. "
        "Use existing YAML/autofill values as the strongest prior. "
        "Return only strict JSON. Do not include markdown."
    )
    user_prompt = json.dumps(
        {
            "task": "Fill or refine scenario definition values.",
            "output_schema": {
                "values": {"value_key": "filled value string"},
                "assumptions": ["short Korean assumption"],
                "confidence": 0.0,
                "needs_human_review": False,
            },
            "rules": [
                "MOTA/MOTP are perception-algorithm KPIs, not V2X-vs-NoV2X visual acuity.",
                "Scenario 1 is unsignalized intersection occlusion unless the user says otherwise.",
                "Scenario 2 is two-lane cut-out/highway lane-change unless the user says otherwise.",
                "Use time-gap values when the definition form asks for longitudinal relative distance in seconds.",
                "For unknown V2X range use 20m if the study context implies V2X communication.",
                "For sensor range use the YAML LiDAR/camera settings when present.",
            ],
            "context": payload,
        },
        ensure_ascii=False,
    )
    request_body = json.dumps(
        {
            "model": model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
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
            response_payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    output_text = response_payload.get("output_text")
    if not output_text:
        chunks: list[str] = []
        for item in response_payload.get("output", []) or []:
            for content in item.get("content", []) or []:
                text = content.get("text")
                if text:
                    chunks.append(text)
        output_text = "\n".join(chunks)
    return _extract_json_object(output_text or "")


def _fallback_definition_autofill(payload: dict[str, Any]) -> dict[str, Any]:
    scenario_id = payload.get("scenario_id")
    detected = payload.get("detected_values") or {}
    existing_values = payload.get("existing_values") or {}
    values: dict[str, str] = {}

    if scenario_id == "scenario_1":
        speed = detected.get("speed_kmh") or "20"
        values.update(
            {
                "road_speed_limit": "30km/h",
                "ego_speed": f"{speed}km/h",
                "actor_speed": f"{speed}km/h",
                "actor_initial_longitudinal_gap": "1.8s",
                "actor_relative_gap": "1.9s",
                "actor_v2x": "V2X 조건 가능, No V2X 조건 불가능",
                "neighbor_v2x": "불가능",
                "sensor_detection_range": existing_values.get("sensor_detection_range", "LiDAR 50m"),
                "communication_frequency": existing_values.get("communication_frequency", "5.9GHz ITS band"),
                "dynamic_information_type": "Actor 위치/속도/ID, V2X 통신 반경 20m",
            }
        )
    elif scenario_id == "scenario_2":
        values.update(
            {
                "road_speed_limit": "115km/h",
                "lane_count": "2",
                "ego_motion": "전방 정지차량 인지 후 차선변경",
                "actor_initial_relative_position": "전방",
                "actor_initial_longitudinal_gap": existing_values.get(
                    "actor_initial_longitudinal_gap",
                    "YAML spawn_position 기준 산출",
                ),
                "actor_longitudinal_motion": "정지",
                "actor_speed": "0km/h",
                "neighbor_v2x": "V2X 조건에서 ego 바로 앞/주변 차량 통신 가능",
                "sensor_detection_range": existing_values.get("sensor_detection_range", "LiDAR 50m"),
                "dynamic_information_type": "정지차량/주변차량 위치, 속도, ID, 통신 반경 20m",
            }
        )

    return {
        "values": values,
        "assumptions": [
            "OPENAI_API_KEY가 설정되지 않아 기존 YAML/autofill 값과 연구 기본값으로 정의서 값을 보완했습니다.",
            "사용자가 명시하지 않은 값은 보수적인 일반 실험값으로 채웠고, 실행 후 AutoTuneAgent가 KPI 기반으로 조정합니다.",
        ],
        "confidence": 0.45,
        "needs_human_review": True,
        "source": "rule_fallback",
    }


def _compact_rows(rows: list[dict[str, Any]], limit: int = 80) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for row in rows[:limit]:
        compact.append(
            {
                "value_key": str(row.get("value_key", "")),
                "element": str(row.get("요소", "")),
                "description": str(row.get("설명", "")),
                "current_value": str(row.get("시험 시나리오", "")),
            }
        )
    return compact


def generate_gpt_definition_autofill(
    *,
    scenario_id: str,
    scenario_type: str,
    natural_language_request: str,
    reference_speed_kmh: float,
    detected_values: dict[str, Any],
    definition_rows: list[dict[str, Any]],
    existing_values: dict[str, Any],
    model: str = "gpt-4.1-mini",
) -> dict[str, Any]:
    payload = {
        "scenario_id": scenario_id,
        "scenario_type": scenario_type,
        "natural_language_request": natural_language_request,
        "reference_speed_kmh": reference_speed_kmh,
        "detected_values": detected_values,
        "existing_values": existing_values,
        "definition_rows": _compact_rows(definition_rows),
    }
    result = _call_openai_for_definition_autofill(payload, model=model)
    if result is None:
        result = _fallback_definition_autofill(payload)
    else:
        result.setdefault("source", "openai_responses_api")
        result.setdefault("confidence", 0.6)
        result.setdefault("needs_human_review", False)
        if not isinstance(result.get("values"), dict):
            result["values"] = {}
        if not isinstance(result.get("assumptions"), list):
            result["assumptions"] = []
    result["model"] = model
    return result
