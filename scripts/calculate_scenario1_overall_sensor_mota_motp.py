#!/usr/bin/env python
"""Calculate overall sensor-only MOTA/MOTP for Scenario 1.

Unlike the critical-actor awareness KPI, this script evaluates the full sensor
prediction set against all CARLA GT vehicles in each observer frame.

Recommended matching:
- center-distance <= 5 m
- observer ROI <= 60 m
- prediction track persistence >= 3 frames
- prediction bbox area in [1, 120] m2

MOTP is reported as mean matched center-distance error in meters.
"""

import argparse
import csv
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import analyze_scenario1_mota_motp_redefined as base  # noqa: E402
import calculate_tracking_hota as hota  # noqa: E402


DEFAULT_HORIZONS_S = [1.0, 2.0, 3.0, 5.0]
DEFAULT_ROI_M = 60.0
DEFAULT_MATCH_DISTANCE_M = 5.0
DEFAULT_MIN_PERSISTENCE = 3
DEFAULT_MIN_AREA = 1.0
DEFAULT_MAX_AREA = 120.0
VALID_SENSOR_MODES = {"yolov5_lidar_fusion"}
GT_LIKE_FALLBACK_MODES = {"semantic_lidar_fallback"}


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


def _scenario_condition(scenario):
    if "no_v2x" in scenario:
        return "No V2X"
    if "v2x" in scenario:
        return "V2X"
    return scenario


def _fixed_delta_seconds(run_dir):
    protocol = hota._load_yaml(os.path.join(run_dir, "data_protocol.yaml"))
    return float(((protocol.get("world") or {}).get("fixed_delta_seconds")) or 0.1)


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


def _load_sequence_sensor_predictions(observer_dir, include_fallback=False):
    frames = []
    pred_lifetime = base.Counter()
    mode_counts = base.Counter()
    excluded_mode_counts = base.Counter()
    files = sorted(
        name for name in os.listdir(observer_dir)
        if name.lower().endswith(".yaml") and name[:6].isdigit())
    for name in files:
        frame_no = int(name[:6])
        data = base._load_yaml(os.path.join(observer_dir, name))
        gt = base._parse_gt(data)
        preds = {}
        for index, (key, obj) in enumerate((data.get("vehicles") or {}).items()):
            mode = obj.get("perception_mode", "")
            if mode in VALID_SENSOR_MODES or (include_fallback and
                                               mode in GT_LIKE_FALLBACK_MODES):
                pr_id = base._int_or_none(obj.get("pr_id"))
                if pr_id is None:
                    pr_id = base._int_or_none(obj.get("carla_id"))
                if pr_id is None:
                    pr_id = index
                center = base._center_xy(obj)
                bbox = base._bbox_bev(obj)
                if center is None or bbox is None:
                    continue
                pred = {
                    "id": pr_id,
                    "center": center,
                    "bbox": bbox,
                    "area": base._bbox_area(obj),
                    "bp_id": obj.get("bp_id", "detected_vehicle"),
                    "matched_gt_id": base._int_or_none(
                        obj.get("matched_gt_id")),
                    "match_distance_log": base._safe_float(
                        obj.get("match_distance")),
                    "pcd": base._safe_float(obj.get("number of pcd")),
                    "perception_mode": mode,
                }
                preds[pr_id] = pred
                mode_counts[mode] += 1
            else:
                excluded_mode_counts[mode] += 1
        origin = base._observer_origin(data)
        for pr_id in preds:
            pred_lifetime[pr_id] += 1
        frames.append({
            "frame": frame_no,
            "gt": gt,
            "preds": preds,
            "origin": origin,
        })
    return frames, pred_lifetime, dict(mode_counts), dict(excluded_mode_counts)


def _result_row(base_row, result):
    row = dict(base_row)
    for key, value in result.items():
        if key == "fp_causes":
            continue
        row[key] = value
    for key, value in result.get("fp_causes", {}).items():
        row["cause_%s" % key] = value
    if row.get("metric_valid") == "false":
        for key in ("mota", "motp_m", "mean_iou", "precision", "recall"):
            row[key] = ""
    return row


