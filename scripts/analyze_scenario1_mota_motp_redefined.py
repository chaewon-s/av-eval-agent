#!/usr/bin/env python
"""
Scenario 1 YOLO/LiDAR tracking MOTA/MOTP analysis.

This script is intentionally separate from the scenario files. It reads existing
OpenCDA datadump YAML files and compares several matching/evaluation choices:

  - legacy BEV IoU matching
  - CLEAR MOT style center-distance matching
  - ROI/FOV filtering
  - track persistence filtering
  - bounding-box size sanity filtering

MOTP is reported as center-distance error in meters, not as IoU similarity.
"""

import argparse
import csv
import math
import os
import sys
from collections import Counter, defaultdict

import yaml


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import calculate_tracking_hota as hota  # noqa: E402


DEFAULT_RUNS = [
    os.path.join(
        REPO_ROOT, "data_dumping", "scenario1_v2x", "2026_05_07_18_09_25"),
    os.path.join(
        REPO_ROOT, "data_dumping", "scenario1_no_v2x", "2026_05_07_18_14_14"),
]
PREDICTION_MODE = "yolov5_lidar_fusion"
DEFAULT_ROLES = {"rsu", "ego"}
DISTANCE_THRESHOLDS = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
PERSISTENCE_VALUES = [1, 2, 3, 5]
SIZE_AREA_MIN_VALUES = [0.0, 0.5, 1.0, 2.0]
DEFAULT_ROI_M = 60.0


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def _as_float_list(value, size):
    if not isinstance(value, list) or len(value) < size:
        return None
    try:
        return [float(value[i]) for i in range(size)]
    except (TypeError, ValueError):
        return None


def _center_xy(obj):
    location = _as_float_list(obj.get("location"), 2)
    if location is None:
        return None
    return (location[0], location[1])


def _extent_xy(obj):
    extent = _as_float_list(obj.get("extent"), 2)
    if extent is None:
        return None
    return (abs(extent[0]), abs(extent[1]))


def _bbox_bev(obj):
    center = _center_xy(obj)
    extent = _extent_xy(obj)
    if center is None or extent is None:
        return None
    x, y = center
    ex, ey = extent
    return (x - ex, y - ey, x + ex, y + ey)


def _bbox_area(obj):
    extent = _extent_xy(obj)
    if extent is None:
        return 0.0
    return max(0.0, 2.0 * extent[0]) * max(0.0, 2.0 * extent[1])


def _iou(box_a, box_b):
    if box_a is None or box_b is None:
        return 0.0
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter
    return inter / denom if denom > 0.0 else 0.0


def _dist(a, b):
    if a is None or b is None:
        return float("inf")
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_gt(frame_data):
    gt = {}
    for key, obj in (frame_data.get("total_vehicles") or {}).items():
        gt_id = _int_or_none(obj.get("carla_id", key))
        center = _center_xy(obj)
        bbox = _bbox_bev(obj)
        if gt_id is None or center is None or bbox is None:
            continue
        gt[gt_id] = {
            "id": gt_id,
            "center": center,
            "bbox": bbox,
            "area": _bbox_area(obj),
            "bp_id": obj.get("bp_id", "vehicle"),
        }
    return gt


def _parse_predictions(frame_data, prediction_mode=PREDICTION_MODE):
    preds = {}
    for index, (key, obj) in enumerate((frame_data.get("vehicles") or {}).items()):
        if prediction_mode and obj.get("perception_mode") != prediction_mode:
            continue
        pr_id = _int_or_none(obj.get("pr_id"))
        if pr_id is None:
            pr_id = _int_or_none(obj.get("carla_id"))
        if pr_id is None:
            pr_id = index
        center = _center_xy(obj)
        bbox = _bbox_bev(obj)
        if center is None or bbox is None:
            continue
        preds[pr_id] = {
            "id": pr_id,
            "center": center,
            "bbox": bbox,
            "area": _bbox_area(obj),
            "bp_id": obj.get("bp_id", "detected_vehicle"),
            "matched_gt_id": _int_or_none(obj.get("matched_gt_id")),
            "match_distance_log": _safe_float(obj.get("match_distance")),
            "pcd": _safe_float(obj.get("number of pcd")),
        }
    return preds


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _observer_origin(frame_data):
    for key in ("true_ego_pos", "predicted_ego_pos", "lidar_pose"):
        value = _as_float_list(frame_data.get(key), 2)
        if value is not None:
            return (value[0], value[1])
    return None


