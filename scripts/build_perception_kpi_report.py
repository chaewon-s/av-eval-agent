#!/usr/bin/env python
"""
Build perception-evaluation KPI tables from tracking HOTA outputs.

The tracking scripts produce research metrics such as HOTA, MOTA, MOTP, DetA,
and AssA. This script reshapes them into perception-evaluation terms that can
be used directly in a scenario evaluation report.
"""

import argparse
import csv
import os

import matplotlib.pyplot as plt


SCENARIO_LABELS = {
    "scenario1_v2x": "V2X",
    "scenario1_no_v2x": "No V2X",
}
ROLE_LABELS = {
    "rsu": "RSU",
    "ego": "Ego",
}


def _read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _float(row, key):
    try:
        return float(row.get(key, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def _condition_label(row):
    return "%s-%s" % (
        SCENARIO_LABELS.get(row["scenario"], row["scenario"]),
        ROLE_LABELS.get(row["observer_role"], row["observer_role"]),
    )


def _critical_actor_tp(summary_row, association_rows):
    target_id = str(summary_row.get("target_actor_id", ""))
    if not target_id:
        return 0
    count = 0
    for assoc in association_rows:
        if assoc.get("scenario") != summary_row.get("scenario"):
            continue
        if assoc.get("observer_role") != summary_row.get("observer_role"):
            continue
        if str(assoc.get("gtID")) == target_id and str(assoc.get("prID")) == target_id:
            count += 1
    return count


def _convert_rows(rows, association_rows, window_name):
    output = []
    for row in rows:
        tp = _float(row, "TP_0.50")
        fp = _float(row, "FP_0.50")
        fn = _float(row, "FN_0.50")
        gt = _float(row, "gt_dets")
        pred = _float(row, "pred_dets")
        frames = _float(row, "frames")
        critical_iou50_tp = _critical_actor_tp(row, association_rows)
        critical_candidate_frames = int(_float(
            row, "target_candidate_frames")) or critical_iou50_tp
        output.append({
            "window": window_name,
            "condition": SCENARIO_LABELS.get(row["scenario"], row["scenario"]),
            "observer": ROLE_LABELS.get(row["observer_role"],
                                         row["observer_role"]),
            "scenario": row["scenario"],
            "observer_role": row["observer_role"],
            "frames": int(frames),
            "gt_objects": int(gt),
            "pred_objects": int(pred),
            "TP": int(tp),
            "FP": int(fp),
            "FN": int(fn),
            "IDSW": int(_float(row, "IDSW_0.50")),
            "critical_actor_candidate_frames": int(critical_candidate_frames),
            "critical_actor_strict_TP": int(critical_iou50_tp),
            "critical_actor_TP": int(critical_iou50_tp),
            "critical_actor_GT_frames": int(frames),
            "critical_actor_availability":
            _ratio(critical_candidate_frames, frames),
            "critical_actor_candidate_availability":
            _ratio(critical_candidate_frames, frames),
            "critical_actor_iou50_availability":
            _ratio(critical_iou50_tp, frames),
            "perception_availability": _ratio(tp, tp + fn),
            "miss_rate": _ratio(fn, tp + fn),
            "false_alarm_ratio": _ratio(fp, tp + fp),
            "precision": _ratio(tp, tp + fp),
            "detection_quality_DetA": _float(row, "DetA_0.50"),
            "association_stability_AssA": _float(row, "AssA_0.50"),
            "tracking_score_HOTA": _float(row, "HOTA_mean"),
            "tracking_accuracy_MOTA": _float(row, "MOTA_0.50"),
            "localization_precision_MOTP": _float(row, "MOTP_0.50"),
            "raw_yolo_target_frames": int(_float(
                row, "raw_yolo_target_frames")),
            "v2x_track_frames": int(_float(row, "v2x_added_frames")),
            "v2x_predicted_frames": int(_float(row, "v2x_predicted_frames")),
            "first_yolo_frame": row.get("first_yolo_target_frame") or "-",
            "first_available_frame": row.get("first_fused_target_frame") or "-",
        })
    return output


def _write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _format(value):
    if isinstance(value, float):
        return "%.4f" % value
    return str(value)


def _write_markdown(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [
        "# Scenario 1 Perception KPI Report",
        "",
        "Prediction definition:",
        "",
        "```text",
        "No V2X prediction = YOLO/LiDAR detection",
        "V2X prediction = YOLO/LiDAR detection + realistic stable V2X actor track",
        "```",
        "",
        "The V2X track includes localization noise, bbox extent scaling, and "
        "message latency from the tracking-summary input, so it is not scored "
        "as a perfect CARLA ground-truth track.",
        "",
        "The following table reframes tracking metrics as perception-evaluation KPIs.",
        "",
        "| window | condition | observer | critical actor recognition | critical IoU@0.50 | overall availability | miss rate | false alarm | "
        "HOTA | MOTA | MOTP | AssA | TP/FP/FN | critical cand/strict | first available |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        counts = "%s/%s/%s" % (row["TP"], row["FP"], row["FN"])
        critical_counts = "%s/%s" % (
            row["critical_actor_candidate_frames"],
            row["critical_actor_strict_TP"])
        lines.append(
            "| {window} | {condition} | {observer} | {critical_recognition} | {critical_iou50} | {availability} | "
            "{miss_rate} | {false_alarm} | {hota} | {mota} | {motp} | "
            "{assa} | {counts} | {critical_counts} | {first_available} |".format(
                window=row["window"],
                condition=row["condition"],
                observer=row["observer"],
                critical_recognition=_format(
                    row["critical_actor_candidate_availability"]),
                critical_iou50=_format(
                    row["critical_actor_iou50_availability"]),
                availability=_format(row["perception_availability"]),
                miss_rate=_format(row["miss_rate"]),
                false_alarm=_format(row["false_alarm_ratio"]),
                hota=_format(row["tracking_score_HOTA"]),
                mota=_format(row["tracking_accuracy_MOTA"]),
                motp=_format(row["localization_precision_MOTP"]),
                assa=_format(row["association_stability_AssA"]),
                counts=counts,
                critical_counts=critical_counts,
                first_available=row["first_available_frame"]))

    lines.extend([
        "",
        "## Interpretation Guide",
        "",
        "- `critical actor recognition`: frames with a critical-actor candidate track / evaluated frames. It captures whether the actor was recognized, independent of strict bbox overlap.",
        "- `critical IoU@0.50`: critical actor TP / evaluated frames under the strict IoU@0.50 matching rule. It captures localization-quality recognition.",
        "- `perception_availability`: all-object TP / (TP + FN) under IoU@0.50. Higher means objects were localized accurately enough for strict matching.",
        "- `miss_rate`: FN / (TP + FN). Lower means fewer missed objects.",
        "- `false_alarm_ratio`: FP / (TP + FP). Lower means fewer false positive tracks.",
        "- `HOTA`: combined detection and association tracking score.",
        "- `MOTA`: tracking accuracy penalized by FN, FP, and ID switches. It can become negative when FP/FN are large.",
        "- `MOTP`: average IoU similarity among matched TP objects. Higher means better localization precision among matched objects.",
        "- `AssA`: association stability. Higher means the same gtID and prID are linked consistently over time.",
        "",
        "Recommended report wording:",
        "",
        "> V2X-fused perception improves critical-actor recognition by adding a stable actor track from cooperative messages. No V2X-RSU may still produce object candidates, but low IoU@0.50 indicates that the limiting factor is precise localization and bbox matching rather than the complete absence of visual coverage.",
    ])
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def _plot_window(rows, window_name, output_path):
    rows = [row for row in rows if row["window"] == window_name]
    labels = [_condition_label(row) for row in rows]
    metrics = [
        ("critical_actor_availability", "Critical recognition", "#111827"),
        ("perception_availability", "Availability", "#2674BA"),
        ("tracking_score_HOTA", "HOTA", "#2A9D76"),
        ("association_stability_AssA", "AssA", "#8E5EA2"),
    ]
    x_positions = list(range(len(rows)))
    width = 0.18

    fig, ax = plt.subplots(figsize=(11, 5.6))
    for index, (key, label, color) in enumerate(metrics):
        xs = [x + (index - 1.5) * width for x in x_positions]
        ax.bar(xs, [row[key] for row in rows], width, label=label,
               color=color)
    ax.set_title("Perception KPI Profile (%s)" % window_name)
    ax.set_ylabel("Score")
    ax.set_ylim(0, 1.05)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=12, ha="right")
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, ncol=4)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _plot_miss_false_alarm(rows, window_name, output_path):
    rows = [row for row in rows if row["window"] == window_name]
    labels = [_condition_label(row) for row in rows]
    metrics = [
        ("miss_rate", "Miss rate", "#6B7280"),
        ("false_alarm_ratio", "False alarm ratio", "#D95F02"),
    ]
    x_positions = list(range(len(rows)))
    width = 0.32

    fig, ax = plt.subplots(figsize=(10.5, 5.4))
    for index, (key, label, color) in enumerate(metrics):
        xs = [x + (index - 0.5) * width for x in x_positions]
        ax.bar(xs, [row[key] for row in rows], width, label=label,
               color=color)
    ax.set_title("Perception Error Profile (%s)" % window_name)
    ax.set_ylabel("Ratio")
    ax.set_ylim(0, 1.05)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=12, ha="right")
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _plot_critical_actor_split(rows, window_name, output_path):
    rows = [row for row in rows if row["window"] == window_name]
    labels = [_condition_label(row) for row in rows]
    metrics = [
        ("critical_actor_candidate_availability", "Recognition candidate",
         "#111827"),
        ("critical_actor_iou50_availability", "IoU@0.50 TP", "#2A9D76"),
    ]
    x_positions = list(range(len(rows)))
    width = 0.32

    fig, ax = plt.subplots(figsize=(10.5, 5.4))
    for index, (key, label, color) in enumerate(metrics):
        xs = [x + (index - 0.5) * width for x in x_positions]
        bars = ax.bar(xs, [row[key] for row in rows], width, label=label,
                      color=color)
        ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=8)
    ax.set_title("Critical Actor Recognition vs Localization (%s)" %
                 window_name)
    ax.set_ylabel("Ratio")
    ax.set_ylim(0, 1.05)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=12, ha="right")
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="Build perception KPI report from tracking summaries.")
    parser.add_argument("--full-dir", required=True)
    parser.add_argument("--early-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    rows = []
    rows.extend(_convert_rows(
        _read_csv(os.path.join(args.full_dir, "tracking_kpi_summary.csv")),
        _read_csv(os.path.join(args.full_dir, "tracking_hota_association.csv")),
        "full_scenario"))
    rows.extend(_convert_rows(
        _read_csv(os.path.join(args.early_dir, "tracking_kpi_summary.csv")),
        _read_csv(os.path.join(args.early_dir, "tracking_hota_association.csv")),
        "early_occlusion"))

    os.makedirs(args.output_dir, exist_ok=True)
    _write_csv(os.path.join(args.output_dir, "perception_kpi_summary.csv"),
               rows)
    _write_markdown(os.path.join(args.output_dir, "perception_kpi_report.md"),
                    rows)
    _plot_window(
        rows, "full_scenario",
        os.path.join(args.output_dir, "perception_kpi_full_scenario.png"))
    _plot_window(
        rows, "early_occlusion",
        os.path.join(args.output_dir, "perception_kpi_early_occlusion.png"))
    _plot_miss_false_alarm(
        rows, "full_scenario",
        os.path.join(args.output_dir, "perception_error_full_scenario.png"))
    _plot_miss_false_alarm(
        rows, "early_occlusion",
        os.path.join(args.output_dir, "perception_error_early_occlusion.png"))
    _plot_critical_actor_split(
        rows, "full_scenario",
        os.path.join(args.output_dir,
                     "critical_actor_recognition_vs_iou50_full_scenario.png"))
    _plot_critical_actor_split(
        rows, "early_occlusion",
        os.path.join(args.output_dir,
                     "critical_actor_recognition_vs_iou50_early_occlusion.png"))
    print("Wrote perception KPI report to", args.output_dir)


if __name__ == "__main__":
    main()
