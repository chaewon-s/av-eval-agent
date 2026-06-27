#!/usr/bin/env python
"""
Calculate ride-comfort KPIs from OpenCDA datadump YAML files.

Inputs are post-run datadumps under data_dumping/<scenario>/<run_time>.
The dump currently contains pose, yaw, speed, and velocity, but not the raw
CARLA steering command. Steering smoothness is therefore reported as a
trajectory-based proxy derived from yaw/curvature.
"""

import argparse
import csv
import math
import os
import sys

import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import calculate_tracking_hota as hota  # noqa: E402


DEFAULT_WHEELBASE_M = 2.875
DEFAULT_MIN_SPEED_FOR_STEERING_MPS = 0.5


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def _variance(values):
    if not values:
        return 0.0
    avg = _mean(values)
    return sum((value - avg) ** 2 for value in values) / len(values)


def _rms(values):
    if not values:
        return 0.0
    return math.sqrt(sum(value * value for value in values) / len(values))


def _percentile(values, pct):
    if not values:
        return 0.0
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * pct / 100.0
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return values[lower]
    ratio = pos - lower
    return values[lower] * (1.0 - ratio) + values[upper] * ratio


def _unwrap_radians(values):
    if not values:
        return []
    output = [values[0]]
    for value in values[1:]:
        previous = output[-1]
        delta = value - previous
        while delta > math.pi:
            value -= 2.0 * math.pi
            delta = value - previous
        while delta < -math.pi:
            value += 2.0 * math.pi
            delta = value - previous
        output.append(value)
    return output


def _diff(values, dt):
    if len(values) < 2 or dt <= 0:
        return []
    return [(values[i] - values[i - 1]) / dt for i in range(1, len(values))]


def _scenario_label(run_dir):
    scenario, run_time = hota._run_label(run_dir)
    if not scenario:
        scenario = os.path.basename(os.path.dirname(run_dir))
    if not run_time:
        run_time = os.path.basename(run_dir)
    return scenario, run_time


def _fixed_delta_seconds(run_dir):
    protocol_path = os.path.join(run_dir, "data_protocol.yaml")
    if not os.path.exists(protocol_path):
        return 0.1
    protocol = _load_yaml(protocol_path)
    return _safe_float(
        ((protocol.get("world") or {}).get("fixed_delta_seconds")), 0.1)


def _iter_vehicle_observers(run_dir, role_filter=None):
    roles = hota._infer_roles(run_dir)
    for observer_id, observer_dir in hota._iter_observer_dirs(run_dir, None):
        role = roles.get(observer_id, "unknown")
        if observer_id == "-1" or role == "rsu":
            continue
        if role_filter and role not in role_filter:
            continue
        yield observer_id, observer_dir, role


def _read_ego_timeseries(observer_dir, dt, wheelbase_m,
                         min_speed_for_steering_mps):
    rows = []
    yaml_files = sorted(
        f for f in os.listdir(observer_dir)
        if f.lower().endswith(".yaml") and f[:6].isdigit())

    for file_name in yaml_files:
        frame = int(file_name[:6])
        data = _load_yaml(os.path.join(observer_dir, file_name))
        pose = data.get("true_ego_pos") or []
        velocity = data.get("ego_velocity") or []
        speed_kmh = _safe_float(data.get("ego_speed"))
        speed_mps = speed_kmh / 3.6
        if len(velocity) >= 2:
            vx = _safe_float(velocity[0])
            vy = _safe_float(velocity[1])
            vz = _safe_float(velocity[2]) if len(velocity) > 2 else 0.0
            velocity_mps = math.sqrt(vx * vx + vy * vy + vz * vz)
        else:
            velocity_mps = speed_mps
        rows.append({
            "frame": frame,
            "time_s": (frame - 1) * dt,
            "x_m": _safe_float(pose[0]) if len(pose) > 0 else 0.0,
            "y_m": _safe_float(pose[1]) if len(pose) > 1 else 0.0,
            "yaw_rad": math.radians(_safe_float(pose[4])) if len(pose) > 4
            else 0.0,
            "speed_kmh": speed_kmh,
            "speed_mps": speed_mps,
            "velocity_mps": velocity_mps,
        })

    yaw_values = _unwrap_radians([row["yaw_rad"] for row in rows])
    speeds = [row["speed_mps"] for row in rows]
    acceleration = _diff(speeds, dt)
    jerk = _diff(acceleration, dt)
    yaw_rate = _diff(yaw_values, dt)

    steering_proxy = []
    for index, row in enumerate(rows):
        if index == 0 or index - 1 >= len(yaw_rate):
            steering_proxy.append(0.0)
            continue
        speed = max(row["speed_mps"], min_speed_for_steering_mps)
        curvature = yaw_rate[index - 1] / speed
        steering_proxy.append(math.atan(wheelbase_m * curvature))
    steering_rate_proxy = _diff(steering_proxy, dt)

    for index, row in enumerate(rows):
        row["yaw_unwrapped_rad"] = yaw_values[index]
        row["acceleration_mps2"] = acceleration[index - 1] if index > 0 else 0.0
        row["jerk_mps3"] = jerk[index - 2] if index > 1 else 0.0
        row["yaw_rate_rad_s"] = yaw_rate[index - 1] if index > 0 else 0.0
        row["steering_angle_proxy_rad"] = steering_proxy[index]
        row["steering_rate_proxy_rad_s"] = (
            steering_rate_proxy[index - 1] if index > 0 else 0.0)
    return rows