def _run_label(run_dir):
    return os.path.basename(os.path.dirname(run_dir)), os.path.basename(run_dir)


def _load_sequence(observer_dir, frame_start=None, frame_end=None):
    frames = []
    pred_lifetime = Counter()
    files = sorted(
        name for name in os.listdir(observer_dir)
        if name.lower().endswith(".yaml") and name[:6].isdigit())
    for name in files:
        frame_no = int(name[:6])
        if frame_start is not None and frame_no < frame_start:
            continue
        if frame_end is not None and frame_no > frame_end:
            continue
        data = _load_yaml(os.path.join(observer_dir, name))
        gt = _parse_gt(data)
        preds = _parse_predictions(data)
        origin = _observer_origin(data)
        for pr_id in preds:
            pred_lifetime[pr_id] += 1
        frames.append({
            "frame": frame_no,
            "gt": gt,
            "preds": preds,
            "origin": origin,
        })
    return frames, pred_lifetime


def _filter_frame(frame, pred_lifetime, roi_m=None, min_persistence=1,
                  min_area=0.0, max_area=120.0):
    origin = frame["origin"]

    def in_roi(obj):
        if roi_m is None or origin is None:
            return True
        return _dist(obj["center"], origin) <= roi_m

    gt = {
        gt_id: obj for gt_id, obj in frame["gt"].items()
        if in_roi(obj)
    }
    preds = {
        pr_id: obj for pr_id, obj in frame["preds"].items()
        if in_roi(obj)
        and pred_lifetime.get(pr_id, 0) >= min_persistence
        and obj["area"] >= min_area
        and obj["area"] <= max_area
    }
    return gt, preds


def _candidate_similarity(gt, pred, method, threshold):
    distance = _dist(gt["center"], pred["center"])
    iou = _iou(gt["bbox"], pred["bbox"])
    if method == "iou":
        ok = iou >= threshold
        score = iou
    elif method == "center_distance":
        ok = distance <= threshold
        # Greedy matcher sorts descending, so invert distance into a score.
        score = -distance
    else:
        raise ValueError("unknown method: %s" % method)
    return ok, score, distance, iou


def _match_frame(gt, preds, method, threshold):
    pairs = []
    for gt_id, gt_obj in gt.items():
        for pr_id, pred in preds.items():
            ok, score, distance, iou = _candidate_similarity(
                gt_obj, pred, method, threshold)
            if ok:
                pairs.append((score, gt_id, pr_id, distance, iou))
    pairs.sort(reverse=True)
    used_gt = set()
    used_pr = set()
    matches = []
    for score, gt_id, pr_id, distance, iou in pairs:
        if gt_id in used_gt or pr_id in used_pr:
            continue
        used_gt.add(gt_id)
        used_pr.add(pr_id)
        matches.append({
            "gt_id": gt_id,
            "pr_id": pr_id,
            "distance_m": distance,
            "iou": iou,
        })
    fp = [pr_id for pr_id in preds if pr_id not in used_pr]
    fn = [gt_id for gt_id in gt if gt_id not in used_gt]
    return matches, fp, fn


def _nearest_gt_stats(pred, gt):
    best = {
        "distance_m": float("inf"),
        "iou": 0.0,
        "gt_id": "",
    }
    for gt_id, gt_obj in gt.items():
        d = _dist(pred["center"], gt_obj["center"])
        iou = _iou(pred["bbox"], gt_obj["bbox"])
        if d < best["distance_m"]:
            best = {"distance_m": d, "iou": iou, "gt_id": gt_id}
    return best


