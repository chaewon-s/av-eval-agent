#!/usr/bin/env python
"""Calculate Scenario 1 path-normalized steering smoothness.

Metric:
    Yaw-rate residual = actual ego yaw-rate - planned-trajectory yaw-rate
    Yaw-rate residual RMS = sqrt(mean(residual^2))

The planned trajectory is read from each ego observer YAML frame. Its first two
future points define the local planned heading. The derivative of that planned
heading across frames is used as the reference yaw-rate.
"""

import csv
import math
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import calculate_scenario1_revised_kpis as revised  # noqa: E402
import calculate_tracking_hota as hota  # noqa: E402


RUNS = [
    (
        "No V2X",
        REPO_ROOT / "data_dumping" / "scenario1" / "2026_05_28_13_45_42",
    ),
    (
        "V2X",
        REPO_ROOT / "data_dumping" / "scenario1_v2x" / "2026_05_10_22_36_44",
    ),
]
OUT_DIR = (
    REPO_ROOT
    / "evaluation_outputs"
    / "scenario1_yaw_rate_residual_smoothness_common_pre_event_2026_06_11"
)
EVENT_WINDOW_SECONDS = 1.0
PLAN_HEADING_LOOKAHEAD_POINTS = 12
REFERENCE_HEADING_SMOOTH_WINDOW = 5

COLORS = {
    "No V2X": "#d45a5a",
    "V2X": "#4c93d2",
    "actual": "#5f6b7a",
    "ref": "#8aa05f",
    "residual": "#cc4b4b",
}


def unwrap(values):
    if not values:
        return []
    out = [values[0]]
    for value in values[1:]:
        prev = out[-1]
        delta = value - prev
        while delta > math.pi:
            value -= 2.0 * math.pi
            delta = value - prev
        while delta < -math.pi:
            value += 2.0 * math.pi
            delta = value - prev
        out.append(value)
    return out


def diff(values, dt):
    if len(values) < 2:
        return []
    return [(values[i] - values[i - 1]) / dt for i in range(1, len(values))]


def rms(values):
    values = [v for v in values if math.isfinite(v)]
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


def percentile(values, pct):
    values = sorted(abs(v) for v in values if math.isfinite(v))
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * pct / 100.0
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return values[lo]
    ratio = pos - lo
    return values[lo] * (1.0 - ratio) + values[hi] * ratio


def planned_heading(plan_trajectory):
    if not isinstance(plan_trajectory, list) or len(plan_trajectory) < 2:
        return None
    points = [
        p for p in plan_trajectory[:PLAN_HEADING_LOOKAHEAD_POINTS]
        if isinstance(p, list) and len(p) >= 2
    ]
    if len(points) < 2:
        return None
    # Use a longer look-ahead segment instead of the first two waypoints.
    # Consecutive planner waypoints can jitter by millimeters between frames;
    # differentiating that tiny heading noise creates a fake zig-zag reference
    # yaw-rate in straight-road scenarios.
    p0 = points[0]
    p1 = points[-1]
    dx = float(p1[0]) - float(p0[0])
    dy = float(p1[1]) - float(p0[1])
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return None
    return math.atan2(dy, dx)


def moving_average(values, window):
    if window <= 1 or len(values) <= 2:
        return values
    radius = window // 2
    smoothed = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        subset = values[start:end]
        smoothed.append(sum(subset) / len(subset))
    return smoothed


def read_planned_headings(run_dir):
    observer_id, observer_dir = revised._role_observer(str(run_dir), "ego")
    if observer_dir is None:
        return observer_id, []
    dt = revised._fixed_delta_seconds(str(run_dir))
    rows = []
    yaml_files = sorted(
        f for f in os.listdir(observer_dir)
        if f.lower().endswith(".yaml") and f[:6].isdigit()
    )
    for file_name in yaml_files:
        frame = int(file_name[:6])
        data = hota._load_yaml(os.path.join(observer_dir, file_name))
        heading = planned_heading(data.get("plan_trajectory"))
        rows.append({
            "frame": frame,
            "time_s": (frame - 1) * dt,
            "planned_heading_rad": heading,
            "plan_points": len(data.get("plan_trajectory") or []),
        })
    return observer_id, rows


