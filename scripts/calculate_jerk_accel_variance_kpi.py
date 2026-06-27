#!/usr/bin/env python
"""
Calculate acceleration variance and jerk variance from OpenCDA datadumps.

Definitions:
  acceleration[i] = (speed[i] - speed[i-1]) / dt
  jerk[i] = (acceleration[i] - acceleration[i-1]) / dt
  variance = (1 / N) * sum((x_i - mean(x)) ** 2)

Speed is read from ego_speed in the saved YAML datadump and converted from
km/h to m/s before calculating acceleration and jerk.
"""

import argparse
import csv
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import calculate_ride_comfort_kpis as comfort  # noqa: E402


def _write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _summarize(run_dir, observer_id, role, rows):
    scenario, run_time = comfort._scenario_label(run_dir)
    acceleration = [row["acceleration_mps2"] for row in rows[1:]]
    jerk = [row["jerk_mps3"] for row in rows[2:]]
    abs_jerk = [abs(value) for value in jerk]

    max_positive_jerk = max(jerk) if jerk else 0.0
    max_negative_jerk = min(jerk) if jerk else 0.0
    max_abs_jerk = max(abs_jerk) if abs_jerk else 0.0
    max_abs_jerk_frame = ""
    max_abs_jerk_time = ""
    if jerk:
        max_index = max(range(len(jerk)), key=lambda index: abs(jerk[index]))
        # jerk starts at rows[2].
        max_abs_jerk_frame = rows[max_index + 2]["frame"]
        max_abs_jerk_time = rows[max_index + 2]["time_s"]

    return {
        "scenario": scenario,
        "run_time": run_time,
        "observer_id": observer_id,
        "observer_role": role,
        "frames": len(rows),
        "duration_s": rows[-1]["time_s"] - rows[0]["time_s"] if rows else 0.0,
        "acceleration_mean_mps2": comfort._mean(acceleration),
        "acceleration_rms_mps2": comfort._rms(acceleration),
        "acceleration_variance_mps4": comfort._variance(acceleration),
        "acceleration_abs_p95_mps2":
        comfort._percentile([abs(value) for value in acceleration], 95),
        "max_accel_mps2": max(acceleration) if acceleration else 0.0,
        "max_decel_mps2": abs(min(acceleration)) if acceleration else 0.0,
        "jerk_mean_mps3": comfort._mean(jerk),
        "jerk_rms_mps3": comfort._rms(jerk),
        "jerk_variance_mps6": comfort._variance(jerk),
        "jerk_abs_p95_mps3": comfort._percentile(abs_jerk, 95),
        "max_positive_jerk_mps3": max_positive_jerk,
        "max_negative_jerk_mps3": max_negative_jerk,
        "max_abs_jerk_mps3": max_abs_jerk,
        "max_abs_jerk_frame": max_abs_jerk_frame,
        "max_abs_jerk_time_s": max_abs_jerk_time,
    }