def _evaluate(frames, pred_lifetime, method, threshold, roi_m=None,
              min_persistence=1, min_area=0.0, max_area=120.0):
    tp = fp = fn = idsw = 0
    gt_total = pred_total = 0
    distances = []
    ious = []
    last_pr_for_gt = {}
    fp_causes = Counter()
    gt_visibility = Counter()
    pred_area_values = []
    matched_area_values = []

    for frame in frames:
        raw_gt = frame["gt"]
        raw_preds = frame["preds"]
        gt, preds = _filter_frame(
            frame, pred_lifetime, roi_m=roi_m,
            min_persistence=min_persistence,
            min_area=min_area,
            max_area=max_area)
        gt_total += len(gt)
        pred_total += len(preds)
        for gt_id in gt:
            gt_visibility[gt_id] += 1
        for pred in preds.values():
            pred_area_values.append(pred["area"])

        matches, false_positives, false_negatives = _match_frame(
            gt, preds, method, threshold)
        tp += len(matches)
        fp += len(false_positives)
        fn += len(false_negatives)

        for match in matches:
            gt_id = match["gt_id"]
            pr_id = match["pr_id"]
            if gt_id in last_pr_for_gt and last_pr_for_gt[gt_id] != pr_id:
                idsw += 1
            last_pr_for_gt[gt_id] = pr_id
            distances.append(match["distance_m"])
            ious.append(match["iou"])
            matched_area_values.append(preds[pr_id]["area"])

        for pr_id in false_positives:
            pred = preds[pr_id]
            nearest = _nearest_gt_stats(pred, gt)
            if not gt:
                fp_causes["no_gt_in_eval_roi"] += 1
            elif pred["area"] < 1.0:
                fp_causes["tiny_bbox"] += 1
            elif pred["area"] > 120.0:
                fp_causes["oversized_bbox"] += 1
            elif nearest["distance_m"] <= 5.0 and nearest["iou"] < 0.1:
                fp_causes["near_gt_but_bbox_mismatch"] += 1
            elif nearest["distance_m"] > 10.0:
                fp_causes["far_from_any_gt"] += 1
            else:
                fp_causes["unmatched_duplicate_or_threshold"] += 1

        # Count predictions removed only by ROI/quality filtering separately.
        if roi_m is not None and frame["origin"] is not None:
            for pred in raw_preds.values():
                if _dist(pred["center"], frame["origin"]) > roi_m:
                    fp_causes["filtered_outside_roi"] += 1
        for pr_id, pred in raw_preds.items():
            if pred_lifetime.get(pr_id, 0) < min_persistence:
                fp_causes["filtered_short_track"] += 1
            elif pred["area"] < min_area:
                fp_causes["filtered_small_bbox"] += 1
            elif pred["area"] > max_area:
                fp_causes["filtered_large_bbox"] += 1
        for gt_id, gt_obj in raw_gt.items():
            if roi_m is not None and frame["origin"] is not None and \
                    _dist(gt_obj["center"], frame["origin"]) > roi_m:
                fp_causes["gt_outside_roi_not_counted"] += 1

    mota = 1.0 - ((fn + fp + idsw) / gt_total) if gt_total else 0.0
    motp_m = sum(distances) / len(distances) if distances else 0.0
    mean_iou = sum(ious) / len(ious) if ious else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {
        "frames": len(frames),
        "gt_dets": gt_total,
        "pred_dets": pred_total,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "idsw": idsw,
        "mota": mota,
        "motp_m": motp_m,
        "mean_iou": mean_iou,
        "precision": precision,
        "recall": recall,
        "mean_pred_area": _mean(pred_area_values),
        "mean_matched_area": _mean(matched_area_values),
        "unique_gt": len(gt_visibility),
        "mean_gt_visible_frames": _mean(list(gt_visibility.values())),
        "fp_causes": dict(fp_causes),
    }


def _mean(values):
    return sum(values) / len(values) if values else 0.0


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


