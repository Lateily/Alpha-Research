#!/usr/bin/env python3
"""Active risk-monitor engine for the systematic strategy.

This module implements docs/strategy/SYSTEMATIC_STRATEGY_v0.md section 6:
eleven independent monitors composed into a deterministic risk action list.

All numeric defaults in CONFIG are the section 6 starting points or explicit
v1 placeholders where the spec leaves a bracketed parameter open. They are
[unvalidated intuition] until calibrated by the 20-year PIT backtest. The
causal logic is valid because each monitor maps an observable risk state to an
auditable action; the specific numbers are not validated against trade data.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Optional


DEFAULT_TS = "1970-01-01T00:00:00Z"

ACTION_EXIT = "EXIT"
ACTION_TRIM = "TRIM"
ACTION_BLOCK_ADD = "BLOCK_ADD"
ACTION_SCALE_DOWN_GROSS = "SCALE_DOWN_GROSS"
ACTION_TO_CASH = "TO_CASH"
ACTION_FREEZE = "FREEZE"
ACTION_FLAG = "FLAG"


CONFIG: dict[str, Any] = {
    "now": DEFAULT_TS,
    "atr_stop_mult": 2.5,
    "time_stop_core_days": 60,
    "time_stop_satellite_days": 10,
    "time_stop_flat_pnl_pct": 0.02,
    "per_name_cap": 0.10,
    "sector_cap": 0.30,
    "top5_cap": 0.50,
    "correlation_rho_threshold": 0.75,
    "correlation_cluster_gross_cap": 0.40,
    "vol_target": 0.20,
    "vol_target_band": 0.05,
    "drawdown_scale_down": -0.12,
    "drawdown_to_cash": -0.20,
    "regime_breadth_threshold": 0.40,
    "regime_gross_cap": 0.40,
    "liquidity_adv_multiple": 5.0,
    "max_feed_age_days": 1.0,
}


@dataclass(frozen=True)
class RiskAction:
    monitor: str
    ticker: str
    trigger_value: Any
    threshold: Any
    action: str
    severity: int
    why: str
    ts: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _merge_config(config: Optional[dict[str, Any]], now: Optional[str] = None) -> dict[str, Any]:
    merged = dict(CONFIG)
    if config:
        thresholds = config.get("thresholds")
        if isinstance(thresholds, dict):
            merged.update(thresholds)
        for key, value in config.items():
            if key != "thresholds":
                merged[key] = value
    if now is not None:
        merged["now"] = now
    merged.setdefault("now", DEFAULT_TS)
    return merged


def _ts(config: dict[str, Any]) -> str:
    return str(config.get("now") or DEFAULT_TS)


def _float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fraction(value: Any) -> Optional[float]:
    number = _float(value)
    if number is None:
        return None
    if abs(number) > 1.0:
        return number / 100.0
    return number


def _clean(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _positions(portfolio_state: dict[str, Any]) -> list[dict[str, Any]]:
    positions = portfolio_state.get("positions") or []
    return positions if isinstance(positions, list) else []


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _make_action(
    config: dict[str, Any],
    monitor: str,
    ticker: str,
    trigger_value: Any,
    threshold: Any,
    action: str,
    severity: int,
    why: str,
) -> RiskAction:
    return RiskAction(
        monitor=monitor,
        ticker=ticker,
        trigger_value=_clean(trigger_value),
        threshold=_clean(threshold),
        action=action,
        severity=severity,
        why=why,
        ts=_ts(config),
    )


def monitor_position_stop(
    portfolio_state: dict[str, Any],
    market_state: dict[str, Any],
    config: dict[str, Any],
) -> list[RiskAction]:
    config = _merge_config(config)
    del market_state
    actions: list[RiskAction] = []
    mult = float(config["atr_stop_mult"])
    for pos in _positions(portfolio_state):
        ticker = str(pos.get("ticker") or "UNKNOWN")
        entry = _float(pos.get("entry_price"))
        last = _float(pos.get("last_price"))
        atr = _float(pos.get("atr"))
        if entry is None or last is None or atr is None or entry <= 0 or atr < 0:
            continue
        atr_stop = entry - mult * atr
        wrongif = _float(pos.get("thesis_wrongif_price"))
        stop = atr_stop
        source = f"ATR stop {atr_stop:.4f}"
        if wrongif is not None:
            stop = max(stop, wrongif)
            source = f"tighter of ATR stop {atr_stop:.4f} and thesis wrongIf {wrongif:.4f}"
        if last <= stop:
            actions.append(
                _make_action(
                    config,
                    "position_stop",
                    ticker,
                    last,
                    stop,
                    ACTION_EXIT,
                    4,
                    f"last price {last:.4f} <= {source}; exit to enforce per-name risk stop",
                )
            )
    return actions


def monitor_time_stop(
    portfolio_state: dict[str, Any],
    market_state: dict[str, Any],
    config: dict[str, Any],
) -> list[RiskAction]:
    config = _merge_config(config)
    del market_state
    actions: list[RiskAction] = []
    flat_band = float(config["time_stop_flat_pnl_pct"])
    for pos in _positions(portfolio_state):
        ticker = str(pos.get("ticker") or "UNKNOWN")
        days_held = _float(pos.get("days_held"))
        if days_held is None:
            continue
        track = str(pos.get("track") or "satellite").strip().lower()
        is_core = track == "core"
        threshold = (
            float(config["time_stop_core_days"])
            if is_core
            else float(config["time_stop_satellite_days"])
        )
        thesis_triggered = _is_truthy(pos.get("thesis_triggered")) or _is_truthy(
            pos.get("catalyst_triggered")
        )
        entry = _float(pos.get("entry_price"))
        last = _float(pos.get("last_price"))
        pnl_pct = _fraction(pos.get("pnl_pct"))
        if pnl_pct is None and entry is not None and last is not None and entry > 0:
            pnl_pct = last / entry - 1.0
        flat_or_worse = pnl_pct is None or pnl_pct <= flat_band
        if days_held >= threshold and not thesis_triggered and flat_or_worse:
            action = ACTION_TRIM if is_core else ACTION_EXIT
            actions.append(
                _make_action(
                    config,
                    "time_stop",
                    ticker,
                    {"days_held": days_held, "pnl_pct": pnl_pct},
                    {"max_days": threshold, "flat_pnl_pct": flat_band},
                    action,
                    3,
                    f"{track} position held {int(days_held)}d without thesis trigger and P&L did not clear flat band",
                )
            )
    return actions


def monitor_per_name_cap(
    portfolio_state: dict[str, Any],
    market_state: dict[str, Any],
    config: dict[str, Any],
) -> list[RiskAction]:
    config = _merge_config(config)
    del market_state
    actions: list[RiskAction] = []
    cap = float(config["per_name_cap"])
    for pos in _positions(portfolio_state):
        ticker = str(pos.get("ticker") or "UNKNOWN")
        weight = _fraction(pos.get("weight"))
        if weight is not None and abs(weight) > cap:
            actions.append(
                _make_action(
                    config,
                    "per_name_cap",
                    ticker,
                    abs(weight),
                    cap,
                    ACTION_TRIM,
                    3,
                    f"position weight {abs(weight):.2%} exceeds per-name cap {cap:.2%}; trim back to cap",
                )
            )
    return actions


def monitor_sector_cap(
    portfolio_state: dict[str, Any],
    market_state: dict[str, Any],
    config: dict[str, Any],
) -> list[RiskAction]:
    config = _merge_config(config)
    del market_state
    exposure: dict[str, float] = {}
    for pos in _positions(portfolio_state):
        sector = str(pos.get("sector") or "UNKNOWN")
        weight = _fraction(pos.get("weight"))
        if weight is not None:
            exposure[sector] = exposure.get(sector, 0.0) + abs(weight)

    actions: list[RiskAction] = []
    cap = float(config["sector_cap"])
    for sector in sorted(exposure):
        weight = exposure[sector]
        if weight > cap:
            ticker = f"SECTOR:{sector}"
            actions.append(
                _make_action(
                    config,
                    "sector_cap",
                    ticker,
                    weight,
                    cap,
                    ACTION_BLOCK_ADD,
                    3,
                    f"{sector} exposure {weight:.2%} exceeds sector cap {cap:.2%}; block additional buys",
                )
            )
            actions.append(
                _make_action(
                    config,
                    "sector_cap",
                    ticker,
                    weight,
                    cap,
                    ACTION_TRIM,
                    3,
                    f"{sector} exposure {weight:.2%} exceeds sector cap {cap:.2%}; trim sector exposure toward cap",
                )
            )
    return actions


def monitor_concentration(
    portfolio_state: dict[str, Any],
    market_state: dict[str, Any],
    config: dict[str, Any],
) -> list[RiskAction]:
    config = _merge_config(config)
    del market_state
    weights = []
    for pos in _positions(portfolio_state):
        weight = _fraction(pos.get("weight"))
        if weight is not None:
            weights.append(abs(weight))
    top5 = sum(sorted(weights, reverse=True)[:5])
    cap = float(config["top5_cap"])
    if top5 > cap:
        return [
            _make_action(
                config,
                "concentration",
                "PORTFOLIO",
                top5,
                cap,
                ACTION_BLOCK_ADD,
                3,
                f"top-5 concentration {top5:.2%} exceeds cap {cap:.2%}; block adds until diversified",
            )
        ]
    return []


def _lookup_corr(corr: Any, a: str, b: str) -> Optional[float]:
    if not isinstance(corr, dict):
        return None
    direct = corr.get(a)
    if isinstance(direct, dict) and b in direct:
        return _float(direct.get(b))
    reverse = corr.get(b)
    if isinstance(reverse, dict) and a in reverse:
        return _float(reverse.get(a))
    for key in (f"{a}|{b}", f"{b}|{a}", f"{a},{b}", f"{b},{a}", f"{a}:{b}", f"{b}:{a}"):
        if key in corr:
            return _float(corr.get(key))
    return None


def _components(nodes: Iterable[str], edges: dict[str, set[str]]) -> list[list[str]]:
    seen: set[str] = set()
    clusters: list[list[str]] = []
    for node in sorted(nodes):
        if node in seen:
            continue
        stack = [node]
        cluster: list[str] = []
        seen.add(node)
        while stack:
            cur = stack.pop()
            cluster.append(cur)
            for nxt in sorted(edges.get(cur, set())):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        clusters.append(sorted(cluster))
    return clusters


def monitor_correlation(
    portfolio_state: dict[str, Any],
    market_state: dict[str, Any],
    config: dict[str, Any],
) -> list[RiskAction]:
    config = _merge_config(config)
    positions = _positions(portfolio_state)
    tickers = [str(p.get("ticker")) for p in positions if p.get("ticker")]
    weights = {str(p.get("ticker")): (_fraction(p.get("weight")) or 0.0) for p in positions if p.get("ticker")}
    corr = portfolio_state.get("correlations") or market_state.get("correlations")
    if not tickers or not corr:
        return []

    rho_threshold = float(config["correlation_rho_threshold"])
    gross_cap = float(config["correlation_cluster_gross_cap"])
    edges: dict[str, set[str]] = {t: set() for t in tickers}
    max_rho_by_pair: dict[tuple[str, str], float] = {}
    for idx, a in enumerate(tickers):
        for b in tickers[idx + 1 :]:
            rho = _lookup_corr(corr, a, b)
            if rho is None:
                continue
            if abs(rho) >= rho_threshold:
                edges[a].add(b)
                edges[b].add(a)
                max_rho_by_pair[(a, b)] = abs(rho)

    actions: list[RiskAction] = []
    for cluster in _components(tickers, edges):
        if len(cluster) < 2:
            continue
        gross = sum(abs(weights.get(t, 0.0)) for t in cluster)
        if gross <= gross_cap:
            continue
        cluster_rhos = [
            rho
            for pair, rho in max_rho_by_pair.items()
            if pair[0] in cluster and pair[1] in cluster
        ]
        max_rho = max(cluster_rhos) if cluster_rhos else None
        actions.append(
            _make_action(
                config,
                "correlation",
                "CLUSTER:" + ",".join(cluster),
                {"gross": gross, "max_abs_rho": max_rho},
                {"cluster_gross_cap": gross_cap, "rho_threshold": rho_threshold},
                ACTION_BLOCK_ADD,
                3,
                f"correlated cluster gross {gross:.2%} exceeds cap {gross_cap:.2%}; block correlated adds",
            )
        )
    return actions


def monitor_vol_target(
    portfolio_state: dict[str, Any],
    market_state: dict[str, Any],
    config: dict[str, Any],
) -> list[RiskAction]:
    config = _merge_config(config)
    del portfolio_state
    realized_vol = _fraction(market_state.get("realized_vol"))
    if realized_vol is None:
        return []
    target = float(config["vol_target"])
    band = float(config["vol_target_band"])
    threshold = target + band
    if realized_vol > threshold:
        return [
            _make_action(
                config,
                "vol_target",
                "PORTFOLIO",
                realized_vol,
                {"target": target, "band": band, "trigger": threshold},
                ACTION_SCALE_DOWN_GROSS,
                4,
                f"realized vol {realized_vol:.2%} exceeds target band {threshold:.2%}; scale gross down",
            )
        ]
    return []


def monitor_drawdown_breaker(
    portfolio_state: dict[str, Any],
    market_state: dict[str, Any],
    config: dict[str, Any],
) -> list[RiskAction]:
    config = _merge_config(config)
    del market_state
    nav = _float(portfolio_state.get("nav"))
    peak_nav = _float(portfolio_state.get("peak_nav"))
    if nav is None or peak_nav is None or peak_nav <= 0:
        return []
    drawdown = nav / peak_nav - 1.0
    to_cash = float(config["drawdown_to_cash"])
    scale_down = float(config["drawdown_scale_down"])
    if drawdown <= to_cash:
        return [
            _make_action(
                config,
                "drawdown_breaker",
                "PORTFOLIO",
                drawdown,
                to_cash,
                ACTION_TO_CASH,
                5,
                f"NAV drawdown {drawdown:.2%} breached cash breaker {to_cash:.2%}; move book to cash",
            )
        ]
    if drawdown <= scale_down:
        return [
            _make_action(
                config,
                "drawdown_breaker",
                "PORTFOLIO",
                drawdown,
                scale_down,
                ACTION_SCALE_DOWN_GROSS,
                4,
                f"NAV drawdown {drawdown:.2%} breached de-risk trigger {scale_down:.2%}; cut gross roughly in half",
            )
        ]
    return []


def monitor_regime(
    portfolio_state: dict[str, Any],
    market_state: dict[str, Any],
    config: dict[str, Any],
) -> list[RiskAction]:
    config = _merge_config(config)
    del portfolio_state
    last = _float(market_state.get("csi300_last"))
    ma200 = _float(market_state.get("csi300_ma200"))
    breadth = _fraction(market_state.get("breadth_pct"))
    breadth_threshold = float(config["regime_breadth_threshold"])
    gross_cap = float(config["regime_gross_cap"])

    downtrend = last is not None and ma200 is not None and last < ma200
    weak_breadth = breadth is not None and breadth < breadth_threshold
    if not downtrend and not weak_breadth:
        return []

    reasons = []
    if downtrend:
        reasons.append(f"CSI300 {last:.4f} < MA200 {ma200:.4f}")
    if weak_breadth:
        reasons.append(f"breadth {breadth:.2%} < threshold {breadth_threshold:.2%}")
    return [
        _make_action(
            config,
            "regime",
            "PORTFOLIO",
            {"csi300_last": last, "csi300_ma200": ma200, "breadth_pct": breadth},
            {
                "csi300_above_ma200": True,
                "breadth_min": breadth_threshold,
                "gross_cap": gross_cap,
            },
            ACTION_SCALE_DOWN_GROSS,
            4,
            "; ".join(reasons) + f"; cap gross at {gross_cap:.2%} and tighten entries",
        )
    ]


def monitor_liquidity(
    portfolio_state: dict[str, Any],
    market_state: dict[str, Any],
    config: dict[str, Any],
) -> list[RiskAction]:
    config = _merge_config(config)
    del market_state
    nav = _float(portfolio_state.get("nav"))
    if nav is None or nav <= 0:
        return []
    multiple = float(config["liquidity_adv_multiple"])
    actions: list[RiskAction] = []
    for pos in _positions(portfolio_state):
        ticker = str(pos.get("ticker") or "UNKNOWN")
        weight = _fraction(pos.get("weight"))
        if weight is None:
            continue
        adv = _float(pos.get("adv"))
        position_value = nav * abs(weight)
        if adv is None or adv <= 0:
            actions.append(
                _make_action(
                    config,
                    "liquidity",
                    ticker,
                    "missing_adv",
                    "adv_required",
                    ACTION_FLAG,
                    2,
                    "ADV missing or non-positive; cannot estimate exit liquidity",
                )
            )
            continue
        days_to_exit = position_value / adv
        if days_to_exit > multiple:
            actions.append(
                _make_action(
                    config,
                    "liquidity",
                    ticker,
                    days_to_exit,
                    multiple,
                    ACTION_TRIM,
                    3,
                    f"position is {days_to_exit:.2f}x ADV, above liquidity cap {multiple:.2f}x; trim exit risk",
                )
            )
    return actions


def monitor_data_staleness(
    portfolio_state: dict[str, Any],
    market_state: dict[str, Any],
    config: dict[str, Any],
) -> list[RiskAction]:
    config = _merge_config(config)
    del portfolio_state
    max_age = float(config["max_feed_age_days"])
    age = _float(market_state.get("feed_age_days"))
    if age is None:
        return [
            _make_action(
                config,
                "data_staleness",
                "PORTFOLIO",
                "missing_feed_age_days",
                max_age,
                ACTION_FREEZE,
                5,
                "feed age is missing; freeze risk actions until data freshness is known",
            )
        ]
    if age > max_age:
        return [
            _make_action(
                config,
                "data_staleness",
                "PORTFOLIO",
                age,
                max_age,
                ACTION_FREEZE,
                5,
                f"market feed age {age:.2f}d exceeds max {max_age:.2f}d; freeze actions and alert",
            )
        ]
    return []


MONITORS = [
    monitor_position_stop,
    monitor_time_stop,
    monitor_per_name_cap,
    monitor_sector_cap,
    monitor_concentration,
    monitor_correlation,
    monitor_vol_target,
    monitor_drawdown_breaker,
    monitor_regime,
    monitor_liquidity,
    monitor_data_staleness,
]


def resolve_conflicts(actions: list[RiskAction]) -> list[RiskAction]:
    """Resolve mutually exclusive actions while keeping auditability.

    FREEZE overrides all trading actions because stale data makes the action set
    untrusted. TO_CASH overrides lower-severity trims and add-blocks. Per-name
    EXIT overrides a same-ticker TRIM.
    """
    if not actions:
        return []

    freezes = [a for a in actions if a.action == ACTION_FREEZE]
    if freezes:
        return _dedupe_sorted(freezes)

    cashouts = [a for a in actions if a.action == ACTION_TO_CASH]
    if cashouts:
        return _dedupe_sorted(cashouts)

    exit_tickers = {a.ticker for a in actions if a.action == ACTION_EXIT}
    filtered = [
        a
        for a in actions
        if not (a.action == ACTION_TRIM and a.ticker in exit_tickers)
    ]
    return _dedupe_sorted(filtered)


def _dedupe_sorted(actions: list[RiskAction]) -> list[RiskAction]:
    unique: dict[str, RiskAction] = {}
    for action in actions:
        key = json.dumps(action.to_dict(), sort_keys=True, ensure_ascii=True)
        unique[key] = action
    return sorted(
        unique.values(),
        key=lambda a: (-a.severity, a.monitor, a.ticker, a.action, json.dumps(a.trigger_value, sort_keys=True)),
    )


def run_monitors(
    portfolio_state: dict[str, Any],
    market_state: dict[str, Any],
    config: Optional[dict[str, Any]] = None,
    *,
    now: Optional[str] = None,
    dry_run: bool = False,
    resolve: bool = True,
) -> list[RiskAction]:
    """Compose all monitors into a deterministic list of risk actions.

    dry_run is intentionally side-effect-free; it exists to make callers state
    that these are would-be actions for backtests or morning inspection.
    """
    del dry_run
    cfg = _merge_config(config, now=now)
    raw: list[RiskAction] = []
    for monitor in MONITORS:
        raw.extend(monitor(portfolio_state or {}, market_state or {}, cfg))
    if resolve:
        return resolve_conflicts(raw)
    return _dedupe_sorted(raw)


def to_audit_log(actions: Iterable[RiskAction]) -> list[dict[str, Any]]:
    return [action.to_dict() if isinstance(action, RiskAction) else dict(action) for action in actions]


def _base_market() -> dict[str, Any]:
    return {
        "csi300_last": 4100.0,
        "csi300_ma200": 3900.0,
        "breadth_pct": 0.55,
        "realized_vol": 0.12,
        "feed_age_days": 0,
    }


def _quiet_position(ticker: str = "AAA", weight: float = 0.05, sector: str = "Tech") -> dict[str, Any]:
    return {
        "ticker": ticker,
        "sector": sector,
        "weight": weight,
        "entry_price": 100.0,
        "last_price": 102.0,
        "atr": 4.0,
        "days_held": 2,
        "adv": 1_000_000_000.0,
    }


def _contains(actions: list[RiskAction], monitor: str, action: str, ticker: Optional[str] = None) -> bool:
    return any(
        a.monitor == monitor and a.action == action and (ticker is None or a.ticker == ticker)
        for a in actions
    )


def _selftest() -> tuple[int, str]:
    now = "2026-05-25T00:00:00Z"
    failures: list[str] = []

    pos_stop_portfolio = {
        "nav": 1_000_000,
        "peak_nav": 1_000_000,
        "gross_exposure": 0.05,
        "positions": [
            {
                "ticker": "STOP.SZ",
                "sector": "Tech",
                "weight": 0.05,
                "entry_price": 100.0,
                "last_price": 86.0,
                "atr": 5.0,
                "days_held": 2,
                "adv": 1_000_000_000.0,
            }
        ],
    }
    actions = run_monitors(pos_stop_portfolio, _base_market(), now=now)
    if not _contains(actions, "position_stop", ACTION_EXIT, "STOP.SZ"):
        failures.append("position_stop did not emit EXIT when price fell below entry - 2.5*ATR")

    dd13 = {"nav": 87.0, "peak_nav": 100.0, "gross_exposure": 0.80, "positions": []}
    actions = run_monitors(dd13, _base_market(), now=now)
    if not _contains(actions, "drawdown_breaker", ACTION_SCALE_DOWN_GROSS, "PORTFOLIO"):
        failures.append("drawdown -13% did not emit SCALE_DOWN_GROSS")

    dd21 = {"nav": 79.0, "peak_nav": 100.0, "gross_exposure": 0.80, "positions": []}
    actions = run_monitors(dd21, _base_market(), now=now)
    if not _contains(actions, "drawdown_breaker", ACTION_TO_CASH, "PORTFOLIO"):
        failures.append("drawdown -21% did not emit TO_CASH")

    sector_portfolio = {
        "nav": 1_000_000,
        "peak_nav": 1_000_000,
        "gross_exposure": 0.35,
        "positions": [
            _quiet_position("SEC1.SZ", 0.09, "AI"),
            _quiet_position("SEC2.SZ", 0.09, "AI"),
            _quiet_position("SEC3.SZ", 0.09, "AI"),
            _quiet_position("SEC4.SZ", 0.08, "AI"),
        ],
    }
    actions = run_monitors(sector_portfolio, _base_market(), now=now)
    if not _contains(actions, "sector_cap", ACTION_BLOCK_ADD, "SECTOR:AI"):
        failures.append("sector 35% did not emit BLOCK_ADD")
    if not _contains(actions, "sector_cap", ACTION_TRIM, "SECTOR:AI"):
        failures.append("sector 35% did not emit TRIM")

    regime_market = dict(_base_market())
    regime_market["csi300_last"] = 3500.0
    regime_market["csi300_ma200"] = 3900.0
    actions = run_monitors({"nav": 1_000_000, "peak_nav": 1_000_000, "positions": []}, regime_market, now=now)
    if not _contains(actions, "regime", ACTION_SCALE_DOWN_GROSS, "PORTFOLIO"):
        failures.append("CSI300 below MA200 did not emit regime SCALE_DOWN_GROSS")

    stale_market = dict(_base_market())
    stale_market["feed_age_days"] = 3
    actions = run_monitors({"nav": 1_000_000, "peak_nav": 1_000_000, "positions": []}, stale_market, now=now)
    if len(actions) != 1 or not _contains(actions, "data_staleness", ACTION_FREEZE, "PORTFOLIO"):
        failures.append("stale feed did not resolve to a single FREEZE action")

    conflict_portfolio = {
        "nav": 79.0,
        "peak_nav": 100.0,
        "gross_exposure": 0.20,
        "positions": [_quiet_position("BIG.SZ", 0.20, "Tech")],
    }
    actions = run_monitors(conflict_portfolio, _base_market(), now=now)
    if not _contains(actions, "drawdown_breaker", ACTION_TO_CASH, "PORTFOLIO"):
        failures.append("conflict fixture did not include TO_CASH")
    if any(a.action == ACTION_TRIM for a in actions):
        failures.append("conflict resolution kept TRIM despite TO_CASH breaker")

    first = to_audit_log(run_monitors(sector_portfolio, _base_market(), now=now))
    second = to_audit_log(run_monitors(sector_portfolio, _base_market(), now=now))
    if first != second:
        failures.append("determinism check failed: same fixture produced different actions")

    if failures:
        return 1, "FAIL risk_monitor selftest\n" + "\n".join(f"- {f}" for f in failures)
    return (
        0,
        "PASS risk_monitor selftest\n"
        "- position_stop EXIT\n"
        "- drawdown -13% SCALE_DOWN_GROSS\n"
        "- drawdown -21% TO_CASH\n"
        "- sector 35% BLOCK_ADD/TRIM\n"
        "- CSI300<MA200 regime cap\n"
        "- stale feed FREEZE\n"
        "- TO_CASH overrides trim\n"
        "- deterministic repeated run",
    )


def _load_json_file(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run active risk monitors over portfolio and market state.")
    parser.add_argument("--selftest", action="store_true", help="run deterministic synthetic fixture tests")
    parser.add_argument("--dry-run", action="store_true", help="emit would-be risk actions as JSON")
    parser.add_argument("--portfolio", help="portfolio_state JSON file for --dry-run")
    parser.add_argument("--market", help="market_state JSON file for --dry-run")
    parser.add_argument("--config", help="optional config JSON file for --dry-run")
    parser.add_argument("--now", default=DEFAULT_TS, help="injected ISO timestamp for deterministic action records")
    args = parser.parse_args(argv)

    if args.selftest:
        code, message = _selftest()
        sys.stdout.write(message + "\n")
        return code

    if args.dry_run:
        if not args.portfolio or not args.market:
            sys.stderr.write("--dry-run requires --portfolio and --market JSON files\n")
            return 1
        try:
            portfolio_state = _load_json_file(args.portfolio)
            market_state = _load_json_file(args.market)
            config = _load_json_file(args.config) if args.config else None
            actions = run_monitors(
                portfolio_state,
                market_state,
                config=config,
                now=args.now,
                dry_run=True,
            )
            sys.stdout.write(json.dumps(to_audit_log(actions), ensure_ascii=False, indent=2, sort_keys=True))
            sys.stdout.write("\n")
            return 0
        except Exception as exc:
            sys.stderr.write(f"risk_monitor dry-run failed: {exc}\n")
            return 1

    parser.print_help(sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
