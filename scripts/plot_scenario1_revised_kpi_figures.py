#!/usr/bin/env python
"""Plot report-ready figures for revised Scenario 1 KPIs."""

import argparse
import csv
import os


LABEL_BBOX = {
    "boxstyle": "round,pad=0.22",
    "facecolor": "white",
    "edgecolor": "none",
    "alpha": 0.86,
}


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _float(row, key, default=0.0):
    try:
        value = row.get(key, "")
        return float(value) if value != "" else default
    except (TypeError, ValueError):
        return default


def _label_scenario(value):
    if "no_v2x" in value:
        return "No V2X"
    if "v2x" in value:
        return "V2X"
    return value


def _label_mode(value):
    return {
        "sensor_only": "Sensor-only",
        "v2x_fused": "V2X fused",
    }.get(value, value)


def _style_axes(ax):
    ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _label_bars(ax, bars, fmt="%.1f", padding=6, fontsize=10):
    ax.bar_label(
        bars,
        fmt=fmt,
        padding=padding,
        fontsize=fontsize,
        fontweight="bold",
        bbox=LABEL_BBOX,
    )


def _pad_y_axis(ax, values, upper_ratio=1.24, minimum_top=None):
    values = [value for value in values if value is not None]
    if not values:
        return
    ymax = max(values)
    top = ymax * upper_ratio if ymax > 0 else 1.0
    if minimum_top is not None:
        top = max(top, minimum_top)
    ax.set_ylim(0, top)


def _annotate_line_points(ax, xs, ys, offset_points, suffix="%",
                          color="#111827"):
    vertical_alignment = "bottom" if offset_points >= 0 else "top"
    for x_value, y_value in zip(xs, ys):
        ax.annotate(
            ("%.1f%s" % (y_value, suffix)),
            xy=(x_value, y_value),
            xytext=(0, offset_points),
            textcoords="offset points",
            ha="center",
            va=vertical_alignment,
            fontsize=9.5,
            fontweight="bold",
            color=color,
            bbox=LABEL_BBOX,
        )


def _save(fig, output_dir, name, manifest, title):
    path = os.path.join(output_dir, name)
    fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")
    manifest.append({
        "file": name,
        "title": title,
        "path": path,
    })


def _plot_perception_by_observer(rows, output_dir, manifest, observer_role):
    import matplotlib.pyplot as plt

    primary = [
        row for row in rows
        if row.get("observer_role") == observer_role and
        row.get("comparison_scope") == "primary_same_run_sensor_vs_fusion"
    ]
    if not primary:
        return
    grouped = {}
    for row in primary:
        grouped.setdefault(row["perception_mode"], []).append(row)

    fig, ax = plt.subplots(figsize=(12.0, 6.6))
    colors = {
        "sensor_only": "#D45A5A",
        "v2x_fused": "#4C8FD3",
    }
    for mode, mode_rows in sorted(grouped.items()):
        mode_rows = sorted(mode_rows, key=lambda r: _float(r, "horizon_s"))
        xs = [_float(r, "horizon_s") for r in mode_rows]
        ys = [100.0 * _float(r, "avg_availability") for r in mode_rows]
        ax.plot(
            xs,
            ys,
            marker="o",
            linewidth=2.4,
            markersize=7,
            color=colors.get(mode),
            label=_label_mode(mode),
        )
        offset = -20 if mode == "sensor_only" else 12
        _annotate_line_points(ax, xs, ys, offset, color=colors.get(mode))
    ax.set_title(
        "Critical Actor Awareness by Observation Horizon (%s)" %
        observer_role.upper(),
        fontsize=17,
        fontweight="bold",
    )
    ax.set_xlabel("Observation horizon (s)")
    ax.set_ylabel("Average availability (%)")
    ax.set_ylim(0, 112)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.14),
              ncol=2)
    _style_axes(ax)
    _save(
        fig,
        output_dir,
        "fig1_perception_%s_horizon_availability.png" % observer_role,
        manifest,
        "Perception horizon availability (%s)" % observer_role,
    )
    plt.close(fig)


