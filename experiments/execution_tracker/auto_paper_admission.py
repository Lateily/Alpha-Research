#!/usr/bin/env python3
"""Automatic paper-only admission after an explicit human stock selection.

The module owns no selection authority. It deterministically turns a verified
Junyan SELECT into a pending order in the existing model-paper-fund ledger.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import model_paper_fund as fund_engine
import paper_portfolio as portfolio_engine


RULE_VERSION = "AUTO_AFTER_HUMAN_PICK_V0"
SETUP = "AUTO_20D_BREAKOUT_10D_STOP_2R"
RISK_PCT = 0.005
MAX_FILL_PREMIUM = 0.02
REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_REGISTRY = REPO_ROOT / "public" / "data" / "v2" / "security_registry.json"
SELECTION_FIELDS = {
    "schema",
    "ticker",
    "name",
    "theme",
    "decision",
    "selected_by",
    "selected_at",
    "selection_ref",
    "standing_authority_ref",
    "rule_version",
    "paper_only",
    "no_trade_flag",
    "trade_authority",
    "production_authority",
}
PLAN_BAR_FIELDS = {
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume_shares",
    "amount_cny",
    "settled",
    "price_basis",
    "source",
    "source_record_hash",
    "source_payload_hash",
    "liquidity_status",
}


class AutoAdmissionError(ValueError):
    """The human selection or deterministic paper inputs are not admissible."""


@lru_cache(maxsize=1)
def _identity_registry() -> tuple[dict, dict]:
    try:
        raw = SECURITY_REGISTRY.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AutoAdmissionError("security identity registry is unreadable") from exc
    rows = document.get("rows")
    if not isinstance(rows, list):
        raise AutoAdmissionError("security identity registry rows are missing")
    identities = {
        row.get("ts_code"): row
        for row in rows
        if isinstance(row, dict) and row.get("ts_code")
    }
    metadata = {
        "registry_sha256": hashlib.sha256(raw).hexdigest(),
        "registry_as_of": document.get("as_of"),
        "registry_schema_version": document.get("schema_version"),
    }
    return identities, metadata


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def eastmoney_payload_to_plan_bars(
    payload: dict,
    *,
    ticker: str,
    expected_name: str,
) -> list[dict]:
    """Normalize a frozen public K-line response for plan calculation only.

    These rows deliberately omit pre-close and exchange limit prices, so they
    cannot be mistaken for execution bars. The fill engine still requires its
    stricter settled execution schema.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise AutoAdmissionError("public K-line payload data is missing")
    expected_code = ticker.split(".")[0]
    if str(data.get("code")) != expected_code or data.get("name") != expected_name:
        raise AutoAdmissionError(
            f"public K-line identity mismatch for {ticker}/{expected_name}"
        )
    raw_rows = data.get("klines")
    if not isinstance(raw_rows, list):
        raise AutoAdmissionError("public K-line payload rows are missing")
    payload_hash = _canonical_hash(payload)
    rows = []
    for raw in raw_rows:
        parts = str(raw).split(",")
        if len(parts) != 11:
            raise AutoAdmissionError("public K-line row shape is invalid")
        try:
            date = dt.datetime.strptime(parts[0], "%Y-%m-%d").strftime("%Y%m%d")
            open_price, close, high, low = map(float, parts[1:5])
            volume_shares = float(parts[5]) * 100.0
            amount_cny = float(parts[6])
        except (TypeError, ValueError) as exc:
            raise AutoAdmissionError("public K-line row contains invalid facts") from exc
        rows.append({
            "date": date,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume_shares": volume_shares,
            "amount_cny": amount_cny,
            "settled": True,
            "price_basis": "RAW_UNADJUSTED",
            "source": "EASTMONEY_PUBLIC_KLINE_PLAN_ONLY_V1",
            "source_record_hash": hashlib.sha256(str(raw).encode("utf-8")).hexdigest(),
            "source_payload_hash": payload_hash,
            "liquidity_status": "COMPLETE",
        })
    return sorted(rows, key=lambda row: row["date"])


