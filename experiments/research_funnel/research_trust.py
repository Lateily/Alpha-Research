#!/usr/bin/env python3
"""Nightly research trust line (contract T, v1.0) and finalize wiring.

The operational receipts say whether the nightly *ran*.  This line says how far
a human may lean on the machine's *filtering* that night: are the U3 red flags
resting on evidence the E1 layer already calls superseded (T1), does E1 agree
(T2), did a human confirm them (T3), did the U4-ready and COMPLETE labels hold
up under human review (T4/T5), and were the news and macro-consensus channels
actually available (T6/T7)?

It is a filtering-trust reading, not a performance number: there is no return,
hit, alpha, P&L, score or composite anywhere in the record (pinned), every rate
below MIN_N is withheld as null (never 0), human-vs-machine metrics stay
DESCRIPTIVE_ONLY, and ``claim_allowed`` is literal false.  Thresholds and MIN_N
are initial, unvalidated constants awaiting Junyan's ratification.

Storage: the line is a finalize-stage bundle artifact (hashed by
``stage_finalize.json``), the new top-level ``funnel_health.research_trust`` key,
and one hash-chained, idempotent-per-run_id entry in
``data_history/research_advisory/research_trust/trust_lines.jsonl`` (+ anchor,
lock).  That ledger is gitignored runtime data: LOCAL_ONLY_UNBACKED.

Offline replay (never writes the ledger):

    python3 experiments/research_funnel/research_trust.py replay \
        --bundle-dir <data_history/funnel/<as_of>/<run_id>> --e1 <e1_event_layer.json> \
        [--run-manifest <runs/<run_id>/manifest.json>] [--macro-dir <public/data/v2/macro>] \
        [--advisory-root <data_history/research_advisory>] [--out <scratch dir>]

不是买卖指令；研究信号，human executes。
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import fcntl
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "execution_tracker"))

import disagreement_queue as dq  # noqa: E402
from funnel_pipeline import (  # noqa: E402
    FORBIDDEN_ACTION_KEYS,
    FunnelError,
    _canonical,
    _hash,
)

SCHEMA = "ar.research_trust_line"
SCHEMA_VERSION = "1.0"
TRUST_FILE = "research_trust_line.json"
FINALIZE_EXTRA_FILES = (dq.QUEUE_FILE, TRUST_FILE)
DISCLAIMER = dq.DISCLAIMER

MIN_N = 20
WINDOW_RUNS = 20
CLAIM_STATUS = "DESCRIPTIVE_ONLY"
RETENTION_STATUS = "LOCAL_ONLY_UNBACKED"
AUTHORITY = {
    "claim_allowed": False,
    "performance_claim": None,
    "u4_selection_authority": False,
}

MACHINE_VS_MACHINE = "MACHINE_VS_MACHINE"
HUMAN_VS_MACHINE = "HUMAN_VS_MACHINE"
COVERAGE = "COVERAGE"
LOWER = "LOWER_IS_BETTER"
HIGHER = "HIGHER_IS_BETTER"

# (metric_id, kind, direction, threshold) — initial, unvalidated, frozen by PR only.
METRIC_SPECS = (
    ("red_flag_stale_evidence_share", MACHINE_VS_MACHINE, LOWER, 0.20),
    ("red_flag_cross_model_confirmed_share", MACHINE_VS_MACHINE, HIGHER, 0.80),
    ("red_flag_human_confirmed_share", HUMAN_VS_MACHINE, HIGHER, 0.80),
    ("u4_ready_false_ready_share", HUMAN_VS_MACHINE, LOWER, 0.20),
    ("complete_label_defect_share", HUMAN_VS_MACHINE, LOWER, 0.10),
    ("news_channel_available_share", COVERAGE, HIGHER, 0.80),
    ("macro_event_consensus_coverage", COVERAGE, HIGHER, 0.80),
)
METRIC_IDS = tuple(spec[0] for spec in METRIC_SPECS)
SPEC_BY_ID = {spec[0]: spec for spec in METRIC_SPECS}
# Recomputable by the nightly verifier from the bundle + staged inputs alone.
MACHINE_METRIC_IDS = (
    "red_flag_stale_evidence_share",
    "red_flag_cross_model_confirmed_share",
    "news_channel_available_share",
    "macro_event_consensus_coverage",
)

MEETS = "MEETS_BAR"
MISSES = "MISSES_BAR"
WITHHELD = "RATE_WITHHELD_N_BELOW_MIN"
NOT_COMPUTABLE = "NOT_COMPUTABLE"
LEVELS = (MEETS, MISSES, WITHHELD, NOT_COMPUTABLE)
NC_LEDGER_FORCES_AGREEMENT = "LEDGER_FORCES_AGREEMENT"
NC_NO_HUMAN_LABELS = "NO_HUMAN_LABELS_FOR_RUN"
NC_NO_MACRO = "NO_MACRO_MANIFEST"
NC_E1_UNAVAILABLE = "E1_UNAVAILABLE"
NC_REASONS = (NC_LEDGER_FORCES_AGREEMENT, NC_NO_HUMAN_LABELS, NC_NO_MACRO, NC_E1_UNAVAILABLE, None)
RELIANCE = ("TRUSTED_FOR_TRIAGE", "ADVISORY_SHOW_STALE_SHARE", "COVERAGE_HONEST",
            "COVERAGE_GAP_DISCLOSE", "UNRATED")

TRUST_KEYS = (
    "schema", "schema_version", "as_of", "run_id", "generated_at", "e1_basis",
    "source_binding", "metrics", "rolling", "claim_status", "retention_status",
    "authority", "disclaimer",
)
METRIC_KEYS = (
    "metric_id", "kind", "numerator", "denominator", "unparsed_count", "rate", "min_n",
    "threshold", "direction", "level", "not_computable_reason", "reliance", "note",
)
SOURCE_BINDING_KEYS = (
    "candidate_manifest_hash", "battery_rows_hash", "queue_rows_hash",
    "e1_layer_rows_hash", "e1_layer_as_of", "e1_layer_status",
    "u4_ledger_head_hash", "adjudication_ledger_head_hash", "macro_manifest_sha256",
)
# A trust number that can be read as a performance number is the failure mode.
FORBIDDEN_KEY_PARTS = ("return", "hit", "alpha", "pnl", "score", "composite")

NEWS_BLOCKED_STATUSES = frozenset({"DATA_BLOCKED", "NOT_RUN"})
U4_FALSE_READY_CODES = frozenset({"U3_INCOMPLETE", "RED_FLAG_ACTIVE"})
# Reasons that may rest on filings after as_of: not scoreable as a machine defect.
U4_LATE_LABEL_CODES = frozenset({"E1_EVIDENCE_MISSING"})
U4_LATE_MISSING_EVIDENCE = frozenset({"SOURCE_FRESHNESS"})
T5_DEFECT_MISSING_EVIDENCE = frozenset({"U3_SIX_DIMENSION_BATTERY"})
HUMAN_CONFIRMS = frozenset({"MACHINE_VERDICT_CONFIRMED", "COUNTER_SIDE_REJECTED"})
HUMAN_REJECTS = frozenset({
    "MACHINE_VERDICT_REJECTED_STALE_EVIDENCE",
    "MACHINE_VERDICT_REJECTED_MISREAD",
    "MACHINE_VERDICT_REJECTED_OTHER",
})

LEDGER_DIR = ("research_trust",)
LEDGER_NAME = "trust_lines.jsonl"
LEDGER_REL = "data_history/research_advisory/research_trust/trust_lines.jsonl"
GENESIS_PREV = "0" * 64
LEDGER_RECORD_KEYS = ("seq", "run_id", "as_of", "content_hash", "trust_line", "members", "prev", "hash")
LEDGER_STATUSES = ("APPENDED", "ALREADY_RECORDED", "CONFLICT_NOT_APPENDED",
                   "LEDGER_INVALID_NOT_APPENDED", "REFUSED_NOT_SAME_RUN", "WRITE_FAILED")
U4_LEDGER_REL = ("u4_decision_ledger", "u4_decision_events.jsonl")
ADJUDICATION_LEDGER_REL = ("disagreement_adjudications", "adjudication_events.jsonl")
ADJUDICATION_KIND = "disagreement_adjudication"
ADJUDICATION_CLOSURE_KIND = "disagreement_adjudication_closure"
ADJUDICATION_SCHEMA = "ar.disagreement_adjudication"


class TrustLineError(FunnelError):
    pass


# ── metric construction ───────────────────────────────────────────────────

def _level(numerator: int, denominator: int, direction: str, threshold: float) -> tuple[float | None, str]:
    # governance-mutation: FUNNEL_TRUST_MIN_SAMPLE_WITHHELD
    if denominator < MIN_N:
        return None, WITHHELD
    rate = round(numerator / denominator, 6)
    meets = rate <= threshold if direction == LOWER else rate >= threshold
    return rate, MEETS if meets else MISSES


def _reliance(kind: str, level: str) -> str:
    if level == MEETS:
        return "COVERAGE_HONEST" if kind == COVERAGE else "TRUSTED_FOR_TRIAGE"
    if level == MISSES:
        return "COVERAGE_GAP_DISCLOSE" if kind == COVERAGE else "ADVISORY_SHOW_STALE_SHARE"
    return "UNRATED"


def metric(metric_id: str, *, numerator: int | None = None, denominator: int | None = None,
           unparsed_count: int = 0, not_computable_reason: str | None = None,
           note: str = "") -> dict[str, Any]:
    _mid, kind, direction, threshold = SPEC_BY_ID[metric_id]
    if not_computable_reason is not None:
        numerator = denominator = None
        rate, level = None, NOT_COMPUTABLE
    else:
        if numerator is None or denominator is None:
            raise TrustLineError(f"{metric_id}: computable metric needs integer counts")
        rate, level = _level(numerator, denominator, direction, threshold)
    return {
        "metric_id": metric_id,
        "kind": kind,
        "numerator": numerator,
        "denominator": denominator,
        "unparsed_count": int(unparsed_count),
        "rate": rate,
        "min_n": MIN_N,
        "threshold": threshold,
        "direction": direction,
        "level": level,
        "not_computable_reason": not_computable_reason,
        "reliance": _reliance(kind, level),
        "note": note,
    }


# ── inputs that may be missing (never raise) ──────────────────────────────

@contextlib.contextmanager
def _shared_lock_if_present(path: Path) -> Iterator[None]:
    """Take the ledger's shared lock without creating anything on disk."""
    lock = Path(f"{path}.lock")
    fd = -1
    try:
        if lock.is_file() and not lock.is_symlink():
            fd = os.open(str(lock), os.O_RDONLY)
            fcntl.flock(fd, fcntl.LOCK_SH)
        yield
    finally:
        if fd >= 0:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _verify_r015(path: Path) -> tuple[bool, str | None, str | None]:
    """Hash chain + anchor via event_ledger's read-only verifiers → (ok, head, error)."""
    import event_ledger  # noqa: WPS433

    chain = event_ledger.verify(str(path))
    anchor = event_ledger.verify_anchor(str(path))
    if not chain.get("ok") or not anchor.get("ok"):
        errors = list(chain.get("errors") or []) + list(anchor.get("errors") or [])
        return False, None, "; ".join(str(e) for e in errors[:2]) or "ledger invalid"
    return True, chain.get("head"), None


