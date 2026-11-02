"""Read-only expected-versus-observed release metadata; never an installer."""
from __future__ import annotations

from datetime import datetime
import re

import workbench_evidence as ev
from foundation_runtime import LABELS

NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
GIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
RELEASE_KEYS = {"schema", "release_id", "created_at", "target_code_sha",
                "target_source_tree_hash", "target_state_schemas", "repository_roles",
                "service_ids", "expected_inventory_hash"}


def _fail(code):
    raise ValueError("RECONCILIATION_" + code)


def _copy(value):
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 15000 or depth > 12:
            _fail("JSON_LIMIT")
        if type(item) is dict:
            if len(item) > 15000 or any(type(key) is not str or len(key) > 256 for key in item):
                _fail("JSON_INVALID")
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            if len(item) > 15000:
                _fail("JSON_LIMIT")
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str and len(item) > 256 * 1024:
            _fail("JSON_LIMIT")
        elif item is not None and type(item) not in {str, int, float, bool}:
            _fail("JSON_INVALID")
    try:
        raw = ev.canonical(value).encode()
    except (ValueError, OverflowError, RecursionError):
        _fail("JSON_INVALID")
    if len(raw) > 256 * 1024:
        _fail("JSON_LIMIT")
    return ev.parse(raw)


def _text(value, pattern):
    if type(value) is not str or not pattern.fullmatch(value):
        _fail("IDENTITY_INVALID")
    return value


def _time(value):
    if (type(value) is not str or len(value) > 40 or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value)):
        _fail("TIME_INVALID")
    try:
        if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            _fail("TIME_INVALID")
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            _fail("TIME_INVALID")
    except ValueError:
        _fail("TIME_INVALID")
    return stamp


def _names(values, limit):
    if type(values) is not list or not 0 < len(values) <= limit:
        _fail("SELECTION_INVALID")
    result = [_text(value, NAME) for value in values]
    if len(set(result)) != len(result):
        _fail("SELECTION_DUPLICATE")
    return sorted(result)


