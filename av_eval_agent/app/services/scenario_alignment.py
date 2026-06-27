from __future__ import annotations

from pathlib import Path
from typing import Any


OBJECTIVE_PROFILES: dict[str, dict[str, Any]] = {
    "scenario_1": {
        "name": "intersection occlusion",
        "purpose": (
            "Evaluate ego response to a cross-traffic actor hidden by a large "
            "illegally parked occluding vehicle at an unsignalized intersection."
        ),
        "required_conditions": [
            "large occluding vehicle near the conflict area",
            "cross-traffic actor approaches from the occluded direction",
            "No V2X should show late visual awareness and high risk",
            "V2X should receive actor information earlier and yield/restart safely",
        ],
        "expected_tests": ["scenario_1_v2x", "scenario_1_no_v2x"],
        "tuning_hints": {
            "too_safe": [
                "Decrease actor release delay or start the actor closer to the conflict point.",
                "Move ego start farther upstream only if both vehicles need more natural acceleration.",
                "Move the occluding vehicle closer to the stop line if visual exposure is too early.",
            ],
            "too_dangerous_v2x": [
                "Increase V2X communication range or trigger braking earlier.",
                "Increase stop-line waiting offset or lower restart aggressiveness.",
                "Require TTC clearance before restart.",
            ],
            "missing_occlusion": [
                "Move the large occluding vehicle between ego and the cross-traffic approach.",
                "Use a larger vehicle type for the occluder and keep it stopped.",
            ],
        },
    },
    "scenario_2": {
        "name": "highway cut-out",
        "purpose": (
            "Evaluate lane-change and cut-out response when a lead/neighboring vehicle "
            "reveals a stopped or slow target on a two-lane road."
        ),
        "required_conditions": [
            "ego/subject travels along the two-lane road",
            "a lead or neighboring vehicle reveals the target hazard",
            "No V2X reacts later and produces a near-crash style maneuver",
            "V2X receives cooperative information earlier and changes lane earlier",
        ],
        "expected_tests": ["scenario2_v2x", "scenario2"],
        "tuning_hints": {
            "too_safe": [
                "Move the target closer to the reveal point.",
                "Delay the No V2X lane-change trigger.",
                "Reduce the available sight distance after cut-out.",
            ],
            "too_dangerous_v2x": [
                "Enable V2X on the lead/neighbor vehicle that first observes the hazard.",
                "Increase communication range or start lane change earlier.",
                "Reduce lane-change aggressiveness only after safety is secured.",
            ],
            "missing_cutout": [
                "Place the lead/neighbor vehicle directly between ego and the target.",
                "Keep the target stopped or slow enough to create a meaningful hazard.",
            ],
        },
    },
}


def _records(execution_results: dict[str, Any]) -> list[dict[str, Any]]:
    opencda = execution_results.get("opencda") or {}
    return list(opencda.get("results") or [])


def _record_by_scenario(execution_results: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("test_scenario")): item
        for item in _records(execution_results)
        if item.get("test_scenario")
    }


def _issue(message: str, severity: str = "warning") -> dict[str, str]:
    return {"severity": severity, "message": message}


def _review_record(record: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    scenario = record.get("test_scenario", "unknown")
    status = record.get("status")
    if status == "failed":
        issues.append(_issue(f"{scenario}: OpenCDA execution failed.", "error"))
    elif status == "completed_missing_datadump":
        issues.append(_issue(f"{scenario}: no data_dumping folder was pinned.", "error"))
    elif status == "completed_with_stale_datadump":
        issues.append(_issue(f"{scenario}: only an older data dump was found.", "warning"))
    elif status == "completed_data_dump_not_kpi_ready":
        issues.append(
            _issue(
                f"{scenario}: data dump exists, but vehicle frame logs are missing. "
                "Video review may be possible, but KPI calculation may be limited.",
                "warning",
            )
        )

    log_scan = record.get("log_scan") or {}
    if log_scan.get("fatal"):
        issues.append(
            _issue(
                f"{scenario}: fatal log pattern detected: {', '.join(log_scan.get('matches') or [])}",
                "error",
            )
        )

    data_dump = record.get("data_dump") or {}
    if data_dump and not data_dump.get("matched_current_execution"):
        issues.append(
            _issue(
                f"{scenario}: pinned dump is latest available, not confirmed as generated by this run.",
                "warning",
            )
        )
    return issues


def _scenario_specific_checks(
    scenario_id: str,
    execution_results: dict[str, Any],
) -> list[dict[str, str]]:
    profile = OBJECTIVE_PROFILES.get(scenario_id)
    if not profile:
        return [
            _issue(
                "Custom scenario: objective alignment cannot be fully judged until a scenario profile is registered.",
                "warning",
            )
        ]

    by_scenario = _record_by_scenario(execution_results)
    issues: list[dict[str, str]] = []
    for expected in profile["expected_tests"]:
        if expected not in by_scenario:
            issues.append(_issue(f"Expected test was not executed: {expected}", "error"))

    if scenario_id == "scenario_1" and not any("no_v2x" in key for key in by_scenario):
        issues.append(_issue("Scenario 1 needs a No V2X late-awareness comparison run.", "warning"))
    if scenario_id == "scenario_2" and "scenario2_v2x" in by_scenario:
        dump = (by_scenario["scenario2_v2x"].get("data_dump") or {})
        if dump.get("completeness") == "protocol_only":
            issues.append(
                _issue(
                    "Scenario 2 V2X produced protocol-only logs. Check whether vehicle datadump is enabled for KPI use.",
                    "warning",
                )
            )
    return issues


def evaluate_scenario_alignment(
    project_root: Path,
    scenario_id: str,
    execution_results: dict[str, Any],
) -> dict[str, Any]:
    del project_root  # Reserved for future KPI/file based checks.
    profile = OBJECTIVE_PROFILES.get(scenario_id, {})
    issues: list[dict[str, str]] = []

    for record in _records(execution_results):
        issues.extend(_review_record(record))
    issues.extend(_scenario_specific_checks(scenario_id, execution_results))

    errors = [item for item in issues if item.get("severity") == "error"]
    warnings = [item for item in issues if item.get("severity") != "error"]
    if errors:
        decision = "human_review_required"
    elif warnings:
        decision = "review_or_autotune_recommended"
    else:
        decision = "aligned"

    review_questions: list[str] = []
    if scenario_id == "scenario_1":
        review_questions = [
            "Should No V2X be tuned to collision, near-crash, or late safe stop?",
            "Should V2X prioritize stop-line yielding or fastest safe restart?",
            "Is 20 m communication range fixed by the study design?",
        ]
    elif scenario_id == "scenario_2":
        review_questions = [
            "Should No V2X be tuned to near-crash without collision?",
            "Which vehicle is the V2X message provider: lead, neighboring, or target?",
            "Should lane-change timing be fixed or optimized by safety margin?",
        ]

    return {
        "scenario_id": scenario_id,
        "objective": profile.get("purpose", "No registered objective profile."),
        "required_conditions": profile.get("required_conditions", []),
        "decision": decision,
        "issues": issues,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "auto_tuning_policy": {
            "mode": "recommend_then_apply_after_review",
            "reason": (
                "Scenario timing can be auto-tuned, but collision/near-crash intent "
                "should be confirmed before overwriting canonical OpenCDA files."
            ),
            "candidate_actions": profile.get("tuning_hints", {}),
        },
        "human_in_the_loop": {
            "required": decision != "aligned",
            "questions": review_questions,
        },
    }
