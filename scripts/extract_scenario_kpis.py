#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Extract scenario-definition values and KPI metrics from OpenCDA YAML dumps.

The script is intentionally independent from CARLA/OpenCDA runtime entrypoints.
It only needs:
  1. scenario config YAML files under opencda/scenario_testing/config_yaml
  2. optional data_dumping/<scenario_title>/<run_time>/*.yaml logs

Outputs are written as CSV and Markdown so the results can be reviewed without
rerunning the simulator.
"""

from __future__ import annotations

import argparse
import csv
import glob
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml


Vec2 = Tuple[float, float]


@dataclass
class ActorFrame:
    actor_id: int
    frame: int
    time_s: float
    x: float
    y: float
    speed_kmh: float
    detected_ids: List[int]


@dataclass
class ActorMeta:
    actor_id: int
    name: str
    bp_id: str
    x: float
    y: float
    extent_x: float
    extent_y: float

    @property
    def radius_m(self) -> float:
        return math.hypot(self.extent_x, self.extent_y)


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def list_get(values: Any, index: int, default: float = 0.0) -> float:
    if not isinstance(values, list) or index >= len(values):
        return default
    return safe_float(values[index], default)


def flatten_dict(data: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in data.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(flatten_dict(value, name))
        else:
            out[name] = value
    return out


def iter_leaf_values(data: Any, prefix: str = "") -> Iterable[Tuple[str, Any]]:
    if isinstance(data, dict):
        for key, value in data.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            yield from iter_leaf_values(value, name)
        return

    if isinstance(data, list):
        if not data or all(not isinstance(value, (dict, list)) for value in data):
            yield prefix, data
            return
        for index, value in enumerate(data):
            yield from iter_leaf_values(value, f"{prefix}[{index}]")
        return

    yield prefix, data


def normalize_column_path(path: str) -> str:
    parts = []
    for part in path.split("."):
        parts.append("{actor_id}" if re.fullmatch(r"-?\d+", part) else part)
    return ".".join(parts)


def value_type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if value is None:
        return "null"
    return type(value).__name__


def format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, list):
        return "[" + ", ".join(format_value(v) for v in value) + "]"
    if value is None:
        return ""
    return str(value)


def actor_configs(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(config.get("scenario", {}).get("single_cav_list", []) or [])


def scenario_title(config: Dict[str, Any], fallback: str) -> str:
    return (
        config.get("vehicle_base", {})
        .get("datadump", {})
        .get("title", fallback)
    )


def extract_definition_rows(config_path: Path, config: Dict[str, Any]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    title = scenario_title(config, config_path.stem)
    definition_rows: List[Dict[str, str]] = []

    def add(layer: str, field: str, value: Any, source: str = "config_yaml") -> None:
        definition_rows.append(
            {
                "scenario": title,
                "source_file": str(config_path),
                "pegasus_layer": layer,
                "field": field,
                "value": format_value(value),
                "source": source,
            }
        )

    world = config.get("world", {}) or {}
    add("L1_road_network", "map", "Town04_inferred_from_scenario_design")
    add("L1_road_network", "road_context", "unsignalized_4way_intersection")
    add("L2_traffic_infrastructure", "traffic_signal", "none_or_ignored")
    add("L3_temporary_modification", "occlusion_source", "large_neighboring_vehicle")
    add("L5_environment", "fixed_delta_seconds", world.get("fixed_delta_seconds"))
    add("L5_environment", "seed", world.get("seed"))
    for key, value in (world.get("weather", {}) or {}).items():
        add("L5_environment", f"weather.{key}", value)

    base = config.get("vehicle_base", {}) or {}
    add("L6_digital_information", "base_v2x.enabled", base.get("v2x", {}).get("enabled"))
    add(
        "L6_digital_information",
        "base_v2x.communication_range",
        base.get("v2x", {}).get("communication_range"),
    )
    add("L6_digital_information", "datadump.title", title)

    actor_rows: List[Dict[str, str]] = []
    for idx, actor in enumerate(actor_configs(config)):
        name = str(actor.get("name", f"actor_{idx}"))
        spawn = actor.get("spawn_position", [])
        destination = actor.get("destination", [])
        vehicle_type = actor.get("vehicle_type", "vehicle.lincoln.mkz_2017")
        v2x = actor.get("v2x", {})
        perception = actor.get("sensing", {}).get("perception", {})
        actor_rows.append(
            {
                "scenario": title,
                "actor_name": name,
                "role": infer_actor_role(name, vehicle_type),
                "vehicle_type": str(vehicle_type),
                "spawn_x": format_value(list_get(spawn, 0)),
                "spawn_y": format_value(list_get(spawn, 1)),
                "spawn_z": format_value(list_get(spawn, 2)),
                "spawn_yaw": format_value(list_get(spawn, 4)),
                "destination_x": format_value(list_get(destination, 0)),
                "destination_y": format_value(list_get(destination, 1)),
                "v2x_enabled": format_value(v2x.get("enabled", base.get("v2x", {}).get("enabled"))),
                "communication_range_m": format_value(v2x.get("communication_range", base.get("v2x", {}).get("communication_range"))),
                "perception_connected": format_value(perception.get("connected")),
                "perception_activate": format_value(perception.get("activate")),
                "lidar_range_m": format_value((perception.get("lidar", {}) or {}).get("range")),
            }
        )
        add("L4_moving_objects", f"actor.{name}.vehicle_type", vehicle_type)
        add("L4_moving_objects", f"actor.{name}.spawn_position", spawn)
        add("L4_moving_objects", f"actor.{name}.destination", destination)
        add("L6_digital_information", f"actor.{name}.v2x.enabled", v2x.get("enabled"))
        add("L6_digital_information", f"actor.{name}.perception.connected", perception.get("connected"))

    rsu_list = config.get("scenario", {}).get("rsu_list", []) or []
    for rsu in rsu_list:
        name = str(rsu.get("name", "rsu"))
        add("L6_digital_information", f"rsu.{name}.spawn_position", rsu.get("spawn_position"))

    return definition_rows, actor_rows


def infer_actor_role(name: str, vehicle_type: str) -> str:
    lowered = name.lower()
    vehicle = vehicle_type.lower()
    if lowered == "ego":
        return "ego_vehicle"
    if lowered == "subject":
        return "conflict_actor"
    if lowered == "neighboring" or "fusorosa" in vehicle or "bus" in vehicle:
        return "occluding_vehicle"
    return "background_or_test_actor"


def load_first_vehicle_meta(record: Dict[str, Any], actor_id: int) -> Optional[ActorMeta]:
    for section in ("total_vehicles", "vehicles"):
        vehicles = record.get(section, {}) or {}
        for key, value in vehicles.items():
            try:
                key_id = int(key)
            except (TypeError, ValueError):
                continue
            if key_id != actor_id:
                continue
            loc = value.get("location", [])
            extent = value.get("extent", [])
            return ActorMeta(
                actor_id=actor_id,
                name=str(actor_id),
                bp_id=str(value.get("bp_id", "")),
                x=list_get(loc, 0),
                y=list_get(loc, 1),
                extent_x=list_get(extent, 0, 2.0),
                extent_y=list_get(extent, 1, 1.0),
            )
    return None


def iter_yaml_files(folder: Path) -> Iterable[Path]:
    return sorted(folder.glob("*.yaml"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0)


def load_run_frames(run_dir: Path, dt_s: float) -> Tuple[Dict[int, List[ActorFrame]], Dict[int, ActorMeta]]:
    frames: Dict[int, List[ActorFrame]] = {}
    meta: Dict[int, ActorMeta] = {}

    actor_dirs = [p for p in run_dir.iterdir() if p.is_dir()]
    for actor_dir in actor_dirs:
        try:
            actor_id = int(actor_dir.name)
        except ValueError:
            continue

        actor_frames: List[ActorFrame] = []
        for path in iter_yaml_files(actor_dir):
            record = load_yaml(path)
            frame = int(path.stem)
            if actor_id not in meta:
                found = load_first_vehicle_meta(record, actor_id)
                if found:
                    meta[actor_id] = found

            true_pos = record.get("true_ego_pos", [])
            detected_ids = []
            for key in (record.get("vehicles", {}) or {}).keys():
                try:
                    detected_ids.append(int(key))
                except (TypeError, ValueError):
                    continue

            actor_frames.append(
                ActorFrame(
                    actor_id=actor_id,
                    frame=frame,
                    time_s=(frame - 1) * dt_s,
                    x=list_get(true_pos, 0),
                    y=list_get(true_pos, 1),
                    speed_kmh=safe_float(record.get("ego_speed")),
                    detected_ids=detected_ids,
                )
            )

            for section in ("total_vehicles", "vehicles"):
                for key, vehicle in (record.get(section, {}) or {}).items():
                    try:
                        vehicle_id = int(key)
                    except (TypeError, ValueError):
                        continue
                    if vehicle_id in meta:
                        continue
                    loc = vehicle.get("location", [])
                    extent = vehicle.get("extent", [])
                    meta[vehicle_id] = ActorMeta(
                        actor_id=vehicle_id,
                        name=str(vehicle_id),
                        bp_id=str(vehicle.get("bp_id", "")),
                        x=list_get(loc, 0),
                        y=list_get(loc, 1),
                        extent_x=list_get(extent, 0, 2.0),
                        extent_y=list_get(extent, 1, 1.0),
                    )

        if actor_frames:
            frames[actor_id] = actor_frames

    return frames, meta


def match_actor_names(config: Dict[str, Any], meta: Dict[int, ActorMeta], frames: Dict[int, List[ActorFrame]]) -> Dict[str, int]:
    configs = actor_configs(config)
    available_ids = set(frames.keys()) | set(meta.keys())
    mapping: Dict[str, int] = {}
    used: set[int] = set()

    for actor in configs:
        name = str(actor.get("name", ""))
        spawn = actor.get("spawn_position", [])
        sx, sy = list_get(spawn, 0), list_get(spawn, 1)
        best_id = None
        best_dist = float("inf")
        for actor_id in available_ids:
            if actor_id in used or actor_id < 0:
                continue
            candidate = meta.get(actor_id)
            if candidate is not None:
                cx, cy = candidate.x, candidate.y
            elif actor_id in frames and frames[actor_id]:
                cx, cy = frames[actor_id][0].x, frames[actor_id][0].y
            else:
                continue
            dist = math.hypot(cx - sx, cy - sy)
            if dist < best_dist:
                best_dist = dist
                best_id = actor_id
        if best_id is not None:
            mapping[name] = best_id
            used.add(best_id)
            if best_id in meta:
                meta[best_id].name = name

    return mapping


def series_by_frame(frames: List[ActorFrame]) -> Dict[int, ActorFrame]:
    return {frame.frame: frame for frame in frames}


def estimate_velocities(points: Dict[int, ActorFrame], dt_s: float) -> Dict[int, Vec2]:
    velocities: Dict[int, Vec2] = {}
    sorted_frames = sorted(points)
    previous_frame: Optional[int] = None
    for frame in sorted_frames:
        if previous_frame is None:
            previous_frame = frame
            continue
        prev = points[previous_frame]
        cur = points[frame]
        elapsed = max((frame - previous_frame) * dt_s, dt_s)
        velocities[frame] = ((cur.x - prev.x) / elapsed, (cur.y - prev.y) / elapsed)
        previous_frame = frame
    return velocities


def first_detection_time(ego_frames: List[ActorFrame], subject_id: int) -> Tuple[Optional[float], Optional[int], float]:
    detected_count = 0
    first_time = None
    first_frame = None
    for frame in ego_frames:
        if subject_id in frame.detected_ids:
            detected_count += 1
            if first_time is None:
                first_time = frame.time_s
                first_frame = frame.frame
    ratio = detected_count / len(ego_frames) if ego_frames else 0.0
    return first_time, first_frame, ratio


def compute_progress(config: Dict[str, Any], ego_frames: List[ActorFrame]) -> float:
    ego_config = next((a for a in actor_configs(config) if str(a.get("name", "")).lower() == "ego"), None)
    if not ego_config or not ego_frames:
        return 0.0
    spawn = ego_config.get("spawn_position", [])
    dest = ego_config.get("destination", [])
    sx, sy = list_get(spawn, 0), list_get(spawn, 1)
    dx, dy = list_get(dest, 0), list_get(dest, 1)
    route_x, route_y = dx - sx, dy - sy
    route_len = math.hypot(route_x, route_y)
    if route_len <= 1e-6:
        return 0.0
    final = ego_frames[-1]
    progress = ((final.x - sx) * route_x + (final.y - sy) * route_y) / (route_len * route_len)
    return max(0.0, min(1.0, progress))


def acceleration_and_jerk(frames: List[ActorFrame], dt_s: float) -> Tuple[float, float, float, float]:
    if len(frames) < 3:
        return 0.0, 0.0, 0.0, 0.0
    speeds = [f.speed_kmh / 3.6 for f in frames]
    accel = [(speeds[i] - speeds[i - 1]) / dt_s for i in range(1, len(speeds))]
    jerk = [(accel[i] - accel[i - 1]) / dt_s for i in range(1, len(accel))]
    avg_speed = sum(speeds) / len(speeds)
    max_decel = max(0.0, -min(accel)) if accel else 0.0
    max_accel = max(accel) if accel else 0.0
    jerk_rms = math.sqrt(sum(j * j for j in jerk) / len(jerk)) if jerk else 0.0
    return avg_speed, max_decel, max_accel, jerk_rms


def score_perception(lead_time: Optional[float], detected_ratio: float) -> float:
    if lead_time is None:
        lead_score = 0.0
    elif lead_time >= 2.0:
        lead_score = 12.0
    elif lead_time >= 1.0:
        lead_score = 10.0
    elif lead_time >= 0.5:
        lead_score = 8.0
    elif lead_time >= 0.0:
        lead_score = 5.0
    else:
        lead_score = 2.0
    ratio_score = min(3.0, max(0.0, detected_ratio * 3.0))
    return min(15.0, lead_score + ratio_score)


def score_safety(min_clearance: Optional[float], min_ttc: Optional[float]) -> float:
    if min_clearance is None:
        return 0.0
    if min_clearance <= 0:
        clearance_score = 0.0
    elif min_clearance >= 5:
        clearance_score = 14.0
    elif min_clearance >= 2:
        clearance_score = 11.0
    elif min_clearance >= 1:
        clearance_score = 8.0
    else:
        clearance_score = 4.0

    if min_ttc is None:
        ttc_score = 3.0
    elif min_ttc >= 3.0:
        ttc_score = 6.0
    elif min_ttc >= 1.5:
        ttc_score = 4.0
    elif min_ttc >= 0.5:
        ttc_score = 2.0
    else:
        ttc_score = 0.0
    return min(20.0, clearance_score + ttc_score)


def score_behavior(max_decel: float, jerk_rms: float) -> float:
    decel_score = 5.0 if max_decel <= 4 else 3.0 if max_decel <= 8 else 1.0
    jerk_score = 5.0 if jerk_rms <= 10 else 3.0 if jerk_rms <= 30 else 1.0
    return decel_score + jerk_score


def score_computation(frames_count: int, expected_actor_count: int, actual_actor_count: int) -> float:
    if frames_count <= 0:
        return 0.0
    actor_ratio = min(1.0, actual_actor_count / max(1, expected_actor_count))
    frame_score = 1.0 if frames_count >= 100 else frames_count / 100.0
    return round(5.0 * min(actor_ratio, frame_score), 3)


def score_traffic(progress_ratio: float, collision: bool) -> float:
    score = 10.0 * max(0.0, min(1.0, progress_ratio))
    if collision:
        score = min(score, 3.0)
    return score


def score_environment(config: Dict[str, Any]) -> float:
    score = 0.0
    world = config.get("world", {}) or {}
    actors = actor_configs(config)
    if "fixed_delta_seconds" in world:
        score += 2.0
    if "weather" in world or "seed" in world:
        score += 2.0
    if any(infer_actor_role(str(a.get("name", "")), str(a.get("vehicle_type", ""))) == "occluding_vehicle" for a in actors):
        score += 2.0
    if any(str(a.get("name", "")).lower() == "subject" for a in actors):
        score += 2.0
    if "v2x" in (config.get("vehicle_base", {}) or {}):
        score += 2.0
    return score


def compute_kpis_for_run(
    config_path: Path,
    config: Dict[str, Any],
    run_dir: Path,
    warning_clearance_m: float,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    title = scenario_title(config, config_path.stem)
    protocol_path = run_dir / "data_protocol.yaml"
    protocol = load_yaml(protocol_path) if protocol_path.exists() else config
    dt_s = safe_float((protocol.get("world", {}) or {}).get("fixed_delta_seconds"), 0.05)
    frames, meta = load_run_frames(run_dir, dt_s)
    name_to_id = match_actor_names(protocol, meta, frames)

    ego_id = name_to_id.get("ego")
    subject_id = name_to_id.get("subject")
    status = "ok"
    notes = []
    if ego_id is None:
        status = "missing_ego"
        notes.append("ego actor could not be matched")
    if subject_id is None:
        status = "missing_subject"
        notes.append("subject actor could not be matched")

    run_rows: List[Dict[str, Any]] = []
    for actor_id, actor_frames in frames.items():
        actor_name = meta.get(actor_id, ActorMeta(actor_id, str(actor_id), "", 0, 0, 0, 0)).name
        if actor_id < 0:
            actor_name = "rsu"
        run_rows.append(
            {
                "scenario": title,
                "run": run_dir.name,
                "actor_id": actor_id,
                "actor_name": actor_name,
                "frames": len(actor_frames),
                "start_time_s": actor_frames[0].time_s if actor_frames else "",
                "end_time_s": actor_frames[-1].time_s if actor_frames else "",
            }
        )

    result: Dict[str, Any] = {
        "scenario": title,
        "config_file": str(config_path),
        "run": run_dir.name,
        "run_dir": str(run_dir),
        "status": status,
        "dt_s": dt_s,
        "frames": max((len(v) for v in frames.values()), default=0),
        "duration_s": "",
        "ego_id": ego_id if ego_id is not None else "",
        "subject_id": subject_id if subject_id is not None else "",
        "first_detection_frame": "",
        "first_detection_time_s": "",
        "detected_frame_ratio": "",
        "first_warning_frame": "",
        "first_warning_time_s": "",
        "first_collision_frame": "",
        "first_collision_time_s": "",
        "detection_lead_to_warning_s": "",
        "detection_lead_to_collision_s": "",
        "min_center_distance_m": "",
        "min_bbox_clearance_m": "",
        "min_ttc_s": "",
        "ego_avg_speed_mps": "",
        "ego_max_decel_mps2": "",
        "ego_max_accel_mps2": "",
        "ego_jerk_rms_mps3": "",
        "ego_progress_ratio": "",
        "event_outcome": "",
        "notes": "; ".join(notes),
    }

    if status != "ok":
        score = empty_score_row(title, run_dir.name, result)
        return result, score, run_rows

    ego_frames = frames.get(ego_id, [])
    subject_frames = frames.get(subject_id, [])
    result["duration_s"] = (max((f.time_s for values in frames.values() for f in values), default=0.0))

    ego_by_frame = series_by_frame(ego_frames)
    subject_by_frame = series_by_frame(subject_frames)
    common_frames = sorted(set(ego_by_frame) & set(subject_by_frame))

    ego_radius = meta.get(ego_id, ActorMeta(ego_id, "ego", "", 0, 0, 2.0, 1.0)).radius_m
    subject_radius = meta.get(subject_id, ActorMeta(subject_id, "subject", "", 0, 0, 2.0, 1.0)).radius_m
    combined_radius = ego_radius + subject_radius

    min_dist = None
    min_clearance = None
    first_warning = None
    first_collision = None

    ego_vel = estimate_velocities(ego_by_frame, dt_s)
    subject_vel = estimate_velocities(subject_by_frame, dt_s)
    min_ttc = None

    for frame in common_frames:
        ego = ego_by_frame[frame]
        subject = subject_by_frame[frame]
        dist = math.hypot(subject.x - ego.x, subject.y - ego.y)
        clearance = dist - combined_radius
        if min_dist is None or dist < min_dist:
            min_dist = dist
        if min_clearance is None or clearance < min_clearance:
            min_clearance = clearance
        if first_warning is None and clearance <= warning_clearance_m:
            first_warning = frame
        if first_collision is None and clearance <= 0:
            first_collision = frame

        if frame in ego_vel and frame in subject_vel and clearance > 0:
            rx, ry = subject.x - ego.x, subject.y - ego.y
            rvx = subject_vel[frame][0] - ego_vel[frame][0]
            rvy = subject_vel[frame][1] - ego_vel[frame][1]
            center_dist = max(math.hypot(rx, ry), 1e-6)
            closing_rate = -((rx * rvx + ry * rvy) / center_dist)
            if closing_rate > 1e-3:
                ttc = clearance / closing_rate
                if min_ttc is None or ttc < min_ttc:
                    min_ttc = ttc

    first_detection_s, first_detection_frame, detected_ratio = first_detection_time(ego_frames, subject_id)
    warning_time = (first_warning - 1) * dt_s if first_warning is not None else None
    collision_time = (first_collision - 1) * dt_s if first_collision is not None else None

    avg_speed, max_decel, max_accel, jerk_rms = acceleration_and_jerk(ego_frames, dt_s)
    progress = compute_progress(protocol, ego_frames)
    collision = first_collision is not None

    result.update(
        {
            "first_detection_frame": first_detection_frame if first_detection_frame is not None else "",
            "first_detection_time_s": first_detection_s if first_detection_s is not None else "",
            "detected_frame_ratio": detected_ratio,
            "first_warning_frame": first_warning if first_warning is not None else "",
            "first_warning_time_s": warning_time if warning_time is not None else "",
            "first_collision_frame": first_collision if first_collision is not None else "",
            "first_collision_time_s": collision_time if collision_time is not None else "",
            "detection_lead_to_warning_s": (warning_time - first_detection_s) if warning_time is not None and first_detection_s is not None else "",
            "detection_lead_to_collision_s": (collision_time - first_detection_s) if collision_time is not None and first_detection_s is not None else "",
            "min_center_distance_m": min_dist if min_dist is not None else "",
            "min_bbox_clearance_m": min_clearance if min_clearance is not None else "",
            "min_ttc_s": min_ttc if min_ttc is not None else "",
            "ego_avg_speed_mps": avg_speed,
            "ego_max_decel_mps2": max_decel,
            "ego_max_accel_mps2": max_accel,
            "ego_jerk_rms_mps3": jerk_rms,
            "ego_progress_ratio": progress,
            "event_outcome": "collision_inferred" if collision else "near_collision" if first_warning is not None else "clear",
        }
    )

    score = {
        "scenario": title,
        "run": run_dir.name,
        "perception_score_15": score_perception(
            result["detection_lead_to_warning_s"]
            if result["detection_lead_to_warning_s"] != ""
            else result["detection_lead_to_collision_s"]
            if result["detection_lead_to_collision_s"] != ""
            else None,
            detected_ratio,
        ),
        "safety_score_20": score_safety(min_clearance, min_ttc),
        "behavior_score_10": score_behavior(max_decel, jerk_rms),
        "computation_score_5": score_computation(
            int(result["frames"]),
            len(actor_configs(protocol)),
            len([actor_id for actor_id in frames if actor_id >= 0]),
        ),
        "traffic_score_10": score_traffic(progress, collision),
        "environment_score_10": score_environment(protocol),
        "event_outcome": result["event_outcome"],
    }
    score["total_score_70"] = sum(
        float(score[key])
        for key in (
            "perception_score_15",
            "safety_score_20",
            "behavior_score_10",
            "computation_score_5",
            "traffic_score_10",
            "environment_score_10",
        )
    )
    return result, score, run_rows


def empty_score_row(scenario: str, run: str, result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "scenario": scenario,
        "run": run,
        "perception_score_15": 0,
        "safety_score_20": 0,
        "behavior_score_10": 0,
        "computation_score_5": 0,
        "traffic_score_10": 0,
        "environment_score_10": 0,
        "total_score_70": 0,
        "event_outcome": result.get("event_outcome", ""),
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: format_value(row.get(key, "")) for key in fieldnames})


def write_markdown(path: Path, kpi_rows: List[Dict[str, Any]], score_rows: List[Dict[str, Any]]) -> None:
    lines = [
        "# Scenario Definition and KPI Summary",
        "",
        "This report is generated from YAML scenario definitions and saved OpenCDA data dumps.",
        "It does not require CARLA or opencda.py to be runnable.",
        "",
        "## KPI Assumptions",
        "",
        "- Pair of interest: `ego` vs `subject`.",
        "- Occluding vehicle: actor named `neighboring` or bus-like vehicle type.",
        "- Collision is inferred when 2D center distance is less than combined bounding-circle radii.",
        "- Warning/near-collision threshold defaults to 2.0 m bounding clearance.",
        "- `vehicles` in the ego dump is treated as perceived/available objects; `total_vehicles` is ground truth.",
        "- Scores are helper scores for comparison, not a formal safety certification.",
        "",
        "## KPI Summary",
        "",
    ]
    lines.extend(markdown_table(kpi_rows))
    lines.extend(["", "## Score Summary", ""])
    lines.extend(markdown_table(score_rows))
    path.write_text("\n".join(lines), encoding="utf-8")


def markdown_table(rows: List[Dict[str, Any]], max_cols: int = 12) -> List[str]:
    if not rows:
        return ["No rows."]
    fieldnames = list(rows[0].keys())[:max_cols]
    output = [
        "| " + " | ".join(fieldnames) + " |",
        "| " + " | ".join(["---"] * len(fieldnames)) + " |",
    ]
    for row in rows:
        output.append("| " + " | ".join(format_value(row.get(key, "")) for key in fieldnames) + " |")
    return output


def find_config_paths(patterns: List[str]) -> List[Path]:
    paths: List[Path] = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            paths.extend(Path(m) for m in matches)
        else:
            paths.append(Path(pattern))
    unique = []
    seen = set()
    for path in paths:
        resolved = str(path.resolve())
        if resolved not in seen and path.exists():
            unique.append(path)
            seen.add(resolved)
    return unique


def find_runs(data_root: Path, title: str) -> List[Path]:
    scenario_dir = data_root / title
    if not scenario_dir.exists():
        return []
    return sorted([p for p in scenario_dir.iterdir() if p.is_dir()])


def vehicle_actor_dirs(run_dir: Path) -> List[Path]:
    actor_dirs: List[Path] = []
    for path in run_dir.iterdir():
        if not path.is_dir():
            continue
        try:
            actor_id = int(path.name)
        except ValueError:
            continue
        if actor_id < 0:
            continue
        if any(path.glob("*.yaml")):
            actor_dirs.append(path)
    return actor_dirs


def is_complete_vehicle_run(run_dir: Path, config: Dict[str, Any]) -> bool:
    expected = len(actor_configs(config))
    return (run_dir / "data_protocol.yaml").exists() and len(vehicle_actor_dirs(run_dir)) >= expected


def latest_complete_runs(runs: List[Path], config: Dict[str, Any]) -> List[Path]:
    complete = [run for run in runs if is_complete_vehicle_run(run, config)]
    if not complete:
        return []
    return [sorted(complete, key=lambda path: path.name)[-1]]


def collect_data_metadata(
    config_path: Path,
    config: Dict[str, Any],
    runs: List[Path],
) -> List[Dict[str, Any]]:
    title = scenario_title(config, config_path.stem)
    rows: List[Dict[str, Any]] = []
    seen = set()

    def add(
        source_type: str,
        path: str,
        value: Any,
        source_file: Path,
        run_name: str = "",
        actor_dir: str = "",
    ) -> None:
        if not path:
            return
        normalized = normalize_column_path(path)
        key = (title, source_type, normalized)
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "scenario": title,
                "run": run_name,
                "source_type": source_type,
                "actor_dir": actor_dir,
                "column_path": normalized,
                "example_path": path,
                "value_type": value_type_name(value),
                "example_value": format_value(value),
                "source_file": str(source_file),
            }
        )

    for path, value in iter_leaf_values(config):
        add("config_yaml", path, value, config_path)

    for run_dir in runs:
        protocol_path = run_dir / "data_protocol.yaml"
        if protocol_path.exists():
            protocol = load_yaml(protocol_path)
            for path, value in iter_leaf_values(protocol):
                add("data_protocol", path, value, protocol_path, run_dir.name)

        for actor_dir in sorted(run_dir.iterdir(), key=lambda p: p.name):
            if not actor_dir.is_dir():
                continue
            sample_files = list(iter_yaml_files(actor_dir))
            if not sample_files:
                continue
            sample_path = sample_files[0]
            record = load_yaml(sample_path)
            for path, value in iter_leaf_values(record):
                add("frame_yaml", path, value, sample_path, run_dir.name, actor_dir.name)

    return rows


def kpi_requirement_rows(title: str) -> List[Dict[str, str]]:
    rows = [
        (
            "perception",
            "first_detection_time_s / first_detection_frame / detected_frame_ratio",
            "ego frame `vehicles.{subject_id}` keys, matched ego/subject actor IDs, `world.fixed_delta_seconds`",
            "frame_yaml, data_protocol, config_yaml",
            "Subject presence in ego perceived vehicles is treated as detection/V2X availability.",
        ),
        (
            "safety",
            "first_warning_time_s / first_warning_frame",
            "ego and subject `true_ego_pos`, `total_vehicles.{actor_id}.extent`, warning clearance threshold",
            "frame_yaml, CLI argument",
            "Default warning clearance is 2.0 m bounding clearance.",
        ),
        (
            "safety",
            "first_collision_time_s / first_collision_frame / event_outcome",
            "ego and subject `true_ego_pos`, `total_vehicles.{actor_id}.extent`",
            "frame_yaml",
            "Collision is inferred when bounding-circle clearance is less than or equal to 0.",
        ),
        (
            "safety",
            "min_center_distance_m / min_bbox_clearance_m",
            "ego and subject `true_ego_pos`, vehicle extents",
            "frame_yaml",
            "Center distance is raw XY distance; clearance subtracts estimated bounding radii.",
        ),
        (
            "safety",
            "min_ttc_s",
            "sequential ego/subject positions and `world.fixed_delta_seconds`",
            "frame_yaml, data_protocol",
            "TTC is calculated only while actors are closing and clearance is positive.",
        ),
        (
            "behavior",
            "ego_avg_speed_mps / ego_max_decel_mps2 / ego_max_accel_mps2 / ego_jerk_rms_mps3",
            "ego `ego_speed` time series and `world.fixed_delta_seconds`",
            "frame_yaml, data_protocol",
            "OpenCDA speed is converted from km/h to m/s before acceleration and jerk.",
        ),
        (
            "traffic_efficiency",
            "ego_progress_ratio",
            "ego config `spawn_position`, `destination`, final ego `true_ego_pos`",
            "config_yaml, frame_yaml",
            "Progress is projected onto the configured route and clipped to 0..1.",
        ),
        (
            "scoring",
            "perception/safety/behavior/computation/traffic/environment/total scores",
            "computed KPIs, actor count, frame count, scenario weather/seed/V2X/occluder settings",
            "kpi_summary, config_yaml, data_protocol",
            "Scores are comparative helper values, not formal certification scores.",
        ),
    ]
    return [
        {
            "scenario": title,
            "kpi_group": group,
            "kpi_field": field,
            "required_data_elements": elements,
            "source": source,
            "notes": notes,
        }
        for group, field, elements, source, notes in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        action="append",
        default=None,
        help="Scenario config YAML or glob. Can be used multiple times.",
    )
    parser.add_argument(
        "--data-root",
        default="data_dumping",
        help="Root folder containing data_dumping/<scenario>/<run>.",
    )
    parser.add_argument(
        "--output-dir",
        default="evaluation_outputs/scenario_definition_kpi",
        help="Folder for generated CSV/Markdown outputs.",
    )
    parser.add_argument(
        "--warning-clearance-m",
        type=float,
        default=2.0,
        help="Bounding clearance threshold for near-collision/warning KPI.",
    )
    parser.add_argument(
        "--latest-complete-only",
        action="store_true",
        help="Use only the latest run that contains data_protocol.yaml and all configured vehicle actor dumps.",
    )
    args = parser.parse_args()

    patterns = args.config or ["opencda/scenario_testing/config_yaml/scenario_1*.yaml"]
    config_paths = find_config_paths(patterns)
    if not config_paths:
        raise SystemExit("No config files found.")

    output_dir = Path(args.output_dir)
    data_root = Path(args.data_root)

    definition_rows: List[Dict[str, str]] = []
    actor_rows: List[Dict[str, str]] = []
    kpi_rows: List[Dict[str, Any]] = []
    score_rows: List[Dict[str, Any]] = []
    run_actor_rows: List[Dict[str, Any]] = []
    data_metadata_rows: List[Dict[str, Any]] = []
    kpi_data_requirement_rows: List[Dict[str, Any]] = []

    for config_path in config_paths:
        config = load_yaml(config_path)
        title = scenario_title(config, config_path.stem)
        d_rows, a_rows = extract_definition_rows(config_path, config)
        definition_rows.extend(d_rows)
        actor_rows.extend(a_rows)
        kpi_data_requirement_rows.extend(kpi_requirement_rows(title))

        runs = find_runs(data_root, title)
        if args.latest_complete_only:
            runs = latest_complete_runs(runs, config)
        data_metadata_rows.extend(collect_data_metadata(config_path, config, runs))
        if not runs:
            kpi_rows.append(
                {
                    "scenario": title,
                    "config_file": str(config_path),
                    "run": "",
                    "run_dir": "",
                    "status": "no_data_dump",
                    "notes": f"No runs under {data_root / title}",
                }
            )
            score_rows.append(empty_score_row(title, "", {"event_outcome": ""}))
            continue

        for run_dir in runs:
            kpi, score, run_rows = compute_kpis_for_run(
                config_path,
                config,
                run_dir,
                args.warning_clearance_m,
            )
            kpi_rows.append(kpi)
            score_rows.append(score)
            run_actor_rows.extend(run_rows)

    write_csv(output_dir / "scenario_definition.csv", definition_rows)
    write_csv(output_dir / "actor_definition.csv", actor_rows)
    write_csv(output_dir / "kpi_summary.csv", kpi_rows)
    write_csv(output_dir / "score_summary.csv", score_rows)
    write_csv(output_dir / "run_actor_mapping.csv", run_actor_rows)
    write_csv(output_dir / "data_column_metadata.csv", data_metadata_rows)
    write_csv(output_dir / "kpi_data_requirements.csv", kpi_data_requirement_rows)
    write_markdown(output_dir / "summary.md", kpi_rows, score_rows)

    print(f"Wrote outputs to {output_dir.resolve()}")
    print(f"Configs: {len(config_paths)}, KPI rows: {len(kpi_rows)}")


if __name__ == "__main__":
    main()
