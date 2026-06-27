from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml


SCENARIO_YAML_SOURCES: dict[str, list[str]] = {
    "scenario_1": [
        "opencda/scenario_testing/config_yaml/scenario_1_v2x.yaml",
        "opencda/scenario_testing/config_yaml/scenario_1_no_v2x.yaml",
    ],
    "scenario_2": [
        "opencda/scenario_testing/config_yaml/scenario2_v2x.yaml",
        "opencda/scenario_testing/config_yaml/scenario2.yaml",
    ],
}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _first_number(values: list[Any], default: float = 0.0) -> float:
    try:
        return float(values[0])
    except (TypeError, ValueError, IndexError):
        return default


def _xy(position: list[Any] | None) -> tuple[float, float]:
    if not position:
        return 0.0, 0.0
    return _first_number(position, 0.0), _first_number(position[1:], 0.0)


def _yaw_deg(position: list[Any] | None) -> float:
    if not position or len(position) < 5:
        return 0.0
    try:
        return float(position[4])
    except (TypeError, ValueError):
        return 0.0


def _distance_m(a: list[Any] | None, b: list[Any] | None) -> float:
    ax, ay = _xy(a)
    bx, by = _xy(b)
    return math.hypot(bx - ax, by - ay)


def _speed_kmh(actor: dict[str, Any], base_speed: float | None = None) -> float | None:
    scripted = actor.get("scripted_profile") or {}
    if scripted.get("speed_mps") is not None:
        return float(scripted["speed_mps"]) * 3.6
    behavior = actor.get("behavior") or {}
    if behavior.get("max_speed") is not None:
        return float(behavior["max_speed"])
    return base_speed


def _speed_text(actor: dict[str, Any], base_speed: float | None = None) -> str:
    speed = _speed_kmh(actor, base_speed)
    scripted = actor.get("scripted_profile") or {}
    behavior = actor.get("behavior") or {}
    if speed is None:
        return "YAML 기준 미확인"
    if scripted.get("speed_mps") is not None and behavior.get("max_speed") is not None:
        return f"{speed:.1f}km/h (scripted_profile), max_speed {behavior['max_speed']}km/h"
    return f"{speed:.1f}km/h"


def _relative_position_text(ego: dict[str, Any], actor: dict[str, Any]) -> str:
    ex, ey = _xy(ego.get("spawn_position"))
    ax, ay = _xy(actor.get("spawn_position"))
    dx = ax - ex
    dy = ay - ey
    yaw = math.radians(_yaw_deg(ego.get("spawn_position")))

    forward_x, forward_y = math.cos(yaw), math.sin(yaw)
    left_x, left_y = -math.sin(yaw), math.cos(yaw)
    longitudinal = dx * forward_x + dy * forward_y
    lateral = dx * left_x + dy * left_y

    long_text = "전방" if longitudinal > 2 else "후방" if longitudinal < -2 else "동일선상"
    lat_text = "좌측" if lateral > 2 else "우측" if lateral < -2 else ""
    if lat_text and long_text != "동일선상":
        return f"{lat_text} {long_text}"
    if lat_text:
        return lat_text
    return long_text


def _gap_text(ego: dict[str, Any], actor: dict[str, Any], base_speed: float | None = None) -> str:
    distance = _distance_m(ego.get("spawn_position"), actor.get("spawn_position"))
    speed = _speed_kmh(ego, base_speed) or base_speed or 0.0
    speed_mps = speed / 3.6
    if speed_mps > 0.1:
        return f"{distance / speed_mps:.2f}s ({distance:.1f}m, YAML spawn 기준)"
    return f"{distance:.1f}m (YAML spawn 기준)"


def _vehicle_kind(vehicle_type: str | None, default: str = "승용차") -> str:
    if not vehicle_type:
        return default
    lowered = vehicle_type.lower()
    if "fusorosa" in lowered or "bus" in lowered:
        return "버스"
    if "patrol" in lowered:
        return "SUV/승용차"
    if "micra" in lowered or "charger" in lowered or "mkz" in lowered:
        return "승용차"
    return vehicle_type


