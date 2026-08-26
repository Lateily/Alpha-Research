#!/usr/bin/env python3
"""Human-authorized U4-to-Model-Paper-Fund registration bridge.

This bridge does one narrow job: it turns an already selected U4 candidate and
an already sealed prospective research case into one pending *paper* order.
It never selects a security, authors research, fetches market data, submits a
broker order, or grants trade authority.

The write path is a small recoverable transaction:

    frozen plan -> exact human approval -> R-015 intent -> projections -> commit

The intent carries the complete replayable plan.  Projection writes take the
same ``nightly.lock`` used by the production runner.  A crash leaves a pending
intent; rerunning ``apply`` converges the two projections and appends the one
commit.  The Model Paper Fund daily path refuses to advance while an intent is
pending or a committed registration cannot be found in both projections.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, time
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.execution_tracker import event_ledger  # noqa: E402
from experiments.execution_tracker import model_paper_fund as paper_fund  # noqa: E402
from experiments.research_funnel import research_cycle  # noqa: E402
from experiments.research_funnel import u4_decision_ledger as u4_ledger  # noqa: E402


SCHEMA_VERSION = "1.0"
PLAN_SCHEMA = "ar.paper_registration_plan.v1"
MARKS_SCHEMA = "ar.paper_registration_marks.v1"
APPROVAL_SCHEMA = "ar.paper_registration_approval.v1"
INTENT_SCHEMA = "ar.paper_registration_intent.v1"
COMMIT_SCHEMA = "ar.paper_registration_commit.v1"
RECEIPT_SCHEMA = "ar.paper_registration_receipt.v1"
INTENT_KIND = "paper_registration_intent"
COMMIT_KIND = "paper_registration_commit"
DISCLAIMER = "不是买卖指令；研究信号，human executes."

SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ID_RE = re.compile(r"^ppr_[0-9a-f]{32}$")
INTENT_ID_RE = re.compile(r"^pri_[0-9a-f]{32}$")
COMMIT_ID_RE = re.compile(r"^prc_[0-9a-f]{32}$")
TICKER_RE = re.compile(r"^[0-9A-Z]+\.[A-Z]+$")
EVIDENCE_REF_RE = re.compile(r"^(conversation|pr|commit):.+$")

MARKS_FIELDS = {
    "schema", "schema_version", "as_of", "generated_at", "run_id",
    "source", "marks", "marks_hash", "no_trade_flag",
    "trade_authority", "production_authority",
}
PLAN_FIELDS = {
    "schema", "schema_version", "generated_at", "registration_id",
    "source_refs", "paper_request", "portfolio_marks", "portfolio_snapshot",
    "projection", "authority", "plan_hash", "disclaimer",
}
SOURCE_REF_FIELDS = {
    "case_hash", "closure_bundle_hash", "u4_receipt_hash",
    "u4_packet_hash", "u4_decision_id", "u4_decision_record_hash",
    "u4_decision_registered_at", "method_registration_hash", "marks_hash",
}
REQUEST_FIELDS = {
    "ticker", "name", "theme", "registered_at", "setup", "entry_review",
    "stop_reference", "take_profit_reference", "risk_pct", "reason",
    "invalid_if", "gate_state", "max_fill_price",
    "max_volume_participation", "execution_mode", "cost_model",
}
SNAPSHOT_FIELDS = {
    "fund_hash", "orders_hash", "decision_log_hash", "nav_history_hash",
}
PROJECTION_FIELDS = {
    "order", "order_registration_projection", "decision_log_event",
    "post_state",
}
AUTHORITY_FIELDS = {
    "paper_registration_authority", "human_approval_required",
    "no_trade_flag", "trade_authority", "production_authority",
    "claim_allowed", "sample_eligible", "method_claim_sample_eligible",
    "portfolio_promotion_eligible",
}
APPROVAL_FIELDS = {
    "schema", "schema_version", "plan_hash", "claimed_approver",
    "identity_verification", "approved_at", "authorization_text",
    "authorization_evidence_ref", "no_trade_flag", "trade_authority",
    "production_authority", "approval_hash",
}
APPROVAL_DRAFT_FIELDS = APPROVAL_FIELDS - {"approval_hash"}
INTENT_FIELDS = {
    "schema", "schema_version", "intent_id", "registration_id", "plan_hash",
    "case_hash", "registered_at", "plan", "approval", "intent_hash",
}
COMMIT_FIELDS = {
    "schema", "schema_version", "commit_id", "intent_id", "registration_id",
    "plan_hash", "committed_at", "post_state", "receipt", "commit_hash",
}
RECEIPT_FIELDS = {
    "schema", "schema_version", "status", "registration_id", "plan_hash",
    "case_hash", "u4_packet_hash", "u4_decision_id", "ticker",
    "order_entry_id", "registered_at", "committed_at", "execution_mode",
    "no_trade_flag", "trade_authority", "production_authority",
    "claim_allowed", "sample_eligible", "method_claim_sample_eligible",
    "portfolio_promotion_eligible", "receipt_hash", "disclaimer",
}
REGISTRATION_PROJECTION_FIELDS = {
    "entry_id", "paper_registration_id", "ticker", "name", "theme", "setup",
    "direction", "registered_at", "entry_review_price",
    "registered_stop_reference", "take_profit_reference", "invalid_if",
    "risk_R", "risk_budget_cny", "shares", "notional", "max_fill_price",
    "max_volume_participation", "slippage_bps", "execution_mode", "cost_model",
    "reason", "research_case_hash", "u4_packet_hash", "u4_decision_id",
    "method_registration_hash", "no_trade_flag", "trade_authority",
    "production_authority", "claim_allowed", "sample_eligible",
    "method_claim_sample_eligible", "portfolio_promotion_eligible",
}
DECISION_PROVENANCE_FIELDS = {
    "paper_registration_id", "research_case_hash", "u4_packet_hash",
    "u4_decision_id", "method_registration_hash", "no_trade_flag",
}
FORBIDDEN_ACTION_KEYS = {
    "trade_action", "buy", "sell", "real_order", "real_capital_authority",
    "formal_blocking_authority", "broker_order", "broker_account",
}
SOURCE_CONTEXT_FIELDS = {"closure_bundle", "case", "u4_ledger_path", "fund_dir"}


class PaperRegistrationError(RuntimeError):
    pass


def _strict_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PaperRegistrationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path, expected_type: type | tuple[type, ...] = dict) -> Any:
    if not path.is_file() or path.is_symlink():
        raise PaperRegistrationError(f"JSON input must be a regular file: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                PaperRegistrationError(f"non-finite JSON value: {token}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PaperRegistrationError(f"cannot read strict JSON {path}: {exc}") from exc
    if not isinstance(value, expected_type):
        raise PaperRegistrationError(f"JSON root has wrong type: {path}")
    return value


def _canonical(value: Any) -> str:
    try:
        return event_ledger.canonical(event_ledger._fixed_floats(value))
    except (TypeError, ValueError) as exc:
        raise PaperRegistrationError(f"value is not canonically serializable: {exc}") from exc


def _sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha_ref(value: Any, label: str) -> str:
    raw = str(value or "")
    candidate = raw if raw.startswith("sha256:") else f"sha256:{raw}"
    if SHA_RE.fullmatch(candidate) is None:
        raise PaperRegistrationError(f"{label} must be a sha256 digest")
    return candidate


def _without(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != field}


def _require_exact(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise PaperRegistrationError(
            f"{label} fields are not exact "
            f"(missing={sorted(fields - set(value))}, extra={sorted(set(value) - fields)})"
        )


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            keys.add(str(key))
            keys.update(_walk_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.update(_walk_keys(nested))
    return keys


def _date8(value: Any, label: str) -> str:
    raw = str(value or "")
    try:
        return datetime.strptime(raw, "%Y%m%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise PaperRegistrationError(f"{label} must be a real YYYYMMDD date") from exc


def _iso(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperRegistrationError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise PaperRegistrationError(f"{label} must be timezone-aware")
    return parsed


def _r015_timestamp(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperRegistrationError("R-015 timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=event_ledger.OPERATIONAL_TIMEZONE)
    localized = parsed.astimezone(event_ledger.OPERATIONAL_TIMEZONE)
    timespec = "microseconds" if localized.microsecond else "seconds"
    return localized.isoformat(timespec=timespec)


def _atomic_write_json(path: Path, value: Any) -> None:
    if path.is_symlink():
        raise PaperRegistrationError(f"refusing to replace symlink projection: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _sha_file_value(value: Any) -> str:
    return _sha(value)


def _load_fund_state(fund_dir: Path) -> dict[str, Any]:
    if not fund_dir.is_dir() or fund_dir.is_symlink():
        raise PaperRegistrationError("fund_dir must be a real directory")
    paths = {
        "fund": fund_dir / "fund.json",
        "orders": fund_dir / "orders.json",
        "decision_log": fund_dir / "decision_log.json",
        "nav_history": fund_dir / "nav_history.json",
    }
    state = {
        "fund": _load_json(paths["fund"], dict),
        "orders": _load_json(paths["orders"], list),
        "decision_log": _load_json(paths["decision_log"], list),
        "nav_history": _load_json(paths["nav_history"], list),
    }
    if state["fund"].get("paper_only") is not True:
        raise PaperRegistrationError("Model Paper Fund lost its paper_only boundary")
    return state


def _state_hashes(state: Mapping[str, Any]) -> dict[str, str]:
    return {
        "fund_hash": _sha_file_value(state["fund"]),
        "orders_hash": _sha_file_value(state["orders"]),
        "decision_log_hash": _sha_file_value(state["decision_log"]),
        "nav_history_hash": _sha_file_value(state["nav_history"]),
    }


def _validate_marks_payload(payload: Mapping[str, Any]) -> None:
    _require_exact(payload, MARKS_FIELDS, "portfolio marks")
    if payload.get("schema") != MARKS_SCHEMA or payload.get("schema_version") != SCHEMA_VERSION:
        raise PaperRegistrationError("portfolio marks schema/version mismatch")
    as_of = _date8(payload.get("as_of"), "portfolio marks as_of")
    generated_at = _iso(payload.get("generated_at"), "portfolio marks generated_at")
    session_close = datetime.combine(
        datetime.strptime(as_of, "%Y%m%d").date(), time(hour=15),
        tzinfo=event_ledger.OPERATIONAL_TIMEZONE,
    )
    if generated_at < session_close:
        raise PaperRegistrationError("portfolio marks were generated before the settled session close")
    if payload.get("source") != "TUSHARE_DAILY_SETTLED" or not str(payload.get("run_id") or "").strip():
        raise PaperRegistrationError("portfolio marks lack a settled source/run_id")
    marks = payload.get("marks")
    if not isinstance(marks, dict):
        raise PaperRegistrationError("portfolio marks must be an object")
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0
        for value in marks.values()
    ):
        raise PaperRegistrationError("portfolio marks must be finite positive prices")
    if payload.get("marks_hash") != _sha(marks):
        raise PaperRegistrationError("portfolio marks hash mismatch")
    if (
        payload.get("no_trade_flag") is not True
        or payload.get("trade_authority") is not False
        or payload.get("production_authority") is not False
    ):
        raise PaperRegistrationError("portfolio marks acquired trading or production authority")


def validate_marks(payload: Mapping[str, Any], orders: Sequence[Mapping[str, Any]]) -> None:
    _validate_marks_payload(payload)
    marks = payload["marks"]
    expected = {
        str(order.get("ticker") or "") for order in orders
        if order.get("status") == "filled"
    }
    # governance-mutation: PAPER_REGISTRATION_MARKS_COVERAGE
    if set(marks) != expected:
        raise PaperRegistrationError(
            f"portfolio marks must cover exactly the filled positions "
            f"(missing={sorted(expected - set(marks))}, extra={sorted(set(marks) - expected)})"
        )


def seal_marks(draft: Mapping[str, Any], orders: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if "marks_hash" in draft:
        raise PaperRegistrationError("marks draft must not predeclare marks_hash")
    payload = dict(draft)
    payload["marks_hash"] = _sha(payload.get("marks"))
    validate_marks(payload, orders)
    return payload


def _registration_projection(order: Mapping[str, Any]) -> dict[str, Any]:
    projection = {field: copy.deepcopy(order.get(field)) for field in REGISTRATION_PROJECTION_FIELDS}
    _require_exact(projection, REGISTRATION_PROJECTION_FIELDS, "order registration projection")
    return projection


def _current_u4_selection(
    *, closure_bundle: Path, u4_ledger_path: Path, ticker: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    packet = _load_json(closure_bundle / "review_packet.json", dict)
    verified = u4_ledger.verify_decision_ledger(u4_ledger_path)
    if not verified["ok"] or verified["pending_packets"]:
        raise PaperRegistrationError(
            f"U4 ledger is not clean/current: {verified.get('errors') or verified.get('pending_packets')}"
        )
    projection = u4_ledger.load_current_projection(u4_ledger_path, packet)
    if projection is None:
        raise PaperRegistrationError("U4 packet has no committed current projection")
    decisions = u4_ledger.current_packet_decisions(u4_ledger_path, packet["packet_hash"])
    matches = [event for event in decisions if event["candidate"]["ts_code"] == ticker]
    if len(matches) != 1:
        raise PaperRegistrationError("research case ticker lacks exactly one current U4 decision")
    decision = matches[0]
    # governance-mutation: PAPER_REGISTRATION_CURRENT_U4_SELECT
    if decision.get("decision") != "SELECT":
        raise PaperRegistrationError(f"current U4 decision is {decision.get('decision')}, not SELECT")
    if (
        decision.get("authority", {}).get("u4_selection_authority") != "HUMAN_JUNYAN_ONLY"
        or decision.get("authority", {}).get("trade_authority") is not False
        or decision.get("authority", {}).get("production_authority") is not False
        or decision.get("authority", {}).get("no_trade_flag") is not True
    ):
        raise PaperRegistrationError("current U4 selection authority boundary changed")
    return packet, projection, decision


def _current_u4_selection_from_records(
    *, closure_bundle: Path, records: Sequence[Mapping[str, Any]], ticker: str,
) -> tuple[dict[str, Any], None, dict[str, Any]]:
    """Resolve current U4 state from the R-015 snapshot already under flock."""
    packet = _load_json(closure_bundle / "review_packet.json", dict)
    try:
        state = u4_ledger._replay_records(records)
    except (u4_ledger.DecisionLedgerError, ValueError, OSError) as exc:
        raise PaperRegistrationError(f"U4 source snapshot is invalid: {exc}") from exc
    committed = {
        (packet_hash, receipt["closure_revision"])
        for packet_hash, receipts in state["closures"].items()
        for receipt in receipts
    }
    pending = {
        key for key in state["intents"] if key not in committed
    }
    if pending:
        raise PaperRegistrationError("U4 ledger has a pending packet transaction")
    packet_ref = _sha_ref(packet.get("packet_hash"), "closure U4 packet hash")
    closures = state["closures"].get(packet_ref, [])
    if not closures:
        raise PaperRegistrationError("closure U4 packet has no committed decision closure")
    latest = closures[-1]
    intent = state["intents"].get((packet_ref, latest["closure_revision"]))
    # The closure copy must be the packet frozen by the latest U4 intent.
    if not isinstance(intent, Mapping) or intent.get("review_packet") != packet:
        raise PaperRegistrationError("closure review packet differs from the committed U4 intent")
    matches = [
        event for (subject_packet, code), event in state["current"].items()
        if subject_packet == packet_ref and code == ticker
    ]
    if len(matches) != 1:
        raise PaperRegistrationError("research case ticker lacks exactly one current U4 decision")
    decision = copy.deepcopy(matches[0])
    # Defense in depth inside the typed boundary; exact source recomputation follows.
    if decision.get("decision") != "SELECT":
        raise PaperRegistrationError(f"current U4 decision is {decision.get('decision')}, not SELECT")
    if (
        decision.get("authority", {}).get("u4_selection_authority") != "HUMAN_JUNYAN_ONLY"
        or decision.get("authority", {}).get("trade_authority") is not False
        or decision.get("authority", {}).get("production_authority") is not False
        or decision.get("authority", {}).get("no_trade_flag") is not True
    ):
        raise PaperRegistrationError("current U4 selection authority boundary changed")
    return packet, None, decision


def _authority() -> dict[str, Any]:
    return {
        "paper_registration_authority": "HUMAN_JUNYAN_ONLY",
        "human_approval_required": True,
        "no_trade_flag": True,
        "trade_authority": False,
        "production_authority": False,
        "claim_allowed": False,
        "sample_eligible": False,
        "method_claim_sample_eligible": False,
        "portfolio_promotion_eligible": False,
    }


def _compose_registration_projection(
    *, case: Mapping[str, Any], source_refs: Mapping[str, Any],
    registration_id: str, state: Mapping[str, Any], marks: Mapping[str, Any],
    registered_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    working_fund = copy.deepcopy(state["fund"])
    working_orders = copy.deepcopy(state["orders"])
    working_decisions = copy.deepcopy(state["decision_log"])
    paper_plan = case["decision_pack"]["paper_plan"]
    smc = case["method_registration"]["smc"]
    order, message = paper_fund.register_order(
        working_fund,
        working_orders,
        working_decisions,
        ticker=case["ticker"],
        name=case["name"],
        theme=case["theme"],
        setup=case["paper_order"]["setup"],
        registered_at=registered_at,
        entry=paper_plan["entry_review"],
        stop=paper_plan["stop_reference"],
        target=paper_plan["take_profit_reference"],
        risk_pct=case["paper_order"]["risk_pct"],
        reason=case["paper_order"]["reason"],
        invalid_if=case["paper_order"]["invalid_if"],
        gate_state=case["paper_order"]["gate_state"],
        marks=marks["marks"],
        max_fill_price=smc["entry_zone"]["high"],
        cost_model=paper_fund.WORKFLOW_DEBUG_COST_MODEL,
        max_volume_participation=paper_fund.MAX_VOLUME_PARTICIPATION,
        execution_mode=paper_fund.pp.EXECUTION_MODEL_VERSION,
    )
    if order is None or message != "registered":
        raise PaperRegistrationError(f"Model Paper Fund refused the plan: {message}")
    order["entry_id"] = registration_id
    order.update({
        "paper_registration_id": registration_id,
        "registered_stop_reference": order["stop_reference"],
        "research_case_hash": source_refs["case_hash"],
        "u4_packet_hash": source_refs["u4_packet_hash"],
        "u4_decision_id": source_refs["u4_decision_id"],
        "method_registration_hash": source_refs["method_registration_hash"],
        "trade_authority": False,
        "production_authority": False,
        "claim_allowed": False,
        "method_claim_sample_eligible": False,
        "portfolio_promotion_eligible": False,
    })
    decision_event = working_decisions[-1]
    decision_event.update({
        "paper_registration_id": registration_id,
        "research_case_hash": source_refs["case_hash"],
        "u4_packet_hash": source_refs["u4_packet_hash"],
        "u4_decision_id": source_refs["u4_decision_id"],
        "method_registration_hash": source_refs["method_registration_hash"],
    })
    post_state = _state_hashes({
        "fund": working_fund,
        "orders": working_orders,
        "decision_log": working_decisions,
        "nav_history": copy.deepcopy(state["nav_history"]),
    })
    request = {
        "ticker": case["ticker"],
        "name": case["name"],
        "theme": case["theme"],
        "registered_at": registered_at,
        "setup": case["paper_order"]["setup"],
        "entry_review": paper_plan["entry_review"],
        "stop_reference": paper_plan["stop_reference"],
        "take_profit_reference": paper_plan["take_profit_reference"],
        "risk_pct": case["paper_order"]["risk_pct"],
        "reason": case["paper_order"]["reason"],
        "invalid_if": case["paper_order"]["invalid_if"],
        "gate_state": case["paper_order"]["gate_state"],
        "max_fill_price": smc["entry_zone"]["high"],
        "max_volume_participation": paper_fund.MAX_VOLUME_PARTICIPATION,
        "execution_mode": paper_fund.pp.EXECUTION_MODEL_VERSION,
        "cost_model": copy.deepcopy(paper_fund.WORKFLOW_DEBUG_COST_MODEL),
    }
    projection = {
        "order": order,
        "order_registration_projection": _registration_projection(order),
        "decision_log_event": decision_event,
        "post_state": post_state,
    }
    return request, projection


def build_plan(
    *, closure_bundle: Path, case: Mapping[str, Any], u4_ledger_path: Path,
    fund_dir: Path, marks: Mapping[str, Any], generated_at: str,
    _u4_records: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        source = research_cycle.validate_case(case, closure_bundle)
    except research_cycle.CycleError as exc:
        raise PaperRegistrationError(f"research case is invalid: {exc}") from exc
    ticker = str(case.get("ticker") or "").upper()
    if TICKER_RE.fullmatch(ticker) is None:
        raise PaperRegistrationError("research case ticker is invalid")
    if _u4_records is None:
        packet, _projection, decision = _current_u4_selection(
            closure_bundle=closure_bundle, u4_ledger_path=u4_ledger_path, ticker=ticker,
        )
    else:
        packet, _projection, decision = _current_u4_selection_from_records(
            closure_bundle=closure_bundle, records=_u4_records, ticker=ticker,
        )
    state = _load_fund_state(fund_dir)
    validate_marks(marks, state["orders"])
    registered_at = _date8(case["paper_order"]["registered_at"], "paper registered_at")
    if marks["as_of"] != registered_at:
        raise PaperRegistrationError("portfolio marks as_of must equal the paper registration date")
    plan_at = _iso(generated_at, "plan generated_at")
    if (
        plan_at < _iso(case["generated_at"], "case generated_at")
        or plan_at < _iso(marks["generated_at"], "marks generated_at")
        or plan_at < _iso(decision["registered_at"], "U4 decision registered_at")
    ):
        raise PaperRegistrationError("paper registration plan predates its frozen evidence")

    closure_manifest = _load_json(closure_bundle / "manifest.json", dict)
    source_refs = {
        "case_hash": _sha_ref(case["case_hash"], "research case hash"),
        "closure_bundle_hash": _sha_ref(
            closure_manifest["bundle_hash"], "closure bundle hash"
        ),
        "u4_receipt_hash": _sha_ref(
            case["source_refs"]["u4_receipt_hash"], "U4 review receipt hash"
        ),
        "u4_packet_hash": _sha_ref(
            decision["source"]["u4_packet_hash"], "U4 packet hash"
        ),
        "u4_decision_id": decision["decision_id"],
        "u4_decision_record_hash": _sha_ref(
            decision["record_hash"], "U4 decision record hash"
        ),
        "u4_decision_registered_at": decision["registered_at"],
        "method_registration_hash": _sha_ref(
            case["method_registration"]["registration_hash"],
            "research method registration hash",
        ),
        "marks_hash": marks["marks_hash"],
    }
    _require_exact(source_refs, SOURCE_REF_FIELDS, "plan source_refs")
    packet_hash = str(packet["packet_hash"])
    normalized_packet_hash = _sha_ref(packet_hash, "closure U4 packet hash")
    if source_refs["u4_packet_hash"] != normalized_packet_hash:
        raise PaperRegistrationError("research closure and current U4 decision use different packets")

    pre_state = _state_hashes(state)
    registration_id = "ppr_" + hashlib.sha256(_canonical({
        "source_refs": source_refs,
        "portfolio_snapshot": pre_state,
        "ticker": ticker,
        "registered_at": registered_at,
    }).encode("utf-8")).hexdigest()[:32]
    request, projection = _compose_registration_projection(
        case=case,
        source_refs=source_refs,
        registration_id=registration_id,
        state=state,
        marks=marks,
        registered_at=registered_at,
    )
    result: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "registration_id": registration_id,
        "source_refs": source_refs,
        "paper_request": request,
        "portfolio_marks": copy.deepcopy(dict(marks)),
        "portfolio_snapshot": pre_state,
        "projection": projection,
        "authority": _authority(),
        "disclaimer": DISCLAIMER,
    }
    result["plan_hash"] = _sha(result)
    validate_plan(result)
    return result


def validate_plan(plan: Mapping[str, Any]) -> None:
    _require_exact(plan, PLAN_FIELDS, "paper registration plan")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("schema_version") != SCHEMA_VERSION:
        raise PaperRegistrationError("paper registration plan schema/version mismatch")
    if ID_RE.fullmatch(str(plan.get("registration_id") or "")) is None:
        raise PaperRegistrationError("paper registration id is invalid")
    # governance-mutation: PAPER_REGISTRATION_PLAN_HASH
    if plan.get("plan_hash") != _sha(_without(plan, "plan_hash")):
        raise PaperRegistrationError("paper registration plan hash mismatch")
    _iso(plan.get("generated_at"), "plan generated_at")
    source_refs = plan.get("source_refs")
    request = plan.get("paper_request")
    marks = plan.get("portfolio_marks")
    snapshot = plan.get("portfolio_snapshot")
    projection = plan.get("projection")
    authority = plan.get("authority")
    if not all(
        isinstance(value, dict)
        for value in (source_refs, request, marks, snapshot, projection, authority)
    ):
        raise PaperRegistrationError("paper registration plan nested objects are invalid")
    _require_exact(source_refs, SOURCE_REF_FIELDS, "plan source_refs")
    _require_exact(request, REQUEST_FIELDS, "paper request")
    _require_exact(snapshot, SNAPSHOT_FIELDS, "portfolio snapshot")
    _require_exact(projection, PROJECTION_FIELDS, "plan projection")
    _require_exact(authority, AUTHORITY_FIELDS, "plan authority")
    _validate_marks_payload(marks)
    if any(SHA_RE.fullmatch(str(source_refs[field] or "")) is None for field in (
        "case_hash", "closure_bundle_hash", "u4_receipt_hash", "u4_packet_hash",
        "u4_decision_record_hash", "method_registration_hash", "marks_hash",
    )):
        raise PaperRegistrationError("paper registration source hash is invalid")
    _iso(source_refs.get("u4_decision_registered_at"), "U4 decision registered_at")
    if not str(source_refs.get("u4_decision_id") or "").strip():
        raise PaperRegistrationError("paper registration U4 decision id is empty")
    if any(SHA_RE.fullmatch(str(snapshot[field] or "")) is None for field in SNAPSHOT_FIELDS):
        raise PaperRegistrationError("portfolio snapshot hash is invalid")
    post_state = projection.get("post_state")
    # Keep malformed nested input on the contract-error path, never AttributeError.
    if not isinstance(post_state, dict):
        raise PaperRegistrationError("projection post-state must be an object")
    if any(SHA_RE.fullmatch(str(post_state.get(field) or "")) is None for field in SNAPSHOT_FIELDS):
        raise PaperRegistrationError("post-state hash is invalid")
    _require_exact(post_state, SNAPSHOT_FIELDS, "projection post-state")
    if source_refs["marks_hash"] != marks["marks_hash"]:
        raise PaperRegistrationError("plan source_refs and embedded portfolio marks differ")
    if authority != _authority() or plan.get("disclaimer") != DISCLAIMER:
        raise PaperRegistrationError("paper registration authority boundary changed")
    order = projection.get("order")
    order_projection = projection.get("order_registration_projection")
    decision = projection.get("decision_log_event")
    if not isinstance(order, dict) or not isinstance(order_projection, dict) or not isinstance(decision, dict):
        raise PaperRegistrationError("paper registration projections are invalid")
    _require_exact(order_projection, REGISTRATION_PROJECTION_FIELDS, "order registration projection")
    if order_projection != _registration_projection(order):
        raise PaperRegistrationError("order registration projection differs from the frozen order")
    # governance-mutation: PAPER_REGISTRATION_NO_ACTION_AUTHORITY
    if _walk_keys(plan) & FORBIDDEN_ACTION_KEYS:
        raise PaperRegistrationError("paper registration plan acquired a forbidden action field")
    if order.get("paper_registration_id") != plan["registration_id"] or order.get("status") != "pending":
        raise PaperRegistrationError("frozen paper order id/status is invalid")
    if order.get("execution_mode") != paper_fund.pp.EXECUTION_MODEL_VERSION:
        raise PaperRegistrationError("paper registration must use the realistic execution model")
    if (
        order.get("no_trade_flag") is not True
        or order.get("trade_authority") is not False
        or order.get("production_authority") is not False
        or order.get("claim_allowed") is not False
        or order.get("sample_eligible") is not False
        or order.get("method_claim_sample_eligible") is not False
        or order.get("portfolio_promotion_eligible") is not False
    ):
        raise PaperRegistrationError("workflow-debug paper order acquired forbidden authority")
    if decision.get("action") != "REGISTER_ORDER" or decision.get("paper_registration_id") != plan["registration_id"]:
        raise PaperRegistrationError("paper registration decision projection is invalid")
    if any(decision.get(field) != order.get(field) for field in DECISION_PROVENANCE_FIELDS):
        raise PaperRegistrationError("order and decision projections have different provenance")
    # governance-mutation: PAPER_REGISTRATION_SOURCE_PROJECTION_BINDING
    if (
        order.get("research_case_hash") != source_refs["case_hash"]
        or order.get("u4_packet_hash") != source_refs["u4_packet_hash"]
        or order.get("u4_decision_id") != source_refs["u4_decision_id"]
        or order.get("method_registration_hash") != source_refs["method_registration_hash"]
    ):
        raise PaperRegistrationError("order projection differs from the frozen source references")
    request_order_fields = {
        "ticker": "ticker",
        "name": "name",
        "theme": "theme",
        "registered_at": "registered_at",
        "setup": "setup",
        "entry_review": "entry_review_price",
        "stop_reference": "registered_stop_reference",
        "take_profit_reference": "take_profit_reference",
        "reason": "reason",
        "invalid_if": "invalid_if",
        "max_fill_price": "max_fill_price",
        "max_volume_participation": "max_volume_participation",
        "execution_mode": "execution_mode",
        "cost_model": "cost_model",
    }
    # governance-mutation: PAPER_REGISTRATION_REQUEST_ORDER_BINDING
    if any(request[source] != order.get(target) for source, target in request_order_fields.items()):
        raise PaperRegistrationError("paper request and frozen order projection differ")
    if (
        decision.get("ticker") != order.get("ticker")
        or decision.get("shares") != order.get("shares")
        or decision.get("notional") != order.get("notional")
        or decision.get("entry") != order.get("entry_review_price")
        or decision.get("stop") != order.get("registered_stop_reference")
        or decision.get("target") != order.get("take_profit_reference")
        or decision.get("risk_budget_cny") != order.get("risk_budget_cny")
        or decision.get("reason") != order.get("reason")
        or decision.get("no_trade_flag") is not True
    ):
        raise PaperRegistrationError("paper decision and frozen order projection differ")


def _validate_plan_evidence(
    *, plan: Mapping[str, Any], closure_bundle: Path, case: Mapping[str, Any],
    u4_ledger_path: Path, fund_dir: Path,
) -> None:
    validate_plan(plan)
    try:
        research_cycle.validate_case(case, closure_bundle)
    except research_cycle.CycleError as exc:
        raise PaperRegistrationError(f"research case is invalid: {exc}") from exc
    if _sha_ref(case.get("case_hash"), "research case hash") != plan["source_refs"]["case_hash"]:
        raise PaperRegistrationError("paper plan is bound to a different research case")
    closure_manifest = _load_json(closure_bundle / "manifest.json", dict)
    if _sha_ref(
        closure_manifest.get("bundle_hash"), "closure bundle hash"
    ) != plan["source_refs"]["closure_bundle_hash"]:
        raise PaperRegistrationError("paper plan is bound to a different closure bundle")
    _packet, _projection, decision = _current_u4_selection(
        closure_bundle=closure_bundle,
        u4_ledger_path=u4_ledger_path,
        ticker=case["ticker"],
    )
    if (
        decision.get("decision_id") != plan["source_refs"]["u4_decision_id"]
        or decision.get("record_hash") != plan["source_refs"]["u4_decision_record_hash"]
        or decision.get("registered_at") != plan["source_refs"]["u4_decision_registered_at"]
    ):
        raise PaperRegistrationError("paper plan is not bound to the current U4 SELECT event")
    # Rebuild from the current authoritative inputs. A self-consistent plan is
    # not evidence that its sizing, ticker, or projections came from them.
    expected = build_plan(
        closure_bundle=closure_bundle,
        case=case,
        u4_ledger_path=u4_ledger_path,
        fund_dir=fund_dir,
        marks=plan["portfolio_marks"],
        generated_at=plan["generated_at"],
    )
    # Early defense; the typed R-015 boundary independently recomputes this projection.
    if expected != plan:
        raise PaperRegistrationError("paper registration plan is not the exact current-input projection")


def validate_approval(approval: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
    _require_exact(approval, APPROVAL_FIELDS, "paper registration approval")
    if approval.get("schema") != APPROVAL_SCHEMA or approval.get("schema_version") != SCHEMA_VERSION:
        raise PaperRegistrationError("paper registration approval schema/version mismatch")
    if approval.get("approval_hash") != _sha(_without(approval, "approval_hash")):
        raise PaperRegistrationError("paper registration approval hash mismatch")
    # governance-mutation: PAPER_REGISTRATION_APPROVAL_PLAN_BINDING
    if approval.get("plan_hash") != plan.get("plan_hash"):
        raise PaperRegistrationError("paper registration approval is bound to another plan")
    approved_at = _iso(approval.get("approved_at"), "approval approved_at")
    if approved_at < _iso(plan.get("generated_at"), "plan generated_at"):
        raise PaperRegistrationError("paper registration approval predates the frozen plan")
    text = str(approval.get("authorization_text") or "")
    plan_hash = str(plan.get("plan_hash") or "")
    text_invalid = (
        len(text.strip()) < 30
        or plan_hash not in text
        or not ("批准" in text or "approve" in text.casefold())
        or not ("模拟" in text or "paper" in text.casefold())
    )
    if text_invalid:
        raise PaperRegistrationError("approval must preserve exact paper authorization text and full plan_hash")
    # governance-mutation: PAPER_REGISTRATION_APPROVAL_AUTHORITY
    if (
        approval.get("claimed_approver") != "Junyan"
        or approval.get("identity_verification") != "UNAVAILABLE"
        or EVIDENCE_REF_RE.fullmatch(str(approval.get("authorization_evidence_ref") or "")) is None
        or approval.get("no_trade_flag") is not True
        or approval.get("trade_authority") is not False
        or approval.get("production_authority") is not False
    ):
        raise PaperRegistrationError("paper registration approval authority/evidence boundary changed")


def seal_approval(draft: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    if set(draft) != APPROVAL_DRAFT_FIELDS:
        raise PaperRegistrationError("paper registration approval draft fields are not exact")
    approval = dict(draft)
    approval["approval_hash"] = _sha(approval)
    validate_approval(approval, plan)
    return approval


def _intent_id(plan_hash: str) -> str:
    return "pri_" + plan_hash.removeprefix("sha256:")[:32]


def _commit_id(plan_hash: str) -> str:
    return "prc_" + plan_hash.removeprefix("sha256:")[:32]


def _build_intent(plan: Mapping[str, Any], approval: Mapping[str, Any], outer_ts: str) -> dict[str, Any]:
    registered_at = _r015_timestamp(outer_ts)
    if _iso(registered_at, "intent registered_at") < _iso(approval["approved_at"], "approval approved_at"):
        raise PaperRegistrationError("R-015 intent timestamp predates human approval")
    intent: dict[str, Any] = {
        "schema": INTENT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "intent_id": _intent_id(plan["plan_hash"]),
        "registration_id": plan["registration_id"],
        "plan_hash": plan["plan_hash"],
        "case_hash": plan["source_refs"]["case_hash"],
        "registered_at": registered_at,
        "plan": copy.deepcopy(dict(plan)),
        "approval": copy.deepcopy(dict(approval)),
    }
    intent["intent_hash"] = _sha(intent)
    validate_intent(intent)
    return intent


def validate_intent(intent: Mapping[str, Any]) -> None:
    _require_exact(intent, INTENT_FIELDS, "paper registration intent")
    if intent.get("schema") != INTENT_SCHEMA or intent.get("schema_version") != SCHEMA_VERSION:
        raise PaperRegistrationError("paper registration intent schema/version mismatch")
    if INTENT_ID_RE.fullmatch(str(intent.get("intent_id") or "")) is None:
        raise PaperRegistrationError("paper registration intent id is invalid")
    if intent.get("intent_hash") != _sha(_without(intent, "intent_hash")):
        raise PaperRegistrationError("paper registration intent hash mismatch")
    plan = intent.get("plan")
    approval = intent.get("approval")
    if not isinstance(plan, dict) or not isinstance(approval, dict):
        raise PaperRegistrationError("paper registration intent lacks its replayable inputs")
    validate_plan(plan)
    validate_approval(approval, plan)
    if (
        intent.get("intent_id") != _intent_id(plan["plan_hash"])
        or intent.get("registration_id") != plan["registration_id"]
        or intent.get("plan_hash") != plan["plan_hash"]
        or intent.get("case_hash") != plan["source_refs"]["case_hash"]
        or _iso(intent.get("registered_at"), "intent registered_at") < _iso(approval["approved_at"], "approval approved_at")
    ):
        raise PaperRegistrationError("paper registration intent is not bound to its plan/approval")


def _build_receipt(intent: Mapping[str, Any], committed_at: str) -> dict[str, Any]:
    plan = intent["plan"]
    order = plan["projection"]["order"]
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "status": "PAPER_REGISTERED",
        "registration_id": plan["registration_id"],
        "plan_hash": plan["plan_hash"],
        "case_hash": plan["source_refs"]["case_hash"],
        "u4_packet_hash": plan["source_refs"]["u4_packet_hash"],
        "u4_decision_id": plan["source_refs"]["u4_decision_id"],
        "ticker": order["ticker"],
        "order_entry_id": order["entry_id"],
        "registered_at": intent["registered_at"],
        "committed_at": committed_at,
        "execution_mode": order["execution_mode"],
        "no_trade_flag": True,
        "trade_authority": False,
        "production_authority": False,
        "claim_allowed": False,
        "sample_eligible": False,
        "method_claim_sample_eligible": False,
        "portfolio_promotion_eligible": False,
        "disclaimer": DISCLAIMER,
    }
    receipt["receipt_hash"] = _sha(receipt)
    return receipt


def _build_commit(intent: Mapping[str, Any], outer_ts: str) -> dict[str, Any]:
    committed_at = _r015_timestamp(outer_ts)
    if _iso(committed_at, "commit committed_at") < _iso(intent["registered_at"], "intent registered_at"):
        raise PaperRegistrationError("paper registration commit predates its intent")
    commit: dict[str, Any] = {
        "schema": COMMIT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "commit_id": _commit_id(intent["plan_hash"]),
        "intent_id": intent["intent_id"],
        "registration_id": intent["registration_id"],
        "plan_hash": intent["plan_hash"],
        "committed_at": committed_at,
        "post_state": copy.deepcopy(intent["plan"]["projection"]["post_state"]),
        "receipt": _build_receipt(intent, committed_at),
    }
    commit["commit_hash"] = _sha(commit)
    validate_commit(commit, intent)
    return commit


def validate_commit(commit: Mapping[str, Any], intent: Mapping[str, Any]) -> None:
    _require_exact(commit, COMMIT_FIELDS, "paper registration commit")
    if commit.get("schema") != COMMIT_SCHEMA or commit.get("schema_version") != SCHEMA_VERSION:
        raise PaperRegistrationError("paper registration commit schema/version mismatch")
    if COMMIT_ID_RE.fullmatch(str(commit.get("commit_id") or "")) is None:
        raise PaperRegistrationError("paper registration commit id is invalid")
    if commit.get("commit_hash") != _sha(_without(commit, "commit_hash")):
        raise PaperRegistrationError("paper registration commit hash mismatch")
    receipt = commit.get("receipt")
    if not isinstance(receipt, dict):
        raise PaperRegistrationError("paper registration commit lacks a receipt")
    _require_exact(receipt, RECEIPT_FIELDS, "paper registration receipt")
    if receipt.get("receipt_hash") != _sha(_without(receipt, "receipt_hash")):
        raise PaperRegistrationError("paper registration receipt hash mismatch")
    expected = _build_receipt(intent, str(commit.get("committed_at") or ""))
    if (
        commit.get("commit_id") != _commit_id(intent["plan_hash"])
        or commit.get("intent_id") != intent["intent_id"]
        or commit.get("registration_id") != intent["registration_id"]
        or commit.get("plan_hash") != intent["plan_hash"]
        or commit.get("post_state") != intent["plan"]["projection"]["post_state"]
        or receipt != expected
    ):
        raise PaperRegistrationError("paper registration commit is not the exact intent projection")


def _paper_outer_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in event_ledger._read_lines(str(path)):
        row = json.loads(line)
        if row.get("kind") in {INTENT_KIND, COMMIT_KIND}:
            records.append(row)
    return records


def _replay_registration_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    intents: dict[str, dict[str, Any]] = {}
    commits: dict[str, dict[str, Any]] = {}
    committed_cases: dict[str, str] = {}
    for outer in records:
        kind = outer.get("kind")
        payload = outer.get("payload")
        if not isinstance(payload, dict):
            raise PaperRegistrationError("paper registration outer payload is not an object")
        if kind == INTENT_KIND:
            validate_intent(payload)
            if outer.get("id") != payload["intent_id"]:
                raise PaperRegistrationError("paper registration intent outer id differs")
            if payload["registered_at"] != _r015_timestamp(outer.get("ts")):
                raise PaperRegistrationError("paper registration intent timestamp is not R-015-stamped")
            if payload["plan_hash"] in intents:
                raise PaperRegistrationError("duplicate paper registration intent plan")
            if set(intents) - set(commits):
                raise PaperRegistrationError("a second paper registration intent appeared while one was pending")
            intents[payload["plan_hash"]] = copy.deepcopy(payload)
        elif kind == COMMIT_KIND:
            intent = intents.get(str(payload.get("plan_hash") or ""))
            if intent is None:
                raise PaperRegistrationError("paper registration commit lacks its preceding intent")
            validate_commit(payload, intent)
            if outer.get("id") != payload["commit_id"]:
                raise PaperRegistrationError("paper registration commit outer id differs")
            if payload["committed_at"] != _r015_timestamp(outer.get("ts")):
                raise PaperRegistrationError("paper registration commit timestamp is not R-015-stamped")
            if payload["plan_hash"] in commits:
                raise PaperRegistrationError("duplicate paper registration commit plan")
            case_hash = intent["case_hash"]
            if case_hash in committed_cases:
                raise PaperRegistrationError("one prospective research case was registered more than once")
            committed_cases[case_hash] = payload["plan_hash"]
            commits[payload["plan_hash"]] = copy.deepcopy(payload)
        else:
            raise PaperRegistrationError(f"unexpected paper registration kind: {kind}")
    pending = sorted(set(intents) - set(commits))
    return {
        "intents": intents,
        "commits": commits,
        "committed_cases": committed_cases,
        "pending": pending,
    }


def validate_typed_outer_append(
    path: str | Path, preview: Mapping[str, Any], *, source_context: Mapping[str, Any],
) -> None:
    """Schema and source-aware R-015 boundary for registration events."""
    _require_exact(source_context, SOURCE_CONTEXT_FIELDS, "paper registration source context")
    ledger_path = Path(path)
    if Path(source_context["u4_ledger_path"]).resolve() != ledger_path.resolve():
        raise PaperRegistrationError(
            "U4 decisions and paper registration must share one R-015 ledger"
        )
    all_records = [json.loads(line) for line in event_ledger._read_lines(str(ledger_path))]
    records = [
        row for row in all_records
        if row.get("kind") in {INTENT_KIND, COMMIT_KIND}
    ]
    records.append(copy.deepcopy(dict(preview)))
    # Replay is also backed by R-015 unique-kind checks for duplicate terminal records.
    state = _replay_registration_records(records)
    payload = preview.get("payload")
    if not isinstance(payload, dict):
        raise PaperRegistrationError("typed paper registration payload is not an object")
    if preview.get("kind") == INTENT_KIND:
        context_case = source_context.get("case")
        if not isinstance(context_case, Mapping):
            raise PaperRegistrationError("typed paper registration context lacks the research case")
        expected = build_plan(
            closure_bundle=Path(source_context["closure_bundle"]),
            case=context_case,
            u4_ledger_path=Path(source_context["u4_ledger_path"]),
            fund_dir=Path(source_context["fund_dir"]),
            marks=payload["plan"]["portfolio_marks"],
            generated_at=payload["plan"]["generated_at"],
            _u4_records=all_records,
        )
        # governance-mutation: PAPER_REGISTRATION_TYPED_SOURCE_BINDING
        if expected != payload["plan"]:
            raise PaperRegistrationError("typed paper registration intent is not the exact source projection")
    elif preview.get("kind") == COMMIT_KIND:
        intent = state["intents"].get(str(payload.get("plan_hash") or ""))
        if intent is None:
            raise PaperRegistrationError("typed paper registration commit lacks its intent")
        current = _state_hashes(_load_fund_state(Path(source_context["fund_dir"])))
        # governance-mutation: PAPER_REGISTRATION_TYPED_COMMIT_PROJECTION
        if current != intent["plan"]["projection"]["post_state"]:
            raise PaperRegistrationError("typed paper registration commit precedes exact projection convergence")


def _registration_state(path: Path, *, allow_missing: bool = False) -> dict[str, Any]:
    if not path.exists():
        if allow_missing and event_ledger.read_anchor(str(path))[1] == "absent":
            return _replay_registration_records([])
        raise PaperRegistrationError("R-015 event ledger does not exist")
    if path.is_symlink() or not path.is_file():
        raise PaperRegistrationError("R-015 event ledger must be a regular file")
    chain = event_ledger.verify(str(path))
    anchor = event_ledger.verify_anchor(str(path))
    if not chain["ok"] or not anchor["ok"]:
        raise PaperRegistrationError(
            f"R-015 ledger/anchor is invalid: "
            f"{(chain.get('errors') or [])[:2] + (anchor.get('errors') or [])[:2]}"
        )
    return _replay_registration_records(_paper_outer_records(path))


def verify_registration_state(*, event_ledger_path: Path, fund_dir: Path) -> dict[str, Any]:
    try:
        ledger_state = _registration_state(event_ledger_path, allow_missing=True)
        if ledger_state["pending"]:
            raise PaperRegistrationError(f"pending paper registration intents: {ledger_state['pending']}")
        fund_state = _load_fund_state(fund_dir)
        seen_registration_ids: set[str] = set()
        for plan_hash, commit in ledger_state["commits"].items():
            intent = ledger_state["intents"][plan_hash]
            validate_commit(commit, intent)
            registration_id = commit["registration_id"]
            if registration_id in seen_registration_ids:
                raise PaperRegistrationError("duplicate committed paper registration id")
            seen_registration_ids.add(registration_id)
            orders = [
                row for row in fund_state["orders"]
                if row.get("paper_registration_id") == registration_id
            ]
            decisions = [
                row for row in fund_state["decision_log"]
                if row.get("paper_registration_id") == registration_id
            ]
            if len(orders) != 1 or len(decisions) != 1:
                raise PaperRegistrationError(
                    "committed paper registration lacks exactly one order and decision projection"
                )
            expected_plan = intent["plan"]
            # governance-mutation: PAPER_REGISTRATION_COMMITTED_ORDER_PROJECTION
            if _registration_projection(orders[0]) != expected_plan["projection"]["order_registration_projection"]:
                raise PaperRegistrationError("committed paper order immutable registration fields changed")
            # governance-mutation: PAPER_REGISTRATION_COMMITTED_DECISION_PROJECTION
            if decisions[0] != expected_plan["projection"]["decision_log_event"]:
                raise PaperRegistrationError("committed paper registration decision changed")
        return {
            "ok": True,
            "intents": len(ledger_state["intents"]),
            "commits": len(ledger_state["commits"]),
            "pending": [],
            "errors": [],
        }
    except (PaperRegistrationError, ValueError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "intents": 0, "commits": 0, "pending": [], "errors": [str(exc)]}


def assert_registration_state_ready(*, event_ledger_path: Path, fund_dir: Path) -> None:
    result = verify_registration_state(event_ledger_path=event_ledger_path, fund_dir=fund_dir)
    # governance-mutation: PAPER_REGISTRATION_DAILY_PREFLIGHT
    if not result["ok"]:
        raise PaperRegistrationError(f"paper registration state is not ready: {result['errors']}")


def _converge_projection(plan: Mapping[str, Any], fund_dir: Path, *, _fail_after: str | None = None) -> None:
    current = _load_fund_state(fund_dir)
    pre = plan["portfolio_snapshot"]
    post = plan["projection"]["post_state"]
    current_hashes = _state_hashes(current)
    for field in ("fund_hash", "nav_history_hash"):
        if current_hashes[field] != pre[field] or post[field] != pre[field]:
            raise PaperRegistrationError(f"immutable registration snapshot drifted: {field}")
    for key, field, filename, addition in (
        ("orders", "orders_hash", "orders.json", plan["projection"]["order"]),
        ("decision_log", "decision_log_hash", "decision_log.json", plan["projection"]["decision_log_event"]),
    ):
        current_hash = current_hashes[field]
        if current_hash == post[field]:
            continue
        if current_hash != pre[field]:
            raise PaperRegistrationError(f"paper registration projection drifted: {filename}")
        next_value = copy.deepcopy(current[key])
        next_value.append(copy.deepcopy(addition))
        if _sha(next_value) != post[field]:
            raise PaperRegistrationError(f"paper registration cannot reproduce frozen post-state: {filename}")
        _atomic_write_json(fund_dir / filename, next_value)
        if _fail_after == key:
            raise PaperRegistrationError(f"injected interruption after {key} projection")
        current = _load_fund_state(fund_dir)
        current_hashes = _state_hashes(current)
    final = _state_hashes(_load_fund_state(fund_dir))
    # Final defense before the typed commit boundary repeats the same state check.
    if final != post:
        raise PaperRegistrationError("paper registration projections did not converge to the frozen post-state")


@contextmanager
def _nightly_lock(path: Path) -> Iterator[None]:
    if path.is_symlink():
        raise PaperRegistrationError("nightly lock path must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            # governance-mutation: PAPER_REGISTRATION_SHARED_NIGHTLY_LOCK
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PaperRegistrationError("nightly.lock is held; refusing concurrent paper registration") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def apply_plan(
    *, plan: Mapping[str, Any], approval: Mapping[str, Any], closure_bundle: Path,
    case: Mapping[str, Any], u4_ledger_path: Path, event_ledger_path: Path,
    fund_dir: Path, nightly_lock_path: Path, _fail_after: str | None = None,
) -> dict[str, Any]:
    validate_plan(plan)
    validate_approval(approval, plan)
    if u4_ledger_path.resolve() != event_ledger_path.resolve():
        raise PaperRegistrationError(
            "U4 decisions and paper registration must share one R-015 ledger"
        )
    with _nightly_lock(nightly_lock_path):
        source_context = {
            "closure_bundle": closure_bundle,
            "case": copy.deepcopy(dict(case)),
            "u4_ledger_path": u4_ledger_path,
            "fund_dir": fund_dir,
        }
        ledger_state = _registration_state(event_ledger_path, allow_missing=True)
        existing_commit = ledger_state["commits"].get(plan["plan_hash"])
        if existing_commit is not None:
            existing_intent = ledger_state["intents"].get(plan["plan_hash"])
            if (
                existing_intent is None
                or existing_intent["plan"] != plan
                or existing_intent["approval"] != approval
            ):
                raise PaperRegistrationError("committed registration differs from the supplied inputs")
            verified = verify_registration_state(
                event_ledger_path=event_ledger_path, fund_dir=fund_dir,
            )
            if not verified["ok"]:
                raise PaperRegistrationError(f"committed registration projection is invalid: {verified['errors']}")
            return {"status": "IDEMPOTENT", "receipt": copy.deepcopy(existing_commit["receipt"])}
        existing_intent = ledger_state["intents"].get(plan["plan_hash"])
        recovering = existing_intent is not None
        if existing_intent is None:
            if ledger_state["pending"]:
                raise PaperRegistrationError("another paper registration intent is pending")
            if plan["source_refs"]["case_hash"] in ledger_state["committed_cases"]:
                raise PaperRegistrationError("the prospective research case is already registered")
            _validate_plan_evidence(
                plan=plan, closure_bundle=closure_bundle, case=case,
                u4_ledger_path=u4_ledger_path, fund_dir=fund_dir,
            )
            current_state = _load_fund_state(fund_dir)
            if _state_hashes(current_state) != plan["portfolio_snapshot"]:
                raise PaperRegistrationError("portfolio changed after plan freeze; generate a new plan")

            def build_intent(outer_ts: str) -> tuple[str, Mapping[str, Any]]:
                intent = _build_intent(plan, approval, outer_ts)
                return intent["intent_id"], intent

            event_ledger.append_paper_registration_stamped(
                INTENT_KIND, build_intent,
                source_context=source_context,
                path=str(event_ledger_path),
            )
            if _fail_after == "intent":
                raise PaperRegistrationError("injected interruption after registration intent")
            ledger_state = _registration_state(event_ledger_path)
            existing_intent = ledger_state["intents"].get(plan["plan_hash"])
        if existing_intent is None or existing_intent["plan"] != plan or existing_intent["approval"] != approval:
            raise PaperRegistrationError("pending paper registration intent differs from the supplied inputs")

        _converge_projection(plan, fund_dir, _fail_after=_fail_after)

        def build_commit(outer_ts: str) -> tuple[str, Mapping[str, Any]]:
            commit = _build_commit(existing_intent, outer_ts)
            return commit["commit_id"], commit

        event_ledger.append_paper_registration_stamped(
            COMMIT_KIND, build_commit,
            source_context=source_context,
            path=str(event_ledger_path),
        )
        if _fail_after == "commit":
            raise PaperRegistrationError("injected interruption after registration commit")
        verified = verify_registration_state(
            event_ledger_path=event_ledger_path, fund_dir=fund_dir,
        )
        if not verified["ok"]:
            raise PaperRegistrationError(f"post-commit paper registration verification failed: {verified['errors']}")
        commit = _registration_state(event_ledger_path)["commits"][plan["plan_hash"]]
        return {
            "status": "RECOVERED" if recovering else "APPLIED",
            "receipt": copy.deepcopy(commit["receipt"]),
        }


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    if os.path.lexists(path):
        raise PaperRegistrationError(f"output already exists; refusing overwrite: {path}")
    _atomic_write_json(path, value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    marks = commands.add_parser("seal-marks")
    marks.add_argument("--input", required=True, type=Path)
    marks.add_argument("--fund-dir", required=True, type=Path)
    marks.add_argument("--output", required=True, type=Path)
    plan = commands.add_parser("plan")
    plan.add_argument("--closure-bundle", required=True, type=Path)
    plan.add_argument("--case", required=True, type=Path)
    plan.add_argument("--u4-ledger", required=True, type=Path)
    plan.add_argument("--fund-dir", required=True, type=Path)
    plan.add_argument("--marks", required=True, type=Path)
    plan.add_argument("--generated-at", required=True)
    plan.add_argument("--output", required=True, type=Path)
    approval = commands.add_parser("seal-approval")
    approval.add_argument("--plan", required=True, type=Path)
    approval.add_argument("--input", required=True, type=Path)
    approval.add_argument("--output", required=True, type=Path)
    apply = commands.add_parser("apply")
    apply.add_argument("--plan", required=True, type=Path)
    apply.add_argument("--approval", required=True, type=Path)
    apply.add_argument("--closure-bundle", required=True, type=Path)
    apply.add_argument("--case", required=True, type=Path)
    apply.add_argument("--u4-ledger", required=True, type=Path)
    apply.add_argument("--event-ledger", required=True, type=Path)
    apply.add_argument("--fund-dir", required=True, type=Path)
    apply.add_argument("--nightly-lock", required=True, type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("--event-ledger", required=True, type=Path)
    verify.add_argument("--fund-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "seal-marks":
            state = _load_fund_state(args.fund_dir)
            payload = seal_marks(_load_json(args.input, dict), state["orders"])
            _write_new_json(args.output, payload)
            print(json.dumps({"status": "SEALED", "marks_hash": payload["marks_hash"]}, sort_keys=True))
        elif args.command == "plan":
            payload = build_plan(
                closure_bundle=args.closure_bundle,
                case=_load_json(args.case, dict),
                u4_ledger_path=args.u4_ledger,
                fund_dir=args.fund_dir,
                marks=_load_json(args.marks, dict),
                generated_at=args.generated_at,
            )
            _write_new_json(args.output, payload)
            print(json.dumps({"status": "PLANNED", "plan_hash": payload["plan_hash"]}, sort_keys=True))
        elif args.command == "seal-approval":
            payload = seal_approval(
                _load_json(args.input, dict), _load_json(args.plan, dict),
            )
            _write_new_json(args.output, payload)
            print(json.dumps({"status": "SEALED", "approval_hash": payload["approval_hash"]}, sort_keys=True))
        elif args.command == "apply":
            result = apply_plan(
                plan=_load_json(args.plan, dict),
                approval=_load_json(args.approval, dict),
                closure_bundle=args.closure_bundle,
                case=_load_json(args.case, dict),
                u4_ledger_path=args.u4_ledger,
                event_ledger_path=args.event_ledger,
                fund_dir=args.fund_dir,
                nightly_lock_path=args.nightly_lock,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            result = verify_registration_state(
                event_ledger_path=args.event_ledger, fund_dir=args.fund_dir,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["ok"] else 1
        return 0
    except (PaperRegistrationError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
