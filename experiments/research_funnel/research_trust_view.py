"""Read-only consumer projection of the nightly research trust line.

The producer writes ``funnel_health["research_trust"]`` (schema
``ar.research_trust_line`` 1.0).  This module never computes a metric and never
imports the producer: it only validates the published JSON against the shared
contract and projects the fields a human needs to read the line.

Doctrine carried here:
- an absent line is ``NOT_PRODUCED``; it is never rendered as zero;
- a withheld rate (denominator below ``min_n``) stays ``None``;
- reliance is derived from level and metric family: a withheld or
  not-computable rate is ``UNRATED`` and never reads as trusted;
- a not-computable metric carries no counts; rolling pools distinct rows;
- a line bound to another run, carrying an authority/claim flag, or naming a
  performance-shaped key is refused as a whole, not partially shown;
- the projection has no approval meaning: counts are descriptive only.

Stdlib only; Python 3.9 compatible.
"""

from __future__ import annotations

import math
import re

SCHEMA = "ar.research_trust_line"
SCHEMA_VERSION = "1.0"
MIN_N = 20
WINDOW_RUNS = 20
READ_ONLY_NOTE = "只读计数，不等于自动轮验收或研究批准"

# metric_id -> (tier, direction, threshold); frozen by the shared contract (T).
METRICS = {
    "red_flag_stale_evidence_share": ("T1", "LOWER_IS_BETTER", 0.20),
    "red_flag_cross_model_confirmed_share": ("T2", "HIGHER_IS_BETTER", 0.80),
    "red_flag_human_confirmed_share": ("T3", "HIGHER_IS_BETTER", 0.80),
    "u4_ready_false_ready_share": ("T4", "LOWER_IS_BETTER", 0.20),
    "complete_label_defect_share": ("T5", "LOWER_IS_BETTER", 0.10),
    "news_channel_available_share": ("T6", "HIGHER_IS_BETTER", 0.80),
    "macro_event_consensus_coverage": ("T7", "HIGHER_IS_BETTER", 0.80),
}
# metric_id -> kind; the producer's frozen METRIC_SPECS (the kind is part of
# the metric's meaning, not a free field).
KIND_BY_METRIC = {
    "red_flag_stale_evidence_share": "MACHINE_VS_MACHINE",
    "red_flag_cross_model_confirmed_share": "MACHINE_VS_MACHINE",
    "red_flag_human_confirmed_share": "HUMAN_VS_MACHINE",
    "u4_ready_false_ready_share": "HUMAN_VS_MACHINE",
    "complete_label_defect_share": "HUMAN_VS_MACHINE",
    "news_channel_available_share": "COVERAGE",
    "macro_event_consensus_coverage": "COVERAGE",
}
E1_DEPENDENT = ("red_flag_stale_evidence_share", "red_flag_cross_model_confirmed_share")
KINDS = frozenset({"MACHINE_VS_MACHINE", "HUMAN_VS_MACHINE", "COVERAGE"})
LEVELS = frozenset({"MEETS_BAR", "MISSES_BAR", "RATE_WITHHELD_N_BELOW_MIN", "NOT_COMPUTABLE"})
RATED_LEVELS = frozenset({"MEETS_BAR", "MISSES_BAR"})
NOT_COMPUTABLE_REASONS = frozenset({
    "LEDGER_FORCES_AGREEMENT", "NO_HUMAN_LABELS_FOR_RUN", "NO_MACRO_MANIFEST", "E1_UNAVAILABLE",
})
RELIANCE = frozenset({
    "TRUSTED_FOR_TRIAGE", "ADVISORY_SHOW_STALE_SHARE", "COVERAGE_HONEST",
    "COVERAGE_GAP_DISCLOSE", "UNRATED",
})
# Frozen rule table (design_full.json doctrine): reliance is derived from the
# level and the metric family, never self-reported.  A withheld or
# not-computable rate is UNRATED; only MEETS_BAR may carry a "trusted" label.
RELIANCE_BY_FAMILY_LEVEL = {
    ("COVERAGE", "MEETS_BAR"): "COVERAGE_HONEST",
    ("COVERAGE", "MISSES_BAR"): "COVERAGE_GAP_DISCLOSE",
    ("PAIRWISE", "MEETS_BAR"): "TRUSTED_FOR_TRIAGE",
    ("PAIRWISE", "MISSES_BAR"): "ADVISORY_SHOW_STALE_SHARE",
}
E1_BASES = frozenset({"SAME_RUN_MANIFEST", "SAME_AS_OF", "UNAVAILABLE"})
E1_SAME_RUN_BASES = frozenset({"SAME_RUN_MANIFEST", "SAME_AS_OF"})
MAX_LINE_DEPTH = 32
FORBIDDEN_KEY = re.compile(r"(?i)(return|hit|alpha|pnl|score|composite)")
RATE_TOLERANCE = 1e-3
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}")
DATE8 = re.compile(r"\d{8}")
FIXED_AUTHORITY = {"claim_allowed": False, "performance_claim": None,
                   "u4_selection_authority": False}


