from __future__ import annotations

from typing import Any, Dict, Iterable


SCENARIO_DEFINITION_FORMAT = "과-19_시나리오_정의서_6-layer_v2"
SCENARIO_DEFINITION_SOURCE = "C:/Users/User/Desktop/연구 관련 파일/(과-19)시나리오 정의서 (2).pdf"
TABLE_COLUMNS = ["레이어", "항목", "요소", "설명", "시험 시나리오"]


def _row(layer: str | None, item: str | None, element: str, description: str, key: str) -> dict[str, str]:
    return {
        "레이어": layer or "",
        "항목": item or "",
        "요소": element,
        "설명": description,
        "value_key": key,
    }


DEFINITION_ROWS: list[dict[str, str]] = [
    _row("레이어 1: 평면 데이터", "도로구간", "도로구간 종류", "시험 도로의 기본 구간 유형", "road_segment_kind"),
    _row(None, "도로선형", "도로선형 종류", "직선부, 곡선부, 교차로 등 평면 선형", "road_alignment_kind"),
    _row(None, None, "평면곡선부 최소 평면곡선 반지름", "곡선부가 있을 때 최소 반지름", "min_curve_radius"),
    _row(None, None, "평면곡선부 최소 평면곡선 길이", "곡선부가 있을 때 최소 곡선 길이", "min_curve_length"),
    _row(None, "종단선형", "최대 종단경사", "도로의 최대 종방향 경사", "max_grade"),
    _row(None, "횡단구성", "차로수", "주행 가능한 차로 수", "lane_count"),
    _row(None, None, "최소 차로폭", "각 차로의 최소 폭", "min_lane_width"),
    _row(None, None, "최소 오른쪽 길어깨 폭", "우측 길어깨 폭", "right_shoulder_width"),
    _row(None, None, "최소 왼쪽 길어깨 폭", "좌측 길어깨 폭", "left_shoulder_width"),
    _row(None, "노면", "포장면 종류", "아스팔트, 콘크리트 등", "pavement_type"),
    _row(None, "보행시설", "횡단보도 여부", "횡단보도 존재 여부", "crosswalk"),
    _row(None, "기타", "도로 제한 속도", "시험 도로의 제한 또는 기준 속도", "road_speed_limit"),
    _row("레이어 2: 입체 데이터", "도로 구조물", "도로 구조물 종류", "일반도로, 교량, 터널 등", "road_structure_kind"),
    _row(None, None, "중앙분리대 종류", "중앙분리대 유무 및 종류", "median_kind"),
    _row(None, None, "비상주차대 여부", "비상주차대 존재 여부", "emergency_parking"),
    _row(None, "도로 시설물", "교통신호기 종류", "차량등, 보행등 등", "traffic_signal_kind"),
    _row(None, None, "교통신호기 설치형식", "횡형, 종형, 측주식 등", "traffic_signal_installation"),
    _row(None, None, "교통기반시설 여부", "RSU, V2X 인프라 등", "traffic_infra_presence"),
    _row(None, None, "교통기반시설 위치", "인프라 설치 위치", "traffic_infra_location"),
    _row(None, "표지", "규제표지 여부", "규제표지 존재 여부", "regulatory_sign"),
    _row(None, None, "주의표지 여부", "주의표지 존재 여부", "warning_sign"),
    _row(None, None, "지시표지 여부", "지시표지 존재 여부", "guide_sign"),
    _row(None, "조명", "도로조명시설 종류", "가로등, 터널등 등", "road_lighting"),
    _row(None, "대중교통", "버스정류장 종류", "정류장 존재 및 종류", "bus_stop_kind"),
    _row("레이어 3: 가변시설 및 임시시설 데이터", "가변시설", "가변시설 종류", "가변차로, 버스전용차로 등", "variable_facility_kind"),
    _row(None, None, "버스전용차로 운영 여부", "버스전용차로 운영 여부", "bus_lane_operation"),
    _row(None, None, "길어깨차로제 운영 여부", "길어깨차로제 운영 여부", "shoulder_lane_operation"),
    _row(None, None, "가변속도제한 운영 여부", "가변속도제한 운영 여부", "variable_speed_limit"),
    _row(None, "임시시설", "공사 및 작업 여부", "공사 또는 작업 구간 여부", "work_zone"),
    _row(None, None, "공사 및 작업 차로", "공사 또는 작업이 있는 차로", "work_zone_lane"),
    _row(None, None, "공사 및 작업 관련물 종류", "콘, 표지판, 작업차 등", "work_zone_object"),
    _row(None, None, "사고 여부", "선행 사고 또는 정지 이벤트 여부", "incident"),
    _row(None, None, "사고 차로", "사고가 발생한 차로", "incident_lane"),
    _row(None, None, "사고 관련물 종류", "사고 관련 차량 또는 물체", "incident_object"),
    _row("레이어 4: 시나리오 참여자 데이터", "Ego Vehicle", "차종", "평가 대상 자율주행 차량 종류", "ego_vehicle_type"),
    _row(None, None, "초기 주행 차선", "Ego 초기 차선", "ego_initial_lane"),
    _row(None, None, "초기 움직임 - 횡방향 움직임", "초기 횡방향 움직임", "ego_initial_lateral_motion"),
    _row(None, None, "초기 움직임 - 종방향 움직임", "초기 종방향 움직임", "ego_initial_longitudinal_motion"),
    _row(None, None, "주행 차선", "Ego 주행 차선", "ego_lane"),
    _row(None, None, "움직임", "주요 주행 행동", "ego_motion"),
    _row(None, None, "종방향 속도", "Ego 목표 또는 초기 속도", "ego_speed"),
    _row(None, None, "인지 음영 발생 여부", "시야 가림 또는 센서 음영 존재 여부", "ego_occlusion_presence"),
    _row(None, None, "인지 음영 원인", "음영 발생 원인", "ego_occlusion_cause"),
    _row(None, None, "인지 음영 발생 위치", "Ego 기준 음영 위치", "ego_occlusion_location"),
    _row(None, "Actor", "Actor 수", "주요 위험/상호작용 객체 수", "actor_count"),
    _row(None, None, "차종 또는 종류", "Actor 차종 또는 물체 종류", "actor_type"),
    _row(None, None, "자율주행차 여부", "Actor 자동화 수준", "actor_autonomy"),
    _row(None, None, "V2X 통신 여부", "Actor V2X 송수신 가능 여부", "actor_v2x"),
    _row(None, None, "초기 주행 혹은 위치 차선", "Actor 초기 차선", "actor_initial_lane"),
    _row(None, None, "초기 상대 위치", "Ego 기준 Actor 초기 상대 위치", "actor_initial_relative_position"),
    _row(None, None, "초기 종방향 상대 거리", "초기 time gap 또는 거리", "actor_initial_longitudinal_gap"),
    _row(None, None, "초기 움직임", "Actor 초기 움직임", "actor_initial_motion"),
    _row(None, None, "주행 혹은 위치한 차선", "Actor 주행 또는 위치 차선", "actor_lane"),
    _row(None, None, "상대 위치", "Ego 기준 Actor 상대 위치", "actor_relative_position"),
    _row(None, None, "상대 거리", "Ego 기준 Actor 상대 거리", "actor_relative_gap"),
    _row(None, None, "움직임 - 횡방향 움직임", "Actor 횡방향 움직임", "actor_lateral_motion"),
    _row(None, None, "움직임 - 종방향 움직임", "Actor 종방향 움직임", "actor_longitudinal_motion"),
    _row(None, None, "종방향 속도", "Actor 종방향 속도", "actor_speed"),
    _row(None, None, "종방향 가속도", "Actor 종방향 가속도", "actor_acceleration"),
    _row(None, None, "차선 이탈 시 횡방향 속도", "차선 변경/이탈 시 횡방향 속도", "actor_lateral_speed"),
    _row(None, "Neighboring", "Neighboring 수", "주변 차량 수", "neighbor_count"),
    _row(None, None, "종류", "주변 차량 종류", "neighbor_type"),
    _row(None, None, "자율주행차 여부", "주변 차량 자동화 수준", "neighbor_autonomy"),
    _row(None, None, "V2X 통신 여부", "주변 차량 V2X 여부", "neighbor_v2x"),
    _row(None, None, "주행 혹은 위치한 차선", "주변 차량 차선", "neighbor_lane"),
    _row(None, None, "상대 위치", "Ego 기준 주변 차량 상대 위치", "neighbor_relative_position"),
    _row(None, None, "상대 거리", "Ego 기준 주변 차량 상대 거리", "neighbor_relative_gap"),
    _row(None, None, "움직임 - 횡방향 움직임", "주변 차량 횡방향 움직임", "neighbor_lateral_motion"),
    _row(None, None, "움직임 - 종방향 움직임", "주변 차량 종방향 움직임", "neighbor_longitudinal_motion"),
    _row(None, None, "종방향 속도", "주변 차량 종방향 속도", "neighbor_speed"),
    _row("레이어 5: 주변환경 데이터", "운영 제약", "밀도", "배경 교통 밀도", "traffic_density"),
    _row(None, "조도", "주간/야간", "시험 시간대", "day_night"),
    _row(None, "기상", "날씨 종류", "맑음, 비, 안개 등", "weather"),
    _row(None, None, "최대 풍속", "최대 풍속", "max_wind_speed"),
    _row(None, "노면", "노면 상태", "건조, 젖음 등", "road_surface"),
    _row(None, "가시성", "가시성 감소 원인", "안개, 강우, 차폐 등", "visibility_reduction_cause"),
    _row(None, None, "감소 원인 농도", "가시성 저하 농도 또는 강도", "visibility_reduction_density"),
    _row("레이어 6: 디지털 데이터", "센서", "센서 수", "사용 센서 수", "sensor_count"),
    _row(None, None, "센서 종류", "카메라, LiDAR, Radar, GPS 등", "sensor_kind"),
    _row(None, None, "센서 상태", "정상, 고장, noise 등", "sensor_status"),
    _row(None, None, "센서 탑재 위치", "차량 또는 인프라 기준 탑재 위치", "sensor_mount_position"),
    _row(None, None, "센서 탐지 범위", "센서 인식 가능 거리", "sensor_detection_range"),
    _row(None, None, "센서 해상도", "센서 공간/이미지 해상도", "sensor_resolution"),
    _row(None, None, "센서 주파수", "센서 갱신 주파수", "sensor_frequency"),
    _row(None, None, "센서 대역폭", "센서 데이터 대역폭", "sensor_bandwidth"),
    _row(None, "통신", "통신 대역폭", "V2X 통신 대역폭", "communication_bandwidth"),
    _row(None, None, "통신 주파수", "V2X 통신 주파수", "communication_frequency"),
    _row(None, None, "데이터 송수신 오류 여부", "통신 오류 존재 여부", "communication_error"),
    _row(None, None, "통신 지연시간", "V2X 메시지 지연시간", "communication_latency"),
    _row(None, None, "데이터 손실률", "통신 패킷 손실률", "communication_loss_rate"),
    _row(None, None, "동적 정보 유형", "공유되는 동적 객체 정보 종류", "dynamic_information_type"),
]


