#!/usr/bin/env python
"""Calculate Scenario 1 traffic-impact KPIs only.

This report-facing script separates traffic impact from the larger revised KPI
framework. It intentionally does not calculate vehicle-count throughput because
Scenario 1 has a very small fixed number of vehicles. Instead it reports:

- average speed and speed-based class
- progress-adjusted delay
- trip completion / flow efficiency

Raw delay is excluded because, in the current datadump, it duplicates observed
travel time unless a separate free-flow reference travel time is defined. A
progress-adjusted delay is provided instead.
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
    "scenario1_traffic_impact_kpis_2026_05_29",
)
DEFAULT_REFERENCE_SPEED_KMH = 30.0


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


def _float_or_zero(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _condition_label(scenario):
    if "no_v2x" in scenario:
        return "No V2X"
    if "v2x" in scenario:
        return "V2X"
    return scenario


def _role_label(role):
    if role == "ego":
        return "Ego"
    if role == "subject":
        return "Subject"
    return role


def _speed_los(avg_speed_kmh):
    """Project LOS criterion based on the user's 30 km/h scenario reference."""
    speed = float(avg_speed_kmh)
    if speed > 25.5:
        return "A", "very_smooth"
    if speed > 20.1:
        return "B", "smooth"
    if speed > 15.0:
        return "C", "moderate"
    if speed > 10.2:
        return "D", "delayed_slow_driving"
    if speed > 9.0:
        return "E", "severe_congestion"
    return "F", "sustained_congestion_or_slow_driving"


def _flow_class(ratio):
    ratio = float(ratio)
    if ratio <= 0.01:
        return "no_progress"
    if ratio >= 0.80:
        return "high_efficiency"
    if ratio >= 0.60:
        return "moderate_efficiency"
    return "low_efficiency"


def _progress_adjusted_delay_class(delay_s):
    if delay_s in ("", None):
        return "undefined"
    delay_s = float(delay_s)
    if delay_s <= 10.0:
        return "very_smooth"
    if delay_s <= 15.0:
        return "good"
    if delay_s <= 25.0:
        return "moderate"
    if delay_s <= 35.0:
        return "large_delay"
    return "severe_delay"


def _project_progress(spawn, dest, xy):
    planned_distance = revised._distance_xy(spawn, dest)
    if planned_distance <= 0.0:
        return 0.0
    path_x = dest[0] - spawn[0]
    path_y = dest[1] - spawn[1]
    projected = ((xy[0] - spawn[0]) * path_x + (xy[1] - spawn[1]) * path_y)
    return max(0.0, min(projected / planned_distance, planned_distance))


