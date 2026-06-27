#!/usr/bin/env python
"""
Calculate steering smoothness KPIs from OpenCDA datadump YAML files.

The current datadump stores pose/yaw/speed, but not the raw CARLA steering
command. This script therefore reports steering smoothness as a trajectory
proxy:

  yaw_rate = d(yaw) / dt
  curvature = yaw_rate / speed
  steering_angle_proxy = atan(wheelbase * curvature)
  steering_rate_proxy = d(steering_angle_proxy) / dt

Lower steering_rate_proxy RMS/variance/p95 means smoother steering behavior.
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
    steering_angle = [row["steering_angle_proxy_rad"] for row in rows]
    steering_rate = [row["steering_rate_proxy_rad_s"] for row in rows[2:]]
    yaw_rate = [row["yaw_rate_rad_s"] for row in rows[1:]]

    return {
        "scenario": scenario,
        "run_time": run_time,
        "observer_id": observer_id,
        "observer_role": role,
        "frames": len(rows),
        "duration_s": rows[-1]["time_s"] - rows[0]["time_s"] if rows else 0.0,
        "yaw_rate_rms_rad_s": comfort._rms(yaw_rate),
        "yaw_rate_abs_p95_rad_s":
        comfort._percentile([abs(value) for value in yaw_rate], 95),
        "steering_angle_proxy_rms_rad": comfort._rms(steering_angle),
        "steering_angle_proxy_abs_p95_rad":
        comfort._percentile([abs(value) for value in steering_angle], 95),
        "steering_angle_proxy_abs_max_rad":
        max([abs(value) for value in steering_angle], default=0.0),
        "steering_rate_proxy_mean_rad_s": comfort._mean(steering_rate),
        "steering_rate_proxy_rms_rad_s": comfort._rms(steering_rate),
        "steering_rate_proxy_variance_rad2_s2": comfort._variance(
            steering_rate),
        "steering_rate_proxy_abs_p95_rad_s":
        comfort._percentile([abs(value) for value in steering_rate], 95),
        "steering_rate_proxy_abs_max_rad_s":
        max([abs(value) for value in steering_rate], default=0.0),
        "steering_source": "yaw_curvature_proxy",
    }


def _write_report(path, rows, run_dirs):
    lines = [
        "# Scenario 1 Steering Smoothness KPI",
        "",
        "Data source: saved OpenCDA datadump YAML files.",
        "",
        "The current YAML dump does not contain the raw CARLA `steer` command, "
        "so steering smoothness is calculated as a yaw/curvature-based proxy.",
        "",
        "Formula:",
        "",
        "```text",
        "yaw_rate = unwrap(yaw[i] - yaw[i-1]) / dt",
        "curvature = yaw_rate / max(speed_mps, 0.5)",
        "steering_angle_proxy = atan(wheelbase * curvature)",
        "steering_rate_proxy = d(steering_angle_proxy) / dt",
        "```",
        "",
        "Lower `steering_rate_proxy_rms_rad_s`, variance, p95, and max values "
        "indicate smoother steering.",
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
        "| scenario | observer | yaw-rate RMS | steering-rate RMS | steering-rate var | steering-rate p95 | steering-rate max | source |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ])
    for row in rows:
        observer = "%s(%s)" % (row["observer_role"], row["observer_id"])
        lines.append(
            "| {scenario} | {observer} | {yaw:.4f} | {rms:.4f} | "
            "{var:.4f} | {p95:.4f} | {maxv:.4f} | {source} |".format(
                scenario=row["scenario"],
                observer=observer,
                yaw=row["yaw_rate_rms_rad_s"],
                rms=row["steering_rate_proxy_rms_rad_s"],
                var=row["steering_rate_proxy_variance_rad2_s2"],
                p95=row["steering_rate_proxy_abs_p95_rad_s"],
                maxv=row["steering_rate_proxy_abs_max_rad_s"],
                source=row["steering_source"]))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def _plot(output_dir, summary_rows, timeseries_rows):
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
        ("steering_rate_proxy_rms_rad_s", "RMS", "#2674BA"),
        ("steering_rate_proxy_abs_p95_rad_s", "P95 abs", "#2A9D76"),
        ("steering_rate_proxy_abs_max_rad_s", "Max abs", "#D95F02"),
    ]
    x_positions = list(range(len(summary_rows)))
    width = 0.24

    fig, ax = plt.subplots(figsize=(10.5, 5.4))
    for index, (key, label, color) in enumerate(metrics):
        xs = [x + (index - 1) * width for x in x_positions]
        bars = ax.bar(xs, [row[key] for row in summary_rows], width,
                      label=label, color=color)
        ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=9)
    ax.set_title("Steering Smoothness KPI")
    ax.set_ylabel("Steering-rate proxy (rad/s)")
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=12, ha="right")
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "steering_smoothness_kpi.png"),
                dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 5.4))
    groups = {}
    for row in timeseries_rows:
        label = "%s-%s" % (row["scenario"].replace("scenario1_", ""),
                           row["observer_role"])
        groups.setdefault(label, []).append(row)
    for label, rows in groups.items():
        rows = sorted(rows, key=lambda row: int(row["frame"]))
        ax.plot(
            [float(row["time_s"]) for row in rows],
            [float(row["steering_rate_proxy_rad_s"]) for row in rows],
            linewidth=1.4, label=label)
    ax.set_title("Steering-Rate Proxy Time Series")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Steering-rate proxy (rad/s)")
    ax.axhline(0, color="#111827", linewidth=0.8, alpha=0.35)
    ax.grid(True, linestyle="--", linewidth=0.6, alpha=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "steering_rate_timeseries.png"),
                dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="Calculate steering smoothness KPI from OpenCDA dumps.")
    parser.add_argument("--run-dir", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--role", action="append",
                        help="Vehicle role to evaluate. Defaults to ego.")
    parser.add_argument("--wheelbase-m", type=float,
                        default=comfort.DEFAULT_WHEELBASE_M)
    parser.add_argument("--min-speed-for-steering-mps", type=float,
                        default=comfort.DEFAULT_MIN_SPEED_FOR_STEERING_MPS)
    args = parser.parse_args()

    role_filter = set(args.role or ["ego"])
    summary_rows = []
    timeseries_rows = []
    for run_dir in args.run_dir:
        dt = comfort._fixed_delta_seconds(run_dir)
        for observer_id, observer_dir, role in comfort._iter_vehicle_observers(
                run_dir, role_filter=role_filter):
            rows = comfort._read_ego_timeseries(
                observer_dir, dt, args.wheelbase_m,
                args.min_speed_for_steering_mps)
            if not rows:
                continue
            summary_rows.append(_summarize(run_dir, observer_id, role, rows))
            scenario, run_time = comfort._scenario_label(run_dir)
            for row in rows:
                output = {
                    "scenario": scenario,
                    "run_time": run_time,
                    "observer_id": observer_id,
                    "observer_role": role,
                }
                output.update({
                    "frame": row["frame"],
                    "time_s": row["time_s"],
                    "speed_kmh": row["speed_kmh"],
                    "yaw_rate_rad_s": row["yaw_rate_rad_s"],
                    "steering_angle_proxy_rad":
                    row["steering_angle_proxy_rad"],
                    "steering_rate_proxy_rad_s":
                    row["steering_rate_proxy_rad_s"],
                })
                timeseries_rows.append(output)

    if not summary_rows:
        raise SystemExit("No steering smoothness rows were generated.")

    os.makedirs(args.output_dir, exist_ok=True)
    _write_csv(os.path.join(args.output_dir,
                            "steering_smoothness_summary.csv"),
               summary_rows)
    _write_csv(os.path.join(args.output_dir,
                            "steering_smoothness_timeseries.csv"),
               timeseries_rows)
    _write_report(os.path.join(args.output_dir,
                               "steering_smoothness_report.md"),
                  summary_rows, args.run_dir)
    _plot(args.output_dir, summary_rows, timeseries_rows)
    print("Wrote steering smoothness KPI to", args.output_dir)


if __name__ == "__main__":
    main()
