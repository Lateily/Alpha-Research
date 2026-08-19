#!/usr/bin/env python3
"""Experimental capital-flow regime policy.

This is not a production signal generator. It encodes the July 2026 model
status change:

- positive "where money goes next" flow nowcasts are observation-only in churn;
- negative distribution / escape signatures may drive risk-review posture;
- no entry/posture claim graduates without forward evidence.

All numeric gates below are operating priors, not calibrated thresholds.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any


POSITIVE_FLOW_TYPES = {
    "ACCUMULATION_PROBABLE",
    "RECLAIM_ATTEMPT",
    "PAPER_RECLAIM_LONG",
    "CVD_FLOOR_FORMED",
    "CONTROLLED_ADVANCE",
    "VOLUME_BREAKOUT",
    "MACD_GOLDEN_CROSS",
    "KDJ_GOLDEN_CROSS",
    "RSI_RECOVERING",
}

NEGATIVE_FLOW_TYPES = {
    "DISTRIBUTION_PROBABLE",
    "FAKE_STRENGTH",
    "OPENING_FADE",
    "PAPER_DERISK",
    "PAPER_EXIT_REVIEW",
    "CVD_BEARISH_DIVERGENCE",
    "VOLUME_SELLOFF",
    "MACD_DEATH_CROSS",
    "KDJ_DEATH_CROSS",
    "KDJ_OVERBOUGHT",
    "RSI_OVERBOUGHT",
}

EDGE_N_MIN = 30
EDGE_HIT_RATE_PRIOR = 0.58
NO_EDGE_HIT_RATE_PRIOR = 0.52
CHURN_HALF_LIFE_DAYS_PRIOR = 2.0
NOWCAST_FAIL_HIT_RATE_PRIOR = 0.55


@dataclass(frozen=True)
class SetupStats:
    sample_n: int
    hit_rate: float | None = None
    avg_forward_return: float | None = None
    false_breakout_rate: float | None = None


@dataclass(frozen=True)
class RegimeStats:
    rotation_half_life_days: float | None = None
    recent_nowcast_hit_rate: float | None = None
    recent_nowcast_n: int = 0
    market_state: str = "UNKNOWN"


def signal_family(signal_type: str) -> str:
    if signal_type in POSITIVE_FLOW_TYPES:
        return "positive_flow"
    if signal_type in NEGATIVE_FLOW_TYPES:
        return "negative_flow"
    return "other"


def evidence_status(stats: SetupStats) -> str:
    """Return evidence status for predictive use.

    Thresholds are unvalidated operating priors. They only decide whether a
    signal can be used as a paper-review candidate, never real capital.
    """
    if stats.sample_n < EDGE_N_MIN:
        return "NO_CLAIM_UNDERPOWERED"
    if stats.hit_rate is None:
        return "NO_CLAIM_MISSING_SCORE"
    if stats.hit_rate <= NO_EDGE_HIT_RATE_PRIOR:
        return "NO_EDGE"
    if (
        stats.hit_rate >= EDGE_HIT_RATE_PRIOR
        and stats.avg_forward_return is not None
        and stats.avg_forward_return > 0
    ):
        return "FORWARD_EDGE_CANDIDATE"
    return "INCONCLUSIVE"


def is_churn_regime(regime: RegimeStats) -> bool:
    short_half_life = (
        regime.rotation_half_life_days is not None
        and regime.rotation_half_life_days <= CHURN_HALF_LIFE_DAYS_PRIOR
    )
    nowcast_failed = (
        regime.recent_nowcast_n >= 10
        and regime.recent_nowcast_hit_rate is not None
        and regime.recent_nowcast_hit_rate <= NOWCAST_FAIL_HIT_RATE_PRIOR
    )
    explicit = regime.market_state in {"STYLE_ROTATION", "CHURN", "RISK_OFF"}
    return bool(short_half_life or nowcast_failed or explicit)


def policy_for_signal(
    signal_type: str,
    setup_stats: SetupStats,
    regime_stats: RegimeStats,
) -> dict[str, Any]:
    family = signal_family(signal_type)
    status = evidence_status(setup_stats)
    churn = is_churn_regime(regime_stats)

    policy: dict[str, Any] = {
        "signal_type": signal_type,
        "family": family,
        "evidence_status": status,
        "regime_churn": churn,
        "predictive_weight_multiplier": 1.0,
        "entry_gate": "BLOCKED",
        "risk_gate": "OBSERVE",
        "posture": "OBSERVE_ONLY",
        "causal_logic": "unestablished",
        "number_status": "unvalidated intuition",
        "required_confirmations": [],
        "notes": [],
    }

    if family == "positive_flow":
        policy["causal_logic"] = (
            "questionable: positive flow facts do not imply next-day continuation "
            "when rotation half-life is near one day"
        )
        if churn or status in {"NO_CLAIM_UNDERPOWERED", "NO_EDGE", "INCONCLUSIVE"}:
            policy["predictive_weight_multiplier"] = 0.0
            policy["entry_gate"] = "BLOCKED"
            policy["posture"] = "OBSERVE_ONLY"
            policy["required_confirmations"] = [
                "2-3 week persistence confirmation",
                "sector anchor confirmation",
                "reclaim or breakout must hold into close",
                "no distribution signature",
                "forward paper edge n>=30 by setup_type",
            ]
            policy["notes"].append("positive destination prediction quarantined")
            return policy

        policy["entry_gate"] = "PAPER_REVIEW_ONLY"
        policy["posture"] = "RECLAIM_REVIEW"
        policy["required_confirmations"] = [
            "human PASS",
            "paper signal log entry",
            "same setup stays forward-edge candidate after costs",
        ]
        return policy

    if family == "negative_flow":
        policy["causal_logic"] = (
            "partially valid: distribution / escape signatures can persist because "
            "inventory overhang, trapped holders, and failed-reclaim supply have inertia"
        )
        policy["entry_gate"] = "BLOCKED"
        policy["predictive_weight_multiplier"] = 0.0
        policy["risk_gate"] = "RISK_REVIEW_ALLOWED"
        policy["posture"] = "DE_RISK_REVIEW"
        policy["required_confirmations"] = [
            "distribution or fake-strength signature",
            "support break or failed reclaim",
            "sector anchor not repairing",
            "portfolio beta/concentration check",
        ]
        if status == "FORWARD_EDGE_CANDIDATE":
            policy["notes"].append("negative setup has scored forward evidence")
        else:
            policy["notes"].append("use as risk gate, not alpha claim")
        return policy

    policy["causal_logic"] = "unestablished: signal not mapped to flow asymmetry"
    policy["predictive_weight_multiplier"] = 0.0 if churn else 0.5
    policy["posture"] = "HOLD_OBSERVE"
    policy["required_confirmations"] = ["map signal to setup_type before predictive use"]
    return policy


def recommended_confluence_overrides(regime_stats: RegimeStats) -> dict[str, Any]:
    churn = is_churn_regime(regime_stats)
    return {
        "model_state": "CHURN_MODE" if churn else "NORMAL_OBSERVATION_MODE",
        "specific_numbers": "unvalidated intuition",
        "causal_logic": (
            "valid as a risk-control overlay, unestablished as a positive capital-flow predictor"
        ),
        "overrides": {
            "positive_flow_entry_weight": 0.0 if churn else "requires forward_edge_candidate",
            "negative_flow_risk_weight": "enabled for risk review",
            "sizing_output": "disabled until production approval; no recommended size",
            "paper_signal_required": True,
            "min_forward_sample_for_alpha_claim": EDGE_N_MIN,
        },
    }


def _selftest() -> int:
    errs: list[str] = []

    churn = RegimeStats(
        rotation_half_life_days=1.0,
        recent_nowcast_hit_rate=0.50,
        recent_nowcast_n=14,
        market_state="STYLE_ROTATION",
    )
    weak_positive = SetupStats(sample_n=14, hit_rate=0.50, avg_forward_return=-0.01)
    p = policy_for_signal("ACCUMULATION_PROBABLE", weak_positive, churn)
    if p["posture"] != "OBSERVE_ONLY" or p["predictive_weight_multiplier"] != 0.0:
        errs.append("positive nowcast in churn must be observation-only")

    scored_negative = SetupStats(sample_n=30, hit_rate=0.67, avg_forward_return=0.02)
    n = policy_for_signal("DISTRIBUTION_PROBABLE", scored_negative, churn)
    if n["risk_gate"] != "RISK_REVIEW_ALLOWED" or n["entry_gate"] != "BLOCKED":
        errs.append("negative distribution must be risk-review only, not entry")

    normal = RegimeStats(rotation_half_life_days=5.0, recent_nowcast_hit_rate=0.62, recent_nowcast_n=30)
    scored_positive = SetupStats(sample_n=30, hit_rate=0.60, avg_forward_return=0.01)
    pp = policy_for_signal("PAPER_RECLAIM_LONG", scored_positive, normal)
    if pp["entry_gate"] != "PAPER_REVIEW_ONLY":
        errs.append("positive flow with forward evidence can only become paper review")

    ov = recommended_confluence_overrides(churn)
    if ov["model_state"] != "CHURN_MODE" or ov["overrides"]["positive_flow_entry_weight"] != 0.0:
        errs.append("churn override must disable positive-flow entry weight")

    if errs:
        print("flow_regime_policy selftest FAILED")
        for err in errs:
            print(f"  - {err}")
        return 1
    print("flow_regime_policy selftest PASSED")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--signal-type", default="ACCUMULATION_PROBABLE")
    parser.add_argument("--sample-n", type=int, default=14)
    parser.add_argument("--hit-rate", type=float, default=0.50)
    parser.add_argument("--avg-forward-return", type=float, default=0.0)
    parser.add_argument("--rotation-half-life-days", type=float, default=1.0)
    parser.add_argument("--recent-nowcast-hit-rate", type=float, default=0.50)
    parser.add_argument("--recent-nowcast-n", type=int, default=14)
    parser.add_argument("--market-state", default="STYLE_ROTATION")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    setup = SetupStats(
        sample_n=args.sample_n,
        hit_rate=args.hit_rate,
        avg_forward_return=args.avg_forward_return,
    )
    regime = RegimeStats(
        rotation_half_life_days=args.rotation_half_life_days,
        recent_nowcast_hit_rate=args.recent_nowcast_hit_rate,
        recent_nowcast_n=args.recent_nowcast_n,
        market_state=args.market_state,
    )
    out = {
        "policy": policy_for_signal(args.signal_type, setup, regime),
        "confluence_overrides": recommended_confluence_overrides(regime),
        "no_trade_flag": True,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
