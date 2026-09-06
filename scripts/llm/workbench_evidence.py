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
        "macro": {name: artifact("macro/" + name + ".json") for name in ("macro_panel", "macro_state", "macro_events", "source_health", "portfolio_macro_exposure", "macro_risk_gate")},
        "macro_legacy": value("macro_gate.json"),
        "candidates": candidate.get("rows", []), "candidate_coverage": candidate.get("coverage", {}),
        "paper": paper, "rotation": value("rotation_panel.json").get("data", {}),
        "files": [{"path": path, **{k: row.get(k) for k in ("status", "source_sha256", "binding")}} for path, row in records.items()],
    })
    return result