def _base_values(reference_speed_kmh: float, detected: dict[str, Any]) -> dict[str, str]:
    speed = detected.get("speed_kmh") or reference_speed_kmh
    comm_range = detected.get("communication_range_m")
    comm_range_text = f"{comm_range:g}m" if isinstance(comm_range, (int, float)) else "20m"
    lane_count = detected.get("lane_count") or 1
    road_alignment = detected.get("road_alignment_kind") or "직선부"
    sensor_range = detected.get("sensor_detection_range_m")
    lidar_channels = detected.get("lidar_channels")
    sensor_frequency = detected.get("sensor_frequency_hz")
    occlusion_present = bool(detected.get("occlusion_mentioned"))
    occlusion_text = "있음" if occlusion_present else "없음"
    occlusion_cause = "차량 차폐" if occlusion_present else "해당없음"
    occlusion_location = "전방" if occlusion_present else "해당없음"

    return {
        "road_segment_kind": "사용자 정의 일반도로 시험 구간",
        "min_curve_radius": "해당없음",
        "min_curve_length": "해당없음",
        "max_grade": "0%",
        "min_lane_width": "CARLA map 기준",
        "right_shoulder_width": "해당없음",
        "left_shoulder_width": "해당없음",
        "pavement_type": "아스팔트",
        "crosswalk": "없음",
        "road_speed_limit": f"{reference_speed_kmh:g}km/h",
        "road_structure_kind": "일반도로",
        "median_kind": "없음",
        "emergency_parking": "없음",
        "traffic_signal_kind": "해당없음",
        "traffic_signal_installation": "해당없음",
        "traffic_infra_presence": "V2X 비교 조건에서 사용",
        "traffic_infra_location": "Ego/Actor 통신 반경 기준",
        "regulatory_sign": "해당없음",
        "warning_sign": "해당없음",
        "guide_sign": "해당없음",
        "road_lighting": "해당없음",
        "bus_stop_kind": "해당없음",
        "variable_facility_kind": "해당없음",
        "bus_lane_operation": "없음",
        "shoulder_lane_operation": "없음",
        "variable_speed_limit": "없음",
        "work_zone": "없음",
        "work_zone_lane": "해당없음",
        "work_zone_object": "해당없음",
        "incident": "시나리오 이벤트로 정의",
        "incident_lane": "Ego 주행 차로",
        "incident_object": "위험 객체/대상 차량",
        "ego_vehicle_type": "승용차",
        "ego_initial_lane": "1",
        "ego_initial_lateral_motion": "직진",
        "ego_initial_longitudinal_motion": "등속",
        "ego_lane": "1",
        "ego_motion": "시나리오 이벤트 대응",
        "ego_speed": f"{speed:g}km/h",
        "ego_occlusion_presence": occlusion_text,
        "ego_occlusion_cause": occlusion_cause,
        "ego_occlusion_location": occlusion_location,
        "actor_count": "1",
        "actor_type": "승용차",
        "actor_autonomy": "레벨 0",
        "actor_v2x": "V2X 조건: 가능 / No V2X 조건: 불가능",
        "actor_initial_lane": "1",
        "actor_initial_relative_position": "전방",
        "actor_initial_longitudinal_gap": "2.0s 일반 가정",
        "actor_initial_motion": "직진",
        "actor_lane": "1",
        "actor_relative_position": "전방",
        "actor_relative_gap": "2.0s 일반 가정",
        "actor_lateral_motion": "직진",
        "actor_longitudinal_motion": "등속 또는 정지 위험 객체",
        "actor_speed": f"{speed:g}km/h",
        "actor_acceleration": "0m/s² 일반 가정",
        "actor_lateral_speed": "해당없음",
        "neighbor_count": "1",
        "neighbor_type": "일반 차량",
        "neighbor_autonomy": "레벨 0",
        "neighbor_v2x": "불가능",
        "neighbor_lane": "1",
        "neighbor_relative_position": "전방 또는 인접 차로",
        "neighbor_relative_gap": "2.0s 일반 가정",
        "neighbor_lateral_motion": "기타",
        "neighbor_longitudinal_motion": "등속",
        "neighbor_speed": f"{speed:g}km/h",
        "traffic_density": "1대 배경교통 일반 가정",
        "day_night": detected.get("day_night") or "주간",
        "weather": detected.get("weather") or "맑음",
        "max_wind_speed": "0m/s",
        "road_surface": "건조",
        "visibility_reduction_cause": "차량 차폐",
        "visibility_reduction_density": "해당없음",
        "sensor_count": "카메라/LiDAR/GPS",
        "sensor_kind": "카메라, LiDAR, GPS",
        "sensor_status": "정상",
        "sensor_mount_position": "Ego 차량 탑재",
        "sensor_detection_range": f"LiDAR {sensor_range:g}m" if isinstance(sensor_range, (int, float)) else "LiDAR 50m 기준",
        "sensor_resolution": f"LiDAR channels {lidar_channels}" if isinstance(lidar_channels, int) else "YAML 센서 설정 기준",
        "sensor_frequency": f"LiDAR rotation_frequency {sensor_frequency:g}Hz" if isinstance(sensor_frequency, (int, float)) else "LiDAR rotation_frequency 기준",
        "sensor_bandwidth": "LiDAR 약 12.8Mbps (100,000pts/s, XYZI 16B/point 기준)",
        "communication_bandwidth": "10MHz 채널 대역폭 (5.9GHz ITS/V2X 일반 가정)",
        "communication_frequency": "5.9GHz ITS band",
        "communication_error": "없음",
        "communication_latency": "100ms 이하 가정",
        "communication_loss_rate": "1% 이하 가정",
        "dynamic_information_type": f"Actor 위치/속도/ID, 통신 반경 {comm_range_text}",
        "road_alignment_kind": road_alignment,
        "lane_count": str(lane_count),
        "actor_count": str(detected.get("actor_count") or 1),
    }


