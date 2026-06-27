#!/usr/bin/env python
"""Calculate Scenario 1 required deceleration at hazard awareness.

This script separates the old PRS proxy into a single, auditable metric:

    required deceleration at awareness (m/s^2)

The calculation uses the same critical ego-subject pair and awareness logic as
calculate_scenario1_revised_kpis.py, but outputs only the required deceleration
KPI, its classification, and a clean figure.
"""

import argparse
import csv
import math
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import calculate_scenario1_revised_kpis as revised  # noqa: E402


DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(SCRIPT_DIR),
    "evaluation_outputs",
    "scenario1_required_deceleration_safety_2026_05_29",
)


def _write_csv(path, rows):
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


def _scenario_label(scenario):
    if "no_v2x" in scenario:
        return "No V2X"
    if "v2x" in scenario:
        return "V2X"
    return scenario


def _classify_required_decel(value, emergency_decel_mps2):
    if value == "":
        return "not_available", "awareness or conflict point unavailable"
    value = float(value)
    if value <= 2.0:
        return "very_safe", "low braking demand"
    if value <= 4.0:
        return "safe", "normal controlled braking demand"
    if value <= 6.0:
        return "caution", "strong braking demand"
    if value <= emergency_decel_mps2:
        return "emergency_marginal", "near emergency braking demand"
    return "hard_to_avoid", "required deceleration exceeds emergency proxy"


def _required_decel_row(run_dir, args):
    scenario, run_time = revised._scenario_and_time(run_dir)
    conflict_xy = revised._conflict_point(run_dir)
    relative_rows = revised._critical_pair_rows(run_dir)
    awareness_frame, awareness_time, awareness_source = \
        revised._first_awareness_frame(run_dir, args.visual_range_m)

    result = {
        "scenario": scenario,
        "condition": _scenario_label(scenario),
        "run_time": run_time,
        "run_dir": run_dir,
        "awareness_frame": awareness_frame,
        "awareness_time_s": awareness_time,
        "awareness_source": awareness_source,
        "reaction_time_s": args.reaction_time_s,
        "emergency_decel_proxy_mps2": args.emergency_decel_mps2,
        "visual_range_m": args.visual_range_m,
        "conflict_x_m": conflict_xy[0] if conflict_xy else "",
        "conflict_y_m": conflict_xy[1] if conflict_xy else "",
        "ego_speed_at_awareness_mps": "",
        "ego_speed_at_awareness_kmh": "",
        "ego_distance_to_conflict_at_awareness_m": "",
        "reaction_distance_m": "",
        "available_braking_distance_m": "",
        "required_decel_mps2": "",
        "ttc_2d_at_awareness_s": "",
        "classification": "not_available",
        "interpretation": "awareness or conflict point unavailable",
        "formula": (
            "required_decel = v_ego^2 / "
            "(2 * max(distance_to_conflict - v_ego * reaction_time, eps))"
        ),
    }

    if awareness_frame == "" or conflict_xy is None:
        return result

    aware_row = next(
        (row for row in relative_rows if row["frame"] == awareness_frame),
        None)
    if aware_row is None:
        return result

    ego_speed = math.hypot(aware_row["ego_vx"], aware_row["ego_vy"])
    distance_to_conflict = math.hypot(
        aware_row["ego_x"] - conflict_xy[0],
        aware_row["ego_y"] - conflict_xy[1],
    )
    reaction_distance = ego_speed * args.reaction_time_s
    available_distance = max(
        distance_to_conflict - reaction_distance,
        args.min_available_distance_m,
    )
    required_decel = (
        ego_speed * ego_speed / (2.0 * available_distance)
        if ego_speed > 1e-6 else 0.0
    )
    ttc_at_awareness = revised._ttc_2d(
        aware_row, args.collision_distance_m)
    classification, interpretation = _classify_required_decel(
        required_decel, args.emergency_decel_mps2)

    result.update({
        "ego_speed_at_awareness_mps": ego_speed,
        "ego_speed_at_awareness_kmh": ego_speed * 3.6,
        "ego_distance_to_conflict_at_awareness_m": distance_to_conflict,
        "reaction_distance_m": reaction_distance,
        "available_braking_distance_m": available_distance,
        "required_decel_mps2": required_decel,
        "ttc_2d_at_awareness_s": (
            ttc_at_awareness if ttc_at_awareness is not None else ""),
        "classification": classification,
        "interpretation": interpretation,
    })
    return result


