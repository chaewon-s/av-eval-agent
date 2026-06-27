#!/usr/bin/env python
"""
Calculate revised Scenario 1 KPIs with event-aware observation windows.

This script keeps the older KPI scripts untouched and produces a revised
research-facing output set:

- Perception: fixed observation-horizon averages instead of one full-exposure
  aggregate.
- Control: ego control metrics are cut at the pre-event frame, so post-crash
  stationary frames cannot make No V2X look artificially smooth.
- Traffic: delay is replaced by travel-time/trip-completion reporting.
- Safety: 2D TTC is calculated from relative 2D position/velocity; PET is
  reported only when both vehicles complete a clean conflict-zone pass; PRS is
  a proxy based on hazard awareness and required deceleration.
"""

import argparse
import csv
import math
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import calculate_ride_comfort_kpis as comfort  # noqa: E402
import calculate_tracking_hota as hota  # noqa: E402
import calculate_v2x_fused_awareness_hota as awareness  # noqa: E402


DEFAULT_HORIZONS_S = [1.0, 2.0, 3.0, 5.0]
DEFAULT_ALPHA = 0.50
DEFAULT_COLLISION_DISTANCE_M = 4.5
DEFAULT_CONFLICT_RADIUS_M = 5.0
DEFAULT_VISUAL_RANGE_M = 5.0
DEFAULT_REACTION_TIME_S = 0.7
DEFAULT_EMERGENCY_DECEL_MPS2 = 8.0


def _write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fieldnames = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _scenario_and_time(run_dir):
    scenario, run_time = hota._run_label(run_dir)
    if not scenario:
        scenario = os.path.basename(os.path.dirname(run_dir))
    if not run_time:
        run_time = os.path.basename(run_dir)
    return scenario, run_time


def _protocol(run_dir):
    return hota._load_yaml(os.path.join(run_dir, "data_protocol.yaml"))


def _scenario_config(run_dir):
    return (_protocol(run_dir).get("scenario") or {})


def _fixed_delta_seconds(run_dir):
    protocol = _protocol(run_dir)
    return float(((protocol.get("world") or {}).get("fixed_delta_seconds")) or 0.1)


def _cav_by_name(run_dir, role):
    scenario = _scenario_config(run_dir)
    for cav in scenario.get("single_cav_list") or []:
        if cav.get("name") == role:
            return cav
    return {}


def _xy_from_list(values):
    if not isinstance(values, list) or len(values) < 2:
        return None
    return float(values[0]), float(values[1])


def _role_observer(run_dir, role):
    roles = hota._infer_roles(run_dir)
    for observer_id, observer_dir in hota._iter_observer_dirs(run_dir, None):
        if roles.get(observer_id) == role:
            return observer_id, observer_dir
    return None, None


def _role_timeseries(run_dir, role):
    observer_id, observer_dir = _role_observer(run_dir, role)
    if observer_dir is None:
        return observer_id, []
    dt = _fixed_delta_seconds(run_dir)
    rows = comfort._read_ego_timeseries(
        observer_dir,
        dt,
        comfort.DEFAULT_WHEELBASE_M,
        comfort.DEFAULT_MIN_SPEED_FOR_STEERING_MPS,
    )
    return observer_id, rows


def _metric_mean(values):
    return sum(values) / len(values) if values else 0.0


def _metric_rms(values):
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


def _metric_variance(values):
    if not values:
        return 0.0
    avg = _metric_mean(values)
    return sum((v - avg) ** 2 for v in values) / len(values)


def _metric_percentile(values, pct):
    if not values:
        return 0.0
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * pct / 100.0
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return values[lo]
    ratio = pos - lo
    return values[lo] * (1.0 - ratio) + values[hi] * ratio


