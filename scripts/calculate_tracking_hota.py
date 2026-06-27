#!/usr/bin/env python
"""
Calculate tracking KPIs from OpenCDA datadump YAML files.

The script reads:
  - total_vehicles: CARLA ground truth objects
  - vehicles: perception/tracking prediction objects

It computes a lightweight HOTA-style score over BEV axis-aligned bounding-box
IoU thresholds. It is intentionally dependency-light so it can run in the
existing CARLA/OpenCDA Python environment.
"""

import argparse
import csv
import math
import os
from collections import Counter, defaultdict

import yaml


DEFAULT_ALPHAS = [round(i / 100.0, 2) for i in range(5, 100, 5)]


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    return data or {}


def _as_float_list(value, size):
    if not isinstance(value, list) or len(value) < size:
        return None
    try:
        return [float(value[i]) for i in range(size)]
    except (TypeError, ValueError):
        return None


def _bbox_bev(obj):
    location = _as_float_list(obj.get("location"), 2)
    extent = _as_float_list(obj.get("extent"), 2)
    if location is None or extent is None:
        return None
    x, y = location
    ex, ey = abs(extent[0]), abs(extent[1])
    return (x - ex, y - ey, x + ex, y + ey)


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
    intersection = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    if union <= 0.0:
        return 0.0
    return intersection / union


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_gt_objects(frame_data):
    objects = {}
    for key, obj in (frame_data.get("total_vehicles") or {}).items():
        gt_id = _int_or_none(obj.get("carla_id", key))
        if gt_id is None:
            continue
        bbox = _bbox_bev(obj)
        if bbox is None:
            continue
        objects[gt_id] = {
            "id": gt_id,
            "bbox": bbox,
            "bp_id": obj.get("bp_id", "vehicle"),
        }
    return objects


def _parse_prediction_objects(frame_data, prediction_mode=None):
    objects = {}
    for index, (key, obj) in enumerate((frame_data.get("vehicles") or {}).items()):
        mode = obj.get("perception_mode", "")
        if prediction_mode and mode != prediction_mode:
            continue
        pr_id = _int_or_none(obj.get("pr_id"))
        if pr_id is None:
            pr_id = _int_or_none(obj.get("carla_id"))
        if pr_id is None:
            pr_id = index
        bbox = _bbox_bev(obj)
        if bbox is None:
            continue
        objects[pr_id] = {
            "id": pr_id,
            "bbox": bbox,
            "bp_id": obj.get("bp_id", "detected_vehicle"),
            "perception_mode": mode,
            "matched_gt_id": _int_or_none(obj.get("matched_gt_id")),
        }
    return objects


def _match_frame(gt_objects, pred_objects, alpha):
    pairs = []
    for gt_id, gt_obj in gt_objects.items():
        for pr_id, pred_obj in pred_objects.items():
            sim = _iou(gt_obj["bbox"], pred_obj["bbox"])
            if sim >= alpha:
                pairs.append((sim, gt_id, pr_id))

    pairs.sort(reverse=True)
    matched_gt = set()
    matched_pr = set()
    matches = []
    for sim, gt_id, pr_id in pairs:
        if gt_id in matched_gt or pr_id in matched_pr:
            continue
        matched_gt.add(gt_id)
        matched_pr.add(pr_id)
        matches.append({
            "gt_id": gt_id,
            "pr_id": pr_id,
            "similarity": sim,
        })

    false_negatives = [gt_id for gt_id in gt_objects if gt_id not in matched_gt]
    false_positives = [pr_id for pr_id in pred_objects if pr_id not in matched_pr]
    return matches, false_positives, false_negatives