def tencent_payload_to_plan_bars(
    payload: dict,
    *,
    ticker: str,
    expected_name: str,
) -> list[dict]:
    """Normalize frozen Tencent raw daily bars without inventing turnover."""
    market_prefix = "sh" if ticker.endswith(".SH") else "sz" if ticker.endswith(".SZ") else "bj"
    source_key = f"{market_prefix}{ticker.split('.')[0]}"
    data = payload.get("data") if isinstance(payload, dict) else None
    security = data.get(source_key) if isinstance(data, dict) else None
    if not isinstance(security, dict):
        raise AutoAdmissionError("Tencent raw K-line security payload is missing")
    quote = security.get("qt", {}).get(source_key)
    if (
        not isinstance(quote, list)
        or len(quote) < 3
        or quote[1] != expected_name
        or str(quote[2]) != ticker.split(".")[0]
    ):
        raise AutoAdmissionError(
            f"Tencent raw K-line identity mismatch for {ticker}/{expected_name}"
        )
    raw_rows = security.get("day")
    if not isinstance(raw_rows, list):
        raise AutoAdmissionError("Tencent raw K-line rows are missing")
    payload_hash = _canonical_hash(payload)
    rows = []
    for raw in raw_rows:
        if not isinstance(raw, list) or len(raw) < 6:
            raise AutoAdmissionError("Tencent raw K-line row shape is invalid")
        try:
            date = dt.datetime.strptime(str(raw[0]), "%Y-%m-%d").strftime("%Y%m%d")
            open_price, close, high, low, volume_shares = map(float, raw[1:6])
        except (TypeError, ValueError) as exc:
            raise AutoAdmissionError("Tencent raw K-line row contains invalid facts") from exc
        rows.append({
            "date": date,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume_shares": volume_shares,
            "amount_cny": None,
            "settled": True,
            "price_basis": "RAW_UNADJUSTED",
            "source": "TENCENT_PUBLIC_RAW_KLINE_PLAN_ONLY_V1",
            "source_record_hash": _canonical_hash(raw),
            "source_payload_hash": payload_hash,
            "liquidity_status": "DATA_BLOCKED_AMOUNT_UNAVAILABLE",
        })
    return sorted(rows, key=lambda row: row["date"])


def _validate_selection(selection: dict) -> dict:
    if not isinstance(selection, dict) or set(selection) != SELECTION_FIELDS:
        raise AutoAdmissionError("human selection fields are not exact")
    if selection.get("schema") != "ar.human_paper_selection.v1":
        raise AutoAdmissionError("human selection schema is unsupported")
    if selection.get("decision") != "SELECT" or selection.get("selected_by") != "Junyan":
        raise AutoAdmissionError("paper admission requires an explicit human SELECT by Junyan")
    if selection.get("rule_version") != RULE_VERSION:
        raise AutoAdmissionError("human selection rule version is not approved")
    if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", str(selection.get("ticker", ""))):
        raise AutoAdmissionError("human selection ticker is invalid")
    if not all(str(selection.get(field, "")).strip() for field in (
        "name", "theme", "selected_at", "selection_ref", "standing_authority_ref",
    )):
        raise AutoAdmissionError("human selection identity or authority reference is missing")
    if (
        selection.get("paper_only") is not True
        or selection.get("no_trade_flag") is not True
        or selection.get("trade_authority") is not False
        or selection.get("production_authority") is not False
    ):
        raise AutoAdmissionError("human selection must remain paper-only with no trade authority")
    identities, _ = _identity_registry()
    identity = identities.get(selection["ticker"])
    if not identity or identity.get("name") != selection["name"]:
        observed = identity.get("name") if identity else "NOT_FOUND"
        raise AutoAdmissionError(
            f"security identity mismatch: {selection['ticker']} is {observed}, "
            f"not {selection['name']}"
        )
    return identity