def _distance_xy(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _target_actor_id(run_dir):
    scenario = _scenario_config(run_dir)
    return awareness._target_actor_id(run_dir, scenario)


def _conflict_point(run_dir):
    scenario = _scenario_config(run_dir)
    return awareness._conflict_point(scenario)


def _critical_pair_rows(run_dir):
    """Return ego-subject relative state rows from the ego observer dump."""
    ego_id, ego_dir = _role_observer(run_dir, "ego")
    if ego_dir is None:
        return []

    target_id = _target_actor_id(run_dir)
    dt = _fixed_delta_seconds(run_dir)
    raw_rows = []
    yaml_files = sorted(
        f for f in os.listdir(ego_dir)
        if f.lower().endswith(".yaml") and f[:6].isdigit())
    for file_name in yaml_files:
        frame = int(file_name[:6])
        data = hota._load_yaml(os.path.join(ego_dir, file_name))
        ego_xy = _xy_from_list(data.get("true_ego_pos") or [])
        subject_xy = None
        for key, obj in (data.get("total_vehicles") or {}).items():
            carla_id = hota._int_or_none(obj.get("carla_id", key))
            if carla_id == target_id:
                subject_xy = _xy_from_list(obj.get("location") or [])
                break
        if ego_xy is None or subject_xy is None:
            continue
        raw_rows.append({
            "frame": frame,
            "time_s": (frame - 1) * dt,
            "ego_x": ego_xy[0],
            "ego_y": ego_xy[1],
            "subject_x": subject_xy[0],
            "subject_y": subject_xy[1],
            "distance_2d_m": _distance_xy(ego_xy, subject_xy),
        })

    for index, row in enumerate(raw_rows):
        if index == 0:
            row.update({
                "ego_vx": 0.0,
                "ego_vy": 0.0,
                "subject_vx": 0.0,
                "subject_vy": 0.0,
            })
            continue
        prev = raw_rows[index - 1]
        row["ego_vx"] = (row["ego_x"] - prev["ego_x"]) / dt
        row["ego_vy"] = (row["ego_y"] - prev["ego_y"]) / dt
        row["subject_vx"] = (row["subject_x"] - prev["subject_x"]) / dt
        row["subject_vy"] = (row["subject_y"] - prev["subject_y"]) / dt
    return raw_rows


def _ttc_2d(row, collision_distance_m):
    """2D time-to-collision for two discs with collision_distance_m radius."""
    rx = row["subject_x"] - row["ego_x"]
    ry = row["subject_y"] - row["ego_y"]
    vx = row["subject_vx"] - row["ego_vx"]
    vy = row["subject_vy"] - row["ego_vy"]
    a = vx * vx + vy * vy
    c = rx * rx + ry * ry - collision_distance_m * collision_distance_m
    if c <= 0.0:
        return 0.0
    if a <= 1e-9:
        return None
    b = 2.0 * (rx * vx + ry * vy)
    if b >= 0.0:
        return None
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    t_enter = (-b - math.sqrt(disc)) / (2.0 * a)
    return t_enter if t_enter >= 0.0 else None


def _event_cutoff(run_dir, collision_distance_m):
    rows = _critical_pair_rows(run_dir)
    if not rows:
        return {
            "event_frame": "",
            "event_time_s": "",
            "event_basis": "no_relative_state",
            "min_distance_2d_m": "",
        }
    min_row = min(rows, key=lambda row: row["distance_2d_m"])
    collision_rows = [
        row for row in rows
        if row["distance_2d_m"] <= collision_distance_m
    ]
    if collision_rows:
        event = collision_rows[0]
        basis = "first_distance_below_collision_threshold"
    else:
        event = min_row
        basis = "closest_approach"
    return {
        "event_frame": event["frame"],
        "event_time_s": event["time_s"],
        "event_basis": basis,
        "min_distance_2d_m": min_row["distance_2d_m"],
    }


def _control_rows(run_dirs, collision_distance_m):
    rows = []
    for run_dir in run_dirs:
        scenario, run_time = _scenario_and_time(run_dir)
        observer_id, series = _role_timeseries(run_dir, "ego")
        cutoff = _event_cutoff(run_dir, collision_distance_m)
        event_frame = cutoff["event_frame"]
        if isinstance(event_frame, int):
            series = [row for row in series if row["frame"] < event_frame]

        accel = [row["acceleration_mps2"] for row in series[1:]]
        steering_rate = [row["steering_rate_proxy_rad_s"] for row in series[2:]]
        jerk = [row["jerk_mps3"] for row in series[2:]]
        abs_steer = [abs(v) for v in steering_rate]
        abs_jerk = [abs(v) for v in jerk]
        rows.append({
            "scenario": scenario,
            "run_time": run_time,
            "observer_role": "ego",
            "observer_id": observer_id,
            "window": "pre_event",
            "frames_used": len(series),
            "duration_used_s": (
                series[-1]["time_s"] - series[0]["time_s"]
                if len(series) >= 2 else 0.0),
            "event_frame_excluded_from": event_frame,
            "event_time_s": cutoff["event_time_s"],
            "event_basis": cutoff["event_basis"],
            "min_distance_2d_m": cutoff["min_distance_2d_m"],
            "steering_rate_rms_rad_s": _metric_rms(steering_rate),
            "steering_rate_abs_p95_rad_s": _metric_percentile(abs_steer, 95),
            "steering_rate_abs_max_rad_s": max(abs_steer, default=0.0),
            "acceleration_variance_mps4": _metric_variance(accel),
            "acceleration_abs_p95_mps2": _metric_percentile(
                [abs(v) for v in accel], 95),
            "jerk_abs_p95_mps3": _metric_percentile(abs_jerk, 95),
            "jerk_abs_max_mps3": max(abs_jerk, default=0.0),
        })
    return rows


def _fused_awareness_frames(run_dir, observer_role, mode):
    scenario = _scenario_config(run_dir)
    protocol = _protocol(run_dir)
    roles = hota._infer_roles(run_dir)
    target_id = awareness._target_actor_id(run_dir, scenario)
    communication_range = awareness._communication_range(scenario, protocol)
    conflict_point = awareness._conflict_point(scenario)
    use_v2x = mode == "v2x_fused"
    for observer_id, observer_dir in hota._iter_observer_dirs(run_dir, None):
        role = roles.get(observer_id, "unknown")
        if role != observer_role:
            continue
        frames, details = awareness._fused_sequence(
            observer_dir,
            target_id,
            use_v2x,
            conflict_point,
            communication_range,
        )
        return observer_id, frames, details
    return "", [], {}


def _perception_horizon_rows(run_dir, horizons_s, alpha):
    scenario, run_time = _scenario_and_time(run_dir)
    dt = _fixed_delta_seconds(run_dir)
    rows = []
    is_v2x_run = awareness._v2x_enabled(_scenario_config(run_dir))
    mode_list = ["sensor_only"]
    if is_v2x_run:
        mode_list.append("v2x_fused")

    for observer_role in ["ego", "rsu"]:
        anchor_frame = None
        if is_v2x_run:
            _, _, fused_details = _fused_awareness_frames(
                run_dir, observer_role, "v2x_fused")
            if fused_details.get("first_fused_frame") != "":
                anchor_frame = int(fused_details["first_fused_frame"])
        for mode in mode_list:
            observer_id, frames, details = _fused_awareness_frames(
                run_dir, observer_role, mode)
            if not frames:
                continue
            local_anchor = anchor_frame
            if local_anchor is None and details.get("first_sensor_frame") != "":
                local_anchor = int(details["first_sensor_frame"])
            if local_anchor is not None:
                frames = [
                    item for item in frames
                    if int(item[0]) >= int(local_anchor)
                ]
            for horizon_s in horizons_s:
                window_size = max(1, int(round(horizon_s / dt)))
                window_results = []
                for start in range(0, len(frames), window_size):
                    window = frames[start:start + window_size]
                    if len(window) < max(1, window_size // 2):
                        continue
                    result = hota._calculate_for_alpha(window, alpha)
                    gt = result["gt_dets"]
                    availability = result["tp"] / gt if gt else 0.0
                    window_results.append({
                        "HOTA": result["HOTA"],
                        "DetA": result["DetA"],
                        "AssA": result["AssA"],
                        "availability": availability,
                        "TP": result["tp"],
                        "FP": result["fp"],
                        "FN": result["fn"],
                    })
                if not window_results:
                    continue
                rows.append({
                    "scenario": scenario,
                    "run_time": run_time,
                    "observer_role": observer_role,
                    "observer_id": observer_id,
                    "perception_mode": mode,
                    "horizon_s": horizon_s,
                    "window_count": len(window_results),
                    "avg_HOTA": _metric_mean([r["HOTA"] for r in window_results]),
                    "avg_DetA": _metric_mean([r["DetA"] for r in window_results]),
                    "avg_AssA": _metric_mean([r["AssA"] for r in window_results]),
                    "avg_availability": _metric_mean([
                        r["availability"] for r in window_results]),
                    "avg_TP": _metric_mean([r["TP"] for r in window_results]),
                    "avg_FP": _metric_mean([r["FP"] for r in window_results]),
                    "avg_FN": _metric_mean([r["FN"] for r in window_results]),
                    "first_sensor_frame": details.get("first_sensor_frame", ""),
                    "first_fused_frame": details.get("first_fused_frame", ""),
                    "v2x_added_frames": details.get("v2x_added_frames", 0),
                    "observation_anchor_frame": local_anchor or "",
                    "comparison_scope": (
                        "primary_same_run_sensor_vs_fusion"
                        if is_v2x_run else
                        "reference_only_not_primary_for_perception"),
                    "method": "fixed_non_overlapping_horizon_average",
                })
    return rows


def _traffic_rows(run_dirs):
    rows = []
    for run_dir in run_dirs:
        scenario, run_time = _scenario_and_time(run_dir)
        for role in ["ego", "subject"]:
            observer_id, series = _role_timeseries(run_dir, role)
            if not series:
                continue
            cav = _cav_by_name(run_dir, role)
            spawn = _xy_from_list(cav.get("spawn_position") or [])
            dest = _xy_from_list(cav.get("destination") or [])
            if spawn is None or dest is None:
                planned_distance = 0.0
                projected_progress = 0.0
            else:
                planned_distance = _distance_xy(spawn, dest)
                path_x = dest[0] - spawn[0]
                path_y = dest[1] - spawn[1]
                final = (series[-1]["x_m"], series[-1]["y_m"])
                if planned_distance > 0:
                    projected_progress = (
                        (final[0] - spawn[0]) * path_x +
                        (final[1] - spawn[1]) * path_y) / planned_distance
                else:
                    projected_progress = 0.0

            actual_path = 0.0
            for prev, cur in zip(series, series[1:]):
                actual_path += math.hypot(
                    cur["x_m"] - prev["x_m"], cur["y_m"] - prev["y_m"])
            completion_path = (
                min(actual_path / planned_distance, 1.0)
                if planned_distance > 0 else 0.0)
            completion_progress = (
                max(0.0, min(projected_progress / planned_distance, 1.0))
                if planned_distance > 0 else 0.0)
            avg_speed = _metric_mean([r["speed_mps"] for r in series]) * 3.6
            rows.append({
                "scenario": scenario,
                "run_time": run_time,
                "role": role,
                "observer_id": observer_id,
                "observed_time_s": (
                    series[-1]["time_s"] - series[0]["time_s"]
                    if len(series) >= 2 else 0.0),
                "avg_speed_kmh": avg_speed,
                "planned_trip_distance_m": planned_distance,
                "actual_path_distance_m": actual_path,
                "trip_completion_path_ratio": completion_path,
                "trip_completion_progress_ratio": completion_progress,
                "recommended_flow_efficiency": completion_progress,
                "traffic_metric_note": (
                    "Delay was removed because it duplicated travel time. "
                    "Flow efficiency is reported as trip completion/progress."),
            })
    return rows


def _conflict_zone_times(run_dir, role, conflict_xy, radius_m):
    _, series = _role_timeseries(run_dir, role)
    inside = []
    for row in series:
        distance = math.hypot(row["x_m"] - conflict_xy[0],
                              row["y_m"] - conflict_xy[1])
        inside.append((row["time_s"], distance <= radius_m))
    entry = None
    exit_time = None
    was_inside = False
    for time_s, is_inside in inside:
        if is_inside and not was_inside and entry is None:
            entry = time_s
        if was_inside and not is_inside and entry is not None:
            exit_time = time_s
            break
        was_inside = is_inside
    return entry, exit_time


def _first_awareness_frame(run_dir, visual_range_m):
    scenario = _scenario_config(run_dir)
    protocol = _protocol(run_dir)
    target_id = _target_actor_id(run_dir)
    conflict_xy = _conflict_point(run_dir)
    communication_range = awareness._communication_range(scenario, protocol)
    rows = _critical_pair_rows(run_dir)
    is_v2x = awareness._v2x_enabled(scenario)
    for row in rows:
        if is_v2x:
            actor_conflict = (
                _distance_xy((row["subject_x"], row["subject_y"]), conflict_xy)
                if conflict_xy is not None else float("inf"))
            direct_link = row["distance_2d_m"]
            if actor_conflict <= communication_range or direct_link <= communication_range:
                return row["frame"], row["time_s"], "v2x_actor_message"
        else:
            if row["distance_2d_m"] <= visual_range_m:
                return row["frame"], row["time_s"], "visual_detection_range"
    return "", "", "not_observed_before_end"


def _safety_rows(run_dirs, collision_distance_m, conflict_radius_m,
                 visual_range_m, reaction_time_s, emergency_decel_mps2):
    rows = []
    for run_dir in run_dirs:
        scenario, run_time = _scenario_and_time(run_dir)
        relative_rows = _critical_pair_rows(run_dir)
        conflict_xy = _conflict_point(run_dir)
        ttc_values = []
        for row in relative_rows:
            ttc = _ttc_2d(row, collision_distance_m)
            if ttc is not None:
                ttc_values.append((row["frame"], row["time_s"], ttc))
        min_ttc = min([v[2] for v in ttc_values], default="")
        event = _event_cutoff(run_dir, collision_distance_m)

        pet_value = ""
        pet_reason = "conflict_point_unavailable"
        ego_entry = ""
        ego_exit = ""
        subject_entry = ""
        subject_exit = ""
        if conflict_xy is not None:
            ego_entry, ego_exit = _conflict_zone_times(
                run_dir, "ego", conflict_xy, conflict_radius_m)
            sub_entry, sub_exit = _conflict_zone_times(
                run_dir, "subject", conflict_xy, conflict_radius_m)
            subject_entry = sub_entry
            subject_exit = sub_exit
            if None in (ego_entry, ego_exit, sub_entry, sub_exit):
                pet_reason = "undefined_one_or_both_vehicles_did_not_cleanly_enter_and_exit_conflict_zone"
            elif ego_exit <= sub_entry:
                pet_value = sub_entry - ego_exit
                pet_reason = "defined_subject_after_ego"
            elif sub_exit <= ego_entry:
                pet_value = ego_entry - sub_exit
                pet_reason = "defined_ego_after_subject"
            else:
                pet_value = 0.0
                pet_reason = "temporal_overlap_or_collision_risk"

        awareness_frame, awareness_time, awareness_source = _first_awareness_frame(
            run_dir, visual_range_m)
        required_decel = ""
        prs = "unknown"
        if awareness_frame != "" and conflict_xy is not None:
            aware_row = next(
                (row for row in relative_rows if row["frame"] == awareness_frame),
                None)
            if aware_row:
                ego_speed = math.hypot(aware_row["ego_vx"], aware_row["ego_vy"])
                distance_to_conflict = math.hypot(
                    aware_row["ego_x"] - conflict_xy[0],
                    aware_row["ego_y"] - conflict_xy[1])
                available_distance = max(
                    distance_to_conflict - ego_speed * reaction_time_s, 0.1)
                required_decel = ego_speed * ego_speed / (
                    2.0 * available_distance)
                ttc_at_awareness = _ttc_2d(aware_row, collision_distance_m)
                if required_decel <= emergency_decel_mps2 and (
                        ttc_at_awareness is None or ttc_at_awareness > reaction_time_s):
                    prs = "preventable_proxy"
                else:
                    prs = "hard_to_avoid_proxy"

        rows.append({
            "scenario": scenario,
            "run_time": run_time,
            "ttc_method": "2d_relative_motion_disc_threshold",
            "collision_distance_m": collision_distance_m,
            "min_ttc_2d_s": min_ttc,
            "min_distance_2d_m": event["min_distance_2d_m"],
            "event_frame": event["event_frame"],
            "event_time_s": event["event_time_s"],
            "event_basis": event["event_basis"],
            "conflict_radius_m": conflict_radius_m,
            "ego_conflict_entry_s": ego_entry if ego_entry is not None else "",
            "ego_conflict_exit_s": ego_exit if ego_exit is not None else "",
            "subject_conflict_entry_s": (
                subject_entry if subject_entry is not None else ""),
            "subject_conflict_exit_s": (
                subject_exit if subject_exit is not None else ""),
            "pet_s": pet_value,
            "pet_reason": pet_reason,
            "awareness_frame": awareness_frame,
            "awareness_time_s": awareness_time,
            "awareness_source": awareness_source,
            "required_decel_at_awareness_mps2": required_decel,
            "prs_proxy": prs,
        })
    return rows


def _plot_outputs(output_dir, perception_rows, control_rows, traffic_rows):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return

    if perception_rows:
        grouped = defaultdict(list)
        for row in perception_rows:
            if row["observer_role"] != "ego":
                continue
            if row.get("comparison_scope") != "primary_same_run_sensor_vs_fusion":
                continue
            label = "%s-%s" % (row["scenario"].replace("scenario1_", ""),
                               row["perception_mode"])
            grouped[label].append(row)
        fig, ax = plt.subplots(figsize=(10.5, 5.4))
        for label, rows in sorted(grouped.items()):
            rows = sorted(rows, key=lambda r: float(r["horizon_s"]))
            ax.plot([r["horizon_s"] for r in rows],
                    [r["avg_availability"] for r in rows],
                    marker="o", linewidth=2.0, label=label)
        ax.set_title("Critical Actor Awareness by Observation Horizon")
        ax.set_xlabel("Observation horizon (s)")
        ax.set_ylabel("Average availability")
        ax.set_ylim(0, 1.05)
        ax.grid(True, linestyle="--", linewidth=0.6, alpha=0.45)
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(os.path.join(output_dir, "perception_observation_horizon.png"),
                    dpi=180)
        plt.close(fig)

    if control_rows:
        labels = [row["scenario"].replace("scenario1_", "")
                  for row in control_rows]
        x = list(range(len(control_rows)))
        width = 0.28
        fig, ax = plt.subplots(figsize=(10.0, 5.2))
        ax.bar([v - width for v in x],
               [row["steering_rate_rms_rad_s"] for row in control_rows],
               width, label="Steering RMS")
        ax.bar(x,
               [row["steering_rate_abs_p95_rad_s"] for row in control_rows],
               width, label="Steering |P95|")
        ax.bar([v + width for v in x],
               [row["acceleration_variance_mps4"] for row in control_rows],
               width, label="Accel variance")
        ax.set_title("Pre-Event Control KPI")
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel("Metric value")
        ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.45)
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(os.path.join(output_dir, "control_pre_event_kpi.png"),
                    dpi=180)
        plt.close(fig)

    if traffic_rows:
        summary = [row for row in traffic_rows if row["role"] == "ego"]
        labels = [row["scenario"].replace("scenario1_", "")
                  for row in summary]
        fig, ax = plt.subplots(figsize=(9.0, 5.0))
        bars = ax.bar(labels,
                      [100.0 * row["recommended_flow_efficiency"]
                       for row in summary],
                      color=["#4C8FD3", "#D95F02"][:len(summary)])
        ax.bar_label(bars, fmt="%.1f%%", padding=3)
        ax.set_ylim(0, 105)
        ax.set_title("Trip Completion Flow Efficiency")
        ax.set_ylabel("Completion (%)")
        ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.45)
        fig.tight_layout()
        fig.savefig(os.path.join(output_dir, "trip_completion_flow_efficiency.png"),
                    dpi=180)
        plt.close(fig)


