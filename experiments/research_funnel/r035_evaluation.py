#!/usr/bin/env python3
"""R-035 offline evaluation for the all-market research funnel.

The evaluator reads one immutable U0-U4 bundle, the same-day U3 battery, and
the local R-008 feature-store SQLite snapshot. It never fetches data, mutates
the source bundle, selects U4 names, registers signals, or emits trade actions.

Two tests remain separate by construction:

* U1/U2 discovery: MAIN_CHANNEL candidates vs the same-batch RANDOM_CONTROL;
* U3 separation: battery pass vs battery non-pass among non-control candidates.

Every security uses the U2 as-of settled close as t0 and close * adj_factor at
T+1/T+3/T+5/T+10. Missing target-day bars use the last available settled bar
at or before the target and are explicitly TRUNCATED. Statistical values are
descriptive while prospective causal-cluster governance remains unavailable;
claim_allowed is therefore always false in this v1 contract.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

import funnel_pipeline as fp
import feature_store as feature_store_contract


SCHEMA = "ar.research_funnel_evaluation"
SCHEMA_VERSION = "1.0"
RULE_VERSION = "r035_aligned_return_v1"
HORIZONS = (1, 3, 5, 10)
HORIZON_KEYS = tuple(f"T+{value}" for value in HORIZONS)
PRIMARY_HORIZON = "T+5"
MIN_GROUP_N = 30
TEST_METHOD = "MANN_WHITNEY_U_TWO_SIDED_TIE_CORRECTED_NO_CONTINUITY/v1"
PRICE_BASIS = "raw_daily.close*raw_adj_factor.adj_factor"
DISCLAIMER = "不是买卖指令；研究信号，human executes."

U12_GROUPS = ("MAIN_CANDIDATE", "RANDOM_CONTROL")
U3_GROUPS = ("BATTERY_PASS", "BATTERY_NON_PASS")
RETURN_STATUSES = {"SETTLED", "TRUNCATED", "WINDOW_OPEN"}


class EvaluationError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise EvaluationError(f"duplicate JSON key: {key}")
        output[key] = value
    return output


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise EvaluationError(f"refusing symlinked JSON input: {path}")
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"cannot read strict JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvaluationError(f"JSON root must be an object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise EvaluationError(f"cannot hash {path}: {exc}") from exc


def _load_bundle(bundle_dir: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if bundle_dir.is_symlink() or not bundle_dir.is_dir():
        raise EvaluationError(f"bundle must be a real directory: {bundle_dir}")
    names = (
        "all_market_scan.json",
        "candidate_review.json",
        "deep_research_queue.json",
        "security_registry_projected.json",
    )
    manifest = _load_json(bundle_dir / "manifest.json")
    if (
        manifest.get("schema") != "ar.research_funnel_bundle"
        or manifest.get("schema_version") != fp.SCHEMA_VERSION
    ):
        raise EvaluationError("funnel bundle schema/version mismatch")
    declared = manifest.get("artifacts")
    if not isinstance(declared, dict) or set(declared) != set(names):
        raise EvaluationError("funnel bundle artifact set is incomplete")
    measured = {name: _sha256_file(bundle_dir / name) for name in names}
    # governance-mutation: R035_BUNDLE_HASH_BINDING
    if declared != measured or manifest.get("bundle_hash") != _hash(declared):
        raise EvaluationError("funnel bundle manifest or artifact hash drift")
    payloads = {name: _load_json(bundle_dir / name) for name in names}
    scan = payloads["all_market_scan.json"]
    candidates = payloads["candidate_review.json"]
    registry = payloads["security_registry_projected.json"]
    try:
        fp.validate_candidate_review(candidates, registry, scan)
    except Exception as exc:
        raise EvaluationError(f"candidate bundle contract failed: {exc}") from exc
    if manifest.get("as_of") != candidates.get("as_of"):
        raise EvaluationError("bundle manifest and candidate as_of differ")
    # governance-mutation: R035_CANDIDATE_OUTCOME_BLIND
    if any(row.get("aligned_return") is not None for row in candidates["rows"]):
        raise EvaluationError("candidate bundle already contains outcome data")
    return manifest, payloads


def _battery_rows(payload: Mapping[str, Any], as_of: str) -> dict[str, dict[str, Any]]:
    try:
        return fp._battery_rows(payload, as_of)
    except Exception as exc:
        raise EvaluationError(f"battery contract failed: {exc}") from exc


def _candidate_groups(
    candidate_review: Mapping[str, Any], battery: Mapping[str, Any]
) -> tuple[str, list[dict[str, Any]], list[str]]:
    as_of = fp._date8(str(candidate_review.get("as_of") or ""))
    frame = candidate_review.get("control_sampling_frame") or {}
    batch_id = str(frame.get("control_batch_id") or "")
    # governance-mutation: R035_CONTROL_FRAME_BINDING
    if batch_id != f"CTRL_{as_of}_v1":
        raise EvaluationError("control batch is not bound to the candidate as_of")
    battery_by_code = _battery_rows(battery, as_of)
    output: list[dict[str, Any]] = []
    missing_battery: list[str] = []
    for source in candidate_review["rows"]:
        status = source.get("review_status")
        if status == "EXCLUDED_RED_FLAG":
            continue
        if status == "MAIN_CHANNEL":
            u12_group = "MAIN_CANDIDATE"
        elif status == "RANDOM_CONTROL":
            u12_group = "RANDOM_CONTROL"
            if source.get("control_batch_id") != batch_id:
                raise EvaluationError("random control row crosses control batches")
        else:
            u12_group = None

        u3_group = None
        u3_reason = None
        if status != "RANDOM_CONTROL":
            battery_row = battery_by_code.get(source["ts_code"])
            if battery_row is None:
                missing_battery.append(source["ts_code"])
                u3_reason = "BATTERY_NOT_OBSERVED"
            else:
                completeness = battery_row.get("completeness") or {}
                passed = (
                    completeness.get("verdict") == "COMPLETE"
                    and "RED_FLAG" not in source.get("flags", [])
                )
                u3_group = "BATTERY_PASS" if passed else "BATTERY_NON_PASS"
                u3_reason = (
                    "COMPLETE_AND_NO_RED_FLAG"
                    if passed else "INCOMPLETE_OR_RED_FLAG"
                )
        if u12_group is not None or u3_group is not None:
            output.append({
                "ts_code": source["ts_code"],
                "industry_key": source.get("industry_key"),
                "stratum": source.get("stratum"),
                "control_batch_id": batch_id,
                "u1_u2_group": u12_group,
                "u3_group": u3_group,
                "u3_group_reason": u3_reason,
            })
    if not any(row["u1_u2_group"] == "MAIN_CANDIDATE" for row in output):
        raise EvaluationError("U1/U2 test has no main candidates")
    if not any(row["u1_u2_group"] == "RANDOM_CONTROL" for row in output):
        raise EvaluationError("U1/U2 test has no random controls")
    output.sort(key=lambda row: row["ts_code"])
    return batch_id, output, sorted(missing_battery)


def _open_feature_store(path: Path) -> sqlite3.Connection:
    if path.is_symlink() or not path.is_file():
        raise EvaluationError(f"feature store must be a real file: {path}")
    try:
        uri_path = quote(str(path.resolve()), safe="/")
        conn = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        required = {
            "store_meta",
            "source_batches",
            *feature_store_contract.RAW_TABLES.values(),
        }
        actual = {
            str(row[0]) for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not required.issubset(actual):
            raise EvaluationError(f"feature store lacks required tables: {sorted(required - actual)}")
        schema_row = conn.execute(
            "SELECT value FROM store_meta WHERE key='schema_version'"
        ).fetchone()
        if (
            schema_row is None
            or str(schema_row[0]) != feature_store_contract.STORE_SCHEMA_VERSION
        ):
            raise EvaluationError("feature store schema version is missing or unsupported")
        return conn
    except (sqlite3.Error, EvaluationError):
        if "conn" in locals():
            conn.close()
        raise


def _aligned_returns(
    feature_db: Path, as_of: str, grouped_rows: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    codes = sorted({str(row["ts_code"]) for row in grouped_rows})
    conn = _open_feature_store(feature_db)
    try:
        batch_rows = [
            dict(source) for source in conn.execute(
            "SELECT * FROM source_batches "
            "WHERE trade_date>=? ORDER BY trade_date,endpoint",
            (as_of,),
            )
        ]
        endpoints_by_date: dict[str, set[str]] = {}
        for source in batch_rows:
            trade_date = fp._date8(str(source["trade_date"]))
            endpoints_by_date.setdefault(trade_date, set()).add(str(source["endpoint"]))
        required_endpoints = set(feature_store_contract.ENDPOINT_FIELDS)
        # governance-mutation: R035_ATOMIC_SOURCE_BATCH
        partial_dates = sorted(
            date for date, endpoints in endpoints_by_date.items()
            if endpoints != required_endpoints
        )
        if partial_dates:
            raise EvaluationError(f"feature store contains partial source batches: {partial_dates}")
        sessions = sorted(endpoints_by_date)
        if not sessions or sessions[0] != as_of or len(sessions) != len(set(sessions)):
            raise EvaluationError("feature store lacks a unique settled t0 daily batch")
        max_index = min(max(HORIZONS), len(sessions) - 1)
        last_session = sessions[max_index]
        placeholders = ",".join("?" for _ in codes)
        query = (
            "SELECT d.ts_code,d.trade_date,d.close,a.adj_factor "
            "FROM raw_daily d JOIN raw_adj_factor a USING(ts_code,trade_date) "
            f"WHERE d.ts_code IN ({placeholders}) AND d.trade_date BETWEEN ? AND ? "
            "ORDER BY d.ts_code,d.trade_date"
        )
        evidence: list[dict[str, Any]] = []
        by_code: dict[str, list[dict[str, Any]]] = {code: [] for code in codes}
        for source in conn.execute(query, (*codes, as_of, last_session)):
            close = float(source["close"])
            factor = float(source["adj_factor"])
            adjusted = close * factor
            if not (math.isfinite(adjusted) and adjusted > 0):
                raise EvaluationError(f"invalid adjusted close for {source['ts_code']}")
            row = {
                "ts_code": str(source["ts_code"]),
                "trade_date": fp._date8(str(source["trade_date"])),
                "adjusted_close": round(adjusted, 12),
            }
            # governance-mutation: R035_COMMITTED_PRICE_DATES
            if row["trade_date"] not in endpoints_by_date:
                raise EvaluationError(
                    f"price evidence is not backed by an atomic source batch: {row['trade_date']}"
                )
            evidence.append(row)
            by_code[row["ts_code"]].append(row)
        for code in codes:
            if not by_code[code] or by_code[code][0]["trade_date"] != as_of:
                # governance-mutation: R035_COMMON_T0_REQUIRED
                raise EvaluationError(f"candidate lacks the common U2 t0 close: {code}")

        scored: list[dict[str, Any]] = []
        for group_row in grouped_rows:
            code = str(group_row["ts_code"])
            prices = by_code[code]
            t0 = prices[0]
            returns: dict[str, dict[str, Any]] = {}
            for horizon in HORIZONS:
                key = f"T+{horizon}"
                if len(sessions) <= horizon:
                    returns[key] = {
                        "status": "WINDOW_OPEN",
                        "target_trade_date": None,
                        "observed_trade_date": None,
                        "adjusted_close": None,
                        "value": None,
                        "truncated": False,
                    }
                    continue
                target = sessions[horizon]
                observed = [row for row in prices if row["trade_date"] <= target][-1]
                truncated = observed["trade_date"] != target
                # governance-mutation: R035_ALIGNED_HORIZON
                value = observed["adjusted_close"] / t0["adjusted_close"] - 1.0
                returns[key] = {
                    "status": "TRUNCATED" if truncated else "SETTLED",
                    "target_trade_date": target,
                    "observed_trade_date": observed["trade_date"],
                    "adjusted_close": observed["adjusted_close"],
                    "value": round(value, 12),
                    "truncated": truncated,
                }
            scored.append({
                **dict(group_row),
                "t0": {
                    "trade_date": as_of,
                    "adjusted_close": t0["adjusted_close"],
                    "basis": PRICE_BASIS,
                },
                "aligned_return": returns,
            })
        receipt = {
            "sessions_from_t0": sessions[:max(HORIZONS) + 1],
            "latest_available_session": sessions[-1],
            "source_batch_rows": len(batch_rows),
            "source_batch_rows_hash": _hash(batch_rows),
            "price_rows_hash": _hash(evidence),
            "price_rows": len(evidence),
        }
        return scored, receipt
    except sqlite3.Error as exc:
        raise EvaluationError(f"feature store read failed: {exc}") from exc
    finally:
        conn.close()


def _mann_whitney(a: Sequence[float], b: Sequence[float]) -> dict[str, Any] | None:
    if not a or not b:
        return None
    pooled = sorted([(float(value), "A") for value in a] + [(float(value), "B") for value in b])
    ranks = [0.0] * len(pooled)
    tie_sum = 0
    index = 0
    while index < len(pooled):
        end = index + 1
        while end < len(pooled) and pooled[end][0] == pooled[index][0]:
            end += 1
        rank = (index + 1 + end) / 2.0
        for offset in range(index, end):
            ranks[offset] = rank
        tie_size = end - index
        tie_sum += tie_size ** 3 - tie_size
        index = end
    n_a, n_b = len(a), len(b)
    rank_a = sum(rank for rank, (_, group) in zip(ranks, pooled) if group == "A")
    u_a = rank_a - n_a * (n_a + 1) / 2.0
    total = n_a + n_b
    variance = n_a * n_b / 12.0 * (
        total + 1.0 - (tie_sum / (total * (total - 1)) if total > 1 else 0.0)
    )
    z = (u_a - n_a * n_b / 2.0) / math.sqrt(variance) if variance > 0 else 0.0
    p = math.erfc(abs(z) / math.sqrt(2.0))
    return {
        "u_a": round(u_a, 8),
        "z": round(z, 8),
        "p_two_sided": round(p, 12),
    }


def _group_summary(values: Sequence[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean": round(mean(values), 12) if values else None,
        "median": round(median(values), 12) if values else None,
    }


def _test_result(
    rows: Sequence[Mapping[str, Any]], *, field: str, groups: tuple[str, str]
) -> dict[str, Any]:
    horizons: dict[str, Any] = {}
    for horizon in HORIZON_KEYS:
        values: dict[str, list[float]] = {groups[0]: [], groups[1]: []}
        window_open = False
        for row in rows:
            group = row.get(field)
            if group not in groups:
                continue
            item = (row.get("aligned_return") or {}).get(horizon) or {}
            if item.get("status") == "WINDOW_OPEN":
                window_open = True
                continue
            value = item.get("value")
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise EvaluationError(f"{field} has invalid {horizon} return")
            values[str(group)].append(float(value))
        sample_gate = all(len(values[group]) >= MIN_GROUP_N for group in groups)
        horizons[horizon] = {
            "status": (
                "WINDOW_OPEN" if window_open
                else "CALIBRATING_CLAIM_BLOCKED" if sample_gate
                else "INSUFFICIENT_SAMPLE"
            ),
            "group_a": {"name": groups[0], **_group_summary(values[groups[0]])},
            "group_b": {"name": groups[1], **_group_summary(values[groups[1]])},
            "median_difference_a_minus_b": (
                round(median(values[groups[0]]) - median(values[groups[1]]), 12)
                if values[groups[0]] and values[groups[1]] else None
            ),
            "statistic": _mann_whitney(values[groups[0]], values[groups[1]]),
            "sample_gate": {
                "minimum_n_per_group": MIN_GROUP_N,
                "passed": sample_gate,
            },
            "claim_allowed": False,
        }
    return {"groups": list(groups), "horizons": horizons}


def _tests_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    # governance-mutation: R035_TWO_LAYER_SEPARATION
    return {
        "u1_u2_discovery": _test_result(
            rows, field="u1_u2_group", groups=U12_GROUPS
        ),
        "u3_battery_separation": _test_result(
            rows, field="u3_group", groups=U3_GROUPS
        ),
    }


def build_evaluation(
    *, bundle_dir: Path, battery_path: Path, feature_db: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    manifest, payloads = _load_bundle(bundle_dir)
    candidates = payloads["candidate_review.json"]
    battery = _load_json(battery_path)
    batch_id, grouped, missing_battery = _candidate_groups(candidates, battery)
    rows, price_receipt = _aligned_returns(
        feature_db, str(candidates["as_of"]), grouped
    )
    generated_at = generated_at or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    tests = _tests_from_rows(rows)
    has_open_window = any(
        item["status"] == "WINDOW_OPEN"
        for test in tests.values()
        for item in test["horizons"].values()
    )
    payload = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "status": "PARTIAL" if missing_battery or has_open_window else "COMPLETE",
        "as_of": candidates["as_of"],
        "generated_at": generated_at,
        "control_batch_id": batch_id,
        "policy": {
            "entry_basis": "U2_AS_OF_SETTLED_CLOSE",
            "price_basis": PRICE_BASIS,
            "horizons": list(HORIZON_KEYS),
            "primary_horizon": PRIMARY_HORIZON,
            "missing_target_bar": "LAST_AVAILABLE_SETTLED_CLOSE_WITH_TRUNCATED_TRUE",
            "u1_u2_groups": list(U12_GROUPS),
            "u3_groups": list(U3_GROUPS),
            "test_method": TEST_METHOD,
            "cross_batch_mixing": "FORBIDDEN",
        },
        "source": {
            "bundle_hash": manifest["bundle_hash"],
            "bundle_generated_at": manifest.get("generated_at"),
            "candidate_rows_hash": candidates["rows_hash"],
            "battery_hash": _hash(battery),
            **price_receipt,
        },
        "coverage": {
            "scored_rows": len(rows),
            "missing_battery_rows": len(missing_battery),
            "missing_battery_tickers": missing_battery,
        },
        "tests": tests,
        "rows": rows,
        "rows_hash": _hash(rows),
        "claim_gate": {
            "status": "BLOCKED",
            "claim_allowed": False,
            "reason": "PROSPECTIVE_CAUSAL_CLUSTER_GOVERNANCE_NOT_AVAILABLE",
            "blocked_by": ["R-038", "R-039", "R-040", "R-041"],
            "retrospective_history_contribution": 0,
        },
        "disclaimer": DISCLAIMER,
    }
    validate_evaluation(payload)
    return payload


def validate_evaluation(payload: Mapping[str, Any]) -> None:
    if (
        payload.get("schema") != SCHEMA
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("rule_version") != RULE_VERSION
    ):
        raise EvaluationError("R-035 schema/version/rule mismatch")
    # governance-mutation: R035_NO_TRADE_AUTHORITY
    offending = fp.FORBIDDEN_ACTION_KEYS.intersection(fp._walk_keys(payload))
    if offending:
        raise EvaluationError(f"R-035 receipt contains trade authority: {sorted(offending)}")
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("rows_hash") != _hash(rows):
        raise EvaluationError("R-035 rows/hash mismatch")
    policy = payload.get("policy") or {}
    # governance-mutation: R035_POLICY_FROZEN
    if (
        policy.get("entry_basis") != "U2_AS_OF_SETTLED_CLOSE"
        or policy.get("price_basis") != PRICE_BASIS
        or policy.get("horizons") != list(HORIZON_KEYS)
        or policy.get("primary_horizon") != PRIMARY_HORIZON
        or policy.get("missing_target_bar")
        != "LAST_AVAILABLE_SETTLED_CLOSE_WITH_TRUNCATED_TRUE"
        or policy.get("test_method") != TEST_METHOD
        or policy.get("u1_u2_groups") != list(U12_GROUPS)
        or policy.get("u3_groups") != list(U3_GROUPS)
        or policy.get("cross_batch_mixing") != "FORBIDDEN"
    ):
        raise EvaluationError("R-035 preregistered policy drift")
    as_of = fp._date8(str(payload.get("as_of") or ""))
    batch = str(payload.get("control_batch_id") or "")
    if batch != f"CTRL_{as_of}_v1":
        raise EvaluationError("R-035 control batch is not bound to as_of")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("control_batch_id") != batch:
            raise EvaluationError("R-035 row crosses control batches")
        code = str(row.get("ts_code") or "")
        if not code or code in seen:
            raise EvaluationError("R-035 rows contain duplicate/empty ts_code")
        seen.add(code)
        if row.get("u1_u2_group") not in (*U12_GROUPS, None):
            raise EvaluationError("R-035 U1/U2 group is invalid")
        if row.get("u3_group") not in (*U3_GROUPS, None):
            raise EvaluationError("R-035 U3 group is invalid")
        # governance-mutation: R035_LAYER_ROW_SEPARATION
        if row.get("u1_u2_group") == "RANDOM_CONTROL" and (
            row.get("u3_group") is not None or row.get("u3_group_reason") is not None
        ):
            raise EvaluationError("R-035 random controls cannot enter the U3 test")
        t0 = row.get("t0") or {}
        if t0.get("trade_date") != payload.get("as_of") or t0.get("basis") != PRICE_BASIS:
            raise EvaluationError("R-035 row does not use the common t0 basis")
        aligned = row.get("aligned_return")
        if not isinstance(aligned, dict) or tuple(aligned) != HORIZON_KEYS:
            raise EvaluationError("R-035 aligned_return horizon set/order drift")
        for item in aligned.values():
            status = item.get("status")
            if status not in RETURN_STATUSES:
                raise EvaluationError("R-035 aligned return status is invalid")
            if status == "WINDOW_OPEN":
                if item.get("value") is not None or item.get("truncated") is not False:
                    raise EvaluationError("open horizon cannot carry a return")
            else:
                value = item.get("value")
                if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise EvaluationError("settled horizon lacks a finite return")
                if (status == "TRUNCATED") is not (item.get("truncated") is True):
                    raise EvaluationError("truncated status/flag mismatch")
                if str(item.get("observed_trade_date")) > str(item.get("target_trade_date")):
                    raise EvaluationError("aligned return looks beyond its target horizon")
    # governance-mutation: R035_STATISTICS_RECOMPUTED
    if payload.get("tests") != _tests_from_rows(rows):
        raise EvaluationError("R-035 test statistics do not match scored rows")
    coverage = payload.get("coverage") or {}
    missing = coverage.get("missing_battery_tickers")
    if (
        not isinstance(missing, list)
        or missing != sorted(set(missing))
        or coverage.get("missing_battery_rows") != len(missing)
        or coverage.get("scored_rows") != len(rows)
    ):
        raise EvaluationError("R-035 coverage receipt is inconsistent")
    has_open_window = any(
        item.get("status") == "WINDOW_OPEN"
        for row in rows
        for item in row["aligned_return"].values()
    )
    # governance-mutation: R035_STATUS_RECOMPUTED
    expected_status = "PARTIAL" if missing or has_open_window else "COMPLETE"
    if payload.get("status") != expected_status:
        raise EvaluationError("R-035 top-level status does not match observed coverage")
    claim = payload.get("claim_gate") or {}
    # governance-mutation: R035_CLAIM_BLOCKED
    if (
        claim.get("status") != "BLOCKED"
        or claim.get("claim_allowed") is not False
        or claim.get("retrospective_history_contribution") != 0
        or claim.get("reason")
        != "PROSPECTIVE_CAUSAL_CLUSTER_GOVERNANCE_NOT_AVAILABLE"
        or claim.get("blocked_by") != ["R-038", "R-039", "R-040", "R-041"]
    ):
        raise EvaluationError("R-035 cannot unlock a research claim")
    if payload.get("disclaimer") != DISCLAIMER:
        raise EvaluationError("R-035 disclaimer is missing")


def _atomic_write_new(path: Path, payload: Mapping[str, Any]) -> None:
    if os.path.lexists(path):
        raise EvaluationError(f"refusing to overwrite an evaluation receipt: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--battery", required=True, type=Path)
    parser.add_argument("--feature-db", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--generated-at")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = build_evaluation(
            bundle_dir=args.bundle_dir,
            battery_path=args.battery,
            feature_db=args.feature_db,
            generated_at=args.generated_at,
        )
        _atomic_write_new(args.output, payload)
    except Exception as exc:
        print(f"REFUSED: {exc}", file=os.sys.stderr)
        return 1
    print(json.dumps({
        "status": payload["status"],
        "as_of": payload["as_of"],
        "control_batch_id": payload["control_batch_id"],
        "scored_rows": payload["coverage"]["scored_rows"],
        "claim_allowed": False,
        "output": str(args.output),
    }, ensure_ascii=False, sort_keys=True))
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