def _flatten_result(base, result):
    row = dict(base)
    for key, value in result.items():
        if key == "fp_causes":
            continue
        row[key] = value
    for cause, count in result.get("fp_causes", {}).items():
        row["cause_%s" % cause] = count
    return row


def _scenario_condition(scenario):
    return "V2X" if "v2x" in scenario and "no_v2x" not in scenario else "No V2X"


def _evaluate_run(run_dir, roles, frame_start=None, frame_end=None):
    scenario, run_time = _run_label(run_dir)
    observer_roles = hota._infer_roles(run_dir)
    summary_rows = []
    sweep_rows = []
    fp_rows = []

    for observer_id, observer_dir in hota._iter_observer_dirs(run_dir, None):
        role = observer_roles.get(observer_id, "unknown")
        if roles and role not in roles:
            continue
        frames, pred_lifetime = _load_sequence(
            observer_dir, frame_start=frame_start, frame_end=frame_end)
        if not frames:
            continue

        base = {
            "scenario": scenario,
            "condition": _scenario_condition(scenario),
            "run_time": run_time,
            "observer_id": observer_id,
            "observer_role": role,
            "prediction_mode": PREDICTION_MODE,
        }

        candidates = [
            ("legacy_iou_0.50", "iou", 0.50, None, 1, 0.0),
            ("center_distance_3m", "center_distance", 3.0, None, 1, 0.0),
            ("center_distance_5m", "center_distance", 5.0, None, 1, 0.0),
            ("center_distance_3m_roi60", "center_distance", 3.0,
             DEFAULT_ROI_M, 1, 0.0),
            ("center_distance_5m_roi60", "center_distance", 5.0,
             DEFAULT_ROI_M, 1, 0.0),
            ("roi60_persist3_size1_center5m", "center_distance", 5.0,
             DEFAULT_ROI_M, 3, 1.0),
        ]
        for label, method, threshold, roi_m, persist, min_area in candidates:
            result = _evaluate(
                frames, pred_lifetime, method, threshold, roi_m=roi_m,
                min_persistence=persist, min_area=min_area)
            row = _flatten_result({
                **base,
                "candidate": label,
                "match_method": method,
                "threshold": threshold,
                "roi_m": "" if roi_m is None else roi_m,
                "min_persistence": persist,
                "min_area_m2": min_area,
            }, result)
            summary_rows.append(row)

        for distance_threshold in DISTANCE_THRESHOLDS:
            result = _evaluate(
                frames, pred_lifetime, "center_distance", distance_threshold,
                roi_m=DEFAULT_ROI_M, min_persistence=1, min_area=0.0)
            sweep_rows.append(_flatten_result({
                **base,
                "sweep_type": "distance_threshold_roi60",
                "threshold": distance_threshold,
                "roi_m": DEFAULT_ROI_M,
                "min_persistence": 1,
                "min_area_m2": 0.0,
            }, result))

        for persist in PERSISTENCE_VALUES:
            result = _evaluate(
                frames, pred_lifetime, "center_distance", 5.0,
                roi_m=DEFAULT_ROI_M, min_persistence=persist,
                min_area=0.0)
            sweep_rows.append(_flatten_result({
                **base,
                "sweep_type": "persistence_roi60_center5m",
                "threshold": 5.0,
                "roi_m": DEFAULT_ROI_M,
                "min_persistence": persist,
                "min_area_m2": 0.0,
            }, result))

        for min_area in SIZE_AREA_MIN_VALUES:
            result = _evaluate(
                frames, pred_lifetime, "center_distance", 5.0,
                roi_m=DEFAULT_ROI_M, min_persistence=1,
                min_area=min_area)
            sweep_rows.append(_flatten_result({
                **base,
                "sweep_type": "min_bbox_area_roi60_center5m",
                "threshold": 5.0,
                "roi_m": DEFAULT_ROI_M,
                "min_persistence": 1,
                "min_area_m2": min_area,
            }, result))

        fp_base = _evaluate(
            frames, pred_lifetime, "iou", 0.50, roi_m=None,
            min_persistence=1, min_area=0.0)
        for cause, count in sorted(fp_base["fp_causes"].items()):
            fp_rows.append({
                **base,
                "baseline": "legacy_iou_0.50",
                "cause": cause,
                "count": count,
            })

    return summary_rows, sweep_rows, fp_rows