def read_u4_decisions(advisory_root: Path | None, run_id: str) -> dict[str, Any]:
    """Committed (closed-packet) U4 decisions for this run, read-only."""
    if advisory_root is None:
        return {"status": "ABSENT", "events": [], "head": None, "error": None}
    path = advisory_root.joinpath(*U4_LEDGER_REL)
    if not path.exists():
        return {"status": "ABSENT", "events": [], "head": None, "error": None}
    try:
        if path.is_symlink() or not path.is_file():
            raise TrustLineError("U4 ledger is not a regular file")
        import u4_decision_ledger as u4  # noqa: WPS433

        with _shared_lock_if_present(path):
            ok, head, error = _verify_r015(path)
            if not ok:
                return {"status": "INVALID", "events": [], "head": None, "error": error}
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                       if line.strip()]
        state = u4._replay_records(records)
        events = [
            copy.deepcopy(event) for event in state["current"].values()
            if (event.get("source") or {}).get("run_id") == run_id
        ]
        return {"status": "OK", "events": sorted(events, key=lambda e: e["candidate"]["ts_code"]),
                "head": head, "error": None}
    except Exception as exc:  # a broken optional input degrades one metric, not the night
        return {"status": "INVALID", "events": [], "head": None,
                "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def read_adjudications(advisory_root: Path | None, run_id: str,
                       queue: Mapping[str, Any]) -> dict[str, Any]:
    """Human verdicts from CLOSED adjudication batches bound to this run's queue."""
    if advisory_root is None:
        return {"status": "ABSENT", "labels": {}, "head": None, "error": None}
    path = advisory_root.joinpath(*ADJUDICATION_LEDGER_REL)
    if not path.exists():
        return {"status": "ABSENT", "labels": {}, "head": None, "error": None}
    try:
        if path.is_symlink() or not path.is_file():
            raise TrustLineError("adjudication ledger is not a regular file")
        with _shared_lock_if_present(path):
            ok, head, error = _verify_r015(path)
            if not ok:
                return {"status": "INVALID", "labels": {}, "head": None, "error": error}
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                       if line.strip()]
        queue_hash = str(queue.get("rows_hash") or "").replace("sha256:", "")
        row_ids = {row["row_id"] for row in queue.get("rows") or []}
        closed = {
            str((record.get("payload") or {}).get("batch_id"))
            for record in records if record.get("kind") == ADJUDICATION_CLOSURE_KIND
        }
        labels: dict[str, str] = {}
        for record in records:
            payload = record.get("payload") or {}
            if record.get("kind") != ADJUDICATION_KIND or not isinstance(payload, Mapping):
                continue
            authority = payload.get("authority") or {}
            if (
                payload.get("schema") != ADJUDICATION_SCHEMA
                or str(payload.get("batch_id")) not in closed
                or payload.get("run_id") != run_id
                or str(payload.get("queue_rows_hash") or "").replace("sha256:", "") != queue_hash
                or payload.get("row_id") not in row_ids
                or authority.get("u4_admission_authority") is not False
                or authority.get("changes_machine_verdict") is not False
            ):
                continue
            labels[str(payload["row_id"])] = str(payload.get("human_verdict"))
        return {"status": "OK", "labels": labels, "head": head, "error": None}
    except Exception as exc:
        return {"status": "INVALID", "labels": {}, "head": None,
                "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def read_macro(macro_dir: Path | None, *, run_id: str, as_of: str) -> dict[str, Any]:
    """Same-run M1-C manifest + the macro_events bytes it hashes, read-only."""
    absent = {"status": "ABSENT", "events": None, "manifest_sha256": None, "reason": None}
    if macro_dir is None:
        return absent
    manifest_path = macro_dir / "m1c_run_manifest.json"
    events_path = macro_dir / "macro_events.json"
    try:
        if not manifest_path.is_file() or manifest_path.is_symlink():
            return dict(absent, reason="M1C_MANIFEST_MISSING")
        raw_manifest = manifest_path.read_bytes()
        manifest = json.loads(raw_manifest.decode("utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema") != "ar.macro.m1c_run_manifest"
            or manifest.get("run_id") != run_id
            or manifest.get("target_trade_date") != as_of
        ):
            return dict(absent, reason="M1C_MANIFEST_NOT_THIS_RUN")
        if not events_path.is_file() or events_path.is_symlink():
            return dict(absent, reason="MACRO_EVENTS_MISSING")
        raw_events = events_path.read_bytes()
        if hashlib.sha256(raw_events).hexdigest() != (manifest.get("artifacts") or {}).get("macro_events.json"):
            return dict(absent, reason="MACRO_EVENTS_NOT_BOUND_TO_MANIFEST")
        events = json.loads(raw_events.decode("utf-8"))
        rows = events.get("data") if isinstance(events, dict) else None
        if events.get("run_id") != run_id or not isinstance(rows, list):
            return dict(absent, reason="MACRO_EVENTS_NOT_THIS_RUN")
        return {"status": "OK", "events": rows,
                "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(), "reason": None}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
        return dict(absent, reason=f"MACRO_UNREADABLE:{type(exc).__name__}")


# ── metrics ───────────────────────────────────────────────────────────────

def _battery_rows(battery: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [row for row in battery.get("results") or [] if isinstance(row, Mapping)]


def machine_metrics(
    *, battery: Mapping[str, Any], scan: Mapping[str, Any], e1: Mapping[str, Any] | None,
    e1_basis: str, macro: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, bool]]]:
    """T1, T2, T6, T7 — derivable from the bundle and same-run inputs only."""
    members: dict[str, dict[str, bool]] = {}
    rows = _battery_rows(battery)
    states = [(row, *dq.u3_fundamental(row)) for row in rows]
    red = [row for row, state, _f in states if state == "RED_FLAG"]
    gate_blocked = sum(1 for _r, state, _f in states if state in {"BLOCKED", "UNKNOWN"})
    out: list[dict[str, Any]] = []

    if e1 is None or e1_basis == dq.E1_UNAVAILABLE:
        note = ("E1 layer is not bound to this run; U3 red flags cannot be compared "
                f"(u3_red_flag_rows={len(red)}).")
        out.append(metric("red_flag_stale_evidence_share", not_computable_reason=NC_E1_UNAVAILABLE, note=note))
        out.append(metric("red_flag_cross_model_confirmed_share", not_computable_reason=NC_E1_UNAVAILABLE, note=note))
    else:
        e1_rows = dq._e1_rows(e1)
        min_period = dq.e1_min_period(e1)
        t1: dict[str, bool] = {}
        tally = {state: 0 for state in dq.STALENESS_ORDER}
        for row in red:
            code = str(row.get("ts_code"))
            _items, staleness = dq.classify_u3_row(row, e1_rows.get(code), min_period)
            tally[staleness] += 1
            if staleness != dq.UNDETERMINED:
                # governance-mutation: FUNNEL_TRUST_T1_E1_CONFIRMED_SUPERSESSION
                t1[code] = staleness == dq.SUPERSEDED
        members["red_flag_stale_evidence_share"] = t1
        out.append(metric(
            "red_flag_stale_evidence_share",
            numerator=sum(t1.values()), denominator=len(t1),
            unparsed_count=tally[dq.UNDETERMINED],
            note=(
                "numerator = U3 RED_FLAG rows whose cited evidence the same-run E1 layer marks "
                f"SUPERSEDED; out_of_e1_window={tally[dq.OUT_OF_WINDOW]} (older than E1 periods, "
                f"not E1-confirmed, counted in the denominator only), active={tally[dq.ACTIVE]}, "
                f"e1_coverage_empty={tally[dq.COVERAGE_EMPTY]}; undetermined rows are unparsed_count; "
                f"基本面 gate blocked/unknown rows excluded={gate_blocked}."
            ),
        ))
        t2: dict[str, bool] = {}
        unparsed = 0
        for row in red:
            code = str(row.get("ts_code"))
            verdict = (e1_rows.get(code) or {}).get("verdict")
            if verdict in {"RED_FLAG", "NO_RED_FLAG_FOUND"}:
                t2[code] = verdict == "RED_FLAG"
            else:
                unparsed += 1
        members["red_flag_cross_model_confirmed_share"] = t2
        out.append(metric(
            "red_flag_cross_model_confirmed_share",
            numerator=sum(t2.values()), denominator=len(t2), unparsed_count=unparsed,
            note=("U3 RED_FLAG rows the same-run E1 layer also flags; E1 DATA_BLOCKED/missing rows "
                  "are unparsed_count. One-directional: U3 PASS vs E1 RED_FLAG is unobservable "
                  "because E1-excluded rows never reach the battery."),
        ))

    t6: dict[str, bool] = {}
    unparsed = 0
    for row in rows:
        dim = (row.get("dims") or {}).get("消息面")
        code = str(row.get("ts_code"))
        if isinstance(dim, Mapping) and "status" not in dim:
            t6[code] = True
        # governance-mutation: FUNNEL_TRUST_NEWS_STATUS_BLOCKED
        elif isinstance(dim, Mapping) and dim.get("status") in NEWS_BLOCKED_STATUSES:
            t6[code] = False
        else:
            unparsed += 1
    members["news_channel_available_share"] = t6
    out.append(metric(
        "news_channel_available_share", numerator=sum(t6.values()), denominator=len(t6),
        unparsed_count=unparsed,
        note="available := 消息面 is a dict without 'status'; DATA_BLOCKED and NOT_RUN are unavailable.",
    ))

    if macro.get("status") != "OK":
        out.append(metric("macro_event_consensus_coverage", not_computable_reason=NC_NO_MACRO,
                          note=f"no same-run M1-C manifest ({macro.get('reason')})."))
    else:
        t7: dict[str, bool] = {}
        unparsed = 0
        for event in macro["events"]:
            key = event.get("context_id") if isinstance(event, Mapping) else None
            if not key or key in t7:
                unparsed += 1
                continue
            t7[str(key)] = (event.get("consensus") is not None
                            and event.get("consensus_status") != "DATA_BLOCKED")
        members["macro_event_consensus_coverage"] = t7
        out.append(metric(
            "macro_event_consensus_coverage", numerator=sum(t7.values()), denominator=len(t7),
            unparsed_count=unparsed,
            note="events with a consensus value that is not DATA_BLOCKED / events in the same-run macro_events.",
        ))
    return out, members


def human_metrics(
    *, battery: Mapping[str, Any], deep_queue: Mapping[str, Any], queue: Mapping[str, Any],
    u4: Mapping[str, Any], adjudication: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, bool]]]:
    """T3, T4, T5 — only from closed human records bound to this run."""
    members: dict[str, dict[str, bool]] = {}
    out: list[dict[str, Any]] = []

    # T3: the U4 ledger forces REJECT+RED_FLAG_ACTIVE on red-flag rows, so it is
    # never a label here; only the separate adjudication ledger can supply one.
    if adjudication.get("status") == "ABSENT":
        out.append(metric(
            "red_flag_human_confirmed_share", not_computable_reason=NC_LEDGER_FORCES_AGREEMENT,
            note="no adjudication ledger; U4 REJECT on red-flag rows is forced agreement, not a label.",
        ))
    else:
        t3: dict[str, bool] = {}
        unparsed = 0
        by_id = {row["row_id"]: row for row in queue.get("rows") or []}
        for row_id, verdict in sorted((adjudication.get("labels") or {}).items()):
            row = by_id.get(row_id)
            if row is None or (row.get("machine_side") or {}).get("verdict") != "RED_FLAG":
                continue
            if verdict in HUMAN_CONFIRMS:
                t3[row["ts_code"]] = True
            elif verdict in HUMAN_REJECTS:
                t3[row["ts_code"]] = False
            else:
                unparsed += 1
        if not t3 and not unparsed:
            out.append(metric(
                "red_flag_human_confirmed_share", not_computable_reason=NC_NO_HUMAN_LABELS,
                note=(f"adjudication ledger {adjudication.get('status')}: no closed batch bound to this "
                      f"run's queue{(' — ' + adjudication['error']) if adjudication.get('error') else ''}."),
            ))
        else:
            members["red_flag_human_confirmed_share"] = t3
            out.append(metric(
                "red_flag_human_confirmed_share", numerator=sum(t3.values()), denominator=len(t3),
                unparsed_count=unparsed,
                note="closed adjudication batches for this run; UNDETERMINED_NEEDS_DATA is unparsed_count.",
            ))

    events = list(u4.get("events") or [])
    if u4.get("status") != "OK" or not events:
        reason_note = (f"U4 ledger {u4.get('status')}: no closed packet bound to this run"
                       f"{(' — ' + u4['error']) if u4.get('error') else ''}.")
        out.append(metric("u4_ready_false_ready_share", not_computable_reason=NC_NO_HUMAN_LABELS, note=reason_note))
        out.append(metric("complete_label_defect_share", not_computable_reason=NC_NO_HUMAN_LABELS, note=reason_note))
        return out, members

    rows = {str(row.get("ts_code")): row for row in _battery_rows(battery)}
    row_hash = {"sha256:" + _hash(dict(row)): code for code, row in rows.items()}
    ready = {str(row.get("ts_code")): row.get("ready") is True
             for row in deep_queue.get("ready_pool") or [] if isinstance(row, Mapping)}
    t4: dict[str, bool] = {}
    t5: dict[str, bool] = {}
    unbound = late = 0
    for event in events:
        code = str((event.get("candidate") or {}).get("ts_code"))
        # governance-mutation: FUNNEL_TRUST_U4_ROW_HASH_JOIN
        if row_hash.get((event.get("source") or {}).get("u3_battery_row_hash")) != code:
            unbound += 1
            continue
        decision = event.get("decision")
        reasons = set(event.get("reason_codes") or [])
        missing = set(event.get("missing_evidence") or [])
        defect = decision == "DATA_BLOCKED" or bool(reasons & U4_FALSE_READY_CODES)
        if ready.get(code):
            if not defect and (reasons & U4_LATE_LABEL_CODES or missing & U4_LATE_MISSING_EVIDENCE):
                late += 1
            else:
                t4[code] = defect
        if ((rows[code].get("completeness") or {}).get("verdict")) == "COMPLETE":
            t5[code] = (decision == "DATA_BLOCKED" or "U3_INCOMPLETE" in reasons
                        or bool(missing & T5_DEFECT_MISSING_EVIDENCE))
    members["u4_ready_false_ready_share"] = t4
    members["complete_label_defect_share"] = t5
    out.append(metric(
        "u4_ready_false_ready_share", numerator=sum(t4.values()), denominator=len(t4),
        unparsed_count=unbound + late,
        note=(f"ready rows the human DATA_BLOCKED or coded U3_INCOMPLETE/RED_FLAG_ACTIVE; "
              f"unbound_rows={unbound}, late_label_rows={late} (E1_EVIDENCE_MISSING/SOURCE_FRESHNESS may "
              f"rest on post-as_of filings). DESCRIPTIVE_ONLY."),
    ))
    out.append(metric(
        "complete_label_defect_share", numerator=sum(t5.values()), denominator=len(t5),
        unparsed_count=unbound,
        note="COMPLETE battery rows the human DATA_BLOCKED, coded U3_INCOMPLETE or marked the battery missing. DESCRIPTIVE_ONLY.",
    ))
    return out, members


