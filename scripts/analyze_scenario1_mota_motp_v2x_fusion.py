#!/usr/bin/env python
"""
Scenario 1 MOTA/MOTP with V2X actor-message fusion.

Definition:
  - No V2X prediction = YOLO/LiDAR detection
  - V2X prediction = YOLO/LiDAR detection + V2X actor message track

This script does not modify scenario files. It reads existing datadump YAML
files and writes analysis outputs under evaluation_outputs.
"""

import argparse
import csv
import os
import sys
from collections import Counter


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import analyze_scenario1_mota_motp_redefined as base  # noqa: E402
import calculate_tracking_hota as hota  # noqa: E402
import calculate_v2x_fused_awareness_hota as awareness  # noqa: E402
import calculate_v2x_fused_tracking_hota as fused_hota  # noqa: E402


DEFAULT_RUNS = [
    os.path.join(
        REPO_ROOT, "data_dumping", "scenario1_v2x", "2026_05_07_18_09_25"),
    os.path.join(
        REPO_ROOT, "data_dumping", "scenario1_no_v2x", "2026_05_07_18_14_14"),
]
DEFAULT_OUTPUT = os.path.join(
    REPO_ROOT, "evaluation_outputs",
    "scenario1_mota_motp_v2x_fusion_2026_05_21")
PREDICTION_MODE = "yolov5_lidar_fusion"
FUSED_MODE = "yolov5_lidar_fusion_plus_v2x_actor_message"


def _center_area_from_bbox(bbox):
    x1, y1, x2, y2 = bbox
    center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    return center, area


def _convert_fused_prediction(pred):
    center, area = _center_area_from_bbox(pred["bbox"])
    return {
        "id": pred["id"],
        "center": center,
        "bbox": pred["bbox"],
        "area": area,
        "bp_id": pred.get("bp_id", "v2x_actor"),
        "matched_gt_id": pred.get("matched_gt_id"),
        "match_distance_log": 0.0,
        "pcd": 0.0,
        "perception_mode": pred.get("perception_mode", "v2x_actor_track"),
    }


def _is_v2x_condition(scenario_name):
    return "v2x" in scenario_name and "no_v2x" not in scenario_name