def _plot_perception_breakdown(rows, output_dir, manifest):
    import matplotlib.pyplot as plt

    selected = [
        row for row in rows
        if row.get("observer_role") == "ego" and
        row.get("comparison_scope") == "primary_same_run_sensor_vs_fusion" and
        abs(_float(row, "horizon_s") - 2.0) < 1e-6
    ]
    if not selected:
        return
    selected = sorted(selected, key=lambda row: row["perception_mode"])
    labels = [_label_mode(row["perception_mode"]) for row in selected]
    metrics = [
        ("avg_HOTA", "HOTA", "#1F77B4"),
        ("avg_DetA", "DetA", "#2A9D76"),
        ("avg_AssA", "AssA", "#E36C0A"),
    ]
    x = list(range(len(selected)))
    width = 0.22

    fig, ax = plt.subplots(figsize=(11.2, 6.4))
    all_values = []
    for idx, (key, label, color) in enumerate(metrics):
        positions = [v + (idx - 1) * width for v in x]
        values = [100.0 * _float(row, key) for row in selected]
        all_values.extend(values)
        bars = ax.bar(
            positions,
            values,
            width,
            label=label,
            color=color,
        )
        _label_bars(ax, bars, fmt="%.1f")
    ax.set_title("Perception KPI Breakdown at 2s Horizon (EGO)",
                 fontsize=17, fontweight="bold")
    ax.set_ylabel("Score (%)")
    _pad_y_axis(ax, all_values, upper_ratio=1.28, minimum_top=70)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.13),
              ncol=3)
    _style_axes(ax)
    _save(fig, output_dir, "fig2_perception_ego_2s_breakdown.png",
          manifest, "Perception KPI breakdown at 2s horizon")
    plt.close(fig)


def _plot_control_steering(rows, output_dir, manifest):
    import matplotlib.pyplot as plt

    if not rows:
        return
    rows = sorted(rows, key=lambda row: row["scenario"])
    labels = [_label_scenario(row["scenario"]) for row in rows]
    x = list(range(len(rows)))
    width = 0.28
    metrics = [
        ("steering_rate_rms_rad_s", "RMS", "#4C8FD3"),
        ("steering_rate_abs_p95_rad_s", "P95 abs", "#2A9D76"),
        ("steering_rate_abs_max_rad_s", "Max abs", "#D95F02"),
    ]

    fig, ax = plt.subplots(figsize=(11.2, 6.4))
    all_values = []
    for idx, (key, label, color) in enumerate(metrics):
        positions = [v + (idx - 1) * width for v in x]
        values = [_float(row, key) for row in rows]
        all_values.extend(values)
        bars = ax.bar(
            positions,
            values,
            width,
            label=label,
            color=color,
        )
        _label_bars(ax, bars, fmt="%.3f")
    ax.set_title("Pre-Event Steering Smoothness", fontsize=17,
                 fontweight="bold")
    ax.set_ylabel("Steering-rate proxy (rad/s)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    _pad_y_axis(ax, all_values, upper_ratio=1.32)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.13),
              ncol=3)
    _style_axes(ax)
    _save(fig, output_dir, "fig3_control_steering_pre_event.png",
          manifest, "Pre-event steering smoothness")
    plt.close(fig)


