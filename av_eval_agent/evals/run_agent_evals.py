from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


AGENT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = AGENT_ROOT.parent
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from app.graph import agent_graph  # noqa: E402


DEFAULT_CASES_PATH = Path(__file__).with_name("eval_cases.json")
DEFAULT_REPORT_PATH = AGENT_ROOT / "data" / "eval_reports" / "last_agent_eval_report.json"


def _load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dig(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _close_enough(expected: Any, actual: Any) -> bool:
    if isinstance(expected, bool):
        return bool(actual) is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if actual is None:
            return False
        try:
            return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=0.01)
        except (TypeError, ValueError):
            return False
    return actual == expected


def _actual_summary(state: dict[str, Any]) -> dict[str, Any]:
    definition = state.get("scenario_definition", {})
    intent = state.get("intent", {})
    return {
        "scenario_id": definition.get("scenario_id"),
        "scenario_type": definition.get("scenario_type"),
        "requested_actions": intent.get("requested_actions", {}),
        "detected_values": intent.get("detected_values", {}),
        "validation_errors": state.get("validation_errors", []),
        "validation_warnings": state.get("validation_warnings", []),
        "approval_required": state.get("approval_required"),
        "status": state.get("status"),
    }


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    state = agent_graph.invoke({"user_request": case["user_request"]})
    actual = _actual_summary(state)
    expected = case.get("expected", {})
    checks: list[dict[str, Any]] = []

    for key in ["scenario_id", "scenario_type"]:
        if key in expected:
            checks.append(
                {
                    "name": key,
                    "expected": expected[key],
                    "actual": actual.get(key),
                    "passed": _close_enough(expected[key], actual.get(key)),
                    "critical": key == "scenario_id",
                }
            )

    for key, expected_value in (expected.get("requested_actions") or {}).items():
        actual_value = _dig(actual, f"requested_actions.{key}")
        checks.append(
            {
                "name": f"requested_actions.{key}",
                "expected": expected_value,
                "actual": actual_value,
                "passed": _close_enough(expected_value, actual_value),
                "critical": False,
            }
        )

    for key, expected_value in (expected.get("detected_values") or {}).items():
        actual_value = _dig(actual, f"detected_values.{key}")
        checks.append(
            {
                "name": f"detected_values.{key}",
                "expected": expected_value,
                "actual": actual_value,
                "passed": _close_enough(expected_value, actual_value),
                "critical": False,
            }
        )

    checks.append(
        {
            "name": "validation_errors_empty",
            "expected": [],
            "actual": actual.get("validation_errors"),
            "passed": actual.get("validation_errors") == [],
            "critical": False,
        }
    )

    critical_failed = any(not check["passed"] for check in checks if check.get("critical"))
    passed_count = sum(1 for check in checks if check["passed"])
    pass_ratio = passed_count / len(checks) if checks else 1.0

    if critical_failed:
        status = "fail"
    elif pass_ratio == 1.0:
        status = "pass"
    elif pass_ratio >= 0.65:
        status = "partial"
    else:
        status = "fail"

    return {
        "id": case["id"],
        "status": status,
        "pass_ratio": round(pass_ratio, 3),
        "checks": checks,
        "actual": actual,
    }


def run_eval(cases_path: Path = DEFAULT_CASES_PATH) -> dict[str, Any]:
    cases = _load_cases(cases_path)
    results = [_evaluate_case(case) for case in cases]
    counts = {
        "pass": sum(1 for result in results if result["status"] == "pass"),
        "partial": sum(1 for result in results if result["status"] == "partial"),
        "fail": sum(1 for result in results if result["status"] == "fail"),
    }
    total = len(results)
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "cases_path": str(cases_path),
        "total": total,
        "counts": counts,
        "pass_rate": round(counts["pass"] / total, 3) if total else 0,
        "usable_rate": round((counts["pass"] + counts["partial"]) / total, 3) if total else 0,
        "results": results,
    }


def _write_report(report_path: Path, report: dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _print_human_summary(report: dict[str, Any], report_path: Path) -> None:
    counts = report["counts"]
    print("AV Evaluation Agent eval summary")
    print(f"- total: {report['total']}")
    print(f"- pass: {counts['pass']}")
    print(f"- partial: {counts['partial']}")
    print(f"- fail: {counts['fail']}")
    print(f"- usable_rate: {report['usable_rate']}")
    print(f"- report: {report_path}")
    failing = [result for result in report["results"] if result["status"] == "fail"]
    if failing:
        print("- failing cases:")
        for result in failing:
            failed_checks = [check["name"] for check in result["checks"] if not check["passed"]]
            print(f"  - {result['id']}: {', '.join(failed_checks)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic evals for the AV Evaluation Agent.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--json", action="store_true", help="Print the full report JSON to stdout.")
    parser.add_argument("--fail-on-fail", action="store_true", help="Return exit code 1 when any case fails.")
    args = parser.parse_args()

    report = run_eval(args.cases)
    _write_report(args.report, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human_summary(report, args.report)
    if args.fail_on_fail and report["counts"]["fail"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

