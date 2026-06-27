#!/usr/bin/env python
"""
Calculate critical-actor awareness HOTA with optional V2X fusion.

The raw tracking HOTA script evaluates only objects dumped under `vehicles`.
That is useful for sensor-only perception, but it does not count a V2X Basic
Safety Message / cooperative object state as an awareness track. This script
evaluates the critical actor only and, for V2X scenarios, injects the actor's
ground-truth state as a fused V2X track once the configured communication
condition is reached.

The result should be reported as cooperative awareness/tracking, not as
sensor-only perception model performance.
"""

import argparse
import csv
import math
import os
import sys

import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import calculate_tracking_hota as hota  # noqa: E402


MODE = "critical_actor_awareness"
DEFAULT_ALPHAS = hota.DEFAULT_ALPHAS
DEFAULT_FUSION_ROLES = {"ego", "rsu"}


def _scenario_config(run_dir):
    protocol = hota._load_yaml(os.path.join(run_dir, "data_protocol.yaml"))
    return protocol.get("scenario") or {}, protocol


def _spawn_for_role(scenario, role):
    for cav in scenario.get("single_cav_list") or []:
        if cav.get("name") == role:
            spawn = cav.get("spawn_position") or []
            if len(spawn) >= 2:
                return float(spawn[0]), float(spawn[1])
    return None