def _plot_control_longitudinal(rows, output_dir, manifest):
    import matplotlib.pyplot as plt

    if not rows:
        return
    rows = sorted(rows, key=lambda row: row["scenario"])
    labels = [_label_scenario(row["scenario"]) for row in rows]
    x = list(range(len(rows)))
    width = 0.28
    metrics = [
        ("acceleration_variance_mps4", "Accel variance", "#4C8FD3"),
        ("acceleration_abs_p95_mps2", "Accel |P95|", "#2A9D76"),
        ("jerk_abs_p95_mps3", "Jerk |P95|", "#D95F02"),
    ]

    fig, ax = plt.subplots(figsize=(11.2, 6.4))
    all_values = []
    for idx, (key, label, color) in enumerate(metrics):
        positions = [v + (idx - 1) * width for v in x]
        values = [_float(row, key) for row in rows]
        all_values.extend(values)
        bars = ax.bar(
            positions,
            values,
            width,
            label=label,
            color=color,
        )
        _label_bars(ax, bars, fmt="%.2f")
    ax.set_title("Pre-Event Longitudinal Control", fontsize=17,
                 fontweight="bold")
    ax.set_ylabel("Metric value")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    _pad_y_axis(ax, all_values, upper_ratio=1.28)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.13),
              ncol=3)
    _style_axes(ax)
    _save(fig, output_dir, "fig4_control_longitudinal_pre_event.png",
          manifest, "Pre-event longitudinal control")
    plt.close(fig)


def _plot_traffic_completion(rows, output_dir, manifest):
    import matplotlib.pyplot as plt

    if not rows:
        return
    roles = ["ego", "subject"]
    scenarios = []
    for row in rows:
        label = _label_scenario(row["scenario"])
        if label not in scenarios:
            scenarios.append(label)
    scenarios = sorted(scenarios, reverse=True)

    x = list(range(len(roles)))
    width = 0.34
    colors = {"V2X": "#4C8FD3", "No V2X": "#D45A5A"}
    fig, ax = plt.subplots(figsize=(11.0, 6.3))
    all_values = []
    for idx, scenario in enumerate(scenarios):
        values = []
        for role in roles:
            match = next(
                (row for row in rows
                 if _label_scenario(row["scenario"]) == scenario and
                 row["role"] == role),
                None,
            )
            values.append(100.0 * _float(match or {}, "recommended_flow_efficiency"))
        all_values.extend(values)
        positions = [v + (idx - 0.5) * width for v in x]
        bars = ax.bar(positions, values, width, color=colors.get(scenario),
                      label=scenario)
        _label_bars(ax, bars, fmt="%.1f%%")
    ax.set_title("Trip Completion Flow Efficiency", fontsize=17,
                 fontweight="bold")
    ax.set_ylabel("Trip completion/progress (%)")
    _pad_y_axis(ax, all_values, upper_ratio=1.18, minimum_top=108)
    ax.set_xticks(x)
    ax.set_xticklabels(["Ego", "Subject"])
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.13),
              ncol=2)
    _style_axes(ax)
    _save(fig, output_dir, "fig5_traffic_trip_completion.png",
          manifest, "Trip completion flow efficiency")
    plt.close(fig)


def _plot_safety_ttc(rows, output_dir, manifest):
    import matplotlib.pyplot as plt

    if not rows:
        return
    rows = sorted(rows, key=lambda row: row["scenario"])
    labels = [_label_scenario(row["scenario"]) for row in rows]
    x = list(range(len(rows)))
    width = 0.34

    fig, ax1 = plt.subplots(figsize=(11.2, 6.4))
    ttc_values = [_float(row, "min_ttc_2d_s") for row in rows]
    distance_values = [_float(row, "min_distance_2d_m") for row in rows]
    bars1 = ax1.bar(
        [v - width / 2 for v in x],
        ttc_values,
        width,
        color="#4C8FD3",
        label="Min 2D TTC",
    )
    ax1.axhline(3.0, color="#2A9D76", linestyle="--", linewidth=1.5,
                label="TTC 3s safe reference")
    ax1.axhline(1.5, color="#D95F02", linestyle="--", linewidth=1.5,
                label="TTC 1.5s risk reference")
    ax1.set_ylabel("TTC (s)")
    ax1.set_ylim(0, max(4.8, max(ttc_values) * 1.50))
    ax2 = ax1.twinx()
    bars2 = ax2.bar(
        [v + width / 2 for v in x],
        distance_values,
        width,
        color="#D45A5A",
        label="Min 2D distance",
    )
    ax2.set_ylabel("Distance (m)")
    ax2.set_ylim(0, max(16.0, max(distance_values) * 1.38))
    _label_bars(ax1, bars1, fmt="%.2f")
    _label_bars(ax2, bars2, fmt="%.2f")
    ax1.set_title("Safety Margin: 2D TTC and Closest Distance", fontsize=17,
                  fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    _style_axes(ax1)
    ax2.spines["top"].set_visible(False)
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, frameon=False,
               loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2)
    _save(fig, output_dir, "fig6_safety_margin_ttc_distance.png",
          manifest, "Safety margin: 2D TTC and closest distance")
    plt.close(fig)


