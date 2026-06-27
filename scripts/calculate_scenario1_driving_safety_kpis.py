#!/usr/bin/env python
"""Calculate Scenario 1 driving-safety KPIs only.

This is a compact, report-facing safety script. It excludes perception,
control, traffic, and comfort KPIs and calculates only:

- 2D minimum TTC
- PET over the conflict zone
- Required deceleration at hazard awareness

The script reuses Scenario 1 parsing helpers from calculate_scenario1_revised_kpis
so it stays consistent with the existing datadump interpretation.
"""

import argparse
import csv
import math
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import calculate_scenario1_revised_kpis as revised  # noqa: E402


DEFAULT_OUTPUT = os.path.join(
    REPO_ROOT,
    "evaluation_outputs",
    "scenario1_driving_safety_kpis_2026_05_29",
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


def _condition_label(scenario):
    if "no_v2x" in scenario:
        return "No V2X"
    if "v2x" in scenario:
        return "V2X"
    return scenario


def _float_or_none(value):
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ttc_class(ttc):
    if ttc is None:
        return "undefined"
    if ttc <= 0.0:
        return "collision"
    if ttc < 1.5:
        return "very_risky"
    if ttc < 3.0:
        return "caution"
    return "relatively_safe"


def _pet_class(pet, reason):
    if pet is None:
        if "cleanly_enter_and_exit" in str(reason):
            return "undefined_no_clean_exit"
        if "conflict_point" in str(reason):
            return "undefined_no_conflict_point"
        return "undefined"
    if pet <= 0.0:
        return "overlap_or_collision_risk"
    if pet < 1.5:
        return "near_pass_risky"
    if pet < 3.0:
        return "caution"
    return "sufficient_gap"


def _required_decel_class(value, emergency_decel_mps2):
    if value is None:
        return "undefined"
    if value <= 2.0:
        return "very_safe"
    if value <= 4.0:
        return "safe"
    if value <= 6.0:
        return "caution"
    if value <= emergency_decel_mps2:
        return "emergency_marginal"
    return "hard_to_avoid"


def _required_decel_details(run_dir, awareness_frame, args):
    conflict_xy = revised._conflict_point(run_dir)
    if awareness_frame in ("", None) or conflict_xy is None:
        return {
            "ego_speed_at_awareness_mps": "",
            "ego_speed_at_awareness_kmh": "",
            "ego_distance_to_conflict_at_awareness_m": "",
            "reaction_distance_m": "",
            "available_braking_distance_m": "",
            "required_decel_mps2": "",
            "ttc_2d_at_awareness_s": "",
        }
    relative_rows = revised._critical_pair_rows(run_dir)
    aware_row = next(
        (row for row in relative_rows if row["frame"] == awareness_frame),
        None)
    if aware_row is None:
        return {
            "ego_speed_at_awareness_mps": "",
            "ego_speed_at_awareness_kmh": "",
            "ego_distance_to_conflict_at_awareness_m": "",
            "reaction_distance_m": "",
            "available_braking_distance_m": "",
            "required_decel_mps2": "",
            "ttc_2d_at_awareness_s": "",
        }

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
    return {
        "ego_speed_at_awareness_mps": ego_speed,
        "ego_speed_at_awareness_kmh": ego_speed * 3.6,
        "ego_distance_to_conflict_at_awareness_m": distance_to_conflict,
        "reaction_distance_m": reaction_distance,
        "available_braking_distance_m": available_distance,
        "required_decel_mps2": required_decel,
        "ttc_2d_at_awareness_s": (
            ttc_at_awareness if ttc_at_awareness is not None else ""),
    }


def _driving_safety_rows(run_dirs, args):
    base_rows = revised._safety_rows(
        run_dirs,
        args.collision_distance_m,
        args.conflict_radius_m,
        args.visual_range_m,
        args.reaction_time_s,
        args.emergency_decel_mps2,
    )
    rows = []
    for row in base_rows:
        min_ttc = _float_or_none(row.get("min_ttc_2d_s"))
        pet = _float_or_none(row.get("pet_s"))
        required = _float_or_none(row.get("required_decel_at_awareness_mps2"))
        details = _required_decel_details(
            row["run_dir"] if "run_dir" in row else _run_dir_for_row(run_dirs, row),
            row.get("awareness_frame"),
            args,
        )
        if required is None:
            required = _float_or_none(details.get("required_decel_mps2"))

        out = {
            "scenario": row["scenario"],
            "condition": _condition_label(row["scenario"]),
            "run_time": row["run_time"],
            "ttc_method": row["ttc_method"],
            "collision_distance_m": row["collision_distance_m"],
            "min_ttc_2d_s": row["min_ttc_2d_s"],
            "ttc_class": _ttc_class(min_ttc),
            "min_distance_2d_m": row["min_distance_2d_m"],
            "event_frame": row["event_frame"],
            "event_time_s": row["event_time_s"],
            "event_basis": row["event_basis"],
            "conflict_radius_m": row["conflict_radius_m"],
            "ego_conflict_entry_s": row["ego_conflict_entry_s"],
            "ego_conflict_exit_s": row["ego_conflict_exit_s"],
            "subject_conflict_entry_s": row["subject_conflict_entry_s"],
            "subject_conflict_exit_s": row["subject_conflict_exit_s"],
            "pet_s": row["pet_s"],
            "pet_reason": row["pet_reason"],
            "pet_class": _pet_class(pet, row["pet_reason"]),
            "awareness_frame": row["awareness_frame"],
            "awareness_time_s": row["awareness_time_s"],
            "awareness_source": row["awareness_source"],
            "reaction_time_s": args.reaction_time_s,
            "ego_speed_at_awareness_kmh": details["ego_speed_at_awareness_kmh"],
            "ego_distance_to_conflict_at_awareness_m": details[
                "ego_distance_to_conflict_at_awareness_m"],
            "available_braking_distance_m": details[
                "available_braking_distance_m"],
            "required_decel_mps2": (
                required if required is not None else ""),
            "required_decel_class": _required_decel_class(
                required, args.emergency_decel_mps2),
            "emergency_decel_proxy_mps2": args.emergency_decel_mps2,
        }
        rows.append(out)
    rows.sort(key=lambda r: {"No V2X": 0, "V2X": 1}.get(r["condition"], 99))
    return rows


def _run_dir_for_row(run_dirs, safety_row):
    for run_dir in run_dirs:
        scenario, run_time = revised._scenario_and_time(run_dir)
        if scenario == safety_row["scenario"] and run_time == safety_row["run_time"]:
            return run_dir
    return run_dirs[0]


def _plot_min_ttc(rows, output_dir):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None
    labels = [
        "%s\n%s" % (row["condition"], row["ttc_class"].replace("_", " "))
        for row in rows
    ]
    values = [_float_or_none(row["min_ttc_2d_s"]) or 0.0 for row in rows]
    colors = [
        "#D95F02" if value < 1.5 else
        "#F4A261" if value < 3.0 else "#4C8FD3"
        for value in values
    ]
    fig, ax = plt.subplots(figsize=(9.8, 5.8))
    bars = ax.bar(labels, values, color=colors, width=0.52)
    ax.axhline(3.0, color="#2A9D76", linestyle="--", linewidth=1.6,
               label="TTC 3.0s safe reference")
    ax.axhline(1.5, color="#D45A5A", linestyle="--", linewidth=1.6,
               label="TTC 1.5s risk reference")
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2.0, value + 0.12,
                "%.2fs" % value, ha="center", va="bottom",
                fontsize=12, fontweight="bold")
    ax.set_title("Safety Margin: Minimum 2D TTC",
                 fontsize=18, fontweight="bold", pad=14)
    ax.set_ylabel("Min 2D TTC (s)", fontsize=13)
    ax.set_ylim(0, max(4.2, max(values + [3.0]) * 1.35))
    ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.13), ncol=2)
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    path = os.path.join(output_dir, "safety_margin_min_2d_ttc.png")
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _plot_required_decel(rows, output_dir, emergency_decel_mps2):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None
    labels = [
        "%s\n%s" % (
            row["condition"],
            row["required_decel_class"].replace("_", " "),
        )
        for row in rows
    ]
    values = [_float_or_none(row["required_decel_mps2"]) or 0.0
              for row in rows]
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
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2.0, value + 0.35,
                "%.2f" % value, ha="center", va="bottom",
                fontsize=12, fontweight="bold")
    ax.set_title("Safety Margin: Required Deceleration at Hazard Awareness",
                 fontsize=17, fontweight="bold", pad=14)
    ax.set_ylabel("Required deceleration (m/s^2)")
    ax.set_ylim(0, max(max(values + [0.0]) * 1.28,
                       emergency_decel_mps2 * 1.25))
    ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.14), ncol=2)
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    path = os.path.join(output_dir, "safety_margin_required_deceleration.png")
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _plot_pet(rows, output_dir):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None
    fig, ax = plt.subplots(figsize=(11.5, 5.8))
    colors = {"Ego": "#4C8FD3", "Subject": "#D95F02"}
    y_ticks = []
    y_labels = []
    max_time = 0.0

    for index, row in enumerate(rows):
        base_y = index * 3.0
        label = row["condition"]
        intervals = [
            ("Subject", _float_or_none(row["subject_conflict_entry_s"]),
             _float_or_none(row["subject_conflict_exit_s"]), base_y + 1.35),
            ("Ego", _float_or_none(row["ego_conflict_entry_s"]),
             _float_or_none(row["ego_conflict_exit_s"]), base_y + 0.35),
        ]
        for actor, entry, exit_time, y_value in intervals:
            y_ticks.append(y_value + 0.18)
            y_labels.append("%s %s" % (label, actor))
            if entry is None:
                continue
            if exit_time is None:
                fallback = _float_or_none(row["event_time_s"]) or entry + 0.7
                duration = max(fallback - entry, 0.7)
                hatch = "///"
                text = "no clean exit"
            else:
                duration = max(exit_time - entry, 0.1)
                hatch = None
                text = "%.1f-%.1fs" % (entry, exit_time)
            max_time = max(max_time, entry + duration)
            ax.broken_barh(
                [(entry, duration)],
                (y_value, 0.36),
                facecolors=colors[actor],
                edgecolors="#111827",
                linewidth=0.8,
                hatch=hatch,
                alpha=0.88,
            )
            ax.text(entry + duration / 2.0, y_value + 0.18, text,
                    ha="center", va="center", fontsize=9,
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.22",
                              facecolor="white", edgecolor="none",
                              alpha=0.88))
        pet = _float_or_none(row["pet_s"])
        if pet is not None:
            ax.text((_float_or_none(row["subject_conflict_exit_s"]) or 0.0)
                    + pet / 2.0,
                    base_y + 2.15,
                    "PET %.1fs" % pet,
                    ha="center", va="center", fontsize=10,
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.22",
                              facecolor="white", edgecolor="none",
                              alpha=0.88))
        else:
            event_time = _float_or_none(row["event_time_s"]) or 0.0
            ax.text(event_time + 0.3, base_y + 2.15,
                    "PET undefined: no clean exit",
                    ha="left", va="center", fontsize=10,
                    fontweight="bold", color="#D45A5A",
                    bbox=dict(boxstyle="round,pad=0.22",
                              facecolor="white", edgecolor="none",
                              alpha=0.88))

    ax.set_title("Post Encroachment Time (PET)",
                 fontsize=17, fontweight="bold")
    ax.set_xlabel("Time (s)")
    ax.set_yticks(y_ticks)
    ax.set_yticklabels(y_labels)
    ax.set_xlim(9.5, max(20.0, max_time + 1.0))
    ax.grid(axis="x", linestyle="--", linewidth=0.7, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    path = os.path.join(output_dir, "driving_safety_pet_timeline.png")
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _write_report(path, rows, figures, args):
    lines = [
        "# Scenario 1 Safety Margin KPIs",
        "",
        "## Scope",
        "",
        "This file calculates safety-margin indicators: 2D TTC and required deceleration, plus PET as a conflict-zone timing reference.",
        "",
        "## Formulas",
        "",
        "```text",
        "2D TTC: solve ||(p_subject - p_ego) + (v_subject - v_ego)t||^2 = R^2",
        "PET = second_vehicle_entry_time - first_vehicle_exit_time",
        "required_decel = v_ego^2 / (2 * max(distance_to_conflict - v_ego * reaction_time, eps))",
        "```",
        "",
        "## Criteria",
        "",
        "- TTC > 3.0s: relatively safe; 1.5-3.0s: caution; 0-1.5s: very risky; 0s: collision.",
        "- PET > 3.0s: sufficient gap; 1.5-3.0s: caution; 0-1.5s: near pass; undefined: no clean exit.",
        "- Required decel <= 2 m/s^2: very safe; 2-4: safe; 4-6: caution; 6-8: emergency marginal; >8: hard to avoid.",
        "",
        "## Parameters",
        "",
        "- collision_distance_m: `%s`" % args.collision_distance_m,
        "- conflict_radius_m: `%s`" % args.conflict_radius_m,
        "- visual_range_m: `%s`" % args.visual_range_m,
        "- reaction_time_s: `%s`" % args.reaction_time_s,
        "- emergency_decel_proxy_mps2: `%s`" % args.emergency_decel_mps2,
        "",
        "## Results",
        "",
        "| Condition | Min 2D TTC | PET | Required decel | Classes |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        ttc = _float_or_none(row["min_ttc_2d_s"])
        pet = _float_or_none(row["pet_s"])
        decel = _float_or_none(row["required_decel_mps2"])
        lines.append(
            "| {condition} | {ttc} | {pet} | {decel} | {classes} |".format(
                condition=row["condition"],
                ttc="%.2fs" % ttc if ttc is not None else "",
                pet="%.2fs" % pet if pet is not None else "undefined",
                decel="%.2f m/s^2" % decel if decel is not None else "",
                classes="%s / %s / %s" % (
                    row["ttc_class"],
                    row["pet_class"],
                    row["required_decel_class"],
                ),
            ))
    lines.extend(["", "## Output Figures", ""])
    for title, file_path in figures:
        if file_path:
            lines.append("- %s: `%s`" % (title, os.path.basename(file_path)))
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(
        description="Calculate Scenario 1 driving-safety KPIs only.")
    parser.add_argument("--run-dir", action="append", required=True,
                        help="Scenario 1 datadump run directory. Repeatable.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    parser.add_argument("--collision-distance-m", type=float,
                        default=revised.DEFAULT_COLLISION_DISTANCE_M)
    parser.add_argument("--conflict-radius-m", type=float,
                        default=revised.DEFAULT_CONFLICT_RADIUS_M)
    parser.add_argument("--visual-range-m", type=float,
                        default=revised.DEFAULT_VISUAL_RANGE_M)
    parser.add_argument("--reaction-time-s", type=float,
                        default=revised.DEFAULT_REACTION_TIME_S)
    parser.add_argument("--emergency-decel-mps2", type=float,
                        default=revised.DEFAULT_EMERGENCY_DECEL_MPS2)
    parser.add_argument("--min-available-distance-m", type=float, default=0.1)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    rows = _driving_safety_rows(args.run_dir, args)
    _write_csv(os.path.join(args.output_dir, "driving_safety_kpi.csv"), rows)
    figures = [
        ("Safety Margin: Minimum 2D TTC",
         _plot_min_ttc(rows, args.output_dir)),
        ("PET timeline",
         _plot_pet(rows, args.output_dir)),
        ("Safety Margin: Required deceleration",
         _plot_required_decel(rows, args.output_dir,
                              args.emergency_decel_mps2)),
    ]
    _write_report(
        os.path.join(args.output_dir, "driving_safety_report.md"),
        rows,
        figures,
        args,
    )
    print("Wrote driving-safety KPIs to", args.output_dir)


if __name__ == "__main__":
    main()