def _scenario_1_values(reference_speed_kmh: float, detected: dict[str, Any]) -> dict[str, str]:
    values = _base_values(reference_speed_kmh, detected)
    speed = detected.get("speed_kmh") or 20.0
    values.update(
        {
            "road_segment_kind": "비신호 4지 교차로 접근 일반도로",
            "road_alignment_kind": "직선부 + 교차로",
            "lane_count": "1",
            "crosswalk": "없음 또는 교차로부 기준",
            "road_speed_limit": "30km/h",
            "traffic_signal_kind": "없음",
            "traffic_signal_installation": "해당없음",
            "incident_lane": "교차로 접근 차로",
            "incident_object": "교차 접근 Actor 차량",
            "ego_motion": "정지선 감속/양보 후 재출발",
            "ego_speed": f"{speed:g}km/h",
            "ego_occlusion_presence": "있음",
            "ego_occlusion_cause": "정차 버스/트럭에 의한 좌측 전방 시야 차폐",
            "ego_occlusion_location": "좌측 전방",
            "actor_type": "승용차",
            "actor_initial_relative_position": "좌측 전방",
            "actor_initial_longitudinal_gap": "정의서 기준 1.8s 내외",
            "actor_relative_position": "좌측 전방",
            "actor_relative_gap": "정의서 기준 1.9s 내외",
            "actor_longitudinal_motion": "직진 또는 감속",
            "actor_speed": f"{speed:g}km/h",
            "actor_acceleration": "-5m/s² 기준 또는 실험 튜닝값",
            "neighbor_type": "버스/트럭",
            "neighbor_v2x": "불가능",
            "neighbor_relative_position": "좌측방",
            "neighbor_relative_gap": "1.2s",
            "neighbor_longitudinal_motion": "정지",
            "neighbor_speed": "0km/h",
            "traffic_density": "20pcpkmpl 정의서 기준, 실험에서는 필요 시 축소",
        }
    )
    return values


