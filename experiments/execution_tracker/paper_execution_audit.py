#!/usr/bin/env python3
"""Read-only behavioral audit for the inherited paper execution engine.

The audit never edits an input ledger and never upgrades historical simulation
results. It executes deterministic offline probes against the imported engine,
then binds the receipt to the exact engine and input snapshot bytes.
"""

from __future__ import annotations

import argparse
import copy
import errno
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import model_paper_fund as fund_engine  # noqa: E402
import paper_portfolio as fill_engine  # noqa: E402


SCHEMA = "ar.paper_execution_audit_receipt.v1"
AUDIT_VERSION = "paper-execution-audit/v1"
CASE_STATUSES = {"PASS", "FAIL", "DATA_BLOCKED"}
HISTORICAL_STATUS = "UNVERIFIED_SIMULATION"


class AuditError(RuntimeError):
    """Fail-closed input, receipt, or append-only output error."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical(value))


def _strict_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise AuditError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _reject_constant(token: str) -> None:
    raise AuditError(f"non-finite JSON constant: {token}")


def _load_snapshot(path: Path, expected: type) -> tuple[Any, dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        raise AuditError(f"input must be a regular non-symlink file: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"invalid JSON input {path}: {exc}") from exc
    if not isinstance(value, expected):
        raise AuditError(f"{path} must contain {expected.__name__}")
    return value, {"path": str(path), "sha256": _sha_bytes(raw), "bytes": len(raw)}


def _validate_timestamp(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuditError("audited_at must be a non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditError("audited_at must be valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise AuditError("audited_at must include a timezone")
    return parsed.isoformat()


def _entry(*, status: str = "pending") -> dict[str, Any]:
    row: dict[str, Any] = {
        "entry_id": "AUDIT.SZ_20260101_AUDIT",
        "ticker": "AUDIT.SZ",
        "name": "Audit Fixture",
        "theme": "AUDIT",
        "setup": "AUDIT",
        "direction": "long",
        "registered_at": "20260101",
        "entry_review_price": 100.0,
        "stop_reference": 95.0,
        "take_profit_reference": 110.0,
        "shares": 1_000,
        "notional": 100_000.0,
        "no_trade_flag": True,
        "sample_eligible": False,
        "status": status,
        "fill_date": None,
        "fill_price": None,
        "exit_date": None,
        "exit_price": None,
        "exit_reason": None,
        "paper_return": None,
        "realized_R": None,
        "pnl_cny": None,
    }
    if status == "filled":
        row["fill_date"] = "20260102"
        row["fill_price"] = 100.0
    return row


def _bar(date: str, open_: float, high: float, low: float, close: float, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "date": date,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
    }
    row.update(extra)
    return row


def _case(
    case_id: str,
    requirement: str,
    probe: Callable[[], tuple[bool, Mapping[str, Any]]],
) -> dict[str, Any]:
    try:
        passed, observed = probe()
        status = "PASS" if passed else "FAIL"
        evidence = dict(observed)
    except Exception as exc:  # A broken probe cannot certify the engine.
        status = "DATA_BLOCKED"
        evidence = {"error": f"{type(exc).__name__}: {exc}"}
    if status not in CASE_STATUSES:
        raise AuditError(f"unsupported case status: {status}")
    return {
        "case_id": case_id,
        "requirement": requirement,
        "status": status,
        "observed": evidence,
    }


def _probe_registration_cutoff() -> tuple[bool, Mapping[str, Any]]:
    order = _entry()
    fill_engine._advance(order, [_bar("20260101", 100, 110, 90, 105)])
    return order["status"] == "pending", {
        "status_after_registration_day": order["status"],
        "fill_date": order["fill_date"],
    }


def _probe_t1_sell() -> tuple[bool, Mapping[str, Any]]:
    order = _entry()
    fill_engine._advance(order, [_bar("20260102", 100, 112, 94, 101)])
    return order["status"] == "filled" and order["exit_date"] is None, {
        "status_after_fill_day": order["status"],
        "fill_date": order["fill_date"],
        "exit_date": order["exit_date"],
    }


def _probe_board_lot() -> tuple[bool, Mapping[str, Any]]:
    shares, notional, _risk = fund_engine.size_order(1_000_000.0, 100.0, 95.0, 0.01)
    return shares > 0 and shares % 100 == 0, {
        "shares": shares,
        "notional": notional,
        "required_round_lot": 100,
    }


def _probe_suspension() -> tuple[bool, Mapping[str, Any]]:
    order = _entry()
    fill_engine._advance(
        order,
        [_bar("20260102", 100, 102, 99, 101, suspended=True)],
    )
    return order["status"] == "pending", {"status_on_suspended_bar": order["status"]}


def _probe_price_limits() -> tuple[bool, Mapping[str, Any]]:
    buy = _entry()
    fill_engine._advance(
        buy,
        [_bar("20260102", 110, 110, 110, 110, pre_close=100, up_limit=110, down_limit=90)],
    )
    sell = _entry(status="filled")
    fill_engine._advance(
        sell,
        [_bar("20260103", 90, 90, 90, 90, pre_close=100, up_limit=110, down_limit=90)],
    )
    passed = buy["status"] == "pending" and sell["status"] == "filled"
    return passed, {
        "one_price_limit_up_buy_status": buy["status"],
        "one_price_limit_down_sell_status": sell["status"],
    }


def _probe_adverse_gaps() -> tuple[bool, Mapping[str, Any]]:
    order = _entry()
    fill_engine._advance(
        order,
        [
            _bar("20260102", 105, 106, 104, 105),
            _bar("20260103", 90, 94, 89, 91),
        ],
    )
    passed = order["fill_price"] == 105 and order["exit_price"] == 90
    return passed, {"fill_price": order["fill_price"], "exit_price": order["exit_price"]}


def _probe_same_bar_conservative() -> tuple[bool, Mapping[str, Any]]:
    order = _entry(status="filled")
    fill_engine._advance(order, [_bar("20260103", 100, 112, 94, 101)])
    return order["exit_price"] == 95 and order["exit_reason"] == "stop_and_target_same_bar->stop", {
        "exit_price": order["exit_price"],
        "exit_reason": order["exit_reason"],
    }


def _probe_costs() -> tuple[bool, Mapping[str, Any]]:
    fund = {"initial_capital": 1_000_000.0, "cash": 1_000_000.0, "paper_only": True}
    order = _entry()
    decisions: list[dict[str, Any]] = []
    fund_engine.process_day(
        fund,
        [order],
        decisions,
        token=None,
        series_fn=lambda *_: [
            _bar("20260102", 100, 101, 99, 100),
            _bar("20260103", 109, 111, 108, 110),
        ],
    )
    gross = order["shares"] * (order["exit_price"] - order["fill_price"])
    net = order.get("pnl_cny")
    passed = net is not None and net < gross and fund["cash"] < 1_000_000.0 + gross
    return passed, {
        "gross_pnl_cny": gross,
        "recorded_pnl_cny": net,
        "ending_cash": fund["cash"],
        "cost_fields_present": any("fee" in key or "slippage" in key for key in order),
    }


def _probe_pending_lifecycle() -> tuple[bool, Mapping[str, Any]]:
    order = _entry()
    bars = [_bar(f"202601{day:02d}", 90, 99, 89, 95) for day in range(2, 23)]
    fill_engine._advance(order, bars)
    return order["status"] in {"expired", "cancelled"}, {
        "settled_sessions_without_fill": len(bars),
        "status_after_sessions": order["status"],
        "partial_fill_fields_present": any("partial" in key for key in order),
    }


def _probe_volume_participation() -> tuple[bool, Mapping[str, Any]]:
    order = _entry()
    order["shares"] = 10_000
    fill_engine._advance(
        order,
        [_bar("20260102", 100, 101, 99, 100, volume_shares=1_000)],
    )
    return order["status"] == "pending", {
        "order_shares": order["shares"],
        "settled_volume_shares": 1_000,
        "status": order["status"],
    }


def _probe_price_basis() -> tuple[bool, Mapping[str, Any]]:
    calls: list[str] = []
    original_qfq = fill_engine.qfq_ohlc_series
    original_raw = getattr(fill_engine, "execution_ohlc_series", None)

    def adjusted_source(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append("QFQ_ADJUSTED")
        return []

    def raw_source(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append("RAW_UNADJUSTED")
        return []

    try:
        fill_engine.qfq_ohlc_series = adjusted_source
        if original_raw is not None:
            fill_engine.execution_ohlc_series = raw_source
        fill_engine.update_portfolio([_entry()], token=None)
    finally:
        fill_engine.qfq_ohlc_series = original_qfq
        if original_raw is not None:
            fill_engine.execution_ohlc_series = original_raw
    return calls == ["RAW_UNADJUSTED"], {"default_execution_source_calls": calls}


def _probe_settled_only() -> tuple[bool, Mapping[str, Any]]:
    order = _entry()
    fill_engine._advance(
        order,
        [_bar("20260102", 100, 101, 99, 100, settled=False)],
    )
    return order["status"] == "pending", {"status_on_unsettled_bar": order["status"]}


def _probe_four_ledger_reconciliation() -> tuple[bool, Mapping[str, Any]]:
    fund = {"initial_capital": 1_000_000.0, "cash": 900_000.0, "paper_only": True}
    nav = [{"date": "20260101", "nav": 1_000_000.0, "cash": 1_000_000.0, "n_positions": 0}]
    rejected = False
    try:
        fund_engine.update_nav(fund, [], nav, "20260102")
    except Exception:
        rejected = True
    return rejected, {
        "inconsistent_cash_accepted": not rejected,
        "nav_rows_after_probe": len(nav),
    }


def _run_capability_probes() -> list[dict[str, Any]]:
    return [
        _case(
            "REGISTRATION_CUTOFF",
            "Registration-day prices cannot fill a prospective order.",
            _probe_registration_cutoff,
        ),
        _case("A_SHARE_T1_SELL", "A cash-equity fill cannot be sold on its purchase date.", _probe_t1_sell),
        _case("BOARD_LOT", "A-share order size uses an explicit 100-share round lot.", _probe_board_lot),
        _case("SUSPENSION", "A suspended security cannot fill or exit.", _probe_suspension),
        _case(
            "PRICE_LIMIT_AVAILABILITY",
            "One-price limit bars cannot manufacture available fills.",
            _probe_price_limits,
        ),
        _case("ADVERSE_GAP", "Entry and stop gaps use the worse available opening price.", _probe_adverse_gaps),
        _case(
            "SAME_BAR_CONSERVATIVE",
            "A later same-bar stop/target ambiguity resolves to stop.",
            _probe_same_bar_conservative,
        ),
        _case(
            "EXECUTION_COSTS",
            "Cash and PnL include explicit commissions, duties, fees, and slippage.",
            _probe_costs,
        ),
        _case(
            "ORDER_LIFECYCLE",
            "Pending orders have explicit expiry/cancel and partial-fill semantics.",
            _probe_pending_lifecycle,
        ),
        _case(
            "VOLUME_PARTICIPATION",
            "A fill cannot exceed its declared share of settled volume.",
            _probe_volume_participation,
        ),
        _case(
            "CORPORATE_ACTION_PRICE_BASIS",
            "Execution levels and bars share a raw, auditable price basis.",
            _probe_price_basis,
        ),
        _case("SETTLED_BAR_ONLY", "Only explicitly settled, visible bars can change order state.", _probe_settled_only),
        _case(
            "FOUR_LEDGER_RECONCILIATION",
            "Cash, orders, positions, and NAV reconcile before acceptance.",
            _probe_four_ledger_reconciliation,
        ),
    ]


def _validate_rows(rows: list[Any], identity_key: str, label: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise AuditError(f"{label}[{index}] must be an object")
        identity = row.get(identity_key)
        if not isinstance(identity, str) or not identity.strip():
            raise AuditError(f"{label}[{index}].{identity_key} must be non-empty")
        if identity in seen:
            raise AuditError(f"duplicate {label} {identity_key}: {identity}")
        if row.get("no_trade_flag") is not True:
            raise AuditError(f"{label} {identity} must preserve no_trade_flag=true")
        seen.add(identity)
        out.append(row)
    return out


def _order_projections(rows: list[dict[str, Any]], failed_cases: list[str]) -> list[dict[str, Any]]:
    projections = []
    for row in rows:
        # governance-mutation: PAPER_AUDIT_HISTORY_UNVERIFIED
        status = HISTORICAL_STATUS
        projections.append({
            "entry_id": row["entry_id"],
            "ticker": row.get("ticker"),
            "observed_order_status": row.get("status"),
            "record_hash": _sha_json(row),
            "execution_evidence_status": status,
            "reason_codes": ["HISTORICAL_INPUTS_NOT_BOUND_TO_REALISM_FACTS", *failed_cases],
            "method_sample_eligible": False,
            "claim_allowed": False,
            "no_trade_flag": True,
        })
    return projections


def _signal_projections(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projections = []
    for row in rows:
        projections.append({
            "signal_id": row["signal_id"],
            "ticker": row.get("ticker"),
            "record_hash": _sha_json(row),
            "has_settled_return_fields": isinstance(row.get("returns"), dict) and bool(row.get("returns")),
            "execution_evidence_status": HISTORICAL_STATUS,
            "reason_code": "SIGNAL_RETURN_IS_NOT_EXECUTABLE_FILL_EVIDENCE",
            "method_sample_eligible": False,
            "claim_allowed": False,
            "no_trade_flag": True,
        })
    return projections


def build_receipt(
    *,
    repo_root: Path,
    orders_path: Path,
    fund_path: Path,
    nav_path: Path,
    signals_path: Path,
    audited_at: str,
) -> dict[str, Any]:
    root = repo_root.resolve()
    if root != REPO_ROOT.resolve():
        raise AuditError("repo_root must identify the checkout that loaded the audit engine")
    audited_at = _validate_timestamp(audited_at)

    orders_value, orders_binding = _load_snapshot(orders_path, list)
    fund_value, fund_binding = _load_snapshot(fund_path, dict)
    nav_value, nav_binding = _load_snapshot(nav_path, list)
    signals_value, signals_binding = _load_snapshot(signals_path, list)
    orders = _validate_rows(orders_value, "entry_id", "orders")
    signals = _validate_rows(signals_value, "signal_id", "signals")

    engine_paths = {
        "paper_portfolio": root / "experiments/execution_tracker/paper_portfolio.py",
        "model_paper_fund": root / "experiments/execution_tracker/model_paper_fund.py",
    }
    engine_bindings = {
        name: {"path": str(path), "sha256": _sha_bytes(path.read_bytes())}
        for name, path in engine_paths.items()
    }

    # governance-mutation: PAPER_AUDIT_BEHAVIORAL_PROBES
    cases = _run_capability_probes()
    if not cases or any(case.get("status") not in CASE_STATUSES for case in cases):
        raise AuditError("behavioral capability probes did not return a complete receipt")
    failed_cases = [case["case_id"] for case in cases if case["status"] != "PASS"]
    counts = {status: sum(case["status"] == status for case in cases) for status in sorted(CASE_STATUSES)}

    # The current-engine audit cannot retroactively validate historical fills.
    # governance-mutation: PAPER_AUDIT_NO_CLAIM_AUTHORITY
    claim_allowed = False
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "audit_version": AUDIT_VERSION,
        "audited_at": audited_at,
        "audit_mode": "READ_ONLY_OFFLINE",
        "current_engine_status": "REALISM_GAPS_FOUND" if failed_cases else "PROBES_PASS_CURRENT_ENGINE_ONLY",
        "historical_simulation_status": HISTORICAL_STATUS,
        "source_bindings": {
            "orders": orders_binding,
            "fund": fund_binding,
            "nav_history": nav_binding,
            "paper_signals": signals_binding,
        },
        "engine_bindings": engine_bindings,
        "capability_summary": {"total": len(cases), **counts, "failed_case_ids": failed_cases},
        "capability_cases": cases,
        "historical_projection": {
            "orders": _order_projections(orders, failed_cases),
            "paper_signals": _signal_projections(signals),
            "original_ledgers_modified": False,
        },
        "fund_snapshot_hash": _sha_json(fund_value),
        "nav_snapshot_hash": _sha_json(nav_value),
        "claim_allowed": claim_allowed,
        "method_sample_eligible": False,
        "production_authority": False,
        "no_trade_flag": True,
    }
    body["audit_id"] = hashlib.sha256(_canonical({
        "audit_version": AUDIT_VERSION,
        "audited_at": audited_at,
        "source_bindings": body["source_bindings"],
        "engine_bindings": engine_bindings,
    })).hexdigest()
    body["receipt_hash"] = _sha_json(body)

    for name, path in engine_paths.items():
        if _sha_bytes(path.read_bytes()) != engine_bindings[name]["sha256"]:
            raise AuditError(f"engine changed during audit: {name}")
    return body


def write_receipt(receipt: Mapping[str, Any], output_dir: Path) -> tuple[Path, str]:
    if output_dir.is_symlink():
        raise AuditError(f"output_dir cannot be a symlink: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_hash = receipt.get("receipt_hash")
    check = dict(receipt)
    check.pop("receipt_hash", None)
    if expected_hash != _sha_json(check):
        raise AuditError("receipt_hash does not match receipt content")
    audit_id = receipt.get("audit_id")
    if not isinstance(audit_id, str) or len(audit_id) != 64:
        raise AuditError("audit_id must be a sha256 hex digest")
    target = output_dir / f"paper-execution-audit-{audit_id}.json"
    payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"

    fd, tmp_name = tempfile.mkstemp(prefix=".paper-audit-", dir=output_dir)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp_name, target)
            status = "WRITTEN"
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            if target.is_symlink() or not target.is_file() or target.read_bytes() != payload:
                raise AuditError(f"append-only receipt collision: {target}") from exc
            status = "ALREADY_EXISTS_VERIFIED"
        dir_fd = os.open(output_dir, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return target, status


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only offline paper execution audit")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--orders", type=Path, required=True)
    parser.add_argument("--fund", type=Path, required=True)
    parser.add_argument("--nav-history", type=Path, required=True)
    parser.add_argument("--paper-signals", type=Path, required=True)
    parser.add_argument("--audited-at", required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    try:
        receipt = build_receipt(
            repo_root=args.repo_root,
            orders_path=args.orders,
            fund_path=args.fund,
            nav_path=args.nav_history,
            signals_path=args.paper_signals,
            audited_at=args.audited_at,
        )
        if args.output_dir:
            target, status = write_receipt(receipt, args.output_dir)
            print(json.dumps({"status": status, "path": str(target), "receipt": receipt}, ensure_ascii=False))
        else:
            print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (AuditError, OSError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
