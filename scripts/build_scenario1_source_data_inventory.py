#!/usr/bin/env python
"""Build a source-data inventory for Scenario 1 KPI calculations."""

import argparse
import csv
from collections import Counter
from pathlib import Path

import yaml


FIELD_DEFS = [
    ("data_protocol.yaml", "world.fixed_delta_seconds",
     "simulation timestep", "s", "all time-series KPIs"),
    ("data_protocol.yaml", "scenario.single_cav_list",
     "vehicle roles, spawn/destination, V2X, behavior, sensing", "-",
     "role mapping, trip distance, V2X condition"),
    ("frame YAML", "RSU", "whether observer is RSU", "bool",
     "observer classification"),
    ("frame YAML", "camera*.intrinsic/extrinsic/cords",
     "camera calibration and pose", "-", "sensor metadata, image projection"),
    ("frame YAML", "ego_speed", "observer vehicle speed", "km/h",
     "average speed, acceleration, jerk"),
    ("frame YAML", "ego_velocity", "observer vehicle velocity vector", "m/s",
     "2D TTC, speed cross-check"),
    ("frame YAML", "true_ego_pos",
     "observer true pose [x,y,z,roll,yaw,pitch]", "m/deg",
     "trajectory, steering proxy, trip completion"),
    ("frame YAML", "predicted_ego_pos", "localized/predicted ego pose",
     "m/deg", "localization comparison"),
    ("frame YAML", "lidar_pose", "LiDAR sensor pose", "m/deg",
     "sensor metadata"),
    ("frame YAML", "plan_trajectory", "planned waypoint trajectory", "-",
     "control/planning reference if available"),
    ("frame YAML", "total_vehicles.*.carla_id",
     "CARLA ground-truth actor id", "-", "GT object identity, MOTA/MOTP/HOTA"),
    ("frame YAML", "total_vehicles.*.location",
     "GT object center location", "m", "2D TTC, PET, MOTA/MOTP matching"),
    ("frame YAML", "total_vehicles.*.velocity", "GT object velocity vector",
     "m/s", "2D TTC, PRS"),
    ("frame YAML", "total_vehicles.*.speed", "GT object speed",
     "km/h/OpenCDA", "traffic/control reference"),
    ("frame YAML", "total_vehicles.*.extent", "GT bounding box half-size",
     "m", "BEV box, IoU/HOTA"),
    ("frame YAML", "total_vehicles.*.angle", "GT object rotation", "deg",
     "object pose metadata"),
    ("frame YAML", "total_vehicles.*.bp_id", "CARLA blueprint/type", "-",
     "vehicle type filtering"),
    ("frame YAML", "vehicles.*.pr_id", "prediction/track id", "-",
     "tracking ID, IDSW"),
    ("frame YAML", "vehicles.*.matched_gt_id", "GT id matched during dump",
     "-", "diagnostics only"),
    ("frame YAML", "vehicles.*.perception_mode", "prediction generation mode",
     "-", "valid sensor filtering"),
    ("frame YAML", "vehicles.*.location", "predicted object location", "m",
     "MOTP center error"),
    ("frame YAML", "vehicles.*.extent", "predicted object box extent", "m",
     "BEV box, IoU/HOTA"),
    ("frame YAML", "vehicles.*.match_distance", "dump-time GT-pred distance",
     "m", "diagnostic"),
    ("*.png", "*_camera*.png", "camera frame images", "pixel",
     "YOLO/perception source and visual evidence"),
    ("*.png", "topview_screen/*.png", "CARLA top-view screenshots", "pixel",
     "visual verification"),
    ("*.pcd", "*.pcd", "LiDAR point cloud frame", "point cloud",
     "LiDAR perception/fusion source"),
]


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def _frame_yaml_files(directory):
    return sorted(
        path for path in directory.glob("*.yaml")
        if path.name[:6].isdigit())


