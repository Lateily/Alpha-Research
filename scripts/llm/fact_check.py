#!/usr/bin/env python3
"""Deterministic post-generation fact tracing for research thesis JSON.

This module does not decide whether a claim is economically correct. It only
checks whether numeric, dated, or event-like thesis statements can be traced
to the supplied field-level context or committed source evidence.

The checker is deliberately conservative:

* exact source value -> TRACED;
* same metric found with another value -> MISMATCH (visible, non-blocking);
* no source value -> UNTRACED;
* an UNTRACED monetary/order/contract/capacity claim blocks the whole output
  pending human review.

No network access and no model call are used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


SCHEMA_VERSION = "fact-check.v1"
PASS = "PASS"
BLOCKED = "BLOCKED_PENDING_HUMAN"
TRACED = "TRACED"
MISMATCH = "MISMATCH"
UNTRACED = "UNTRACED"

BLOCKING_ENTITY_CLASSES = frozenset(
    {"MONETARY", "ORDER", "CONTRACT", "CAPACITY"}
)

_SKIP_PATH_PARTS = frozenset(
    {
        "_fact_check",
        "_quality",
        "qc_checklist",
        "qcChecklistResults",
        "ticker",
        "ts_code",
        "name",
        "en",
        "sector",
    }
)

_METRIC_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("order_book", ("order book", "backlog", "在手订单", "订单")),
    ("gross_margin", ("gross margin", "gross_margin", "gm", "毛利率", "毛利")),
    ("contract_amount", ("contract amount", "contract value", "合同金额", "合同额", "合同")),
    ("capacity", ("capacity", "wfr/month", "wafer/month", "产能", "产量")),
    ("revenue", ("total_revenue", "revenue", "sales", "营收", "收入")),
    ("net_profit", ("net_profit", "net income", "归母", "净利润", "净利")),
    ("eps", ("diluted_eps", "basic_eps", "eps", "每股收益")),
    ("operating_cash_flow", ("operating cash flow", "ocf", "经营现金流")),
    ("market_cap", ("market cap", "market_cap", "mktcap", "市值")),
    ("price", ("target price", "live_price", "current price", "price", "股价", "目标价")),
    ("ratio", ("book-to-bill", "reward_to_risk", "reward to risk", "ratio", "比例", "占比")),
)

_EVENT_WORDS = re.compile(
    r"(?:earnings|report|announcement|tender|award|launch|approval|guidance|"
    r"业绩|财报|公告|招标|中标|发布|获批|指引|扩产|投产)",
    re.IGNORECASE,
)

_DATE_RE = re.compile(
    r"(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|20\d{6}|FY20\d{2}|FY\d{2}|"
    r"20\d{2}[HQ]\d|\d{2}[HQ]\d|[HQ]\d\s*20\d{2}|20\d{2})",
    re.IGNORECASE,
)

_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_.])"
    r"(?P<currency>RMB|CNY|USD|HKD|¥|￥|\$)?\s*"
    r"(?P<comparator>[<>≤≥~≈]?)\s*"
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|pp|bps|[Bb](?:n|illion)?|[Mm](?:n|illion)?|亿|万元|万|x|×)?"
    # A sentence-ending period is a valid boundary.  Keep unit tokens in the
    # boundary guard so the optional group cannot backtrack and silently drop
    # "%"/"B"/"亿" while still accepting the shorter numeric prefix.
    r"(?![A-Za-z0-9_]|%|pp|bps|亿|万元|万|x|×|\.\d)",
    re.IGNORECASE,
)

_CLAUSE_SPLIT_RE = re.compile(r"(?:\r?\n|[;；。！？!?]+)")
_TICKER_RE = re.compile(r"^(?:\d{6}\.(?:SZ|SH|BJ)|\d{1,5}\.HK)$")


@dataclass(frozen=True)
class Observation:
    raw: str
    metric: str
    normalized: float | str | None
    unit: str
    entity_class: str
    periods: tuple[str, ...]


@dataclass(frozen=True)
class SourceFact:
    observation: Observation
    source_path: str
    source_tier: str
    source_label: str
    source_excerpt: str


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _path_text(path: Sequence[str]) -> str:
    return " ".join(str(part).replace("_", " ") for part in path).lower()


def _metric_for(text: str, path: Sequence[str], start: int) -> str:
    lowered = text.lower()
    window = lowered[max(0, start - 80) : start + 40]
    path_hint = _path_text(path)
    best: tuple[int, int, str] | None = None
    for rank, (metric, aliases) in enumerate(_METRIC_ALIASES):
        for alias in aliases:
            pos = window.rfind(alias.lower())
            if pos >= 0:
                distance = len(window) - pos
                candidate = (distance, rank, metric)
                if best is None or candidate < best:
                    best = candidate
            elif alias.lower() in path_hint:
                candidate = (100, rank, metric)
                if best is None or candidate < best:
                    best = candidate
    return best[2] if best else "unclassified"


def _periods(text: str) -> tuple[str, ...]:
    out: set[str] = set()
    for match in _DATE_RE.finditer(text):
        raw = re.sub(r"[\s/]", "", match.group(0).upper())
        if re.fullmatch(r"20\d{2}-\d{1,2}-\d{1,2}", raw):
            out.add(raw.replace("-", ""))
        elif re.fullmatch(r"20\d{6}", raw):
            out.add(raw)
        elif raw.startswith("FY20"):
            out.add(raw[2:6])
        elif re.fullmatch(r"FY\d{2}", raw):
            out.add("20" + raw[2:])
        elif re.fullmatch(r"\d{2}[HQ]\d", raw):
            out.add("20" + raw)
        elif re.fullmatch(r"[HQ]\d20\d{2}", raw):
            out.add(raw[2:] + raw[:2])
        else:
            out.add(raw)
    return tuple(sorted(out))


def _normalize_number(
    value: float,
    unit: str,
    currency: str,
    metric: str,
) -> tuple[float, str, str]:
    lowered = unit.lower()
    if unit == "%":
        return value, "percent", "RATIO"
    if lowered == "pp":
        return value, "percentage_point", "RATIO"
    if lowered == "bps":
        return value, "basis_point", "RATIO"
    if lowered in {"x", "×"}:
        return value, "multiple", "RATIO"

    multiplier = 1.0
    if lowered in {"b", "bn", "billion"}:
        multiplier = 1_000_000_000.0
    elif lowered in {"m", "mn", "million"}:
        multiplier = 1_000_000.0
    elif unit == "亿":
        multiplier = 100_000_000.0
    elif unit in {"万", "万元"}:
        multiplier = 10_000.0

    money_metric = metric in {
        "order_book",
        "contract_amount",
        "revenue",
        "net_profit",
        "operating_cash_flow",
        "market_cap",
        "price",
    }
    if currency or multiplier != 1.0 or money_metric:
        return value * multiplier, "money", "MONETARY"

    if metric == "gross_margin":
        return (value * 100.0 if abs(value) <= 1.0 else value), "percent", "RATIO"
    return value, "number", "OTHER"


def _entity_class(metric: str, base_class: str) -> str:
    if metric == "order_book":
        return "ORDER"
    if metric == "contract_amount":
        return "CONTRACT"
    if metric == "capacity":
        return "CAPACITY"
    return base_class


def extract_observations(text: str, path: Sequence[str] = ()) -> list[Observation]:
    observations: list[Observation] = []
    periods = _periods(text)
    date_spans = [match.span() for match in _DATE_RE.finditer(text)]

    for match in _NUMBER_RE.finditer(text):
        if any(start <= match.start() < end for start, end in date_spans):
            continue
        raw = match.group(0).strip()
        metric = _metric_for(text, path, match.start())
        unit = match.group("unit") or ""
        currency = match.group("currency") or ""
        value = float(match.group("value"))
        normalized, normalized_unit, base_class = _normalize_number(
            value, unit, currency, metric
        )
        if not (unit or currency or metric != "unclassified"):
            continue
        observations.append(
            Observation(
                raw=raw,
                metric=metric,
                normalized=normalized,
                unit=normalized_unit,
                entity_class=_entity_class(metric, base_class),
                periods=periods,
            )
        )

    for match in _DATE_RE.finditer(text):
        observations.append(
            Observation(
                raw=match.group(0),
                metric="date",
                normalized=re.sub(r"[\s/-]", "", match.group(0).upper()),
                unit="date",
                entity_class="EVENT",
                periods=periods,
            )
        )

    if not observations and _EVENT_WORDS.search(text):
        observations.append(
            Observation(
                raw=_EVENT_WORDS.search(text).group(0),  # type: ignore[union-attr]
                metric="event",
                normalized=None,
                unit="event",
                entity_class="EVENT",
                periods=periods,
            )
        )
    return observations


def _walk_strings(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    if any(part in _SKIP_PATH_PARTS or part.startswith("_") for part in path):
        return
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, child in value.items():
            yield from _walk_strings(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_strings(child, path + (str(index),))


def _walk_source_leaves(
    value: Any,
    path: tuple[str, ...] = (),
) -> Iterator[tuple[tuple[str, ...], str]]:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, (int, float)) and math.isfinite(float(value)):
        yield path, str(value)
    elif isinstance(value, Mapping):
        for key, child in value.items():
            yield from _walk_source_leaves(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_source_leaves(child, path + (str(index),))


def _source_facts_from_payload(
    payload: Any,
    *,
    source_label: str,
    source_tier: str = "UNSPECIFIED",
    path_prefix: tuple[str, ...] = (),
) -> list[SourceFact]:
    facts: list[SourceFact] = []
    for path, raw_text in _walk_source_leaves(payload, path_prefix):
        clauses = [part.strip() for part in _CLAUSE_SPLIT_RE.split(raw_text) if part.strip()]
        for clause in clauses or [raw_text]:
            for observation in extract_observations(clause, path):
                facts.append(
                    SourceFact(
                        observation=observation,
                        source_path=".".join(path),
                        source_tier=source_tier,
                        source_label=source_label,
                        source_excerpt=clause[:240],
                    )
                )
    return facts


def _decision_sheet_sources(path: Path, payload: Any) -> list[SourceFact]:
    evidence = payload.get("evidence", {}) if isinstance(payload, Mapping) else {}
    items = evidence.get("items", []) if isinstance(evidence, Mapping) else []
    facts: list[SourceFact] = []
    for index, item in enumerate(items if isinstance(items, list) else []):
        if not isinstance(item, Mapping) or not isinstance(item.get("claim"), str):
            continue
        source_label = str(item.get("source") or path.as_posix())
        tier = str(item.get("tier") or "UNSPECIFIED")
        facts.extend(
            _source_facts_from_payload(
                {"claim": item["claim"]},
                source_label=source_label,
                source_tier=tier,
                path_prefix=(path.as_posix(), "evidence", "items", str(index)),
            )
        )
    return facts


def load_repo_sources(repo_root: Path, ticker: str) -> list[SourceFact]:
    if not _TICKER_RE.fullmatch(ticker):
        raise ValueError(f"unsupported ticker shape: {ticker}")
    public_data = repo_root / "public" / "data"
    ticker_under = ticker.replace(".", "_")
    candidates: set[Path] = set()
    candidates.update(public_data.glob(f"*/{ticker}.json"))
    candidates.update(public_data.glob(f"*{ticker_under}*.json"))
    decision_sheet = public_data / "decision_sheets" / f"{ticker_under}.json"
    if decision_sheet.exists():
        candidates.add(decision_sheet)

    market_data = public_data / "market_data.json"
    facts: list[SourceFact] = []
    for path in sorted(candidates):
        if "api_generated" in path.parts:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        relative = path.relative_to(repo_root)
        if path == decision_sheet:
            facts.extend(_decision_sheet_sources(relative, payload))
        else:
            facts.extend(
                _source_facts_from_payload(
                    payload,
                    source_label=relative.as_posix(),
                    source_tier="LANDED",
                    path_prefix=(relative.as_posix(),),
                )
            )

    if market_data.exists():
        try:
            market_payload = json.loads(market_data.read_text(encoding="utf-8"))
            ticker_payload = market_payload.get("yahoo", {}).get(ticker)
        except (AttributeError, OSError, json.JSONDecodeError):
            ticker_payload = None
        if ticker_payload:
            facts.extend(
                _source_facts_from_payload(
                    ticker_payload,
                    source_label="public/data/market_data.json",
                    source_tier="LANDED",
                    path_prefix=("public/data/market_data.json", "yahoo", ticker),
                )
            )
    return _dedupe_source_facts(facts)


def _dedupe_source_facts(facts: Iterable[SourceFact]) -> list[SourceFact]:
    seen: set[tuple[Any, ...]] = set()
    output: list[SourceFact] = []
    for fact in facts:
        key = (
            fact.observation.metric,
            fact.observation.normalized,
            fact.observation.unit,
            fact.source_path,
            fact.source_label,
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(fact)
    return output


def _numeric_equal(left: float | str | None, right: float | str | None, unit: str) -> bool:
    if isinstance(left, str) or isinstance(right, str):
        return left == right
    if left is None or right is None:
        return False
    tolerance = 0.02 if unit in {"percent", "percentage_point", "number", "multiple"} else max(1.0, abs(left) * 0.0005)
    return abs(left - right) <= tolerance


def _candidate_facts(observation: Observation, facts: Sequence[SourceFact]) -> list[SourceFact]:
    if observation.metric == "unclassified":
        return [fact for fact in facts if fact.observation.unit == observation.unit]
    return [fact for fact in facts if fact.observation.metric == observation.metric]


def _best_fact(observation: Observation, facts: Sequence[SourceFact]) -> SourceFact:
    def rank(fact: SourceFact) -> tuple[int, float, str]:
        overlap = bool(set(observation.periods) & set(fact.observation.periods))
        left = observation.normalized
        right = fact.observation.normalized
        distance = abs(float(left) - float(right)) if isinstance(left, (int, float)) and isinstance(right, (int, float)) else float("inf")
        return (0 if overlap else 1, distance, fact.source_path)

    return sorted(facts, key=rank)[0]


def _fact_ref(fact: SourceFact) -> dict[str, Any]:
    return {
        "source_path": fact.source_path,
        "source_tier": fact.source_tier,
        "source": fact.source_label,
        "raw": fact.observation.raw,
        "normalized": fact.observation.normalized,
    }


def _check_observation(observation: Observation, facts: Sequence[SourceFact]) -> dict[str, Any]:
    candidates = _candidate_facts(observation, facts)
    exact = [
        fact
        for fact in candidates
        if fact.observation.unit == observation.unit
        and _numeric_equal(observation.normalized, fact.observation.normalized, observation.unit)
    ]
    result: dict[str, Any] = {
        "raw": observation.raw,
        "metric": observation.metric,
        "normalized": observation.normalized,
        "unit": observation.unit,
        "entity_class": observation.entity_class,
    }
    if observation.metric == "event":
        event_matches = [
            fact
            for fact in facts
            if fact.observation.metric == "event"
            and str(observation.raw).lower() == str(fact.observation.raw).lower()
        ]
        if event_matches:
            result.update({"state": TRACED, "source": _fact_ref(event_matches[0])})
        else:
            result["state"] = UNTRACED
        return result
    if exact:
        result.update({"state": TRACED, "source": _fact_ref(_best_fact(observation, exact))})
    elif candidates and observation.metric not in {"unclassified", "date"}:
        selected = _best_fact(observation, candidates)
        result.update({"state": MISMATCH, "source": _fact_ref(selected)})
    else:
        result["state"] = UNTRACED
    return result


def fact_check(
    thesis: Mapping[str, Any],
    *,
    ticker: str = "",
    source_payloads: Sequence[tuple[Any, str, str]] = (),
    source_facts: Sequence[SourceFact] = (),
) -> dict[str, Any]:
    facts = list(source_facts)
    for payload, label, tier in source_payloads:
        facts.extend(
            _source_facts_from_payload(
                payload,
                source_label=label,
                source_tier=tier,
                path_prefix=(label,),
            )
        )
    facts = _dedupe_source_facts(facts)

    claims: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    untraced: list[dict[str, Any]] = []
    fabrication_suspects: list[dict[str, Any]] = []

    for path, text in _walk_strings(thesis):
        for clause in (part.strip() for part in _CLAUSE_SPLIT_RE.split(text)):
            if not clause:
                continue
            observations = extract_observations(clause, path)
            if not observations:
                continue
            checked = [_check_observation(item, facts) for item in observations]
            states = {item["state"] for item in checked}
            state = UNTRACED if UNTRACED in states else MISMATCH if MISMATCH in states else TRACED
            claim = {
                "path": ".".join(path),
                "excerpt": clause[:300],
                "state": state,
                "observations": checked,
            }
            claims.append(claim)
            for item in checked:
                row = {
                    "path": claim["path"],
                    "excerpt": claim["excerpt"],
                    **item,
                }
                if item["state"] == MISMATCH:
                    mismatches.append(row)
                elif item["state"] == UNTRACED:
                    untraced.append(row)
                    if item["entity_class"] in BLOCKING_ENTITY_CLASSES:
                        fabrication_suspects.append(row)

    # governance-mutation: FACT_CHECK_BLOCKS_UNTRACED_MONETARY_CLAIMS
    status = BLOCKED if fabrication_suspects else PASS
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "ticker": ticker,
        "input_hash": _canonical_hash(thesis),
        "summary": {
            "claims": len(claims),
            "traced": sum(item["state"] == TRACED for item in claims),
            "mismatches": len(mismatches),
            "untraced": len(untraced),
            "fabrication_suspects": len(fabrication_suspects),
            "source_facts": len(facts),
        },
        "claims": claims,
        "mismatches": mismatches,
        "untraced": untraced,
        "fabrication_suspects": fabrication_suspects,
    }


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="thesis JSON or API response")
    parser.add_argument("--output", type=Path, help="write deterministic receipt here")
    parser.add_argument("--extras", action="append", default=[], type=Path, help="additional field-level source JSON")
    parser.add_argument("--source", action="append", default=[], type=Path, help="additional source JSON")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--no-repo-sources", action="store_true")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    payload = _load_json(args.input)
    if not isinstance(payload, Mapping):
        raise ValueError("input JSON root must be an object")
    thesis = payload.get("data", payload)
    if not isinstance(thesis, Mapping):
        raise ValueError("thesis payload must be an object")
    ticker = str(payload.get("ticker") or thesis.get("ticker") or "")

    source_payloads: list[tuple[Any, str, str]] = []
    for path in [*args.extras, *args.source]:
        source_payloads.append((_load_json(path), path.as_posix(), "SUPPLIED"))
    facts = [] if args.no_repo_sources or not ticker else load_repo_sources(args.repo_root, ticker)
    receipt = fact_check(
        thesis,
        ticker=ticker,
        source_payloads=source_payloads,
        source_facts=facts,
    )
    rendered = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
