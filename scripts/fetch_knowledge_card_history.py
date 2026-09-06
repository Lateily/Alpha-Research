#!/usr/bin/env python3
"""Knowledge-card history: PLAN -> (human-approved) FETCH -> offline INGEST.

WO-B4 replays the reviewed AUTO knowledge cards on three known cycle points
(2019-06-30 / 2021-09-30 / 2023-03-31). The nightly point-in-time store only
reaches back to 2026-08, so the look-back stays DATA_BLOCKED until the history
is collected AND loaded into a dated store the engine can read.

Three operator steps, each explicit, none automatic:

    # 1. plan (default; prints what would be requested, sends nothing)
    python3 scripts/fetch_knowledge_card_history.py

    # 2. fetch — costs real Tushare quota, so it needs a human's approval
    AR_HISTORY_FETCH_APPROVED=1 python3 scripts/fetch_knowledge_card_history.py --execute
    #    (TUSHARE_TOKEN must be in the environment; it is never printed or stored)

    # 3. ingest the fetched files into a DEDICATED history store (offline)
    python3 scripts/fetch_knowledge_card_history.py --ingest \\
        --history-db data_history/knowledge_card_history/store.sqlite3

The plan is derived from the committed card table, not hand-typed. The ingest
writes through ``semiconductor_extended_sources.ingest_extended_source`` in
HISTORY mode (append-only, hash-bound, point-in-time on read) and refuses the
production feature store as a destination. Nothing here selects, ranks, or
trades anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
FUNNEL = REPO_ROOT / "experiments" / "research_funnel"
if str(FUNNEL) not in sys.path:
    sys.path.insert(0, str(FUNNEL))

import knowledge_card_backtest as backtest  # noqa: E402
import knowledge_cards  # noqa: E402
import security_registry  # noqa: E402
import semiconductor_extended_sources as extended  # noqa: E402
from security_registry import RegistryError, _date8, _sha256  # noqa: E402
from semiconductor_inputs import SemiconductorInputError  # noqa: E402


PLAN_SCHEMA = "ar.knowledge_card_history_plan.v1"
FETCH_RECEIPT_SCHEMA = "ar.knowledge_card_history_fetch_receipt.v1"
INGEST_RECEIPT_SCHEMA = "ar.knowledge_card_history_ingest_receipt.v1"
APPROVAL_ENV = "AR_HISTORY_FETCH_APPROVED"
DEFAULT_OUT_DIR = "data_history/knowledge_card_history"
DEFAULT_HISTORY_DB = "data_history/knowledge_card_history/store.sqlite3"
PRODUCTION_STORE = "data_history/feature_store.sqlite3"
FETCH_RECEIPT_NAME = "fetch_receipt.json"
INGEST_RECEIPT_NAME = "ingest_receipt.json"
DISCLAIMER = (
    "采集计划,不是采集本身;执行需人类批准。No selection, ranking, or trade action."
)

# The earliest look-back point is 2019-06-30 and the deepest card look-back is
# 10Y (SEMI_MAT_023), so history must start ten years before it.
PLAN_START = "20090101"
PLAN_END = "20230331"

# Endpoints paged one calendar year at a time (Tushare caps rows per call).
PAGED_ENDPOINTS = frozenset({"daily", "daily_basic", "adj_factor"})
PAGE_DAYS = 365

# Card catalog api -> extended source that persists it (history-shaped tables).
API_TO_SOURCE: Mapping[str, str] = {
    "income": "income",
    "balancesheet": "balancesheet",
    "cashflow": "cashflow",
    "fina_indicator": "fina_indicator",
    "fina_mainbz": "fina_mainbz",
    "daily_basic": "daily_basic_ext",
}
# income first: the fina_mainbz point-in-time view derives its date from it.
INGEST_ORDER = ("income", "balancesheet", "cashflow", "fina_indicator", "fina_mainbz", "daily_basic_ext")
MAINBZ_TYPES = extended.MAINBZ_TYPES

# Endpoints needed for reasons other than a card's own declared source pair.
STOCK_BASIC_FIELDS = "ts_code,list_date,delist_date"
STOCK_BASIC_STATUSES = ("L", "D", "P")
SUPPORT_ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    (
        "stock_basic",
        STOCK_BASIC_FIELDS,
        "已上市判定(每个回看点只纳入当时已上市的票);仓内 security_registry 已有,"
        "此调用仅用于交叉校验",
    ),
)


class PlanError(RuntimeError):
    pass


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_date8(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def year_windows(start: str, end: str) -> int:
    span_days = (_parse_date8(end) - _parse_date8(start)).days + 1
    if span_days <= 0:
        raise PlanError(f"empty date range: {start}..{end}")
    return int(math.ceil(span_days / PAGE_DAYS))


def _windows(start: str, end: str) -> list[tuple[str, str]]:
    cursor = _parse_date8(start)
    last = _parse_date8(end)
    output: list[tuple[str, str]] = []
    while cursor <= last:
        window_end = min(cursor + timedelta(days=PAGE_DAYS - 1), last)
        output.append((cursor.strftime("%Y%m%d"), window_end.strftime("%Y%m%d")))
        cursor = window_end + timedelta(days=1)
    return output


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------


def declared_endpoints(cards_path: Path) -> dict[str, dict[str, Any]]:
    """Which Tushare endpoints/fields the AUTO cards actually declare."""
    cards = knowledge_cards.load_cards(cards_path)
    wanted: dict[str, dict[str, Any]] = {}
    for card in backtest.auto_cards(cards):
        coverage = knowledge_cards.source_coverage(card)
        for pair in coverage["declared_pairs"]:
            endpoint = str(pair["api"])
            entry = wanted.setdefault(
                endpoint, {"endpoint": endpoint, "fields": set(), "card_ids": set()}
            )
            entry["fields"].add(str(pair["field"]))
            entry["card_ids"].add(str(card["card_id"]))
    return wanted


def endpoint_fields(endpoint: str, declared: Sequence[str]) -> list[str]:
    """The exact field list a request carries: the collector's declaration when
    one exists (so fetched rows match the ingest normalizer), else the cards'."""
    catalog = extended.CATALOG_DECLARATIONS.get(endpoint)
    if catalog:
        return [field.strip() for field in catalog.split(",") if field.strip()]
    return sorted(set(declared))