def condition_series(condition, run_dir):
    scenario, run_time = revised._scenario_and_time(str(run_dir))
    observer_id, actual_rows = revised._role_timeseries(str(run_dir), "ego")
    _, plan_rows = read_planned_headings(run_dir)
    cutoff = revised._event_cutoff(str(run_dir), 4.5)
    event_time = cutoff.get("event_time_s")
    try:
        event_time = float(event_time)
    except (TypeError, ValueError):
        event_time = None

    by_frame = {row["frame"]: row for row in actual_rows}
    frames = [row["frame"] for row in plan_rows if row["frame"] in by_frame]

    actual_yaw = []
    planned_heading_values = []
    valid_frames = []
    for row in plan_rows:
        frame = row["frame"]
        actual = by_frame.get(frame)
        if actual is None or row["planned_heading_rad"] is None:
            continue
        valid_frames.append(frame)
        actual_yaw.append(actual["yaw_unwrapped_rad"])
        planned_heading_values.append(row["planned_heading_rad"])

    actual_yaw = unwrap(actual_yaw)
    planned_heading_values = moving_average(
        unwrap(planned_heading_values),
        REFERENCE_HEADING_SMOOTH_WINDOW,
    )
    dt = revised._fixed_delta_seconds(str(run_dir))
    actual_yaw_rate = diff(actual_yaw, dt)
    ref_yaw_rate = diff(planned_heading_values, dt)

    output = []
    for index, frame in enumerate(valid_frames):
        actual = by_frame[frame]
        if index == 0:
            ay = 0.0
            ry = 0.0
        else:
            ay = actual_yaw_rate[index - 1]
            ry = ref_yaw_rate[index - 1]
        residual = ay - ry
        output.append({
            "scenario": scenario,
            "condition": condition,
            "run_time": run_time,
            "run_dir": str(run_dir),
            "observer_id": observer_id,
            "frame": frame,
            "time_s": actual["time_s"],
            "speed_kmh": actual["speed_kmh"],
            "yaw_rate_actual_rad_s": ay,
            "yaw_rate_ref_from_plan_rad_s": ry,
            "yaw_rate_residual_rad_s": residual,
            "event_time_s": "" if event_time is None else event_time,
            "event_basis": cutoff.get("event_basis", ""),
            "plan_trajectory_available": True,
        })
    return output, cutoff


