#!/usr/bin/env python3
"""Collection PLAN for the history WO-B4 needs. Dry-run by default; never auto-runs.

WO-B4 replays the reviewed AUTO knowledge cards on three known cycle points
(2019-06-30 / 2021-09-30 / 2023-03-31). The local point-in-time store does not
reach back that far, so the look-back is DATA_BLOCKED until this history is
collected.

Collecting it costs real Tushare quota and is therefore a human decision. This
script prints exactly what would be requested — which endpoints, which
securities, which date range, how many requests — and refuses to execute unless
a human explicitly approves the run:

    python3 scripts/fetch_knowledge_card_history.py                 # plan only
    python3 scripts/fetch_knowledge_card_history.py --execute       # refused
    AR_HISTORY_FETCH_APPROVED=1 TUSHARE_TOKEN=... \\
        python3 scripts/fetch_knowledge_card_history.py --execute   # runs

The plan is derived from the committed card table, not hand-typed, so it stays
truthful when the cards change. This script performs no selection, ranking, or
trade action of any kind.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
FUNNEL = REPO_ROOT / "experiments" / "research_funnel"
if str(FUNNEL) not in sys.path:
    sys.path.insert(0, str(FUNNEL))

import knowledge_card_backtest as backtest  # noqa: E402
import knowledge_cards  # noqa: E402


PLAN_SCHEMA = "ar.knowledge_card_history_plan.v1"
APPROVAL_ENV = "AR_HISTORY_FETCH_APPROVED"
DEFAULT_OUT_DIR = "data_history/knowledge_card_history"
DISCLAIMER = (
    "采集计划,不是采集本身;执行需人类批准。No selection, ranking, or trade action."
)

# The earliest look-back point is 2019-06-30 and the deepest card look-back is
# 10Y (SEMI_MAT_023), so history must start ten years before it.
PLAN_START = "20090101"
PLAN_END = "20230331"

# Endpoints paged one calendar year at a time by the repository's existing
# history collector (scripts/fetch_history_tushare.py PAGE_DAYS = 365).
PAGED_ENDPOINTS = frozenset({"daily", "daily_basic", "adj_factor"})
# Endpoints the same collector requests once per security per date range.
SINGLE_CALL_ENDPOINTS = frozenset(
    {"income", "balancesheet", "cashflow", "fina_indicator", "fina_mainbz"}
)
PAGE_DAYS = 365

# Endpoints needed for reasons other than a card's own declared source pair.
SUPPORT_ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    (
        "stock_basic",
        "list_date,delist_date",
        "已上市判定(每个回看点只纳入当时已上市的票);仓内 security_registry 已有,"
        "此调用仅用于交叉校验",
    ),
)

# Gaps this collection alone does NOT close: the field is absent from the
# repository's collector declarations, so a code change must land first.
COLLECTOR_PREREQUISITES: tuple[Mapping[str, str], ...] = (
    {
        "endpoint": "daily_basic",
        "field": "ps_ttm",
        "blocker": "feature_store.ENDPOINT_FIELDS 未声明 ps_ttm",
        "consequence": "SEMI_MAT_023 的 ps_ttm 分位在收齐历史后仍会 DATA_BLOCKED",
    },
    {
        "endpoint": "fina_indicator",
        "field": "inv_turn,invturn_days",
        "blocker": "semiconductor_inputs.FINANCIAL_FIELDS 未声明这两个字段",
        "consequence": "SEMI_MAT_008 / SEMI_MAT_016 的周转项仍会 DATA_BLOCKED",
    },
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
    for endpoint in sorted(wanted):
        entry = wanted[endpoint]
        if endpoint in PAGED_ENDPOINTS:
            per_security = windows
            paging = f"每 {PAGE_DAYS} 天一页,共 {windows} 页"
        elif endpoint in SINGLE_CALL_ENDPOINTS:
            per_security = 1
            paging = "单次调用覆盖整个区间"
        else:
            per_security = 1
            paging = "分页形态未知,按 1 次估算(执行前需人工确认)"
        requests.append(
            {
                "endpoint": endpoint,
                "fields": sorted(entry["fields"]),
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
                "fields": sorted(fields.split(",")),
                "requested_by_card_ids": [],
                "securities": 0,
                "requests_per_security": 0,
                "estimated_requests": 1,
                "paging": "全市场单次调用",
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
        "cards_hash": knowledge_cards.canonical_hash(
            knowledge_cards.load_cards(resolved_cards)
        ),
        "date_range": {
            "start": start,
            "end": end,
            "start_rationale": (
                "最早回看点 20190630 减去卡片最深回看 10Y(SEMI_MAT_023)"
            ),
            "end_rationale": "最晚回看点 20230331;PIT 边界在评分阶段再次强制",
        },
        "securities": securities,
        "look_back_points": [dict(point) for point in backtest.LOOK_BACK_POINTS],
        "requests": requests,
        "estimated_total_requests": total,
        "estimated_wall_clock_seconds_at_0p4s": round(total * 0.4, 1),
        "output_dir": str(out_dir),
        "collector_prerequisites": [dict(item) for item in COLLECTOR_PREREQUISITES],
        "notes": [
            "本脚本默认只打印计划;--execute 且 "
            f"{APPROVAL_ENV}=1 才会真正发起请求。",
            "已上市判定用 security_registry 的 list_date;stock_basic 仅作交叉校验,"
            "缺 list_date 的票显式排除而不是猜测。",
            "采集区间可以超过回看点,但 PIT 边界由 "
            "experiments/research_funnel/knowledge_card_backtest.py 在评分时强制,"
            "越界即抛错。",
            "collector_prerequisites 列出的字段即使收齐历史也仍会 DATA_BLOCKED,"
            "需要先改采集器声明。",
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
        f"  回看点      : "
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
            "",
            "  即使收齐历史也仍然 DATA_BLOCKED 的字段(需先改采集器声明):",
        ]
    )
    for item in plan["collector_prerequisites"]:
        lines.append(
            f"    - {item['endpoint']}.{item['field']}: {item['blocker']} → {item['consequence']}"
        )
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
    print(
        "本次运行没有发起任何请求。请人类先审阅上面的计划再决定。",
        file=sys.stderr,
    )
    return 2


def execute_plan(plan: Mapping[str, Any], sleep_seconds: float) -> int:
    """Run the printed plan verbatim. Reached only after explicit approval."""
    import tushare as ts  # imported here so the dry run never needs the dependency

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    pro = ts.pro_api(token)
    out_dir = backtest._resolve(plan["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    start = plan["date_range"]["start"]
    end = plan["date_range"]["end"]
    issued = 0
    receipts: list[dict[str, Any]] = []

    for item in plan["requests"]:
        endpoint = item["endpoint"]
        api = getattr(pro, endpoint, None)
        if api is None:
            receipts.append({"endpoint": endpoint, "status": "ENDPOINT_UNAVAILABLE", "rows": 0})
            continue
        targets = (
            [security["ts_code"] for security in plan["securities"]]
            if item["securities"]
            else [None]
        )
        for ts_code in targets:
            kwargs: dict[str, Any] = {"start_date": start, "end_date": end}
            if ts_code is not None:
                kwargs["ts_code"] = ts_code
            try:
                frame = api(**kwargs)
                rows = [] if frame is None else json.loads(frame.to_json(orient="records"))
            except Exception as exc:  # noqa: BLE001 - receipt records the failure
                receipts.append(
                    {
                        "endpoint": endpoint,
                        "ts_code": ts_code,
                        "status": "ERROR",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                issued += 1
                time.sleep(sleep_seconds)
                continue
            name = f"{endpoint}__{ts_code or 'ALL'}.json"
            (out_dir / name).write_text(
                json.dumps(
                    {
                        "endpoint": endpoint,
                        "ts_code": ts_code,
                        "start_date": start,
                        "end_date": end,
                        "fetched_at": _iso_now(),
                        "rows": rows,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            receipts.append(
                {"endpoint": endpoint, "ts_code": ts_code, "status": "OK", "rows": len(rows)}
            )
            issued += 1
            time.sleep(sleep_seconds)

    (out_dir / "fetch_receipt.json").write_text(
        json.dumps(
            {
                "schema": PLAN_SCHEMA,
                "executed": True,
                "issued_requests": issued,
                "estimated_requests": plan["estimated_total_requests"],
                "receipts": receipts,
                "finished_at": _iso_now(),
                "disclaimer": DISCLAIMER,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"executed requests={issued} output_dir={out_dir}")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards", default=backtest.DEFAULT_CARDS)
    parser.add_argument("--start", default=PLAN_START)
    parser.add_argument("--end", default=PLAN_END)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--sleep", type=float, default=0.4)
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="print the plan and exit (default)",
    )
    parser.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help=f"actually collect; also requires {APPROVAL_ENV}=1 and TUSHARE_TOKEN",
    )
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
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