def _write_definition_report(path, run_dirs, output_dir):
    lines = [
        "# Scenario 1 Revised KPI Framework",
        "",
        "This output applies the KPI revisions requested on 2026-05-26.",
        "",
        "## Inputs",
        "",
    ]
    for run_dir in run_dirs:
        lines.append("- `%s`" % run_dir)
    lines.extend([
        "",
        "## 1. Perception",
        "",
        "V2X and No V2X should not be treated as two unrelated perception experiments. "
        "The revised calculation evaluates critical-actor awareness over fixed observation "
        "time horizons, then averages each window. This avoids the old bias where a longer "
        "exposure window mechanically adds more FN opportunities.",
        "",
        "Output: `perception_observation_horizon.csv` and "
        "`perception_observation_horizon.png`.",
        "",
        "## 2. Control Performance",
        "",
        "Control KPIs are calculated only until the pre-event cutoff. For No V2X, frames "
        "after collision/closest-approach are excluded, because stationary post-crash "
        "frames can make RMS look artificially stable.",
        "",
        "- RMS: average control activity over the valid window.",
        "- P95 abs: severe but not single-frame-extreme control demand.",
        "- Max abs: diagnostic spike only, not the main grade.",
        "- Acceleration variance remains appropriate as the longitudinal smoothness KPI.",
        "",
        "Output: `control_pre_event_kpi.csv` and `control_pre_event_kpi.png`.",
        "",
        "## 3. Traffic Impact",
        "",
        "Delay is removed from the main KPI set because it duplicated travel time in the "
        "current dump. Flow efficiency is redefined as trip completion/progress: actual "
        "movement or projected progress divided by the configured trip distance.",
        "",
        "Output: `traffic_trip_completion_kpi.csv` and "
        "`trip_completion_flow_efficiency.png`.",
        "",
        "## 4. Safety",
        "",
        "TTC is now explicitly 2D TTC from relative position and velocity. PET is reported "
        "only if both vehicles cleanly enter and exit the conflict zone; otherwise it is "
        "marked undefined with a reason. PRS is reported as a proxy based on hazard "
        "awareness timing and required deceleration at awareness.",
        "",
        "Output: `safety_2d_ttc_pet_prs.csv`.",
        "",
        "## Output Folder",
        "",
        "`%s`" % output_dir,
        "",
    ])
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(
        description="Calculate revised Scenario 1 KPI framework.")
    parser.add_argument("--v2x-run-dir", required=True)
    parser.add_argument("--no-v2x-run-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--horizon-s", action="append", type=float,
                        help="Observation horizon in seconds. Can repeat.")
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    parser.add_argument("--collision-distance-m", type=float,
                        default=DEFAULT_COLLISION_DISTANCE_M)
    parser.add_argument("--conflict-radius-m", type=float,
                        default=DEFAULT_CONFLICT_RADIUS_M)
    parser.add_argument("--visual-range-m", type=float,
                        default=DEFAULT_VISUAL_RANGE_M)
    parser.add_argument("--reaction-time-s", type=float,
                        default=DEFAULT_REACTION_TIME_S)
    parser.add_argument("--emergency-decel-mps2", type=float,
                        default=DEFAULT_EMERGENCY_DECEL_MPS2)
    args = parser.parse_args()

    run_dirs = [args.v2x_run_dir, args.no_v2x_run_dir]
    horizons_s = args.horizon_s or DEFAULT_HORIZONS_S
    os.makedirs(args.output_dir, exist_ok=True)

    perception_rows = []
    for run_dir in run_dirs:
        perception_rows.extend(
            _perception_horizon_rows(run_dir, horizons_s, args.alpha))
    control_rows = _control_rows(run_dirs, args.collision_distance_m)
    traffic_rows = _traffic_rows(run_dirs)
    safety_rows = _safety_rows(
        run_dirs,
        args.collision_distance_m,
        args.conflict_radius_m,
        args.visual_range_m,
        args.reaction_time_s,
        args.emergency_decel_mps2,
    )

    _write_csv(os.path.join(args.output_dir,
                            "perception_observation_horizon.csv"),
               perception_rows)
    _write_csv(os.path.join(args.output_dir, "control_pre_event_kpi.csv"),
               control_rows)
    _write_csv(os.path.join(args.output_dir,
                            "traffic_trip_completion_kpi.csv"),
               traffic_rows)
    _write_csv(os.path.join(args.output_dir, "safety_2d_ttc_pet_prs.csv"),
               safety_rows)
    _write_definition_report(
        os.path.join(args.output_dir, "revised_kpi_definition.md"),
        run_dirs,
        args.output_dir,
    )
    _plot_outputs(args.output_dir, perception_rows, control_rows, traffic_rows)
    print("Wrote revised Scenario 1 KPIs to", args.output_dir)


if __name__ == "__main__":
    main()