class TrustLineRefused(ValueError):
    """The published line is present but cannot be shown as a trust line."""


def _count(value, field):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrustLineRefused(f"COUNT_INVALID:{field}")
    return value


def _rate(value, field):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrustLineRefused(f"RATE_INVALID:{field}")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise TrustLineRefused(f"RATE_INVALID:{field}")
    return float(value)


def _forbidden_keys(value, path="research_trust"):
    """Walk the line iteratively (bounded depth) and refuse performance keys."""
    stack = [(value, path, 0)]
    while stack:
        item, where, depth = stack.pop()
        if isinstance(item, (dict, list)) and depth >= MAX_LINE_DEPTH:
            raise TrustLineRefused("LINE_SHAPE_INVALID:TOO_DEEP")
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or FORBIDDEN_KEY.search(key):
                    raise TrustLineRefused(f"FORBIDDEN_KEY_PRESENT:{where}.{key}")
                stack.append((child, f"{where}.{key}", depth + 1))
        elif isinstance(item, list):
            for index, child in enumerate(item):
                stack.append((child, f"{where}[{index}]", depth + 1))


def _expected_reliance(metric_id, level):
    family = "COVERAGE" if KIND_BY_METRIC[metric_id] == "COVERAGE" else "PAIRWISE"
    return RELIANCE_BY_FAMILY_LEVEL.get((family, level), "UNRATED")


def _expected_level(numerator, denominator, direction, threshold):
    """Return the set of levels a rated metric may legitimately carry."""
    share = numerator / denominator
    if abs(share - threshold) <= 1e-12:
        return {"MEETS_BAR", "MISSES_BAR"}
    meets = share < threshold if direction == "LOWER_IS_BETTER" else share > threshold
    return {"MEETS_BAR" if meets else "MISSES_BAR"}


def _check_rated(metric_id, level, numerator, denominator, rate, gate_n, where):
    direction, threshold = METRICS[metric_id][1], METRICS[metric_id][2]
    if level == "NOT_COMPUTABLE":
        if rate is not None:
            raise TrustLineRefused(f"NOT_COMPUTABLE_WITH_RATE:{where}")
        return
    # governance-mutation: RESEARCH_TRUST_VIEW_WITHHELD_BELOW_MIN
    if gate_n is None or gate_n < MIN_N or numerator is None or denominator is None:
        if level != "RATE_WITHHELD_N_BELOW_MIN" or rate is not None:
            raise TrustLineRefused(f"RATE_SHOWN_BELOW_MIN_SAMPLE:{where}")
        return
    if level == "RATE_WITHHELD_N_BELOW_MIN":
        raise TrustLineRefused(f"RATE_WITHHELD_AT_OR_ABOVE_MIN_SAMPLE:{where}")
    if numerator > denominator or denominator == 0:
        raise TrustLineRefused(f"COUNT_INVALID:{where}")
    if rate is not None and abs(rate - numerator / denominator) > RATE_TOLERANCE:
        raise TrustLineRefused(f"RATE_DIFFERS_FROM_COUNTS:{where}")
    # governance-mutation: RESEARCH_TRUST_VIEW_LEVEL_RECOMPUTED
    if level not in _expected_level(numerator, denominator, direction, threshold):
        raise TrustLineRefused(f"LEVEL_DIFFERS_FROM_COUNTS:{where}")


