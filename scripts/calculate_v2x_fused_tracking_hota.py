#!/usr/bin/env python
"""
Calculate HOTA with YOLO/LiDAR detections plus V2X actor-message tracks.

Prediction definition:
  - No V2X: YOLO/LiDAR detections only
  - V2X: YOLO/LiDAR detections + fused V2X actor message track

The V2X actor message is emulated from the CARLA actor state already present in
the datadump ground-truth snapshot. This is the right evaluation abstraction for
checking whether cooperative communication makes the critical actor available
to the tracker before visual perception can see it. It is not a sensor-only
YOLO model score.
"""

import argparse
import copy
import csv
import math
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import calculate_tracking_hota as hota  # noqa: E402
import calculate_v2x_fused_awareness_hota as awareness  # noqa: E402


MODE = "yolov5_lidar_fusion_plus_stable_v2x_track"
DEFAULT_ALPHAS = hota.DEFAULT_ALPHAS
DEFAULT_FUSION_ROLES = {"ego", "rsu"}
DEFAULT_V2X_TRACK_MAX_AGE = 120
DEFAULT_V2X_POSITION_NOISE_M = 0.6
DEFAULT_V2X_EXTENT_SCALE = 0.92
DEFAULT_V2X_MESSAGE_LATENCY_FRAMES = 1


def _is_target_prediction(pred, target_gt, target_id):
    if pred.get("matched_gt_id") == target_id:
        return True
    if pred.get("id") == target_id:
        return True
    return target_gt is not None and hota._iou(target_gt["bbox"], pred["bbox"]) >= 0.05


def _target_raw_object(frame_data, target_id):
    for key, obj in (frame_data.get("total_vehicles") or {}).items():
        carla_id = hota._int_or_none(obj.get("carla_id", key))
        if carla_id == target_id:
            return copy.deepcopy(obj)
    return None


def _state_from_raw(raw_obj, frame_number):
    if not raw_obj:
        return None
    location = raw_obj.get("location") or []
    extent = raw_obj.get("extent") or []
    velocity = raw_obj.get("velocity") or [0.0, 0.0, 0.0]
    if len(location) < 3 or len(extent) < 3:
        return None
    return {
        "frame": frame_number,
        "location": [float(location[0]), float(location[1]), float(location[2])],
        "extent": [abs(float(extent[0])), abs(float(extent[1])),
                   abs(float(extent[2]))],
        "velocity": [
            float(velocity[0]) if len(velocity) > 0 else 0.0,
            float(velocity[1]) if len(velocity) > 1 else 0.0,
            float(velocity[2]) if len(velocity) > 2 else 0.0,
        ],
        "bp_id": raw_obj.get("bp_id", "v2x_actor"),
        "angle": raw_obj.get("angle", [0.0, 0.0, 0.0]),
        "center": raw_obj.get("center", [0.0, 0.0, 0.0]),
    }


def _deterministic_noise(track_id, frame_number, amplitude):
    if amplitude <= 0.0:
        return 0.0, 0.0
    phase = frame_number * 12.9898 + track_id * 78.233
    return math.sin(phase) * amplitude, math.cos(phase * 0.73) * amplitude


def _fused_track_from_state(state, target_id, frame_number, dt,
                            position_noise_m, extent_scale):
    frame_delta = max(0, frame_number - state["frame"])
    seconds = frame_delta * dt
    noise_x, noise_y = _deterministic_noise(
        target_id, frame_number, position_noise_m)
    location = [
        state["location"][0] + state["velocity"][0] * seconds + noise_x,
        state["location"][1] + state["velocity"][1] * seconds + noise_y,
        state["location"][2] + state["velocity"][2] * seconds,
    ]
    extent_x = state["extent"][0] * extent_scale
    extent_y = state["extent"][1] * extent_scale
    return {
        "id": target_id,
        "bbox": (
            location[0] - extent_x,
            location[1] - extent_y,
            location[0] + extent_x,
            location[1] + extent_y,
        ),
        "bp_id": state["bp_id"],
        "perception_mode": "stable_v2x_actor_track",
        "matched_gt_id": target_id,
    }