def _calculate_for_alpha(frames, alpha, include_association_rows=False):
    tp_matches = []
    fp_total = 0
    fn_total = 0
    gt_total = 0
    pred_total = 0
    similarity_sum = 0.0
    gt_count = Counter()
    pred_count = Counter()
    pair_count = Counter()
    last_pr_for_gt = {}
    id_switches = 0

    for frame_number, gt_objects, pred_objects in frames:
        gt_total += len(gt_objects)
        pred_total += len(pred_objects)
        gt_count.update(gt_objects.keys())
        pred_count.update(pred_objects.keys())

        matches, false_positives, false_negatives = _match_frame(
            gt_objects, pred_objects, alpha)
        fp_total += len(false_positives)
        fn_total += len(false_negatives)

        for match in matches:
            gt_id = match["gt_id"]
            pr_id = match["pr_id"]
            if gt_id in last_pr_for_gt and last_pr_for_gt[gt_id] != pr_id:
                id_switches += 1
            last_pr_for_gt[gt_id] = pr_id
            pair_count[(gt_id, pr_id)] += 1
            similarity_sum += match["similarity"]
            match["frame"] = frame_number
            tp_matches.append(match)

    tp_total = len(tp_matches)
    det_denominator = tp_total + fp_total + fn_total
    deta = tp_total / det_denominator if det_denominator else 0.0

    assoc_values = []
    association_rows = []
    for match in tp_matches:
        gt_id = match["gt_id"]
        pr_id = match["pr_id"]
        tpa = pair_count[(gt_id, pr_id)]
        fna = gt_count[gt_id] - tpa
        fpa = pred_count[pr_id] - tpa
        denom = tpa + fna + fpa
        assa_c = tpa / denom if denom else 0.0
        assoc_values.append(assa_c)
        if include_association_rows:
            association_rows.append({
                "alpha": alpha,
                "frame": match["frame"],
                "gtID": gt_id,
                "prID": pr_id,
                "similarity": match["similarity"],
                "TPA": tpa,
                "FNA": fna,
                "FPA": fpa,
                "AssA_c": assa_c,
            })

    assa = sum(assoc_values) / len(assoc_values) if assoc_values else 0.0
    hota = math.sqrt(deta * assa) if deta > 0 and assa > 0 else 0.0
    loca = similarity_sum / tp_total if tp_total else 0.0
    mota = 1.0 - ((fn_total + fp_total + id_switches) / gt_total) \
        if gt_total else 0.0

    result = {
        "alpha": alpha,
        "frames": len(frames),
        "gt_dets": gt_total,
        "pred_dets": pred_total,
        "tp": tp_total,
        "fp": fp_total,
        "fn": fn_total,
        "idsw": id_switches,
        "DetA": deta,
        "AssA": assa,
        "HOTA": hota,
        "LocA": loca,
        "MOTA": mota,
        "MOTP": loca,
    }
    if include_association_rows:
        result["association_rows"] = association_rows
    return result


def _read_sequence(observer_dir, prediction_mode=None):
    frames = []
    perception_modes = Counter()
    yaml_files = sorted(
        f for f in os.listdir(observer_dir)
        if f.lower().endswith(".yaml") and f[:6].isdigit())

    for file_name in yaml_files:
        path = os.path.join(observer_dir, file_name)
        frame_data = _load_yaml(path)
        frame_number = int(file_name[:6])
        gt_objects = _parse_gt_objects(frame_data)
        pred_objects = _parse_prediction_objects(
            frame_data, prediction_mode=prediction_mode)
        for obj in pred_objects.values():
            if obj.get("perception_mode"):
                perception_modes[obj["perception_mode"]] += 1
        frames.append((frame_number, gt_objects, pred_objects))

    return frames, perception_modes


def _infer_roles(run_dir):
    protocol_path = os.path.join(run_dir, "data_protocol.yaml")
    if not os.path.exists(protocol_path):
        return {}

    protocol = _load_yaml(protocol_path)
    scenario = protocol.get("scenario") or {}
    role_spawns = {}
    for cav in scenario.get("single_cav_list") or []:
        spawn = cav.get("spawn_position") or []
        if len(spawn) >= 2:
            role_spawns[cav.get("name", "vehicle")] = (
                float(spawn[0]), float(spawn[1]))

    roles = {}
    for name in os.listdir(run_dir):
        observer_dir = os.path.join(run_dir, name)
        if not os.path.isdir(observer_dir) or name == "topview_screen":
            continue
        if name == "-1":
            roles[name] = "rsu"
            continue
        yaml_files = sorted(
            f for f in os.listdir(observer_dir)
            if f.lower().endswith(".yaml") and f[:6].isdigit())
        if not yaml_files:
            roles[name] = "unknown"
            continue
        frame_data = _load_yaml(os.path.join(observer_dir, yaml_files[0]))
        true_pos = frame_data.get("true_ego_pos") or \
            frame_data.get("predicted_ego_pos") or []
        if len(true_pos) < 2 or not role_spawns:
            roles[name] = "vehicle"
            continue
        x, y = float(true_pos[0]), float(true_pos[1])
        best_role = "vehicle"
        best_dist = 999999.0
        for role, (sx, sy) in role_spawns.items():
            dist = math.hypot(x - sx, y - sy)
            if dist < best_dist:
                best_dist = dist
                best_role = role
        roles[name] = best_role
    return roles