# ── rolling window over distinct rows ─────────────────────────────────────

def rolling(current_members: Mapping[str, Mapping[str, bool]], current_metrics: Sequence[Mapping[str, Any]],
            prior: Sequence[Mapping[str, Any]], *, as_of: str) -> dict[str, Any]:
    """Pool the last WINDOW_RUNS lines by distinct row (latest night wins), never row-nights.

    ``prior`` are verified ledger records; lines dated after ``as_of`` are ignored
    so an offline replay of an older night cannot pool later information.
    """
    usable = [record for record in prior if str(record.get("as_of") or "") <= as_of]
    window = usable[-(WINDOW_RUNS - 1):] if WINDOW_RUNS > 1 else []
    computable_now = {m["metric_id"] for m in current_metrics if m["level"] != NOT_COMPUTABLE}
    per_metric: dict[str, Any] = {}
    for metric_id, kind, direction, threshold in METRIC_SPECS:
        pooled: dict[str, bool] = {}
        seen_any = False
        for record in window:
            line_members = (record.get("members") or {}).get(metric_id)
            if isinstance(line_members, Mapping):
                seen_any = True
                pooled.update({str(k): bool(v) for k, v in line_members.items()})
        if metric_id in computable_now:
            seen_any = True
            pooled.update({str(k): bool(v) for k, v in (current_members.get(metric_id) or {}).items()})
        distinct = len(pooled)
        numerator = sum(pooled.values())
        if not seen_any:
            level = NOT_COMPUTABLE
        else:
            _rate, level = _level(numerator, distinct, direction, threshold)
        per_metric[metric_id] = {
            "distinct_rows": distinct,
            "pooled_numerator": numerator,
            "pooled_denominator": distinct,
            "level": level,
        }
    return {"window_runs": WINDOW_RUNS, "per_metric": per_metric}


