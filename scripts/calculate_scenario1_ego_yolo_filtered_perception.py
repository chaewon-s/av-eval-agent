#!/usr/bin/env python
"""Calculate ego-only YOLO/LiDAR MOTA/MOTP with fairer observation filters.

The goal is to avoid interpreting V2X driving behavior as a detector-quality
gain.  This script excludes RSU, V2X message fusion, and fallback perception,
then evaluates only ego-mounted YOLO/LiDAR predictions under explicit frame
filters:

- frame_index_pre_event: same frame-index range before the first event.
- actor_fov_only: frames where the critical actor is inside ego's front FOV.
- actor_fov_pre_event: critical actor in ego FOV and before collision/event.
"""

import argparse
import csv
import math
import os
import sys
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import analyze_scenario1_mota_motp_redefined as base  # noqa: E402
import calculate_tracking_hota as hota  # noqa: E402


PREDICTION_MODE = "yolov5_lidar_fusion"
DEFAULT_HORIZONS_S = [1.0, 2.0, 3.0, 5.0]
DEFAULT_DISPLAY_CONDITION = "V2X"


def _write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fields = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _scenario_condition(scenario):
    if "no_v2x" in scenario:
        return "No V2X"
    if "v2x" in scenario:
        return "V2X"
    return scenario


def _condition_slug(condition):
    return condition.lower().replace(" ", "_")


def _display_filter(rows, display_condition):
    if display_condition == "all":
        return list(rows)
    return [row for row in rows if row.get("condition") == display_condition]


def _fixed_delta_seconds(run_dir):
    protocol = hota._load_yaml(os.path.join(run_dir, "data_protocol.yaml"))
    return float(((protocol.get("world") or {}).get("fixed_delta_seconds"))
                 or 0.1)


def _ego_observer_dir(run_dir):
    roles = hota._infer_roles(run_dir)
    for observer_id, observer_dir in hota._iter_observer_dirs(run_dir, None):
        if roles.get(observer_id) == "ego":
            return observer_id, observer_dir
    raise RuntimeError("ego observer directory not found for %s" % run_dir)


def _yaw_forward(yaw_deg):
    yaw = math.radians(float(yaw_deg))
    return math.cos(yaw), math.sin(yaw)


def _angle_abs_deg(forward, rel):
    rel_norm = math.hypot(rel[0], rel[1])
    if rel_norm <= 1e-6:
        return 0.0
    dot = (forward[0] * rel[0] + forward[1] * rel[1]) / rel_norm
    dot = max(-1.0, min(1.0, dot))
    return abs(math.degrees(math.acos(dot)))


def _in_ego_front_fov(frame_data, obj, hfov_deg, max_range_m):
    ego = frame_data.get("true_ego_pos") or frame_data.get("predicted_ego_pos")
    if not isinstance(ego, list) or len(ego) < 5:
        return False
    center = base._center_xy(obj)
    if center is None:
        return False
    rel = (center[0] - float(ego[0]), center[1] - float(ego[1]))
    dist = math.hypot(rel[0], rel[1])
    if dist > max_range_m:
        return False
    forward = _yaw_forward(float(ego[4]))
    if forward[0] * rel[0] + forward[1] * rel[1] <= 0:
        return False
    return _angle_abs_deg(forward, rel) <= hfov_deg / 2.0


def _critical_actor_id(frame_data):
    candidates = []
    for key, obj in (frame_data.get("total_vehicles") or {}).items():
        bp_id = str(obj.get("bp_id", "")).lower()
        gt_id = base._int_or_none(obj.get("carla_id", key))
        if gt_id is None:
            continue
        if "dodge" in bp_id or "charger" in bp_id:
            return gt_id
        if "fusorosa" not in bp_id and "bus" not in bp_id:
            candidates.append(gt_id)
    return candidates[0] if candidates else None


def _vehicle_by_id(frame_data, vehicle_id):
    vehicles = frame_data.get("total_vehicles") or {}
    if vehicle_id in vehicles:
        return vehicles[vehicle_id]
    text_id = str(vehicle_id)
    if text_id in vehicles:
        return vehicles[text_id]
    for key, value in vehicles.items():
        if base._int_or_none(key) == vehicle_id:
            return value
        if base._int_or_none(value.get("carla_id")) == vehicle_id:
            return value
    return None


