"""Bounded, read-only observations of an explicitly configured local AR root.

This is an observation catalog, not a publication verifier or a U4 authority.
Missing manifests and stale data remain visible, including when payloads say OK.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

PUBLIC = (
    "model_portfolio_state.json", "trade_cards.json", "rotation_panel.json",
    "feature_store_health.json", "funnel_health.json", "funnel_stage_candidates.json",
    "funnel_stage_battery.json", "macro_gate.json", "meta.json",
    "macro/macro_panel.json", "macro/macro_state.json", "macro/macro_events.json",
    "macro/source_health.json", "macro/portfolio_macro_exposure.json",
    "macro/macro_risk_gate.json",
)
BUNDLE = ("manifest.json", "candidate_review.json", "candidate_manifest.json",
          "candidate_battery.json", "deep_research_queue.json")
MAX_FILE = 12 * 1024 * 1024
ID = r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}"


class EvidenceError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def sealed(value):
    return sha(canonical(value).encode())


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_local(root: Path, relative: str):
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or any(x in {"..", "."} for x in parts):
        raise EvidenceError("SOURCE_PATH_INVALID")
    # Open every component without following links. The configured root is
    # trusted by the launcher; paths obtained from artifacts are not trusted.
    flags = os.O_RDONLY | os.O_NOFOLLOW
    fd = os.open(root, flags | os.O_DIRECTORY)
    try:
        for component in parts[:-1]:
            new = os.open(component, flags | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = new
        file_fd = os.open(parts[-1], flags, dir_fd=fd)
        with os.fdopen(file_fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE:
                raise EvidenceError("SOURCE_SIZE_OR_TYPE_INVALID")
            raw = stream.read(MAX_FILE + 1)
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or len(raw) > MAX_FILE:
                raise EvidenceError("SOURCE_CHANGED_DURING_READ")
            return raw
    finally:
        os.close(fd)


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise EvidenceError("DUPLICATE_SOURCE_KEY")
            if re.fullmatch(r"(?i)(api_?key|access_?token|secret|password|authorization)", key) and value:
                raise EvidenceError("SECRET_SHAPED_SOURCE_FIELD_REFUSED")
            result[key] = value
        return result

    def constant(_value):
        raise EvidenceError("NONFINITE_SOURCE_VALUE")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict):
        raise EvidenceError("SOURCE_OBJECT_REQUIRED")
    return value


def freshness(date, now):
    if not isinstance(date, str) or not re.fullmatch(r"\d{8}", date):
        return {"status": "UNKNOWN", "calendar_age_days": None}
    try:
        current = datetime.fromisoformat(now)
        if current.tzinfo is None:
            raise ValueError("aware observation time required")
        age = (current.astimezone(timezone(timedelta(hours=8))).date() - datetime.strptime(date, "%Y%m%d").date()).days
    except ValueError:
        return {"status": "UNKNOWN", "calendar_age_days": None}
    return {"status": "FUTURE" if age < 0 else "STALE" if age > 3 else "RECENT_CALENDAR_ONLY",
            "calendar_age_days": age}


def capture(root: Path, now=None):
    now = now or utc_now()
    records, issues = {}, []

    def take(path, expected=None):
        try:
            raw = read_local(root, path)
            value = parse(raw)
            actual = sha(raw)
            binding = "UNBOUND" if not expected else "MATCH" if actual == expected.removeprefix("sha256:") else "MISMATCH"
            records[path] = {"status": "OBSERVED", "source_sha256": actual, "binding": binding, "payload": value}
            if binding == "MISMATCH":
                issues.append({"path": path, "reason": "HASH_MISMATCH"})
            return value
        except (OSError, ValueError, TypeError):
            records[path] = {"status": "MISSING_OR_INVALID", "binding": "UNVERIFIED", "payload": None, "source_sha256": None}
            issues.append({"path": path, "reason": "MISSING_OR_INVALID"})
            return {}

    pointer_path = "public/data/v2/current_run.json"
    pointer = take(pointer_path)
    rid = pointer.get("run_id")
    hashes = pointer.get("artifacts") if isinstance(pointer.get("artifacts"), dict) else {}
    manifest = {}
    if isinstance(rid, str) and re.fullmatch(ID, rid):
        path = f"public/data/v2/runs/{rid}/manifest.json"
        if pointer.get("manifest_path") == f"runs/{rid}/manifest.json":
            manifest = take(path, pointer.get("manifest_sha256"))
        else:
            issues.append({"path": pointer_path, "reason": "MANIFEST_PATH_BINDING_INVALID"})
    else:
        issues.append({"path": pointer_path, "reason": "RUN_ID_INVALID"})
    for name in PUBLIC:
        take("public/data/v2/" + name, hashes.get("public:" + name))
    health = records["public/data/v2/funnel_health.json"]["payload"] or {}
    bundle = health.get("bundle") or {}
    location = bundle.get("location")
    date = health.get("as_of")
    if (isinstance(date, str) and re.fullmatch(r"\d{8}", date) and isinstance(rid, str)
            and re.fullmatch(ID, rid) and health.get("run_id") == rid
            and location == f"data_history/funnel/{date}/{rid}"):
        bundle_hashes = bundle.get("artifacts") or {}
        for name in BUNDLE:
            take(location + "/" + name, bundle_hashes.get(name))
    else:
        issues.append({"path": "public/data/v2/funnel_health.json", "reason": "BUNDLE_LOCATION_BINDING_INVALID"})
    # Only operational fields are retained; stdout/tails can contain secrets.
    attempt_path = "experiments/execution_tracker/nightly_run.json"
    attempt = take(attempt_path)
    if attempt:
        records[attempt_path]["payload"] = {k: attempt.get(k) for k in (
            "run_id", "target_trade_date", "generated_at", "report", "data_quality", "research_data_quality", "published")}
        records[attempt_path]["payload"]["steps"] = [{k: row.get(k) for k in (
            "step", "status", "exit_code", "elapsed_sec", "blocks_publication")} for row in attempt.get("steps", []) if isinstance(row, dict)]
        records[attempt_path]["projection"] = "OPERATIONAL_FIELDS_ONLY"
    try:
        if sha(read_local(root, pointer_path)) != records[pointer_path]["source_sha256"]:
            raise EvidenceError("PUBLIC_POINTER_CHANGED_DURING_CAPTURE")
    except OSError:
        raise EvidenceError("PUBLIC_POINTER_UNAVAILABLE_AFTER_CAPTURE") from None
    payload = {
        "schema": "ar-workbench-observation.v1", "observed_at": now,
        "source_mode": "LOCAL_READ_ONLY", "sample_purpose": "WORKFLOW_DEBUG",
        "formal_authority": False, "production_write": False,
        "published_run_id": rid, "target_trade_date": pointer.get("target_trade_date"),
        "publication_verified": False,
        "verification_scope": "FILE_HASH_OBSERVATION_NOT_FULL_PUBLICATION_ACCEPTANCE",
        "manifest_available": bool(manifest), "issues": issues, "records": records,
    }
    payload["snapshot_hash"] = sealed(payload)
    return payload


def verify(snapshot):
    expected = sealed({k: v for k, v in snapshot.items() if k != "snapshot_hash"})
    if expected != snapshot.get("snapshot_hash"):
        raise EvidenceError("OBSERVATION_HASH_MISMATCH")
    if snapshot.get("formal_authority") is not False or snapshot.get("production_write") is not False:
        raise EvidenceError("OBSERVATION_AUTHORITY_INVALID")
    return snapshot


def research_quality(snapshot):
    records = snapshot["records"]
    run_id = snapshot.get("published_run_id")
    target = snapshot.get("target_trade_date")
    blocked = {"status": "NOT_EVALUATED", "run_id": run_id,
               "formal_authority": False}
    if not isinstance(run_id, str) or not re.fullmatch(ID, run_id) or not isinstance(target, str) or not re.fullmatch(r"\d{8}", target):
        return {**blocked, "reason": "PUBLISHED_RUN_BINDING_INVALID"}
    base = "public/data/v2/"
    bundle = f"data_history/funnel/{target}/{run_id}/"
    paths = {
        "publication": base + f"runs/{run_id}/manifest.json",
        "health": base + "funnel_health.json",
        "sources": base + "macro/source_health.json",
        "events": base + "macro/macro_events.json",
        "manifest": bundle + "candidate_manifest.json",
        "battery": bundle + "candidate_battery.json",
    }
    # governance-mutation: WORKBENCH_QUALITY_SOURCE_BINDING
    if any(records.get(path, {}).get("binding") != "MATCH" or
           records[path].get("status") != "OBSERVED" for path in paths.values()):
        return {**blocked, "reason": "MISSING_OR_UNBOUND_SOURCE"}
    payloads = {name: records[path]["payload"] for name, path in paths.items()}
    health, manifest, battery = (payloads[name] for name in ("health", "manifest", "battery"))
    if not isinstance(health.get("bundle"), dict):
        return {**blocked, "reason": "ROW_SHAPE_INVALID"}
    if (health.get("run_id") != run_id or health.get("as_of") != target
            or health["bundle"].get("location") != bundle[:-1]
            or manifest.get("run_id") != run_id or manifest.get("as_of") != target
            or battery.get("run_id") != run_id or battery.get("as_of") != target
            or battery.get("target_trade_date", target) != target
            or payloads["events"].get("run_id") != run_id):
        return {**blocked, "reason": "RUN_BINDING_INVALID"}
    source_rows = payloads["sources"].get("data")
    event_rows = payloads["events"].get("data")
    rows = battery.get("results")
    codes = manifest.get("ts_codes")
    if (not isinstance(source_rows, list) or not isinstance(event_rows, list)
            or not isinstance(rows, list) or not isinstance(codes, list)
            or any(not isinstance(row, dict) for row in (*source_rows, *event_rows, *rows))):
        return {**blocked, "reason": "ROW_SHAPE_INVALID"}
    observed_codes = [row.get("ts_code") for row in rows]
    if (any(not isinstance(code, str) for code in (*codes, *observed_codes))
            or len(codes) != len(set(codes)) or len(observed_codes) != len(set(observed_codes))
            or set(codes) != set(observed_codes)):
        return {**blocked, "reason": "COVERAGE_SET_INVALID"}
    dimensions = {"行情", "资金", "基本面", "技术面", "消息面", "估值"}
    coverage = {"complete": 0, "partial": 0, "zero": 0}
    not_started = 0
    for row in rows:
        dims = row.get("dims")
        if (not isinstance(dims, dict) or set(dims) != dimensions
                or any(not isinstance(value, dict) or not value for value in dims.values())):
            return {**blocked, "reason": "ROW_SHAPE_INVALID"}
        if any(value.get("status") not in {None, "DATA_BLOCKED", "NOT_RUN"}
               for value in dims.values()):
            return {**blocked, "reason": "ROW_SHAPE_INVALID"}
        missing = [name for name, value in dims.items()
                   if value.get("status") in {"DATA_BLOCKED", "NOT_RUN"}]
        if any(not str(dims[name].get("err") or "").strip() for name in missing):
            return {**blocked, "reason": "ROW_SHAPE_INVALID"}
        derived = 6 - len(missing)
        stamp = row.get("completeness")
        if not isinstance(stamp, dict):
            return {**blocked, "reason": "ROW_SHAPE_INVALID"}
        reported_missing = stamp.get("missing")
        if (not isinstance(reported_missing, list)
                or any(not isinstance(name, str) for name in reported_missing)
                or len(reported_missing) != len(missing)
                or set(reported_missing) != set(missing)):
            # governance-mutation: WORKBENCH_QUALITY_MISSING_LIST
            return {**blocked, "reason": "SELF_REPORTED_COMPLETENESS_MISMATCH"}
        # governance-mutation: WORKBENCH_QUALITY_DERIVE_COVERAGE
        if (stamp.get("covered") != derived or stamp.get("of") != 6
                or stamp.get("verdict") != ("COMPLETE" if derived == 6 else "PARTIAL")):
            return {**blocked, "reason": "SELF_REPORTED_COMPLETENESS_MISMATCH"}
        coverage["zero" if derived == 0 else "partial" if derived < 6 else "complete"] += 1
        not_started += any(dims[name].get("err") == "BATCH_NOT_STARTED" for name in missing)
    if not source_rows or not event_rows:
        return {**blocked, "reason": "EMPTY_MACRO_EVIDENCE"}
    if any(not isinstance(row.get("status"), str) or not isinstance(row.get("source_id"), str)
           for row in source_rows):
        return {**blocked, "reason": "ROW_SHAPE_INVALID"}
    code_root = Path(__file__).resolve().parents[2]
    if str(code_root) not in sys.path:
        sys.path.insert(0, str(code_root))
    try:
        from experiments.macro_os import collectors, contracts, m1a
        registry = contracts.load_json(contracts.SOURCE_REGISTRY)
        contracts.validate_source_registry(registry)
        rules = m1a.load_rules()
        expected_sources = {
            (spec.source_id, metric.series_id, metric.metric_key)
            for spec in collectors.collection_plan() for metric in spec.metrics
        }
        expected_events = {
            f"{rule['source_id']}:{rule['series_id']}:{rule['metric_key']}"
            for region in rules["regions"].values() for rule in region
        }
    except (ImportError, OSError, RuntimeError, ValueError, KeyError, TypeError):
        return {**blocked, "reason": "MACRO_CONTRACT_UNAVAILABLE"}
    # governance-mutation: WORKBENCH_QUALITY_MACRO_CONTRACT_BINDING
    if (payloads["sources"].get("source_registry_hash") != registry["registry_hash"]
            or payloads["events"].get("rules_hash") != rules["rules_hash"]):
        return {**blocked, "reason": "MACRO_CONTRACT_MISMATCH"}
    observed_sources = [
        (row.get("source_id"), row.get("series_id"), row.get("metric_key"))
        for row in source_rows
    ]
    observed_events = [row.get("context_id") for row in event_rows]
    try:
        source_set, event_set = set(observed_sources), set(observed_events)
    except TypeError:
        return {**blocked, "reason": "ROW_SHAPE_INVALID"}
    source_coverage_complete = (
        len(observed_sources) == len(expected_sources) and source_set == expected_sources
    )
    event_coverage_complete = (
        len(observed_events) == len(expected_events) and event_set == expected_events
    )
    unavailable = [row for row in source_rows if row["status"] != "OK"]
    missing_consensus = sum(row.get("consensus") is None or
                            row.get("consensus_status") == "DATA_BLOCKED" for row in event_rows)
    # governance-mutation: WORKBENCH_QUALITY_ACTUAL_STATUS
    actual_blocked = sum(row.get("actual_status") != "AVAILABLE" for row in event_rows)
    return {
        "status": "BOUND_OBSERVATION_ONLY", "run_id": run_id,
        "target_trade_date": target, "formal_authority": False,
        # governance-mutation: WORKBENCH_QUALITY_MACRO_UNIVERSE
        "gaps_present": bool(not source_coverage_complete or not event_coverage_complete
                             or unavailable or missing_consensus or actual_blocked or coverage["partial"] or coverage["zero"]),
        "macro": {
            "sources_total": len(source_rows), "unavailable_sources": len(unavailable),
            "missing_consensus": missing_consensus, "events_total": len(event_rows),
            "actual_blocked_events": actual_blocked,
            "expected_sources": len(expected_sources),
            "missing_source_rows": len(expected_sources - source_set),
            "source_coverage_complete": source_coverage_complete,
            "expected_events": len(expected_events),
            "missing_event_rows": len(expected_events - event_set),
            "event_coverage_complete": event_coverage_complete,
            "unavailable_detail": [
                {"source_id": row["source_id"], "metric_key": row.get("metric_key"),
                 "status": row["status"], "reason": row.get("last_error_code")}
                for row in unavailable
            ],
        },
        "funnel": {"candidate_count": len(rows), "coverage": coverage,
                   "batch_not_started": not_started},
    }


def view(snapshot, now=None):
    verify(snapshot)
    records = snapshot["records"]

    def artifact(name):
        return records.get("public/data/v2/" + name, {})

    def value(name):
        return artifact(name).get("payload") or {}

    candidate = next((r.get("payload") or {} for p, r in records.items() if p.endswith("/candidate_review.json")), {})
    portfolio = value("model_portfolio_state.json").get("data") or {}
    # Historical P&L is descriptive. No win rate, alpha, or methodology claim.
    paper = {k: portfolio.get(k) for k in ("paper_only", "cash", "initial_capital", "nav_latest", "nav_series", "open_positions", "closed_trades", "closed_trades_n", "win_rate_note")}
    result = {k: snapshot[k] for k in ("snapshot_hash", "observed_at", "published_run_id", "target_trade_date", "issues", "publication_verified", "manifest_available")}
    result.update({
        "freshness": freshness(snapshot.get("target_trade_date"), now or utc_now()),
        "attempt": (records.get("experiments/execution_tracker/nightly_run.json", {}).get("payload") or {}),
        "funnel": value("funnel_health.json"), "feature": value("feature_store_health.json"),
        "research_quality": research_quality(snapshot),
        "macro": {name: artifact("macro/" + name + ".json") for name in ("macro_panel", "macro_state", "macro_events", "source_health", "portfolio_macro_exposure", "macro_risk_gate")},
        "macro_legacy": value("macro_gate.json"),
        "candidates": candidate.get("rows", []), "candidate_coverage": candidate.get("coverage", {}),
        "paper": paper, "rotation": value("rotation_panel.json").get("data", {}),
        "files": [{"path": path, **{k: row.get(k) for k in ("status", "source_sha256", "binding")}} for path, row in records.items()],
    })
    return result