def _write_csv(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _field_rows():
    return [{
        "source_file_type": source,
        "field_or_pattern": field,
        "meaning": meaning,
        "unit": unit,
        "used_for": used_for,
    } for source, field, meaning, unit, used_for in FIELD_DEFS]


def _summarize_run(condition, run_dir, role_map):
    protocol = _load_yaml(run_dir / "data_protocol.yaml")
    fixed_dt = ((protocol.get("world") or {}).get("fixed_delta_seconds"))
    summary_rows = []
    mode_rows = []

    for observer_dir in sorted(path for path in run_dir.iterdir()
                               if path.is_dir()):
        observer_id = observer_dir.name
        if observer_id == "topview_screen":
            summary_rows.append({
                "condition": condition,
                "run_dir": str(run_dir),
                "observer_id": observer_id,
                "role": "topview_screen",
                "frame_yaml_count": 0,
                "camera_png_count": len(list(observer_dir.glob("*.png"))),
                "pcd_count": 0,
                "fixed_delta_seconds": fixed_dt,
                "first_frame": "",
                "last_frame": "",
                "gt_detections_total": "",
                "prediction_total": "",
                "prediction_modes": "",
            })
            continue

        files = _frame_yaml_files(observer_dir)
        modes = Counter()
        gt_total = 0
        pred_total = 0
        for file_path in files:
            data = _load_yaml(file_path)
            gt_total += len(data.get("total_vehicles") or {})
            vehicles = data.get("vehicles") or {}
            pred_total += len(vehicles)
            for obj in vehicles.values():
                modes[obj.get("perception_mode", "")] += 1

        summary_rows.append({
            "condition": condition,
            "run_dir": str(run_dir),
            "observer_id": observer_id,
            "role": role_map.get(observer_id, "unknown"),
            "frame_yaml_count": len(files),
            "camera_png_count": len(list(observer_dir.glob("*.png"))),
            "pcd_count": len(list(observer_dir.glob("*.pcd"))),
            "fixed_delta_seconds": fixed_dt,
            "first_frame": files[0].stem if files else "",
            "last_frame": files[-1].stem if files else "",
            "gt_detections_total": gt_total,
            "prediction_total": pred_total,
            "prediction_modes": ";".join(
                "%s:%s" % (key, value)
                for key, value in sorted(modes.items())),
        })

        for mode, count in modes.items():
            mode_rows.append({
                "condition": condition,
                "observer_id": observer_id,
                "role": role_map.get(observer_id, "unknown"),
                "perception_mode": mode or "(empty)",
                "count": count,
                "valid_for_overall_sensor_mota_motp":
                "yes" if mode == "yolov5_lidar_fusion" else "no",
                "note":
                "actual YOLO/LiDAR prediction"
                if mode == "yolov5_lidar_fusion" else
                "GT-like fallback; excluded from real sensor MOTA/MOTP"
                if mode == "semantic_lidar_fallback" else "",
            })

    return summary_rows, mode_rows


def _write_markdown(path, runs, summary_rows):
    lines = [
        "# Scenario 1 Source Data Inventory",
        "",
        "## 사용한 원본 실험 결과",
    ]
    for condition, run_dir in runs.items():
        lines.append("- %s: `%s`" % (condition, run_dir))
    lines.extend([
        "",
        "## 저장된 데이터 요약",
        "",
        "| condition | observer | role | YAML frames | camera PNG | PCD | GT dets | predictions | prediction modes |",
        "|---|---:|---|---:|---:|---:|---:|---:|---|",
    ])
    for row in summary_rows:
        lines.append(
            "| {condition} | {observer_id} | {role} | {frame_yaml_count} | "
            "{camera_png_count} | {pcd_count} | {gt_detections_total} | "
            "{prediction_total} | {prediction_modes} |".format(**row))
    lines.extend([
        "",
        "## 핵심 해석",
        "",
        "- `total_vehicles`는 CARLA ground truth 객체 정보다. MOTA/MOTP, TTC, PET, PRS의 GT 기준으로 사용했다.",
        "- `vehicles`는 perception/tracking prediction 정보다. V2X run은 `yolov5_lidar_fusion` prediction을 포함한다.",
        "- 최신 No V2X run의 `vehicles`는 `semantic_lidar_fallback`만 포함한다. 이는 GT-like prediction이므로 실제 센서 MOTA/MOTP에서 제외했다.",
        "- 카메라 원본 PNG와 LiDAR PCD도 저장되어 있으나, 현재 KPI 산출은 프레임별 YAML에 dump된 GT/prediction/pose/speed를 주로 사용했다.",
        "",
        "## 산출 파일",
        "",
        "- `source_data_inventory_summary.csv`: run/observer별 데이터 개수",
        "- `source_data_field_metadata.csv`: 저장 필드 의미와 사용 지표",
        "- `source_prediction_modes.csv`: prediction mode별 유효성",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Build source data inventory for Scenario 1 results.")
    parser.add_argument("--v2x-run-dir", required=True)
    parser.add_argument("--no-v2x-run-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    runs = {
        "V2X": Path(args.v2x_run_dir),
        "No V2X": Path(args.no_v2x_run_dir),
    }
    role_maps = {
        "V2X": {"-1": "RSU", "147": "ego", "154": "neighboring",
                "160": "subject"},
        "No V2X": {"-1": "RSU", "747": "ego", "754": "neighboring",
                   "760": "subject"},
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = []
    mode_rows = []
    for condition, run_dir in runs.items():
        rows, modes = _summarize_run(condition, run_dir, role_maps[condition])
        summary_rows.extend(rows)
        mode_rows.extend(modes)

    _write_csv(output_dir / "source_data_inventory_summary.csv", summary_rows)
    _write_csv(output_dir / "source_data_field_metadata.csv", _field_rows())
    _write_csv(output_dir / "source_prediction_modes.csv", mode_rows)
    _write_markdown(output_dir / "source_data_inventory.md", runs,
                    summary_rows)
    print("Wrote source data inventory to", output_dir)


if __name__ == "__main__":
    main()