def _plot_outputs(output_dir, summary_rows, sweep_rows):
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - plotting is optional
        print("Plotting skipped: %s" % exc)
        return

    os.makedirs(output_dir, exist_ok=True)
    focus_candidates = [
        "legacy_iou_0.50",
        "center_distance_3m",
        "center_distance_5m",
        "center_distance_5m_roi60",
        "roi60_persist3_size1_center5m",
    ]
    focus_rows = [
        r for r in summary_rows
        if r["candidate"] in focus_candidates and r["observer_role"] in {"rsu", "ego"}
    ]

    labels = [
        "%s-%s-%s" % (r["condition"], r["observer_role"], r["candidate"])
        for r in focus_rows
    ]
    x = list(range(len(focus_rows)))
    if focus_rows:
        fig, ax1 = plt.subplots(figsize=(max(12, len(focus_rows) * 0.55), 6))
        ax1.bar(x, [float(r["mota"]) for r in focus_rows],
                color="#4c8fd3", label="MOTA")
        ax1.set_ylabel("MOTA")
        ax1.set_ylim(min(-2.0, min(float(r["mota"]) for r in focus_rows) - 0.2), 1.05)
        ax1.axhline(0.0, color="#555555", linewidth=1)
        ax2 = ax1.twinx()
        ax2.plot(x, [float(r["motp_m"]) for r in focus_rows],
                 color="#e36c0a", marker="o", label="MOTP distance")
        ax2.set_ylabel("MOTP center error (m)")
        ax1.set_xticks(x)
        ax1.set_xticklabels(labels, rotation=65, ha="right", fontsize=8)
        ax1.set_title("Scenario 1 MOTA/MOTP by Matching Criterion")
        ax1.grid(axis="y", linestyle="--", alpha=0.35)
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
        fig.tight_layout()
        fig.savefig(os.path.join(output_dir, "fig1_mota_motp_by_method.png"),
                    dpi=160)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(max(12, len(focus_rows) * 0.55), 6))
        width = 0.25
        ax.bar([i - width for i in x], [float(r["tp"]) for r in focus_rows],
               width, label="TP", color="#3b82c4")
        ax.bar(x, [float(r["fp"]) for r in focus_rows],
               width, label="FP", color="#d65a5a")
        ax.bar([i + width for i in x], [float(r["fn"]) for r in focus_rows],
               width, label="FN", color="#8a8f98")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=65, ha="right", fontsize=8)
        ax.set_ylabel("Count")
        ax.set_title("TP / FP / FN Decomposition")
        ax.grid(axis="y", linestyle="--", alpha=0.35)
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(output_dir, "fig2_error_decomposition.png"),
                    dpi=160)
        plt.close(fig)

    distance_rows = [
        r for r in sweep_rows
        if r["sweep_type"] == "distance_threshold_roi60"
    ]
    groups = defaultdict(list)
    for r in distance_rows:
        groups[(r["condition"], r["observer_role"])].append(r)
    if groups:
        fig, ax = plt.subplots(figsize=(10, 6))
        for key, rows in sorted(groups.items()):
            rows = sorted(rows, key=lambda r: float(r["threshold"]))
            ax.plot([float(r["threshold"]) for r in rows],
                    [float(r["mota"]) for r in rows],
                    marker="o", label="%s-%s" % key)
        ax.set_xlabel("Center-distance matching threshold (m)")
        ax.set_ylabel("MOTA")
        ax.set_title("Distance Threshold Sensitivity (ROI 60m)")
        ax.grid(True, linestyle="--", alpha=0.35)
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(output_dir, "fig3_distance_threshold_sweep.png"),
                    dpi=160)
        plt.close(fig)

    persist_rows = [
        r for r in sweep_rows
        if r["sweep_type"] == "persistence_roi60_center5m"
    ]
    groups = defaultdict(list)
    for r in persist_rows:
        groups[(r["condition"], r["observer_role"])].append(r)
    if groups:
        fig, ax = plt.subplots(figsize=(10, 6))
        for key, rows in sorted(groups.items()):
            rows = sorted(rows, key=lambda r: int(r["min_persistence"]))
            ax.plot([int(r["min_persistence"]) for r in rows],
                    [float(r["fp"]) for r in rows],
                    marker="o", label="%s-%s FP" % key)
        ax.set_xlabel("Minimum track persistence (frames)")
        ax.set_ylabel("False positives")
        ax.set_title("FP Suppression by Track Persistence")
        ax.grid(True, linestyle="--", alpha=0.35)
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(output_dir, "fig4_persistence_fp_effect.png"),
                    dpi=160)
        plt.close(fig)