def _comfort_score(row):
    # Conservative 0-100 score: lower jerk/accel variation and smoother
    # steering-rate proxy should score higher. It is a report convenience score,
    # not a direct ISO 2631-1 weighted acceleration value.
    jerk_score = max(0.0, 100.0 - 8.0 * row["jerk_rms_mps3"])
    accel_score = max(0.0, 100.0 - 18.0 * row["acceleration_rms_mps2"])
    steering_score = max(0.0, 100.0 -
                         90.0 * row["steering_rate_proxy_rms_rad_s"])
    return 0.4 * jerk_score + 0.35 * accel_score + 0.25 * steering_score


def _summarize_timeseries(run_dir, observer_id, role, rows):
    scenario, run_time = _scenario_label(run_dir)
    accel = [row["acceleration_mps2"] for row in rows[1:]]
    jerk = [row["jerk_mps3"] for row in rows[2:]]
    yaw_rate = [row["yaw_rate_rad_s"] for row in rows[1:]]
    steering_rate = [row["steering_rate_proxy_rad_s"] for row in rows[2:]]
    speed = [row["speed_mps"] for row in rows]

    summary = {
        "scenario": scenario,
        "run_time": run_time,
        "observer_id": observer_id,
        "observer_role": role,
        "frames": len(rows),
        "duration_s": rows[-1]["time_s"] - rows[0]["time_s"] if rows else 0.0,
        "avg_speed_kmh": _mean(speed) * 3.6,
        "max_speed_kmh": max(speed) * 3.6 if speed else 0.0,
        "acceleration_mean_mps2": _mean(accel),
        "acceleration_rms_mps2": _rms(accel),
        "acceleration_variance_mps4": _variance(accel),
        "max_accel_mps2": max(accel) if accel else 0.0,
        "max_decel_mps2": abs(min(accel)) if accel else 0.0,
        "jerk_mean_mps3": _mean(jerk),
        "jerk_rms_mps3": _rms(jerk),
        "jerk_variance_mps6": _variance(jerk),
        "jerk_abs_p95_mps3": _percentile([abs(v) for v in jerk], 95),
        "jerk_abs_max_mps3": max([abs(v) for v in jerk], default=0.0),
        "yaw_rate_rms_rad_s": _rms(yaw_rate),
        "yaw_rate_abs_p95_rad_s": _percentile([abs(v) for v in yaw_rate], 95),
        "steering_rate_proxy_rms_rad_s": _rms(steering_rate),
        "steering_rate_proxy_variance_rad2_s2": _variance(steering_rate),
        "steering_rate_proxy_abs_p95_rad_s":
        _percentile([abs(v) for v in steering_rate], 95),
        "steering_rate_proxy_abs_max_rad_s":
        max([abs(v) for v in steering_rate], default=0.0),
        "steering_source": "yaw_curvature_proxy",
    }
    summary["comfort_score_100"] = _comfort_score(summary)
    return summary


