#!/usr/bin/env python3
"""Nightly machine-vs-machine disagreement queue (contract Q, v0.1).

The funnel carries two independent machine judgements about financial red flags:

  * U3 ``red_flag_gate`` inside the candidate battery (``基本面.红旗闸门`` with
    free-text ``红旗理由``), run only on the ~180 dispatched candidates;
  * the same-night E1 event layer (``public/data/v2/e1_event_layer.json``),
    run on the whole U0 universe, with supersession-aware ``evidence_coverage``.

When U3 says RED_FLAG and E1 says NO_RED_FLAG_FOUND, the two models disagree.
This module lists those rows the same night, tags how stale the evidence U3
cited is *according to the E1 layer*, adds two seeded control rows from the
E1-excluded side (so the review is not one-directional), and ranks at most
``HUMAN_CAP`` rows for human adjudication.

Nothing here changes a machine verdict, admits anything to U4, or fills a human
label.  ``adjudication_status`` is always ``PENDING``; humans record verdicts in
the separate adjudication ledger (contract A).  The E1 layer is not ground truth
either: a row says "the two models disagree", never "who is right".

不是买卖指令；研究信号，human executes。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from funnel_pipeline import FunnelError, _hash  # noqa: E402

SCHEMA = "ar.funnel_disagreement_queue"
SCHEMA_VERSION = "0.1"
QUEUE_FILE = "disagreement_queue.json"
DISCLAIMER = "不是买卖指令；研究信号，human executes。"

HUMAN_CAP = 10
CONTROL_PER_NIGHT = 2
STALENESS_RULE_VERSION = "v0.1"
ORDERING = "CLASS_THEN_STALENESS_THEN_HASH/v0.1"

CLASS_U3_VS_E1 = "U3_RED_FLAG_VS_E1_CLEAR"
CLASS_CONTROL = "E1_RED_FLAG_CONTROL_SAMPLE"
# Routing order: the two control rows are reserved first so the human always
# sees the opposite direction (E1 red flags U3 never looked at) as well.
CLASS_ORDER = (CLASS_CONTROL, CLASS_U3_VS_E1)

SUPERSEDED = "SUPERSEDED_PER_E1_LAYER"
OUT_OF_WINDOW = "OUT_OF_E1_WINDOW"
ACTIVE = "ACTIVE_PER_E1_LAYER"
COVERAGE_EMPTY = "E1_COVERAGE_EMPTY"
UNDETERMINED = "UNDETERMINED"
# Routing priority inside a class: rows the known supersession defect cannot
# explain (both models looked at live evidence) come first.
STALENESS_ORDER = (ACTIVE, COVERAGE_EMPTY, UNDETERMINED, OUT_OF_WINDOW, SUPERSEDED)
REASON_KINDS = ("forecast", "express", "income", "unparsed")

E1_SAME_RUN = "SAME_RUN_MANIFEST"
E1_SAME_AS_OF = "SAME_AS_OF"
E1_UNAVAILABLE = "UNAVAILABLE"
E1_BASES = (E1_SAME_RUN, E1_SAME_AS_OF, E1_UNAVAILABLE)
E1_RUN_MANIFEST_KEY = "public:e1_event_layer.json"

U3_SURFACE = "U3_RED_FLAG_GATE"
E1_SURFACE = "E1_LAYER"
UNOBSERVED_SURFACE = "NONE_OBSERVED"
UNOBSERVED_VERDICT = "NOT_OBSERVED"
CONTROL_COUNTER_REASON = "U3_BATTERY_NOT_DISPATCHED_FOR_E1_EXCLUDED_ROWS"

AUTHORITY = {
    "changes_machine_verdict": False,
    "u4_admission_authority": False,
    "claim_allowed": False,
    "no_trade_flag": True,
}
TOP_KEYS = (
    "schema", "schema_version", "as_of", "run_id", "generated_at", "source_bindings",
    "policy", "counts", "rows", "rows_hash", "authority", "disclaimer",
)
ROW_KEYS = (
    "row_id", "ts_code", "display_name", "disagreement_class", "evidence_staleness",
    "reason_staleness", "machine_side", "counter_side", "bindings", "routing",
    "adjudication_status",
)
COUNT_KEYS = (
    "battery_dispatched_rows", "u3_red_flag_rows", "u3_red_flag_vs_e1_clear_rows",
    "superseded_rows", "out_of_e1_window_rows", "active_rows", "e1_coverage_empty_rows",
    "undetermined_rows", "control_rows", "human_routed_rows", "unobservable_cells",
)
STALENESS_COUNT_KEYS = {
    SUPERSEDED: "superseded_rows",
    OUT_OF_WINDOW: "out_of_e1_window_rows",
    ACTIVE: "active_rows",
    COVERAGE_EMPTY: "e1_coverage_empty_rows",
    UNDETERMINED: "undetermined_rows",
}
# The battery only runs on candidates E1 did not exclude (funnel_pipeline marks
# every E1 red flag EXCLUDED_RED_FLAG and leaves it out of the candidate
# manifest), so NO battery row can carry an E1 RED_FLAG: neither a U3 PASS nor a
# U3 RED_FLAG against an E1 RED_FLAG is observable here.  Said out loud, not
# implied by 0.  The second cell is a proposed contract Q v0.1 amendment
# (review finding QT-C2), pending Junyan's sign-off.
UNOBSERVABLE_CELLS = ["U3_PASS_VS_E1_RED_FLAG", "U3_RED_FLAG_VS_E1_RED_FLAG"]

_PERIOD_RE = re.compile(r"(?:期末|end_date=|period=)(\d{8})")
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*(?::.*)?$", re.S)
_CODE_KIND_PREFIXES = (
    ("FORECAST", "forecast"),
    ("NEGATIVE_ISSUER_GUIDANCE", "forecast"),
    ("EXPRESS", "express"),
    ("INCOME", "income"),
    ("QUARTER", "income"),
    ("NEGATIVE_AND_WORSENING_QUARTER", "income"),
)


class DisagreementError(FunnelError):
    pass


# ── small helpers ─────────────────────────────────────────────────────────

def _sha_ref(value: Any) -> str:
    return "sha256:" + _hash(value)


def row_id_for(as_of: str, ts_code: str, disagreement_class: str) -> str:
    return _sha_ref({"as_of": as_of, "ts_code": ts_code, "disagreement_class": disagreement_class})


def _parse_iso(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def scan_e1_projection(scan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The E1 verdict as the candidates stage saw it, from the hash-bound scan."""
    result: dict[str, dict[str, Any]] = {}
    for row in scan.get("rows") or []:
        if not isinstance(row, Mapping) or row.get("channel") != "E1_EVENT":
            continue
        values = row.get("feature_values") or {}
        result[str(row.get("ts_code"))] = {
            "verdict": str(values.get("verdict") or "DATA_BLOCKED"),
            "reason_codes": [str(code) for code in (row.get("reason_codes") or [])],
            "latest_e1_date": values.get("latest_e1_date"),
        }
    return result