def _load_sequence(run_dir, observer_dir, role, use_fusion,
                   frame_start=None, frame_end=None,
                   v2x_track_max_age=fused_hota.DEFAULT_V2X_TRACK_MAX_AGE,
                   v2x_position_noise_m=fused_hota.DEFAULT_V2X_POSITION_NOISE_M,
                   v2x_extent_scale=fused_hota.DEFAULT_V2X_EXTENT_SCALE,
                   v2x_message_latency_frames=(
                       fused_hota.DEFAULT_V2X_MESSAGE_LATENCY_FRAMES)):
    scenario, protocol = awareness._scenario_config(run_dir)
    scenario_name, _ = base._run_label(run_dir)
    is_v2x_run = _is_v2x_condition(scenario_name) and awareness._v2x_enabled(scenario)
    target_id = awareness._target_actor_id(run_dir, scenario)
    communication_range = awareness._communication_range(scenario, protocol)
    conflict_point = awareness._conflict_point(scenario)
    dt = float(((protocol.get("world") or {}).get("fixed_delta_seconds") or 0.1))
    apply_fusion = bool(use_fusion and is_v2x_run and role in {"ego", "rsu"})

    frames = []
    pred_lifetime = Counter()
    stats = {
        "target_actor_id": target_id,
        "v2x_fusion_applied": str(apply_fusion).lower(),
        "raw_yolo_pred_dets": 0,
        "raw_yolo_target_frames": 0,
        "v2x_message_frames": 0,
        "v2x_added_frames": 0,
        "v2x_predicted_frames": 0,
        "v2x_replaced_yolo_target_dets": 0,
        "first_yolo_target_frame": "",
        "first_fused_target_frame": "",
    }
    stable_track_state = None
    stable_track_age = 0

    yaml_files = sorted(
        name for name in os.listdir(observer_dir)
        if name.lower().endswith(".yaml") and name[:6].isdigit())

    for file_name in yaml_files:
        frame_number = int(file_name[:6])
        if frame_start is not None and frame_number < frame_start:
            continue
        if frame_end is not None and frame_number > frame_end:
            continue

        frame_data = base._load_yaml(os.path.join(observer_dir, file_name))
        gt = base._parse_gt(frame_data)
        preds = base._parse_predictions(frame_data, PREDICTION_MODE)
        stats["raw_yolo_pred_dets"] += len(preds)

        target_gt = gt.get(target_id)
        target_raw = fused_hota._target_raw_object(frame_data, target_id)
        target_pred_ids = [
            pr_id for pr_id, pred in preds.items()
            if fused_hota._is_target_prediction(pred, target_gt, target_id)
        ]
        if target_pred_ids:
            stats["raw_yolo_target_frames"] += 1
            if not stats["first_yolo_target_frame"]:
                stats["first_yolo_target_frame"] = frame_number

        has_v2x_message = (
            apply_fusion and target_gt is not None and
            awareness._v2x_in_range(frame_data, target_id, conflict_point,
                                    communication_range)
        )
        if has_v2x_message:
            stable_track_state = fused_hota._state_from_raw(
                target_raw, frame_number)
            if stable_track_state:
                stable_track_state["frame"] = (
                    frame_number + v2x_message_latency_frames)
            stable_track_age = 0
            stats["v2x_message_frames"] += 1

        has_stable_track = (
            apply_fusion and stable_track_state is not None and
            (v2x_track_max_age < 0 or stable_track_age <= v2x_track_max_age))
        if has_stable_track:
            for pr_id in target_pred_ids:
                preds.pop(pr_id, None)
            stats["v2x_replaced_yolo_target_dets"] += len(target_pred_ids)

            fused_pred = fused_hota._fused_track_from_state(
                stable_track_state, target_id, frame_number, dt,
                v2x_position_noise_m, v2x_extent_scale)
            preds[target_id] = _convert_fused_prediction(fused_pred)
            stats["v2x_added_frames"] += 1
            if not has_v2x_message:
                stats["v2x_predicted_frames"] += 1
            if not stats["first_fused_target_frame"]:
                stats["first_fused_target_frame"] = frame_number

        frame = {
            "frame": frame_number,
            "gt": gt,
            "preds": preds,
            "origin": base._observer_origin(frame_data),
        }
        frames.append(frame)
        for pr_id in preds:
            pred_lifetime[pr_id] += 1

        if apply_fusion and stable_track_state is not None:
            stable_track_age += 1

    return frames, pred_lifetime, stats


def _evaluate_run(run_dir, use_fusion, roles, frame_start=None, frame_end=None,
                  v2x_track_max_age=fused_hota.DEFAULT_V2X_TRACK_MAX_AGE,
                  v2x_position_noise_m=fused_hota.DEFAULT_V2X_POSITION_NOISE_M,
                  v2x_extent_scale=fused_hota.DEFAULT_V2X_EXTENT_SCALE,
                  v2x_message_latency_frames=(
                      fused_hota.DEFAULT_V2X_MESSAGE_LATENCY_FRAMES)):
    scenario_name, run_time = base._run_label(run_dir)
    condition = "V2X" if _is_v2x_condition(scenario_name) else "No V2X"
    observer_roles = hota._infer_roles(run_dir)
    rows = []

    for observer_id, observer_dir in hota._iter_observer_dirs(run_dir, None):
        role = observer_roles.get(observer_id, "unknown")
        if role not in roles:
            continue

        frames, pred_lifetime, stats = _load_sequence(
            run_dir, observer_dir, role, use_fusion,
            frame_start=frame_start, frame_end=frame_end,
            v2x_track_max_age=v2x_track_max_age,
            v2x_position_noise_m=v2x_position_noise_m,
            v2x_extent_scale=v2x_extent_scale,
            v2x_message_latency_frames=v2x_message_latency_frames)
        result = base._evaluate(
            frames, pred_lifetime, "center_distance", 5.0,
            roi_m=60.0, min_persistence=3, min_area=1.0,
            max_area=120.0)

        mode_label = "v2x_fused" if use_fusion and condition == "V2X" else "yolo_only"
        row = {
            "scenario": scenario_name,
            "condition": condition,
            "run_time": run_time,
            "observer_id": observer_id,
            "observer_role": role,
            "evaluation_mode": mode_label,
            "prediction_definition": (
                FUSED_MODE if mode_label == "v2x_fused" else PREDICTION_MODE),
            "match_method": "center_distance",
            "threshold_m": 5.0,
            "roi_m": 60.0,
            "min_persistence": 3,
            "min_area_m2": 1.0,
        }
        row.update({
            key: value for key, value in result.items()
            if key != "fp_causes"
        })
        row.update(stats)
        rows.append(row)
    return rows


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


