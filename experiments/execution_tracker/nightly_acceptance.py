#!/usr/bin/env python3
"""Read-only acceptance check for the scheduled launchd nightly run.

This verifier does not run the nightly engine and never changes runtime state.
It binds five independent observations to the same run:

1. the installed launchd job points at this checkout's wrapper and runner;
2. launchd's run counter advanced and its last exit code is zero;
3. the post-schedule log segment names the exact run and reports the funnel OK;
4. nightly_run and funnel_health bind the same target/run and the immutable
   bundle passes the production verifier;
5. no incomplete alarm flag remains.

The receipt is filesystem/process-manager evidence, not cryptographic process
attestation. A human can still manufacture equivalent files, so the receipt
must not be described as proof of operator identity.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import plistlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


SCHEMA = "ar.nightly_launchd_acceptance.v1"
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
LAUNCHD_LAST_EXIT_RE = re.compile(r"^\s*last exit code = (-?\d+)\s*$", re.MULTILINE)
LAUNCHD_RUNS_RE = re.compile(r"^\s*runs = (\d+)\s*$", re.MULTILINE)


class AcceptanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Inputs:
    repo_root: Path
    expected_start: dt.datetime
    expected_target: str
    runs_before: int
    log_path: Path
    alarm_path: Path
    plist_path: Path
    launchd_label: str
    launchctl_state_file: Path | None = None


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AcceptanceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"cannot read strict JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AcceptanceError(f"JSON root must be an object: {path}")
    return value


def _date8(value: object, name: str) -> str:
    text = str(value or "")
    if not (len(text) == 8 and text.isdigit()):
        raise AcceptanceError(f"{name} must be an 8-digit date: {text!r}")
    return text


def _aware_time(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO timestamp: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("expected-start must include a UTC offset")
    return parsed


def _path_mtime_is_fresh(path: Path, expected_start: dt.datetime) -> None:
    try:
        modified = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
    except OSError as exc:
        raise AcceptanceError(f"required path missing: {path}") from exc
    if modified < expected_start.astimezone(dt.timezone.utc):
        raise AcceptanceError(
            f"stale path {path}: mtime={modified.isoformat()} "
            f"expected>={expected_start.astimezone(dt.timezone.utc).isoformat()}"
        )


def _load_plist(inputs: Inputs) -> dict:
    try:
        with inputs.plist_path.open("rb") as fh:
            payload = plistlib.load(fh)
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        raise AcceptanceError(f"cannot read launchd plist: {exc}") from exc
    if not isinstance(payload, dict):
        raise AcceptanceError("launchd plist root must be a dictionary")
    return payload


def _validate_plist(inputs: Inputs) -> dict:
    payload = _load_plist(inputs)
    wrapper = inputs.repo_root / "experiments" / "execution_tracker" / "launchd" / "ar_env_wrapper.sh"
    runner = inputs.repo_root / "experiments" / "execution_tracker" / "run_nightly.py"
    expected_args = [str(wrapper), "/usr/bin/python3", str(runner)]
    if payload.get("Label") != inputs.launchd_label:
        raise AcceptanceError(f"launchd Label mismatch: {payload.get('Label')!r}")
    # governance-mutation: NIGHTLY_ACCEPTANCE_ENTRYPOINT
    if payload.get("ProgramArguments") != expected_args:
        raise AcceptanceError("launchd ProgramArguments do not bind the expected wrapper and runner")
    if payload.get("StandardOutPath") != str(inputs.log_path):
        raise AcceptanceError("launchd stdout does not bind the audited log")
    schedule = payload.get("StartCalendarInterval")
    if not isinstance(schedule, list):
        raise AcceptanceError("launchd schedule must be a weekday list")
    normalized = {
        (item.get("Weekday"), item.get("Hour"), item.get("Minute"))
        for item in schedule if isinstance(item, dict)
    }
    expected = {(weekday, 16, 35) for weekday in range(1, 6)}
    if normalized != expected:
        raise AcceptanceError(f"launchd schedule mismatch: {sorted(normalized)!r}")
    return {"label": inputs.launchd_label, "program_arguments": expected_args}


def _launchctl_text(inputs: Inputs) -> str:
    if inputs.launchctl_state_file is not None:
        try:
            return inputs.launchctl_state_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise AcceptanceError(f"cannot read launchctl state fixture: {exc}") from exc
    command = ["launchctl", "print", f"gui/{os.getuid()}/{inputs.launchd_label}"]
    result = subprocess.run(command, text=True, capture_output=True, timeout=15)
    if result.returncode != 0:
        raise AcceptanceError(f"launchctl print failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def _validate_launchctl(inputs: Inputs) -> dict:
    text = _launchctl_text(inputs)
    runs_match = LAUNCHD_RUNS_RE.search(text)
    exit_match = LAUNCHD_LAST_EXIT_RE.search(text)
    if not runs_match or not exit_match:
        raise AcceptanceError("launchctl state lacks runs or last exit code")
    runs = int(runs_match.group(1))
    last_exit = int(exit_match.group(1))
    # governance-mutation: NIGHTLY_ACCEPTANCE_LAUNCHD_ADVANCED
    if runs <= inputs.runs_before:
        raise AcceptanceError(
            f"launchd run counter did not advance: before={inputs.runs_before} now={runs}"
        )
    # governance-mutation: NIGHTLY_ACCEPTANCE_LAUNCHD_EXIT
    if last_exit != 0:
        raise AcceptanceError(f"launchd last exit code is {last_exit}, expected 0")
    return {"runs_before": inputs.runs_before, "runs_after": runs, "last_exit_code": last_exit}


def _validate_nightly_result(inputs: Inputs) -> tuple[dict, dict]:
    nightly_path = inputs.repo_root / "experiments" / "execution_tracker" / "nightly_run.json"
    health_path = inputs.repo_root / "public" / "data" / "v2" / "funnel_health.json"
    _path_mtime_is_fresh(nightly_path, inputs.expected_start)
    _path_mtime_is_fresh(health_path, inputs.expected_start)
    nightly = _load_json(nightly_path)
    health = _load_json(health_path)
    target = _date8(nightly.get("target_trade_date"), "nightly target_trade_date")
    run_id = str(nightly.get("run_id") or "")
    if target != inputs.expected_target:
        raise AcceptanceError(f"nightly target mismatch: {target} != {inputs.expected_target}")
    if not RUN_ID_RE.fullmatch(run_id):
        raise AcceptanceError(f"nightly run_id is not a safe component: {run_id!r}")
    if nightly.get("report") != "COMPLETE" or nightly.get("published") is not True:
        raise AcceptanceError("nightly result is not COMPLETE and published=true")
    rows = [row for row in nightly.get("steps", []) if isinstance(row, dict) and row.get("step") == "research_funnel"]
    if len(rows) != 1 or rows[0].get("status") != "OK":
        raise AcceptanceError("nightly result lacks exactly one research_funnel=OK step")
    if health.get("run_id") != run_id or health.get("target_trade_date") != target:
        raise AcceptanceError("funnel health is not bound to the nightly run and target")

    et_dir = inputs.repo_root / "experiments" / "execution_tracker"
    if str(et_dir) not in sys.path:
        sys.path.insert(0, str(et_dir))
    import run_nightly  # imported only for its production, read-only verifier

    # governance-mutation: NIGHTLY_ACCEPTANCE_PERSISTENT_BUNDLE
    run_nightly._validate_funnel_health(health, str(health_path))
    bundle = inputs.repo_root / str((health.get("bundle") or {}).get("location") or "")
    if bundle.is_symlink() or not bundle.is_dir():
        raise AcceptanceError(f"immutable funnel bundle is missing or symlinked: {bundle}")
    _path_mtime_is_fresh(bundle / "manifest.json", inputs.expected_start)
    return nightly, health


def _validate_log(inputs: Inputs, run_id: str) -> dict:
    _path_mtime_is_fresh(inputs.log_path, inputs.expected_start)
    try:
        text = inputs.log_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AcceptanceError(f"cannot read nightly log: {exc}") from exc
    marker = f"[run] run_id={run_id} target_trade_date={inputs.expected_target}"
    position = text.rfind(marker)
    if position < 0:
        raise AcceptanceError("nightly log lacks the exact run context marker")
    tail = text[position:]
    # governance-mutation: NIGHTLY_ACCEPTANCE_LOG_RUN_BOUNDARY
    next_run = re.search(r"(?m)^\[run\] ", tail[len(marker):])
    if next_run:
        tail = tail[:len(marker) + next_run.start()]
    # governance-mutation: NIGHTLY_ACCEPTANCE_EXACT_LOG_SEGMENT
    if not re.search(r"(?m)^research_funnel: OK\s*$", tail):
        raise AcceptanceError("exact run log segment lacks research_funnel: OK")
    report_pattern = (
        rf"(?m)^\[report\] COMPLETE\b.*\brun_id={re.escape(run_id)}\b"
        rf".*\btarget={re.escape(inputs.expected_target)}\b"
    )
    if not re.search(report_pattern, tail):
        raise AcceptanceError("exact run log segment lacks its bound COMPLETE report")
    return {"run_context_marker": marker, "segment_bytes": len(tail.encode("utf-8"))}


def _validate_no_alarm(inputs: Inputs) -> dict:
    # governance-mutation: NIGHTLY_ACCEPTANCE_NO_ALARM
    if inputs.alarm_path.exists():
        raise AcceptanceError("incomplete alarm flag still exists")
    return {"path": str(inputs.alarm_path), "exists": False}


def audit(inputs: Inputs) -> dict:
    checks: list[dict] = []

    def check(name: str, callback: Callable[[], object]) -> object | None:
        try:
            evidence = callback()
        except Exception as exc:  # every malformed observation is a failed receipt, never a crash-pass
            checks.append({"name": name, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
            return None
        checks.append({"name": name, "status": "PASS", "evidence": evidence})
        return evidence

    check("launchd_plist_binding", lambda: _validate_plist(inputs))
    check("launchd_process_state", lambda: _validate_launchctl(inputs))
    result = check("nightly_and_funnel_artifacts", lambda: _validate_nightly_result(inputs))
    if isinstance(result, tuple):
        nightly, _health = result
        check("exact_run_log_segment", lambda: _validate_log(inputs, str(nightly["run_id"])))
    else:
        checks.append({"name": "exact_run_log_segment", "status": "FAIL", "error": "artifact binding failed first"})
    check("no_incomplete_alarm", lambda: _validate_no_alarm(inputs))
    passed = all(row["status"] == "PASS" for row in checks)
    return {
        "schema": SCHEMA,
        "status": "PASS" if passed else "FAIL",
        "expected_start": inputs.expected_start.isoformat(),
        "expected_target": inputs.expected_target,
        "evidence_strength": "FILESYSTEM_AND_LAUNCHCTL_PROXY_NOT_PROCESS_ATTESTATION",
        "checks": checks,
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--expected-start", required=True, type=_aware_time)
    parser.add_argument("--expected-target", required=True)
    parser.add_argument("--launchctl-runs-before", required=True, type=int)
    parser.add_argument("--log", default="/tmp/ar-nightly.log", type=Path)
    parser.add_argument("--alarm", default="/tmp/ar-nightly-incomplete", type=Path)
    parser.add_argument("--plist", default=str(Path.home() / "Library/LaunchAgents/com.ar.nightly.plist"), type=Path)
    parser.add_argument("--launchd-label", default="com.ar.nightly")
    parser.add_argument("--launchctl-state-file", type=Path)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    target = _date8(args.expected_target, "expected-target")
    receipt = audit(Inputs(
        repo_root=args.repo_root.resolve(),
        expected_start=args.expected_start,
        expected_target=target,
        runs_before=args.launchctl_runs_before,
        log_path=args.log,
        alarm_path=args.alarm,
        plist_path=args.plist,
        launchd_label=args.launchd_label,
        launchctl_state_file=args.launchctl_state_file,
    ))
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