def _plot_safety_prs(rows, output_dir, manifest):
    import matplotlib.pyplot as plt

    if not rows:
        return
    rows = sorted(rows, key=lambda row: row["scenario"])
    labels = [_label_scenario(row["scenario"]) for row in rows]
    x = list(range(len(rows)))
    width = 0.34

    fig, ax1 = plt.subplots(figsize=(11.2, 6.4))
    tick_labels = [
        "%s\n%s" % (_label_scenario(row["scenario"]),
                   row.get("prs_proxy", "").replace("_proxy", "")
                   .replace("_", " "))
        for row in rows
    ]
    awareness_values = [_float(row, "awareness_time_s") for row in rows]
    required_decel_values = [
        _float(row, "required_decel_at_awareness_mps2") for row in rows
    ]
    bars1 = ax1.bar(
        [v - width / 2 for v in x],
        awareness_values,
        width,
        color="#4C8FD3",
        label="Awareness time",
    )
    ax1.set_ylabel("Awareness time (s)")
    ax1.set_ylim(0, max(13.0, max(awareness_values) * 1.26))
    ax2 = ax1.twinx()
    bars2 = ax2.bar(
        [v + width / 2 for v in x],
        required_decel_values,
        width,
        color="#D95F02",
        label="Required decel at awareness",
    )
    ax2.axhline(8.0, color="#D45A5A", linestyle="--", linewidth=1.5,
                label="Emergency decel proxy")
    ax2.set_ylabel("Required decel (m/s^2)")
    ax2.set_ylim(0, max(14.5, max(required_decel_values + [8.0]) * 1.22))
    _label_bars(ax1, bars1, fmt="%.1f")
    _label_bars(ax2, bars2, fmt="%.2f")
    ax1.set_title("Safety Margin: Awareness Timing and Required Deceleration",
                  fontsize=17,
                  fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(tick_labels)
    _style_axes(ax1)
    ax2.spines["top"].set_visible(False)
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, frameon=False,
               loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2)
    _save(fig, output_dir, "fig7_safety_margin_awareness_required_decel.png",
          manifest, "Safety margin: awareness timing and required deceleration")
    plt.close(fig)


