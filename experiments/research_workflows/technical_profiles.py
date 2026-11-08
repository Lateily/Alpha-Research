"""Operator-selected daily profile; approval is not implementation or efficacy."""
from __future__ import annotations

from copy import deepcopy

from .evidence import canonical, sha

PROFILE_ID = "DAILY_SWEEP_RECLAIM_CANDIDATE_0_1"
SPEC_BYTE_SHA256 = "b4bf29fddbebb94298e8d58b948766697b915611142e0c6ee933b35554c8e9f7"


def _catalog():
    definitions = {
        "STRICT_PIVOT_LOW": ("Low strictly below two bars on each side; equality is excluded.",
                             "Second following bar closed and available.", ["Equal lows are not pivots."]),
        "STRICT_PIVOT_HIGH": ("High strictly above two bars on each side; equality is excluded.",
                              "Second following bar closed and available.", ["Unconfirmed highs are not targets."]),
        "LIQUIDITY_SWEEP": ("Low at least one tick below the most recent confirmed, unbroken pivot low.",
                            "Sweep bar closed and available.", ["Do not recover an older broken reference."]),
        "RECLAIM": ("First close at or above reference from sweep through third following bar.",
                    "Reclaim bar closed and available.", ["Later reclaim is outside the window."]),
    }
    names = ["HH", "HL", "LH", "LL", "BOS", "CHOCH", "MSS", "EQUAL_HIGHS", "EQUAL_LOWS",
             "PREMIUM_DISCOUNT", "FVG", "IFVG", "ORDER_BLOCK", "MITIGATION", "BREAKER", "OTE",
             "INDUCEMENT", "SMT", "LIQUIDITY_TARGET", "SESSION", "KILLZONE"]
    rows = []
    for name in list(definitions) + names:
        definition, confirmation, counterexamples = definitions.get(
            name, ("Not defined for execution in this profile.", "Not executable in this profile.",
                   ["Catalog presence is not an implemented signal."]))
        rows.append({"method_id": name, "definition": definition, "confirmation": confirmation,
                     "parameters": ("Approved profile parameters" if name in definitions else None),
                     "counterexamples": counterexamples, "enabled": name in definitions,
                     "implementation_state": ("UNSUPPORTED_TIMEFRAME" if name in {"SESSION", "KILLZONE"}
                                              else "NOT_IMPLEMENTED")})
    return rows


def load_profile(profile_id: str) -> dict:
    """Return a fresh approved profile and its canonical semantic (not file) SHA."""
    if type(profile_id) is not str or profile_id != PROFILE_ID:
        raise ValueError("unknown technical profile")
    profile = {
        "schema_version": "technical-profile.v1", "profile_id": PROFILE_ID,
        "workflow_version": "technical-workflow.v0.1", "spec_byte_sha256": SPEC_BYTE_SHA256,
        "market": "A_SHARE", "timeframe": "1d", "direction": "LONG_ONLY",
        "approval_scope": "OFFLINE_WORKFLOW_DEBUG", "efficacy_validated": False,
        "parameters": {
            "minimum_history_bars": 60, "pivot_left_bars": 2, "pivot_right_bars": 2,
            "strict_pivots": True, "tick_cny": "0.01", "minimum_sweep_ticks": 1,
            "reclaim_following_bars": 3, "event_selection": "FIRST_LEGAL_EVENT",
            "atr_period": 14, "atr_method": "WILDER", "atr_seed": "FIRST_14_TR_MEAN",
            "stop_atr_multiplier": "0.25", "volume_short_bars": 5, "volume_long_bars": 60,
            "volume_comparison": "SHORT_MEAN_GTE_LONG_MEAN", "settled_flow_days": 2,
            "settled_flow_comparison": "SUM_GT_ZERO", "minimum_gross_reward_risk": "2",
            "price_basis": "RAW", "currency": "CNY", "normalized_volume_unit": "shares",
            "normalized_amount_unit": "CNY", "market_timezone": "Asia/Shanghai",
        },
        "context_requirements": {"excluded_market_states": ["RISK_OFF", "UNKNOWN"],
                                 "sector_state": "CONFIRMED", "bound_human_receipt_required": True},
        "method_catalog": _catalog(),
    }
    profile["profile_hash"] = sha(canonical(profile))
    return deepcopy(profile)