def collector_prerequisites(cards_path: Path) -> list[dict[str, Any]]:
    """Declared pairs no repository collector persists: history alone cannot
    unblock them. Derived every run so the list is empty exactly when it is."""
    cards = knowledge_cards.load_cards(cards_path)
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for card in backtest.auto_cards(cards):
        coverage = knowledge_cards.source_coverage(card)
        for pair in coverage["declared_pairs"]:
            if pair["collected_by_repo"]:
                continue
            key = (str(pair["api"]), str(pair["field"]))
            entry = by_pair.setdefault(
                key,
                {
                    "endpoint": key[0],
                    "field": key[1],
                    "card_ids": set(),
                    "reason": pair.get("reason") or knowledge_cards.REASON_NOT_COLLECTED,
                    "blocker": "仓内采集器未声明该字段(knowledge_cards.repo_collected_tushare_fields)",
                    "consequence": "收齐历史后该卡仍会 DATA_BLOCKED;需先改采集器声明",
                },
            )
            entry["card_ids"].add(str(card["card_id"]))
    return [
        {**entry, "card_ids": sorted(entry["card_ids"])}
        for _key, entry in sorted(by_pair.items())
    ]


def build_plan(
    *,
    cards_path: str | Path = backtest.DEFAULT_CARDS,
    start: str = PLAN_START,
    end: str = PLAN_END,
    cohort: Sequence[tuple[str, str]] = backtest.COHORT,
    out_dir: str | Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    resolved_cards = backtest._resolve(cards_path)
    wanted = declared_endpoints(resolved_cards)
    windows = year_windows(start, end)
    securities = [{"ts_code": code, "name": name} for code, name in cohort]

    requests: list[dict[str, Any]] = []
    fields_by_endpoint: dict[str, list[str]] = {}
    for endpoint in sorted(wanted):
        entry = wanted[endpoint]
        fields = endpoint_fields(endpoint, sorted(entry["fields"]))
        fields_by_endpoint[endpoint] = fields
        types: list[str] = []
        if endpoint in PAGED_ENDPOINTS:
            per_security = windows
            paging = f"每 {PAGE_DAYS} 天一页,共 {windows} 页"
        elif endpoint == "fina_mainbz":
            types = list(MAINBZ_TYPES)
            per_security = len(types)
            paging = "每报表类型(P/D/I)各一次,单次覆盖整个区间"
        else:
            per_security = 1
            paging = "单次调用覆盖整个区间"
        requests.append(
            {
                "endpoint": endpoint,
                "source": API_TO_SOURCE.get(endpoint),
                "fields": fields,
                "types": types,
                "requested_by_card_ids": sorted(entry["card_ids"]),
                "securities": len(securities),
                "requests_per_security": per_security,
                "estimated_requests": per_security * len(securities),
                "paging": paging,
                "purpose": "知识卡声明的数据源",
            }
        )
    for endpoint, fields, purpose in SUPPORT_ENDPOINTS:
        requests.append(
            {
                "endpoint": endpoint,
                "source": None,
                "fields": [field for field in fields.split(",") if field],
                "types": [],
                "requested_by_card_ids": [],
                "securities": 0,
                "requests_per_security": 0,
                "estimated_requests": len(STOCK_BASIC_STATUSES),
                "paging": f"全市场,按上市状态 {'/'.join(STOCK_BASIC_STATUSES)} 各一次",
                "purpose": purpose,
            }
        )

    total = sum(item["estimated_requests"] for item in requests)
    return {
        "schema": PLAN_SCHEMA,
        "generated_at": _iso_now(),
        "mode": "DRY_RUN_PLAN_ONLY",
        "executed": False,
        "approval_required": True,
        "approval_env": APPROVAL_ENV,
        "cards_path": str(cards_path),
        "cards_hash": knowledge_cards.canonical_hash(knowledge_cards.load_cards(resolved_cards)),
        "date_range": {
            "start": start,
            "end": end,
            "start_rationale": "最早回看点 20190630 减去卡片最深回看 10Y(SEMI_MAT_023)",
            "end_rationale": "最晚回看点 20230331;PIT 边界在评分阶段再次强制",
        },
        "securities": securities,
        "look_back_points": [dict(point) for point in backtest.LOOK_BACK_POINTS],
        "requests": requests,
        "fields_by_endpoint": fields_by_endpoint,
        "estimated_total_requests": total,
        "estimated_wall_clock_seconds_at_0p4s": round(total * 0.4, 1),
        "output_dir": str(out_dir),
        "history_db_default": DEFAULT_HISTORY_DB,
        "ingest_flow": "--ingest 将采集文件按 HISTORY 模式写入专用 store;禁止写入生产 feature store",
        "collector_prerequisites": collector_prerequisites(resolved_cards),
        "notes": [
            f"本脚本默认只打印计划;--execute 且 {APPROVAL_ENV}=1 才会真正发起请求。",
            "已上市判定用 security_registry 的 list_date;stock_basic 仅作交叉校验,"
            "缺 list_date 的票显式排除而不是猜测。",
            "采集区间可以超过回看点,但 PIT 边界由 "
            "experiments/research_funnel/knowledge_card_backtest.py 在评分时强制,越界即抛错。",
            "collector_prerequisites 列出的字段即使收齐历史也仍会 DATA_BLOCKED,需要先改采集器声明。",
            "fina_mainbz 无 ann_date,其 PIT 日期在入库后借同期 income.ann_date 派生;income 必须先入库。",
        ],
        "disclaimer": DISCLAIMER,
    }


def render_plan(plan: Mapping[str, Any]) -> str:
    lines = [
        "WO-B4 知识卡历史采集计划 (DRY RUN — 未执行任何请求)",
        f"  卡表        : {plan['cards_path']}",
        f"  区间        : {plan['date_range']['start']} .. {plan['date_range']['end']}",
        f"  票池        : {len(plan['securities'])} 只 — "
        + ", ".join(f"{item['ts_code']}({item['name']})" for item in plan["securities"]),
        "  回看点      : "
        + ", ".join(
            f"{point['as_of']}[{point['cycle_label']}]" for point in plan["look_back_points"]
        ),
        "",
        "  接口                字段                                        票数 x 次数 = 估计请求",
    ]
    for item in plan["requests"]:
        fields = ",".join(item["fields"])
        if len(fields) > 42:
            fields = fields[:39] + "..."
        lines.append(
            f"  {item['endpoint']:<18} {fields:<44} "
            f"{item['securities']:>3} x {item['requests_per_security']:<4} = "
            f"{item['estimated_requests']:>4}   [{item['paging']}]"
        )
    lines.extend(
        [
            "",
            f"  估计请求总数: {plan['estimated_total_requests']}",
            f"  估计耗时    : ~{plan['estimated_wall_clock_seconds_at_0p4s']}s (0.4s/请求)",
            f"  输出目录    : {plan['output_dir']}",
            f"  入库目标    : {plan['history_db_default']}(专用 store;--ingest)",
            "",
            "  即使收齐历史也仍然 DATA_BLOCKED 的字段(需先改采集器声明):",
        ]
    )
    if plan["collector_prerequisites"]:
        for item in plan["collector_prerequisites"]:
            lines.append(
                f"    - {item['endpoint']}.{item['field']} [{','.join(item['card_ids'])}]: "
                f"{item['blocker']} → {item['consequence']}"
            )
    else:
        lines.append("    (无 —— 每个声明的字段仓内都有采集器声明)")
    lines.extend(["", "  说明:"])
    lines.extend(f"    - {note}" for note in plan["notes"])
    lines.extend(
        [
            "",
            f"  执行需人类批准: --execute 且 {plan['approval_env']}=1 且 TUSHARE_TOKEN 就绪。",
            f"  {plan['disclaimer']}",
        ]
    )
    return "\n".join(lines)


def _refuse_execution(reason: str) -> int:
    print(f"REFUSED: {reason}", file=sys.stderr)
    print("本次运行没有发起任何请求。请人类先审阅上面的计划再决定。", file=sys.stderr)
    return 2


# --------------------------------------------------------------------------
# fetch (only after explicit approval)
# --------------------------------------------------------------------------


Fetcher = Callable[[str, str, dict[str, Any], str], list[dict[str, Any]]]


def _request_params(item: Mapping[str, Any], ts_code: str | None, start: str, end: str) -> list[dict[str, Any]]:
    endpoint = str(item["endpoint"])
    if endpoint == "stock_basic":
        return [{"exchange": "", "list_status": status} for status in STOCK_BASIC_STATUSES]
    if endpoint in PAGED_ENDPOINTS:
        return [
            {"ts_code": ts_code, "start_date": window_start, "end_date": window_end}
            for window_start, window_end in _windows(start, end)
        ]
    if endpoint == "fina_mainbz":
        return [
            {"ts_code": ts_code, "type": bz_type, "start_date": start, "end_date": end}
            for bz_type in item["types"]
        ]
    return [{"ts_code": ts_code, "start_date": start, "end_date": end}]


def _file_name(endpoint: str, ts_code: str | None, bz_type: str | None) -> str:
    parts = [endpoint]
    if bz_type:
        parts.append(bz_type)
    parts.append(ts_code or "ALL")
    return "__".join(parts) + ".json"


def execute_plan(
    plan: Mapping[str, Any],
    sleep_seconds: float,
    *,
    fetcher: Fetcher | None = None,
    token: str | None = None,
) -> int:
    """Run the printed plan verbatim. Reached only after explicit approval.

    The token comes from the environment, is passed to the transport helper
    only, and is never written into any file or message.
    """
    transport = fetcher or security_registry._tushare_call
    secret = (token if token is not None else os.environ.get("TUSHARE_TOKEN", "")).strip()
    if not secret:
        raise PlanError("TUSHARE_TOKEN is empty")
    out_dir = backtest._resolve(plan["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    start = plan["date_range"]["start"]
    end = plan["date_range"]["end"]
    issued = 0
    receipts: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []

    for item in plan["requests"]:
        endpoint = str(item["endpoint"])
        fields = ",".join(item["fields"])
        targets: list[str | None] = (
            [security["ts_code"] for security in plan["securities"]] if item["securities"] else [None]
        )
        for ts_code in targets:
            param_sets = _request_params(item, ts_code, start, end)
            # One file per (endpoint, type, security); mainbz keeps one file per type.
            grouped: dict[str | None, dict[str, Any]] = {}
            for params in param_sets:
                bz_type = params.get("type")
                bucket = grouped.setdefault(
                    bz_type, {"rows": [], "params": [], "errors": []},
                )
                try:
                    rows = transport(secret, endpoint, dict(params), fields)
                    bucket["rows"].extend(rows)
                    bucket["params"].append(dict(params))
                    receipts.append(
                        {"endpoint": endpoint, "ts_code": ts_code, "type": bz_type,
                         "params": dict(params), "status": "OK", "rows": len(rows)}
                    )
                except RegistryError as exc:  # transport boundary; message carries no token
                    receipts.append(
                        {"endpoint": endpoint, "ts_code": ts_code, "type": bz_type,
                         "params": dict(params), "status": "ERROR",
                         "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
                    )
                    bucket["errors"].append(f"{type(exc).__name__}: {str(exc)[:200]}")
                issued += 1
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
            for bz_type, bucket in grouped.items():
                name = _file_name(endpoint, ts_code, bz_type)
                path = out_dir / name
                path.write_text(
                    json.dumps(
                        {
                            "endpoint": endpoint,
                            "source": item.get("source"),
                            "type": bz_type,
                            "ts_code": ts_code,
                            "fields": item["fields"],
                            "start_date": start,
                            "end_date": end,
                            "params": bucket["params"],
                            "errors": bucket["errors"],
                            "fetched_at": _iso_now(),
                            "rows": bucket["rows"],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                files.append(
                    {"name": name, "endpoint": endpoint, "source": item.get("source"),
                     "type": bz_type, "ts_code": ts_code, "rows": len(bucket["rows"]),
                     "errors": len(bucket["errors"]), "sha256": _sha256_file(path)}
                )

    errors = sum(1 for receipt in receipts if receipt["status"] == "ERROR")
    (out_dir / FETCH_RECEIPT_NAME).write_text(
        json.dumps(
            {
                "schema": FETCH_RECEIPT_SCHEMA,
                "executed": True,
                "plan_schema": plan["schema"],
                "cards_hash": plan["cards_hash"],
                "date_range": dict(plan["date_range"]),
                "securities": [dict(security) for security in plan["securities"]],
                "issued_requests": issued,
                "estimated_requests": plan["estimated_total_requests"],
                "error_count": errors,
                "receipts": receipts,
                "files": files,
                "finished_at": _iso_now(),
                "disclaimer": DISCLAIMER,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"executed requests={issued} errors={errors} files={len(files)} output_dir={out_dir}")
    return 0 if errors == 0 else 1


# --------------------------------------------------------------------------
# ingest (offline; dedicated store only)
# --------------------------------------------------------------------------


def is_production_store(path: str | Path) -> bool:
    candidate = Path(path).expanduser().resolve()
    production = {
        (REPO_ROOT / PRODUCTION_STORE).resolve(),
        Path(PRODUCTION_STORE).expanduser().resolve(),
    }
    return candidate in production or candidate.name == Path(PRODUCTION_STORE).name


def _receipt_as_of(receipt: Mapping[str, Any]) -> str:
    finished = str(receipt.get("finished_at") or "")
    if len(finished) < 10:
        raise PlanError("fetch receipt has no finished_at stamp")
    return _date8(finished[:10].replace("-", ""))


def _load_rows(out_dir: Path, receipt: Mapping[str, Any], source_name: str) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    names: list[str] = []
    for entry in receipt.get("files", []):
        if API_TO_SOURCE.get(str(entry.get("endpoint"))) != source_name:
            continue
        path = out_dir / str(entry["name"])
        if not path.is_file():
            raise PlanError(f"fetched file is missing: {path}")
        if _sha256_file(path) != entry.get("sha256"):
            raise PlanError(f"fetched file hash drifted since the receipt: {path.name}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        bz_type = payload.get("type")
        for raw in payload.get("rows", []):
            row = dict(raw)
            if source_name == "fina_mainbz":
                row["bz_type"] = bz_type
            rows.append(row)
        names.append(path.name)
    return rows, names


def _disclosure_coverage(rows: Sequence[Mapping[str, Any]], start: str, end: str, as_of: str) -> tuple[str, str]:
    """History fetches filter statements by announcement date, so a report
    period can precede the plan window; coverage is widened to what was seen."""
    periods = [str(row.get("end_date") or "") for row in rows if row.get("end_date")]
    lo = min([start, *periods]) if periods else start
    hi = max([end, *periods]) if periods else end
    return lo, min(hi, as_of)


def ingest_history(
    out_dir: str | Path,
    history_db: str | Path,
    *,
    cohort: Sequence[tuple[str, str]] = backtest.COHORT,
    points: Sequence[Mapping[str, str]] = backtest.LOOK_BACK_POINTS,
) -> dict[str, Any]:
    directory = backtest._resolve(out_dir)
    db = backtest._resolve(history_db)
    if is_production_store(db):
        raise PlanError(
            f"history store must be a dedicated file, never the production feature store: {db}"
        )
    receipt_path = directory / FETCH_RECEIPT_NAME
    if not receipt_path.is_file():
        raise PlanError(f"no fetch receipt at {receipt_path}; run --execute (approved) first")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema") != FETCH_RECEIPT_SCHEMA or receipt.get("executed") is not True:
        raise PlanError("fetch receipt is not an executed history fetch receipt")
    as_of = _receipt_as_of(receipt)
    start = _date8(str(receipt["date_range"]["start"]))
    end = _date8(str(receipt["date_range"]["end"]))
    codes = sorted({str(code) for code, _name in cohort})
    universe_hash = _sha256(codes)

    results: list[dict[str, Any]] = []
    failures = 0
    for source_name in INGEST_ORDER:
        rows, names = _load_rows(directory, receipt, source_name)
        spec = extended.EXTENDED_SOURCES[source_name]
        if spec.shape == "DISCLOSURE":
            coverage_start, coverage_end = _disclosure_coverage(rows, start, end, as_of)
        else:
            coverage_start, coverage_end = start, min(end, as_of)
        try:
            outcome = extended.ingest_extended_source(
                db, source_name, as_of, rows, codes, universe_hash,
                mode="HISTORY", coverage_start=coverage_start, coverage_end=coverage_end,
            )
            results.append({**outcome, "files": names, "raw_rows": len(rows)})
        except SemiconductorInputError as exc:
            failures += 1
            results.append(
                {"source": source_name, "as_of": as_of, "status": "INGEST_FAILED",
                 "error": f"{type(exc).__name__}: {str(exc)[:300]}", "files": names,
                 "raw_rows": len(rows)}
            )

    snapshots: list[dict[str, Any]] = []
    for point in points:
        try:
            snapshot = extended.build_extended_snapshot(db, None, point["as_of"], codes=codes)
            snapshots.append(
                {
                    "point_id": point["point_id"],
                    "as_of": point["as_of"],
                    "status": snapshot["status"],
                    "coverage": {
                        name: snapshot["coverage"][name] for name in INGEST_ORDER
                    },
                }
            )
        except SemiconductorInputError as exc:
            failures += 1
            snapshots.append(
                {"point_id": point["point_id"], "as_of": point["as_of"],
                 "status": "SNAPSHOT_FAILED", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            )

    payload = {
        "schema": INGEST_RECEIPT_SCHEMA,
        "history_db": str(db),
        "fetch_receipt": str(receipt_path),
        "fetch_receipt_sha256": _sha256_file(receipt_path),
        "as_of": as_of,
        "codes": codes,
        "universe_hash": universe_hash,
        "sources": results,
        "look_back_snapshots": snapshots,
        "failures": failures,
        "finished_at": _iso_now(),
        "disclaimer": DISCLAIMER,
    }
    (directory / INGEST_RECEIPT_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def render_ingest(payload: Mapping[str, Any]) -> str:
    lines = [f"history ingest -> {payload['history_db']} (as_of={payload['as_of']}, codes={len(payload['codes'])})"]
    for item in payload["sources"]:
        extra = (
            f" inserted={item.get('inserted_count')} observed={item.get('observed_count')}"
            if item.get("status") in ("INGESTED",) else (f" error={item.get('error')}" if item.get("error") else "")
        )
        lines.append(f"  {item['source']:<16} {item['status']:<18} raw_rows={item['raw_rows']}{extra}")
    for snap in payload["look_back_snapshots"]:
        if "coverage" in snap:
            parts = ", ".join(
                f"{name}:{cov['complete']}/{cov['not_observed']}/{cov['data_blocked']}"
                for name, cov in snap["coverage"].items()
            )
            lines.append(f"  {snap['point_id']} {snap['status']:<9} complete/not_observed/data_blocked -> {parts}")
        else:
            lines.append(f"  {snap['point_id']} {snap['status']} {snap.get('error')}")
    lines.append(f"  failures={payload['failures']}")
    lines.append(f"  {payload['disclaimer']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cards", default=backtest.DEFAULT_CARDS)
    parser.add_argument("--start", default=PLAN_START)
    parser.add_argument("--end", default=PLAN_END)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--sleep", type=float, default=0.4)
    parser.add_argument(
        "--dry-run", dest="dry_run", action="store_true", default=True,
        help="print the plan and exit (default)",
    )
    parser.add_argument(
        "--execute", dest="dry_run", action="store_false",
        help=f"actually collect; also requires {APPROVAL_ENV}=1 and TUSHARE_TOKEN",
    )
    parser.add_argument(
        "--ingest", action="store_true",
        help="load the fetched files from --out-dir into --history-db (offline, no approval env)",
    )
    parser.add_argument("--history-db", default=DEFAULT_HISTORY_DB)
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.ingest:
        try:
            payload = ingest_history(args.out_dir, args.history_db)
        except (PlanError, SemiconductorInputError, OSError, ValueError) as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        print(render_ingest(payload))
        return 0 if payload["failures"] == 0 else 1
    try:
        plan = build_plan(
            cards_path=args.cards, start=args.start, end=args.end, out_dir=args.out_dir
        )
    except (PlanError, knowledge_cards.KnowledgeCardError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(plan, ensure_ascii=False, indent=2) if args.json else render_plan(plan))

    if args.dry_run:
        return 0
    if os.environ.get("AR_OFFLINE") == "1":
        return _refuse_execution("AR_OFFLINE=1 时禁止采集")
    if os.environ.get(APPROVAL_ENV) != "1":
        return _refuse_execution(
            f"缺少人类批准:需要 {APPROVAL_ENV}=1 才能执行采集(默认永远是 dry-run)"
        )
    if not os.environ.get("TUSHARE_TOKEN", "").strip():
        return _refuse_execution("缺少 TUSHARE_TOKEN")
    plan = dict(plan)
    plan["mode"] = "EXECUTED_AFTER_HUMAN_APPROVAL"
    return execute_plan(plan, args.sleep)


if __name__ == "__main__":
    raise SystemExit(main())