def _evaluate_run(run_dir, args):
    scenario, run_time = base._run_label(run_dir)
    condition = _scenario_condition(scenario)
    roles = hota._infer_roles(run_dir)
    dt = _fixed_delta_seconds(run_dir)
    summary_rows = []
    horizon_rows = []

    for observer_id, observer_dir in hota._iter_observer_dirs(run_dir, None):
        role = roles.get(observer_id, "unknown")
        if role not in set(args.role):
            continue
        frames, pred_lifetime, mode_counts, excluded_mode_counts = (
            _load_sequence_sensor_predictions(
                observer_dir, include_fallback=args.include_fallback))
        if not frames:
            continue

        base_row = {
            "scenario": scenario,
            "condition": condition,
            "run_time": run_time,
            "observer_role": role,
            "observer_id": observer_id,
            "matching": "center_distance",
            "match_distance_m": args.match_distance_m,
            "roi_m": args.roi_m,
            "min_persistence": args.min_persistence,
            "min_area": args.min_area,
            "max_area": args.max_area,
            "scope": "overall_sensor_all_gt_vehicles",
            "valid_sensor_modes": ",".join(sorted(VALID_SENSOR_MODES)),
            "included_prediction_modes": ";".join(
                "%s:%s" % (key, value)
                for key, value in sorted(mode_counts.items())),
            "excluded_prediction_modes": ";".join(
                "%s:%s" % (key, value)
                for key, value in sorted(excluded_mode_counts.items())),
            "motp_valid": "true" if mode_counts else "false",
            "mota_valid": "true" if mode_counts else "false",
            "metric_valid": "true" if mode_counts else "false",
            "validity_note": (
                "valid_yolov5_lidar_fusion_sensor_predictions"
                if mode_counts else
                "invalid_no_real_sensor_predictions_after_excluding_gt_like_fallback"),
        }
        summary_rows.append(
            _result_row(dict(base_row, window="full_run"),
                        _evaluate_frames(frames, pred_lifetime, args)))

        for horizon_s in args.horizon_s:
            window_size = max(1, int(round(float(horizon_s) / dt)))
            window_results = []
            for start in range(0, len(frames), window_size):
                window = frames[start:start + window_size]
                if len(window) < max(1, window_size // 2):
                    continue
                result = _evaluate_frames(window, pred_lifetime, args)
                window_results.append(result)
            if not window_results:
                continue

            def avg(key):
                return sum(float(r[key]) for r in window_results) / len(window_results)

            horizon_row = {
                **base_row,
                "horizon_s": horizon_s,
                "window_count": len(window_results),
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
            }
            if base_row["metric_valid"] == "false":
                for key in ("avg_mota", "avg_motp_m", "avg_precision",
                            "avg_recall"):
                    horizon_row[key] = ""
            horizon_rows.append(horizon_row)
    return summary_rows, horizon_rows


def _label_bar(ax, bars, fmt):
    ax.bar_label(
        bars,
        fmt=fmt,
        padding=6,
        fontsize=9,
        fontweight="bold",
        bbox={
            "boxstyle": "round,pad=0.2",
            "facecolor": "white",
            "edgecolor": "none",
            "alpha": 0.86,
        },
    )


def _style(ax):
    ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _float_or_none(value):
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _plot_summary(output_dir, rows):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return []
    if not rows:
        return []

    manifest = []
    rows = sorted(rows, key=lambda r: (r["observer_role"], r["condition"]))
    labels = ["%s-%s" % (r["condition"], r["observer_role"].upper()) for r in rows]
    x = list(range(len(rows)))
    width = 0.35

    fig, ax1 = plt.subplots(figsize=(12.0, 6.4))
    mota_values = [_float_or_none(r.get("mota")) for r in rows]
    motp_values = [
        _float_or_none(r.get("motp_m")) if r.get("motp_valid") == "true"
        else None
        for r in rows
    ]
    bars = ax1.bar([v - width / 2 for v in x],
                   [v if v is not None else 0.0 for v in mota_values], width,
                   color="#4C8FD3", label="MOTA")
    ax1.axhline(0.0, color="#111827", linewidth=1.0)
    ax1.set_ylabel("MOTA (higher is better)")
    valid_mota = [value for value in mota_values if value is not None]
    ax1.set_ylim(min(-0.2, min(valid_mota or [0.0]) * 1.25),
                 max(1.05, max(valid_mota or [0.0]) * 1.25))
    ax2 = ax1.twinx()
    valid_x = [xi for xi, value in zip(x, motp_values) if value is not None]
    valid_motp = [value for value in motp_values if value is not None]
    line = ax2.plot(valid_x, valid_motp, color="#D95F02", marker="o",
                    linewidth=2.2, label="MOTP center error")
    ax2.set_ylabel("MOTP center error (m, lower is better)")
    ax2.set_ylim(0, max(5.0, max(valid_motp or [0.0]) * 1.35))
    _label_bar(ax1, bars, "%.2f")
    for xi, value in zip(x, mota_values):
        if value is None:
            ax1.annotate(
                "N/A",
                xy=(xi - width / 2, 0.05),
                xytext=(0, 8),
                textcoords="offset points",
                ha="center",
                fontsize=8.5,
                fontweight="bold",
                color="#D45A5A",
                bbox={
                    "boxstyle": "round,pad=0.2",
                    "facecolor": "white",
                    "edgecolor": "none",
                    "alpha": 0.86,
                },
            )
    for xi, value in zip(x, motp_values):
        if value is None:
            text = "N/A\nfallback excluded"
            y_value = 0.18
            color = "#D45A5A"
        else:
            text = "%.2fm" % value
            y_value = value
            color = "#111827"
        ax2.annotate(
            text,
            xy=(xi, y_value),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            fontsize=8.5,
            fontweight="bold",
            color=color,
            bbox={
                "boxstyle": "round,pad=0.2",
                "facecolor": "white",
                "edgecolor": "none",
                "alpha": 0.86,
            },
        )
    ax1.set_title("Overall Sensor MOTA/MOTP", fontsize=17,
                  fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=12, ha="right")
    _style(ax1)
    ax2.spines["top"].set_visible(False)
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, frameon=False,
               loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2)
    path = os.path.join(output_dir, "fig9_overall_sensor_mota_motp.png")
    fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    manifest.append({
        "file": os.path.basename(path),
        "title": "Overall sensor MOTA/MOTP",
        "path": path,
    })

    fig, ax = plt.subplots(figsize=(12.0, 6.2))
    precision = [
        100.0 * value if (value := _float_or_none(r.get("precision"))) is not None
        else 0.0 for r in rows
    ]
    recall = [
        100.0 * value if (value := _float_or_none(r.get("recall"))) is not None
        else 0.0 for r in rows
    ]
    bars1 = ax.bar([v - width / 2 for v in x], precision, width,
                   color="#2A9D76", label="Precision")
    bars2 = ax.bar([v + width / 2 for v in x], recall, width,
                   color="#D45A5A", label="Recall")
    _label_bar(ax, bars1, "%.1f%%")
    _label_bar(ax, bars2, "%.1f%%")
    ax.set_title("Overall Sensor Precision / Recall", fontsize=17,
                 fontweight="bold")
    ax.set_ylabel("Score (%)")
    ax.set_ylim(0, 112)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=12, ha="right")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.16),
              ncol=2)
    _style(ax)
    path = os.path.join(output_dir, "fig10_overall_sensor_precision_recall.png")
    fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    manifest.append({
        "file": os.path.basename(path),
        "title": "Overall sensor precision and recall",
        "path": path,
    })
    return manifest