def _read_fused_sequence(observer_dir, target_id, use_v2x_fusion,
                         conflict_point, communication_range,
                         prediction_mode, dt, v2x_track_max_age,
                         v2x_position_noise_m, v2x_extent_scale,
                         v2x_message_latency_frames,
                         frame_start=None, frame_end=None):
    frames = []
    stats = {
        "raw_yolo_pred_dets": 0,
        "v2x_added_frames": 0,
        "v2x_message_frames": 0,
        "v2x_predicted_frames": 0,
        "v2x_replaced_yolo_target_dets": 0,
        "raw_yolo_target_frames": 0,
        "target_candidate_frames": 0,
        "first_yolo_target_frame": "",
        "first_fused_target_frame": "",
    }
    stable_track_state = None
    stable_track_age = 0
    yaml_files = sorted(
        f for f in os.listdir(observer_dir)
        if f.lower().endswith(".yaml") and f[:6].isdigit())

    for file_name in yaml_files:
        frame_number = int(file_name[:6])
        if frame_start is not None and frame_number < frame_start:
            continue
        if frame_end is not None and frame_number > frame_end:
            continue

        frame_data = hota._load_yaml(os.path.join(observer_dir, file_name))
        gt_objects = hota._parse_gt_objects(frame_data)
        pred_objects = hota._parse_prediction_objects(
            frame_data, prediction_mode=prediction_mode)
        stats["raw_yolo_pred_dets"] += len(pred_objects)

        target_gt = gt_objects.get(target_id)
        target_raw = _target_raw_object(frame_data, target_id)
        target_pred_ids = [
            pr_id for pr_id, pred in pred_objects.items()
            if _is_target_prediction(pred, target_gt, target_id)
        ]
        if target_pred_ids and not stats["first_yolo_target_frame"]:
            stats["first_yolo_target_frame"] = frame_number
        if target_pred_ids:
            stats["raw_yolo_target_frames"] += 1

        has_v2x_message = (
            use_v2x_fusion and target_gt and
            awareness._v2x_in_range(frame_data, target_id, conflict_point,
                                    communication_range))
        if has_v2x_message:
            stable_track_state = _state_from_raw(target_raw, frame_number)
            if stable_track_state:
                stable_track_state["frame"] = (
                    frame_number + v2x_message_latency_frames)
            stable_track_age = 0
            stats["v2x_message_frames"] += 1

        has_stable_track = (
            use_v2x_fusion and stable_track_state is not None and
            (v2x_track_max_age < 0 or stable_track_age <= v2x_track_max_age))

        if has_stable_track:
            # Fusion should not double-count the same actor. Remove target-like
            # YOLO detections, then insert one cooperative actor track.
            for pr_id in target_pred_ids:
                pred_objects.pop(pr_id, None)
            stats["v2x_replaced_yolo_target_dets"] += len(target_pred_ids)

            pred_objects[target_id] = _fused_track_from_state(
                stable_track_state, target_id, frame_number, dt,
                v2x_position_noise_m, v2x_extent_scale)
            stats["v2x_added_frames"] += 1
            if not has_v2x_message:
                stats["v2x_predicted_frames"] += 1
            if not stats["first_fused_target_frame"]:
                stats["first_fused_target_frame"] = frame_number
        elif target_pred_ids and not stats["first_fused_target_frame"]:
            stats["first_fused_target_frame"] = frame_number
        if has_stable_track or target_pred_ids:
            stats["target_candidate_frames"] += 1

        frames.append((frame_number, gt_objects, pred_objects))
        if use_v2x_fusion and stable_track_state is not None:
            stable_track_age += 1

    return frames, stats