def _target(value):
    if type(value) is not dict or set(value) != RELEASE_KEYS or value["schema"] != "ar.release-target.v1":
        _fail("TARGET_INVALID")
    _text(value["release_id"], NAME)
    _time(value["created_at"])
    _text(value["target_code_sha"], GIT_SHA)
    _text(value["target_source_tree_hash"], HASH)
    _text(value["expected_inventory_hash"], HASH)
    _names(value["repository_roles"], 16)
    if value["service_ids"]:
        _names(value["service_ids"], 32)
    elif type(value["service_ids"]) is not list:
        _fail("SELECTION_INVALID")
    schemas = value["target_state_schemas"]
    if type(schemas) is not dict or not 1 <= len(schemas) <= 16:
        _fail("STATE_SCHEMAS_INVALID")
    for name, version in schemas.items():
        _text(name, NAME)
        if (type(version) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", version)):
            _fail("STATE_SCHEMAS_INVALID")
    return value


def _inventory(value):
    keys = {"schema", *LABELS, "observed_at", "observation_time_authority", "captured_at_utc",
            "repository_capture_scope", "read_only", "repositories", "services", "clocks",
            "remote_fetch_performed", "service_probe_performed", "deployment_authority"}
    if (type(value) is not dict or set(value) != keys or value["schema"] != "ar.runtime-inventory.v1"
            or value["read_only"] is not True or value["remote_fetch_performed"] is not False
            or value["service_probe_performed"] is not False or value["deployment_authority"] is not False
            or value["observation_time_authority"] != "CALLER_SUPPLIED"
            or value["repository_capture_scope"] != "CURRENT_LOCAL_READ_NOT_HISTORICAL_RECONSTRUCTION"
            or any(type(value[key]) is not type(expected) or value[key] != expected for key, expected in LABELS.items())):
        _fail("INVENTORY_INVALID")
    _time(value["observed_at"])
    _time(value["captured_at_utc"])
    repositories, services = value["repositories"], value["services"]
    if (type(repositories) is not list or len(repositories) > 16
            or type(services) is not list or len(services) > 32):
        _fail("INVENTORY_LIMIT")
    roles, identifiers = set(), set()
    for row in repositories:
        if type(row) is not dict:
            _fail("REPOSITORY_INVALID")
        role = _text(row.get("role"), NAME)
        if role in roles or row.get("service_code_binding") != "NOT_ATTESTED":
            _fail("REPOSITORY_CONFLICT")
        roles.add(role)
        for key in ("code_sha", "cached_main_sha"):
            if row.get(key) is not None:
                _text(row[key], GIT_SHA)
        if row.get("dirty") is not None and type(row["dirty"]) is not bool:
            _fail("REPOSITORY_INVALID")
        if row.get("remote_ref_scope") != "LOCAL_CACHED_NOT_FETCHED":
            _fail("REMOTE_SCOPE_INVALID")
        if row.get("consistency_scope") != "SEQUENTIAL_LOCAL_GIT_READS_NOT_ATOMIC":
            _fail("REPOSITORY_SCOPE_INVALID")
        if row.get("status") == "OBSERVED_LOCAL_ONLY" and (row.get("code_sha") is None or type(row.get("dirty")) is not bool):
            _fail("REPOSITORY_INVALID")
    for row in services:
        if type(row) is not dict:
            _fail("SERVICE_INVALID")
        identifier = _text(row.get("service_id"), NAME)
        role = row.get("repository_role")
        if (identifier in identifiers or role is not None and role not in roles
                or row.get("running_service_attestation") != "NOT_ATTESTED"
                or row.get("caller_observed_state") not in {"UNKNOWN", "RUNNING", "STOPPED", "FAILED"}):
            _fail("SERVICE_CONFLICT")
        identifiers.add(identifier)
        if row.get("caller_observed_code_sha") is not None:
            _text(row["caller_observed_code_sha"], GIT_SHA)
    return value


def reconcile_deployments(inventory, release):
    """Bind an explicit target to an exact inventory; never infer running code."""
    inventory, release = _inventory(_copy(inventory)), _target(_copy(release))
    inventory_hash = ev.sealed(inventory)
    if inventory_hash != release["expected_inventory_hash"]:
        _fail("INVENTORY_HASH_MISMATCH")
    repositories = {row["role"]: row for row in inventory["repositories"]}
    services = {row["service_id"]: row for row in inventory["services"]}
    rows, service_rows, blockers = [], [], []
    target_sha = release["target_code_sha"]
    for role in sorted(release["repository_roles"]):
        actual = repositories.get(role)
        if actual is None:
            status = "MISSING_OBSERVATION"
        elif actual.get("status") != "OBSERVED_LOCAL_ONLY" or actual.get("dirty") is None:
            status = "INCOMPLETE_OBSERVATION"
        elif actual["code_sha"] != target_sha:
            status = "CODE_DRIFT"
        elif actual["dirty"]:
            status = "DIRTY_WORKTREE"
        else:
            status = "LOCAL_METADATA_MATCH"
        if status != "LOCAL_METADATA_MATCH":
            blockers.append({"subject": role, "reason": status})
        cached = actual.get("cached_main_sha") if actual else None
        rows.append({"role": role, "comparison_status": status, "expected_code_sha": target_sha,
                     "observed_code_sha": actual.get("code_sha") if actual else None,
                     "observed_dirty": actual.get("dirty") if actual else None,
                     "cached_main_sha": cached, "remote_ref_scope": "LOCAL_CACHED_NOT_FETCHED",
                     "cached_main_relation": "UNKNOWN" if cached is None else "MATCH_CACHED_ONLY" if cached == target_sha else "CACHED_DRIFT",
                     "source_tree_hash": None, "source_tree_status": "NOT_OBSERVED",
                     "state_schemas": None, "state_schema_status": "NOT_OBSERVED"})
        blockers.extend({"subject": role, "reason": reason} for reason in
                        ("SOURCE_TREE_NOT_OBSERVED", "STATE_SCHEMA_NOT_OBSERVED"))
    for identifier in sorted(release["service_ids"]):
        actual = services.get(identifier)
        observed_sha = actual.get("caller_observed_code_sha") if actual else None
        if actual is None:
            status = "MISSING_SERVICE_OBSERVATION"
        elif actual.get("repository_role") not in release["repository_roles"]:
            status = "SERVICE_ROLE_OUTSIDE_TARGET"
        elif actual["caller_observed_state"] in {"STOPPED", "FAILED"}:
            status = "CALLER_REPORTED_NOT_RUNNING"
        elif observed_sha is not None and observed_sha != target_sha:
            status = "CALLER_REPORTED_CODE_DRIFT"
        else:
            status = "RUNNING_CODE_NOT_ATTESTED"
        service_rows.append({"service_id": identifier, "comparison_status": status,
                             "caller_observed_code_sha": observed_sha,
                             "running_service_attestation": "NOT_ATTESTED"})
        blockers.append({"subject": identifier, "reason": status})
    has_drift = any(row["comparison_status"] in {"CODE_DRIFT", "DIRTY_WORKTREE"} for row in rows)
    has_drift = has_drift or any(row["comparison_status"] in {
        "CALLER_REPORTED_CODE_DRIFT", "CALLER_REPORTED_NOT_RUNNING", "SERVICE_ROLE_OUTSIDE_TARGET"} for row in service_rows)
    metadata_match = all(row["comparison_status"] == "LOCAL_METADATA_MATCH" for row in rows)
    result = {"schema": "ar.deployment-reconciliation.v1", **LABELS, "deployment_authority": False,
              "release_id": release["release_id"], "release_hash": ev.sealed(release),
              "inventory_hash": inventory_hash, "inventory_observed_at": inventory["observed_at"],
              "inventory_captured_at_utc": inventory["captured_at_utc"],
              "temporal_scope": "EXACT_SAVED_INVENTORY_NOT_CURRENT_RUNTIME",
              "expected_source_tree_hash": release["target_source_tree_hash"],
              "expected_state_schemas": release["target_state_schemas"],
              "comparison_status": "DRIFT" if has_drift else "LOCAL_METADATA_MATCH_RUNTIME_UNVERIFIED" if metadata_match else "INCOMPLETE",
              "deployment_readiness": "BLOCKED_UNVERIFIED", "repositories": rows, "services": service_rows,
              "blockers": blockers, "mutation_performed": False,
              "acceptance_evidence": "NOT_SUPPLIED_OR_VERIFIED", "rollback_evidence": "NOT_SUPPLIED_OR_VERIFIED",
              "approval": "NOT_SUPPLIED_OR_VERIFIED", "remote_freshness": "NOT_VERIFIED"}
    result["reconciliation_hash"] = ev.sealed(result)
    return result