def _best_rows(summary_rows):
    rows = [
        r for r in summary_rows
        if r["candidate"] == "roi60_persist3_size1_center5m"
    ]
    return sorted(rows, key=lambda r: (r["condition"], r["observer_role"]))


def _write_report(output_dir, run_dirs, summary_rows, sweep_rows, fp_rows):
    path = os.path.join(output_dir, "interpretation.md")
    best = _best_rows(summary_rows)
    legacy = [r for r in summary_rows if r["candidate"] == "legacy_iou_0.50"]
    center5 = [r for r in summary_rows if r["candidate"] == "center_distance_5m"]

    def fmt(value, digits=3):
        try:
            return ("%%.%df" % digits) % float(value)
        except (TypeError, ValueError):
            return str(value)

    lines = [
        "# Scenario 1 MOTA/MOTP Redefined Analysis",
        "",
        "## Inputs",
        "",
    ]
    for run_dir in run_dirs:
        scenario_name, run_time = _run_label(run_dir)
        lines.append("- `%s/%s`" % (scenario_name, run_time))

    lines.extend([
        "",
        "## Redefined Calculation",
        "",
        "- Prediction: YOLO/LiDAR detection only (`yolov5_lidar_fusion`).",
        "- Ground truth: CARLA `total_vehicles` in the same datadump frame.",
        "- MOTA = `1 - (FN + FP + IDSW) / GT`.",
        "- MOTP = mean center-distance error between matched GT and prediction, in meters.",
        "- Main recommended matching: center-distance threshold 5 m + ROI 60 m + track persistence >= 3 frames + bbox area >= 1 m2.",
        "- YOLO confidence score is not stored in these datadump YAML files, so post-hoc FP suppression is evaluated with track persistence and bbox-size sanity filters instead of a true confidence threshold sweep.",
        "",
        "## Why Legacy YOLO MOTA/MOTP Was Low",
        "",
        "The legacy IoU-based matching is too strict for this log because the YOLO/LiDAR fused boxes often have unstable extents. A prediction can be close to a real vehicle center but still receive low BEV IoU, so it is counted as FP while the corresponding GT is counted as FN. This double penalty pushes MOTA down.",
        "",
        "In addition, the raw YOLO/LiDAR logs contain many short-lived detections and small boxes. Without ROI/FOV and persistence filtering, these detections inflate FP.",
        "",
        "## Baseline vs Center-Distance Matching",
        "",
        "| condition | observer | candidate | MOTA | MOTP_m | TP | FP | FN | IDSW |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for r in sorted(legacy + center5, key=lambda row: (
            row["condition"], row["observer_role"], row["candidate"])):
        lines.append("| {condition} | {observer_role} | {candidate} | {mota} | {motp} | {tp} | {fp} | {fn} | {idsw} |".format(
            condition=r["condition"],
            observer_role=r["observer_role"],
            candidate=r["candidate"],
            mota=fmt(r["mota"]),
            motp=fmt(r["motp_m"], 2),
            tp=r["tp"],
            fp=r["fp"],
            fn=r["fn"],
            idsw=r["idsw"]))

    lines.extend([
        "",
        "## Recommended Setting",
        "",
        "| condition | observer | MOTA | MOTP_m | precision | recall | TP | FP | FN | IDSW |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for r in best:
        lines.append("| {condition} | {observer_role} | {mota} | {motp} | {precision} | {recall} | {tp} | {fp} | {fn} | {idsw} |".format(
            condition=r["condition"],
            observer_role=r["observer_role"],
            mota=fmt(r["mota"]),
            motp=fmt(r["motp_m"], 2),
            precision=fmt(r["precision"]),
            recall=fmt(r["recall"]),
            tp=r["tp"],
            fp=r["fp"],
            fn=r["fn"],
            idsw=r["idsw"]))

    lines.extend([
        "",
        "## Final Recommendation",
        "",
        "For YOLO-only perception evaluation, use center-distance CLEAR MOT rather than strict BEV IoU as the main MOTA/MOTP criterion. Use IoU as a supplementary localization/shape-quality diagnostic.",
        "",
        "Recommended Scenario 1 YOLO-only report setting:",
        "",
        "- Matching: center-distance <= 5 m",
        "- Evaluation ROI: observer-centered 60 m",
        "- Track persistence: >= 3 frames",
        "- Size sanity: bbox area >= 1 m2, bbox area <= 120 m2",
        "- MOTP unit: meters, lower is better",
        "",
        "This improves the fairness of YOLO-only evaluation, but it does not remove the early-occlusion limitation. V2X fusion is still necessary because it provides a stable actor-message track before visual/LiDAR-only perception can reliably observe the critical actor.",
        "",
        "## Output Files",
        "",
        "- `mota_motp_summary.csv`",
        "- `candidate_threshold_sweep.csv`",
        "- `fp_root_cause.csv`",
        "- `fig1_mota_motp_by_method.png`",
        "- `fig2_error_decomposition.png`",
        "- `fig3_distance_threshold_sweep.png`",
        "- `fig4_persistence_fp_effect.png`",
    ])

    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", action="append",
                        help="Scenario 1 datadump run dir. Defaults to the 5/7 YOLO runs.")
    parser.add_argument("--output-dir",
                        default=os.path.join(
                            REPO_ROOT, "evaluation_outputs",
                            "scenario1_mota_motp_redefined_2026_05_18"))
    parser.add_argument("--role", action="append",
                        help="Observer role to evaluate. Defaults to rsu and ego.")
    parser.add_argument("--frame-start", type=int)
    parser.add_argument("--frame-end", type=int)
    args = parser.parse_args()

    run_dirs = args.run_dir or DEFAULT_RUNS
    roles = set(args.role) if args.role else DEFAULT_ROLES
    summary_rows = []
    sweep_rows = []
    fp_rows = []
    for run_dir in run_dirs:
        run_summary, run_sweep, run_fp = _evaluate_run(
            run_dir, roles, frame_start=args.frame_start,
            frame_end=args.frame_end)
        summary_rows.extend(run_summary)
        sweep_rows.extend(run_sweep)
        fp_rows.extend(run_fp)

    if not summary_rows:
        raise SystemExit("No rows generated. Check run paths and prediction mode.")

    os.makedirs(args.output_dir, exist_ok=True)
    _write_csv(os.path.join(args.output_dir, "mota_motp_summary.csv"),
               summary_rows)
    _write_csv(os.path.join(args.output_dir, "candidate_threshold_sweep.csv"),
               sweep_rows)
    _write_csv(os.path.join(args.output_dir, "fp_root_cause.csv"), fp_rows)
    _plot_outputs(args.output_dir, summary_rows, sweep_rows)
    _write_report(args.output_dir, run_dirs, summary_rows, sweep_rows, fp_rows)

    print("Wrote Scenario 1 MOTA/MOTP analysis to %s" % args.output_dir)


if __name__ == "__main__":
    main()
