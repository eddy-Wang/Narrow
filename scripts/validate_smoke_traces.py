from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_SECTIONS = {
    "evaluation",
    "turn_metrics",
    "latency",
    "model_usage",
    "mode_specific_metrics",
    "sessions",
}

REQUIRED_AGENT_NODES = {
    "understand_user",
    "validate_patch",
    "update_state",
    "build_query",
    "lexical_retrieve",
    "dense_retrieve_fallback",
    "attribute_retrieve",
    "rrf_fusion",
    "constraint_filter",
    "rerank_fallback",
    "information_gain_question",
    "build_response",
    "validate_response",
}


def validate_report_schema(
    path: Path,
    expected_mode: str,
    expected_sessions: int,
) -> dict[str, Any]:
    """Validate the shared report contract used by both evaluation modes."""

    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise TypeError(f"{path}: report root must be an object")
    missing = REQUIRED_SECTIONS - report.keys()
    if missing:
        raise ValueError(f"{path}: missing sections {sorted(missing)}")
    for section in REQUIRED_SECTIONS - {"sessions"}:
        if not isinstance(report[section], dict):
            raise TypeError(f"{path}: section {section!r} must be an object")
    if report.get("mode") != expected_mode:
        raise ValueError(f"{path}: expected mode {expected_mode!r}")
    if report.get("schema_version") != "1.0":
        raise ValueError(f"{path}: unsupported schema_version")

    sessions = report["sessions"]
    if not isinstance(sessions, list):
        raise TypeError(f"{path}: sessions must be an array")
    if report["evaluation"].get("sample_count") != expected_sessions:
        raise ValueError(
            f"{path}: expected {expected_sessions} sessions, got "
            f"{report['evaluation'].get('sample_count')}"
        )
    if len(sessions) != expected_sessions:
        raise ValueError(f"{path}: sessions length does not match expected count")

    try:
        api_calls = report["model_usage"]["combined"]["api_calls"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{path}: combined API usage is missing") from exc
    if api_calls != 0:
        raise ValueError(f"{path}: traditional evaluation used an API")

    for session in sessions:
        if not isinstance(session, dict):
            raise TypeError(f"{path}: every session must be an object")
        missing_session = {
            "scenario_id", "success", "turns", "goal_snapshot", "conversation"
        } - session.keys()
        if missing_session:
            raise ValueError(
                f"{path}: session is missing fields {sorted(missing_session)}"
            )
        if not isinstance(session["goal_snapshot"], dict):
            raise TypeError(f"{path}: {session['scenario_id']} has no goal snapshot")
        if not isinstance(session["conversation"], list):
            raise TypeError(f"{path}: {session['scenario_id']} conversation is not an array")
        for turn in session["conversation"]:
            if not isinstance(turn, dict):
                raise TypeError(f"{path}: conversation turn must be an object")
            missing_turn = {
                "turn", "user", "assistant", "recommendations",
                "agent_layer_trace", "agent_trace_error",
            } - turn.keys()
            if missing_turn:
                raise ValueError(
                    f"{path}: conversation turn is missing fields {sorted(missing_turn)}"
                )
    return report


def validate(
    path: Path, expected_mode: str, expected_sessions: int
) -> dict[str, Any]:
    report = validate_report_schema(path, expected_mode, expected_sessions)

    turn_count = 0
    node_counts = {node: 0 for node in REQUIRED_AGENT_NODES}
    for session in report["sessions"]:
        for turn in session["conversation"]:
            turn_count += 1
            if turn.get("agent_trace_error") is not None:
                raise ValueError(
                    f"{path}: turn {turn['turn']} trace failed: "
                    f"{turn['agent_trace_error']}"
                )
            trace = turn.get("agent_layer_trace")
            if not trace:
                raise ValueError(f"{path}: turn {turn['turn']} has no layer trace")
            observed_nodes: set[str] = set()
            for step in trace:
                if not isinstance(step.get("step"), int):
                    raise TypeError(f"{path}: trace step is not an integer")
                if not isinstance(step.get("nodes"), list) or not step["nodes"]:
                    raise ValueError(f"{path}: trace nodes are missing")
                if not isinstance(step.get("updates"), dict):
                    raise TypeError(f"{path}: trace updates are not an object")
                observed_nodes.update(str(node) for node in step["nodes"])
            missing_nodes = REQUIRED_AGENT_NODES - observed_nodes
            if missing_nodes:
                raise ValueError(
                    f"{path}: {session['scenario_id']} turn {turn['turn']} "
                    f"missing nodes {sorted(missing_nodes)}"
                )
            for node in observed_nodes:
                if node in node_counts:
                    node_counts[node] += 1
    if turn_count == 0:
        raise ValueError(f"{path}: no executed turns")
    return {
        "mode": expected_mode,
        "sessions": len(report["sessions"]),
        "turns": turn_count,
        "node_counts": node_counts,
        "trace_coverage": 1.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("techjam", type=Path)
    parser.add_argument("realistic", type=Path)
    parser.add_argument("--expected-techjam", type=int, default=1)
    parser.add_argument("--expected-realistic", type=int, default=1)
    parser.add_argument("--schema-only", action="store_true")
    args = parser.parse_args()
    inputs = [
        (args.techjam, "techjam", args.expected_techjam),
        (args.realistic, "realistic", args.expected_realistic),
    ]
    if args.schema_only:
        results = [
            {
                "mode": mode,
                "sessions": len(validate_report_schema(path, mode, expected)["sessions"]),
                "schema_valid": True,
            }
            for path, mode, expected in inputs
        ]
    else:
        results = [validate(path, mode, expected) for path, mode, expected in inputs]
    print(json.dumps({"valid": True, "reports": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