def _scenario_2_values(reference_speed_kmh: float, detected: dict[str, Any]) -> dict[str, str]:
    values = _base_values(reference_speed_kmh, detected)
    speed = detected.get("speed_kmh") or reference_speed_kmh
    values.update(
        {
            "road_segment_kind": "2차로 직선 주행 구간",
            "road_alignment_kind": "직선부",
            "lane_count": "2",
            "crosswalk": "없음",
            "road_speed_limit": f"{reference_speed_kmh:g}km/h",
            "incident": "정지 선행차량 회피/차선변경 이벤트",
            "incident_lane": "Ego 주행 차로",
            "incident_object": "정지 차량",
            "ego_initial_lane": "1",
            "ego_lane": "1 -> 2",
            "ego_motion": "선행차량 인지 후 차선변경",
            "ego_speed": f"{speed:g}km/h",
            "ego_occlusion_presence": "있음",
            "ego_occlusion_cause": "선행 차량 또는 주변 차량에 의한 정지차량 차폐",
            "ego_occlusion_location": "전방",
            "actor_type": "정지 차량 또는 차선변경 위험 객체",
            "actor_initial_lane": "1",
            "actor_initial_relative_position": "전방",
            "actor_initial_longitudinal_gap": "YAML spawn_position 기준 산출",
            "actor_initial_motion": "정지",
            "actor_lane": "1",
            "actor_relative_position": "전방",
            "actor_relative_gap": "실험 로그 기준 산출",
            "actor_lateral_motion": "없음",
            "actor_longitudinal_motion": "정지",
            "actor_speed": "0km/h",
            "actor_acceleration": "0m/s²",
            "neighbor_type": "선행 차량/일반 차량",
            "neighbor_v2x": "V2X 조건에서 바로 앞 차량 통신 가능",
            "neighbor_lane": "1",
            "neighbor_relative_position": "전방",
            "neighbor_relative_gap": "YAML spawn_position 기준 산출",
            "neighbor_lateral_motion": "차선변경",
            "neighbor_longitudinal_motion": "등속 또는 추월",
            "neighbor_speed": "YAML max_speed 기준",
            "traffic_density": "1대 배경교통",
            "visibility_reduction_cause": "선행차량 차폐",
        }
    )
    return values


