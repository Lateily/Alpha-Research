#!/usr/bin/env python3
"""R-032: permanent U0 registry for the full A-share universe.

This module stores identity and eligibility facts. It does not rank securities,
generate research conclusions, or create trade-adjacent output. Missing symbols
are preserved from the prior registry and marked instead of being deleted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import tempfile
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA = "ar.security_registry"
SCHEMA_VERSION = "1.0"
SOURCE = "tushare.stock_basic"
TUSHARE_URL = os.environ.get("TUSHARE_URL", "https://api.tushare.pro")
TS_CODE_RE = re.compile(r"^(T)?[0-9]{6}\.(SH|SZ|BJ)$")
ST_RE = re.compile(r"(^|[^A-Z])\*?ST", re.IGNORECASE)
VALID_STAGES = {
    "UNSCANNED",
    "SCANNED",
    "CANDIDATE",
    "BATTERY",
    "DEEP_RESEARCH",
    "COURT",
    "PORTFOLIO",
    "EXCLUDED",
    "MONITOR",
}
STOCK_BASIC_FIELDS = (
    "ts_code,symbol,name,area,industry,market,exchange,list_status,list_date,delist_date"
)


class RegistryError(RuntimeError):
    pass


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _date8(value: str) -> str:
    raw = str(value or "").replace("-", "")
    try:
        datetime.strptime(raw, "%Y%m%d")
    except ValueError as exc:
        raise RegistryError(f"invalid YYYYMMDD date: {value!r}") from exc
    return raw


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve(path: str | Path) -> Path:
    value = Path(path).expanduser()
    return value if value.is_absolute() else _repo_root() / value


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read valid JSON from {path}: {exc}") from exc


def _validate_prior(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    validate_registry(payload)
    rows = payload["rows"]
    by_code: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_code[row["ts_code"]] = row
    return by_code


def validate_registry(payload: dict[str, Any]) -> None:
    if payload.get("schema") != SCHEMA or payload.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError("registry schema/version mismatch")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise RegistryError("registry rows must be a list")
    if payload.get("registry_hash") != _sha256(rows):
        raise RegistryError("registry_hash mismatch")
    codes: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or not TS_CODE_RE.fullmatch(str(row.get("ts_code", ""))):
            raise RegistryError("registry contains an invalid row")
        code = row["ts_code"]
        codes.append(code)
        if not isinstance(row.get("qualification"), dict) or not isinstance(row.get("data_coverage"), dict):
            raise RegistryError(f"registry row missing coverage objects: {code}")
    if len(codes) != len(set(codes)):
        raise RegistryError("registry contains duplicate ts_code")
    eligible_codes = sorted(
        row["ts_code"] for row in rows if row["qualification"].get("u1_scan_eligible") is True
    )
    if payload.get("eligible_universe_hash") != _sha256(eligible_codes):
        raise RegistryError("eligible_universe_hash mismatch")
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        raise RegistryError("registry coverage must be an object")
    expected = {
        "registry_rows": len(rows),
        "listed": sum(row.get("list_status") == "L" for row in rows),
        "delisted": sum(row.get("list_status") == "D" for row in rows),
        "prelisted": sum(row.get("list_status") == "P" for row in rows),
        "st_labeled": sum(row["qualification"].get("is_st") is True for row in rows),
        "bse_labeled": sum(row["qualification"].get("is_bse") is True for row in rows),
        "low_liquidity_labeled": sum(
            row["qualification"].get("liquidity_label") == "LOW" for row in rows
        ),
        "liquidity_data_blocked": sum(
            row["qualification"].get("liquidity_label") == "DATA_BLOCKED" for row in rows
        ),
        "preserved_missing_from_source": sum(
            row.get("source_presence") == "MISSING_PRESERVED" for row in rows
        ),
    }
    mismatches = {
        key: {"declared": coverage.get(key), "computed": value}
        for key, value in expected.items()
        if coverage.get(key) != value
    }
    if mismatches:
        raise RegistryError(f"registry coverage mismatch: {mismatches}")
    source = payload.get("source") or {}
    requires_partial = bool(
        source.get("errors")
        or expected["preserved_missing_from_source"]
        or expected["liquidity_data_blocked"]
    )
    expected_status = "PARTIAL" if requires_partial else "COMPLETE"
    if payload.get("status") != expected_status:
        raise RegistryError(
            f"registry status mismatch: declared={payload.get('status')} computed={expected_status}"
        )


def _tushare_call(token: str, api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
    body = json.dumps(
        {"api_name": api_name, "token": token, "params": params, "fields": fields}
    ).encode("utf-8")
    request = urllib.request.Request(
        TUSHARE_URL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "ar-u0-registry/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # network/provider boundary
        raise RegistryError(f"Tushare {api_name} request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise RegistryError(f"Tushare {api_name} returned a non-object response")
    if payload.get("code") != 0:
        raise RegistryError(f"Tushare {api_name} error: {payload.get('msg')}")
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise RegistryError(f"Tushare {api_name} returned malformed data")
    names = data.get("fields") or []
    items = data.get("items") or []
    if not isinstance(names, list) or not isinstance(items, list):
        raise RegistryError(f"Tushare {api_name} returned malformed fields/items")
    return [dict(zip(names, values)) for values in items]


def fetch_stock_basic(token: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for status in ("L", "D", "P"):
        rows.extend(
            _tushare_call(
                token,
                "stock_basic",
                {"exchange": "", "list_status": status},
                STOCK_BASIC_FIELDS,
            )
        )
    return rows


def _open_dates(token: str, as_of: str, count: int) -> list[str]:
    end = datetime.strptime(as_of, "%Y%m%d").date()
    start = end - timedelta(days=max(45, count * 3))
    rows = _tushare_call(
        token,
        "trade_cal",
        {"exchange": "SSE", "start_date": start.strftime("%Y%m%d"), "end_date": as_of, "is_open": "1"},
        "cal_date,is_open",
    )
    dates = sorted({str(row.get("cal_date", "")) for row in rows if row.get("is_open") in (1, "1")})
    return dates[-count:]


def fetch_liquidity(
    token: str, as_of: str, days: int
) -> tuple[dict[str, list[float]], set[str], list[str], list[str]]:
    open_dates = _open_dates(token, as_of, days)
    if not open_dates:
        raise RegistryError("trade_cal returned no open dates")
    amounts: dict[str, list[float]] = {}
    traded_as_of: set[str] = set()
    errors: list[str] = []
    for trade_date in open_dates:
        try:
            rows = _tushare_call(
                token,
                "daily",
                {"trade_date": trade_date},
                "ts_code,trade_date,amount",
            )
        except RegistryError as exc:
            errors.append(str(exc))
            continue
        for row in rows:
            code = str(row.get("ts_code", ""))
            amount_thousand = row.get("amount")
            if not TS_CODE_RE.fullmatch(code) or not isinstance(amount_thousand, (int, float)):
                continue
            amounts.setdefault(code, []).append(float(amount_thousand) * 1000.0)
            if trade_date == as_of:
                traded_as_of.add(code)
    return amounts, traded_as_of, open_dates, errors


def _normalize_source_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise RegistryError("stock_basic row must be an object")
        code = str(raw.get("ts_code", "")).strip().upper()
        if not TS_CODE_RE.fullmatch(code):
            raise RegistryError(f"invalid A-share ts_code: {code!r}")
        if code in by_code:
            raise RegistryError(f"stock_basic duplicate ts_code: {code}")
        status = str(raw.get("list_status", "")).strip().upper()
        if status not in {"L", "D", "P"}:
            raise RegistryError(f"invalid list_status for {code}: {status!r}")
        row = dict(raw)
        row["ts_code"] = code
        row["list_status"] = status
        by_code[code] = row
    return by_code


def _row_from_source(
    source: dict[str, Any],
    prior: dict[str, Any] | None,
    *,
    as_of: str,
    generated_at: str,
    liquidity: list[float] | None,
    traded_as_of: set[str] | None,
    liquidity_days: int,
    min_liquidity_observations: int,
    low_liquidity_threshold_cny: float,
) -> dict[str, Any]:
    code = source["ts_code"]
    name = str(source.get("name") or "").strip()
    industry = str(source.get("industry") or "").strip()
    exchange = str(source.get("exchange") or code.split(".")[-1]).strip().upper()
    board = str(source.get("market") or exchange).strip() or exchange
    list_status = source["list_status"]
    is_st = bool(ST_RE.search(name.upper()))
    is_bse = exchange == "BSE" or code.endswith(".BJ") or "北交" in board
    is_legacy_provider_code = code.startswith("T")

    reason_codes: list[str] = []
    if is_st:
        reason_codes.append("ST_LABEL")
    if is_bse:
        reason_codes.append("BSE_LABEL")
    if is_legacy_provider_code:
        reason_codes.append("LEGACY_PROVIDER_CODE")
    if list_status == "D":
        reason_codes.append("DELISTED")
    elif list_status == "P":
        reason_codes.append("PRELISTED")
    if not industry:
        reason_codes.append("INDUSTRY_UNKNOWN")

    liquidity_values = [float(value) for value in (liquidity or []) if value is not None]
    if list_status != "L":
        liquidity_label = "NOT_APPLICABLE"
        median_amount = None
    elif len(liquidity_values) < min_liquidity_observations:
        liquidity_label = "DATA_BLOCKED"
        median_amount = None
        reason_codes.append("LIQUIDITY_DATA_BLOCKED")
    else:
        median_amount = round(statistics.median(liquidity_values), 2)
        liquidity_label = "LOW" if median_amount < low_liquidity_threshold_cny else "NORMAL"
        if liquidity_label == "LOW":
            reason_codes.append("LOW_LIQUIDITY_INITIAL_THRESHOLD")

    if list_status == "L" and traded_as_of is not None and code not in traded_as_of:
        reason_codes.append("NO_DAILY_BAR_ON_AS_OF")

    stage = (prior or {}).get("current_stage", "UNSCANNED")
    if stage not in VALID_STAGES:
        stage = "UNSCANNED"

    return {
        "ts_code": code,
        "symbol": str(source.get("symbol") or code.split(".")[0]),
        "name": name or "UNKNOWN",
        "market": "A_SHARE",
        "board": board,
        "exchange": exchange,
        "list_status": list_status,
        "list_date": str(source.get("list_date") or "") or None,
        "delist_date": str(source.get("delist_date") or "") or None,
        "area": str(source.get("area") or "") or None,
        "industry_key": industry or "UNKNOWN",
        "industry_source": "tushare.stock_basic.industry",
        "first_seen": (prior or {}).get("first_seen") or as_of,
        "last_seen": as_of,
        "last_scanned_at": generated_at,
        "source_presence": "CURRENT",
        "current_stage": stage,
        "reason_codes": sorted(set(reason_codes)),
        "next_review_at": None,
        "qualification": {
            "is_st": is_st,
            "is_bse": is_bse,
            "u1_scan_eligible": list_status == "L" and not is_legacy_provider_code,
            "liquidity_label": liquidity_label,
            "liquidity_20d_median_cny": median_amount,
            "liquidity_observations": len(liquidity_values),
            "liquidity_window_target": liquidity_days,
            "low_liquidity_threshold_cny": low_liquidity_threshold_cny,
            "threshold_status": "UNVALIDATED_INITIAL_TAG_ONLY",
            "has_daily_bar_on_as_of": None if traded_as_of is None or list_status != "L" else code in traded_as_of,
        },
        "data_coverage": {
            "identity": "COMPLETE" if name else "PARTIAL",
            "industry": "COMPLETE" if industry else "DATA_BLOCKED",
            "liquidity": liquidity_label if liquidity_label in {"DATA_BLOCKED", "NOT_APPLICABLE"} else "COMPLETE",
        },
        "source": SOURCE,
        "source_as_of": as_of,
        "fetched_at": generated_at,
    }


def build_registry(
    source_rows: list[dict[str, Any]],
    *,
    as_of: str,
    generated_at: str | None = None,
    prior_payload: dict[str, Any] | None = None,
    liquidity_by_code: dict[str, list[float]] | None = None,
    traded_as_of: set[str] | None = None,
    liquidity_days: int = 20,
    min_liquidity_observations: int = 5,
    low_liquidity_threshold_cny: float = 20_000_000.0,
    source_errors: list[str] | None = None,
) -> dict[str, Any]:
    as_of = _date8(as_of)
    generated_at = generated_at or _now_utc()
    current = _normalize_source_rows(source_rows)
    prior = _validate_prior(prior_payload) if prior_payload is not None else {}
    liquidity_by_code = liquidity_by_code or {}
    source_errors = list(source_errors or [])

    output_rows: list[dict[str, Any]] = []
    for code in sorted(current):
        output_rows.append(
            _row_from_source(
                current[code],
                prior.get(code),
                as_of=as_of,
                generated_at=generated_at,
                liquidity=liquidity_by_code.get(code),
                traded_as_of=traded_as_of,
                liquidity_days=liquidity_days,
                min_liquidity_observations=min_liquidity_observations,
                low_liquidity_threshold_cny=low_liquidity_threshold_cny,
            )
        )

    preserved = 0
    for code in sorted(set(prior) - set(current)):
        row = json.loads(json.dumps(prior[code], ensure_ascii=False))
        row["source_presence"] = "MISSING_PRESERVED"
        row["last_scanned_at"] = generated_at
        row["reason_codes"] = sorted(set(row.get("reason_codes", [])) | {"MISSING_FROM_CURRENT_SOURCE"})
        row["next_review_at"] = as_of
        output_rows.append(row)
        preserved += 1

    output_rows.sort(key=lambda row: row["ts_code"])
    active_codes = sorted(row["ts_code"] for row in output_rows if row["qualification"]["u1_scan_eligible"])
    listed = sum(row["list_status"] == "L" for row in output_rows)
    blocked_liquidity = sum(
        row["qualification"]["liquidity_label"] == "DATA_BLOCKED" for row in output_rows
    )
    status = "PARTIAL" if source_errors or preserved or blocked_liquidity else "COMPLETE"
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "as_of": as_of,
        "generated_at": generated_at,
        "source": {
            "provider": "Tushare Pro",
            "identity_endpoint": "stock_basic",
            "endpoints": ["stock_basic", "trade_cal", "daily"],
            "source_as_of": as_of,
            "fetched_at": generated_at,
            "errors": source_errors,
        },
        "policy": {
            "permanent_identity": True,
            "missing_symbols_are_preserved": True,
            "qualification_tags_do_not_delete_rows": True,
            "low_liquidity_threshold_cny": low_liquidity_threshold_cny,
            "threshold_status": "UNVALIDATED_INITIAL_TAG_ONLY",
            "registry_hash_algorithm": "sha256(canonical_json(rows))/v1",
            "eligible_hash_algorithm": "sha256(canonical_json(sorted_eligible_ts_codes))/v1",
        },
        "coverage": {
            "source_rows": len(current),
            "registry_rows": len(output_rows),
            "listed": listed,
            "delisted": sum(row["list_status"] == "D" for row in output_rows),
            "prelisted": sum(row["list_status"] == "P" for row in output_rows),
            "st_labeled": sum(row["qualification"]["is_st"] for row in output_rows),
            "bse_labeled": sum(row["qualification"]["is_bse"] for row in output_rows),
            "low_liquidity_labeled": sum(
                row["qualification"]["liquidity_label"] == "LOW" for row in output_rows
            ),
            "liquidity_data_blocked": blocked_liquidity,
            "preserved_missing_from_source": preserved,
        },
        "eligible_universe_hash": _sha256(active_codes),
        "registry_hash": _sha256(output_rows),
        "rows": output_rows,
        "disclaimer": "Identity and eligibility metadata only; no research conclusion or trading action.",
    }


def _selftest() -> int:
    rows = [
        {"ts_code": "600000.SH", "symbol": "600000", "name": "浦发银行", "area": "上海", "industry": "银行", "market": "主板", "exchange": "SSE", "list_status": "L", "list_date": "19991110", "delist_date": ""},
        {"ts_code": "000001.SZ", "symbol": "000001", "name": "*ST测试", "area": "深圳", "industry": "银行", "market": "主板", "exchange": "SZSE", "list_status": "L", "list_date": "19910403", "delist_date": ""},
        {"ts_code": "920001.BJ", "symbol": "920001", "name": "北交测试", "area": "北京", "industry": "机械", "market": "北交所", "exchange": "BSE", "list_status": "L", "list_date": "20250101", "delist_date": ""},
        {"ts_code": "600001.SH", "symbol": "600001", "name": "退市测试", "area": "上海", "industry": "综合", "market": "主板", "exchange": "SSE", "list_status": "D", "list_date": "19900101", "delist_date": "20200101"},
        {"ts_code": "T600018.SH", "symbol": "T600018", "name": "历史退市代码", "area": "上海", "industry": "港口", "market": "主板", "exchange": "SSE", "list_status": "D", "list_date": "20000719", "delist_date": "20061020"},
    ]
    liquidity = {
        "600000.SH": [50_000_000.0] * 10,
        "000001.SZ": [10_000_000.0] * 10,
        "920001.BJ": [30_000_000.0] * 10,
    }
    first = build_registry(
        rows,
        as_of="20260805",
        generated_at="2026-08-05T08:00:00+00:00",
        liquidity_by_code=liquidity,
        traded_as_of={"600000.SH", "000001.SZ"},
    )
    by_code = {row["ts_code"]: row for row in first["rows"]}
    checks = [
        (len(first["rows"]) == 5, "all rows registered"),
        (by_code["000001.SZ"]["qualification"]["is_st"], "ST tag"),
        (by_code["920001.BJ"]["qualification"]["is_bse"], "BSE tag"),
        (by_code["000001.SZ"]["qualification"]["liquidity_label"] == "LOW", "liquidity tag"),
        (by_code["600001.SH"]["qualification"]["u1_scan_eligible"] is False, "delisted not U1 eligible"),
        ("LEGACY_PROVIDER_CODE" in by_code["T600018.SH"]["reason_codes"], "legacy provider code retained and tagged"),
        ("NO_DAILY_BAR_ON_AS_OF" in by_code["920001.BJ"]["reason_codes"], "missing daily bar exposed"),
    ]
    second_rows = [row for row in rows if row["ts_code"] != "600001.SH"]
    second = build_registry(
        second_rows,
        as_of="20260806",
        generated_at="2026-08-06T08:00:00+00:00",
        prior_payload=first,
        liquidity_by_code=liquidity,
        traded_as_of=set(liquidity),
    )
    second_by_code = {row["ts_code"]: row for row in second["rows"]}
    checks.extend(
        [
            (len(second["rows"]) == 5, "missing source row preserved"),
            (second_by_code["600001.SH"]["source_presence"] == "MISSING_PRESERVED", "preserved row marked"),
            (second_by_code["600000.SH"]["first_seen"] == "20260805", "first_seen stable"),
            (second["status"] == "PARTIAL", "missing source row surfaces PARTIAL"),
            (second["registry_hash"] == _sha256(second["rows"]), "registry hash valid"),
        ]
    )
    blocked = build_registry(
        rows,
        as_of="20260805",
        generated_at="2026-08-05T08:00:00+00:00",
        liquidity_by_code={"600000.SH": liquidity["600000.SH"]},
        traded_as_of={"600000.SH"},
    )
    checks.append(
        (
            blocked["status"] == "PARTIAL"
            and blocked["coverage"]["liquidity_data_blocked"] == 2,
            "listed liquidity gaps surface top-level PARTIAL",
        )
    )
    try:
        build_registry(rows + [rows[0]], as_of="20260805")
        checks.append((False, "duplicates rejected"))
    except RegistryError:
        checks.append((True, "duplicates rejected"))
    corrupt = dict(first)
    corrupt["registry_hash"] = "0" * 64
    try:
        build_registry(rows, as_of="20260806", prior_payload=corrupt)
        checks.append((False, "corrupt prior rejected"))
    except RegistryError:
        checks.append((True, "corrupt prior rejected"))
    corrupt_coverage = json.loads(json.dumps(first))
    corrupt_coverage["coverage"]["listed"] += 1
    try:
        validate_registry(corrupt_coverage)
        checks.append((False, "coverage drift rejected"))
    except RegistryError:
        checks.append((True, "coverage drift rejected"))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "registry.json"
        _atomic_write_json(path, first)
        checks.append((_load_json(path)["registry_hash"] == first["registry_hash"], "atomic round trip"))

    for ok, name in checks:
        print(("PASS" if ok else "FAIL"), name)
    passed = sum(ok for ok, _ in checks)
    print(f"SELFTEST {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the permanent all-A-share U0 registry")
    parser.add_argument(
        "--as-of",
        default=os.environ.get("AR_TARGET_TRADE_DATE") or date.today().strftime("%Y%m%d"),
    )
    parser.add_argument("--output", default="public/data/v2/security_registry.json")
    parser.add_argument("--prior", default="")
    parser.add_argument("--input", help="offline JSON with rows/liquidity_by_code/as_of_traded")
    parser.add_argument("--skip-liquidity", action="store_true")
    parser.add_argument("--liquidity-days", type=int, default=20)
    parser.add_argument("--min-liquidity-observations", type=int, default=5)
    parser.add_argument("--low-liquidity-threshold-cny", type=float, default=20_000_000.0)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument(
        "--allow-partial-exit-zero",
        action="store_true",
        help="Treat a structurally valid PARTIAL artifact as process success for nightly quality reporting.",
    )
    args = parser.parse_args()
    if args.selftest:
        return _selftest()

    as_of = _date8(args.as_of)
    output_path = _resolve(args.output)
    prior_path = _resolve(args.prior) if args.prior else output_path
    prior_payload = _load_json(prior_path) if prior_path.exists() else None
    source_errors: list[str] = []

    if args.input:
        fixture = _load_json(_resolve(args.input))
        rows = fixture.get("rows")
        if not isinstance(rows, list):
            raise RegistryError("offline input requires rows[]")
        liquidity_by_code = fixture.get("liquidity_by_code") or {}
        traded_as_of = set(fixture.get("as_of_traded") or [])
        source_errors.extend(fixture.get("source_errors") or [])
    else:
        token = os.environ.get("TUSHARE_TOKEN", "")
        if not token:
            raise RegistryError("TUSHARE_TOKEN is required for live registry build")
        rows = fetch_stock_basic(token)
        if args.skip_liquidity:
            liquidity_by_code = {}
            traded_as_of = None
            source_errors.append("liquidity fetch skipped by operator")
        else:
            liquidity_by_code, traded_as_of, _, liquidity_errors = fetch_liquidity(
                token, as_of, args.liquidity_days
            )
            source_errors.extend(liquidity_errors)

    payload = build_registry(
        rows,
        as_of=as_of,
        prior_payload=prior_payload,
        liquidity_by_code=liquidity_by_code,
        traded_as_of=traded_as_of,
        liquidity_days=args.liquidity_days,
        min_liquidity_observations=args.min_liquidity_observations,
        low_liquidity_threshold_cny=args.low_liquidity_threshold_cny,
        source_errors=source_errors,
    )
    validate_registry(payload)
    _atomic_write_json(output_path, payload)
    coverage = payload["coverage"]
    print(
        f"[written] {output_path} status={payload['status']} rows={coverage['registry_rows']} "
        f"listed={coverage['listed']} ST={coverage['st_labeled']} BSE={coverage['bse_labeled']} "
        f"low_liquidity={coverage['low_liquidity_labeled']} blocked={coverage['liquidity_data_blocked']}"
    )
    print("Identity and eligibility metadata only; no research conclusion or trading action.")
    if payload["status"] == "COMPLETE":
        return 0
    return 0 if args.allow_partial_exit_zero and payload["status"] == "PARTIAL" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RegistryError as exc:
        print(f"REGISTRY_REFUSED: {exc}")
        raise SystemExit(2)