# ── the line ──────────────────────────────────────────────────────────────

def build_trust_line(
    *, as_of: str, run_id: str, generated_at: str, queue: Mapping[str, Any],
    battery: Mapping[str, Any], scan: Mapping[str, Any], deep_queue: Mapping[str, Any],
    candidate_manifest: Mapping[str, Any], e1: Mapping[str, Any] | None, e1_basis: str,
    macro: Mapping[str, Any], u4: Mapping[str, Any], adjudication: Mapping[str, Any],
    prior: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], dict[str, dict[str, bool]]]:
    machine, machine_members = machine_metrics(
        battery=battery, scan=scan, e1=e1, e1_basis=e1_basis, macro=macro)
    human, human_members = human_metrics(
        battery=battery, deep_queue=deep_queue, queue=queue, u4=u4, adjudication=adjudication)
    by_id = {m["metric_id"]: m for m in machine + human}
    metrics = [by_id[metric_id] for metric_id in METRIC_IDS]
    members = {**machine_members, **human_members}
    line = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "run_id": run_id,
        "generated_at": generated_at,
        "e1_basis": e1_basis,
        "source_binding": {
            "candidate_manifest_hash": candidate_manifest.get("manifest_hash"),
            "battery_rows_hash": battery.get("rows_hash"),
            "queue_rows_hash": queue.get("rows_hash"),
            "e1_layer_rows_hash": e1.get("rows_hash") if e1 is not None else None,
            "e1_layer_as_of": e1.get("as_of") if e1 is not None else None,
            "e1_layer_status": e1.get("status") if e1 is not None else None,
            "u4_ledger_head_hash": u4.get("head"),
            "adjudication_ledger_head_hash": adjudication.get("head"),
            "macro_manifest_sha256": macro.get("manifest_sha256"),
        },
        "metrics": metrics,
        "rolling": rolling(members, metrics, prior, as_of=as_of),
        "claim_status": CLAIM_STATUS,
        "retention_status": RETENTION_STATUS,
        "authority": dict(AUTHORITY),
        "disclaimer": DISCLAIMER,
    }
    validate_trust_line(line)
    return line, members