def _iter_observer_dirs(run_dir, observer_filter):
    for name in sorted(os.listdir(run_dir)):
        observer_dir = os.path.join(run_dir, name)
        if not os.path.isdir(observer_dir) or name == "topview_screen":
            continue
        if observer_filter and name not in observer_filter:
            continue
        yield name, observer_dir


def _run_label(run_dir):
    scenario = os.path.basename(os.path.dirname(run_dir))
    run_time = os.path.basename(run_dir)
    return scenario, run_time


def evaluate_run(run_dir, alphas, observer_filter=None, role_filter=None,
                 prediction_mode=None, association_alpha=0.5):
    roles = _infer_roles(run_dir)
    scenario, run_time = _run_label(run_dir)
    rows = []
    detail_rows = []
    association_rows = []

    for observer_id, observer_dir in _iter_observer_dirs(run_dir, observer_filter):
        observer_role = roles.get(observer_id, "unknown")
        if role_filter and observer_role not in role_filter:
            continue
        frames, perception_modes = _read_sequence(
            observer_dir, prediction_mode=prediction_mode)
        if not frames:
            continue

        alpha_results = [_calculate_for_alpha(
            frames, alpha,
            include_association_rows=abs(alpha - association_alpha) < 1e-9)
            for alpha in alphas]
        result_050 = min(alpha_results, key=lambda r: abs(r["alpha"] - 0.5))
        mode = prediction_mode or (
            perception_modes.most_common(1)[0][0] if perception_modes else "")
        summary = {
            "scenario": scenario,
            "run_time": run_time,
            "observer_id": observer_id,
            "observer_role": observer_role,
            "perception_mode": mode,
            "frames": result_050["frames"],
            "gt_dets": result_050["gt_dets"],
            "pred_dets": result_050["pred_dets"],
            "HOTA_mean": sum(r["HOTA"] for r in alpha_results) /
            len(alpha_results),
            "HOTA_0.50": result_050["HOTA"],
            "DetA_0.50": result_050["DetA"],
            "AssA_0.50": result_050["AssA"],
            "LocA_0.50": result_050["LocA"],
            "MOTA_0.50": result_050["MOTA"],
            "MOTP_0.50": result_050["MOTP"],
            "TP_0.50": result_050["tp"],
            "FP_0.50": result_050["fp"],
            "FN_0.50": result_050["fn"],
            "IDSW_0.50": result_050["idsw"],
        }
        rows.append(summary)

        association_result = min(
            alpha_results, key=lambda r: abs(r["alpha"] - association_alpha))
        for assoc in association_result.get("association_rows", []):
            association_row = {
                "scenario": scenario,
                "run_time": run_time,
                "observer_id": observer_id,
                "observer_role": observer_role,
                "perception_mode": mode,
            }
            association_row.update(assoc)
            association_rows.append(association_row)

        for result in alpha_results:
            detail = {
                "scenario": scenario,
                "run_time": run_time,
                "observer_id": observer_id,
                "observer_role": observer_role,
                "perception_mode": mode,
            }
            detail.update({
                key: value for key, value in result.items()
                if key != "association_rows"
            })
            detail_rows.append(detail)

    return rows, detail_rows, association_rows


def _write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _format_float(value):
    if isinstance(value, float):
        return "%.4f" % value
    return str(value)