def _plot_required_decel(output_dir, rows, emergency_decel_mps2):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None

    plot_rows = [
        row for row in rows
        if row.get("required_decel_mps2") not in ("", None)
    ]
    if not plot_rows:
        return None

    plot_rows = sorted(plot_rows, key=lambda row: row["condition"])
    labels = [
        "%s\n%s" % (
            row["condition"],
            str(row["classification"]).replace("_", " "),
        )
        for row in plot_rows
    ]
    values = [float(row["required_decel_mps2"]) for row in plot_rows]
    colors = [
        "#D95F02" if value > emergency_decel_mps2 else "#4C8FD3"
        for value in values
    ]

    fig, ax = plt.subplots(figsize=(10.8, 6.2))
    bars = ax.bar(labels, values, color=colors, width=0.52)
    for y, label, color in [
            (2.0, "2 m/s^2 low demand", "#2A9D76"),
            (4.0, "4 m/s^2 controlled braking", "#8AB17D"),
            (6.0, "6 m/s^2 strong braking", "#F4A261"),
            (emergency_decel_mps2, "8 m/s^2 emergency proxy", "#D45A5A")]:
        ax.axhline(y, color=color, linestyle="--", linewidth=1.4,
                   label=label)
    ax.bar_label(bars, labels=["%.2f" % v for v in values],
                 padding=5, fontsize=11, fontweight="bold")
    ax.set_title("Required Deceleration at Hazard Awareness",
                 fontsize=17, fontweight="bold", pad=14)
    ax.set_ylabel("Required deceleration (m/s^2)")
    ax.set_ylim(0, max(max(values) * 1.28, emergency_decel_mps2 * 1.25))
    ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.14), ncol=2)
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    path = os.path.join(output_dir, "required_deceleration_only.png")
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _write_report(output_dir, rows, figure_path, args):
    lines = [
        "# Scenario 1 Safety KPI: Required Deceleration",
        "",
        "## Used Files",
        "",
        "- Calculation script: `scripts/calculate_scenario1_required_deceleration.py`",
        "- Shared safety logic: `scripts/calculate_scenario1_revised_kpis.py`",
        "- Main output CSV: `required_deceleration_kpi.csv`",
        "- Figure: `required_deceleration_only.png`",
        "",
        "## Formula",
        "",
        "```text",
        "required_decel = v_ego^2 / (2 * d_available)",
        "d_available = max(distance_to_conflict - v_ego * reaction_time, eps)",
        "```",
        "",
        "- `v_ego`: ego vehicle speed at the first hazard-awareness frame",
        "- `distance_to_conflict`: 2D distance from ego to configured conflict point",
        "- `reaction_time`: assumed reaction/control latency before braking starts",
        "- `eps`: minimum distance guard to avoid division by zero",
        "",
        "## Project Criteria",
        "",
        "| Required decel | Class | Meaning |",
        "|---:|---|---|",
        "| <= 2 m/s^2 | very_safe | Low braking demand |",
        "| 2-4 m/s^2 | safe | Normal controlled braking demand |",
        "| 4-6 m/s^2 | caution | Strong braking demand |",
        "| 6-8 m/s^2 | emergency_marginal | Near emergency braking demand |",
        "| > 8 m/s^2 | hard_to_avoid | Required braking exceeds emergency proxy |",
        "",
        "## Parameters",
        "",
        "- reaction_time_s: `%s`" % args.reaction_time_s,
        "- emergency_decel_proxy_mps2: `%s`" % args.emergency_decel_mps2,
        "- visual_range_m: `%s`" % args.visual_range_m,
        "- collision_distance_m: `%s`" % args.collision_distance_m,
        "",
        "## Results",
        "",
        "| Condition | Awareness source | Awareness time | Required decel | Class |",
        "|---|---|---:|---:|---|",
    ]
    for row in rows:
        value = row.get("required_decel_mps2", "")
        lines.append(
            "| {condition} | {source} | {time} | {decel} | {cls} |".format(
                condition=row["condition"],
                source=row["awareness_source"],
                time=(
                    "%.2f s" % float(row["awareness_time_s"])
                    if row.get("awareness_time_s") not in ("", None)
                    else ""),
                decel=(
                    "%.2f m/s^2" % float(value)
                    if value not in ("", None) else ""),
                cls=row["classification"],
            ))
    if figure_path:
        lines.extend([
            "",
            "## Figure",
            "",
            "`%s`" % os.path.basename(figure_path),
        ])

    with open(os.path.join(output_dir, "required_deceleration_report.md"),
              "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(
        description="Calculate required deceleration at awareness.")
    parser.add_argument("--run-dir", action="append", required=True)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    parser.add_argument("--visual-range-m", type=float,
                        default=revised.DEFAULT_VISUAL_RANGE_M)
    parser.add_argument("--reaction-time-s", type=float,
                        default=revised.DEFAULT_REACTION_TIME_S)
    parser.add_argument("--emergency-decel-mps2", type=float,
                        default=revised.DEFAULT_EMERGENCY_DECEL_MPS2)
    parser.add_argument("--collision-distance-m", type=float,
                        default=revised.DEFAULT_COLLISION_DISTANCE_M)
    parser.add_argument("--min-available-distance-m", type=float, default=0.1)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    rows = [_required_decel_row(run_dir, args) for run_dir in args.run_dir]
    _write_csv(os.path.join(args.output_dir, "required_deceleration_kpi.csv"),
               rows)
    figure_path = _plot_required_decel(
        args.output_dir, rows, args.emergency_decel_mps2)
    _write_report(args.output_dir, rows, figure_path, args)
    print("Wrote required deceleration KPI to", args.output_dir)


if __name__ == "__main__":
    main()
