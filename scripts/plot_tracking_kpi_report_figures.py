#!/usr/bin/env python
"""
Create report-ready tracking KPI comparison figures.

This script is intended for the Scenario 1 comparison report. It uses only
RSU/Ego observer rows for a selected perception mode and creates:
  1. HOTA mean comparison by scenario
  2. DetA/AssA decomposition at alpha 0.50
  3. TP/FP/FN stacked counts at alpha 0.50
  4. HOTA curve by alpha
"""

import argparse
import csv
import os

import matplotlib.pyplot as plt


ROLE_ORDER = ["rsu", "ego"]
SCENARIO_ORDER = ["scenario1_v2x", "scenario1_no_v2x"]
SCENARIO_LABELS = {
    "scenario1_v2x": "V2X",
    "scenario1_no_v2x": "No V2X",
}
ROLE_LABELS = {
    "rsu": "RSU",
    "ego": "Ego",
}
ROLE_COLORS = {
    "rsu": "#2674BA",
    "ego": "#D95F02",
}


def _read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _float(row, key):
    try:
        return float(row.get(key, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _filter_rows(rows, mode):
    return [
        row for row in rows
        if row.get("perception_mode") == mode
        and row.get("observer_role") in ROLE_ORDER
        and row.get("scenario") in SCENARIO_ORDER
    ]


def _sort_key(row):
    return (
        SCENARIO_ORDER.index(row["scenario"]),
        ROLE_ORDER.index(row["observer_role"]),
    )


def _condition_role_label(row):
    return "%s-%s" % (
        SCENARIO_LABELS[row["scenario"]],
        ROLE_LABELS[row["observer_role"]],
    )


def _style_axes(ax):
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.45)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _save_hota_condition(summary_rows, output_path):
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    width = 0.34
    x_positions = list(range(len(SCENARIO_ORDER)))

    for role_index, role in enumerate(ROLE_ORDER):
        values = []
        for scenario in SCENARIO_ORDER:
            row = next(
                r for r in summary_rows
                if r["scenario"] == scenario and r["observer_role"] == role)
            values.append(_float(row, "HOTA_mean"))

        xs = [x + (role_index - 0.5) * width for x in x_positions]
        bars = ax.bar(
            xs, values, width, label=ROLE_LABELS[role],
            color=ROLE_COLORS[role])
        ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=9)

    ax.set_title("HOTA Comparison by Scenario Condition")
    ax.set_ylabel("HOTA_mean")
    ax.set_ylim(0, 1)
    ax.set_xticks(x_positions)
    ax.set_xticklabels([SCENARIO_LABELS[s] for s in SCENARIO_ORDER])
    _style_axes(ax)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _save_deta_assa(summary_rows, output_path):
    summary_rows = sorted(summary_rows, key=_sort_key)
    labels = [_condition_role_label(row) for row in summary_rows]
    metrics = [("DetA_0.50", "DetA@0.50", "#2A9D76"),
               ("AssA_0.50", "AssA@0.50", "#8E5EA2")]
    width = 0.34
    x_positions = list(range(len(summary_rows)))

    fig, ax = plt.subplots(figsize=(10.5, 5.4))
    for metric_index, (key, label, color) in enumerate(metrics):
        xs = [x + (metric_index - 0.5) * width for x in x_positions]
        bars = ax.bar(
            xs, [_float(row, key) for row in summary_rows],
            width, label=label, color=color)
        ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=8)

    ax.set_title("Detection and Association Decomposition")
    ax.set_ylabel("Score")
    ax.set_ylim(0, 1)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=12, ha="right")
    _style_axes(ax)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _save_counts(summary_rows, output_path):
    summary_rows = sorted(summary_rows, key=_sort_key)
    labels = [_condition_role_label(row) for row in summary_rows]
    x_positions = list(range(len(summary_rows)))
    tp = [_float(row, "TP_0.50") for row in summary_rows]
    fp = [_float(row, "FP_0.50") for row in summary_rows]
    fn = [_float(row, "FN_0.50") for row in summary_rows]

    fig, ax = plt.subplots(figsize=(10.5, 5.4))
    ax.bar(x_positions, tp, label="TP", color="#2A9D76")
    ax.bar(x_positions, fp, bottom=tp, label="FP", color="#D95F02")
    bottoms = [a + b for a, b in zip(tp, fp)]
    ax.bar(x_positions, fn, bottom=bottoms, label="FN", color="#6B7280")

    for x, total in zip(x_positions, [a + b + c for a, b, c in zip(tp, fp, fn)]):
        ax.text(x, total + max(total * 0.015, 4), "%d" % int(total),
                ha="center", va="bottom", fontsize=9)

    ax.set_title("Tracking Detection Coverage at Alpha 0.50")
    ax.set_ylabel("Count")
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=12, ha="right")
    _style_axes(ax)
    ax.legend(frameon=False, ncol=3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _save_alpha_curve(detail_rows, output_path):
    detail_rows = sorted(detail_rows, key=lambda row: (
        SCENARIO_ORDER.index(row["scenario"]),
        ROLE_ORDER.index(row["observer_role"]),
        _float(row, "alpha"),
    ))
    groups = {}
    for row in detail_rows:
        groups.setdefault(_condition_role_label(row), []).append(row)

    fig, ax = plt.subplots(figsize=(10.5, 5.4))
    linestyles = {
        "V2X-RSU": "-",
        "V2X-Ego": "-",
        "No V2X-RSU": "--",
        "No V2X-Ego": "--",
    }
    colors = {
        "V2X-RSU": ROLE_COLORS["rsu"],
        "V2X-Ego": ROLE_COLORS["ego"],
        "No V2X-RSU": "#4B83C3",
        "No V2X-Ego": "#E6843A",
    }

    for label, rows in groups.items():
        ax.plot(
            [_float(row, "alpha") for row in rows],
            [_float(row, "HOTA") for row in rows],
            marker="o", markersize=3.5, linewidth=1.9,
            linestyle=linestyles.get(label, "-"),
            color=colors.get(label), label=label)

    ax.set_title("HOTA Curve by IoU Alpha")
    ax.set_xlabel("IoU threshold alpha")
    ax.set_ylabel("HOTA")
    ax.set_ylim(0, 1)
    ax.set_xlim(0.05, 0.95)
    ax.grid(True, linestyle="--", linewidth=0.6, alpha=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _save_score_overlay_line(summary_rows, output_path):
    summary_rows = sorted(summary_rows, key=_sort_key)
    metrics = [
        ("HOTA_mean", "HOTA mean"),
        ("DetA_0.50", "DetA@0.50"),
        ("AssA_0.50", "AssA@0.50"),
        ("MOTA_0.50", "MOTA@0.50"),
    ]
    x_positions = list(range(len(metrics)))

    fig, ax = plt.subplots(figsize=(10.5, 5.4))
    for row in summary_rows:
        label = _condition_role_label(row)
        values = [_float(row, key) for key, _ in metrics]
        color = ROLE_COLORS[row["observer_role"]]
        linestyle = "-" if row["scenario"] == "scenario1_v2x" else "--"
        ax.plot(
            x_positions, values, marker="o", markersize=5,
            linewidth=2.0, linestyle=linestyle, color=color, label=label)

    ax.set_title("Tracking KPI Score Profile")
    ax.set_ylabel("Score")
    ax.set_ylim(-0.1, 1.0)
    ax.set_xticks(x_positions)
    ax.set_xticklabels([label for _, label in metrics])
    ax.axhline(0, color="#111827", linewidth=0.8, alpha=0.35)
    ax.grid(True, linestyle="--", linewidth=0.6, alpha=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _save_count_overlay_line(summary_rows, output_path):
    summary_rows = sorted(summary_rows, key=_sort_key)
    metrics = [
        ("TP_0.50", "TP"),
        ("FP_0.50", "FP"),
        ("FN_0.50", "FN"),
        ("IDSW_0.50", "IDSW"),
    ]
    x_positions = list(range(len(metrics)))

    fig, ax = plt.subplots(figsize=(10.5, 5.4))
    for row in summary_rows:
        label = _condition_role_label(row)
        values = [_float(row, key) for key, _ in metrics]
        color = ROLE_COLORS[row["observer_role"]]
        linestyle = "-" if row["scenario"] == "scenario1_v2x" else "--"
        ax.plot(
            x_positions, values, marker="o", markersize=5,
            linewidth=2.0, linestyle=linestyle, color=color, label=label)

    ax.set_title("Tracking Count Profile at Alpha 0.50")
    ax.set_ylabel("Count")
    ax.set_xticks(x_positions)
    ax.set_xticklabels([label for _, label in metrics])
    ax.grid(True, linestyle="--", linewidth=0.6, alpha=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="Create Scenario 1 report-ready KPI figures.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--mode", default="semantic_lidar_fallback")
    args = parser.parse_args()

    summary_path = os.path.join(args.input_dir, "tracking_kpi_summary.csv")
    detail_path = os.path.join(args.input_dir, "tracking_kpi_by_alpha.csv")
    summary_rows = _filter_rows(_read_csv(summary_path), args.mode)
    detail_rows = _filter_rows(_read_csv(detail_path), args.mode)

    if len(summary_rows) != 4:
        raise RuntimeError(
            "Expected 4 summary rows for mode %s, got %d"
            % (args.mode, len(summary_rows)))

    _save_hota_condition(
        summary_rows,
        os.path.join(args.input_dir, "fig1_hota_comparison_by_condition.png"))
    _save_deta_assa(
        summary_rows,
        os.path.join(args.input_dir, "fig2_deta_assa_decomposition.png"))
    _save_counts(
        summary_rows,
        os.path.join(args.input_dir, "fig3_tp_fp_fn_detection_coverage.png"))
    _save_alpha_curve(
        detail_rows,
        os.path.join(args.input_dir, "fig4_hota_alpha_curve.png"))
    _save_score_overlay_line(
        summary_rows,
        os.path.join(args.input_dir, "fig5_score_profile_overlay_line.png"))
    _save_count_overlay_line(
        summary_rows,
        os.path.join(args.input_dir, "fig6_count_profile_overlay_line.png"))

    print("Wrote report figures to", args.input_dir)


if __name__ == "__main__":
    main()