def _lidar_bandwidth_text(lidar: dict[str, Any]) -> str:
    """Estimate LiDAR data bandwidth from YAML points_per_second.

    The estimate assumes each point stores XYZI as 4 float32 values, i.e. 16
    bytes per point. If the YAML does not expose the point rate, use a typical
    evaluation assumption of 100,000 points/s.
    """

    points_per_second = lidar.get("points_per_second") or 100_000
    try:
        pps = float(points_per_second)
    except (TypeError, ValueError):
        pps = 100_000.0
    mbps = pps * 16 * 8 / 1_000_000
    return f"LiDAR 약 {mbps:.1f}Mbps ({int(pps):,}pts/s, XYZI 16B/point 기준)"


def _get_cavs(data: dict[str, Any]) -> list[dict[str, Any]]:
    return list((data.get("scenario") or {}).get("single_cav_list") or [])


def _find_actor(cavs: list[dict[str, Any]], name_part: str) -> dict[str, Any] | None:
    for cav in cavs:
        if name_part in str(cav.get("name", "")).lower():
            return cav
    return None


def _scenario_1_autofill(data: dict[str, Any]) -> dict[str, str]:
    vehicle_base = data.get("vehicle_base") or {}
    base_behavior = vehicle_base.get("behavior") or {}
    base_speed = float(base_behavior.get("max_speed") or 20)
    base_v2x = vehicle_base.get("v2x") or {}
    lidar = ((vehicle_base.get("sensing") or {}).get("lidar") or {})
    cavs = _get_cavs(data)
    ego = _find_actor(cavs, "ego") or (cavs[0] if cavs else {})
    actor = _find_actor(cavs, "subject") or (cavs[-1] if cavs else {})
    neighbor = _find_actor(cavs, "neighbor") or {}

    actor_v2x = actor.get("v2x") or {}
    neighbor_v2x = neighbor.get("v2x") or {}
    ego_lidar = (((ego.get("sensing") or {}).get("perception") or {}).get("lidar") or lidar)

    return {
        "road_speed_limit": f"{base_speed:.0f}km/h (YAML behavior.max_speed)",
        "ego_speed": _speed_text(ego, base_speed),
        "actor_speed": _speed_text(actor, base_speed),
        "neighbor_speed": _speed_text(neighbor, 0.0),
        "actor_v2x": "가능" if actor_v2x.get("enabled") else "불가능",
        "neighbor_v2x": "가능" if neighbor_v2x.get("enabled") else "불가능",
        "actor_initial_relative_position": _relative_position_text(ego, actor),
        "actor_initial_longitudinal_gap": _gap_text(ego, actor, base_speed),
        "actor_relative_position": _relative_position_text(ego, actor),
        "actor_relative_gap": _gap_text(ego, actor, base_speed),
        "neighbor_relative_position": _relative_position_text(ego, neighbor),
        "neighbor_relative_gap": _gap_text(ego, neighbor, base_speed),
        "neighbor_longitudinal_motion": "정지" if float((neighbor.get("behavior") or {}).get("max_speed") or 0) == 0 else "주행",
        "sensor_detection_range": f"LiDAR {ego_lidar.get('range', lidar.get('range', '미정'))}m",
        "sensor_resolution": f"LiDAR channels {ego_lidar.get('channels', '미정')}",
        "sensor_frequency": f"LiDAR rotation_frequency {ego_lidar.get('rotation_frequency', '미정')}Hz",
        "sensor_bandwidth": _lidar_bandwidth_text(ego_lidar),
        "communication_bandwidth": "10MHz 채널 대역폭 (5.9GHz ITS/V2X 일반 가정)",
        "communication_frequency": "5.9GHz ITS band",
        "communication_latency": "100ms 이하 가정",
        "communication_loss_rate": "1% 이하 가정",
        "dynamic_information_type": f"Actor 위치/속도/ID, 통신 반경 {actor_v2x.get('communication_range', base_v2x.get('communication_range', 0))}m",
    }


