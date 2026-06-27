#!/usr/bin/env python
"""Calculate Scenario 1 control-performance KPIs with event-aware windows.

This dedicated script evaluates only ego-vehicle control performance. It cuts
the normal stability window before the collision/closest-approach event so that
stationary post-crash frames cannot make No V2X look artificially smooth. It
also calculates a short event-response window around the event to capture
emergency braking/steering severity.

Primary KPIs:
- steering-rate proxy RMS
- steering-rate proxy absolute P95
- acceleration variance

Supplementary KPIs:
- steering-rate proxy absolute max
- acceleration absolute P95
- jerk absolute P95/max
"""

import argparse
import csv
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
    "scenario1_control_performance_event_window_2026_06_01",
)
DEFAULT_COLLISION_DISTANCE_M = 4.5
DEFAULT_EVENT_PRE_SECONDS = 2.0
DEFAULT_EVENT_POST_SECONDS = 0.5


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


def _condition_label(scenario):
    if "no_v2x" in scenario:
        return "No V2X"
    if "v2x" in scenario:
        return "V2X"
    return scenario


def _sort_key(row):
    condition_order = {"No V2X": 0, "V2X": 1}
    window_order = {"pre_event": 0, "event_response": 1}
    return (condition_order.get(row.get("condition"), 99),
            window_order.get(row.get("evaluation_window",
                                     row.get("window", "")), 99),
            row.get("scenario", ""),
            row.get("run_time", ""))


def _duration(rows):
    if len(rows) < 2:
        return 0.0
    return rows[-1]["time_s"] - rows[0]["time_s"]


def _metric_values(series):
    accel = [row["acceleration_mps2"] for row in series[1:]]
    steering_rate = [row["steering_rate_proxy_rad_s"] for row in series[2:]]
    jerk = [row["jerk_mps3"] for row in series[2:]]
    abs_steering_rate = [abs(value) for value in steering_rate]
    abs_accel = [abs(value) for value in accel]
    abs_jerk = [abs(value) for value in jerk]
    return {
        "accel": accel,
        "steering_rate": steering_rate,
        "jerk": jerk,
        "abs_steering_rate": abs_steering_rate,
        "abs_accel": abs_accel,
        "abs_jerk": abs_jerk,
    }


def _class_steering_rms(value):
    if value <= 0.05:
        return "very_smooth"
    if value <= 0.10:
        return "smooth"
    if value <= 0.20:
        return "moderate"
    return "unstable"


def _class_accel_variance(value):
    if value <= 1.0:
        return "very_smooth"
    if value <= 3.0:
        return "smooth"
    if value <= 6.0:
        return "moderate"
    return "unstable"


def _series_for_window(full_series, cutoff, window, event_pre_s,
                       event_post_s):
    event_frame = cutoff["event_frame"]
    event_time = cutoff["event_time_s"]
    if window == "pre_event":
        if isinstance(event_frame, int):
            return [row for row in full_series if row["frame"] < event_frame]
        return list(full_series)

    if event_time == "":
        return list(full_series)
    start_s = max(float(full_series[0]["time_s"]), float(event_time) - event_pre_s)
    end_s = min(float(full_series[-1]["time_s"]), float(event_time) + event_post_s)
    return [
        row for row in full_series
        if start_s <= float(row["time_s"]) <= end_s
    ]


def _window_bounds(full_series, cutoff, window, event_pre_s, event_post_s):
    if not full_series:
        return "", ""
    event_time = cutoff["event_time_s"]
    if window == "pre_event":
        return full_series[0]["time_s"], event_time
    if event_time == "":
        return full_series[0]["time_s"], full_series[-1]["time_s"]
    return (
        max(float(full_series[0]["time_s"]), float(event_time) - event_pre_s),
        min(float(full_series[-1]["time_s"]), float(event_time) + event_post_s),
    )


def _window_note(window):
    if window == "pre_event":
        return (
            "Normal control stability before the event. Event and post-event "
            "stationary frames are excluded.")
    return (
        "Emergency response severity around the event. This short window "
        "includes immediate post-event reaction but avoids long stationary "
        "post-crash frames.")


