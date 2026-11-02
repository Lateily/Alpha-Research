"""Read-only health and non-dispatching backfill projections."""
from __future__ import annotations

from collections import defaultdict
import hashlib

from .catalog import aware_time, canonical, catalog_hash, valid_date
from .call_receipts import validate_receipt

SEVERITY = {"OK": 0, "NOT_RUN": 1, "STALE": 2, "SOURCE_DOWN": 3,
            "PARAM_ERROR": 4, "DATA_BLOCKED": 5}


def _state(row, target):
    if row["status"] == "INTERRUPTED":
        return "DATA_BLOCKED", "INTERRUPTED"
    if row["status"] == "FAILED":
        code = row["error_code"]
        return ({"SOURCE_DOWN": "SOURCE_DOWN", "PARAM_ERROR": "PARAM_ERROR"}.get(code, "DATA_BLOCKED"), code)
    if not row["rows"]:
        return "DATA_BLOCKED", "EMPTY_REQUIRED"
    if row["context"]["ts_code"] is not None and row["target_rows"] > 1:
        return "DATA_BLOCKED", "AMBIGUOUS_TARGET_ROW"
    if row["missing_date_rows"] or row["last_date"] is None:
        return "DATA_BLOCKED", "MISSING_DATE"
    # governance-mutation: DG_SOURCE_TARGET_DATE
    if row["last_date"] > target:
        return "DATA_BLOCKED", "FUTURE_DATE"
    if row["last_date"] < target:
        return "STALE", "TARGET_ROW_MISSING"
    if not row["target_rows"]:
        return "DATA_BLOCKED", "TARGET_ROW_MISSING"
    return "OK", None


def _worst(states):
    return max(states, key=lambda s: (SEVERITY[s[0]], s[1] or ""))


def evaluate_health(catalog, receipts, *, target_trade_date):
    target = valid_date(target_trade_date)
    digest = catalog_hash(catalog)
    if not isinstance(receipts, list) or len(receipts) > 2000:
        raise ValueError("INVALID_RECEIPT_SET")
    unique = {}
    for row in receipts:
        validate_receipt(row)
        if row["context"]["catalog_hash"] != digest:
            raise ValueError("CATALOG_HASH_MISMATCH")
        identifier = row["context"]["logical_call_id"]
        if identifier in unique and canonical(unique[identifier]) != canonical(row):
            raise ValueError("DUPLICATE_CALL_CONFLICT")
        unique[identifier] = row
    groups = defaultdict(list)
    outside = 0
    for row in unique.values():
        ctx = row["context"]
        if ctx["target_trade_date"] != target:
            outside += 1
            continue
        groups[(ctx["source_id"], ctx["collector_run_id"], ctx["ts_code"])].append(row)
    sources = {}
    for source_id, source in sorted(catalog["sources"].items()):
        scopes = []
        for (identifier, run, ticker), rows in groups.items():
            if identifier != source_id:
                continue
            latest = max(aware_time(r["context"]["invoked_at"]) for r in rows)
            current = [r for r in rows if aware_time(r["context"]["invoked_at"]) == latest]
            status, reason = _worst([_state(row, target) for row in current])
            failed = [r for r in rows if _state(r, target)[0] != "OK" and r["status"] != "INTERRUPTED"]
            scopes.append({"collector_run_id": run, "ts_code": ticker,
                           "target_trade_date": target, "status": status, "reason": reason,
                           "attempt_ids": sorted(r["context"]["logical_call_id"] for r in failed),
                           "evidence_refs": sorted("call:" + r["context"]["logical_call_id"] for r in rows),
                           "latest_invoked_at": latest.isoformat(),
                           "downstream": (["official_sample"] if source_id in
                                          {"tushare.daily", "tushare.moneyflow_dc"} else [])})
        scopes.sort(key=lambda s: (s["collector_run_id"], s["ts_code"] or ""))
        status = _worst([(s["status"], s["reason"]) for s in scopes])[0] if scopes else "NOT_RUN"
        reason = None if scopes else ("NOT_INSTRUMENTED" if source["instrumentation"] == "NOT_INSTRUMENTED" else "NO_RECEIPTS")
        sources[source_id] = {"status": status, "reason": reason, "scopes": scopes,
                              "instrumentation": source["instrumentation"],
                              "rights_status": source["rights_status"]}
    return {"schema": "ar.data-governance-health.v1", "catalog_hash": digest,
            "target_trade_date": target, "coverage": "OBSERVED_CALLS_ONLY",
            "status": "OK" if all(s["status"] == "OK" for s in sources.values()) else "PARTIAL",
            "out_of_scope_calls": outside, "sources": sources,
            "evidence_grade": "WORKFLOW_DEBUG", "human_review": "PENDING",
            "production_write_allowed": False}


def plan_backfills(health, *, now, max_attempts=2):
    if (not isinstance(health, dict) or health.get("schema") != "ar.data-governance-health.v1"
            or type(max_attempts) is not int or not 1 <= max_attempts <= 2):
        raise ValueError("INVALID_BACKFILL_INPUT")
    aware_time(now.isoformat())
    target = valid_date(health["target_trade_date"])
    gaps = {}
    for source_id, source in sorted(health["sources"].items()):
        scopes = source["scopes"] or [{"ts_code": None, "status": source["status"],
                                       "reason": source["reason"], "attempt_ids": [], "evidence_refs": []}]
        for scope in scopes:
            if scope["status"] == "OK":
                continue
            identity = {"source_id": source_id, "target_trade_date": target, "ts_code": scope["ts_code"]}
            gap_id = hashlib.sha256(canonical(identity)).hexdigest()
            gap = gaps.setdefault(gap_id, dict(identity, gap_id=gap_id, reasons=set(),
                                               attempt_ids=set(), evidence_refs=set()))
            gap["reasons"].add(scope["reason"])
            gap["attempt_ids"].update(scope["attempt_ids"])
            gap["evidence_refs"].update(scope["evidence_refs"])
    plans = []
    for gap in gaps.values():
        attempts = len(gap.pop("attempt_ids"))
        reasons = gap.pop("reasons")
        if "PERMISSION_DENIED" in reasons:
            status = "BLOCKED_PERMISSION"
        elif "INTERRUPTED" in reasons:
            status = "BLOCKED_RECONCILIATION"
        elif reasons & {"FUTURE_DATE", "MISSING_DATE", "INVALID_RESPONSE", "PARAM_ERROR", "AMBIGUOUS_TARGET_ROW"}:
            status = "BLOCKED_EVIDENCE"
        elif reasons & {"NOT_INSTRUMENTED", "NO_RECEIPTS"}:
            status = "BLOCKED_NOT_INSTRUMENTED"
        elif attempts >= max_attempts:
            status = "EXHAUSTED"
        else:
            status = "PLANNED_NOT_DISPATCHABLE"
        # governance-mutation: DG_BACKFILL_NO_DISPATCH
        plans.append(dict(gap, reason=sorted(reasons), attempts_seen=attempts,
                          evidence_refs=sorted(gap["evidence_refs"]), max_attempts=max_attempts,
                          next_eligible_at=None, status=status, dispatch_allowed=False))
    return sorted(plans, key=lambda p: p["gap_id"])