def _load_ego_frames(observer_dir, hfov_deg, max_range_m):
    frames = []
    pred_lifetime = Counter()
    files = sorted(
        name for name in os.listdir(observer_dir)
        if name.lower().endswith(".yaml") and name[:6].isdigit())
    subject_id = None
    for name in files:
        frame_no = int(name[:6])
        data = hota._load_yaml(os.path.join(observer_dir, name))
        if subject_id is None:
            subject_id = _critical_actor_id(data)
        gt = base._parse_gt(data)
        preds = base._parse_predictions(data, prediction_mode=PREDICTION_MODE)
        for pr_id in preds:
            pred_lifetime[pr_id] += 1
        subject_obj = _vehicle_by_id(data, subject_id)
        subject_in_fov = False
        if subject_obj:
            subject_in_fov = _in_ego_front_fov(
                data, subject_obj, hfov_deg, max_range_m)
        frames.append({
            "frame": frame_no,
            "data": data,
            "gt": gt,
            "preds": preds,
            "origin": base._observer_origin(data),
            "subject_id": subject_id,
            "subject_in_fov": subject_in_fov,
        })
    return frames, pred_lifetime, subject_id


def _event_frame(frames, subject_id, collision_distance_m):
    closest_frame = None
    closest_distance = float("inf")
    for frame in frames:
        data = frame["data"]
        ego = data.get("true_ego_pos") or data.get("predicted_ego_pos")
        subject = _vehicle_by_id(data, subject_id)
        if not isinstance(ego, list) or len(ego) < 2 or not subject:
            continue
        center = base._center_xy(subject)
        if center is None:
            continue
        dist = math.hypot(center[0] - float(ego[0]), center[1] - float(ego[1]))
        if dist < closest_distance:
            closest_distance = dist
            closest_frame = frame["frame"]
        if dist <= collision_distance_m:
            return frame["frame"], dist, "collision_threshold"
    return closest_frame, closest_distance, "closest_approach"


def _filter_objects_to_fov(frame, hfov_deg, max_range_m):
    data = frame["data"]
    gt = {}
    for gt_id, obj in frame["gt"].items():
        raw = _vehicle_by_id(data, gt_id)
        if raw and _in_ego_front_fov(data, raw, hfov_deg, max_range_m):
            gt[gt_id] = obj
    preds = {}
    for pr_id, pred in frame["preds"].items():
        raw_like = {
            "location": [pred["center"][0], pred["center"][1], 0.0],
        }
        if _in_ego_front_fov(data, raw_like, hfov_deg, max_range_m):
            preds[pr_id] = pred
    out = dict(frame)
    out["gt"] = gt
    out["preds"] = preds
    return out


def _select_frames(frames, mode, event_cutoff, hfov_deg, max_range_m,
                   common_frame_end=None):
    selected = []
    for frame in frames:
        if mode == "frame_index_pre_event":
            if common_frame_end is not None and frame["frame"] > common_frame_end:
                continue
        elif mode == "actor_fov_only":
            if not frame["subject_in_fov"]:
                continue
        elif mode == "actor_fov_pre_event":
            if not frame["subject_in_fov"] or frame["frame"] >= event_cutoff:
                continue
        else:
            raise ValueError("unknown mode: %s" % mode)
        selected.append(_filter_objects_to_fov(frame, hfov_deg, max_range_m))
    return selected


def _evaluate_frames(frames, pred_lifetime, args):
    return base._evaluate(
        frames,
        pred_lifetime,
        method="center_distance",
        threshold=args.match_distance_m,
        roi_m=args.roi_m,
        min_persistence=args.min_persistence,
        min_area=args.min_area,
        max_area=args.max_area,
    )


def _result_row(meta, result):
    row = dict(meta)
    for key, value in result.items():
        if key != "fp_causes":
            row[key] = value
    return row


