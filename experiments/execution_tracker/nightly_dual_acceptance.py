#!/usr/bin/env python3
"""Read-only scheduled-run and research-usability receipts for one nightly run.

Exit 0 means both sheets were observed without a research data gap; exit 2
means the scheduled run passed but research remains degraded; exit 1 means the
scheduled run or artifact binding failed. No exit status grants U4 or paper
authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

CODE_ROOT = Path(__file__).resolve().parents[2]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

import nightly_acceptance
import run_nightly


SCHEMA = "ar.nightly_dual_acceptance.v1"
HEX64 = re.compile(r"[0-9a-f]{64}")
GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
REQUIRED_PUBLIC = {
    "public:meta.json", "public:funnel_health.json",
    "public:macro/source_health.json", "public:macro/macro_events.json",
}


class AuditError(RuntimeError):
    pass


def _object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise AuditError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object)
    except (OSError, ValueError) as exc:
        raise AuditError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"JSON root is not an object: {path}")
    return value


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AuditError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _installed_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=5,
    )
    head = result.stdout.strip()
    # governance-mutation: NIGHTLY_ACCEPTANCE_GIT_OID
    if result.returncode != 0 or not GIT_OID.fullmatch(head):
        raise AuditError("cannot identify installed repository HEAD")
    return head


def summarize_steps(steps: object) -> dict:
    expected = [name for name, *_ in run_nightly.STEPS]
    if not isinstance(steps, list) or len(steps) != len(expected):
        raise AuditError(f"nightly must report all {len(expected)} steps (24 at this code version)")
    observed = [row.get("step") for row in steps if isinstance(row, dict)]
    if observed != expected:
        raise AuditError("nightly steps differ from the current ordered DAG")
    return {
        "count": len(steps),
        "non_ok": [{"step": row["step"], "status": row.get("status")}
                   for row in steps if row.get("status") != "OK"],
        "steps": [{"step": row["step"], "status": row.get("status")} for row in steps],
    }


def validate_publication(root: Path, run_id: str, target: str) -> dict:
    if not nightly_acceptance.RUN_ID_RE.fullmatch(run_id):
        raise AuditError("unsafe run_id")
    public = root / "public" / "data" / "v2"
    et = root / "experiments" / "execution_tracker"
    public_pointer_path = public / "current_run.json"
    et_pointer_path = et / "current_run.json"
    # governance-mutation: NIGHTLY_ACCEPTANCE_DUAL_POINTER
    if _sha(public_pointer_path) != _sha(et_pointer_path):
        raise AuditError("public and ET current_run pointer bytes differ")
    pointer = _read(public_pointer_path)
    rel = f"runs/{run_id}/manifest.json"
    if (pointer.get("run_id") != run_id or pointer.get("target_trade_date") != target
            or pointer.get("manifest_path") != rel):
        raise AuditError("current_run pointer is not bound to this run and target")
    expected_hash = pointer.get("manifest_sha256")
    if not isinstance(expected_hash, str) or not HEX64.fullmatch(expected_hash):
        raise AuditError("invalid current_run manifest hash")
    public_manifest = public / rel
    durable_manifest = et / rel
    # governance-mutation: NIGHTLY_ACCEPTANCE_DUAL_MANIFEST
    if _sha(public_manifest) != expected_hash or _sha(durable_manifest) != expected_hash:
        raise AuditError("public/durable manifest hash differs from the current_run pointer")
    manifest = _read(public_manifest)
    if manifest.get("run_id") != run_id or manifest.get("target_trade_date") != target:
        raise AuditError("manifest run/target binding differs")
    artifacts = manifest.get("artifacts")
    # governance-mutation: NIGHTLY_ACCEPTANCE_REQUIRED_ARTIFACTS
    if (not isinstance(artifacts, dict) or pointer.get("artifacts") != artifacts
            or not REQUIRED_PUBLIC.issubset(artifacts)):
        raise AuditError("manifest artifacts differ from current_run pointer")
    count = 0
    for name, digest in artifacts.items():
        if not name.startswith("public:"):
            continue
        rel_path = PurePosixPath(name.removeprefix("public:"))
        if (rel_path.is_absolute() or ".." in rel_path.parts or not rel_path.parts
                or not isinstance(digest, str) or not HEX64.fullmatch(digest)):
            raise AuditError(f"invalid public manifest artifact: {name}")
        path = public.joinpath(*rel_path.parts)
        if path.is_symlink() or _sha(path) != digest:
            raise AuditError(f"public manifest artifact hash differs: {name}")
        count += 1
    return {"run_id": run_id, "target_trade_date": target,
            "manifest_sha256": expected_hash, "public_artifacts": count,
            "pointers_byte_identical": True, "manifests_hash_identical": True}


def summarize_research(root: Path, run_id: str, target: str) -> dict:
    from experiments.macro_os import collectors, m1a

    public = root / "public" / "data" / "v2"
    source = _read(public / "macro" / "source_health.json")
    events = _read(public / "macro" / "macro_events.json")
    health = _read(public / "funnel_health.json")
    # governance-mutation: NIGHTLY_ACCEPTANCE_MACRO_RUN_BINDING
    if events.get("run_id") != run_id:
        raise AuditError("macro_events run_id is not the accepted run_id")
    if health.get("run_id") != run_id or health.get("target_trade_date") != target:
        raise AuditError("funnel_health run_id/target is not the accepted run")
    sources = source.get("data")
    event_rows = events.get("data")
    if not isinstance(sources, list) or not isinstance(event_rows, list):
        raise AuditError("macro source/event rows must be arrays")
    unavailable = [row for row in sources if isinstance(row, dict) and row.get("status") != "OK"]
    if len(unavailable) + sum(isinstance(row, dict) and row.get("status") == "OK" for row in sources) != len(sources):
        raise AuditError("malformed macro source row")
    missing_consensus = sum(
        isinstance(row, dict) and (row.get("consensus") is None or row.get("consensus_status") == "DATA_BLOCKED")
        for row in event_rows
    )
    if any(not isinstance(row, dict) for row in event_rows):
        raise AuditError("malformed macro event row")
    expected_sources = {
        (spec.source_id, metric.series_id, metric.metric_key)
        for spec in collectors.collection_plan() for metric in spec.metrics
    }
    observed_sources = [
        (row.get("source_id"), row.get("series_id"), row.get("metric_key"))
        for row in sources
    ]
    expected_events = {
        f"{rule['source_id']}:{rule['series_id']}:{rule['metric_key']}"
        for rules in m1a.load_rules()["regions"].values() for rule in rules
    }
    observed_events = [row.get("context_id") for row in event_rows]
    source_coverage_complete = (
        len(observed_sources) == len(expected_sources)
        and set(observed_sources) == expected_sources
    )
    event_coverage_complete = (
        len(observed_events) == len(expected_events)
        and set(observed_events) == expected_events
    )
    macro = {
        "step": "macro_m1c", "run_id": run_id, "target_trade_date": target,
        # governance-mutation: NIGHTLY_ACCEPTANCE_MACRO_UNIVERSE
        "quality": "DATA_BLOCKED" if (not source_coverage_complete or not event_coverage_complete
                                      or unavailable or missing_consensus)
                   else "REVIEW_REQUIRED",
        "sources_total": len(sources), "unavailable_sources": len(unavailable),
        "expected_sources": len(expected_sources),
        "missing_source_rows": len(expected_sources - set(observed_sources)),
        "expected_events": len(expected_events),
        "missing_event_rows": len(expected_events - set(observed_events)),
        "source_coverage_complete": source_coverage_complete,
        "event_coverage_complete": event_coverage_complete,
        "unavailable_detail": [{"source_id": row.get("source_id"), "metric_key": row.get("metric_key"),
                                "status": row.get("status"), "error": row.get("last_error_code")}
                               for row in unavailable],
        "events_total": len(event_rows), "missing_consensus": missing_consensus,
        "missing_surprise": sum(row.get("surprise") is None for row in event_rows),
    }
    location = (health.get("bundle") or {}).get("location")
    expected_location = f"data_history/funnel/{target}/{run_id}"
    if location != expected_location:
        raise AuditError("funnel bundle location is not bound to this run")
    bundle = root / expected_location
    if bundle.is_symlink() or not bundle.is_dir():
        raise AuditError("funnel bundle is missing or symlinked")
    battery = _read(bundle / "candidate_battery.json")
    if battery.get("run_id") != run_id or battery.get("target_trade_date") != target:
        raise AuditError("candidate battery run_id/target is not the accepted run")
    rows = battery.get("results")
    if not isinstance(rows, list):
        raise AuditError("candidate battery results must be an array")
    queue = _read(bundle / "deep_research_queue.json")
    queue_rows = queue.get("ready_pool")
    if not isinstance(queue_rows, list) or len(queue_rows) != len(rows):
        raise AuditError("U4 review pool does not cover every battery candidate")
    red_flags = 0
    for row in queue_rows:
        if not isinstance(row, dict) or not isinstance(row.get("blocked_reasons"), list):
            raise AuditError("malformed U4 review row")
        has_red_flag = "E1_RED_FLAG_REQUIRES_SEPARATE_REVIEW" in row["blocked_reasons"]
        red_flags += has_red_flag
        if has_red_flag and row.get("ready") is True:
            raise AuditError("red-flag U4 row is marked ready")
    zero = 0
    partial = 0
    complete = 0
    not_started = 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("dims"), dict):
            raise AuditError("malformed candidate battery row")
        covered = (row.get("completeness") or {}).get("covered")
        if not isinstance(covered, int) or isinstance(covered, bool) or not 0 <= covered <= 6:
            raise AuditError("candidate battery completeness is malformed")
        if covered == 0:
            zero += 1
        elif covered < 6:
            partial += 1
        else:
            complete += 1
        if any(dim.get("err") == "BATCH_NOT_STARTED" for dim in row["dims"].values()
               if isinstance(dim, dict)):
            not_started += 1
    collection = health.get("battery_collection")
    if collection is not None and not isinstance(collection, dict):
        raise AuditError("funnel battery_collection is malformed")
    funnel = {
        "step": "funnel_finalize", "run_id": run_id, "target_trade_date": target,
        # governance-mutation: NIGHTLY_ACCEPTANCE_ZERO_DIMENSION_QUALITY
        "quality": "DATA_BLOCKED" if not rows or zero else "PARTIAL" if partial else "REVIEW_REQUIRED",
        "reported_status": health.get("status"),
        "candidate_count": len(rows), "complete_rows": complete, "partial_rows": partial,
        "zero_dimension_rows": zero, "batch_not_started": not_started,
        "red_flag_rows": red_flags,
        "by_board": (collection or {}).get("by_board"),
        "zero_row_reasons": (collection or {}).get("zero_row_reasons"),
        "degraded_channels": health.get("degraded_channels"),
    }
    return {"status": "OBSERVED_WITH_GAPS" if macro["quality"] == "DATA_BLOCKED"
            or funnel["quality"] != "REVIEW_REQUIRED"
            else "OBSERVED_REVIEW_REQUIRED", "run_id": run_id, "target_trade_date": target,
            "macro": macro, "funnel": funnel,
            "authority": "NO_U4_OR_PAPER_APPROVAL"}


def audit(inputs: nightly_acceptance.Inputs) -> dict:
    operational = nightly_acceptance.audit(inputs)
    result = {"schema": SCHEMA, "installed_repo_head": _installed_head(inputs.repo_root),
              "operational": operational, "research": {"status": "NOT_EVALUATED"}}
    if operational["status"] != "PASS":
        return result
    try:
        nightly = _read(inputs.repo_root / "experiments" / "execution_tracker" / "nightly_run.json")
        steps = summarize_steps(nightly.get("steps"))
        publication = validate_publication(inputs.repo_root, nightly["run_id"], inputs.expected_target)
        result["operational"]["checks"].extend([
            {"name": "all_24_steps", "status": "PASS", "evidence": steps},
            {"name": "double_pointer_and_manifest", "status": "PASS", "evidence": publication},
        ])
    except (AuditError, OSError, KeyError, TypeError, ValueError) as exc:
        result["operational"]["status"] = "FAIL"
        result["operational"]["checks"].append(
            {"name": "dual_sheet_binding", "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        return result
    try:
        result["research"] = summarize_research(inputs.repo_root, nightly["run_id"], inputs.expected_target)
    except (AuditError, OSError, KeyError, TypeError, ValueError) as exc:
        # governance-mutation: NIGHTLY_ACCEPTANCE_RESEARCH_RUN_SEPARATION
        result["research"] = {"status": "AUDIT_FAILED", "run_id": nightly["run_id"],
                              "error": f"{type(exc).__name__}: {exc}"}
    return result


def main() -> int:
    args = nightly_acceptance.parse_args()
    inputs = nightly_acceptance.Inputs(
        repo_root=args.repo_root.resolve(), expected_start=args.expected_start,
        expected_target=nightly_acceptance._date8(args.expected_target, "expected-target"),
        runs_before=args.launchctl_runs_before, log_path=args.log, alarm_path=args.alarm,
        plist_path=args.plist, launchd_label=args.launchd_label,
        launchctl_state_file=args.launchctl_state_file,
    )
    receipt = audit(inputs)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2))
    if receipt["operational"]["status"] != "PASS":
        return 1
    return 0 if receipt["research"]["status"] == "OBSERVED_REVIEW_REQUIRED" else 2


if __name__ == "__main__":
    sys.exit(main())