def _traffic_rows(run_dirs, reference_speed_kmh, arrival_distance_m):
    rows = []
    for run_dir in run_dirs:
        scenario, run_time = revised._scenario_and_time(run_dir)
        condition = _condition_label(scenario)
        for role in ["ego", "subject"]:
            observer_id, series = revised._role_timeseries(run_dir, role)
            if not series:
                continue
            cav = revised._cav_by_name(run_dir, role)
            spawn = revised._xy_from_list(cav.get("spawn_position") or [])
            dest = revised._xy_from_list(cav.get("destination") or [])
            if spawn is None or dest is None:
                continue

            planned_distance = revised._distance_xy(spawn, dest)
            if planned_distance <= 0.0:
                continue

            first_time = series[0]["time_s"]
            observed_time = series[-1]["time_s"] - first_time
            final_xy = (series[-1]["x_m"], series[-1]["y_m"])
            progress_distance = _project_progress(spawn, dest, final_xy)
            flow_ratio = max(0.0, min(progress_distance / planned_distance, 1.0))

            actual_path = 0.0
            arrival_elapsed_time = ""
            for prev, cur in zip(series, series[1:]):
                actual_path += math.hypot(
                    cur["x_m"] - prev["x_m"], cur["y_m"] - prev["y_m"])
            for cur in series:
                dist_to_dest = math.hypot(cur["x_m"] - dest[0],
                                          cur["y_m"] - dest[1])
                if dist_to_dest <= arrival_distance_m:
                    arrival_elapsed_time = cur["time_s"] - first_time
                    break

            if arrival_elapsed_time != "":
                final_time_for_delay = arrival_elapsed_time
                final_time_basis = "arrival_distance"
            else:
                final_time_for_delay = observed_time
                final_time_basis = "simulation_end"

            reference_speed_mps = reference_speed_kmh / 3.6
            reference_travel_time = (
                planned_distance / reference_speed_mps
                if planned_distance > 0.0 and reference_speed_mps > 0.0
                else 0.0
            )

            progress_adjusted_travel_time = ""
            progress_adjusted_delay_raw = ""
            progress_adjusted_delay = ""
            if flow_ratio > 1e-6:
                progress_adjusted_travel_time = (
                    final_time_for_delay / flow_ratio)
                progress_adjusted_delay_raw = (
                    progress_adjusted_travel_time - reference_travel_time)
                progress_adjusted_delay = max(0.0, progress_adjusted_delay_raw)

            rows.append({
                "scenario": scenario,
                "condition": condition,
                "run_time": run_time,
                "role": role,
                "role_label": _role_label(role),
                "observer_id": observer_id,
                "final_time_for_delay_s": final_time_for_delay,
                "final_time_basis": final_time_basis,
                "arrival_elapsed_time_s": arrival_elapsed_time,
                "arrival_distance_threshold_m": arrival_distance_m,
                "reference_travel_time_s": reference_travel_time,
                "progress_adjusted_travel_time_s":
                    progress_adjusted_travel_time,
                "progress_adjusted_delay_raw_s": progress_adjusted_delay_raw,
                "progress_adjusted_delay_s": progress_adjusted_delay,
                "progress_adjusted_delay_class":
                    _progress_adjusted_delay_class(progress_adjusted_delay),
                "projected_progress_distance_m": progress_distance,
                "route_distance_m": planned_distance,
                "flow_efficiency_ratio": flow_ratio,
                "flow_efficiency_percent": flow_ratio * 100.0,
                "flow_efficiency_class": _flow_class(flow_ratio),
                "actual_path_distance_m": actual_path,
                "traffic_metric_note": (
                    "Traffic impact uses only progress-adjusted delay and "
                    "route-completion flow efficiency."),
            })

    condition_order = {"No V2X": 0, "V2X": 1}
    role_order = {"ego": 0, "subject": 1}
    rows.sort(key=lambda r: (
        condition_order.get(r["condition"], 99),
        role_order.get(r["role"], 99),
    ))
    return rows


def _summary_rows(rows):
    summary = []
    for condition in sorted({row["condition"] for row in rows},
                            key=lambda c: {"No V2X": 0, "V2X": 1}.get(c, 99)):
        subset = [row for row in rows if row["condition"] == condition]
        if not subset:
            continue
        total_progress = sum(
            row["projected_progress_distance_m"] for row in subset)
        total_route = sum(row["route_distance_m"] for row in subset)
        flow = total_progress / total_route if total_route > 0.0 else 0.0
        delays = [
            row["progress_adjusted_delay_s"] for row in subset
            if row["progress_adjusted_delay_s"] != ""
        ]
        mean_progress_delay = (
            sum(float(v) for v in delays) / len(delays)
            if delays else "")
        summary.append({
            "condition": condition,
            "vehicle_count": len(subset),
            "total_projected_progress_distance_m": total_progress,
            "total_route_distance_m": total_route,
            "mean_progress_adjusted_delay_s": mean_progress_delay,
            "mean_progress_adjusted_delay_class":
                _progress_adjusted_delay_class(mean_progress_delay),
            "overall_flow_efficiency_ratio": flow,
            "overall_flow_efficiency_percent": flow * 100.0,
            "overall_flow_efficiency_class": _flow_class(flow),
        })
    return summary