def _validated_bars(bars: list[dict], registered_at: str) -> list[dict]:
    if not isinstance(bars, list) or len(bars) < 20:
        raise AutoAdmissionError("automatic paper admission needs at least 20 settled bars")
    try:
        portfolio_engine._execution_date(registered_at)
        for bar in bars:
            if set(bar) == portfolio_engine.REALISTIC_BAR_FIELDS:
                portfolio_engine.validate_realistic_bar(bar)
                continue
            if set(bar) != PLAN_BAR_FIELDS:
                raise ValueError("paper plan bar fields are not exact")
            if (
                bar.get("source") not in {
                    "EASTMONEY_PUBLIC_KLINE_PLAN_ONLY_V1",
                    "TENCENT_PUBLIC_RAW_KLINE_PLAN_ONLY_V1",
                }
                or bar.get("settled") is not True
                or bar.get("price_basis") != "RAW_UNADJUSTED"
            ):
                raise ValueError("paper plan bar provenance is invalid")
            portfolio_engine._execution_date(bar.get("date"))
            prices = [bar.get(key) for key in ("open", "high", "low", "close")]
            if any(
                not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
                for value in prices
            ):
                raise ValueError("paper plan bar contains invalid prices")
            if bar["high"] < max(bar["open"], bar["low"], bar["close"]):
                raise ValueError("paper plan bar high is impossible")
            if bar["low"] > min(bar["open"], bar["high"], bar["close"]):
                raise ValueError("paper plan bar low is impossible")
            if not isinstance(bar["volume_shares"], (int, float)) or bar["volume_shares"] <= 0:
                raise ValueError("paper plan bar lacks positive volume")
            if bar["liquidity_status"] == "COMPLETE":
                if not isinstance(bar["amount_cny"], (int, float)) or bar["amount_cny"] <= 0:
                    raise ValueError("complete paper plan bar lacks positive amount")
            elif (
                bar["liquidity_status"] != "DATA_BLOCKED_AMOUNT_UNAVAILABLE"
                or bar["amount_cny"] is not None
            ):
                raise ValueError("paper plan bar liquidity status is invalid")
            for field in ("source_record_hash", "source_payload_hash"):
                if not re.fullmatch(r"[0-9a-f]{64}", str(bar.get(field, ""))):
                    raise ValueError(f"paper plan bar {field} is invalid")
    except ValueError as exc:
        raise AutoAdmissionError(str(exc)) from exc
    dates = [bar["date"] for bar in bars]
    if dates != sorted(set(dates)):
        raise AutoAdmissionError("settled bars must be strictly ordered and unique")
    if dates[-1] > registered_at:
        raise AutoAdmissionError("settled bar appears after registration date")
    return bars


def build_auto_plan(
    selection: dict,
    bars: list[dict],
    *,
    nav: float,
    registered_at: str,
    nav_basis: str = "EXPLICIT_CALLER_NAV",
    nav_marks_hash: str | None = None,
) -> dict:
    """Derive the frozen paper plan from the approved V0 rule."""
    identity = _validate_selection(selection)
    _, identity_metadata = _identity_registry()
    rows = _validated_bars(bars, registered_at)
    if not isinstance(nav, (int, float)) or not math.isfinite(nav) or nav <= 0:
        raise AutoAdmissionError("paper NAV must be a positive finite number")

    window = rows[-20:]
    entry = round(max(float(row["high"]) for row in window), 4)
    stop = round(min(float(row["low"]) for row in window[-10:]), 4)
    if not stop < entry:
        raise AutoAdmissionError("automatic structural stop must be below entry")
    target = round(entry + 2.0 * (entry - stop), 4)
    max_fill = round(entry * (1.0 + MAX_FILL_PREMIUM), 4)
    if max_fill >= target:
        raise AutoAdmissionError("automatic no-chase ceiling must remain below target")
    shares, notional, risk_budget = fund_engine.size_order(
        float(nav), max_fill, stop, RISK_PCT, selection["ticker"],
    )
    if shares <= 0:
        raise AutoAdmissionError("automatic paper sizing produced zero shares")

    plan = {
        "schema": "ar.auto_paper_plan.v1",
        "ticker": selection["ticker"],
        "name": selection["name"],
        "theme": selection["theme"],
        "identity_industry_key": identity.get("industry_key"),
        "identity_registry_sha256": identity_metadata["registry_sha256"],
        "identity_registry_as_of": identity_metadata["registry_as_of"],
        "identity_registry_schema_version": identity_metadata["registry_schema_version"],
        "registered_at": registered_at,
        "nav_cny": round(float(nav), 2),
        "nav_basis": nav_basis,
        "nav_marks_hash": nav_marks_hash or _canonical_hash({}),
        "source_cutoff": window[-1]["date"],
        "setup": SETUP,
        "rule_version": RULE_VERSION,
        "entry_review_price": entry,
        "stop_reference": stop,
        "take_profit_reference": target,
        "max_fill_price": max_fill,
        "risk_pct": RISK_PCT,
        "shares_preview": shares,
        "notional_preview_cny": notional,
        "risk_budget_cny": risk_budget,
        "selection_hash": _canonical_hash(selection),
        "source_bars_hash": _canonical_hash(window),
        "source_payload_hash": window[-1].get("source_payload_hash"),
        "source_liquidity_status": window[-1].get("liquidity_status", "COMPLETE"),
        "execution_mode": portfolio_engine.EXECUTION_MODEL_VERSION,
        "paper_only": True,
        "no_trade_flag": True,
        "trade_authority": False,
        "production_authority": False,
        "method_claim_sample_eligible": False,
        "portfolio_promotion_eligible": False,
        "claim_allowed": False,
    }
    plan["plan_hash"] = _canonical_hash(plan)
    return plan