def _write_report(path, rows, run_dirs):
    lines = [
        "# Scenario 1 Jerk / Acceleration Variance KPI",
        "",
        "Data source: saved OpenCDA datadump YAML files.",
        "",
        "Formula:",
        "",
        "```text",
        "speed_mps = ego_speed_kmh / 3.6",
        "acceleration[i] = (speed[i] - speed[i-1]) / dt",
        "jerk[i] = (acceleration[i] - acceleration[i-1]) / dt",
        "variance = (1 / N) * sum((x_i - mean(x))^2)",
        "```",
        "",
        "Lower acceleration variance and jerk variance indicate smoother "
        "longitudinal ride comfort.",
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
        "| scenario | observer | accel var | accel RMS | jerk var | jerk RMS | jerk p95 | +jerk max | -jerk max | peak time |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in rows:
        observer = "%s(%s)" % (row["observer_role"], row["observer_id"])
        lines.append(
            "| {scenario} | {observer} | {accel_var:.4f} | {accel_rms:.4f} | "
            "{jerk_var:.4f} | {jerk_rms:.4f} | {jerk_p95:.4f} | "
            "{pos:.4f} | {neg:.4f} | {time} |".format(
                scenario=row["scenario"],
                observer=observer,
                accel_var=row["acceleration_variance_mps4"],
                accel_rms=row["acceleration_rms_mps2"],
                jerk_var=row["jerk_variance_mps6"],
                jerk_rms=row["jerk_rms_mps3"],
                jerk_p95=row["jerk_abs_p95_mps3"],
                pos=row["max_positive_jerk_mps3"],
                neg=row["max_negative_jerk_mps3"],
                time=("%.2f" % row["max_abs_jerk_time_s"]
                      if row["max_abs_jerk_time_s"] != "" else "-")))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def _plot_jerk_like_example(output_dir, summary, rows):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return

    scenario = summary["scenario"]
    role = summary["observer_role"]
    label = "%s_%s" % (scenario, role)
    times = [row["time_s"] for row in rows]
    jerk = [row["jerk_mps3"] for row in rows]
    if not times or not jerk:
        return

    pos_index = max(range(len(jerk)), key=lambda index: jerk[index])
    neg_index = min(range(len(jerk)), key=lambda index: jerk[index])
    peak_index = max(range(len(jerk)), key=lambda index: abs(jerk[index]))

    fig, ax = plt.subplots(figsize=(10.8, 4.2))
    ax.plot(times, jerk, color="#70A84A", linewidth=2.2)
    ax.scatter([times[pos_index]], [jerk[pos_index]], color="black", s=34,
               zorder=4)
    ax.scatter([times[neg_index]], [jerk[neg_index]], color="black", s=34,
               zorder=4)
    ax.axvline(times[peak_index], color="#C94848", linestyle="--",
               linewidth=1.1, alpha=0.8)
    ax.annotate(
        "Positive Jerk",
        xy=(times[pos_index], jerk[pos_index]),
        xytext=(12, 0),
        textcoords="offset points",
        va="center",
        fontsize=11,
        fontweight="bold",
        arrowprops={"arrowstyle": "-", "color": "black", "linewidth": 0.8})
    ax.annotate(
        "Negative Jerk",
        xy=(times[neg_index], jerk[neg_index]),
        xytext=(12, 0),
        textcoords="offset points",
        va="center",
        fontsize=11,
        fontweight="bold",
        arrowprops={"arrowstyle": "-", "color": "black", "linewidth": 0.8})

    ax.set_title("%s %s Jerk Time Series" %
                 (scenario.replace("scenario1_", "").upper(), role.upper()),
                 loc="left", fontsize=12, fontweight="bold")
    ax.set_xlabel("Time (s)", fontsize=12, fontweight="bold")
    ax.set_ylabel("Jerk ($m/s^3$)", fontsize=12, fontweight="bold")
    ax.set_ylim(-250, 250)
    ax.set_yticks([-250, -200, -150, -100, -50, 0, 50, 100, 150, 200, 250])
    ax.grid(False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_position(("outward", 4))
    ax.spines["bottom"].set_position(("outward", 4))
    ax.annotate(
        "",
        xy=(1.01, 0), xycoords=("axes fraction", "axes fraction"),
        xytext=(0, 0), textcoords=("axes fraction", "axes fraction"),
        arrowprops={"arrowstyle": "->", "color": "#666666", "linewidth": 1.2})
    ax.annotate(
        "",
        xy=(0, 1.03), xycoords=("axes fraction", "axes fraction"),
        xytext=(0, 0), textcoords=("axes fraction", "axes fraction"),
        arrowprops={"arrowstyle": "->", "color": "#666666", "linewidth": 1.2})
    ax.text(times[peak_index], ax.get_ylim()[0], "$t$", ha="center",
            va="top", fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "%s_jerk_example_style.png" % label),
                dpi=180)
    plt.close(fig)


def _plot_variance_comparison(output_dir, summary_rows):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return

    labels = [
        "%s-%s" % (row["scenario"].replace("scenario1_", ""),
                   row["observer_role"])
        for row in summary_rows
    ]
    x_positions = list(range(len(summary_rows)))
    width = 0.34

    fig, ax = plt.subplots(figsize=(9.8, 5.2))
    accel = [row["acceleration_variance_mps4"] for row in summary_rows]
    jerk = [row["jerk_variance_mps6"] for row in summary_rows]
    xs_accel = [x - width / 2 for x in x_positions]
    xs_jerk = [x + width / 2 for x in x_positions]
    bars_accel = ax.bar(xs_accel, accel, width, label="Acceleration variance",
                        color="#2674BA")
    bars_jerk = ax.bar(xs_jerk, jerk, width, label="Jerk variance",
                       color="#D95F02")
    ax.bar_label(bars_accel, fmt="%.2f", padding=3, fontsize=9)
    ax.bar_label(bars_jerk, fmt="%.1f", padding=3, fontsize=9)
    ax.set_title("Acceleration / Jerk Variance")
    ax.set_ylabel("Variance")
    ax.set_ylim(0, max(accel + jerk) * 1.18)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=10, ha="right")
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir,
                             "acceleration_jerk_variance_comparison.png"),
                dpi=180)
    plt.close(fig)