def _scenario_metadata(scenario_id: str, scenario_type: str) -> dict[str, str]:
    if scenario_id == "scenario_2" or scenario_type == "highway_cutout":
        return {
            "유형": "자율주행차량 주행",
            "위치": "2차로 직선 도로 / 고속 주행 구간",
            "목적": "정지 선행차량 및 차선변경 상황에서 인지, 회피, 제어 성능 평가",
            "전체 상황도": "OpenCDA/CARLA top-view 또는 시나리오2 시각화 영상",
            "시나리오 상세 설명": (
                "2차로 직선 도로에서 Ego 차량이 주행 중 전방 정지차량 또는 선행차량 차폐 상황을 만나며, "
                "V2X 조건에서는 선행차량/위험 객체 정보를 먼저 공유받아 차선변경을 수행하고, "
                "No V2X 조건에서는 센서 인지 이후 회피 여부를 평가한다."
            ),
            "인지 음영 원인": "선행 차량 또는 주변 차량에 의한 전방 정지차량 차폐",
        }

    if scenario_id == "custom" or scenario_type == "custom":
        return {
            "유형": "자율주행차량 주행",
            "위치": "자연어 요청 기반 사용자 정의 시험 구간",
            "목적": "요청된 도로/객체/센서/통신 조건에서 공통 KPI 평가",
            "전체 상황도": "Agent가 생성한 정의서 및 실행 후 OpenCDA/CARLA top-view",
            "시나리오 상세 설명": (
                "사용자 자연어 요청에서 추출 가능한 도로, 차량, 센서, V2X 조건을 우선 반영하고, "
                "누락된 값은 일반 시험 가정값으로 보완한다. 이후 YAML/PY 매핑이 지정되면 해당 실행 파일로 실험을 수행한다."
            ),
            "인지 음영 원인": "요청에 명시된 차폐/가시성 조건 또는 기본 차량 차폐 가정",
        }

    return {
        "유형": "자율주행차량 주행",
        "위치": "비신호 4지 교차로",
        "목적": "목표 자동차에 대한 인지 및 대응 평가",
        "전체 상황도": "OpenCDA/CARLA top-view 또는 시나리오1 비교 영상",
        "시나리오 상세 설명": (
            "비신호 4지 교차로에서 Ego 차량이 정지선으로 접근하는 동안 정차 차량에 의해 좌측 전방 시야가 차폐되고, "
            "좌측에서 접근하는 Actor 차량과의 상호작용을 통해 V2X 사전인지, 감속, 양보, 재출발 성능을 평가한다."
        ),
        "인지 음영 원인": "정차 버스/트럭에 의한 좌측 전방 시야 차단",
    }