def _evaluate_observer(run_dir, observer_id, observer_dir, role,
                       scenario, protocol, target_id, alphas,
                       prediction_mode, fusion_roles,
                       frame_start=None, frame_end=None,
                       association_alpha=0.5,
                       v2x_track_max_age=DEFAULT_V2X_TRACK_MAX_AGE,
                       v2x_position_noise_m=DEFAULT_V2X_POSITION_NOISE_M,
                       v2x_extent_scale=DEFAULT_V2X_EXTENT_SCALE,
                       v2x_message_latency_frames=DEFAULT_V2X_MESSAGE_LATENCY_FRAMES):
    is_v2x_scenario = awareness._v2x_enabled(scenario)
    communication_range = awareness._communication_range(scenario, protocol)
    conflict_point = awareness._conflict_point(scenario)
    dt = float(((protocol.get("world") or {}).get("fixed_delta_seconds") or 0.1))
    use_v2x_fusion = is_v2x_scenario and role in fusion_roles

    frames, stats = _read_fused_sequence(
        observer_dir, target_id, use_v2x_fusion, conflict_point,
        communication_range, prediction_mode, dt, v2x_track_max_age,
        v2x_position_noise_m, v2x_extent_scale, v2x_message_latency_frames,
        frame_start=frame_start, frame_end=frame_end)

    alpha_results = [
        hota._calculate_for_alpha(
            frames, alpha,
            include_association_rows=abs(alpha - association_alpha) < 1e-9)
        for alpha in alphas
    ]
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
        "v2x_track_max_age": v2x_track_max_age,
        "v2x_position_noise_m": v2x_position_noise_m,
        "v2x_extent_scale": v2x_extent_scale,
        "v2x_message_latency_frames": v2x_message_latency_frames,
        "raw_yolo_pred_dets": stats["raw_yolo_pred_dets"],
        "v2x_added_frames": stats["v2x_added_frames"],
        "v2x_message_frames": stats["v2x_message_frames"],
        "v2x_predicted_frames": stats["v2x_predicted_frames"],
        "v2x_replaced_yolo_target_dets":
        stats["v2x_replaced_yolo_target_dets"],
        "raw_yolo_target_frames": stats["raw_yolo_target_frames"],
        "target_candidate_frames": stats["target_candidate_frames"],
        "first_yolo_target_frame": stats["first_yolo_target_frame"],
        "first_fused_target_frame": stats["first_fused_target_frame"],
    }

    detail_rows = []
    association_rows = []
    association_result = min(
        alpha_results, key=lambda r: abs(r["alpha"] - association_alpha))
    for assoc in association_result.get("association_rows", []):
        association_row = {
            "scenario": scenario_name,
            "run_time": run_time,
            "observer_id": observer_id,
            "observer_role": role,
            "perception_mode": MODE,
        }
        association_row.update(assoc)
        association_rows.append(association_row)

    for result in alpha_results:
        detail = {
            "scenario": scenario_name,
            "run_time": run_time,
            "observer_id": observer_id,
            "observer_role": role,
            "perception_mode": MODE,
        }
        detail.update({
            key: value for key, value in result.items()
            if key != "association_rows"
        })
        detail_rows.append(detail)

    return summary, detail_rows, association_rows


def _evaluate_run(run_dir, alphas, prediction_mode, fusion_roles,
                  role_filter=None, frame_start=None, frame_end=None,
                  association_alpha=0.5,
                  v2x_track_max_age=DEFAULT_V2X_TRACK_MAX_AGE,
                  v2x_position_noise_m=DEFAULT_V2X_POSITION_NOISE_M,
                  v2x_extent_scale=DEFAULT_V2X_EXTENT_SCALE,
                  v2x_message_latency_frames=DEFAULT_V2X_MESSAGE_LATENCY_FRAMES):
    scenario, protocol = awareness._scenario_config(run_dir)
    target_id = awareness._target_actor_id(run_dir, scenario)
    roles = hota._infer_roles(run_dir)
    summary_rows = []
    detail_rows = []
    association_rows = []

    for observer_id, observer_dir in hota._iter_observer_dirs(run_dir, None):
        role = roles.get(observer_id, "unknown")
        if role_filter and role not in role_filter:
            continue
        if role not in {"rsu", "ego"}:
            continue
        summary, details, associations = _evaluate_observer(
            run_dir, observer_id, observer_dir, role, scenario, protocol,
            target_id, alphas, prediction_mode, fusion_roles,
            frame_start=frame_start, frame_end=frame_end,
            association_alpha=association_alpha,
            v2x_track_max_age=v2x_track_max_age,
            v2x_position_noise_m=v2x_position_noise_m,
            v2x_extent_scale=v2x_extent_scale,
            v2x_message_latency_frames=v2x_message_latency_frames)
        summary_rows.append(summary)
        detail_rows.extend(details)
        association_rows.extend(associations)

    return summary_rows, detail_rows, association_rows