def write_csv(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summary_rows(series_by_condition):
    rows = []
    for condition, rows_series in series_by_condition.items():
        residual = [r["yaw_rate_residual_rad_s"] for r in rows_series[1:]]
        actual = [r["yaw_rate_actual_rad_s"] for r in rows_series[1:]]
        ref = [r["yaw_rate_ref_from_plan_rad_s"] for r in rows_series[1:]]
        rows.append({
            "condition": condition,
            "window": "common_pre_event_%.1fs" % EVENT_WINDOW_SECONDS,
            "frames_used": len(rows_series),
            "duration_s": (
                rows_series[-1]["time_s"] - rows_series[0]["time_s"]
                if len(rows_series) >= 2 else 0.0
            ),
            "actual_yaw_rate_rms_rad_s": rms(actual),
            "planned_ref_yaw_rate_rms_rad_s": rms(ref),
            "yaw_rate_residual_rms_rad_s": rms(residual),
            "yaw_rate_residual_abs_p95_rad_s": percentile(residual, 95),
            "yaw_rate_residual_abs_max_rad_s": max(
                [abs(v) for v in residual], default=0.0
            ),
        })
    return rows


def event_window_rows(rows, window_seconds):
    event_time = next((r["event_time_s"] for r in rows if r["event_time_s"] != ""), "")
    try:
        event_time = float(event_time)
    except (TypeError, ValueError):
        return rows
    filtered = []
    for row in rows:
        relative_time = float(row["time_s"]) - event_time
        if -window_seconds <= relative_time <= window_seconds:
            copied = dict(row)
            copied["relative_time_s"] = relative_time
            copied["event_window_s"] = window_seconds
            filtered.append(copied)
    return filtered


def comparable_pre_event_rows(rows, window_seconds):
    if not rows:
        return []
    event_time = next((r["event_time_s"] for r in rows if r["event_time_s"] != ""), "")
    try:
        event_time = float(event_time)
    except (TypeError, ValueError):
        event_time = None
    last_time = float(rows[-1]["time_s"])
    if event_time is None:
        reference_time = last_time
        reference_basis = "last_valid_frame_no_event"
    else:
        reference_time = min(event_time, last_time)
        reference_basis = (
            "event_time" if event_time <= last_time else
            "last_valid_frame_before_event"
        )

    start_time = reference_time - window_seconds
    filtered = []
    for row in rows:
        time_s = float(row["time_s"])
        if start_time <= time_s <= reference_time:
            copied = dict(row)
            copied["relative_time_s"] = time_s - reference_time
            copied["window_reference_time_s"] = reference_time
            copied["window_reference_basis"] = reference_basis
            copied["event_window_s"] = window_seconds
            filtered.append(copied)
    return filtered


def plot_timeseries(series_by_condition, out_path):
    fig, axes = plt.subplots(2, 1, figsize=(12.8, 8.0), dpi=170, sharex=True)

    for condition, rows in series_by_condition.items():
        x = [r.get("relative_time_s", r["time_s"]) for r in rows]
        actual = [r["yaw_rate_actual_rad_s"] for r in rows]
        ref = [r["yaw_rate_ref_from_plan_rad_s"] for r in rows]
        residual = [r["yaw_rate_residual_rad_s"] for r in rows]
        event_time = next((r["event_time_s"] for r in rows if r["event_time_s"] != ""), "")
        try:
            event_time = float(event_time)
        except (TypeError, ValueError):
            event_time = None

        ax = axes[0]
        if condition == "V2X":
            ax.plot(x, actual, color=COLORS["actual"], linewidth=1.6, alpha=0.75,
                    label="actual yaw-rate")
            ax.plot(x, ref, color=COLORS["ref"], linewidth=1.6, alpha=0.75,
                    label="planned ref yaw-rate")
        axes[1].plot(
            x,
            residual,
            color=COLORS[condition],
            linewidth=2.2,
            label=f"{condition} residual",
        )
        if event_time is not None:
            for ax in axes:
                if rows and "relative_time_s" in rows[0]:
                    ax.axvspan(-EVENT_WINDOW_SECONDS, 0.0,
                               color=COLORS[condition], alpha=0.05)
                    ax.axvline(0.0, color=COLORS[condition],
                               linestyle="--", linewidth=1.4, alpha=0.75)
                else:
                    ax.axvspan(event_time - 1.0, event_time + 1.0,
                               color=COLORS[condition], alpha=0.06)
                    ax.axvline(event_time, color=COLORS[condition],
                               linestyle="--", linewidth=1.4, alpha=0.75)

    axes[0].set_title("Actual vs Planned Reference Yaw-rate (V2X shown)", fontsize=15, fontweight="bold")
    axes[0].set_ylabel("Yaw-rate (rad/s)")
    axes[0].legend(loc="upper right")
    axes[1].set_title("Path-normalized Steering Smoothness: Yaw-rate Residual", fontsize=15, fontweight="bold")
    axes[1].set_ylabel("Residual yaw-rate (rad/s)")
    axes[1].set_xlabel("Time relative to matched reference point (s)")
    axes[1].legend(loc="upper right")

    for ax in axes:
        ax.axhline(0, color="#5d6670", linewidth=1.0, alpha=0.7)
        ax.grid(axis="both", linestyle="--", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.suptitle("Scenario 1 Comparable Pre-event Yaw-rate Residual Smoothness", fontsize=22, fontweight="bold", y=1.01)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def plot_bar(summary, out_path):
    labels = [row["condition"] for row in summary]
    residual = [row["yaw_rate_residual_rms_rad_s"] for row in summary]
    actual = [row["actual_yaw_rate_rms_rad_s"] for row in summary]
    ref = [row["planned_ref_yaw_rate_rms_rad_s"] for row in summary]

    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(9.8, 5.8), dpi=170)
    width = 0.24
    bars1 = ax.bar([i - width for i in x], actual, width=width, color="#9aa3ad", label="Actual yaw-rate RMS")
    bars2 = ax.bar(list(x), ref, width=width, color="#8aa05f", label="Planned ref yaw-rate RMS")
    bars3 = ax.bar([i + width for i in x], residual, width=width, color="#4c93d2", label="Residual RMS")
    ax.set_xticks(list(x), labels)
    ax.set_ylabel("RMS (rad/s)")
    ax.set_title("Scenario 1 Comparable Pre-event Path-normalized Steering Smoothness", fontsize=18, fontweight="bold")
    ax.grid(axis="y", linestyle="--", alpha=0.32)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for bars in (bars1, bars2, bars3):
        for bar in bars:
            h = bar.get_height()
            ax.annotate(f"{h:.4f}", (bar.get_x() + bar.get_width() / 2, h),
                        xytext=(0, 4), textcoords="offset points",
                        ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    series_by_condition = {}
    full_rows = []
    all_rows = []
    for condition, run_dir in RUNS:
        rows, _ = condition_series(condition, run_dir)
        full_rows.extend(rows)
        windowed_rows = comparable_pre_event_rows(rows, EVENT_WINDOW_SECONDS)
        series_by_condition[condition] = windowed_rows
        all_rows.extend(windowed_rows)

    summary = summary_rows(series_by_condition)
    write_csv(OUT_DIR / "scenario1_yaw_rate_residual_full_timeseries.csv", full_rows)
    write_csv(OUT_DIR / "scenario1_yaw_rate_residual_common_pre_event_timeseries.csv", all_rows)
    write_csv(OUT_DIR / "scenario1_yaw_rate_residual_common_pre_event_summary.csv", summary)
    plot_timeseries(series_by_condition, OUT_DIR / "scenario1_yaw_rate_residual_common_pre_event_timeseries.png")
    plot_bar(summary, OUT_DIR / "scenario1_yaw_rate_residual_common_pre_event_rms_comparison.png")
    print(OUT_DIR)


if __name__ == "__main__":
    main()