def _open_items(rows: Iterable[dict[str, str]]) -> list[str]:
    markers = ("미정", "시나리오별 설정", "로그 기준 산출", "YAML spawn_position 기준 산출")
    items = []
    for row in rows:
        value = row.get("시험 시나리오", "")
        if any(marker in value for marker in markers):
            items.append(f"{row.get('항목') or row.get('레이어')} - {row.get('요소')}: {value}")
    return items


def build_scenario_definition_form(
    *,
    scenario_id: str,
    scenario_type: str,
    natural_language_request: str,
    reference_speed_kmh: float,
    detected_values: dict[str, Any] | None = None,
    autofill_values: dict[str, str] | None = None,
    autofill_sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a scenario definition form matching `(과-19)시나리오 정의서 (2).pdf`.

    The form skeleton is scenario-independent. Scenario 1/2 only change the values in
    the `시험 시나리오` column.
    """

    detected = detected_values or {}
    if scenario_id == "scenario_2" or scenario_type == "highway_cutout":
        values = _scenario_2_values(reference_speed_kmh, detected)
    elif scenario_id == "scenario_1" or scenario_type == "intersection_occlusion":
        values = _scenario_1_values(reference_speed_kmh, detected)
    else:
        values = _base_values(reference_speed_kmh, detected)
    if autofill_values:
        values.update({key: value for key, value in autofill_values.items() if value not in (None, "")})
    metadata = _scenario_metadata(scenario_id, scenario_type)

    rows = []
    for template_row in DEFINITION_ROWS:
        key = template_row["value_key"]
        rows.append(
            {
                "레이어": template_row["레이어"],
                "항목": template_row["항목"],
                "요소": template_row["요소"],
                "설명": template_row["설명"],
                "시험 시나리오": values.get(key, "미정"),
            }
        )

    return {
        "definition_format": SCENARIO_DEFINITION_FORMAT,
        "source_pdf": SCENARIO_DEFINITION_SOURCE,
        "scenario_type": metadata,
        "table_columns": TABLE_COLUMNS,
        "rows": rows,
        "open_items": _open_items(rows),
        "autofill": autofill_sources or {"values": autofill_values or {}, "sources": [], "notes": []},
        "generation_note": (
            "본 정의서는 첨부 PDF의 5열 표 구조(레이어/항목/요소/설명/시험 시나리오)를 따르며, "
            "자연어 요청에서 확정되지 않은 값은 시나리오 YAML에서 우선 자동 보완하고, "
            "실험 이후에만 알 수 있는 값은 실행 로그로 후속 보완한다."
        ),
        "natural_language_request": natural_language_request,
    }