def _control_rows(run_dirs, collision_distance_m, event_pre_s, event_post_s):
    rows = []
    timeseries_rows = []
    for run_dir in run_dirs:
        scenario, run_time = revised._scenario_and_time(run_dir)
        condition = _condition_label(scenario)
        observer_id, full_series = revised._role_timeseries(run_dir, "ego")
        if not full_series:
            continue

        cutoff = revised._event_cutoff(run_dir, collision_distance_m)
        for window in ["pre_event", "event_response"]:
            used_series = _series_for_window(
                full_series, cutoff, window, event_pre_s, event_post_s)
            if not used_series:
                continue
            values = _metric_values(used_series)
            steering_rms = revised._metric_rms(values["steering_rate"])
            accel_variance = revised._metric_variance(values["accel"])
            window_start_s, window_end_s = _window_bounds(
                full_series, cutoff, window, event_pre_s, event_post_s)
            row = {
                "scenario": scenario,
                "condition": condition,
                "run_time": run_time,
                "observer_role": "ego",
                "observer_id": observer_id,
                "evaluation_window": window,
                "cutoff_rule": (
                    "pre_event excludes frames from event_frame onward; "
                    "event_response uses event_time - pre_seconds through "
                    "event_time + post_seconds"),
                "collision_distance_m": collision_distance_m,
                "event_response_pre_s": event_pre_s,
                "event_response_post_s": event_post_s,
                "total_frames": len(full_series),
                "frames_used": len(used_series),
                "frames_excluded_from_total": len(full_series) - len(used_series),
                "total_duration_s": _duration(full_series),
                "duration_used_s": _duration(used_series),
                "window_start_s": window_start_s,
                "window_end_s": window_end_s,
                "event_frame": cutoff["event_frame"],
                "event_time_s": cutoff["event_time_s"],
                "event_basis": cutoff["event_basis"],
                "min_distance_2d_m": cutoff["min_distance_2d_m"],
                "steering_rate_rms_rad_s": steering_rms,
                "steering_rate_rms_class": _class_steering_rms(steering_rms),
                "steering_rate_abs_p95_rad_s": revised._metric_percentile(
                    values["abs_steering_rate"], 95),
                "steering_rate_abs_max_rad_s": max(
                    values["abs_steering_rate"], default=0.0),
                "acceleration_variance_mps4": accel_variance,
                "acceleration_variance_class":
                    _class_accel_variance(accel_variance),
                "acceleration_abs_p95_mps2": revised._metric_percentile(
                    values["abs_accel"], 95),
                "jerk_abs_p95_mps3": revised._metric_percentile(
                    values["abs_jerk"], 95),
                "jerk_abs_max_mps3": max(values["abs_jerk"], default=0.0),
                "interpretation_note": _window_note(window),
            }
            rows.append(row)

            event_time = cutoff["event_time_s"]
            for item in used_series:
                event_relative_time_s = (
                    float(item["time_s"]) - float(event_time)
                    if event_time != "" else "")
                timeseries_rows.append({
                    "scenario": scenario,
                    "condition": condition,
                    "run_time": run_time,
                    "observer_role": "ego",
                    "observer_id": observer_id,
                    "window": window,
                    "frame": item["frame"],
                    "time_s": item["time_s"],
                    "event_relative_time_s": event_relative_time_s,
                    "x_m": item["x_m"],
                    "y_m": item["y_m"],
                    "speed_kmh": item["speed_kmh"],
                    "acceleration_mps2": item["acceleration_mps2"],
                    "jerk_mps3": item["jerk_mps3"],
                    "steering_angle_proxy_rad":
                        item["steering_angle_proxy_rad"],
                    "steering_rate_proxy_rad_s":
                        item["steering_rate_proxy_rad_s"],
                })

    rows.sort(key=_sort_key)
    timeseries_rows.sort(key=_sort_key)
    return rows, timeseries_rows


def _bar_label(ax, bars, fmt, dy):
    for bar in bars:
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            height + dy,
            fmt % height,
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )


def _style_axes(ax):
    ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _plot_steering(rows, output_dir):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None
    if not rows:
        return None

    labels = [
        "%s\n%s" % (row["condition"], row["evaluation_window"].replace("_", " "))
        for row in rows
    ]
    x = list(range(len(rows)))
    width = 0.26
    metrics = [
        ("steering_rate_rms_rad_s", "RMS", "#4C8FD3", "%.3f"),
        ("steering_rate_abs_p95_rad_s", "P95 abs", "#2A9D76", "%.3f"),
        ("steering_rate_abs_max_rad_s", "Max abs", "#D95F02", "%.3f"),
    ]
    fig, ax = plt.subplots(figsize=(10.8, 6.0))
    max_value = 0.0
    for index, (key, label, color, fmt) in enumerate(metrics):
        positions = [pos + (index - 1) * width for pos in x]
        values = [float(row[key]) for row in rows]
        max_value = max(max_value, max(values or [0.0]))
        bars = ax.bar(positions, values, width=width, label=label,
                      color=color)
        _bar_label(ax, bars, fmt, max(0.006, max_value * 0.035))
    ax.set_title("Control Performance: Windowed Steering Smoothness",
                 fontsize=17, fontweight="bold", pad=14)
    ax.set_ylabel("Steering-rate proxy (rad/s)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, max(0.08, max_value * 1.35))
    ax.legend(frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.12), ncol=3)
    _style_axes(ax)
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    path = os.path.join(output_dir, "control_steering_windowed.png")
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _plot_acceleration_variance(rows, output_dir):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None
    if not rows:
        return None

    labels = [
        "%s\n%s" % (row["condition"], row["evaluation_window"].replace("_", " "))
        for row in rows
    ]
    values = [float(row["acceleration_variance_mps4"]) for row in rows]
    colors = ["#D45A5A" if row["condition"] == "No V2X" else "#4C8FD3"
              for row in rows]
    fig, ax = plt.subplots(figsize=(9.6, 5.8))
    bars = ax.bar(labels, values, color=colors, width=0.54)
    dy = max(0.08, max(values or [0.0]) * 0.05)
    _bar_label(ax, bars, "%.2f", dy)
    ax.set_title("Control Performance: Windowed Acceleration Variance",
                 fontsize=17, fontweight="bold", pad=14)
    ax.set_ylabel("Acceleration variance (m^2/s^4)")
    ax.set_ylim(0, max(1.0, max(values or [0.0]) * 1.25))
    _style_axes(ax)
    fig.tight_layout()
    path = os.path.join(output_dir, "control_acceleration_variance_windowed.png")
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _plot_timeseries(timeseries_rows, output_dir):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None
    timeseries_rows = [
        row for row in timeseries_rows if row["window"] == "event_response"
    ]
    if not timeseries_rows:
        return None

    fig, axes = plt.subplots(2, 1, figsize=(12.2, 7.4), sharex=False)
    colors = {"No V2X": "#D45A5A", "V2X": "#4C8FD3"}
    for condition in ["No V2X", "V2X"]:
        rows = [row for row in timeseries_rows if row["condition"] == condition]
        if not rows:
            continue
        times = [float(row["event_relative_time_s"]) for row in rows]
        steering = [float(row["steering_rate_proxy_rad_s"]) for row in rows]
        accel = [float(row["acceleration_mps2"]) for row in rows]
        axes[0].plot(times, steering, label=condition,
                     color=colors.get(condition), linewidth=1.9)
        axes[1].plot(times, accel, label=condition,
                     color=colors.get(condition), linewidth=1.9)

    axes[0].set_title("Event-Response Control Time Series",
                      fontsize=17, fontweight="bold", pad=12)
    axes[0].set_ylabel("Steering-rate proxy\n(rad/s)")
    axes[1].set_ylabel("Acceleration\n(m/s^2)")
    axes[1].set_xlabel("Time relative to event (s)")
    for ax in axes:
        ax.axhline(0.0, color="#333333", linewidth=0.9, alpha=0.55)
        ax.axvline(0.0, color="#D45A5A", linestyle="--", linewidth=1.1,
                   alpha=0.75)
        ax.legend(frameon=False, loc="upper right")
        _style_axes(ax)
    fig.tight_layout()
    path = os.path.join(output_dir, "control_event_response_timeseries.png")
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _write_report(path, rows, figures, args):
    lines = [
        "# Scenario 1 Control Performance KPIs",
        "",
        "## Scope",
        "",
        "This file calculates ego control-performance KPIs only. Two event-aware windows are reported.",
        "",
        "- `pre_event`: normal control stability before collision/closest approach.",
        "- `event_response`: emergency response severity from shortly before the event to immediately after it.",
        "",
        "The purpose is to avoid a known bias: long post-collision stationary frames can reduce RMS values and make No V2X look smoother than it actually was. The event-response window includes only a short immediate post-event segment.",
        "",
        "## Window Rule",
        "",
        "```text",
        "event = first frame where ego-subject 2D distance <= collision_distance_m",
        "if no collision threshold is reached:",
        "    event = closest-approach frame",
        "pre_event window = frames before event",
        "event_response window = [event_time - pre_seconds, event_time + post_seconds]",
        "```",
        "",
        "## Formulas",
        "",
        "```text",
        "steering_rate_RMS = sqrt(mean(steering_rate_proxy^2))",
        "steering_rate_abs_P95 = percentile(abs(steering_rate_proxy), 95)",
        "acceleration_variance = mean((a_i - mean(a))^2)",
        "jerk_abs_P95 = percentile(abs(jerk), 95)",
        "```",
        "",
        "Lower values indicate smoother control. RMS captures average control activity, while P95 abs captures severe but not single-frame-extreme control demand.",
        "",
        "## Parameters",
        "",
        "- collision_distance_m: `%s`" % args.collision_distance_m,
        "- event_response_pre_s: `%s`" % args.event_response_pre_s,
        "- event_response_post_s: `%s`" % args.event_response_post_s,
        "",
        "## Results",
        "",
        "| Condition | Window | Frames used / total | Event basis | Steering RMS | Steering P95 | Accel variance | Jerk P95 |",
        "|---|---|---:|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {condition} | {window} | {used}/{total} | {basis} | {srms:.4f} | {sp95:.4f} | {avar:.4f} | {jp95:.2f} |".format(
                condition=row["condition"],
                window=row["evaluation_window"],
                used=row["frames_used"],
                total=row["total_frames"],
                basis=row["event_basis"],
                srms=float(row["steering_rate_rms_rad_s"]),
                sp95=float(row["steering_rate_abs_p95_rad_s"]),
                avar=float(row["acceleration_variance_mps4"]),
                jp95=float(row["jerk_abs_p95_mps3"]),
            ))
    lines.extend(["", "## Output Figures", ""])
    for title, file_path in figures:
        if file_path:
            lines.append("- %s: `%s`" % (title, os.path.basename(file_path)))
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Calculate Scenario 1 ego control-performance KPIs with "
            "pre-event cutoff."))
    parser.add_argument("--run-dir", action="append", required=True,
                        help="Scenario 1 datadump run directory. Repeatable.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    parser.add_argument("--collision-distance-m", type=float,
                        default=DEFAULT_COLLISION_DISTANCE_M)
    parser.add_argument("--event-response-pre-s", type=float,
                        default=DEFAULT_EVENT_PRE_SECONDS,
                        help="Seconds before event for event-response window.")
    parser.add_argument("--event-response-post-s", type=float,
                        default=DEFAULT_EVENT_POST_SECONDS,
                        help="Seconds after event for event-response window.")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    rows, timeseries_rows = _control_rows(
        args.run_dir,
        args.collision_distance_m,
        args.event_response_pre_s,
        args.event_response_post_s,
    )
    if not rows:
        raise SystemExit("No control-performance rows were generated.")

    _write_csv(os.path.join(args.output_dir, "control_windowed_kpi.csv"), rows)
    _write_csv(os.path.join(args.output_dir, "control_windowed_timeseries.csv"),
               timeseries_rows)
    _write_csv(
        os.path.join(args.output_dir, "control_pre_event_kpi.csv"),
        [row for row in rows if row["evaluation_window"] == "pre_event"])
    _write_csv(
        os.path.join(args.output_dir, "control_event_response_kpi.csv"),
        [row for row in rows if row["evaluation_window"] == "event_response"])
    figures = [
        ("Windowed steering smoothness", _plot_steering(rows, args.output_dir)),
        ("Acceleration variance",
         _plot_acceleration_variance(rows, args.output_dir)),
        ("Event-response time series",
         _plot_timeseries(timeseries_rows, args.output_dir)),
    ]
    _write_report(
        os.path.join(args.output_dir, "control_windowed_report.md"),
        rows,
        figures,
        args,
    )
    print("Wrote control-performance KPIs to", args.output_dir)


if __name__ == "__main__":
    main()