def _metric(row, e1_basis):
    if not isinstance(row, dict):
        raise TrustLineRefused("METRIC_SHAPE_INVALID")
    metric_id = row.get("metric_id")
    if metric_id not in METRICS:
        raise TrustLineRefused("METRIC_ID_UNKNOWN")
    tier, direction, threshold = METRICS[metric_id]
    if row.get("direction") != direction or row.get("threshold") != threshold:
        raise TrustLineRefused(f"THRESHOLD_OR_DIRECTION_DRIFT:{metric_id}")
    if row.get("min_n") != MIN_N or isinstance(row.get("min_n"), bool):
        raise TrustLineRefused(f"MIN_SAMPLE_DRIFT:{metric_id}")
    kind, level = row.get("kind"), row.get("level")
    reason, reliance = row.get("not_computable_reason"), row.get("reliance")
    if kind not in KINDS or level not in LEVELS or reliance not in RELIANCE:
        raise TrustLineRefused(f"VOCABULARY_INVALID:{metric_id}")
    if kind != KIND_BY_METRIC[metric_id]:
        raise TrustLineRefused(f"KIND_DRIFT:{metric_id}")
    # governance-mutation: RESEARCH_TRUST_VIEW_RELIANCE_FROM_LEVEL
    if reliance != _expected_reliance(metric_id, level):
        raise TrustLineRefused(f"RELIANCE_DIFFERS_FROM_LEVEL:{metric_id}")
    if (level == "NOT_COMPUTABLE") != (reason is not None) or (
            reason is not None and reason not in NOT_COMPUTABLE_REASONS):
        raise TrustLineRefused(f"NOT_COMPUTABLE_REASON_INVALID:{metric_id}")
    if e1_basis == "UNAVAILABLE" and metric_id in E1_DEPENDENT and level != "NOT_COMPUTABLE":
        raise TrustLineRefused(f"E1_UNAVAILABLE_BUT_COUNTED:{metric_id}")
    numerator = _count(row.get("numerator"), metric_id + ".numerator")
    denominator = _count(row.get("denominator"), metric_id + ".denominator")
    unparsed = _count(row.get("unparsed_count"), metric_id + ".unparsed_count")
    if unparsed is None:
        raise TrustLineRefused(f"COUNT_INVALID:{metric_id}.unparsed_count")
    rate = _rate(row.get("rate"), metric_id)
    # governance-mutation: RESEARCH_TRUST_VIEW_NOT_COMPUTABLE_NO_COUNTS
    if level == "NOT_COMPUTABLE" and (numerator is not None or denominator is not None):
        raise TrustLineRefused(f"NOT_COMPUTABLE_WITH_COUNTS:{metric_id}")
    if level not in RATED_LEVELS and rate is not None:
        raise TrustLineRefused(f"RATE_SHOWN_WITHOUT_RATING:{metric_id}")
    if level in RATED_LEVELS and rate is None:
        raise TrustLineRefused(f"RATED_WITHOUT_RATE:{metric_id}")
    _check_rated(metric_id, level, numerator, denominator, rate, denominator, metric_id)
    note = row.get("note")
    return {
        "metric_id": metric_id, "tier": tier, "kind": kind,
        "numerator": numerator, "denominator": denominator, "unparsed_count": unparsed,
        "rate": rate, "min_n": MIN_N, "threshold": threshold, "direction": direction,
        "level": level, "not_computable_reason": reason, "reliance": reliance,
        "note": note if isinstance(note, str) else None,
    }


def _rolling(value, metric_ids):
    if not isinstance(value, dict) or value.get("window_runs") != WINDOW_RUNS:
        raise TrustLineRefused("ROLLING_SHAPE_INVALID")
    per_metric = value.get("per_metric")
    if not isinstance(per_metric, dict) or not set(per_metric) <= set(metric_ids):
        raise TrustLineRefused("ROLLING_SHAPE_INVALID")
    rows = {}
    for metric_id in sorted(per_metric, key=lambda item: METRICS[item][0]):
        row = per_metric[metric_id]
        if not isinstance(row, dict) or row.get("level") not in LEVELS:
            raise TrustLineRefused(f"ROLLING_SHAPE_INVALID:{metric_id}")
        distinct = _count(row.get("distinct_rows"), metric_id + ".distinct_rows")
        numerator = _count(row.get("pooled_numerator"), metric_id + ".pooled_numerator")
        denominator = _count(row.get("pooled_denominator"), metric_id + ".pooled_denominator")
        level = row["level"]
        # Pooled row-nights never stand in for distinct rows: the pooled
        # denominator is the distinct-row count itself (contract T).
        # governance-mutation: RESEARCH_TRUST_VIEW_ROLLING_DISTINCT_ROWS
        if (denominator != distinct or (numerator is None) != (denominator is None)
                or (numerator is not None and numerator > denominator)):
            raise TrustLineRefused(f"ROLLING_NOT_DISTINCT_ROWS:{metric_id}")
        _check_rated(metric_id, level, numerator, denominator, None, distinct,
                     "rolling." + metric_id)
        rows[metric_id] = {"distinct_rows": distinct, "pooled_numerator": numerator,
                           "pooled_denominator": denominator, "level": level}
    return {"window_runs": WINDOW_RUNS, "per_metric": rows}


