#!/usr/bin/env python3
"""M0-B2 adapters for explicit official NBS, PBOC, and ISM releases.

These adapters deliberately do not discover release URLs.  M0-B3 owns the
release scheduler and discovery loop.  A caller must provide the exact HTTPS
official release URL in the documented environment variable; the adapter then
validates the host, stores the source bytes, and emits typed observations.

ISM collection also requires an explicit content-permission acknowledgement.
Without it the adapter is DATA_BLOCKED before any network request is made.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.macro_os import collectors, contracts
from experiments.macro_os.storage import DEFAULT_DB, MacroHistoryStore, MacroStoreError, Observation


COLLECTOR_VERSION = "macro-m0b2-releases/1.0"
DEFAULT_HEALTH = Path("public/data/v2/macro/official_release_health.json")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self.parts.append(data)


def _html_text(raw: bytes) -> str:
    decoded: str | None = None
    for encoding in ("utf-8", "gb18030"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise collectors.CollectionError(
            "DATA_INVALID", "RELEASE_ENCODING", "official release is neither UTF-8 nor GB18030"
        )
    parser = _TextExtractor()
    try:
        parser.feed(decoded)
    except Exception as exc:
        raise collectors.CollectionError(
            "DATA_INVALID", "RELEASE_HTML", "official release HTML cannot be parsed"
        ) from exc
    normalized = re.sub(r"\s+", " ", html.unescape(" ".join(parser.parts))).strip()
    if not normalized:
        raise collectors.CollectionError(
            "DATA_INVALID", "RELEASE_EMPTY", "official release contains no readable text"
        )
    return normalized


def _period_from_text(text: str) -> str:
    monthly = re.search(r"(20[0-9]{2})\s*年\s*(1[0-2]|[1-9])\s*月(?:份)?", text)
    if monthly:
        return collectors._date_iso(int(monthly.group(1)), int(monthly.group(2)))
    quarter = re.search(r"(20[0-9]{2})\s*年\s*(一季度|上半年|前三季度|全年)", text)
    if quarter:
        month = {"一季度": 1, "上半年": 4, "前三季度": 7, "全年": 10}[quarter.group(2)]
        return collectors._date_iso(int(quarter.group(1)), month)
    english = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20[0-9]{2})\b",
        text,
        re.IGNORECASE,
    )
    if english:
        month_names = {
            name: index
            for index, name in enumerate(
                "January February March April May June July August September October November December".split(),
                1,
            )
        }
        return collectors._date_iso(int(english.group(2)), month_names[english.group(1).title()])
    raise collectors.CollectionError(
        "DATA_INVALID", "RELEASE_PERIOD", "official release lacks a supported observation period"
    )


def _pct(text: str, pattern: str, label: str) -> tuple[str, float]:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        raise collectors.CollectionError(
            "DATA_INVALID", "RELEASE_VALUE", f"official release lacks {label}"
        )
    direction = (match.groupdict().get("direction") or "").lower()
    value = float(match.group("value").replace(",", ""))
    if direction in {"下降", "减少", "回落", "contracted", "decreased", "fell"}:
        value = -abs(value)
    return f"{value:g}", value


def _amount_100m_cny(text: str, pattern: str, label: str) -> tuple[str, float]:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        raise collectors.CollectionError(
            "DATA_INVALID", "RELEASE_VALUE", f"official release lacks {label}"
        )
    value = float(match.group("value").replace(",", ""))
    unit = match.group("unit")
    normalized = value * 10000 if unit == "万亿元" else value
    return f"{normalized:g}", normalized


def _observation(
    metric: collectors.MetricSpec,
    period: str,
    fetched_at: str,
    value_text: str,
    value: float,
    attributes: dict[str, Any],
) -> Observation:
    return Observation(
        series_id=metric.series_id,
        metric_key=metric.metric_key,
        observation_at=period,
        vintage_at=fetched_at,
        value_text=value_text,
        value=value,
        unit=metric.unit,
        attributes={"native_series_id": metric.native_series_id, **attributes},
    )


NBS_RULES: dict[str, tuple[str, str]] = {
    "headline_cpi_yoy": (
        r"居民消费价格(?:指数|CPI)?.{0,160}?(?P<direction>上涨|增长|下降|回落)?\s*(?P<value>[+-]?[0-9]+(?:\.[0-9]+)?)\s*%",
        "CPI同比",
    ),
    "producer_price_yoy": (
        r"工业生产者出厂价格(?:指数|PPI)?.{0,160}?(?P<direction>上涨|增长|下降|回落)?\s*(?P<value>[+-]?[0-9]+(?:\.[0-9]+)?)\s*%",
        "PPI同比",
    ),
    "manufacturing_pmi": (
        r"(?:制造业采购经理指数|制造业PMI|PMI).{0,80}?(?:为|是)\s*(?P<value>[0-9]+(?:\.[0-9]+)?)\s*%?",
        "制造业PMI",
    ),
    "real_gdp_yoy": (
        r"国内生产总值.{0,220}?同比(?P<direction>增长|下降)?\s*(?P<value>[+-]?[0-9]+(?:\.[0-9]+)?)\s*%",
        "GDP同比",
    ),
    "industrial_production_yoy": (
        r"规模以上工业增加值.{0,180}?同比(?P<direction>增长|下降)?\s*(?P<value>[+-]?[0-9]+(?:\.[0-9]+)?)\s*%",
        "工业增加值同比",
    ),
    "retail_sales_yoy": (
        r"社会消费品零售总额.{0,180}?同比(?P<direction>增长|下降)?\s*(?P<value>[+-]?[0-9]+(?:\.[0-9]+)?)\s*%",
        "社会消费品零售同比",
    ),
    "fixed_asset_investment_yoy": (
        r"固定资产投资(?:（不含农户）|\(不含农户\))?.{0,180}?(?:同比)?(?P<direction>增长|下降)?\s*(?P<value>[+-]?[0-9]+(?:\.[0-9]+)?)\s*%",
        "固定资产投资同比",
    ),
    "surveyed_unemployment_rate": (
        r"城镇调查失业率.{0,80}?(?:为|是)\s*(?P<value>[0-9]+(?:\.[0-9]+)?)\s*%",
        "城镇调查失业率",
    ),
}


def _nbs_parser(raw: bytes, fetched_at: str, spec: collectors.RequestSpec) -> list[Observation]:
    text = _html_text(raw)
    period = _period_from_text(text)
    metric = spec.metrics[0]
    pattern, label = NBS_RULES[metric.metric_key]
    value_text, value = _pct(text, pattern, label)
    return [_observation(metric, period, fetched_at, value_text, value, {"parser": "nbs_release/v1"})]


def _pboc_parser(raw: bytes, fetched_at: str, spec: collectors.RequestSpec) -> list[Observation]:
    text = _html_text(raw)
    period = _period_from_text(text)
    rows: list[Observation] = []
    for metric in spec.metrics:
        if metric.metric_key == "lpr_1y":
            value_text, value = _pct(
                text,
                r"1\s*年期\s*LPR\s*(?:为|是)\s*(?P<value>[0-9]+(?:\.[0-9]+)?)\s*%",
                "1年期LPR",
            )
        elif metric.metric_key == "lpr_5y":
            value_text, value = _pct(
                text,
                r"5\s*年期以上\s*LPR\s*(?:为|是)\s*(?P<value>[0-9]+(?:\.[0-9]+)?)\s*%",
                "5年期以上LPR",
            )
        elif metric.metric_key == "m2_yoy":
            value_text, value = _pct(
                text,
                r"(?:广义货币\s*[（(]M2[）)]|M2).{0,120}?同比(?P<direction>增长|下降)?\s*(?P<value>[+-]?[0-9]+(?:\.[0-9]+)?)\s*%",
                "M2同比",
            )
        elif metric.metric_key == "aggregate_financing_increment":
            value_text, value = _amount_100m_cny(
                text,
                r"社会融资规模增量.{0,100}?(?:为|是)\s*(?P<value>[0-9,]+(?:\.[0-9]+)?)\s*(?P<unit>万亿元|亿元)",
                "社会融资规模增量",
            )
        elif metric.metric_key == "new_rmb_loans":
            value_text, value = _amount_100m_cny(
                text,
                r"人民币贷款(?:增加|新增)\s*(?P<value>[0-9,]+(?:\.[0-9]+)?)\s*(?P<unit>万亿元|亿元)",
                "人民币新增贷款",
            )
        else:  # pragma: no cover - construction invariant
            raise collectors.CollectionError("DATA_INVALID", "PBOC_RULE", "unknown PBOC metric")
        rows.append(_observation(metric, period, fetched_at, value_text, value, {"parser": "pboc_release/v1"}))
    return rows


def _ism_parser(raw: bytes, fetched_at: str, spec: collectors.RequestSpec) -> list[Observation]:
    text = _html_text(raw)
    period = _period_from_text(text)
    metric = spec.metrics[0]
    if metric.series_id == "manufacturing_pmi":
        pattern = r"Manufacturing\s+PMI.{0,100}?(?:registered|was|at)\s*(?P<value>[0-9]+(?:\.[0-9]+)?)\s*(?:percent|%)"
        label = "Manufacturing PMI"
    else:
        pattern = r"Services\s+PMI.{0,100}?(?:registered|was|at)\s*(?P<value>[0-9]+(?:\.[0-9]+)?)\s*(?:percent|%)"
        label = "Services PMI"
    value_text, value = _pct(text, pattern, label)
    return [_observation(metric, period, fetched_at, value_text, value, {"parser": "ism_release/v1"})]


def _release_builder(
    env_name: str,
    allowed_hosts: tuple[str, ...],
    *,
    permission_env: str | None = None,
) -> collectors.Builder:
    def build(_now: datetime, env: dict[str, str]) -> collectors.HttpRequest:
        if permission_env and env.get(permission_env) != "1":
            raise collectors.CollectionError(
                "DATA_BLOCKED",
                "ISM_CONTENT_PERMISSION_MISSING",
                "ISM content collection requires an explicit permission acknowledgement",
            )
        url = env.get(env_name, "").strip()
        if not url:
            raise collectors.CollectionError(
                "DATA_BLOCKED", f"{env_name}_MISSING", f"{env_name} is not configured"
            )
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in allowed_hosts:
            raise collectors.CollectionError(
                "DATA_INVALID", "UNAPPROVED_RELEASE_URL", "release URL is outside the official host allowlist"
            )
        public = collectors._sanitize_url(
            urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")),
            env,
        )
        return collectors.HttpRequest(
            method="GET",
            url=url,
            public_locator=public,
            headers={"Accept": "text/html", "User-Agent": "Alpha-Research-MacroOS/1"},
            body=None,
            allowed_hosts=allowed_hosts,
        )

    return build


MONTHLY_AGE = collectors.MONTHLY_AGE
MONTHLY_FETCH = collectors.MONTHLY_FETCH
QUARTERLY_AGE = collectors.QUARTERLY_AGE

NBS_METRICS = (
    ("nbs_cpi", "NBS_CPI_RELEASE_URL", collectors.MetricSpec("cn_cpi", "headline_cpi_yoy", "NBS_CPI_YOY", "pct_yoy", "monthly", MONTHLY_AGE, MONTHLY_FETCH)),
    ("nbs_ppi", "NBS_PPI_RELEASE_URL", collectors.MetricSpec("cn_ppi", "producer_price_yoy", "NBS_PPI_YOY", "pct_yoy", "monthly", MONTHLY_AGE, MONTHLY_FETCH)),
    ("nbs_pmi", "NBS_PMI_RELEASE_URL", collectors.MetricSpec("cn_pmi", "manufacturing_pmi", "NBS_MANUFACTURING_PMI", "index_points", "monthly", MONTHLY_AGE, MONTHLY_FETCH)),
    ("nbs_gdp", "NBS_GDP_RELEASE_URL", collectors.MetricSpec("cn_gdp", "real_gdp_yoy", "NBS_REAL_GDP_YOY", "pct_yoy", "quarterly", QUARTERLY_AGE, MONTHLY_FETCH)),
    ("nbs_industrial", "NBS_INDUSTRIAL_RELEASE_URL", collectors.MetricSpec("industrial_production", "industrial_production_yoy", "NBS_INDUSTRIAL_YOY", "pct_yoy", "monthly", MONTHLY_AGE, MONTHLY_FETCH)),
    ("nbs_retail", "NBS_RETAIL_RELEASE_URL", collectors.MetricSpec("retail_sales", "retail_sales_yoy", "NBS_RETAIL_YOY", "pct_yoy", "monthly", MONTHLY_AGE, MONTHLY_FETCH)),
    ("nbs_fai", "NBS_FAI_RELEASE_URL", collectors.MetricSpec("fixed_asset_investment", "fixed_asset_investment_yoy", "NBS_FAI_YOY", "pct_yoy", "monthly", MONTHLY_AGE, MONTHLY_FETCH)),
    ("nbs_unemployment", "NBS_UNEMPLOYMENT_RELEASE_URL", collectors.MetricSpec("unemployment_rate", "surveyed_unemployment_rate", "NBS_SURVEYED_UNEMPLOYMENT", "pct", "monthly", MONTHLY_AGE, MONTHLY_FETCH)),
)

PBOC_SPECS = (
    ("pboc_lpr", "PBOC_LPR_RELEASE_URL", (
        collectors.MetricSpec("lpr", "lpr_1y", "PBOC_LPR_1Y", "pct", "monthly", MONTHLY_AGE, MONTHLY_FETCH),
        collectors.MetricSpec("lpr", "lpr_5y", "PBOC_LPR_5Y", "pct", "monthly", MONTHLY_AGE, MONTHLY_FETCH),
    )),
    ("pboc_money_supply", "PBOC_MONEY_SUPPLY_RELEASE_URL", (
        collectors.MetricSpec("money_supply", "m2_yoy", "PBOC_M2_YOY", "pct_yoy", "monthly", MONTHLY_AGE, MONTHLY_FETCH),
    )),
    ("pboc_tsf", "PBOC_TSF_RELEASE_URL", (
        collectors.MetricSpec("aggregate_financing", "aggregate_financing_increment", "PBOC_TSF_INCREMENT", "100m_cny", "monthly", MONTHLY_AGE, MONTHLY_FETCH),
    )),
    ("pboc_new_loans", "PBOC_NEW_LOANS_RELEASE_URL", (
        collectors.MetricSpec("new_loans", "new_rmb_loans", "PBOC_NEW_RMB_LOANS", "100m_cny", "monthly", MONTHLY_AGE, MONTHLY_FETCH),
    )),
)

ISM_SPECS = (
    ("ism_manufacturing", "ISM_MANUFACTURING_RELEASE_URL", collectors.MetricSpec("manufacturing_pmi", "manufacturing_pmi", "ISM_MANUFACTURING_PMI", "index_points", "monthly", MONTHLY_AGE, MONTHLY_FETCH)),
    ("ism_services", "ISM_SERVICES_RELEASE_URL", collectors.MetricSpec("services_pmi", "services_pmi", "ISM_SERVICES_PMI", "index_points", "monthly", MONTHLY_AGE, MONTHLY_FETCH)),
)


def release_plan() -> tuple[collectors.RequestSpec, ...]:
    specs: list[collectors.RequestSpec] = []
    for request_id, env_name, metric in NBS_METRICS:
        specs.append(
            collectors.RequestSpec(
                request_id,
                "china_nbs",
                (metric,),
                _release_builder(env_name, ("www.stats.gov.cn", "stats.gov.cn", "data.stats.gov.cn")),
                _nbs_parser,
            )
        )
    for request_id, env_name, metrics in PBOC_SPECS:
        specs.append(
            collectors.RequestSpec(
                request_id,
                "pboc",
                metrics,
                _release_builder(env_name, ("www.pbc.gov.cn", "pbc.gov.cn")),
                _pboc_parser,
            )
        )
    for request_id, env_name, metric in ISM_SPECS:
        specs.append(
            collectors.RequestSpec(
                request_id,
                "ism_official_release",
                (metric,),
                _release_builder(
                    env_name,
                    ("www.ismworld.org", "ismworld.org"),
                    permission_env="ISM_CONTENT_PERMISSION_CONFIRMED",
                ),
                _ism_parser,
            )
        )
    return tuple(specs)


def _selected_specs(
    source_ids: list[str], request_ids: list[str]
) -> tuple[collectors.RequestSpec, ...]:
    plan = release_plan()
    unknown_sources = sorted(set(source_ids) - {row.source_id for row in plan})
    if unknown_sources:
        raise collectors.CollectionError(
            "DATA_INVALID",
            "UNKNOWN_COLLECTOR",
            f"unknown release collector source: {unknown_sources}",
        )
    unknown_requests = sorted(set(request_ids) - {row.request_id for row in plan})
    if unknown_requests:
        raise collectors.CollectionError(
            "DATA_INVALID",
            "UNKNOWN_REQUEST",
            f"unknown release collector request: {unknown_requests}",
        )
    selected = plan
    if source_ids:
        selected = tuple(row for row in selected if row.source_id in set(source_ids))
    if request_ids:
        selected = tuple(row for row in selected if row.request_id in set(request_ids))
    if not selected:
        raise collectors.CollectionError(
            "DATA_INVALID", "EMPTY_SELECTION", "source/request filters select no release adapter"
        )
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--health-out", default=str(DEFAULT_HEALTH))
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--request", action="append", default=[])
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)
    try:
        fixed_now = collectors._parse_iso(args.now) if args.now else None
        clock = fixed_now or datetime.now(timezone.utc)
        run_id = args.run_id or "macro_release_" + clock.strftime("%Y%m%d_%H%M%S")
        specs = _selected_specs(args.source, args.request)
        store = MacroHistoryStore(args.db)
        store.initialize()
        results = collectors.collect(
            store=store,
            transport=collectors.UrllibTransport(),
            specs=specs,
            run_id=run_id,
            now=fixed_now,
        )
        health = collectors.build_health(store=store, specs=specs, now=clock)
        collectors.write_health(args.health_out, health)
        problems = store.verify_integrity()
        if problems:
            raise MacroStoreError("; ".join(problems))
        for row in results:
            print(f"macro_m0b2: {row['request_id']} status={row['status']} rows={row['rows']}")
        return 0 if health["report"] == "COMPLETE" else 2
    except (collectors.CollectionError, MacroStoreError, contracts.ContractError, ValueError) as exc:
        print(f"macro_m0b2: REFUSED {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
