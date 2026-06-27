#!/usr/bin/env python
"""
Plot tracking KPI CSV outputs from calculate_tracking_hota.py.
"""

import argparse
import csv
import os

import matplotlib.pyplot as plt


def _float(row, key):
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return 0.0


def _label(row):
    scenario = row["scenario"].replace("scenario1_", "")
    role = row["observer_role"]
    return "%s %s" % (scenario, role)


def _read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _save_summary_bars(rows, output_path):
    rows = [r for r in rows if r.get("perception_mode") == "yolov5_lidar_fusion"]
    labels = [_label(r) for r in rows]
    metrics = ["HOTA_0.50", "DetA_0.50", "AssA_0.50"]
    colors = ["#2674ba", "#d95f02", "#2a9d76"]
    width = 0.24
    x_positions = list(range(len(rows)))

    fig, ax = plt.subplots(figsize=(10, 5))
    for index, metric in enumerate(metrics):
        values = [_float(r, metric) for r in rows]
        xs = [x + (index - 1) * width for x in x_positions]
        ax.bar(xs, values, width, label=metric, color=colors[index])

    ax.set_title("YOLOv5 Tracking KPI at IoU alpha 0.50")
    ax.set_ylabel("Score")
    ax.set_ylim(0, 1)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _save_error_counts(rows, output_path):
    rows = [r for r in rows if r.get("perception_mode") == "yolov5_lidar_fusion"]
    labels = [_label(r) for r in rows]
    tp = [_float(r, "TP_0.50") for r in rows]
    fp = [_float(r, "FP_0.50") for r in rows]
    fn = [_float(r, "FN_0.50") for r in rows]
    x_positions = list(range(len(rows)))

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x_positions, tp, label="TP", color="#2a9d76")
    ax.bar(x_positions, fp, bottom=tp, label="FP", color="#d95f02")
    bottoms = [a + b for a, b in zip(tp, fp)]
    ax.bar(x_positions, fn, bottom=bottoms, label="FN", color="#6b7280")
    ax.set_title("YOLOv5 Tracking Error Counts at IoU alpha 0.50")
    ax.set_ylabel("Detections")
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _save_alpha_curve(rows, output_path):
    rows = [r for r in rows if r.get("perception_mode") == "yolov5_lidar_fusion"]
    groups = {}
    for row in rows:
        groups.setdefault(_label(row), []).append(row)

    fig, ax = plt.subplots(figsize=(10, 5))
    for label, group_rows in sorted(groups.items()):
        group_rows.sort(key=lambda r: _float(r, "alpha"))
        ax.plot([_float(r, "alpha") for r in group_rows],
                [_float(r, "HOTA") for r in group_rows],
                marker="o", linewidth=1.8, markersize=3.5, label=label)

    ax.set_title("YOLOv5 HOTA Curve by IoU Alpha")
    ax.set_xlabel("IoU alpha")
    ax.set_ylabel("HOTA")
    ax.set_ylim(0, 1)
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Plot tracking KPI CSV files.")
    parser.add_argument("--input-dir", required=True)
    args = parser.parse_args()

    summary_path = os.path.join(args.input_dir, "tracking_kpi_summary.csv")
    detail_path = os.path.join(args.input_dir, "tracking_kpi_by_alpha.csv")
    summary_rows = _read_csv(summary_path)
    detail_rows = _read_csv(detail_path)

    _save_summary_bars(
        summary_rows, os.path.join(args.input_dir, "tracking_kpi_summary.png"))
    _save_error_counts(
        summary_rows, os.path.join(args.input_dir, "tracking_error_counts.png"))
    _save_alpha_curve(
        detail_rows, os.path.join(args.input_dir, "tracking_hota_alpha_curve.png"))

    print("Wrote plots to", args.input_dir)


if __name__ == "__main__":
    main()