def _plot_horizon(output_dir, rows):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return []
    if not rows:
        return []
    rows = [row for row in rows if row.get("motp_valid") == "true"]
    if not rows:
        return []
    manifest = []
    colors = {
        ("V2X", "ego"): "#4C8FD3",
        ("No V2X", "ego"): "#D45A5A",
        ("V2X", "rsu"): "#2A9D76",
        ("No V2X", "rsu"): "#D95F02",
    }
    for key, ylabel, filename, title in [
            ("avg_mota", "Average MOTA", "fig11_overall_sensor_mota_horizon.png",
             "Overall Sensor MOTA by Observation Horizon"),
            ("avg_motp_m", "Average MOTP center error (m)",
             "fig12_overall_sensor_motp_horizon.png",
             "Overall Sensor MOTP by Observation Horizon")]:
        grouped = {}
        for row in rows:
            if row.get("metric_valid") != "true":
                continue
            group = (row["condition"], row["observer_role"])
            grouped.setdefault(group, []).append(row)
        if not grouped:
            continue
        fig, ax = plt.subplots(figsize=(12.0, 6.4))
        for group, group_rows in sorted(grouped.items()):
            group_rows = sorted(group_rows, key=lambda r: float(r["horizon_s"]))
            xs = [float(r["horizon_s"]) for r in group_rows]
            ys = [float(r[key]) for r in group_rows]
            label = "%s-%s" % (group[0], group[1].upper())
            ax.plot(xs, ys, marker="o", linewidth=2.2, markersize=6,
                    color=colors.get(group), label=label)
            for x_value, y_value in zip(xs, ys):
                suffix = "m" if key == "avg_motp_m" else ""
                ax.annotate(
                    "%.2f%s" % (y_value, suffix),
                    xy=(x_value, y_value),
                    xytext=(0, 10),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8.5,
                    fontweight="bold",
                    bbox={
                        "boxstyle": "round,pad=0.18",
                        "facecolor": "white",
                        "edgecolor": "none",
                        "alpha": 0.84,
                    },
                )
        ax.set_title(title, fontsize=17, fontweight="bold")
        ax.set_xlabel("Observation horizon (s)")
        ax.set_ylabel(ylabel)
        if key == "avg_mota":
            ax.axhline(0.0, color="#111827", linewidth=1.0)
        else:
            ax.set_ylim(bottom=0.0)
        ax.legend(frameon=False, loc="upper center",
                  bbox_to_anchor=(0.5, -0.15), ncol=2)
        _style(ax)
        path = os.path.join(output_dir, filename)
        fig.tight_layout()
        fig.savefig(path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        manifest.append({
            "file": filename,
            "title": title,
            "path": path,
        })
    return manifest


def _write_report(output_dir, summary_rows, horizon_rows):
    lines = [
        "# Scenario 1 Overall Sensor MOTA/MOTP",
        "",
        "This report evaluates full sensor perception performance, not only the critical actor.",
        "",
        "## Definition",
        "",
        "- GT: all CARLA `total_vehicles` inside observer ROI.",
        "- Prediction: all sensor `vehicles` outputs.",
        "- Matching: center-distance <= 5 m.",
        "- MOTP: mean matched center-distance error in meters. Lower is better.",
        "- MOTA: `1 - (FN + FP + IDSW) / GT`. Higher is better.",
        "",
        "## Full-Run Summary",
        "",
        "| condition | observer | MOTA | MOTP(m) | precision | recall | TP/FP/FN/IDSW | GT | Pred |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        counts = "%s/%s/%s/%s" % (row["tp"], row["fp"], row["fn"], row["idsw"])
        lines.append(
            "| {condition} | {observer} | {mota} | {motp} | "
            "{precision:.3f} | {recall:.3f} | {counts} | {gt} | {pred} |".format(
                condition=row["condition"],
                observer=row["observer_role"],
                mota=("%.3f" % float(row["mota"])
                      if row.get("mota_valid") == "true" else "N/A"),
                motp=("%.2f" % float(row["motp_m"])
                      if row.get("motp_valid") == "true" else "N/A"),
                precision=(_float_or_none(row.get("precision")) or 0.0),
                recall=(_float_or_none(row.get("recall")) or 0.0),
                counts=counts,
                gt=row["gt_dets"],
                pred=row["pred_dets"],
            ))
    lines.extend([
        "",
        "## Note",
        "",
        "This metric can differ from the critical-actor awareness KPI. A sensor can perform well over all easy visible vehicles while still failing early awareness of the occluded critical actor.",
        "",
    ])
    with open(os.path.join(output_dir, "overall_sensor_mota_motp_report.md"),
              "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def _write_manifest(output_dir, rows):
    if not rows:
        return
    path = os.path.join(output_dir, "overall_sensor_figure_manifest.csv")
    _write_csv(path, rows)


def main():
    parser = argparse.ArgumentParser(
        description="Calculate Scenario 1 overall sensor MOTA/MOTP.")
    parser.add_argument("--run-dir", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--role", action="append", default=["ego", "rsu"])
    parser.add_argument("--horizon-s", action="append", type=float,
                        default=DEFAULT_HORIZONS_S)
    parser.add_argument("--roi-m", type=float, default=DEFAULT_ROI_M)
    parser.add_argument("--match-distance-m", type=float,
                        default=DEFAULT_MATCH_DISTANCE_M)
    parser.add_argument("--min-persistence", type=int,
                        default=DEFAULT_MIN_PERSISTENCE)
    parser.add_argument("--min-area", type=float, default=DEFAULT_MIN_AREA)
    parser.add_argument("--max-area", type=float, default=DEFAULT_MAX_AREA)
    parser.add_argument("--include-fallback", action="store_true",
                        help="Include GT-like semantic_lidar_fallback "
                        "predictions. Off by default because fallback makes "
                        "MOTP artificially zero.")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    summary_rows = []
    horizon_rows = []
    for run_dir in args.run_dir:
        rows, horizon = _evaluate_run(run_dir, args)
        summary_rows.extend(rows)
        horizon_rows.extend(horizon)

    _write_csv(os.path.join(args.output_dir,
                            "overall_sensor_mota_motp_summary.csv"),
               summary_rows)
    _write_csv(os.path.join(args.output_dir,
                            "overall_sensor_mota_motp_by_horizon.csv"),
               horizon_rows)
    _write_report(args.output_dir, summary_rows, horizon_rows)
    manifest = []
    manifest.extend(_plot_summary(args.output_dir, summary_rows))
    manifest.extend(_plot_horizon(args.output_dir, horizon_rows))
    _write_manifest(args.output_dir, manifest)
    print("Wrote overall sensor MOTA/MOTP to", args.output_dir)


if __name__ == "__main__":
    main()
