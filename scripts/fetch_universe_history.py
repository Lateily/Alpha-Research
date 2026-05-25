#!/usr/bin/env python3
"""Fetch full-universe Tushare history into columnar panel files.

This bulk fetcher is intentionally date-oriented: Tushare daily endpoints can
return the full market for one trade date in one call, which makes a 20-year
A-share panel feasible. Financial statements are fetched by report period so
announcement dates remain available for point-in-time downstream loaders.

Causal logic is valid because the store preserves trade dates and statement
announcement dates separately; downstream backtests can filter by data known as
of T. Specific runtime estimates and the 0.12s sleep default are unvalidated
operational priors based on the current Tushare tier and should be measured in
GitHub Actions.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import sys
import tempfile
import time
import types
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_START = "20050101"
DEFAULT_OUT = REPO_ROOT / "data_history" / "panel"
LIST_STATUSES = ("L", "D", "P")

PRICE_COLUMNS = [
    "ts_code",
    "trade_date",
    "close",
    "adj_factor",
    "pe",
    "pb",
    "total_mv",
    "circ_mv",
]
FINANCIAL_COLUMNS = [
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "revenue",
    "oper_cost",
    "n_income",
    "n_income_attr_p",
    "total_hldr_eqy_exc_min_int",
    "total_assets",
    "total_liab",
]
DAILY_FIELDS = "ts_code,trade_date,close"
DAILY_BASIC_FIELDS = "ts_code,trade_date,pe,pb,total_mv,circ_mv"
ADJ_FACTOR_FIELDS = "ts_code,trade_date,adj_factor"
INCOME_FIELDS = "ts_code,ann_date,f_ann_date,end_date,revenue,oper_cost,n_income,n_income_attr_p"
BALANCESHEET_FIELDS = (
    "ts_code,ann_date,f_ann_date,end_date,total_hldr_eqy_exc_min_int,total_assets,total_liab"
)
CASHFLOW_FIELDS = "ts_code,ann_date,f_ann_date,end_date"
STOCK_BASIC_FIELDS = "ts_code,symbol,name,market,list_date,delist_date,list_status"


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _today_ts() -> str:
    return date.today().strftime("%Y%m%d")


def _validate_ts_date(value: str, arg_name: str) -> str:
    text = str(value).strip()
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{arg_name} must be YYYYMMDD, got {value!r}") from exc
    return text


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _json_safe(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    try:
        if value != value:
            return None
    except (TypeError, ValueError):
        pass
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def _frame_or_empty(df, columns: list[str]) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame(columns=columns)
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)
    if df.empty:
        return pd.DataFrame(columns=columns)
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = pd.NA
    return out[columns]


def _normalize_dates_as_text(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].map(lambda v: None if pd.isna(v) else str(v))
    return out


def _filter_universe(df: pd.DataFrame, universe: Optional[set[str]]) -> pd.DataFrame:
    if universe is None or df.empty or "ts_code" not in df.columns:
        return df
    return df[df["ts_code"].astype(str).isin(universe)].copy()


def _dedupe_sort(df: pd.DataFrame, keys: list[str], columns: list[str]) -> pd.DataFrame:
    df = _frame_or_empty(df, columns)
    if df.empty:
        return df
    df = df.dropna(subset=keys)
    df = df.drop_duplicates(subset=keys, keep="last")
    return df.sort_values(keys).reset_index(drop=True)[columns]


def _parse_universe_arg(value: Optional[str]) -> Optional[list[str]]:
    if not value:
        return None
    candidate = Path(value)
    if candidate.exists():
        raw_items = []
        for line in candidate.read_text(encoding="utf-8").splitlines():
            raw_items.extend(line.replace(",", " ").split())
    else:
        raw_items = value.replace(",", " ").split()
    tickers = sorted({item.strip() for item in raw_items if item.strip()})
    if not tickers:
        raise ValueError("--universe was provided but no ts_code values were found")
    return tickers


def _quarter_periods(start: str, end: str) -> list[str]:
    start_year = int(start[:4])
    end_year = int(end[:4])
    periods = []
    for year in range(start_year, end_year + 1):
        for suffix in ("0331", "0630", "0930", "1231"):
            period = f"{year}{suffix}"
            if start <= period <= end:
                periods.append(period)
    return periods


def _install_pyarrow_selftest_stub() -> None:
    """Install a tiny in-process pyarrow substitute for offline self-tests.

    The real fetch path requires pyarrow or another parquet engine. The local
    Codex sandbox may not have pyarrow and cannot install packages, so the
    self-test uses this isolated stub to exercise the persistence code path
    without changing repository files or production behavior.
    """
    if "pyarrow" in sys.modules and "pyarrow.parquet" in sys.modules:
        return

    class _Schema:
        metadata = {}

    class _Table:
        def __init__(self, df: pd.DataFrame):
            self._df = df.copy()
            self.schema = _Schema()

        @classmethod
        def from_pandas(cls, df: pd.DataFrame, preserve_index: bool = False):
            return cls(df.reset_index(drop=True) if not preserve_index else df)

        def to_pandas(self):
            return self._df.copy()

        def replace_schema_metadata(self, _metadata):
            return self

    parquet_module = types.ModuleType("pyarrow.parquet")

    def write_table(table, path, **_kwargs):
        with open(path, "wb") as f:
            pickle.dump(table.to_pandas(), f)

    def read_table(path, **_kwargs):
        with open(path, "rb") as f:
            return _Table(pickle.load(f))

    parquet_module.write_table = write_table
    parquet_module.read_table = read_table
    pyarrow_module = types.ModuleType("pyarrow")
    pyarrow_module.__version__ = "selftest-stub"
    pyarrow_module.Table = _Table
    pyarrow_module.parquet = parquet_module
    sys.modules["pyarrow"] = pyarrow_module
    sys.modules["pyarrow.parquet"] = parquet_module


def _import_parquet(allow_selftest_stub: bool = False):
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        return pa, pq, False
    except ImportError:
        if not allow_selftest_stub:
            raise RuntimeError(
                "pyarrow is required to write parquet. Install pyarrow in the runner "
                "or use --selftest for the offline fixture."
            )
        _install_pyarrow_selftest_stub()
        import pyarrow as pa
        import pyarrow.parquet as pq

        return pa, pq, True


def _write_parquet(path: Path, df: pd.DataFrame, allow_selftest_stub: bool = False) -> bool:
    pa, pq, used_stub = _import_parquet(allow_selftest_stub=allow_selftest_stub)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df.reset_index(drop=True), preserve_index=False)
    pq.write_table(table, str(path), compression="snappy")
    return used_stub


def _read_parquet(path: Path, allow_selftest_stub: bool = False) -> pd.DataFrame:
    _pa, pq, _used_stub = _import_parquet(allow_selftest_stub=allow_selftest_stub)
    return pq.read_table(str(path)).to_pandas()


def _read_existing(path: Path, columns: list[str], allow_selftest_stub: bool) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    return _frame_or_empty(_read_parquet(path, allow_selftest_stub=allow_selftest_stub), columns)


def _call_api(pro, api_name: str, sleep_seconds: float, errors: list[dict], **kwargs):
    try:
        api = getattr(pro, api_name)
        return api(**kwargs)
    except Exception as exc:
        error = {"api": api_name, "error": f"{type(exc).__name__}: {exc}"}
        error.update({k: _json_safe(v) for k, v in kwargs.items() if k != "fields"})
        errors.append(error)
        return None
    finally:
        _sleep(sleep_seconds)


def fetch_universe(pro, requested: Optional[list[str]], sleep_seconds: float) -> tuple[list[str], int, list[dict]]:
    if requested is not None:
        return sorted(set(requested)), 0, []

    by_code = {}
    errors = []
    calls = 0
    for list_status in LIST_STATUSES:
        calls += 1
        df = _call_api(
            pro,
            "stock_basic",
            sleep_seconds,
            errors,
            exchange="",
            list_status=list_status,
            fields=STOCK_BASIC_FIELDS,
        )
        rows = _frame_or_empty(df, STOCK_BASIC_FIELDS.split(","))
        for row in rows.to_dict(orient="records"):
            ts_code = row.get("ts_code")
            if ts_code:
                by_code[str(ts_code)] = row

    return sorted(by_code), calls, errors


def fetch_trade_dates(pro, start: str, end: str, sleep_seconds: float) -> tuple[list[str], int, list[dict]]:
    errors: list[dict] = []
    df = _call_api(
        pro,
        "trade_cal",
        sleep_seconds,
        errors,
        exchange="SSE",
        is_open=1,
        start_date=start,
        end_date=end,
    )
    # BUGFIX 2026-05-25: Tushare trade_cal returns the date in `cal_date`,
    # NOT `trade_date` (only daily/daily_basic/adj_factor use trade_date).
    # The old code read `trade_date` here → empty set → 0 trade-dates → 0
    # prices → degenerate (flat) backtest. Read cal_date (fallback trade_date).
    rows = _frame_or_empty(df, ["cal_date", "trade_date", "is_open"])
    if rows.empty:
        return [], 1, errors
    out = set()
    for row in rows.to_dict(orient="records"):
        # honor is_open==1 if present (API param should already filter)
        if "is_open" in row and row.get("is_open") not in (1, "1", None):
            continue
        d = row.get("cal_date") or row.get("trade_date")
        if d:
            out.add(str(d))
    trade_dates = sorted(out)
    return trade_dates, 1, errors


def _merge_price_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on=["ts_code", "trade_date"], how="outer")
    return _dedupe_sort(merged, ["ts_code", "trade_date"], PRICE_COLUMNS)


def fetch_price_panel(
    pro,
    trade_dates: list[str],
    universe: set[str],
    sleep_seconds: float,
) -> tuple[pd.DataFrame, int, list[dict], dict[str, int]]:
    errors: list[dict] = []
    frames: list[pd.DataFrame] = []
    calls = 0
    endpoint_counts = {"daily": 0, "daily_basic": 0, "adj_factor": 0}
    specs = [
        ("daily", DAILY_FIELDS, ["ts_code", "trade_date", "close"]),
        ("daily_basic", DAILY_BASIC_FIELDS, ["ts_code", "trade_date", "pe", "pb", "total_mv", "circ_mv"]),
        ("adj_factor", ADJ_FACTOR_FIELDS, ["ts_code", "trade_date", "adj_factor"]),
    ]

    for trade_date in trade_dates:
        date_frames = []
        for api_name, fields, columns in specs:
            calls += 1
            endpoint_counts[api_name] += 1
            df = _call_api(pro, api_name, sleep_seconds, errors, trade_date=trade_date, fields=fields)
            frame = _filter_universe(_frame_or_empty(df, columns), universe)
            frame = _normalize_dates_as_text(frame, ["trade_date"])
            if not frame.empty:
                date_frames.append(frame)
        if date_frames:
            frames.append(_merge_price_frames(date_frames))

    if not frames:
        return pd.DataFrame(columns=PRICE_COLUMNS), calls, errors, endpoint_counts
    panel = pd.concat(frames, ignore_index=True)
    return _dedupe_sort(panel, ["ts_code", "trade_date"], PRICE_COLUMNS), calls, errors, endpoint_counts


def _collapse_statement_frame(
    df: pd.DataFrame,
    columns: list[str],
    universe: set[str],
) -> pd.DataFrame:
    frame = _filter_universe(_frame_or_empty(df, columns), universe)
    frame = _normalize_dates_as_text(frame, ["ann_date", "f_ann_date", "end_date"])
    if frame.empty:
        return frame
    frame = frame.dropna(subset=["ts_code", "end_date"])
    frame = frame.sort_values(["ts_code", "end_date", "ann_date", "f_ann_date"], na_position="last")
    return frame.drop_duplicates(subset=["ts_code", "end_date"], keep="last").reset_index(drop=True)


def _merge_financial_frames(income: pd.DataFrame, balance: pd.DataFrame) -> pd.DataFrame:
    if income.empty and balance.empty:
        return pd.DataFrame(columns=FINANCIAL_COLUMNS)

    income = income.rename(columns={"ann_date": "income_ann_date", "f_ann_date": "income_f_ann_date"})
    balance = balance.rename(columns={"ann_date": "balance_ann_date", "f_ann_date": "balance_f_ann_date"})
    merged = income.merge(balance, on=["ts_code", "end_date"], how="outer")

    for source_col in ("income_ann_date", "balance_ann_date"):
        if source_col not in merged.columns:
            merged[source_col] = pd.NA
    for source_col in ("income_f_ann_date", "balance_f_ann_date"):
        if source_col not in merged.columns:
            merged[source_col] = pd.NA

    merged["ann_date"] = merged[["income_ann_date", "balance_ann_date"]].max(axis=1, skipna=True)
    merged["f_ann_date"] = merged[["income_f_ann_date", "balance_f_ann_date"]].max(axis=1, skipna=True)
    merged["ann_date"] = merged["ann_date"].fillna(merged["f_ann_date"])
    merged["f_ann_date"] = merged["f_ann_date"].fillna(merged["ann_date"])
    for col in FINANCIAL_COLUMNS:
        if col not in merged.columns:
            merged[col] = pd.NA
    return merged[FINANCIAL_COLUMNS]


def _fetch_vip_or_fallback(
    pro,
    api_name: str,
    fallback_name: str,
    fields: str,
    period: str,
    columns: list[str],
    universe: set[str],
    sleep_seconds: float,
    vip_unavailable: dict[str, bool],
    errors: list[dict],
) -> tuple[pd.DataFrame, int, int, bool]:
    calls = 0
    fallback_calls = 0
    used_fallback = False

    if not vip_unavailable.get(api_name):
        calls += 1
        before_errors = len(errors)
        df = _call_api(pro, api_name, sleep_seconds, errors, period=period, fields=fields)
        if df is not None:
            return _collapse_statement_frame(df, columns, universe), calls, fallback_calls, False
        vip_unavailable[api_name] = True
        errors.append(
            {
                "api": api_name,
                "period": period,
                "fallback": fallback_name,
                "reason": "vip endpoint failed; switching this endpoint to per-ticker fallback",
            }
        )
        if len(errors) == before_errors:
            errors.append({"api": api_name, "period": period, "error": "unknown vip endpoint failure"})

    frames = []
    used_fallback = True
    for ts_code in sorted(universe):
        calls += 1
        fallback_calls += 1
        df = _call_api(
            pro,
            fallback_name,
            sleep_seconds,
            errors,
            ts_code=ts_code,
            period=period,
            fields=fields,
        )
        frame = _collapse_statement_frame(df, columns, universe)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=columns), calls, fallback_calls, used_fallback
    return pd.concat(frames, ignore_index=True), calls, fallback_calls, used_fallback


def fetch_financial_panel(
    pro,
    periods: list[str],
    universe: set[str],
    sleep_seconds: float,
) -> tuple[pd.DataFrame, int, list[dict], dict[str, int], bool]:
    errors: list[dict] = []
    frames: list[pd.DataFrame] = []
    calls = 0
    used_any_fallback = False
    endpoint_counts = {
        "income_vip": 0,
        "balancesheet_vip": 0,
        "cashflow_vip": 0,
        "income_fallback": 0,
        "balancesheet_fallback": 0,
        "cashflow_fallback": 0,
    }
    vip_unavailable: dict[str, bool] = {}

    for period in periods:
        income, endpoint_calls, fallback_calls, used_fallback = _fetch_vip_or_fallback(
            pro,
            "income_vip",
            "income",
            INCOME_FIELDS,
            period,
            INCOME_FIELDS.split(","),
            universe,
            sleep_seconds,
            vip_unavailable,
            errors,
        )
        calls += endpoint_calls
        endpoint_counts["income_vip"] += endpoint_calls - fallback_calls
        endpoint_counts["income_fallback"] += fallback_calls
        used_any_fallback = used_any_fallback or used_fallback

        balance, endpoint_calls, fallback_calls, used_fallback = _fetch_vip_or_fallback(
            pro,
            "balancesheet_vip",
            "balancesheet",
            BALANCESHEET_FIELDS,
            period,
            BALANCESHEET_FIELDS.split(","),
            universe,
            sleep_seconds,
            vip_unavailable,
            errors,
        )
        calls += endpoint_calls
        endpoint_counts["balancesheet_vip"] += endpoint_calls - fallback_calls
        endpoint_counts["balancesheet_fallback"] += fallback_calls
        used_any_fallback = used_any_fallback or used_fallback

        cashflow, endpoint_calls, fallback_calls, used_fallback = _fetch_vip_or_fallback(
            pro,
            "cashflow_vip",
            "cashflow",
            CASHFLOW_FIELDS,
            period,
            CASHFLOW_FIELDS.split(","),
            universe,
            sleep_seconds,
            vip_unavailable,
            errors,
        )
        calls += endpoint_calls
        endpoint_counts["cashflow_vip"] += endpoint_calls - fallback_calls
        endpoint_counts["cashflow_fallback"] += fallback_calls
        used_any_fallback = used_any_fallback or used_fallback

        merged = _merge_financial_frames(income, balance)
        if not merged.empty:
            frames.append(merged)
        if cashflow.empty and vip_unavailable.get("cashflow_vip"):
            errors.append(
                {
                    "api": "cashflow_vip",
                    "period": period,
                    "note": "cashflow fallback produced no target output columns",
                }
            )

    if not frames:
        return pd.DataFrame(columns=FINANCIAL_COLUMNS), calls, errors, endpoint_counts, used_any_fallback
    panel = pd.concat(frames, ignore_index=True)
    panel = _normalize_dates_as_text(panel, ["ann_date", "f_ann_date", "end_date"])
    panel = _dedupe_sort(panel, ["ts_code", "end_date", "ann_date", "f_ann_date"], FINANCIAL_COLUMNS)
    return panel, calls, errors, endpoint_counts, used_any_fallback


def append_write_panels(
    out_dir: Path,
    prices_new: pd.DataFrame,
    financials_new: pd.DataFrame,
    allow_selftest_stub: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    prices_path = out_dir / "prices.parquet"
    financials_path = out_dir / "financials.parquet"
    out_dir.mkdir(parents=True, exist_ok=True)

    prices_existing = _read_existing(prices_path, PRICE_COLUMNS, allow_selftest_stub)
    financials_existing = _read_existing(financials_path, FINANCIAL_COLUMNS, allow_selftest_stub)

    prices = prices_new if prices_existing.empty else pd.concat([prices_existing, prices_new], ignore_index=True)
    prices = _normalize_dates_as_text(prices, ["trade_date"])
    prices = _dedupe_sort(prices, ["ts_code", "trade_date"], PRICE_COLUMNS)

    financials = (
        financials_new
        if financials_existing.empty
        else pd.concat([financials_existing, financials_new], ignore_index=True)
    )
    financials = _normalize_dates_as_text(financials, ["ann_date", "f_ann_date", "end_date"])
    financials = _dedupe_sort(financials, ["ts_code", "end_date", "ann_date", "f_ann_date"], FINANCIAL_COLUMNS)

    used_stub_prices = _write_parquet(prices_path, prices, allow_selftest_stub)
    used_stub_financials = _write_parquet(financials_path, financials, allow_selftest_stub)
    return prices, financials, used_stub_prices or used_stub_financials


def fetch_universe_history(
    pro,
    start: str,
    end: str,
    out_dir: Path,
    sleep_seconds: float,
    requested_universe: Optional[list[str]] = None,
    allow_selftest_stub: bool = False,
    month_end_only: bool = False,
) -> dict:
    started = time.monotonic()
    out_dir = Path(out_dir)
    errors: list[dict] = []
    call_counts: dict[str, int] = {}

    universe, calls, universe_errors = fetch_universe(pro, requested_universe, sleep_seconds)
    call_counts["stock_basic"] = calls
    errors.extend(universe_errors)
    universe_set = set(universe)

    trade_dates, calls, trade_cal_errors = fetch_trade_dates(pro, start, end, sleep_seconds)
    call_counts["trade_cal"] = calls
    errors.extend(trade_cal_errors)

    # MONTH-END-ONLY (2026-05-25): a monthly-rebalance backtest doesn't need
    # daily bars. Keep only the last trading day of each month (~240 over 20yr
    # vs ~4950) → ~20x fewer price calls → fetch in minutes not ~5h. The price
    # series becomes month-end bars; satellite_strategy uses monthly factor
    # windows to match.
    if month_end_only and trade_dates:
        by_month: dict[str, str] = {}
        for d in trade_dates:  # 'YYYYMMDD' sorted asc
            by_month[d[:6]] = d  # last seen per YYYYMM = month-end
        trade_dates = sorted(by_month.values())
    call_counts["trade_dates_used"] = len(trade_dates)

    prices_new, calls, price_errors, price_counts = fetch_price_panel(
        pro, trade_dates, universe_set, sleep_seconds
    )
    call_counts.update(price_counts)
    call_counts["price_total"] = calls
    errors.extend(price_errors)

    periods = _quarter_periods(start, end)
    financials_new, calls, financial_errors, financial_counts, used_financial_fallback = fetch_financial_panel(
        pro, periods, universe_set, sleep_seconds
    )
    call_counts.update(financial_counts)
    call_counts["financial_total"] = calls
    errors.extend(financial_errors)

    prices, financials, used_parquet_stub = append_write_panels(
        out_dir, prices_new, financials_new, allow_selftest_stub=allow_selftest_stub
    )

    manifest = {
        "source": "tushare",
        "date_range": {"start": start, "end": end},
        "n_stocks": len(universe),
        "n_rows": {"prices": int(len(prices)), "financials": int(len(financials))},
        "new_rows_this_run": {"prices": int(len(prices_new)), "financials": int(len(financials_new))},
        "trade_dates": len(trade_dates),
        "report_periods": len(periods),
        "fetched_at": _iso_now(),
        "output_files": {
            "prices": str(out_dir / "prices.parquet"),
            "financials": str(out_dir / "financials.parquet"),
            "manifest": str(out_dir / "_manifest.json"),
        },
        "api_call_count": int(
            call_counts.get("stock_basic", 0)
            + call_counts.get("trade_cal", 0)
            + call_counts.get("price_total", 0)
            + call_counts.get("financial_total", 0)
        ),
        "api_call_breakdown": call_counts,
        "financials_vip_fallback_used": used_financial_fallback,
        "selftest_parquet_stub_used": used_parquet_stub,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "errors": errors,
        "_status": "ok" if not errors else ("partial" if len(prices) or len(financials) else "failed"),
    }
    _write_json(out_dir / "_manifest.json", manifest)
    return manifest


class _FakePro:
    def __init__(self):
        self.trade_dates = ["20240102", "20240103"]
        self.tickers = ["000001.SZ", "600000.SH", "300104.SZ"]
        self.call_log: list[tuple[str, dict]] = []

    def _record(self, name, kwargs):
        self.call_log.append((name, dict(kwargs)))

    def stock_basic(self, **kwargs):
        self._record("stock_basic", kwargs)
        status = kwargs.get("list_status")
        rows = {
            "L": [
                {"ts_code": "000001.SZ", "symbol": "000001", "name": "Ping An Bank", "list_status": "L"},
                {"ts_code": "600000.SH", "symbol": "600000", "name": "SPDB", "list_status": "L"},
            ],
            "D": [{"ts_code": "300104.SZ", "symbol": "300104", "name": "Delisted", "list_status": "D"}],
            "P": [],
        }.get(status, [])
        return pd.DataFrame(rows)

    def trade_cal(self, **kwargs):
        self._record("trade_cal", kwargs)
        return pd.DataFrame({"trade_date": self.trade_dates, "is_open": [1, 1]})

    def daily(self, **kwargs):
        self._record("daily", kwargs)
        trade_date = kwargs["trade_date"]
        close_base = {"20240102": 10.0, "20240103": 10.5}[trade_date]
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": trade_date, "close": close_base},
                {"ts_code": "600000.SH", "trade_date": trade_date, "close": close_base + 5},
                {"ts_code": "300104.SZ", "trade_date": trade_date, "close": close_base + 9},
            ]
        )

    def daily_basic(self, **kwargs):
        self._record("daily_basic", kwargs)
        trade_date = kwargs["trade_date"]
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": trade_date,
                    "pe": 5.0,
                    "pb": 0.6,
                    "total_mv": 1000.0,
                    "circ_mv": 900.0,
                },
                {
                    "ts_code": "600000.SH",
                    "trade_date": trade_date,
                    "pe": 6.0,
                    "pb": 0.7,
                    "total_mv": 2000.0,
                    "circ_mv": 1800.0,
                },
                {
                    "ts_code": "300104.SZ",
                    "trade_date": trade_date,
                    "pe": 7.0,
                    "pb": 0.8,
                    "total_mv": 300.0,
                    "circ_mv": 250.0,
                },
            ]
        )

    def adj_factor(self, **kwargs):
        self._record("adj_factor", kwargs)
        trade_date = kwargs["trade_date"]
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": trade_date, "adj_factor": 1.0},
                {"ts_code": "600000.SH", "trade_date": trade_date, "adj_factor": 1.1},
                {"ts_code": "300104.SZ", "trade_date": trade_date, "adj_factor": 0.9},
            ]
        )

    def income_vip(self, **kwargs):
        self._record("income_vip", kwargs)
        if kwargs["period"] != "20231231":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20240320",
                    "f_ann_date": "20240320",
                    "end_date": "20231231",
                    "revenue": 100.0,
                    "oper_cost": 45.0,
                    "n_income": 20.0,
                    "n_income_attr_p": 18.0,
                },
                {
                    "ts_code": "600000.SH",
                    "ann_date": "20240321",
                    "f_ann_date": "20240321",
                    "end_date": "20231231",
                    "revenue": 200.0,
                    "oper_cost": 90.0,
                    "n_income": 30.0,
                    "n_income_attr_p": 28.0,
                },
            ]
        )

    def balancesheet_vip(self, **kwargs):
        self._record("balancesheet_vip", kwargs)
        if kwargs["period"] != "20231231":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20240322",
                    "f_ann_date": "20240322",
                    "end_date": "20231231",
                    "total_hldr_eqy_exc_min_int": 80.0,
                    "total_assets": 500.0,
                    "total_liab": 420.0,
                },
                {
                    "ts_code": "600000.SH",
                    "ann_date": "20240323",
                    "f_ann_date": "20240323",
                    "end_date": "20231231",
                    "total_hldr_eqy_exc_min_int": 120.0,
                    "total_assets": 800.0,
                    "total_liab": 680.0,
                },
            ]
        )

    def cashflow_vip(self, **kwargs):
        self._record("cashflow_vip", kwargs)
        if kwargs["period"] != "20231231":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20240324",
                    "f_ann_date": "20240324",
                    "end_date": "20231231",
                },
                {
                    "ts_code": "600000.SH",
                    "ann_date": "20240325",
                    "f_ann_date": "20240325",
                    "end_date": "20231231",
                },
            ]
        )


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _selftest() -> int:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "panel"
            default_universe, stock_basic_calls, stock_basic_errors = fetch_universe(_FakePro(), None, 0)
            _assert(stock_basic_calls == 3, "default universe should query stock_basic L+D+P")
            _assert(not stock_basic_errors, f"default universe errors: {stock_basic_errors}")
            _assert(
                set(default_universe) == {"000001.SZ", "600000.SH", "300104.SZ"},
                "default universe did not include listed and delisted stocks",
            )

            fake = _FakePro()
            manifest = fetch_universe_history(
                fake,
                start="20230101",
                end="20240103",
                out_dir=out_dir,
                sleep_seconds=0,
                requested_universe=["000001.SZ", "600000.SH"],
                allow_selftest_stub=True,
            )
            prices = _read_parquet(out_dir / "prices.parquet", allow_selftest_stub=True)
            financials = _read_parquet(out_dir / "financials.parquet", allow_selftest_stub=True)

            _assert(manifest["_status"] == "ok", f"unexpected manifest status: {manifest['_status']}")
            _assert(len(prices) == 4, f"expected 4 price rows, got {len(prices)}")
            _assert(set(prices["ts_code"]) == {"000001.SZ", "600000.SH"}, "universe filter failed")
            row = prices[(prices["ts_code"] == "000001.SZ") & (prices["trade_date"] == "20240103")].iloc[0]
            _assert(float(row["close"]) == 10.5, "daily close did not merge")
            _assert(float(row["adj_factor"]) == 1.0, "adj_factor did not merge")
            _assert(float(row["pe"]) == 5.0 and float(row["total_mv"]) == 1000.0, "daily_basic did not merge")

            _assert(len(financials) == 2, f"expected 2 financial rows, got {len(financials)}")
            fin = financials[financials["ts_code"] == "000001.SZ"].iloc[0]
            _assert(fin["end_date"] == "20231231", "financial end_date missing")
            _assert(fin["ann_date"] == "20240322", "financial ann_date was not retained conservatively")
            _assert(float(fin["revenue"]) == 100.0, "income fields missing from financial panel")
            _assert(float(fin["total_assets"]) == 500.0, "balance fields missing from financial panel")

            roundtrip_path = out_dir / "roundtrip.parquet"
            expected = prices.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
            _write_parquet(roundtrip_path, expected, allow_selftest_stub=True)
            actual = _read_parquet(roundtrip_path, allow_selftest_stub=True)
            pd.testing.assert_frame_equal(expected, actual, check_dtype=False)

            second = fetch_universe_history(
                fake,
                start="20230101",
                end="20240103",
                out_dir=out_dir,
                sleep_seconds=0,
                requested_universe=["000001.SZ", "600000.SH"],
                allow_selftest_stub=True,
            )
            prices2 = _read_parquet(out_dir / "prices.parquet", allow_selftest_stub=True)
            duplicate_count = prices2.duplicated(subset=["ts_code", "trade_date"]).sum()
            _assert(len(prices2) == 4, f"overlapping rerun was not idempotent: {len(prices2)} rows")
            _assert(int(duplicate_count) == 0, f"dedupe failed: {duplicate_count} duplicates")
            _assert(second["n_rows"]["prices"] == 4, "manifest did not report deduped price rows")

            daily_calls = [name for name, _kwargs in fake.call_log if name == "daily"]
            _assert(len(daily_calls) == 4, "two runs should call daily once per trade date")
            print(
                "SELFTEST PASS: rows prices=4 financials=2; ann_date retained; "
                "roundtrip ok; overlapping rerun deduped"
            )
        return 0
    except Exception as exc:
        print(f"SELFTEST FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch full-universe Tushare daily and PIT financial panels into parquet."
    )
    parser.add_argument("--start", default=DEFAULT_START, help="Start date YYYYMMDD. Default: 20050101.")
    parser.add_argument("--end", default=_today_ts(), help="End date YYYYMMDD. Default: today.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory. Default: data_history/panel.")
    parser.add_argument("--sleep", type=float, default=0.12, help="Seconds between Tushare calls.")
    parser.add_argument(
        "--universe",
        default=None,
        help="Optional comma/space-separated ts_code allowlist, or path to a text allowlist. Default: stock_basic L+D+P.",
    )
    parser.add_argument("--month-end-only", action="store_true", dest="month_end_only",
                        help="Fetch only the last trading day of each month (~240 vs ~4950 dates) "
                             "→ minutes not hours. Use for monthly-rebalance backtests.")
    parser.add_argument("--selftest", action="store_true", help="Run offline fixture tests and exit.")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    start = _validate_ts_date(args.start, "--start")
    end = _validate_ts_date(args.end, "--end")
    if end < start:
        print("ERROR: --end must be >= --start", file=sys.stderr)
        return 1

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required", file=sys.stderr)
        return 1

    requested_universe = _parse_universe_arg(args.universe)

    try:
        _import_parquet(allow_selftest_stub=False)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        import tushare as ts
    except ImportError as exc:
        print(f"ERROR: tushare is required: {exc}", file=sys.stderr)
        return 1

    pro = ts.pro_api(token)
    manifest = fetch_universe_history(
        pro,
        start=start,
        end=end,
        out_dir=Path(args.out),
        sleep_seconds=args.sleep,
        requested_universe=requested_universe,
        allow_selftest_stub=False,
        month_end_only=args.month_end_only,
    )
    print(
        f"status={manifest['_status']} stocks={manifest['n_stocks']} "
        f"trade_dates={manifest['trade_dates']} report_periods={manifest['report_periods']} "
        f"prices={manifest['n_rows']['prices']} financials={manifest['n_rows']['financials']} "
        f"errors={len(manifest['errors'])} output={args.out}"
    )
    return 0 if manifest["_status"] in {"ok", "partial"} else 1


if __name__ == "__main__":
    sys.exit(main())
