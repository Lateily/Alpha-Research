"""Small offline CLI for AIOS-K1 control-plane checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from policy_engine import POLICY_ALLOWED, evaluate_policy
from registry import replay_events
from reconciler import reconcile
from task_compiler import SPEC_BLOCKED, compile_task_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline AIOS-K1 tooling.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser("compile", help="Compile one task manifest")
    compile_parser.add_argument("--input", required=True, help="Source JSON task record")
    compile_parser.add_argument("--output", help="Optional output JSON path")

    replay_parser = subparsers.add_parser("replay", help="Replay AIOS state events")
    replay_parser.add_argument("--events", required=True, help="JSON list of events")
    replay_parser.add_argument("--output", help="Optional output JSON path")

    reconcile_parser = subparsers.add_parser(
        "reconcile", help="Run read-only reconciliation from a fixture JSON"
    )
    reconcile_parser.add_argument("--input", required=True, help="Fixture JSON object")
    reconcile_parser.add_argument("--output", help="Optional output JSON path")

    policy_parser = subparsers.add_parser(
        "policy", help="Evaluate a K2 policy fixture without executing"
    )
    policy_parser.add_argument("--input", required=True, help="Policy fixture JSON object")
    policy_parser.add_argument("--output", help="Optional output JSON path")

    args = parser.parse_args(argv)
    if args.command == "compile":
        result = compile_task_manifest(_load_json(args.input)).to_dict()
        _write_json(result, args.output)
        return 2 if result["status"] == SPEC_BLOCKED else 0
    if args.command == "replay":
        result = replay_events(_load_json(args.events)).to_dict()
        _write_json(result, args.output)
        return 2 if result["invalid_events"] else 0
    if args.command == "reconcile":
        fixture = _load_json(args.input)
        if not isinstance(fixture, dict):
            print("reconcile input must be a JSON object", file=sys.stderr)
            return 2
        result = reconcile(
            backlog_items=fixture.get("backlog_items", []),
            manifests=fixture.get("manifests", []),
            registry_snapshot=fixture.get("registry_snapshot"),
            progress_events=fixture.get("progress_events", []),
            pull_requests=fixture.get("pull_requests", []),
            doc_claims=fixture.get("doc_claims", []),
            alerts=fixture.get("alerts", []),
            followups=fixture.get("followups", []),
        )
        _write_json(result, args.output)
        return 1 if _has_findings(result) else 0
    if args.command == "policy":
        fixture = _load_json(args.input)
        if not isinstance(fixture, dict):
            print("policy input must be a JSON object", file=sys.stderr)
            return 2
        result = evaluate_policy(
            fixture.get("task_manifest"),
            mode=fixture.get("mode"),
            task_type=fixture.get("task_type"),
            required_tools=fixture.get("required_tools"),
            target_paths=fixture.get("target_paths"),
            reviewer_agent=fixture.get("reviewer_agent"),
            approval_evidence=fixture.get("approval_evidence"),
            allowlist_evidence=fixture.get("allowlist_evidence"),
            external_texts=fixture.get("external_texts"),
        ).to_dict()
        _write_json(result, args.output)
        return 0 if result["policy_status"] == POLICY_ALLOWED else 2
    return 2


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(value: Any, output: str | None) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if output:
        Path(output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


def _has_findings(report: dict[str, Any]) -> bool:
    return any(
        bool(value)
        for key, value in report.items()
        if key not in {"schema", "generated_at"}
    )


if __name__ == "__main__":
    raise SystemExit(main())