def _window_average(frames, pred_lifetime, args, dt):
    rows = []
    for horizon_s in args.horizon_s:
        window_size = max(1, int(round(float(horizon_s) / dt)))
        results = []
        for start in range(0, len(frames), window_size):
            window = frames[start:start + window_size]
            if len(window) < max(1, window_size // 2):
                continue
            results.append(_evaluate_frames(window, pred_lifetime, args))
        if not results:
            continue

        def avg(key):
            return sum(float(r[key]) for r in results) / len(results)

        rows.append({
            "horizon_s": horizon_s,
            "window_count": len(results),
            "avg_mota": avg("mota"),
            "avg_motp_m": avg("motp_m"),
            "avg_precision": avg("precision"),
            "avg_recall": avg("recall"),
            "avg_tp": avg("tp"),
            "avg_fp": avg("fp"),
            "avg_fn": avg("fn"),
            "avg_idsw": avg("idsw"),
            "avg_gt_dets": avg("gt_dets"),
            "avg_pred_dets": avg("pred_dets"),
        })
    return rows


def _plot_horizon(output_dir, rows, mode, display_condition):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return []
    mode_rows = [r for r in rows if r["eval_mode"] == mode]
    if not mode_rows:
        return []
    manifest = []
    colors = {"V2X": "#4C92D9", "No V2X": "#D45A5A"}
    conditions = ["V2X", "No V2X"] if display_condition == "all" \
        else [display_condition]
    label_box = {
        "boxstyle": "round,pad=0.22",
        "facecolor": "white",
        "edgecolor": "none",
        "alpha": 0.86,
    }

    for metric, ylabel, filename in [
            ("avg_mota", "Average MOTA", "ego_yolo_fov_pre_event_mota.png"),
            ("avg_motp_m", "Average MOTP (m)",
             "ego_yolo_fov_pre_event_motp.png"),
            ("avg_recall", "Average Recall",
             "ego_yolo_fov_pre_event_recall.png"),
            ("avg_precision", "Average Precision",
             "ego_yolo_fov_pre_event_precision.png")]:
        fig, ax = plt.subplots(figsize=(10.6, 6.0))
        values = []
        for condition in conditions:
            cond_rows = sorted(
                [r for r in mode_rows if r["condition"] == condition],
                key=lambda r: float(r["horizon_s"]))
            if not cond_rows:
                continue
            xs = [float(r["horizon_s"]) for r in cond_rows]
            ys = [float(r[metric]) for r in cond_rows]
            values.extend(ys)
            ax.plot(xs, ys, marker="o", linewidth=2.4, markersize=7,
                    label=condition, color=colors.get(condition, "#555555"))
            offset = 10 if condition == "V2X" else -18
            for x_value, y_value in zip(xs, ys):
                ax.annotate("%.3f" % y_value, (x_value, y_value),
                            textcoords="offset points", xytext=(0, offset),
                            ha="center", fontsize=10, fontweight="bold",
                            bbox=label_box)
        if values:
            lo, hi = min(values), max(values)
            span = hi - lo if hi != lo else max(abs(hi), 1.0) * 0.1
            ax.set_ylim(lo - span * 0.35, hi + span * 0.55)
        title_scope = "All conditions" if display_condition == "all" \
            else "%s only" % display_condition
        ax.set_title(
            "Ego YOLO/LiDAR: Actor FOV + Pre-event (%s, %s)" %
            (ylabel, title_scope),
            fontsize=15, fontweight="bold", pad=14)
        ax.set_xlabel("Observation time horizon (s)", fontsize=12)
        ax.set_ylabel(ylabel, fontsize=12)
        ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13),
                  ncol=2, frameon=False)
        fig.tight_layout(rect=[0, 0.04, 1, 1])
        if display_condition != "all":
            stem, ext = os.path.splitext(filename)
            filename = "%s_%s%s" % (
                stem, _condition_slug(display_condition), ext)
        path = os.path.join(output_dir, filename)
        fig.savefig(path, dpi=180)
        plt.close(fig)
        manifest.append({
            "figure": filename,
            "metric": metric,
            "eval_mode": mode,
        })
    return manifest