def _receipt(selection: dict, plan: dict, order: dict, *, status="REGISTERED_PENDING") -> dict:
    receipt = {
        "schema": "ar.auto_paper_admission_receipt.v1",
        "ticker": selection["ticker"],
        "registered_at": plan["registered_at"],
        "selection_ref": selection["selection_ref"],
        "standing_authority_ref": selection["standing_authority_ref"],
        "selected_by": selection["selected_by"],
        "selection_hash": plan["selection_hash"],
        "source_bars_hash": plan["source_bars_hash"],
        "plan_hash": plan["plan_hash"],
        "entry_id": order["entry_id"],
        "status": status,
        "paper_only": True,
        "no_trade_flag": True,
        "method_claim_sample_eligible": False,
    }
    receipt["receipt_hash"] = _canonical_hash(receipt)
    return receipt


@contextmanager
def _ledger_lock(fund_dir: Path):
    lock_path = fund_dir / ".auto_admission.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise AutoAdmissionError("automatic paper admission is already in progress") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def _admit_selection_locked(
    *,
    selection: dict,
    bars: list[dict],
    fund_dir: Path,
    registered_at: str,
    marks: dict | None = None,
) -> dict:
    """Register one pending order, with exact replay idempotence."""
    fund_dir = Path(fund_dir)
    fund = fund_engine.load("fund.json", None, str(fund_dir))
    if not isinstance(fund, dict):
        raise AutoAdmissionError("model paper fund is not initialized")
    orders = fund_engine.load("orders.json", [], str(fund_dir))
    decisions = fund_engine.load("decision_log.json", [], str(fund_dir))
    receipts = fund_engine.load("auto_admission_receipts.json", [], str(fund_dir))
    filled_tickers = sorted({
        order["ticker"] for order in orders if order.get("status") == "filled"
    })
    usable_marks = {
        ticker: float((marks or {}).get(ticker))
        for ticker in filled_tickers
        if isinstance((marks or {}).get(ticker), (int, float))
        and math.isfinite(float((marks or {})[ticker]))
        and float((marks or {})[ticker]) > 0
    }
    missing_marks = [ticker for ticker in filled_tickers if ticker not in usable_marks]
    if missing_marks:
        raise AutoAdmissionError(
            f"current settled marks are required for filled positions: {missing_marks}"
        )
    nav = fund_engine.current_nav(
        fund, orders, usable_marks, require_complete_marks=bool(filled_tickers),
    )
    nav_basis = "CURRENT_SETTLED_MARKS" if filled_tickers else "CASH_ONLY"
    plan = build_auto_plan(
        selection,
        bars,
        nav=nav,
        registered_at=registered_at,
        nav_basis=nav_basis,
        nav_marks_hash=_canonical_hash(usable_marks),
    )

    existing = next(
        (item for item in receipts if item.get("plan_hash") == plan["plan_hash"]),
        None,
    )
    if existing is not None:
        return {"status": "IDEMPOTENT", "plan": plan, "receipt": existing}
    existing_order = next(
        (order for order in orders if order.get("auto_plan_hash") == plan["plan_hash"]),
        None,
    )
    if existing_order is not None:
        if not any(event.get("auto_plan_hash") == plan["plan_hash"] for event in decisions):
            decisions.append({
                "date": registered_at,
                "action": "RECOVER_ADMISSION",
                "ticker": selection["ticker"],
                "admission_mode": RULE_VERSION,
                "human_selection_ref": selection["selection_ref"],
                "auto_plan_hash": plan["plan_hash"],
                "reason": "recovered missing projections for an existing automatic paper order",
                "paper_only": True,
                "no_trade_flag": True,
                "trade_authority": False,
                "production_authority": False,
            })
        receipt = _receipt(
            selection, plan, existing_order, status="RECOVERED_PENDING",
        )
        receipts.append(receipt)
        fund_engine.save("decision_log.json", decisions, str(fund_dir))
        fund_engine.save("auto_admission_receipts.json", receipts, str(fund_dir))
        return {
            "status": "RECOVERED",
            "plan": plan,
            "order": existing_order,
            "receipt": receipt,
        }

    order, message = fund_engine.register_order(
        fund,
        orders,
        decisions,
        ticker=selection["ticker"],
        name=selection["name"],
        theme=selection["theme"],
        setup=SETUP,
        registered_at=registered_at,
        entry=plan["entry_review_price"],
        stop=plan["stop_reference"],
        target=plan["take_profit_reference"],
        risk_pct=RISK_PCT,
        reason=(
            f"human SELECT by {selection['selected_by']}; deterministic {RULE_VERSION}; "
            "paper-only workflow debug"
        ),
        invalid_if="close violates the frozen 10-day structural stop",
        gate_state="RECLAIM_REVIEW",
        marks=usable_marks,
        max_fill_price=plan["max_fill_price"],
        cost_model=fund_engine.WORKFLOW_DEBUG_COST_MODEL,
        max_volume_participation=fund_engine.MAX_VOLUME_PARTICIPATION,
        execution_mode=portfolio_engine.EXECUTION_MODEL_VERSION,
    )
    if order is None:
        raise AutoAdmissionError(message)

    order.update({
        "admission_mode": RULE_VERSION,
        "human_selection_ref": selection["selection_ref"],
        "human_selected_by": selection["selected_by"],
        "standing_authority_ref": selection["standing_authority_ref"],
        "selection_hash": plan["selection_hash"],
        "source_bars_hash": plan["source_bars_hash"],
        "auto_plan_hash": plan["plan_hash"],
        "method_claim_sample_eligible": False,
        "portfolio_promotion_eligible": False,
        "claim_allowed": False,
        "paper_only": True,
        "trade_authority": False,
        "production_authority": False,
    })
    decisions[-1].update({
        "admission_mode": RULE_VERSION,
        "human_selection_ref": selection["selection_ref"],
        "auto_plan_hash": plan["plan_hash"],
        "paper_only": True,
        "trade_authority": False,
        "production_authority": False,
    })
    receipt = _receipt(selection, plan, order)
    receipts.append(receipt)

    # Each projection is replaced atomically. The receipt is written last so a
    # retry never reports success before the order and decision are durable.
    fund_engine.save("orders.json", orders, str(fund_dir))
    fund_engine.save("decision_log.json", decisions, str(fund_dir))
    fund_engine.save("auto_admission_receipts.json", receipts, str(fund_dir))
    return {"status": "REGISTERED", "plan": plan, "order": order, "receipt": receipt}