def _e1_rows(e1: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if e1 is None:
        return {}
    return {str(row.get("ts_code")): row for row in e1.get("rows") or [] if isinstance(row, Mapping)}


def _e1_periods(e1: Mapping[str, Any] | None) -> list[str]:
    return [str(p) for p in ((e1 or {}).get("source") or {}).get("periods") or []
            if re.fullmatch(r"\d{8}", str(p))]


def e1_min_period(e1: Mapping[str, Any] | None) -> str | None:
    periods = _e1_periods(e1)
    return min(periods) if periods else None


def e1_max_period(e1: Mapping[str, Any] | None) -> str | None:
    periods = _e1_periods(e1)
    return max(periods) if periods else None


def control_codes(candidate_review: Mapping[str, Any], as_of: str,
                  n: int = CONTROL_PER_NIGHT) -> list[str]:
    """Seeded, replayable draw from the E1-excluded side: lowest sha256(as_of|ts_code)."""
    excluded = sorted({
        str(row.get("ts_code")) for row in candidate_review.get("rows") or []
        if isinstance(row, Mapping) and row.get("review_status") == "EXCLUDED_RED_FLAG"
    })
    keyed = sorted(excluded, key=lambda code: hashlib.sha256(
        f"{as_of}|{code}".encode("utf-8")).hexdigest())
    return keyed[:n]


# ── E1 same-run binding ───────────────────────────────────────────────────

def resolve_e1_basis(
    e1_raw: bytes | None, *, as_of: str, scan: Mapping[str, Any],
    codes: Sequence[str], run_manifest: Mapping[str, Any] | None,
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Decide whether this E1 layer may be compared with this run's U3 rows.

    Returns ``(basis, payload_or_None, reason_or_None)``.  Never raises on bad
    input: an unusable layer is ``UNAVAILABLE`` (and every staleness becomes
    UNDETERMINED); it must not take the whole finalize step down.

    A layer from another night/run is refused.  ``SAME_RUN_MANIFEST`` needs the
    run's publish manifest to record exactly these bytes; without that manifest
    (the nightly finalize runs before publication) ``SAME_AS_OF`` needs the same
    as_of, an E1 layer generated no later than the scan that consumed it, and a
    verdict for every compared ticker equal to the scan's own E1 projection.
    E1 status PARTIAL is a valid same-night basis.

    Known limit (review finding QT-C4): the candidates stage records no digest
    of the E1 layer it consumed, so ``SAME_AS_OF`` means "same as_of, generated
    before the scan, verdicts equal to the scan projection" and cannot tell two
    same-as_of layers from different runs apart when their verdicts agree
    (``evidence_coverage`` is not in the scan).  ``SAME_RUN_MANIFEST`` is the
    only digest-exact binding.
    """
    if e1_raw is None:
        return E1_UNAVAILABLE, None, "E1_LAYER_MISSING"
    try:
        e1 = json.loads(e1_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return E1_UNAVAILABLE, None, "E1_LAYER_UNREADABLE"
    if not isinstance(e1, dict) or e1.get("schema") != "ar.e1_event_layer":
        return E1_UNAVAILABLE, None, "E1_LAYER_SCHEMA"
    rows = e1.get("rows")
    if not isinstance(rows, list) or e1.get("rows_hash") != _hash(rows):
        return E1_UNAVAILABLE, None, "E1_ROWS_HASH_MISMATCH"
    codes_seen = [str(row.get("ts_code")) for row in rows if isinstance(row, Mapping)]
    if len(codes_seen) != len(rows) or len(set(codes_seen)) != len(codes_seen):
        return E1_UNAVAILABLE, None, "E1_ROWS_INVALID"
    # governance-mutation: FUNNEL_TRUST_E1_SAME_RUN_ONLY
    if str(e1.get("as_of") or "") != as_of:
        return E1_UNAVAILABLE, None, "E1_AS_OF_MISMATCH"
    digest = hashlib.sha256(e1_raw).hexdigest()
    if run_manifest is not None:
        recorded = (run_manifest.get("artifacts") or {}).get(E1_RUN_MANIFEST_KEY)
        if recorded != digest:
            return E1_UNAVAILABLE, None, "E1_DIGEST_NOT_THIS_RUN"
        basis = E1_SAME_RUN
    else:
        e1_at = _parse_iso(e1.get("generated_at"))
        scan_at = _parse_iso(scan.get("generated_at"))
        if e1_at is None or scan_at is None or e1_at > scan_at:
            return E1_UNAVAILABLE, None, "E1_NOT_BEFORE_SCAN"
        basis = E1_SAME_AS_OF
    projected = scan_e1_projection(scan)
    by_code = _e1_rows(e1)
    for code in codes:
        if (projected.get(code) or {}).get("verdict") != (by_code.get(code) or {}).get("verdict"):
            return E1_UNAVAILABLE, None, "E1_PROJECTION_MISMATCH"
    return basis, e1, None


def run_manifest_path(public_v2: Path, run_id: str) -> Path:
    return public_v2 / "runs" / run_id / "manifest.json"


def load_e1_inputs(public_v2: Path, run_id: str) -> tuple[bytes | None, dict | None]:
    """Read (never write) the staged E1 layer and, if present, this run's publish manifest."""
    e1_path = public_v2 / "e1_event_layer.json"
    try:
        e1_raw = e1_path.read_bytes() if e1_path.is_file() and not e1_path.is_symlink() else None
    except OSError:
        e1_raw = None
    manifest = None
    mp = run_manifest_path(public_v2, run_id)
    try:
        if mp.is_file() and not mp.is_symlink():
            loaded = json.loads(mp.read_text(encoding="utf-8"))
            manifest = loaded if isinstance(loaded, dict) and loaded.get("run_id") == run_id else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        manifest = {}
    return e1_raw, manifest


# ── reason parsing and staleness ──────────────────────────────────────────

def parse_reason(reason: Any) -> tuple[str, str | None]:
    """Map one U3 red-flag reason to (kind, cited period-end or None).

    Accepts the current free-text f-strings (最新预告/最新快报/最近季度) and closed
    reason codes (``FORECAST_*``/``EXPRESS_*``/``INCOME_*``/``QUARTER_*``, a string
    or a ``{"code", "end_date"|"period"}`` object) if the red-flag fix adopts them.
    Anything else is ``unparsed`` and stays visible, never dropped.
    """
    code: str | None = None
    period: str | None = None
    if isinstance(reason, str):
        text = reason.strip()
        match = _PERIOD_RE.search(text)
        period = match.group(1) if match else None
        if text.startswith("最新预告"):
            return "forecast", period
        if text.startswith("最新快报"):
            return "express", None
        if text.startswith("最近季度"):
            return "income", None
        if _CODE_RE.match(text):
            code = text.split(":", 1)[0]
    elif isinstance(reason, Mapping):
        raw_code = reason.get("code") or reason.get("reason_code") or reason.get("kind")
        code = str(raw_code).strip().upper() if raw_code else None
        raw_period = reason.get("end_date") or reason.get("period")
        period = str(raw_period) if raw_period and re.fullmatch(r"\d{8}", str(raw_period)) else None
    if code:
        for prefix, kind in _CODE_KIND_PREFIXES:
            if code.startswith(prefix):
                return kind, (period if kind == "forecast" else None)
    return "unparsed", None


def reason_staleness(kind: str, period: str | None, coverage: Mapping[str, Any] | None,
                     min_period: str | None, max_period: str | None = None) -> tuple[Any, str]:
    """Map one parsed reason onto E1's *kind-level* coverage.

    E1 ``evidence_coverage`` is per kind, not per period, so it only describes a
    cited filing whose period lies inside E1's own period window.  A cited
    forecast period before that window is OUT_OF_E1_WINDOW; one after it is a
    filing E1 never looked at, so E1's value is not about it: UNDETERMINED.
    """
    if kind == "unparsed" or not isinstance(coverage, Mapping):
        return None, UNDETERMINED
    value = coverage.get(kind)
    # governance-mutation: FUNNEL_DISAGREEMENT_OUT_OF_WINDOW
    if kind == "forecast" and period and min_period and period < min_period:
        return value, OUT_OF_WINDOW
    # governance-mutation: FUNNEL_DISAGREEMENT_AFTER_E1_WINDOW
    if kind == "forecast" and period and max_period and period > max_period:
        return value, UNDETERMINED
    if value == "SUPERSEDED":
        return value, SUPERSEDED
    if value == "PRESENT" or (kind == "income" and value == "COMPLETE"):
        return value, ACTIVE
    if value == "EMPTY_VALID":
        return value, COVERAGE_EMPTY
    return value, UNDETERMINED


def row_staleness(items: Sequence[Mapping[str, Any]]) -> str:
    states = [item["staleness"] for item in items]
    if not states:
        return UNDETERMINED
    # Conservative precedence: one reason resting on live evidence keeps the row ACTIVE.
    # governance-mutation: FUNNEL_DISAGREEMENT_ACTIVE_PRECEDENCE
    if ACTIVE in states:
        return ACTIVE
    if UNDETERMINED in states:
        return UNDETERMINED
    if all(state == SUPERSEDED for state in states):
        return SUPERSEDED
    if all(state in (SUPERSEDED, OUT_OF_WINDOW) for state in states):
        return OUT_OF_WINDOW
    return COVERAGE_EMPTY


def u3_fundamental(row: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    """Return (U3 state, 基本面 dict). State ∈ {RED_FLAG, PASS, BLOCKED, UNKNOWN}."""
    dims = row.get("dims") if isinstance(row.get("dims"), Mapping) else {}
    fundamental = dims.get("基本面") if isinstance(dims.get("基本面"), Mapping) else {}
    if fundamental.get("status") in {"DATA_BLOCKED", "NOT_RUN"}:
        return "BLOCKED", fundamental
    verdict = fundamental.get("红旗闸门")
    if verdict in {"RED_FLAG", "PASS"}:
        return str(verdict), fundamental
    return "UNKNOWN", fundamental


def classify_u3_row(row: Mapping[str, Any], e1_row: Mapping[str, Any] | None,
                    min_period: str | None,
                    max_period: str | None = None) -> tuple[list[dict[str, Any]], str]:
    _state, fundamental = u3_fundamental(row)
    reasons = fundamental.get("红旗理由")
    reasons = list(reasons) if isinstance(reasons, list) else ([] if reasons is None else [reasons])
    coverage = (e1_row or {}).get("evidence_coverage") if e1_row is not None else None
    items = []
    for reason in reasons:
        kind, period = parse_reason(reason)
        value, staleness = reason_staleness(kind, period, coverage, min_period, max_period)
        items.append({
            "reason_verbatim": reason,
            "kind": kind,
            "e1_coverage_value": value,
            "staleness": staleness,
        })
    return items, row_staleness(items)


# ── queue ─────────────────────────────────────────────────────────────────

def _names(registry_projected: Mapping[str, Any] | None) -> dict[str, str]:
    return {
        str(row.get("ts_code")): str(row.get("name"))
        for row in (registry_projected or {}).get("rows") or []
        if isinstance(row, Mapping) and row.get("name")
    }


def build_queue(
    *, as_of: str, run_id: str, generated_at: str,
    candidate_manifest: Mapping[str, Any], battery: Mapping[str, Any],
    candidate_review: Mapping[str, Any], scan: Mapping[str, Any],
    registry_projected: Mapping[str, Any] | None,
    e1: Mapping[str, Any] | None, e1_basis: str,
) -> dict[str, Any]:
    """Pure: same inputs ⇒ same bytes.  ``e1`` must be None unless the basis is bound."""
    if e1_basis not in E1_BASES:
        raise DisagreementError(f"unknown E1 basis: {e1_basis!r}")
    if (e1 is None) != (e1_basis == E1_UNAVAILABLE):
        raise DisagreementError("E1 payload and E1 basis disagree")
    projection = scan_e1_projection(scan)
    e1_by_code = _e1_rows(e1)
    min_period = e1_min_period(e1)
    max_period = e1_max_period(e1)
    names = _names(registry_projected)
    results = [row for row in battery.get("results") or [] if isinstance(row, Mapping)]

    rows: list[dict[str, Any]] = []
    u3_red = 0
    for battery_row in results:
        code = str(battery_row.get("ts_code"))
        state, fundamental = u3_fundamental(battery_row)
        # A blocked/unknown 基本面 is neither a red flag nor agreement: it is not counted.
        # governance-mutation: FUNNEL_DISAGREEMENT_BLOCKED_NOT_COUNTED
        if state != "RED_FLAG":
            continue
        u3_red += 1
        e1_view = projection.get(code) or {"verdict": "DATA_BLOCKED", "reason_codes": [],
                                          "latest_e1_date": None}
        if e1_view["verdict"] != "NO_RED_FLAG_FOUND":
            continue
        e1_row = e1_by_code.get(code) if e1 is not None else None
        items, staleness = classify_u3_row(battery_row, e1_row, min_period, max_period)
        if e1 is None:
            staleness = UNDETERMINED
        reasons = fundamental.get("红旗理由")
        rows.append({
            "row_id": row_id_for(as_of, code, CLASS_U3_VS_E1),
            "ts_code": code,
            "display_name": names.get(code),
            "disagreement_class": CLASS_U3_VS_E1,
            "evidence_staleness": staleness,
            "reason_staleness": items,
            "machine_side": {
                "surface": U3_SURFACE,
                "verdict": "RED_FLAG",
                "reasons_verbatim": list(reasons) if isinstance(reasons, list) else [],
                "latest_e1_date": fundamental.get("最新E1日期"),
            },
            "counter_side": {
                "surface": E1_SURFACE,
                "verdict": e1_view["verdict"],
                "reason_codes": list(e1_view["reason_codes"]),
                "evidence_coverage": (dict(e1_row.get("evidence_coverage") or {})
                                      if e1_row is not None else None),
            },
            "bindings": {
                "u3_battery_row_hash": _sha_ref(dict(battery_row)),
                "e1_row_hash": _sha_ref(dict(e1_row)) if e1_row is not None else None,
            },
            "routing": None,
            "adjudication_status": "PENDING",
        })

    controls = control_codes(candidate_review, as_of)
    for code in controls:
        e1_view = projection.get(code) or {"verdict": "DATA_BLOCKED", "reason_codes": [],
                                          "latest_e1_date": None}
        e1_row = e1_by_code.get(code) if e1 is not None else None
        rows.append({
            "row_id": row_id_for(as_of, code, CLASS_CONTROL),
            "ts_code": code,
            "display_name": names.get(code),
            "disagreement_class": CLASS_CONTROL,
            # Staleness describes U3's cited evidence; a control row has none.
            "evidence_staleness": UNDETERMINED,
            "reason_staleness": [],
            "machine_side": {
                "surface": E1_SURFACE,
                "verdict": e1_view["verdict"],
                "reasons_verbatim": list(e1_view["reason_codes"]),
                "latest_e1_date": e1_view.get("latest_e1_date"),
            },
            "counter_side": {
                "surface": UNOBSERVED_SURFACE,
                "verdict": UNOBSERVED_VERDICT,
                "reason_codes": [CONTROL_COUNTER_REASON],
                "evidence_coverage": (dict(e1_row.get("evidence_coverage") or {})
                                      if e1_row is not None else None),
            },
            "bindings": {
                "u3_battery_row_hash": None,
                "e1_row_hash": _sha_ref(dict(e1_row)) if e1_row is not None else None,
            },
            "routing": None,
            "adjudication_status": "PENDING",
        })

    ordered = sorted(rows, key=lambda row: (
        CLASS_ORDER.index(row["disagreement_class"]),
        STALENESS_ORDER.index(row["evidence_staleness"]),
        row["row_id"],
    ))
    for rank, row in enumerate(ordered, start=1):
        queue = "HUMAN_ADJUDICATION" if rank <= HUMAN_CAP else "OBSERVED_NOT_ROUTED"
        row["routing"] = {"queue": queue, "rank": rank}

    u3_rows = [row for row in ordered if row["disagreement_class"] == CLASS_U3_VS_E1]
    counts: dict[str, Any] = {
        "battery_dispatched_rows": len(results),
        "u3_red_flag_rows": u3_red,
        "u3_red_flag_vs_e1_clear_rows": len(u3_rows),
    }
    for state, key in STALENESS_COUNT_KEYS.items():
        observed = sum(1 for row in u3_rows if row["evidence_staleness"] == state)
        # Without a bound E1 layer staleness is unknown: say null, never 0.
        counts[key] = observed if (e1 is not None or state == UNDETERMINED) else None
    counts["control_rows"] = sum(1 for row in ordered if row["disagreement_class"] == CLASS_CONTROL)
    counts["human_routed_rows"] = sum(
        1 for row in ordered if row["routing"]["queue"] == "HUMAN_ADJUDICATION")
    counts["unobservable_cells"] = list(UNOBSERVABLE_CELLS)
    counts = {key: counts[key] for key in COUNT_KEYS}

    payload = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "run_id": run_id,
        "generated_at": generated_at,
        "source_bindings": {
            "candidate_manifest_hash": candidate_manifest.get("manifest_hash"),
            "battery_rows_hash": battery.get("rows_hash"),
            "e1_layer_rows_hash": e1.get("rows_hash") if e1 is not None else None,
            "e1_layer_as_of": e1.get("as_of") if e1 is not None else None,
            "e1_basis": e1_basis,
        },
        "policy": {
            "human_cap": HUMAN_CAP,
            "control_per_night": CONTROL_PER_NIGHT,
            "staleness_rule_version": STALENESS_RULE_VERSION,
            "ordering": ORDERING,
        },
        "counts": counts,
        "rows": ordered,
        "rows_hash": _hash(ordered),
        "authority": dict(AUTHORITY),
        "disclaimer": DISCLAIMER,
    }
    validate_queue(payload)
    return payload


def validate_queue(payload: Mapping[str, Any]) -> None:
    """Shape + authority + withholding discipline.  Raises DisagreementError."""
    if set(payload) != set(TOP_KEYS):
        raise DisagreementError(f"queue keys are not the v0.1 contract: {list(payload)}")
    if payload["schema"] != SCHEMA or payload["schema_version"] != SCHEMA_VERSION:
        raise DisagreementError("queue schema/version is invalid")
    # governance-mutation: FUNNEL_DISAGREEMENT_NO_AUTHORITY
    if payload["authority"] != AUTHORITY:
        raise DisagreementError("disagreement queue cannot carry verdict or admission authority")
    bindings = payload["source_bindings"]
    if bindings.get("e1_basis") not in E1_BASES:
        raise DisagreementError("queue e1_basis is invalid")
    rows = payload["rows"]
    if not isinstance(rows, list) or payload["rows_hash"] != _hash(rows):
        raise DisagreementError("queue rows_hash does not match its rows")
    seen = set()
    for index, row in enumerate(rows, start=1):
        if set(row) != set(ROW_KEYS):
            raise DisagreementError("queue row keys are not the v0.1 contract")
        if row["adjudication_status"] != "PENDING":
            raise DisagreementError("the machine may only write adjudication_status=PENDING")
        if row["row_id"] != row_id_for(payload["as_of"], row["ts_code"], row["disagreement_class"]):
            raise DisagreementError("queue row_id is not derived from as_of/ts_code/class")
        if row["row_id"] in seen or row["routing"]["rank"] != index:
            raise DisagreementError("queue ranks are not a dense deterministic order")
        seen.add(row["row_id"])
        if row["evidence_staleness"] not in STALENESS_ORDER:
            raise DisagreementError("queue evidence_staleness is outside the closed set")
    counts = payload["counts"]
    if set(counts) != set(COUNT_KEYS):
        raise DisagreementError("queue counts are not the v0.1 contract")
    # governance-mutation: FUNNEL_DISAGREEMENT_UNAVAILABLE_IS_NULL
    if bindings["e1_basis"] == E1_UNAVAILABLE and any(
        counts[key] is not None for state, key in STALENESS_COUNT_KEYS.items() if state != UNDETERMINED
    ):
        raise DisagreementError("an unavailable E1 layer cannot publish staleness counts")
    routed = [row for row in rows if row["routing"]["queue"] == "HUMAN_ADJUDICATION"]
    # governance-mutation: FUNNEL_DISAGREEMENT_HUMAN_CAP
    if len(routed) > HUMAN_CAP or counts["human_routed_rows"] != len(routed):
        raise DisagreementError("queue routes more rows than the human cap")


def summarize(queue: Mapping[str, Any]) -> dict[str, Any]:
    """Compact projection for funnel_health (new top-level key, never battery_coverage)."""
    return {
        "schema": queue["schema"],
        "schema_version": queue["schema_version"],
        "as_of": queue["as_of"],
        "run_id": queue["run_id"],
        "e1_basis": queue["source_bindings"]["e1_basis"],
        "rows_hash": queue["rows_hash"],
        "counts": dict(queue["counts"]),
    }