def _float(row, key):
    try:
        return float(row[key])
    except (TypeError, ValueError):
        return 0.0


def _plot(output_dir, rows):
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover
        print("Plot skipped:", exc)
        return

    ego_rows = [
        row for row in rows
        if row["observer_role"] == "ego" and
        (row["condition"] == "No V2X" or row["evaluation_mode"] == "v2x_fused")
    ]
    order = {"No V2X": 0, "V2X": 1}
    ego_rows = sorted(ego_rows, key=lambda row: order[row["condition"]])
    labels = [
        "No V2X\nYOLO/LiDAR",
        "V2X\nYOLO/LiDAR + V2X",
    ]

    if len(ego_rows) == 2:
        x = list(range(2))
        motas = [_float(row, "mota") for row in ego_rows]
        motps = [_float(row, "motp_m") for row in ego_rows]
        fig, ax1 = plt.subplots(figsize=(8.8, 5.2))
        bars = ax1.bar(x, motas, color=["#d65a5a", "#3b82c4"],
                       width=0.45, label="MOTA")
        ax1.axhline(0, color="#555555", linewidth=1)
        ax1.set_ylabel("MOTA (higher is better)")
        ax1.set_ylim(min(-0.15, min(motas) - 0.05), max(0.7, max(motas) + 0.1))
        for bar, value in zip(bars, motas):
            ax1.text(
                bar.get_x() + bar.get_width() / 2.0,
                value + (0.025 if value >= 0 else -0.035),
                "%.3f" % value,
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontweight="bold")
        ax2 = ax1.twinx()
        ax2.plot(x, motps, color="#e36c0a", marker="o", linewidth=2.2,
                 label="MOTP center error")
        ax2.set_ylabel("MOTP center error (m, lower is better)")
        ax2.set_ylim(0.0, max(motps) * 1.35 if motps else 1.0)
        for xi, value in zip(x, motps):
            ax2.text(xi, value + 0.12, "%.2f m" % value,
                     ha="center", color="#b45309")
        ax1.set_xticks(x)
        ax1.set_xticklabels(labels)
        ax1.set_title("Scenario 1 MOTA/MOTP with V2X Fusion")
        ax1.grid(axis="y", linestyle="--", alpha=0.35)
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
        fig.tight_layout()
        fig.savefig(os.path.join(output_dir, "fig1_v2x_fusion_mota_motp.png"),
                    dpi=170)
        plt.close(fig)

        precision = [_float(row, "precision") for row in ego_rows]
        recall = [_float(row, "recall") for row in ego_rows]
        fig, ax = plt.subplots(figsize=(8.8, 5.2))
        width = 0.32
        ax.bar([i - width / 2.0 for i in x], precision, width,
               label="Precision", color="#2563a8")
        ax.bar([i + width / 2.0 for i in x], recall, width,
               label="Recall", color="#6aa84f")
        for i, value in enumerate(precision):
            ax.text(i - width / 2.0, value + 0.02, "%.3f" % value,
                    ha="center")
        for i, value in enumerate(recall):
            ax.text(i + width / 2.0, value + 0.02, "%.3f" % value,
                    ha="center")
        ax.set_ylim(0.0, 1.0)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel("Score")
        ax.set_title("Scenario 1 Ego Precision / Recall with V2X Fusion")
        ax.grid(axis="y", linestyle="--", alpha=0.35)
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(output_dir, "fig2_v2x_fusion_precision_recall.png"),
                    dpi=170)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(8.8, 5.2))
        width = 0.24
        ax.bar([i - width for i in x], [_float(row, "tp") for row in ego_rows],
               width, label="TP", color="#3b82c4")
        ax.bar(x, [_float(row, "fp") for row in ego_rows],
               width, label="FP", color="#d65a5a")
        ax.bar([i + width for i in x], [_float(row, "fn") for row in ego_rows],
               width, label="FN", color="#8a8f98")
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel("Count")
        ax.set_title("Scenario 1 Ego TP / FP / FN with V2X Fusion")
        ax.grid(axis="y", linestyle="--", alpha=0.35)
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(output_dir, "fig3_v2x_fusion_error_counts.png"),
                    dpi=170)
        plt.close(fig)