def _walk_keys(value: Any) -> Iterator[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key).casefold()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def validate_trust_line(line: Mapping[str, Any]) -> None:
    if set(line) != set(TRUST_KEYS):
        raise TrustLineError(f"trust line keys are not the v1.0 contract: {sorted(line)}")
    if line["schema"] != SCHEMA or line["schema_version"] != SCHEMA_VERSION:
        raise TrustLineError("trust line schema/version is invalid")
    keys = set(_walk_keys(line))
    # governance-mutation: FUNNEL_TRUST_NO_PERFORMANCE_KEYS
    offending = sorted(k for k in keys if any(part in k for part in FORBIDDEN_KEY_PARTS)
                       or k in FORBIDDEN_ACTION_KEYS)
    if offending:
        raise TrustLineError(f"trust line carries performance/action keys: {offending}")
    # governance-mutation: FUNNEL_TRUST_NO_CLAIM_AUTHORITY
    if (line["authority"] != AUTHORITY or line["claim_status"] != CLAIM_STATUS
            or line["retention_status"] != RETENTION_STATUS):
        raise TrustLineError("trust line cannot claim performance, selection authority or durability")
    if line["e1_basis"] not in dq.E1_BASES:
        raise TrustLineError("trust line e1_basis is invalid")
    if set(line["source_binding"]) != set(SOURCE_BINDING_KEYS):
        raise TrustLineError("trust line source_binding keys are invalid")
    metrics = line["metrics"]
    if [m.get("metric_id") for m in metrics] != list(METRIC_IDS):
        raise TrustLineError("trust line metrics are not the closed T1..T7 set in order")
    for m in metrics:
        if set(m) != set(METRIC_KEYS):
            raise TrustLineError(f"metric keys are invalid: {m.get('metric_id')}")
        _mid, kind, direction, threshold = SPEC_BY_ID[m["metric_id"]]
        if (m["kind"], m["direction"], m["threshold"], m["min_n"]) != (kind, direction, threshold, MIN_N):
            raise TrustLineError(f"metric spec drifted: {m['metric_id']}")
        if m["not_computable_reason"] not in NC_REASONS or m["reliance"] not in RELIANCE:
            raise TrustLineError(f"metric vocabulary is invalid: {m['metric_id']}")
        if m["not_computable_reason"] is not None:
            expected = metric(m["metric_id"], not_computable_reason=m["not_computable_reason"], note=m["note"])
        else:
            if not all(isinstance(m[k], int) and not isinstance(m[k], bool) and m[k] >= 0
                       for k in ("numerator", "denominator", "unparsed_count")) or m["numerator"] > m["denominator"]:
                raise TrustLineError(f"metric counts are invalid: {m['metric_id']}")
            expected = metric(m["metric_id"], numerator=m["numerator"], denominator=m["denominator"],
                              unparsed_count=m["unparsed_count"], note=m["note"])
        # Level, rate and reliance are recomputed, never self-reported: a rate
        # under MIN_N must be null and can never be rendered as 0.
        if m != expected:
            raise TrustLineError(f"metric level/rate/reliance is not derived from its counts: {m['metric_id']}")
    roll = line["rolling"]
    if set(roll) != {"window_runs", "per_metric"} or roll["window_runs"] != WINDOW_RUNS \
            or set(roll["per_metric"]) != set(METRIC_IDS):
        raise TrustLineError("trust line rolling block is invalid")
    for metric_id, pooled in roll["per_metric"].items():
        if set(pooled) != {"distinct_rows", "pooled_numerator", "pooled_denominator", "level"}:
            raise TrustLineError(f"rolling keys are invalid: {metric_id}")
        if pooled["level"] not in LEVELS or pooled["pooled_denominator"] != pooled["distinct_rows"]:
            raise TrustLineError(f"rolling must pool distinct rows: {metric_id}")
        if pooled["level"] in (MEETS, MISSES) and pooled["distinct_rows"] < MIN_N:
            raise TrustLineError(f"rolling level below MIN_N distinct rows: {metric_id}")