def _scenario_2_autofill(data: dict[str, Any]) -> dict[str, str]:
    vehicle_base = data.get("vehicle_base") or {}
    base_behavior = vehicle_base.get("behavior") or {}
    base_speed = float(base_behavior.get("max_speed") or 25)
    base_v2x = vehicle_base.get("v2x") or {}
    lidar = ((vehicle_base.get("sensing") or {}).get("lidar") or {})
    cavs = _get_cavs(data)
    traffic_list = (data.get("carla_traffic_manager") or {}).get("vehicle_list") or []

    ego = _find_actor(cavs, "subject") or (cavs[0] if cavs else {})
    actor = traffic_list[0] if traffic_list else (_find_actor(cavs, "target") or (cavs[-1] if cavs else {}))
    neighbor = _find_actor(cavs, "neighbor") or {}
    actor_v2x = actor.get("v2x") or base_v2x
    neighbor_v2x = neighbor.get("v2x") or {}

    return {
        "road_speed_limit": f"{base_speed:.0f}km/h (YAML behavior.max_speed)",
        "lane_count": "2",
        "ego_vehicle_type": _vehicle_kind(ego.get("vehicle_type")),
        "ego_speed": _speed_text(ego, base_speed),
        "actor_type": _vehicle_kind(actor.get("vehicle_type")),
        "actor_v2x": "가능" if bool(actor_v2x.get("enabled")) else "불가능",
        "actor_initial_relative_position": _relative_position_text(ego, actor),
        "actor_initial_longitudinal_gap": _gap_text(ego, actor, base_speed),
        "actor_relative_position": _relative_position_text(ego, actor),
        "actor_relative_gap": _gap_text(ego, actor, base_speed),
        "actor_speed": _speed_text(actor, base_speed),
        "actor_longitudinal_motion": "등속 주행" if _speed_kmh(actor, 0.0) else "정지",
        "neighbor_type": _vehicle_kind(neighbor.get("vehicle_type")),
        "neighbor_v2x": "가능" if neighbor_v2x.get("enabled") else "불가능",
        "neighbor_relative_position": _relative_position_text(ego, neighbor),
        "neighbor_relative_gap": _gap_text(ego, neighbor, base_speed),
        "neighbor_speed": _speed_text(neighbor, base_speed),
        "traffic_density": f"{len(traffic_list)}대 배경교통",
        "sensor_detection_range": f"LiDAR {lidar.get('range', '미정')}m",
        "sensor_resolution": f"LiDAR channels {lidar.get('channels', '미정')}",
        "sensor_frequency": f"LiDAR rotation_frequency {lidar.get('rotation_frequency', '미정')}Hz",
        "sensor_bandwidth": _lidar_bandwidth_text(lidar),
        "communication_bandwidth": "10MHz 채널 대역폭 (5.9GHz ITS/V2X 일반 가정)",
        "communication_frequency": "5.9GHz ITS band",
        "communication_latency": "100ms 이하 가정",
        "communication_loss_rate": "1% 이하 가정",
        "dynamic_information_type": f"주변 차량 위치/속도/ID, 통신 반경 {base_v2x.get('communication_range', 0)}m",
    }


def collect_definition_autofill_values(project_root: Path, scenario_id: str) -> dict[str, Any]:
    """Collect definition-table values from the scenario YAML files.

    The first YAML in the scenario source list is used as the representative
    condition. Additional YAML paths are recorded as provenance so reviewers know
    where the automatic values came from.
    """

    source_paths = [project_root / item for item in SCENARIO_YAML_SOURCES.get(scenario_id, [])]
    existing_sources = [path for path in source_paths if path.exists()]
    if not existing_sources:
        return {
            "values": {},
            "sources": [],
            "notes": [f"{scenario_id}에 연결된 YAML 파일을 찾지 못했습니다."],
        }

    representative = existing_sources[0]
    data = _load_yaml(representative)
    if scenario_id == "scenario_2":
        values = _scenario_2_autofill(data)
    elif scenario_id == "scenario_1":
        values = _scenario_1_autofill(data)
    else:
        values = {}

    return {
        "values": {key: value for key, value in values.items() if value not in (None, "")},
        "sources": [str(path) for path in existing_sources],
        "representative_source": str(representative),
        "notes": ["YAML spawn_position, behavior, v2x, sensing 설정에서 자동 보완했습니다."],
    }