def admit_selection(
    *,
    selection: dict,
    bars: list[dict],
    fund_dir: Path,
    registered_at: str,
    marks: dict | None = None,
) -> dict:
    fund_dir = Path(fund_dir)
    if not fund_dir.is_dir():
        raise AutoAdmissionError("model paper fund is not initialized")
    with _ledger_lock(fund_dir):
        return _admit_selection_locked(
            selection=selection,
            bars=bars,
            fund_dir=fund_dir,
            registered_at=registered_at,
            marks=marks,
        )


def paper_status_view(order: dict, *, mark: float | None = None, mark_date: str | None = None) -> dict:
    """Return the concrete buy point, simulated fill time, and descriptive PnL."""
    status = order.get("status")
    view = {
        "ticker": order.get("ticker"),
        "name": order.get("name"),
        "status": status,
        "buy_point": order.get("entry_review_price"),
        "buy_time": order.get("fill_date"),
        "buy_price": order.get("fill_price"),
        "stop_reference": order.get("stop_reference"),
        "take_profit_reference": order.get("take_profit_reference"),
        "shares": order.get("shares"),
        "mark_date": mark_date,
        "mark_price": mark,
        "unrealized_pnl_cny": None,
        "unrealized_return": None,
        "realized_pnl_cny": order.get("net_pnl_cny") or order.get("pnl_cny"),
        "realized_return": order.get("paper_return"),
        "paper_only": True,
        "no_trade_flag": True,
        "trade_authority": False,
    }
    if status == "filled" and isinstance(mark, (int, float)) and mark > 0:
        fill = float(order["fill_price"])
        shares = float(order["shares"])
        view["unrealized_pnl_cny"] = round((float(mark) - fill) * shares, 2)
        view["unrealized_return"] = round(float(mark) / fill - 1.0, 4)
    return view