def content_hash(line: Mapping[str, Any]) -> str:
    """Reproducible identity: excludes generated_at (a reviewer can re-run and compare)."""
    return "sha256:" + _hash({k: v for k, v in line.items() if k != "generated_at"})


# ── the hash-chained, idempotent ledger ───────────────────────────────────

def ledger_path(advisory_root: Path) -> Path:
    return advisory_root.joinpath(*LEDGER_DIR, LEDGER_NAME)


def _record_hash(record: Mapping[str, Any]) -> str:
    return _hash({k: v for k, v in record.items() if k != "hash"})


def _canonical_line(record: Mapping[str, Any]) -> str:
    return _canonical(record).decode("utf-8")


def _read_ledger_unlocked(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        anchor = Path(f"{path}.anchor.json")
        if anchor.exists():
            raise TrustLineError("trust ledger anchor exists without its ledger (truncated)")
        return []
    if path.is_symlink() or not path.is_file():
        raise TrustLineError("trust ledger is not a regular file")
    records: list[dict[str, Any]] = []
    prev = GENESIS_PREV
    for index, raw in enumerate(path.read_text(encoding="utf-8").splitlines()):
        record = json.loads(raw)
        if (
            not isinstance(record, dict) or tuple(sorted(record)) != tuple(sorted(LEDGER_RECORD_KEYS))
            or raw != _canonical_line(record) or record["seq"] != index or record["prev"] != prev
            or record["hash"] != _record_hash(record)
            or record["content_hash"] != content_hash(record["trust_line"])
        ):
            raise TrustLineError(f"trust ledger record {index} breaks the hash chain")
        prev = record["hash"]
        records.append(record)
    anchor_path = Path(f"{path}.anchor.json")
    if not anchor_path.exists():
        if records:
            raise TrustLineError("trust ledger has records but no anchor")
    else:
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        n, head = anchor.get("n"), anchor.get("head")
        if not isinstance(n, int) or n > len(records) or (n and records[n - 1]["hash"] != head):
            raise TrustLineError("trust ledger was truncated or its tail replaced")
    return records


@contextlib.contextmanager
def _ledger_lock(path: Path, exclusive: bool) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{path}.lock", "a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def read_prior_lines(advisory_root: Path | None) -> tuple[list[dict[str, Any]], str | None]:
    """Verified prior records for the rolling pool → (records, error)."""
    if advisory_root is None:
        return [], None
    path = ledger_path(advisory_root)
    if not path.exists() and not Path(f"{path}.anchor.json").exists():
        return [], None
    try:
        with _shared_lock_if_present(path):
            return _read_ledger_unlocked(path), None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {str(exc)[:160]}"


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def append_trust_line(advisory_root: Path, line: Mapping[str, Any],
                      members: Mapping[str, Any]) -> dict[str, Any]:
    """Append once per run_id; never raises — the outcome is returned for health."""
    result = {"status": None, "seq": None, "head_hash": None, "error": None,
              "location": LEDGER_REL, "retention_status": RETENTION_STATUS}
    try:
        validate_trust_line(line)
        # governance-mutation: FUNNEL_TRUST_LEDGER_SAME_RUN_ONLY
        if line["source_binding"]["e1_layer_as_of"] not in (None, line["as_of"]):
            return dict(result, status="REFUSED_NOT_SAME_RUN",
                        error="trust line was computed against an E1 layer from another night")
        path = ledger_path(advisory_root)
        with _ledger_lock(path, exclusive=True):
            try:
                records = _read_ledger_unlocked(path)
            except Exception as exc:
                return dict(result, status="LEDGER_INVALID_NOT_APPENDED",
                            error=f"{type(exc).__name__}: {str(exc)[:160]}")
            digest = content_hash(line)
            for record in records:
                # governance-mutation: FUNNEL_TRUST_LEDGER_IDEMPOTENT
                if record["run_id"] == line["run_id"]:
                    status = "ALREADY_RECORDED" if record["content_hash"] == digest else "CONFLICT_NOT_APPENDED"
                    return dict(result, status=status, seq=record["seq"], head_hash=records[-1]["hash"])
            record = {
                "seq": len(records),
                "run_id": line["run_id"],
                "as_of": line["as_of"],
                "content_hash": digest,
                "trust_line": copy.deepcopy(dict(line)),
                "members": {k: dict(sorted(v.items())) for k, v in sorted(members.items())},
                "prev": records[-1]["hash"] if records else GENESIS_PREV,
            }
            record["hash"] = _record_hash(record)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(_canonical_line(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            anchor = Path(f"{path}.anchor.json")
            tmp = Path(f"{anchor}.tmp")
            tmp.write_text(json.dumps({"n": record["seq"] + 1, "head": record["hash"]}), encoding="utf-8")
            os.replace(tmp, anchor)
            _fsync_dir(path.parent)
            return dict(result, status="APPENDED", seq=record["seq"], head_hash=record["hash"])
    except Exception as exc:
        return dict(result, status="WRITE_FAILED", error=f"{type(exc).__name__}: {str(exc)[:160]}")


# ── finalize orchestration + verifier recompute ───────────────────────────

def _e1_codes(battery: Mapping[str, Any], candidate_review: Mapping[str, Any], as_of: str) -> list[str]:
    return [str(row.get("ts_code")) for row in _battery_rows(battery)] + dq.control_codes(candidate_review, as_of)


def build_finalize_extras(
    *, as_of: str, run_id: str, generated_at: str, public_v2: Path,
    advisory_root: Path | None, candidate_manifest: Mapping[str, Any],
    battery: Mapping[str, Any], candidate_review: Mapping[str, Any], scan: Mapping[str, Any],
    deep_queue: Mapping[str, Any], registry_projected: Mapping[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Return ({file: payload} for the finalize stage, context for health/ledger).

    Missing or other-run E1/macro/ledger inputs degrade to UNAVAILABLE /
    NOT_COMPUTABLE; they never refuse the finalize step.
    """
    e1_raw, run_manifest = dq.load_e1_inputs(public_v2, run_id)
    basis, e1, e1_reason = dq.resolve_e1_basis(
        e1_raw, as_of=as_of, scan=scan, codes=_e1_codes(battery, candidate_review, as_of),
        run_manifest=run_manifest,
    )
    queue = dq.build_queue(
        as_of=as_of, run_id=run_id, generated_at=generated_at,
        candidate_manifest=candidate_manifest, battery=battery, candidate_review=candidate_review,
        scan=scan, registry_projected=registry_projected, e1=e1, e1_basis=basis,
    )
    prior, prior_error = read_prior_lines(advisory_root)
    line, members = build_trust_line(
        as_of=as_of, run_id=run_id, generated_at=generated_at, queue=queue, battery=battery,
        scan=scan, deep_queue=deep_queue, candidate_manifest=candidate_manifest, e1=e1,
        e1_basis=basis, macro=read_macro(public_v2 / "macro", run_id=run_id, as_of=as_of),
        u4=read_u4_decisions(advisory_root, run_id),
        adjudication=read_adjudications(advisory_root, run_id, queue),
        prior=[record for record in prior if record.get("run_id") != run_id],
    )
    files = {dq.QUEUE_FILE: queue, TRUST_FILE: line}
    return files, {"members": members, "e1_reason": e1_reason, "prior_error": prior_error}


def health_updates(files: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """New top-level funnel_health keys (never inside battery_coverage)."""
    return {
        "disagreement_summary": dq.summarize(files[dq.QUEUE_FILE]),
        "research_trust": copy.deepcopy(dict(files[TRUST_FILE])),
    }


def verify_finalize_extras(
    health: Mapping[str, Any], *, bundle_dir: Path, payloads: Mapping[str, Any],
    public_v2: Path,
) -> dict[str, Any] | None:
    """Recompute the queue and the machine trust metrics from the durable bundle.

    Returns None for a legacy bundle (neither the finalize-stage files nor the
    health keys exist).  Raises ValueError on any mismatch.
    """
    import funnel_dag  # noqa: WPS433

    as_of = str(health.get("as_of") or "")
    run_id = str(health.get("run_id") or "")
    stage: dict[str, Any] = {}
    stage_payloads: dict[str, Any] = {}
    # Pre-DAG (single-step) bundles have no stage manifests at all.
    if os.path.lexists(bundle_dir / "stage_finalize.json"):
        try:
            stage, stage_payloads = funnel_dag._read_stage(
                bundle_dir, "finalize", as_of=as_of, run_id=run_id)
        except FunnelError as exc:
            raise ValueError(f"finalize stage evidence is unreadable: {exc}") from exc
    extras = [name for name in FINALIZE_EXTRA_FILES if name in stage_payloads]
    keys = [key for key in ("disagreement_summary", "research_trust") if key in health]
    # governance-mutation: FUNNEL_TRUST_PRESENCE_BOUND
    if (len(extras), len(keys)) not in {(0, 0), (2, 2)}:
        raise ValueError(f"finalize extras and health keys are not bound together: files={extras} keys={keys}")
    if not extras:
        return None
    if "candidate_battery.json" not in payloads or "candidate_manifest.json" not in payloads:
        raise ValueError("finalize extras cannot be recomputed without the candidate battery evidence")
    queue_file = stage_payloads[dq.QUEUE_FILE]
    trust_file = stage_payloads[TRUST_FILE]
    generated_at = stage["generated_at"]
    scan = payloads["all_market_scan.json"]
    battery = payloads["candidate_battery.json"]
    candidates = payloads["candidate_review.json"]
    e1_raw, run_manifest = dq.load_e1_inputs(public_v2, run_id)
    basis, e1, _reason = dq.resolve_e1_basis(
        e1_raw, as_of=as_of, scan=scan, codes=_e1_codes(battery, candidates, as_of),
        run_manifest=run_manifest,
    )
    recorded_basis = (queue_file.get("source_bindings") or {}).get("e1_basis")
    if basis != recorded_basis and not (
        recorded_basis == dq.E1_SAME_AS_OF and basis == dq.E1_SAME_RUN
    ):
        raise ValueError(f"E1 basis does not replay: recorded {recorded_basis}, measured {basis}")
    if recorded_basis != basis:
        basis = recorded_basis  # published after finalize: the same bytes are now run-manifest bound
    queue = dq.build_queue(
        as_of=as_of, run_id=run_id, generated_at=generated_at,
        candidate_manifest=payloads["candidate_manifest.json"], battery=battery,
        candidate_review=candidates, scan=scan,
        registry_projected=payloads.get("security_registry_projected.json"),
        e1=e1, e1_basis=basis,
    )
    try:
        validate_trust_line(trust_file)
    except TrustLineError as exc:
        raise ValueError(f"research trust line is invalid: {exc}") from exc
    machine, _members = machine_metrics(
        battery=battery, scan=scan, e1=e1, e1_basis=basis,
        macro=read_macro(public_v2 / "macro", run_id=run_id, as_of=as_of),
    )
    recorded = {m["metric_id"]: m for m in trust_file["metrics"]}
    binding = trust_file["source_binding"]
    expected_binding = {
        "candidate_manifest_hash": payloads["candidate_manifest.json"].get("manifest_hash"),
        "battery_rows_hash": battery.get("rows_hash"),
        "queue_rows_hash": queue["rows_hash"],
        "e1_layer_rows_hash": e1.get("rows_hash") if e1 is not None else None,
        "e1_layer_as_of": e1.get("as_of") if e1 is not None else None,
    }
    return {
        "queue_file": queue_file,
        "queue_recomputed": queue,
        "summary_recomputed": dq.summarize(queue),
        "trust_file": trust_file,
        "trust_identity_ok": (
            trust_file["as_of"] == as_of and trust_file["run_id"] == run_id
            and trust_file["generated_at"] == generated_at and trust_file["e1_basis"] == basis
            and all(binding.get(k) == v for k, v in expected_binding.items())
        ),
        "machine_recorded": [recorded[m["metric_id"]] for m in machine],
        "machine_recomputed": machine,
    }


# ── offline replay CLI (never writes the ledger) ──────────────────────────

def replay(bundle_dir: Path, *, e1_path: Path | None, run_manifest_path: Path | None,
           macro_dir: Path | None, advisory_root: Path | None) -> dict[str, Any]:
    import funnel_dag  # noqa: WPS433

    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    as_of, run_id = str(manifest["as_of"]), str(manifest["run_id"])
    _s1, p1 = funnel_dag._read_stage(bundle_dir, "candidates", as_of=as_of, run_id=run_id)
    _s2, p2 = funnel_dag._read_stage(bundle_dir, "battery", as_of=as_of, run_id=run_id)
    _s3, p3 = funnel_dag._read_stage(bundle_dir, "finalize", as_of=as_of, run_id=run_id)
    scan, candidates = p1["all_market_scan.json"], p1["candidate_review.json"]
    battery = p2["candidate_battery.json"]
    e1_raw = e1_path.read_bytes() if e1_path is not None else None
    run_manifest = (json.loads(run_manifest_path.read_text(encoding="utf-8"))
                    if run_manifest_path is not None else None)
    basis, e1, reason = dq.resolve_e1_basis(
        e1_raw, as_of=as_of, scan=scan, codes=_e1_codes(battery, candidates, as_of),
        run_manifest=run_manifest,
    )
    generated_at = _s3["generated_at"]
    queue = dq.build_queue(
        as_of=as_of, run_id=run_id, generated_at=generated_at,
        candidate_manifest=p1["candidate_manifest.json"], battery=battery,
        candidate_review=candidates, scan=scan,
        registry_projected=p3.get("security_registry_projected.json"), e1=e1, e1_basis=basis,
    )
    prior, _error = read_prior_lines(advisory_root)
    line, _members = build_trust_line(
        as_of=as_of, run_id=run_id, generated_at=generated_at, queue=queue, battery=battery,
        scan=scan, deep_queue=p3["deep_research_queue.json"],
        candidate_manifest=p1["candidate_manifest.json"], e1=e1, e1_basis=basis,
        macro=read_macro(macro_dir, run_id=run_id, as_of=as_of),
        u4=read_u4_decisions(advisory_root, run_id),
        adjudication=read_adjudications(advisory_root, run_id, queue),
        prior=[record for record in prior if record.get("run_id") != run_id],
    )
    return {"queue": queue, "trust_line": line, "e1_reason": reason,
            "content_hash": content_hash(line)}


def _summary(result: Mapping[str, Any]) -> dict[str, Any]:
    line = result["trust_line"]
    return {
        "as_of": line["as_of"], "run_id": line["run_id"], "e1_basis": line["e1_basis"],
        "e1_reason": result["e1_reason"], "queue_counts": result["queue"]["counts"],
        "queue_rows_hash": result["queue"]["rows_hash"], "trust_content_hash": result["content_hash"],
        "metrics": [
            {k: m[k] for k in ("metric_id", "numerator", "denominator", "rate", "level",
                               "not_computable_reason", "reliance")}
            for m in line["metrics"]
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline disagreement-queue / trust-line replay (no ledger writes).")
    sub = parser.add_subparsers(dest="command", required=True)
    rp = sub.add_parser("replay")
    rp.add_argument("--bundle-dir", type=Path, required=True)
    rp.add_argument("--e1", type=Path)
    rp.add_argument("--run-manifest", type=Path)
    rp.add_argument("--macro-dir", type=Path)
    rp.add_argument("--advisory-root", type=Path, help="read-only: U4/adjudication/trust ledgers")
    rp.add_argument("--out", type=Path, help="scratch directory for the two JSON files (must not exist)")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        result = replay(args.bundle_dir, e1_path=args.e1, run_manifest_path=args.run_manifest,
                        macro_dir=args.macro_dir, advisory_root=args.advisory_root)
    except (FunnelError, OSError, ValueError, KeyError) as exc:
        print(f"REFUSED: {exc}")
        return 1
    if args.out is not None:
        if os.path.lexists(args.out):
            print(f"REFUSED: output directory already exists: {args.out}")
            return 1
        args.out.mkdir(parents=True)
        for name, payload in ((dq.QUEUE_FILE, result["queue"]), (TRUST_FILE, result["trust_line"])):
            (args.out / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    print(json.dumps(_summary(result), ensure_ascii=False, indent=1))
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