def _write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path, summary_rows, run_dirs, frame_start=None, frame_end=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [
        "# Scenario 1 Stable V2X-Fused Tracking HOTA",
        "",
        "Prediction definition: `YOLO/LiDAR detections + stable V2X actor track`.",
        "For No V2X runs, only YOLO/LiDAR detections are used.",
        "",
        "The V2X actor message updates a persistent actor track. If the "
        "message is temporarily unavailable, the track is propagated with the "
        "last actor velocity until `max_age` expires. Target-like YOLO "
        "detections are deduplicated against this stable V2X track.",
        "",
        "To avoid evaluating an unrealistically perfect CARLA ground-truth "
        "track, the V2X track is scored after deterministic localization "
        "noise, bbox extent scaling, and message latency are applied.",
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
        "TP/FP/FN | target candidate | V2X frames | predicted | first YOLO | first fused |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in summary_rows:
        observer = "%s(%s)" % (row["observer_role"], row["observer_id"])
        counts = "%s/%s/%s" % (
            row["TP_0.50"], row["FP_0.50"], row["FN_0.50"])
        lines.append(
            "| {scenario} | {observer} | {hota:.4f} | {deta:.4f} | "
            "{assa:.4f} | {counts} | {candidate} | {v2x_frames} | {predicted} | {first_yolo} | "
            "{first_fused} |".format(
                scenario=row["scenario"],
                observer=observer,
                hota=float(row["HOTA_mean"]),
                deta=float(row["DetA_0.50"]),
                assa=float(row["AssA_0.50"]),
                counts=counts,
                candidate=row["target_candidate_frames"],
                v2x_frames=row["v2x_added_frames"],
                predicted=row["v2x_predicted_frames"],
                first_yolo=row["first_yolo_target_frame"] or "-",
                first_fused=row["first_fused_target_frame"] or "-"))
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Calculate YOLO/LiDAR + V2X actor-message HOTA.")
    parser.add_argument("--run-dir", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--prediction-mode", default="yolov5_lidar_fusion")
    parser.add_argument("--role", action="append",
                        help="Optional observer role filter, e.g. rsu or ego.")
    parser.add_argument("--fusion-role", action="append",
                        choices=["ego", "rsu"],
                        help="Observer role that receives V2X actor tracks. "
                        "Defaults to ego and rsu.")
    parser.add_argument("--frame-start", type=int)
    parser.add_argument("--frame-end", type=int)
    parser.add_argument("--association-alpha", type=float, default=0.5)
    parser.add_argument("--v2x-track-max-age", type=int,
                        default=DEFAULT_V2X_TRACK_MAX_AGE,
                        help="Number of frames to keep predicting the V2X "
                        "track after the last actor message. Use -1 to keep "
                        "it for the rest of the evaluated sequence.")
    parser.add_argument("--v2x-position-noise-m", type=float,
                        default=DEFAULT_V2X_POSITION_NOISE_M,
                        help="Deterministic V2X localization noise amplitude "
                        "in meters.")
    parser.add_argument("--v2x-extent-scale", type=float,
                        default=DEFAULT_V2X_EXTENT_SCALE,
                        help="Scale applied to the V2X bbox extent before "
                        "IoU matching.")
    parser.add_argument("--v2x-message-latency-frames", type=int,
                        default=DEFAULT_V2X_MESSAGE_LATENCY_FRAMES,
                        help="Frame delay applied to each received V2X actor "
                        "message before fusion.")
    args = parser.parse_args()

    fusion_roles = set(args.fusion_role or DEFAULT_FUSION_ROLES)
    role_filter = set(args.role) if args.role else None

    summary_rows = []
    detail_rows = []
    association_rows = []
    for run_dir in args.run_dir:
        rows, details, associations = _evaluate_run(
            run_dir, DEFAULT_ALPHAS, args.prediction_mode, fusion_roles,
            role_filter=role_filter, frame_start=args.frame_start,
            frame_end=args.frame_end,
            association_alpha=args.association_alpha,
            v2x_track_max_age=args.v2x_track_max_age,
            v2x_position_noise_m=args.v2x_position_noise_m,
            v2x_extent_scale=args.v2x_extent_scale,
            v2x_message_latency_frames=args.v2x_message_latency_frames)
        summary_rows.extend(rows)
        detail_rows.extend(details)
        association_rows.extend(associations)

    if not summary_rows:
        raise SystemExit("No V2X-fused tracking KPI rows were generated.")

    _write_csv(os.path.join(args.output_dir, "tracking_kpi_summary.csv"),
               summary_rows)
    _write_csv(os.path.join(args.output_dir, "tracking_kpi_by_alpha.csv"),
               detail_rows)
    _write_csv(os.path.join(args.output_dir, "tracking_hota_association.csv"),
               association_rows)
    _write_report(os.path.join(args.output_dir, "tracking_kpi_report.md"),
                  summary_rows, args.run_dir,
                  frame_start=args.frame_start, frame_end=args.frame_end)
    print("Wrote V2X-fused tracking KPI to", args.output_dir)


if __name__ == "__main__":
    main()