def main(argv: list[str] | None = None, *, series_fn=None) -> int:
    parser = argparse.ArgumentParser(
        description="Auto-register a paper-only order after Junyan SELECT",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    register = subparsers.add_parser("register")
    register.add_argument("--ticker", required=True)
    register.add_argument("--name", required=True)
    register.add_argument("--theme", required=True)
    register.add_argument("--selected-by", required=True)
    register.add_argument("--selected-at", required=True)
    register.add_argument("--selection-ref", required=True)
    register.add_argument("--standing-authority-ref", required=True)
    register.add_argument("--registered-at", required=True)
    register.add_argument("--fund-dir", type=Path, required=True)
    register.add_argument("--bars-json", type=Path)
    register.add_argument("--marks-json", type=Path)
    args = parser.parse_args(argv)

    try:
        registration_day = dt.datetime.strptime(args.registered_at, "%Y%m%d").date()
    except ValueError as exc:
        raise AutoAdmissionError("registered_at must be a real YYYYMMDD date") from exc
    start_date = (registration_day - dt.timedelta(days=90)).strftime("%Y%m%d")
    if args.bars_json is not None:
        try:
            payload = json.loads(args.bars_json.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AutoAdmissionError("frozen public K-line JSON is unreadable") from exc
        if isinstance(payload.get("data"), dict) and "klines" in payload["data"]:
            bars = eastmoney_payload_to_plan_bars(
                payload, ticker=args.ticker, expected_name=args.name,
            )
        else:
            bars = tencent_payload_to_plan_bars(
                payload, ticker=args.ticker, expected_name=args.name,
            )
    else:
        token = os.environ.get("TUSHARE_TOKEN", "").strip()
        if not token:
            raise AutoAdmissionError("TUSHARE_TOKEN is required to fetch settled paper bars")
        fetch = series_fn or portfolio_engine.execution_ohlc_series
        bars = fetch(args.ticker, token, start_date)
    bars = [
        row for row in bars if str(row.get("date", "")) <= args.registered_at
    ]
    selection = {
        "schema": "ar.human_paper_selection.v1",
        "ticker": args.ticker,
        "name": args.name,
        "theme": args.theme,
        "decision": "SELECT",
        "selected_by": args.selected_by,
        "selected_at": args.selected_at,
        "selection_ref": args.selection_ref,
        "standing_authority_ref": args.standing_authority_ref,
        "rule_version": RULE_VERSION,
        "paper_only": True,
        "no_trade_flag": True,
        "trade_authority": False,
        "production_authority": False,
    }
    marks = None
    if args.marks_json is not None:
        try:
            marks = json.loads(args.marks_json.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AutoAdmissionError("settled marks JSON is unreadable") from exc
        if not isinstance(marks, dict) or any(
            not isinstance(ticker, str)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0
            for ticker, value in marks.items()
        ):
            raise AutoAdmissionError("settled marks JSON must map ticker to positive price")
    result = admit_selection(
        selection=selection,
        bars=bars,
        fund_dir=args.fund_dir,
        registered_at=args.registered_at,
        marks=marks,
    )
    plan = result["plan"]
    order = result.get("order") or next(
        item for item in fund_engine.load("orders.json", [], str(args.fund_dir))
        if item.get("auto_plan_hash") == plan["plan_hash"]
    )
    output = paper_status_view(order)
    output.update({
        "admission_status": result["status"],
        "registered_at": args.registered_at,
        "source_cutoff": plan["source_cutoff"],
        "source_bars_hash": plan["source_bars_hash"],
        "source_payload_hash": plan["source_payload_hash"],
        "source_liquidity_status": plan["source_liquidity_status"],
        "plan_hash": plan["plan_hash"],
        "max_fill_price": plan["max_fill_price"],
        "risk_pct": plan["risk_pct"],
        "nav_cny": plan["nav_cny"],
        "nav_basis": plan["nav_basis"],
        "nav_marks_hash": plan["nav_marks_hash"],
        "rule_version": RULE_VERSION,
        "method_claim_sample_eligible": False,
    })
    print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AutoAdmissionError as exc:
        print(json.dumps({"status": "DATA_BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