def _write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path, summary_rows, run_dirs):
    lines = [
        "# Scenario Ride Comfort KPI Report",
        "",
        "Data source: saved OpenCDA datadump YAML files.",
        "",
        "## KPI Definitions",
        "",
        "- `acceleration_rms_mps2`: RMS of longitudinal acceleration from ego speed.",
        "- `acceleration_variance_mps4`: variance of longitudinal acceleration.",
        "- `jerk_rms_mps3`: RMS of jerk from acceleration derivative.",
        "- `jerk_variance_mps6`: variance of jerk.",
        "- `steering_rate_proxy_rms_rad_s`: RMS of yaw/curvature-based steering-angle-rate proxy.",
        "- `steering_source`: current dump has no raw steering command, so steering smoothness is a trajectory proxy.",
        "",
        "Formula summary:",
        "",
        "```text",
        "speed_mps = ego_speed_kmh / 3.6",
        "acceleration[i] = (speed[i] - speed[i-1]) / dt",
        "jerk[i] = (acceleration[i] - acceleration[i-1]) / dt",
        "yaw_rate[i] = unwrap(yaw[i] - yaw[i-1]) / dt",
        "curvature[i] = yaw_rate[i] / max(speed[i], 0.5)",
        "steering_angle_proxy[i] = atan(wheelbase * curvature[i])",
        "steering_rate_proxy[i] = d(steering_angle_proxy) / dt",
        "```",
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
        "| scenario | observer | accel RMS | accel var | jerk RMS | jerk var | steering-rate RMS | steering-rate p95 | score |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in summary_rows:
        observer = "%s(%s)" % (row["observer_role"], row["observer_id"])
        lines.append(
            "| {scenario} | {observer} | {accel:.4f} | {accel_var:.4f} | "
            "{jerk:.4f} | {jerk_var:.4f} | {steer:.4f} | {steer_p95:.4f} | "
            "{score:.1f} |".format(
                scenario=row["scenario"],
                observer=observer,
                accel=row["acceleration_rms_mps2"],
                accel_var=row["acceleration_variance_mps4"],
                jerk=row["jerk_rms_mps3"],
                jerk_var=row["jerk_variance_mps6"],
                steer=row["steering_rate_proxy_rms_rad_s"],
                steer_p95=row["steering_rate_proxy_abs_p95_rad_s"],
                score=row["comfort_score_100"]))
    lines.extend([
        "",
        "## Interpretation",
        "",
        "Lower acceleration RMS/variance and jerk RMS/variance indicate smoother longitudinal ride comfort. Lower steering-rate proxy indicates smoother lateral motion/heading control. The score is a convenience normalization for comparison, not a direct ISO 2631-1 weighted score.",
    ])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def _plot_summary(output_dir, summary_rows):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return
    if not summary_rows:
        return
    labels = [
        "%s-%s" % (row["scenario"].replace("scenario1_", ""),
                   row["observer_role"])
        for row in summary_rows
    ]
    metrics = [
        ("acceleration_rms_mps2", "Accel RMS"),
        ("jerk_rms_mps3", "Jerk RMS"),
        ("steering_rate_proxy_rms_rad_s", "Steering-rate RMS"),
    ]
    x_positions = list(range(len(summary_rows)))
    width = 0.24

    fig, ax = plt.subplots(figsize=(11, 5.6))
    colors = ["#2674BA", "#D95F02", "#2A9D76"]
    for idx, (key, label) in enumerate(metrics):
        xs = [x + (idx - 1) * width for x in x_positions]
        ax.bar(xs, [row[key] for row in summary_rows], width,
               label=label, color=colors[idx])
    ax.set_title("Ride Comfort KPI Comparison")
    ax.set_ylabel("Metric value")
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=12, ha="right")
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "ride_comfort_kpi_comparison.png"),
                dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.5, 5.0))
    bars = ax.bar(x_positions, [row["comfort_score_100"] for row in summary_rows],
                  color="#111827")
    ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=9)
    ax.set_title("Ride Comfort Score")
    ax.set_ylabel("Score (0-100)")
    ax.set_ylim(0, 100)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=12, ha="right")
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "ride_comfort_score.png"), dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="Calculate ride-comfort KPIs from OpenCDA datadumps.")
    parser.add_argument("--run-dir", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--role", action="append",
                        help="Vehicle role to evaluate. Defaults to ego.")
    parser.add_argument("--wheelbase-m", type=float,
                        default=DEFAULT_WHEELBASE_M)
    parser.add_argument("--min-speed-for-steering-mps", type=float,
                        default=DEFAULT_MIN_SPEED_FOR_STEERING_MPS)
    args = parser.parse_args()

    role_filter = set(args.role or ["ego"])
    summary_rows = []
    timeseries_rows = []

    for run_dir in args.run_dir:
        dt = _fixed_delta_seconds(run_dir)
        for observer_id, observer_dir, role in _iter_vehicle_observers(
                run_dir, role_filter=role_filter):
            rows = _read_ego_timeseries(
                observer_dir, dt, args.wheelbase_m,
                args.min_speed_for_steering_mps)
            if not rows:
                continue
            summary = _summarize_timeseries(run_dir, observer_id, role, rows)
            summary["fixed_delta_seconds"] = dt
            summary["wheelbase_m"] = args.wheelbase_m
            summary_rows.append(summary)
            for row in rows:
                output_row = {
                    "scenario": summary["scenario"],
                    "run_time": summary["run_time"],
                    "observer_id": observer_id,
                    "observer_role": role,
                }
                output_row.update(row)
                timeseries_rows.append(output_row)

    if not summary_rows:
        raise SystemExit("No ride-comfort KPI rows were generated.")

    os.makedirs(args.output_dir, exist_ok=True)
    _write_csv(os.path.join(args.output_dir, "ride_comfort_kpi_summary.csv"),
               summary_rows)
    _write_csv(os.path.join(args.output_dir, "ride_comfort_timeseries.csv"),
               timeseries_rows)
    _write_report(os.path.join(args.output_dir, "ride_comfort_kpi_report.md"),
                  summary_rows, args.run_dir)
    _plot_summary(args.output_dir, summary_rows)
    print("Wrote ride-comfort KPIs to", args.output_dir)


if __name__ == "__main__":
    main()