def _write_report(output_dir, summary_rows, horizon_rows, event_rows,
                  display_condition):
    def fmt(value, digits=3):
        try:
            return ("%%.%df" % digits) % float(value)
        except (TypeError, ValueError):
            return str(value)

    lines = [
        "# Scenario 1 Ego-only YOLO/LiDAR Filtered Perception",
        "",
        "## Scope",
        "",
        "- Display condition: `%s`" % display_condition,
        "- Observer: ego only",
        "- Prediction: `yolov5_lidar_fusion` only",
        "- Excluded: RSU, V2X fused message tracks, semantic fallback",
        "- FOV filter: ego front camera cone approximation",
        "- Event cutoff: collision threshold if reached, otherwise closest approach",
        "- Observation time horizon: windowed average over `%s` seconds" %
        ", ".join(str(row) for row in sorted({
            r.get("horizon_s") for r in horizon_rows
            if r.get("horizon_s") is not None
        })),
        "",
        "## Event Cutoff",
        "",
        "| Condition | Run | Ego ID | Subject ID | Event frame | Basis | Distance |",
        "|---|---|---:|---:|---:|---|---:|",
    ]
    for row in event_rows:
        lines.append(
            "| {condition} | {run_time} | {ego_id} | {subject_id} | "
            "{event_frame} | {event_basis} | {event_distance_m} m |".format(
                condition=row["condition"],
                run_time=row["run_time"],
                ego_id=row["ego_id"],
                subject_id=row["subject_id"],
                event_frame=row["event_frame"],
                event_basis=row["event_basis"],
                event_distance_m=fmt(row["event_distance_m"], 2),
            ))

    lines.extend([
        "",
        "## Summary by Filter",
        "",
        "| Filter | Condition | Frames | GT | Pred | TP | FP | FN | IDSW | MOTA | MOTP | Precision | Recall |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in summary_rows:
        lines.append(
            "| {eval_mode} | {condition} | {frames} | {gt_dets} | "
            "{pred_dets} | {tp} | {fp} | {fn} | {idsw} | {mota} | "
            "{motp} m | {precision} | {recall} |".format(
                eval_mode=row["eval_mode"],
                condition=row["condition"],
                frames=row["frames"],
                gt_dets=row["gt_dets"],
                pred_dets=row["pred_dets"],
                tp=row["tp"],
                fp=row["fp"],
                fn=row["fn"],
                idsw=row["idsw"],
                mota=fmt(row["mota"]),
                motp=fmt(row["motp_m"]),
                precision=fmt(row["precision"]),
                recall=fmt(row["recall"]),
            ))

    lines.extend([
        "",
        "## Main Interpretation",
        "",
        "The default output is display-filtered to `%s` so the perception KPI is not presented as a V2X-vs-No-V2X detector comparison." % display_condition,
        "",
        "`actor_fov_pre_event` is the recommended ego-mounted perception KPI because it evaluates only frames where the critical actor is inside ego's front FOV and removes post-collision/post-event frames.",
        "",
        "Important: `frame_index_pre_event` is only a frame-index aligned reference. It is not a true same-input YOLO benchmark because V2X and No V2X runs do not contain identical ego camera/LiDAR images.",
        "",
        "Audit note: all-condition raw CSV files may be kept for traceability, but the report-facing figures and summary tables should use the display-filtered result.",
        "",
        "Recommended wording:",
        "",
        "> Ego-mounted YOLO/LiDAR perception was evaluated after restricting the analysis to frames where the critical actor was inside the ego vehicle's FOV and before the collision/closest-approach event. This avoids post-event stationary frames and reduces bias from unequal exposure durations. The result should be interpreted as onboard perception under each observation condition, not as a V2X fusion effect.",
    ])
    with open(os.path.join(output_dir, "ego_yolo_filtered_perception_report.md"),
              "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2x-run-dir", required=True)
    parser.add_argument("--no-v2x-run-dir")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--horizon-s", action="append", type=float,
                        default=DEFAULT_HORIZONS_S)
    parser.add_argument("--match-distance-m", type=float, default=5.0)
    parser.add_argument("--roi-m", type=float, default=60.0)
    parser.add_argument("--min-persistence", type=int, default=3)
    parser.add_argument("--min-area", type=float, default=1.0)
    parser.add_argument("--max-area", type=float, default=120.0)
    parser.add_argument("--ego-hfov-deg", type=float, default=110.0)
    parser.add_argument("--ego-fov-range-m", type=float, default=70.0)
    parser.add_argument("--collision-distance-m", type=float, default=4.5)
    parser.add_argument("--display-condition", default=DEFAULT_DISPLAY_CONDITION,
                        choices=["V2X", "No V2X", "all"],
                        help="Condition shown in report-facing outputs. "
                             "Use all only for audit/debug comparison.")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    if args.display_condition in ("No V2X", "all") and \
            not args.no_v2x_run_dir:
        parser.error("--no-v2x-run-dir is required when display condition is "
                     "No V2X or all")

    run_inputs = [args.v2x_run_dir]
    if args.no_v2x_run_dir:
        run_inputs.append(args.no_v2x_run_dir)
    loaded = []
    common_event_end = None
    for run_dir in run_inputs:
        scenario, run_time = base._run_label(run_dir)
        condition = _scenario_condition(scenario)
        ego_id, ego_dir = _ego_observer_dir(run_dir)
        frames, pred_lifetime, subject_id = _load_ego_frames(
            ego_dir, args.ego_hfov_deg, args.ego_fov_range_m)
        event_frame, event_distance, event_basis = _event_frame(
            frames, subject_id, args.collision_distance_m)
        loaded.append({
            "run_dir": run_dir,
            "scenario": scenario,
            "condition": condition,
            "run_time": run_time,
            "ego_id": ego_id,
            "subject_id": subject_id,
            "frames": frames,
            "pred_lifetime": pred_lifetime,
            "event_frame": event_frame,
            "event_distance_m": event_distance,
            "event_basis": event_basis,
            "dt": _fixed_delta_seconds(run_dir),
        })
        event_end = event_frame - 1 if event_frame else None
        if event_end is not None:
            common_event_end = (
                event_end if common_event_end is None
                else min(common_event_end, event_end))

    summary_rows = []
    horizon_rows = []
    event_rows = []
    modes = ["frame_index_pre_event", "actor_fov_only", "actor_fov_pre_event"]
    for item in loaded:
        event_rows.append({
            "condition": item["condition"],
            "scenario": item["scenario"],
            "run_time": item["run_time"],
            "ego_id": item["ego_id"],
            "subject_id": item["subject_id"],
            "event_frame": item["event_frame"],
            "event_distance_m": item["event_distance_m"],
            "event_basis": item["event_basis"],
            "common_frame_index_end": common_event_end,
        })
        for mode in modes:
            selected = _select_frames(
                item["frames"], mode, item["event_frame"],
                args.ego_hfov_deg, args.ego_fov_range_m,
                common_frame_end=common_event_end)
            meta = {
                "scenario": item["scenario"],
                "condition": item["condition"],
                "run_time": item["run_time"],
                "ego_id": item["ego_id"],
                "subject_id": item["subject_id"],
                "eval_mode": mode,
                "prediction_mode": PREDICTION_MODE,
                "selected_frame_start": selected[0]["frame"] if selected else "",
                "selected_frame_end": selected[-1]["frame"] if selected else "",
                "event_frame": item["event_frame"],
                "event_basis": item["event_basis"],
                "match_distance_m": args.match_distance_m,
                "roi_m": args.roi_m,
                "min_persistence": args.min_persistence,
                "ego_hfov_deg": args.ego_hfov_deg,
                "ego_fov_range_m": args.ego_fov_range_m,
            }
            summary_rows.append(_result_row(
                meta, _evaluate_frames(selected, item["pred_lifetime"], args)))
            for row in _window_average(
                    selected, item["pred_lifetime"], args, item["dt"]):
                horizon_row = dict(meta)
                horizon_row.update(row)
                horizon_rows.append(horizon_row)

    display_summary_rows = _display_filter(summary_rows, args.display_condition)
    display_horizon_rows = _display_filter(horizon_rows, args.display_condition)
    display_event_rows = _display_filter(event_rows, args.display_condition)

    _write_csv(os.path.join(args.output_dir,
                            "ego_yolo_filtered_mota_motp_summary.csv"),
               display_summary_rows)
    _write_csv(os.path.join(args.output_dir,
                            "ego_yolo_filtered_mota_motp_by_horizon.csv"),
               display_horizon_rows)
    _write_csv(os.path.join(args.output_dir,
                            "ego_yolo_filtered_event_metadata.csv"),
               display_event_rows)
    _write_csv(os.path.join(args.output_dir,
                            "ego_yolo_filtered_mota_motp_summary_all_conditions.csv"),
               summary_rows)
    _write_csv(os.path.join(args.output_dir,
                            "ego_yolo_filtered_mota_motp_by_horizon_all_conditions.csv"),
               horizon_rows)
    _write_csv(os.path.join(args.output_dir,
                            "ego_yolo_filtered_event_metadata_all_conditions.csv"),
               event_rows)
    manifest = _plot_horizon(
        args.output_dir, display_horizon_rows, "actor_fov_pre_event",
        args.display_condition)
    _write_csv(os.path.join(args.output_dir, "figure_manifest.csv"), manifest)
    _write_report(args.output_dir, display_summary_rows, display_horizon_rows,
                  display_event_rows, args.display_condition)
    print("Wrote ego-only filtered YOLO perception KPIs to", args.output_dir)


if __name__ == "__main__":
    main()