def _report(output_dir, rows):
    path = os.path.join(output_dir, "final_v2x_fusion_analysis.md")
    rows_sorted = sorted(rows, key=lambda row: (
        row["condition"], row["observer_role"], row["evaluation_mode"]))
    no_ego = next(row for row in rows_sorted
                  if row["condition"] == "No V2X" and row["observer_role"] == "ego")
    v2x_ego = next(row for row in rows_sorted
                   if row["condition"] == "V2X" and row["observer_role"] == "ego"
                   and row["evaluation_mode"] == "v2x_fused")

    def pct_drop(before, after):
        before = float(before)
        after = float(after)
        return ((before - after) / before * 100.0) if before else 0.0

    mota_delta = _float(v2x_ego, "mota") - _float(no_ego, "mota")
    motp_delta = _float(no_ego, "motp_m") - _float(v2x_ego, "motp_m")
    fp_drop = pct_drop(no_ego["fp"], v2x_ego["fp"])
    fn_drop = pct_drop(no_ego["fn"], v2x_ego["fn"])

    lines = [
        "# 시나리오1 V2X Fusion 기반 MOTA/MOTP 최종 분석",
        "",
        "## 계산 정의",
        "",
        "```text",
        "No V2X prediction = YOLO/LiDAR detection",
        "V2X prediction = YOLO/LiDAR detection + V2X actor message track",
        "```",
        "",
        "MOTA/MOTP 기준은 이전에 확정한 center-distance 기반 CLEAR MOT 기준을 유지했다.",
        "",
        "- TP: GT와 prediction 중심거리 <= 5 m",
        "- ROI: 관측자 기준 60 m",
        "- Track persistence: 3 frame 이상",
        "- bbox sanity: 1 m2 <= bbox area <= 120 m2",
        "- MOTP: matched GT와 prediction 중심거리 평균 오차(m), 낮을수록 좋음",
        "",
        "## 결과 요약",
        "",
        "| 조건 | 관측자 | prediction | MOTA | MOTP(m) | Precision | Recall | TP | FP | FN | IDSW | V2X frames |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows_sorted:
        lines.append(
            "| {condition} | {observer} | {mode} | {mota:.3f} | {motp:.2f} | "
            "{precision:.3f} | {recall:.3f} | {tp} | {fp} | {fn} | {idsw} | {v2x_frames} |".format(
                condition=row["condition"],
                observer=row["observer_role"],
                mode=row["evaluation_mode"],
                mota=_float(row, "mota"),
                motp=_float(row, "motp_m"),
                precision=_float(row, "precision"),
                recall=_float(row, "recall"),
                tp=row["tp"],
                fp=row["fp"],
                fn=row["fn"],
                idsw=row["idsw"],
                v2x_frames=row["v2x_added_frames"]))

    lines.extend([
        "",
        "## Ego 기준 V2X Fusion 효과",
        "",
        "| 항목 | No V2X YOLO/LiDAR | V2X Fusion | 변화 |",
        "|---|---:|---:|---:|",
        "| MOTA | {a:.3f} | {b:.3f} | +{d:.3f} |".format(
            a=_float(no_ego, "mota"), b=_float(v2x_ego, "mota"),
            d=mota_delta),
        "| MOTP | {a:.2f} m | {b:.2f} m | -{d:.2f} m |".format(
            a=_float(no_ego, "motp_m"), b=_float(v2x_ego, "motp_m"),
            d=motp_delta),
        "| FP | {a} | {b} | {d:.1f}% 감소 |".format(
            a=no_ego["fp"], b=v2x_ego["fp"], d=fp_drop),
        "| FN | {a} | {b} | {d:.1f}% 감소 |".format(
            a=no_ego["fn"], b=v2x_ego["fn"], d=fn_drop),
        "",
        "V2X fusion은 YOLO/LiDAR가 직접 안정적으로 잡지 못하는 critical actor에 대해 actor-message track을 prediction set에 추가한다. 따라서 이 결과는 YOLO detector 자체의 성능 향상이 아니라 cooperative perception/fusion을 적용했을 때의 최종 인지/추적 성능 향상으로 해석해야 한다.",
        "",
        "## 보고서용 문장",
        "",
        "본 연구에서는 No V2X 조건의 prediction을 YOLO/LiDAR detection으로 정의하고, V2X 조건의 prediction을 YOLO/LiDAR detection과 V2X actor message track을 결합한 fused prediction으로 정의하였다. 동일한 center-distance 기반 CLEAR MOT 기준을 적용한 결과, Ego 관측 기준에서 V2X fusion 조건은 No V2X 대비 MOTA가 {mota_delta:.3f} 증가하고 MOTP 중심거리 오차가 {motp_delta:.2f} m 감소하였다. 또한 FP와 FN이 각각 {fp_drop:.1f}%, {fn_drop:.1f}% 감소하여, V2X actor message가 가려짐 및 조기 인지 구간에서 critical actor tracking 안정성을 향상시키는 것으로 분석된다.".format(
            mota_delta=mota_delta,
            motp_delta=motp_delta,
            fp_drop=fp_drop,
            fn_drop=fn_drop),
    ])
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", action="append",
                        help="Scenario 1 run dir. Defaults to the 5/7 YOLO runs.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    parser.add_argument("--role", action="append",
                        help="Observer role. Defaults to ego and rsu.")
    parser.add_argument("--frame-start", type=int)
    parser.add_argument("--frame-end", type=int)
    parser.add_argument("--v2x-track-max-age", type=int,
                        default=fused_hota.DEFAULT_V2X_TRACK_MAX_AGE)
    parser.add_argument("--v2x-position-noise-m", type=float,
                        default=fused_hota.DEFAULT_V2X_POSITION_NOISE_M)
    parser.add_argument("--v2x-extent-scale", type=float,
                        default=fused_hota.DEFAULT_V2X_EXTENT_SCALE)
    parser.add_argument("--v2x-message-latency-frames", type=int,
                        default=fused_hota.DEFAULT_V2X_MESSAGE_LATENCY_FRAMES)
    args = parser.parse_args()

    roles = set(args.role or ["ego", "rsu"])
    run_dirs = args.run_dir or DEFAULT_RUNS
    rows = []
    for run_dir in run_dirs:
        condition = "V2X" if _is_v2x_condition(base._run_label(run_dir)[0]) else "No V2X"
        use_fusion = condition == "V2X"
        rows.extend(_evaluate_run(
            run_dir, use_fusion, roles,
            frame_start=args.frame_start, frame_end=args.frame_end,
            v2x_track_max_age=args.v2x_track_max_age,
            v2x_position_noise_m=args.v2x_position_noise_m,
            v2x_extent_scale=args.v2x_extent_scale,
            v2x_message_latency_frames=args.v2x_message_latency_frames))

    if not rows:
        raise SystemExit("No rows generated.")
    os.makedirs(args.output_dir, exist_ok=True)
    _write_csv(os.path.join(args.output_dir, "v2x_fusion_mota_motp_summary.csv"),
               rows)
    _plot(args.output_dir, rows)
    _report(args.output_dir, rows)
    print("Wrote Scenario 1 V2X-fused MOTA/MOTP analysis to %s" %
          args.output_dir)


if __name__ == "__main__":
    main()