def _base(status, reason):
    return {"status": status, "reason": reason, "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION, "metrics": None, "rolling": None,
            "missing_metric_ids": None, "authority": dict(FIXED_AUTHORITY),
            "note": READ_ONLY_NOTE}


def project(health, run_id, as_of):
    """Project ``health["research_trust"]`` for one accepted run.

    Never raises; every failure becomes an explicit status.  ``status`` is one
    of ``PRESENT``, ``NOT_PRODUCED`` or ``REFUSED``.
    """
    if not isinstance(health, dict):
        return _base("REFUSED", "HEALTH_SHAPE_INVALID")
    line = health.get("research_trust")
    # governance-mutation: RESEARCH_TRUST_VIEW_ABSENT_NOT_ZERO
    if line is None:
        return _base("NOT_PRODUCED", "HEALTH_HAS_NO_RESEARCH_TRUST")
    try:
        if not isinstance(line, dict):
            raise TrustLineRefused("LINE_SHAPE_INVALID")
        if line.get("schema") != SCHEMA or line.get("schema_version") != SCHEMA_VERSION:
            raise TrustLineRefused("SCHEMA_UNSUPPORTED")
        # governance-mutation: RESEARCH_TRUST_VIEW_FORBIDDEN_KEYS
        _forbidden_keys(line)
        # governance-mutation: RESEARCH_TRUST_VIEW_RUN_BINDING
        if (not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id)
                or not isinstance(as_of, str) or not DATE8.fullmatch(as_of)
                or line.get("run_id") != run_id or line.get("as_of") != as_of):
            raise TrustLineRefused("RUN_BINDING_MISMATCH")
        e1_basis = line.get("e1_basis")
        if e1_basis not in E1_BASES:
            raise TrustLineRefused("E1_BASIS_INVALID")
        # governance-mutation: RESEARCH_TRUST_VIEW_AUTHORITY
        if (line.get("authority") != FIXED_AUTHORITY
                or line.get("claim_status") != "DESCRIPTIVE_ONLY"):
            raise TrustLineRefused("AUTHORITY_OR_CLAIM_INVALID")
        if line.get("retention_status") != "LOCAL_ONLY_UNBACKED":
            raise TrustLineRefused("RETENTION_STATUS_INVALID")
        binding = line.get("source_binding")
        if not isinstance(binding, dict) or any(
                not isinstance(key, str) or not (item is None or isinstance(item, str))
                for key, item in binding.items()):
            raise TrustLineRefused("SOURCE_BINDING_INVALID")
        # A line computed against an E1 layer from another night is refused:
        # a same-run basis must name this as_of; UNAVAILABLE binds no E1 layer.
        # governance-mutation: RESEARCH_TRUST_VIEW_E1_SAME_RUN
        if e1_basis in E1_SAME_RUN_BASES:
            if binding.get("e1_layer_as_of") != as_of:
                raise TrustLineRefused("E1_BINDING_MISMATCH")
        elif any(key.startswith("e1_") and item is not None for key, item in binding.items()):
            raise TrustLineRefused("E1_BINDING_MISMATCH")
        rows = line.get("metrics")
        if not isinstance(rows, list) or not rows:
            raise TrustLineRefused("METRICS_SHAPE_INVALID")
        metrics = [_metric(row, e1_basis) for row in rows]
        ids = [row["metric_id"] for row in metrics]
        if len(ids) != len(set(ids)):
            raise TrustLineRefused("METRIC_ID_DUPLICATE")
        metrics.sort(key=lambda row: row["tier"])
        rolling = _rolling(line.get("rolling"), ids)
    except TrustLineRefused as exc:
        return _base("REFUSED", str(exc))
    except (TypeError, ValueError, KeyError, ZeroDivisionError, RecursionError):
        return _base("REFUSED", "LINE_SHAPE_INVALID")
    generated_at = line.get("generated_at")
    result = _base("PRESENT", None)
    result.update({
        "run_id": run_id, "as_of": as_of,
        "generated_at": generated_at if isinstance(generated_at, str) else None,
        "e1_basis": e1_basis, "claim_status": "DESCRIPTIVE_ONLY",
        "retention_status": "LOCAL_ONLY_UNBACKED",
        "source_binding": dict(sorted(binding.items())),
        "metrics": metrics, "rolling": rolling,
        "missing_metric_ids": sorted(set(METRICS) - set(ids), key=lambda item: METRICS[item][0]),
    })
    return result
