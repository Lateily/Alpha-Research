#!/usr/bin/env python3
"""
Audit universe_* JSON snapshots before using them for research screens.

This is a local, deterministic guard. It does not fetch data and does not
mutate pipeline state unless --output is provided. The purpose is to prevent
screening reports from treating stale prices, ambiguous PE fields, or short
tape factors as registration-grade evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_UNIVERSE = ROOT / "public" / "data" / "universe_a.json"


def _to_float(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
        if not value or value in {"--", "-", "None", "nan", "NaN"}:
            return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _parse_dt(value: str | None):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load(path: Path):
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    stocks = payload.get("stocks")
    if not isinstance(stocks, list):
        raise ValueError(f"{path} does not contain a stocks list")
    return payload


def _coverage(stocks, field: str) -> float:
    if not stocks:
        return 0.0
    n = sum(1 for row in stocks if _to_float(row.get(field)) is not None)
    return n / len(stocks)


def _factor_values(stocks, factor: str):
    out = []
    for row in stocks:
        factors = row.get("factors") or {}
        val = _to_float(factors.get(factor))
        if val is not None:
            out.append(val)
    return out


def _factor_summary(stocks, factor: str):
    vals = _factor_values(stocks, factor)
    if not vals:
        return {"coverage": 0.0, "unique": 0, "stdev": None, "median": None}
    return {
        "coverage": len(vals) / len(stocks) if stocks else 0.0,
        "unique": len(set(round(v, 4) for v in vals)),
        "stdev": round(statistics.pstdev(vals), 6),
        "median": round(statistics.median(vals), 4),
    }


def audit_universe(payload, *, as_of: datetime, max_age_days: int, tickers: list[str]):
    meta = payload.get("_meta") or {}
    stocks = payload.get("stocks") or []
    by_ticker = {row.get("ticker"): row for row in stocks}

    errors: list[dict] = []
    warnings: list[dict] = []

    fetched_at = _parse_dt(meta.get("fetched_at"))
    age_days = None
    if fetched_at is None:
        errors.append(
            {
                "code": "missing_or_invalid_fetched_at",
                "message": "Universe snapshot has no parseable _meta.fetched_at.",
            }
        )
    else:
        age_days = (as_of.date() - fetched_at.date()).days
        if age_days > max_age_days:
            errors.append(
                {
                    "code": "stale_universe_snapshot",
                    "message": (
                        f"Universe snapshot is {age_days} calendar days old "
                        f"(max {max_age_days}). Do not use for execution or entry zones."
                    ),
                    "fetched_at": fetched_at.isoformat(),
                    "as_of": as_of.date().isoformat(),
                }
            )

    field_defs = meta.get("field_definitions") or {}
    factor_defs = meta.get("factor_definitions") or {}
    if not field_defs:
        warnings.append(
            {
                "code": "missing_field_definitions",
                "message": "Universe metadata does not state PE/price field basis.",
            }
        )
    if not factor_defs:
        warnings.append(
            {
                "code": "missing_factor_definitions",
                "message": "Universe metadata does not state factor definitions.",
            }
        )

    pe_basis = ((field_defs.get("pe") or {}).get("basis") or "").lower()
    if not pe_basis or ("not guaranteed" in pe_basis):
        warnings.append(
            {
                "code": "pe_basis_not_registration_grade",
                "message": "PE is a provider multiple, not a verified TTM/forward valuation anchor.",
            }
        )

    momentum_basis = ((factor_defs.get("momentum") or {}).get("basis") or "").lower()
    if "1-day" in momentum_basis or "change_pct" in momentum_basis or not momentum_basis:
        warnings.append(
            {
                "code": "momentum_is_short_tape",
                "message": "factors.momentum is 1-day tape rank, not 12-1 month momentum.",
            }
        )

    roe_cov = _coverage(stocks, "roe")
    quality = _factor_summary(stocks, "quality")
    if roe_cov < 0.10 or (quality["unique"] <= 3 and quality["median"] == 50.0):
        warnings.append(
            {
                "code": "quality_factor_inert_or_unbacked",
                "message": "Quality factor lacks broad ROE coverage and should not be used as quality evidence.",
                "roe_coverage": round(roe_cov, 4),
                "quality_summary": quality,
            }
        )

    ticker_checks = []
    for ticker in tickers:
        row = by_ticker.get(ticker)
        if not row:
            ticker_checks.append({"ticker": ticker, "status": "missing"})
            continue
        ticker_checks.append(
            {
                "ticker": ticker,
                "name": row.get("name"),
                "price": row.get("price"),
                "pe": row.get("pe"),
                "change_pct": row.get("change_pct"),
                "turnover_rate": row.get("turnover_rate"),
                "factors": row.get("factors") or {},
            }
        )

    verdict = "PASS"
    if warnings:
        verdict = "WARN"
    if errors:
        verdict = "BLOCKED"

    return {
        "verdict": verdict,
        "as_of": as_of.isoformat(),
        "max_age_days": max_age_days,
        "meta": {
            "fetched_at": meta.get("fetched_at"),
            "count": meta.get("count"),
            "version": meta.get("version"),
            "scorer": meta.get("scorer"),
        },
        "coverage": {
            "price": round(_coverage(stocks, "price"), 4),
            "pe": round(_coverage(stocks, "pe"), 4),
            "pb": round(_coverage(stocks, "pb"), 4),
            "roe": round(roe_cov, 4),
        },
        "factor_summaries": {
            factor: _factor_summary(stocks, factor)
            for factor in ("value", "quality", "momentum", "size", "low_vol")
        },
        "errors": errors,
        "warnings": warnings,
        "ticker_checks": ticker_checks,
    }


def _json_dump(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def selftest():
    now = datetime(2026, 6, 16, tzinfo=timezone.utc)
    stocks = [
        {
            "ticker": "A.SZ",
            "price": 10,
            "pe": 20,
            "pb": 2,
            "change_pct": 3,
            "factors": {"quality": 50, "momentum": 90},
        },
        {
            "ticker": "B.SZ",
            "price": 12,
            "pe": 30,
            "pb": 3,
            "change_pct": -1,
            "factors": {"quality": 50, "momentum": 10},
        },
    ]
    legacy = {"_meta": {"fetched_at": "2026-06-10T00:00:00", "count": 2}, "stocks": stocks}
    report = audit_universe(legacy, as_of=now, max_age_days=2, tickers=["A.SZ"])
    assert report["verdict"] == "BLOCKED"
    assert any(e["code"] == "stale_universe_snapshot" for e in report["errors"])
    assert any(w["code"] == "missing_factor_definitions" for w in report["warnings"])
    assert any(w["code"] == "quality_factor_inert_or_unbacked" for w in report["warnings"])
    assert report["ticker_checks"][0]["ticker"] == "A.SZ"

    fresh = {
        "_meta": {
            "fetched_at": "2026-06-16T00:00:00",
            "count": 2,
            "field_definitions": {"pe": {"basis": "provider valuation multiple; NOT guaranteed"}},
            "factor_definitions": {"momentum": {"basis": "cross-sectional rank of 1-day change_pct"}},
        },
        "stocks": stocks,
    }
    report = audit_universe(fresh, as_of=now, max_age_days=2, tickers=[])
    assert report["verdict"] == "WARN"
    assert not report["errors"]
    assert any(w["code"] == "momentum_is_short_tape" for w in report["warnings"])

    # Real 12-1 month momentum basis must CLEAR the short-tape warning (proves the
    # universe_momentum.py fix is recognised as registration-grade by this gate).
    clean = {
        "_meta": {
            "fetched_at": "2026-06-16T00:00:00",
            "count": 2,
            "field_definitions": {"pe": {"basis": "provider valuation multiple; NOT guaranteed"}},
            "factor_definitions": {"momentum": {
                "basis": "12-1 month HFQ-adjusted return (T-252→T-21 trading days), "
                         "cross-sectional rank",
                "status": "medium_term_trend",
            }},
        },
        "stocks": stocks,
    }
    report = audit_universe(clean, as_of=now, max_age_days=2, tickers=[])
    assert not any(w["code"] == "momentum_is_short_tape" for w in report["warnings"]), \
        "real 12-1 momentum basis should not trip the short-tape warning"
    print("universe_data_health selftest PASSED")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_UNIVERSE), help="Universe JSON path.")
    parser.add_argument("--output", help="Optional JSON output path.")
    parser.add_argument("--as-of", help="Audit date/time, ISO format. Defaults to now UTC.")
    parser.add_argument("--max-age-days", type=int, default=2, help="Max calendar age before BLOCKED.")
    parser.add_argument("--tickers", default="", help="Comma-separated tickers to echo in ticker_checks.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on BLOCKED.")
    parser.add_argument("--selftest", action="store_true", help="Run built-in tests.")
    args = parser.parse_args(argv)

    if args.selftest:
        selftest()
        return 0

    as_of = _parse_dt(args.as_of) if args.as_of else datetime.now(timezone.utc)
    if as_of is None:
        raise SystemExit("--as-of must be an ISO date/time")
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    payload = _load(Path(args.input))
    report = audit_universe(payload, as_of=as_of, max_age_days=args.max_age_days, tickers=tickers)
    if args.output:
        _json_dump(Path(args.output), report)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    if args.strict and report["verdict"] == "BLOCKED":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