def _communication_range(scenario, protocol):
    for cav in scenario.get("single_cav_list") or []:
        if cav.get("name") == "ego":
            v2x = cav.get("v2x") or {}
            try:
                return float(v2x.get("communication_range", 0.0))
            except (TypeError, ValueError):
                return 0.0
    v2x = ((protocol.get("vehicle_base") or {}).get("v2x") or {})
    try:
        return float(v2x.get("communication_range", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _v2x_enabled(scenario):
    states = {}
    for cav in scenario.get("single_cav_list") or []:
        states[cav.get("name")] = bool((cav.get("v2x") or {}).get("enabled"))
    return bool(states.get("ego") and states.get("subject"))


def _first_frame_data(run_dir):
    for name in sorted(os.listdir(run_dir)):
        observer_dir = os.path.join(run_dir, name)
        if not os.path.isdir(observer_dir) or name == "topview_screen":
            continue
        yaml_files = sorted(
            f for f in os.listdir(observer_dir)
            if f.lower().endswith(".yaml") and f[:6].isdigit())
        if yaml_files:
            return hota._load_yaml(os.path.join(observer_dir, yaml_files[0]))
    return {}


def _target_actor_id(run_dir, scenario):
    subject_spawn = _spawn_for_role(scenario, "subject")
    if subject_spawn is None:
        raise RuntimeError("Could not find subject spawn in %s" % run_dir)

    frame_data = _first_frame_data(run_dir)
    vehicles = frame_data.get("total_vehicles") or {}
    best_id = None
    best_dist = float("inf")
    for key, obj in vehicles.items():
        location = obj.get("location") or []
        if len(location) < 2:
            continue
        bp_id = obj.get("bp_id", "")
        if "fusorosa" in bp_id or "sprinter" in bp_id:
            continue
        dist = math.hypot(float(location[0]) - subject_spawn[0],
                          float(location[1]) - subject_spawn[1])
        if dist < best_dist:
            best_dist = dist
            best_id = hota._int_or_none(obj.get("carla_id", key))

    if best_id is None:
        raise RuntimeError("Could not infer subject actor id in %s" % run_dir)
    return best_id


def _conflict_point(scenario):
    ego_spawn = _spawn_for_role(scenario, "ego")
    subject_spawn = _spawn_for_role(scenario, "subject")
    if ego_spawn is None or subject_spawn is None:
        return None
    return ego_spawn[0], subject_spawn[1]


def _target_gt(frame_data, target_id):
    gt_objects = hota._parse_gt_objects(frame_data)
    return gt_objects.get(target_id)


def _target_predictions(frame_data, target_gt, target_id):
    predictions = {}
    target_bbox = target_gt["bbox"] if target_gt else None
    raw_predictions = hota._parse_prediction_objects(frame_data)
    for pr_id, pred in raw_predictions.items():
        if pred.get("matched_gt_id") == target_id:
            predictions[pr_id] = pred
            continue
        if pr_id == target_id:
            predictions[pr_id] = pred
            continue
        if target_bbox is not None and hota._iou(target_bbox, pred["bbox"]) >= 0.05:
            predictions[pr_id] = pred
    return predictions


def _v2x_in_range(frame_data, target_id, conflict_point, communication_range):
    if communication_range <= 0.0 or conflict_point is None:
        return False
    total_vehicles = frame_data.get("total_vehicles") or {}
    target = None
    for key, obj in total_vehicles.items():
        carla_id = hota._int_or_none(obj.get("carla_id", key))
        if carla_id == target_id:
            target = obj
            break
    if not target:
        return False
    target_location = target.get("location") or []
    ego_location = frame_data.get("true_ego_pos") or frame_data.get(
        "predicted_ego_pos") or []
    if len(target_location) < 2:
        return False

    target_x, target_y = float(target_location[0]), float(target_location[1])
    actor_conflict_distance = math.hypot(
        target_x - conflict_point[0], target_y - conflict_point[1])
    direct_link_distance = float("inf")
    if len(ego_location) >= 2:
        direct_link_distance = math.hypot(
            target_x - float(ego_location[0]),
            target_y - float(ego_location[1]))
    return (actor_conflict_distance <= communication_range or
            direct_link_distance <= communication_range)


def _fused_sequence(observer_dir, target_id, use_v2x_fusion,
                    conflict_point, communication_range,
                    frame_start=None, frame_end=None):
    frames = []
    awareness = {
        "first_sensor_frame": "",
        "first_fused_frame": "",
        "v2x_added_frames": 0,
    }
    yaml_files = sorted(
        f for f in os.listdir(observer_dir)
        if f.lower().endswith(".yaml") and f[:6].isdigit())

    for file_name in yaml_files:
        frame_data = hota._load_yaml(os.path.join(observer_dir, file_name))
        frame_number = int(file_name[:6])
        if frame_start is not None and frame_number < frame_start:
            continue
        if frame_end is not None and frame_number > frame_end:
            continue
        target_gt = _target_gt(frame_data, target_id)
        gt_objects = {target_id: target_gt} if target_gt else {}
        pred_objects = _target_predictions(frame_data, target_gt, target_id)
        if pred_objects and not awareness["first_sensor_frame"]:
            awareness["first_sensor_frame"] = frame_number

        has_v2x_track = (
            use_v2x_fusion and target_gt and
            _v2x_in_range(frame_data, target_id, conflict_point,
                          communication_range))
        if has_v2x_track:
            v2x_track = dict(target_gt)
            v2x_track["id"] = target_id
            v2x_track["perception_mode"] = "v2x_fused_track"
            pred_objects[target_id] = v2x_track
            awareness["v2x_added_frames"] += 1

        if pred_objects and not awareness["first_fused_frame"]:
            awareness["first_fused_frame"] = frame_number
        frames.append((frame_number, gt_objects, pred_objects))

    return frames, awareness


def _evaluate_observer(run_dir, observer_id, observer_dir, role,
                       scenario, protocol, alphas, fusion_roles,
                       frame_start=None, frame_end=None):
    target_id = _target_actor_id(run_dir, scenario)
    is_v2x_scenario = _v2x_enabled(scenario)
    communication_range = _communication_range(scenario, protocol)
    conflict_point = _conflict_point(scenario)
    use_v2x_fusion = is_v2x_scenario and role in fusion_roles
    frames, awareness = _fused_sequence(
        observer_dir, target_id, use_v2x_fusion, conflict_point,
        communication_range, frame_start=frame_start, frame_end=frame_end)
    alpha_results = [hota._calculate_for_alpha(frames, alpha)
                     for alpha in alphas]
    result_050 = min(alpha_results, key=lambda r: abs(r["alpha"] - 0.5))
    scenario_name, run_time = hota._run_label(run_dir)
    summary = {
        "scenario": scenario_name,
        "run_time": run_time,
        "observer_id": observer_id,
        "observer_role": role,
        "perception_mode": MODE,
        "frames": result_050["frames"],
        "gt_dets": result_050["gt_dets"],
        "pred_dets": result_050["pred_dets"],
        "HOTA_mean": sum(r["HOTA"] for r in alpha_results) /
        len(alpha_results),
        "HOTA_0.50": result_050["HOTA"],
        "DetA_0.50": result_050["DetA"],
        "AssA_0.50": result_050["AssA"],
        "LocA_0.50": result_050["LocA"],
        "MOTA_0.50": result_050["MOTA"],
        "MOTP_0.50": result_050["MOTP"],
        "TP_0.50": result_050["tp"],
        "FP_0.50": result_050["fp"],
        "FN_0.50": result_050["fn"],
        "IDSW_0.50": result_050["idsw"],
        "target_actor_id": target_id,
        "v2x_fusion_applied": str(use_v2x_fusion).lower(),
        "v2x_added_frames": awareness["v2x_added_frames"],
        "first_sensor_frame": awareness["first_sensor_frame"],
        "first_fused_frame": awareness["first_fused_frame"],
    }
    detail_rows = []
    for result in alpha_results:
        detail = {
            "scenario": scenario_name,
            "run_time": run_time,
            "observer_id": observer_id,
            "observer_role": role,
            "perception_mode": MODE,
        }
        detail.update(result)
        detail_rows.append(detail)
    return summary, detail_rows


def _evaluate_run(run_dir, alphas, fusion_roles,
                  frame_start=None, frame_end=None):
    roles = hota._infer_roles(run_dir)
    scenario, protocol = _scenario_config(run_dir)
    rows = []
    detail_rows = []
    for observer_id, observer_dir in hota._iter_observer_dirs(run_dir, None):
        role = roles.get(observer_id, "unknown")
        if role not in {"rsu", "ego"}:
            continue
        summary, details = _evaluate_observer(
            run_dir, observer_id, observer_dir, role, scenario, protocol,
            alphas, fusion_roles, frame_start=frame_start,
            frame_end=frame_end)
        rows.append(summary)
        detail_rows.extend(details)
    return rows, detail_rows


def _write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path, summary_rows, run_dirs, frame_start=None,
                  frame_end=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [
        "# Scenario 1 Critical Actor Awareness HOTA",
        "",
        "This report evaluates only the critical actor. In V2X runs, the "
        "actor's cooperative message is counted as a fused awareness track "
        "once the communication condition is reached.",
        "",
        "This is not sensor-only perception HOTA. It should be reported as "
        "`V2X-fused awareness/tracking`.",
        "",
        "Frame window: `%s` to `%s`." % (
            frame_start if frame_start is not None else "all",
            frame_end if frame_end is not None else "all"),
        "",
        "## Input Runs",
        "",
    ]
    for run_dir in run_dirs:
        lines.append("- `%s`" % run_dir)
    lines.extend([
        "",
        "## Summary",
        "",
        "| scenario | observer | HOTA_mean | DetA@0.50 | AssA@0.50 | "
        "TP/FP/FN | first sensor | first fused | V2X frames |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in summary_rows:
        observer = "%s(%s)" % (row["observer_role"], row["observer_id"])
        counts = "%s/%s/%s" % (
            row["TP_0.50"], row["FP_0.50"], row["FN_0.50"])
        lines.append(
            "| {scenario} | {observer} | {hota:.4f} | {deta:.4f} | "
            "{assa:.4f} | {counts} | {first_sensor} | {first_fused} | "
            "{v2x_frames} |".format(
                scenario=row["scenario"],
                observer=observer,
                hota=float(row["HOTA_mean"]),
                deta=float(row["DetA_0.50"]),
                assa=float(row["AssA_0.50"]),
                counts=counts,
                first_sensor=row["first_sensor_frame"] or "-",
                first_fused=row["first_fused_frame"] or "-",
                v2x_frames=row["v2x_added_frames"]))
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Calculate V2X-fused critical actor awareness HOTA.")
    parser.add_argument("--run-dir", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fusion-role", action="append",
                        choices=["ego", "rsu"],
                        help="Observer role that receives V2X fused tracks. "
                        "Defaults to ego and rsu for system-level reporting.")
    parser.add_argument("--frame-start", type=int,
                        help="Optional first frame to include.")
    parser.add_argument("--frame-end", type=int,
                        help="Optional last frame to include.")
    args = parser.parse_args()

    fusion_roles = set(args.fusion_role or DEFAULT_FUSION_ROLES)
    summary_rows = []
    detail_rows = []
    for run_dir in args.run_dir:
        rows, details = _evaluate_run(
            run_dir, DEFAULT_ALPHAS, fusion_roles,
            frame_start=args.frame_start, frame_end=args.frame_end)
        summary_rows.extend(rows)
        detail_rows.extend(details)

    _write_csv(os.path.join(args.output_dir, "tracking_kpi_summary.csv"),
               summary_rows)
    _write_csv(os.path.join(args.output_dir, "tracking_kpi_by_alpha.csv"),
               detail_rows)
    _write_report(os.path.join(args.output_dir, "tracking_kpi_report.md"),
                  summary_rows, args.run_dir, frame_start=args.frame_start,
                  frame_end=args.frame_end)
    print("Wrote V2X-fused awareness KPI to", args.output_dir)


if __name__ == "__main__":
    main()