def _plot_avg_speed(rows, output_dir):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None

    labels = ["%s\n%s" % (row["condition"], row["role_label"])
              for row in rows]
    values = [row["avg_speed_kmh"] for row in rows]
    colors = ["#D45A5A" if row["condition"] == "No V2X" else "#4C8FD3"
              for row in rows]
    fig, ax = plt.subplots(figsize=(11.2, 6.0))
    bars = ax.bar(labels, values, color=colors, width=0.58)
    thresholds = [
        (25.5, "LOS A/B 25.5 km/h", "#2A9D76"),
        (20.1, "LOS B/C 20.1 km/h", "#8AB17D"),
        (15.0, "LOS C/D 15.0 km/h", "#F4A261"),
        (10.2, "LOS D/E 10.2 km/h", "#E76F51"),
        (9.0, "LOS E/F 9.0 km/h", "#D45A5A"),
    ]
    for y, label, color in thresholds:
        ax.axhline(y, color=color, linestyle="--", linewidth=1.1,
                   alpha=0.78, label=label)
    for bar, row in zip(bars, rows):
        value = row["avg_speed_kmh"]
        ax.text(bar.get_x() + bar.get_width() / 2.0, value + 0.45,
                "%.2f\nLOS %s" % (value, row["speed_los"]),
                ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_title("Traffic Impact: Average Speed and LOS",
                 fontsize=17, fontweight="bold", pad=14)
    ax.set_ylabel("Average speed (km/h)")
    ax.set_ylim(0, max(31.5, max(values + [30.0]) * 1.16))
    ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.16), ncol=3, fontsize=9)
    fig.tight_layout(rect=[0, 0.08, 1, 1])
    path = os.path.join(output_dir, "traffic_average_speed_los.png")
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _plot_flow_efficiency(rows, output_dir):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None
    labels = ["%s\n%s" % (row["condition"], row["role_label"])
              for row in rows]
    values = [row["flow_efficiency_percent"] for row in rows]
    colors = ["#D45A5A" if row["condition"] == "No V2X" else "#4C8FD3"
              for row in rows]
    fig, ax = plt.subplots(figsize=(10.8, 5.8))
    bars = ax.bar(labels, values, color=colors, width=0.58)
    for y, label, color in [
            (80, "high efficiency 80%", "#2A9D76"),
            (60, "moderate efficiency 60%", "#F4A261")]:
        ax.axhline(y, color=color, linestyle="--", linewidth=1.3,
                   label=label)
    for bar, row in zip(bars, rows):
        value = row["flow_efficiency_percent"]
        ax.text(bar.get_x() + bar.get_width() / 2.0, value + 2.5,
                "%.1f%%\n%s" % (
                    value,
                    row["flow_efficiency_class"].replace("_", " ")),
                ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_title("Traffic Impact: Flow Efficiency / Trip Completion",
                 fontsize=17, fontweight="bold", pad=14)
    ax.set_ylabel("Trip completion/progress (%)")
    ax.set_ylim(0, max(108, max(values + [100.0]) * 1.12))
    ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.14), ncol=3)
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    path = os.path.join(output_dir, "traffic_flow_efficiency.png")
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _plot_progress_adjusted_delay(rows, output_dir):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None
    plot_rows = [
        row for row in rows
        if row["progress_adjusted_delay_s"] != ""
    ]
    if not plot_rows:
        return None
    labels = ["%s\n%s" % (row["condition"], row["role_label"])
              for row in plot_rows]
    values = [float(row["progress_adjusted_delay_s"]) for row in plot_rows]
    colors = ["#D45A5A" if row["condition"] == "No V2X" else "#4C8FD3"
              for row in plot_rows]
    fig, ax = plt.subplots(figsize=(10.8, 5.8))
    bars = ax.bar(labels, values, color=colors, width=0.58)
    for y, label, color in [
            (10, "very smooth <=10s", "#2A9D76"),
            (15, "good <=15s", "#8AB17D"),
            (25, "moderate <=25s", "#F4A261"),
            (35, "large delay <=35s", "#D45A5A")]:
        ax.axhline(y, color=color, linestyle="--", linewidth=1.3,
                   label=label)
    for bar, row in zip(bars, plot_rows):
        value = float(row["progress_adjusted_delay_s"])
        ax.text(bar.get_x() + bar.get_width() / 2.0, value + 0.8,
                "%.1fs\n%s" % (
                    value,
                    row["progress_adjusted_delay_class"].replace("_", " ")),
                ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_title("Traffic Impact: Progress-Adjusted Delay",
                 fontsize=17, fontweight="bold", pad=14)
    ax.set_ylabel("Progress-adjusted delay (s)")
    ax.set_ylim(0, max(40.0, max(values + [35.0]) * 1.18))
    ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.15), ncol=2)
    fig.tight_layout(rect=[0, 0.07, 1, 1])
    path = os.path.join(output_dir, "traffic_progress_adjusted_delay.png")
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _plot_travel_time(rows, output_dir):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None
    labels = ["%s\n%s" % (row["condition"], row["role_label"])
              for row in rows]
    values = [row["observed_travel_time_s"] for row in rows]
    colors = ["#D45A5A" if row["condition"] == "No V2X" else "#4C8FD3"
              for row in rows]
    fig, ax = plt.subplots(figsize=(10.0, 5.6))
    bars = ax.bar(labels, values, color=colors, width=0.58)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2.0, value + 0.35,
                "%.1fs" % value, ha="center", va="bottom",
                fontsize=11, fontweight="bold")
    ax.set_title("Traffic Impact: Observed Travel Time",
                 fontsize=17, fontweight="bold", pad=14)
    ax.set_ylabel("Observed time (s)")
    ax.set_ylim(0, max(24.0, max(values + [0.0]) * 1.20))
    ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    path = os.path.join(output_dir, "traffic_observed_travel_time.png")
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _write_report(path, rows, summary, figures, args):
    lines = [
        "# Scenario 1 Traffic Impact KPIs",
        "",
        "## Scope",
        "",
        "This file calculates only traffic-impact indicators: average speed, observed travel time, and flow efficiency.",
        "",
        "Vehicle-count throughput is not used because Scenario 1 contains a small fixed number of vehicles. Delay is also excluded from the main KPI because it duplicates observed travel time unless a separate free-flow reference is defined.",
        "",
        "## Formulas",
        "",
        "```text",
        "average_speed = mean(vehicle_speed)",
        "speed_efficiency_ratio = average_speed / reference_speed",
        "observed_travel_time = last_timestamp - first_timestamp",
        "flow_efficiency = projected_progress_distance / planned_trip_distance",
        "```",
        "",
        "Projected progress is used instead of raw path length for the main flow-efficiency KPI because raw path length can be inflated by detours, oscillation, or collision motion.",
        "",
        "## Criteria",
        "",
        "Speed LOS 기준은 최고/기준속도 30 km/h를 기준으로 한 프로젝트용 기준이다.",
        "",
        "| Average speed | LOS | Interpretation |",
        "|---:|---|---|",
        "| > 25.5 km/h | A | very smooth |",
        "| 20.1-25.5 km/h | B | smooth |",
        "| 15.0-20.1 km/h | C | moderate |",
        "| 12.0-15.0 km/h | D | low speed / delay |",
        "| 9.0-12.0 km/h | E | low efficiency |",
        "| <= 9.0 km/h | F | congested / very poor |",
        "",
        "Flow efficiency 기준:",
        "",
        "| Trip completion/progress | Interpretation |",
        "|---:|---|",
        "| >= 90% | complete |",
        "| 70-90% | mostly complete |",
        "| 40-70% | partial progress |",
        "| 10-40% | poor progress |",
        "| < 10% | stopped or no progress |",
        "",
        "## Parameters",
        "",
        "- reference_speed_kmh: `%s`" % args.reference_speed_kmh,
        "",
        "## Per-Vehicle Results",
        "",
        "| Condition | Role | Avg speed | LOS | Travel time | Flow efficiency |",
        "|---|---|---:|---|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {condition} | {role} | {speed:.2f} km/h | {los} | {time:.1f}s | {flow:.1f}% |".format(
                condition=row["condition"],
                role=row["role_label"],
                speed=row["avg_speed_kmh"],
                los=row["speed_los"],
                time=row["observed_travel_time_s"],
                flow=row["flow_efficiency_percent"],
            ))
    lines.extend([
        "",
        "## Condition Summary",
        "",
        "| Condition | Mean avg speed | Mean LOS | Mean travel time | Mean flow efficiency |",
        "|---|---:|---|---:|---:|",
    ])
    for row in summary:
        lines.append(
            "| {condition} | {speed:.2f} km/h | {los} | {time:.1f}s | {flow:.1f}% |".format(
                condition=row["condition"],
                speed=row["mean_avg_speed_kmh"],
                los=row["mean_speed_los"],
                time=row["mean_observed_travel_time_s"],
                flow=row["mean_flow_efficiency_percent"],
            ))
    lines.extend(["", "## Output Figures", ""])
    for title, file_path in figures:
        if file_path:
            lines.append("- %s: `%s`" % (title, os.path.basename(file_path)))
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def _write_report_v2(path, rows, summary, figures, args):
    lines = [
        "# Scenario 1 Traffic Impact KPIs",
        "",
        "## Scope",
        "",
        "This file calculates only two traffic-impact indicators: progress-adjusted delay and route-completion flow efficiency.",
        "",
        "Average speed and vehicle-count throughput are excluded from this output. Scenario 1 contains a small fixed number of vehicles, so route progress is more meaningful than vehicle count.",
        "",
        "## Formulas",
        "",
        "```text",
        "RC = d_progress / d_route",
        "T_reference = d_route / v_reference",
        "T_progress_adjusted = T_final / RC",
        "progress_adjusted_delay = max(0, T_progress_adjusted - T_reference)",
        "flow_efficiency = RC = d_progress / d_route",
        "```",
        "",
        "`T_final` is the destination-arrival time when the vehicle reaches the arrival-distance threshold. If the vehicle does not arrive, the simulation end time is used. Projected progress is used instead of raw path length because raw path length can be inflated by detours, oscillation, or collision motion.",
        "",
        "## Criteria",
        "",
        "Progress-adjusted delay criteria:",
        "",
        "| Progress-adjusted delay | Interpretation |",
        "|---:|---|",
        "| <= 10s | very smooth |",
        "| 10-15s | good |",
        "| 15-25s | moderate |",
        "| 25-35s | large delay |",
        "| > 35s | severe delay |",
        "",
        "Route completion flow efficiency criteria:",
        "",
        "| Trip completion/progress | Interpretation |",
        "|---:|---|",
        "| >= 80% | high efficiency |",
        "| 60-80% | moderate efficiency |",
        "| < 60% | low efficiency |",
        "| ~= 0% | no progress |",
        "",
        "## Parameters",
        "",
        "- reference_speed_kmh: `%s`" % args.reference_speed_kmh,
        "- arrival_distance_m: `%s`" % args.arrival_distance_m,
        "",
        "## Per-Vehicle Results",
        "",
        "| Condition | Role | Progress delay | Flow efficiency | Progress / route | Time basis |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        progress_delay = (
            "%.1fs" % float(row["progress_adjusted_delay_s"])
            if row["progress_adjusted_delay_s"] != "" else "")
        lines.append(
            "| {condition} | {role} | {delay} | {flow:.1f}% | {progress:.1f}/{route:.1f} m | {basis} |".format(
                condition=row["condition"],
                role=row["role_label"],
                delay=progress_delay,
                flow=row["flow_efficiency_percent"],
                progress=row["projected_progress_distance_m"],
                route=row["route_distance_m"],
                basis=row["final_time_basis"],
            ))
    lines.extend([
        "",
        "## Condition Summary",
        "",
        "| Condition | Mean progress delay | Overall flow efficiency | Progress / route |",
        "|---|---:|---:|---:|",
    ])
    for row in summary:
        progress_delay = (
            "%.1fs" % float(row["mean_progress_adjusted_delay_s"])
            if row["mean_progress_adjusted_delay_s"] != "" else "")
        lines.append(
            "| {condition} | {delay} | {flow:.1f}% | {progress:.1f}/{route:.1f} m |".format(
                condition=row["condition"],
                delay=progress_delay,
                flow=row["overall_flow_efficiency_percent"],
                progress=row["total_projected_progress_distance_m"],
                route=row["total_route_distance_m"],
            ))
    lines.extend(["", "## Output Figures", ""])
    for title, file_path in figures:
        if file_path:
            lines.append("- %s: `%s`" % (title, os.path.basename(file_path)))
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(
        description="Calculate Scenario 1 traffic-impact KPIs only.")
    parser.add_argument("--run-dir", action="append", required=True,
                        help="Scenario 1 datadump run directory. Repeatable.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    parser.add_argument("--reference-speed-kmh", type=float,
                        default=DEFAULT_REFERENCE_SPEED_KMH)
    parser.add_argument("--arrival-distance-m", type=float, default=10.0,
                        help="Distance to destination treated as arrival.")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    rows = _traffic_rows(
        args.run_dir, args.reference_speed_kmh, args.arrival_distance_m)
    summary = _summary_rows(rows)
    _write_csv(os.path.join(args.output_dir, "traffic_impact_kpi.csv"), rows)
    _write_csv(os.path.join(args.output_dir, "traffic_impact_summary.csv"),
               summary)
    figures = [
        ("Flow efficiency", _plot_flow_efficiency(rows, args.output_dir)),
        ("Progress-adjusted delay",
         _plot_progress_adjusted_delay(rows, args.output_dir)),
    ]
    _write_report_v2(
        os.path.join(args.output_dir, "traffic_impact_report.md"),
        rows,
        summary,
        figures,
        args,
    )
    print("Wrote traffic-impact KPIs to", args.output_dir)


if __name__ == "__main__":
    main()