def _plot_jerk_peak_comparison(output_dir, summary_rows):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return

    labels = [
        "%s-%s" % (row["scenario"].replace("scenario1_", ""),
                   row["observer_role"])
        for row in summary_rows
    ]
    metrics = [
        ("jerk_rms_mps3", "Jerk RMS", "#2674BA"),
        ("jerk_abs_p95_mps3", "Jerk |P95|", "#2A9D76"),
        ("max_abs_jerk_mps3", "Max |Jerk|", "#D95F02"),
    ]
    x_positions = list(range(len(summary_rows)))
    width = 0.24

    fig, ax = plt.subplots(figsize=(9.8, 5.2))
    all_values = []
    for index, (key, label, color) in enumerate(metrics):
        values = [row[key] for row in summary_rows]
        all_values.extend(values)
        xs = [x + (index - 1) * width for x in x_positions]
        bars = ax.bar(xs, values, width, label=label, color=color)
        ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=9)

    ax.set_title("Jerk KPI Including Maximum Jerk")
    ax.set_ylabel("Jerk ($m/s^3$)")
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=10, ha="right")
    ax.set_ylim(0, max(all_values) * 1.18 if all_values else 1.0)
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "jerk_kpi_with_max_comparison.png"),
                dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="Calculate acceleration and jerk variance KPIs.")
    parser.add_argument("--run-dir", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--role", action="append",
                        help="Vehicle role to evaluate. Defaults to ego.")
    args = parser.parse_args()

    role_filter = set(args.role or ["ego"])
    summary_rows = []
    timeseries_rows = []
    plot_payload = []

    for run_dir in args.run_dir:
        dt = comfort._fixed_delta_seconds(run_dir)
        for observer_id, observer_dir, role in comfort._iter_vehicle_observers(
                run_dir, role_filter=role_filter):
            rows = comfort._read_ego_timeseries(
                observer_dir, dt, comfort.DEFAULT_WHEELBASE_M,
                comfort.DEFAULT_MIN_SPEED_FOR_STEERING_MPS)
            if not rows:
                continue
            summary = _summarize(run_dir, observer_id, role, rows)
            summary["fixed_delta_seconds"] = dt
            summary_rows.append(summary)
            plot_payload.append((summary, rows))
            for row in rows:
                scenario, run_time = comfort._scenario_label(run_dir)
                output = {
                    "scenario": scenario,
                    "run_time": run_time,
                    "observer_id": observer_id,
                    "observer_role": role,
                    "frame": row["frame"],
                    "time_s": row["time_s"],
                    "speed_kmh": row["speed_kmh"],
                    "speed_mps": row["speed_mps"],
                    "acceleration_mps2": row["acceleration_mps2"],
                    "jerk_mps3": row["jerk_mps3"],
                }
                timeseries_rows.append(output)

    if not summary_rows:
        raise SystemExit("No acceleration/jerk KPI rows were generated.")

    os.makedirs(args.output_dir, exist_ok=True)
    _write_csv(os.path.join(args.output_dir,
                            "acceleration_jerk_variance_summary.csv"),
               summary_rows)
    _write_csv(os.path.join(args.output_dir,
                            "acceleration_jerk_timeseries.csv"),
               timeseries_rows)
    _write_report(os.path.join(args.output_dir,
                               "acceleration_jerk_variance_report.md"),
                  summary_rows, args.run_dir)
    for summary, rows in plot_payload:
        _plot_jerk_like_example(args.output_dir, summary, rows)
    _plot_variance_comparison(args.output_dir, summary_rows)
    _plot_jerk_peak_comparison(args.output_dir, summary_rows)
    print("Wrote acceleration/jerk variance KPI to", args.output_dir)


if __name__ == "__main__":
    main()