def _write_report(path, summary_rows, run_dirs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    modes = sorted(set(row.get("perception_mode") or "unknown"
                       for row in summary_rows))
    lines = [
        "# Scenario 1 Tracking KPI Report",
        "",
        "This report computes HOTA-style tracking KPIs from the current "
        "OpenCDA datadump structure.",
        "",
        "Detected perception modes: `%s`." % "`, `".join(modes),
        "",
        "For `yolov5_lidar_fusion` rows, `vehicles` are perception "
        "predictions matched against CARLA `total_vehicles` ground truth. "
        "Rows marked `server_or_semantic` are not YOLO tracker outputs and "
        "should be treated as supporting reference only.",
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
        "| scenario | run_time | observer | mode | HOTA_mean | HOTA_0.50 | "
        "DetA_0.50 | AssA_0.50 | MOTA_0.50 | TP/FP/FN/IDSW |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for row in summary_rows:
        observer = "%s(%s)" % (row["observer_role"], row["observer_id"])
        counts = "%s/%s/%s/%s" % (
            row["TP_0.50"], row["FP_0.50"], row["FN_0.50"],
            row["IDSW_0.50"])
        lines.append(
            "| {scenario} | {run_time} | {observer} | {mode} | {hota_mean} "
            "| {hota50} | {deta50} | {assa50} | {mota50} | {counts} |"
            .format(
                scenario=row["scenario"],
                run_time=row["run_time"],
                observer=observer,
                mode=row["perception_mode"] or "-",
                hota_mean=_format_float(row["HOTA_mean"]),
                hota50=_format_float(row["HOTA_0.50"]),
                deta50=_format_float(row["DetA_0.50"]),
                assa50=_format_float(row["AssA_0.50"]),
                mota50=_format_float(row["MOTA_0.50"]),
                counts=counts))

    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Calculate HOTA-style tracking KPIs from OpenCDA dumps.")
    parser.add_argument("--run-dir", action="append", required=True,
                        help="OpenCDA run folder, e.g. data_dumping/.../time")
    parser.add_argument("--output-dir", required=True,
                        help="Folder for CSV and Markdown outputs.")
    parser.add_argument("--observer", action="append",
                        help="Optional observer folder id to evaluate.")
    parser.add_argument("--role", action="append",
                        help="Optional observer role to evaluate, e.g. rsu or ego.")
    parser.add_argument("--prediction-mode",
                        help="Optional prediction mode filter, e.g. "
                        "yolov5_lidar_fusion.")
    parser.add_argument("--association-alpha", type=float, default=0.5,
                        help="Alpha threshold used for the per-TP "
                        "TPA/FNA/FPA association table.")
    args = parser.parse_args()

    summary_rows = []
    detail_rows = []
    association_rows = []
    for run_dir in args.run_dir:
        run_summary, run_details, run_associations = evaluate_run(
            run_dir,
            DEFAULT_ALPHAS,
            observer_filter=set(args.observer) if args.observer else None,
            role_filter=set(args.role) if args.role else None,
            prediction_mode=args.prediction_mode,
            association_alpha=args.association_alpha)
        summary_rows.extend(run_summary)
        detail_rows.extend(run_details)
        association_rows.extend(run_associations)

    if not summary_rows:
        raise SystemExit("No tracking KPI rows were generated.")

    _write_csv(os.path.join(args.output_dir, "tracking_kpi_summary.csv"),
               summary_rows)
    _write_csv(os.path.join(args.output_dir, "tracking_kpi_by_alpha.csv"),
               detail_rows)
    _write_csv(os.path.join(args.output_dir, "tracking_hota_association.csv"),
               association_rows)
    _write_report(os.path.join(args.output_dir, "tracking_kpi_report.md"),
                  summary_rows,
                  args.run_dir)

    print("Wrote tracking KPI summary to %s" %
          os.path.join(args.output_dir, "tracking_kpi_summary.csv"))
    print("Wrote tracking KPI alpha details to %s" %
          os.path.join(args.output_dir, "tracking_kpi_by_alpha.csv"))
    print("Wrote HOTA association details to %s" %
          os.path.join(args.output_dir, "tracking_hota_association.csv"))
    print("Wrote report to %s" %
          os.path.join(args.output_dir, "tracking_kpi_report.md"))


if __name__ == "__main__":
    main()