def _plot_pet_timeline(rows, output_dir, manifest):
    import matplotlib.pyplot as plt

    if not rows:
        return
    rows = sorted(rows, key=lambda row: row["scenario"], reverse=True)
    fig, ax = plt.subplots(figsize=(12.0, 6.4))
    y_ticks = []
    y_labels = []
    colors = {"Ego": "#4C8FD3", "Subject": "#D95F02"}
    max_time = 0.0

    for scenario_index, row in enumerate(rows):
        base_y = scenario_index * 3.0
        scenario_label = _label_scenario(row["scenario"])
        intervals = [
            ("Subject", _float(row, "subject_conflict_entry_s", None),
             _float(row, "subject_conflict_exit_s", None), base_y + 1.4),
            ("Ego", _float(row, "ego_conflict_entry_s", None),
             _float(row, "ego_conflict_exit_s", None), base_y + 0.4),
        ]
        for actor, entry, exit_time, y_value in intervals:
            y_ticks.append(y_value + 0.18)
            y_labels.append("%s %s" % (scenario_label, actor))
            if entry is None:
                continue
            if exit_time is None or exit_time == 0.0:
                fallback_end = max(_float(row, "event_time_s"), entry + 0.6)
                duration = max(fallback_end - entry, 0.6)
                hatch = "///"
                label_text = "no clean exit"
            else:
                duration = max(exit_time - entry, 0.1)
                hatch = None
                label_text = "%.1f-%.1fs" % (entry, exit_time)
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
            ax.text(
                entry + duration / 2.0,
                y_value + 0.18,
                label_text,
                ha="center",
                va="center",
                fontsize=9,
                fontweight="bold",
                bbox=LABEL_BBOX,
            )

        pet = row.get("pet_s", "")
        if pet != "":
            pet_value = _float(row, "pet_s")
            subject_exit = _float(row, "subject_conflict_exit_s", None)
            ego_entry = _float(row, "ego_conflict_entry_s", None)
            if subject_exit is not None and ego_entry is not None:
                y_arrow = base_y + 2.05
                ax.annotate(
                    "",
                    xy=(ego_entry, y_arrow),
                    xytext=(subject_exit, y_arrow),
                    arrowprops=dict(arrowstyle="<->", color="#111827",
                                    linewidth=1.5),
                )
                ax.text(
                    (subject_exit + ego_entry) / 2.0,
                    y_arrow + 0.18,
                    "PET %.1fs" % pet_value,
                    ha="center",
                    va="bottom",
                    fontsize=10,
                    fontweight="bold",
                    bbox=LABEL_BBOX,
                )
        else:
            ax.text(
                _float(row, "event_time_s") + 0.3,
                base_y + 2.05,
                "PET undefined: no clean exit",
                ha="left",
                va="center",
                fontsize=10,
                fontweight="bold",
                color="#D45A5A",
                bbox=LABEL_BBOX,
            )

    ax.set_title("Post Encroachment Time (PET) Timeline",
                 fontsize=17, fontweight="bold")
    ax.set_xlabel("Time (s)")
    ax.set_yticks(y_ticks)
    ax.set_yticklabels(y_labels)
    ax.set_xlim(9.5, max(20.0, max_time + 1.0))
    ax.grid(axis="x", linestyle="--", linewidth=0.7, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    _save(fig, output_dir, "fig8_safety_pet_timeline.png",
          manifest, "PET conflict-zone timeline")
    plt.close(fig)


def _write_manifest(output_dir, manifest):
    path = os.path.join(output_dir, "figure_manifest.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["file", "title", "path"])
        writer.writeheader()
        writer.writerows(manifest)


def main():
    parser = argparse.ArgumentParser(
        description="Plot revised Scenario 1 KPI figures.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir")
    args = parser.parse_args()

    input_dir = args.input_dir
    output_dir = args.output_dir or input_dir
    os.makedirs(output_dir, exist_ok=True)

    perception = _read_csv(os.path.join(input_dir,
                                        "perception_observation_horizon.csv"))
    control = _read_csv(os.path.join(input_dir, "control_pre_event_kpi.csv"))
    traffic = _read_csv(os.path.join(input_dir,
                                     "traffic_trip_completion_kpi.csv"))
    safety = _read_csv(os.path.join(input_dir, "safety_2d_ttc_pet_prs.csv"))

    manifest = []
    _plot_perception_by_observer(perception, output_dir, manifest, "ego")
    _plot_perception_by_observer(perception, output_dir, manifest, "rsu")
    _plot_perception_breakdown(perception, output_dir, manifest)
    _plot_control_steering(control, output_dir, manifest)
    _plot_control_longitudinal(control, output_dir, manifest)
    _plot_traffic_completion(traffic, output_dir, manifest)
    _plot_safety_ttc(safety, output_dir, manifest)
    _plot_safety_prs(safety, output_dir, manifest)
    _plot_pet_timeline(safety, output_dir, manifest)
    _write_manifest(output_dir, manifest)
    print("Wrote %d figures to %s" % (len(manifest), output_dir))


if __name__ == "__main__":
    main()
