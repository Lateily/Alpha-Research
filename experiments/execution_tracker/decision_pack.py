"""decision_pack.py — Research Decision Pack completeness gate (the output contract).

WHY: the discipline layer (discipline_prompt.md) constrains what may NOT be said
(no buy/sell, posture enums, E1-E4) but nothing enforced what MUST be said — so
research outputs drifted: variant view / catalysts / risk-mitigation / portfolio
impact kept needing to be chased by the human. This module is the missing
completeness gate: a deliverable that fails validation is REPORT_INCOMPLETE and
does not count as delivered.

Usage:
    from decision_pack import validate_pack, verdict
    ok, problems = validate_pack(pack_dict)
    print(verdict(pack_dict))       # "REPORT_COMPLETE" | "REPORT_INCOMPLETE: ..."

    python3 decision_pack.py --selftest
"""
from __future__ import annotations

EXECUTION_POSTURES = {"NO_CHASE", "HOLD_OBSERVE", "WARNING", "RECLAIM_REVIEW",
                      "DE_RISK_REVIEW", "EXIT_REVIEW"}
NOWCAST_STATES = {"ACCUMULATION_PROBABLE", "DISTRIBUTION_PROBABLE", "RECLAIM_ATTEMPT",
                  "OPENING_FADE", "FAKE_STRENGTH", "DATA_INSUFFICIENT"}

REQUIRED_SECTIONS = ("variant_view", "clean_valuation", "catalyst_map",
                     "risk_mitigation", "execution_gate", "portfolio_impact",
                     "paper_plan", "self_audit")

MIN_SELF_AUDIT_ANSWERS = 4


def _present(v):
    """A section is present if it is a non-empty dict/list/str."""
    if v is None:
        return False
    if isinstance(v, (dict, list, str)):
        return len(v) > 0
    return True


def validate_pack(pack):
    """Return (ok, problems). Checks presence of all 8 sections plus the quality
    rules that make each section mean something (not just exist)."""
    problems = []
    if not isinstance(pack, dict):
        return False, ["pack must be a dict"]

    for sec in REQUIRED_SECTIONS:
        if not _present(pack.get(sec)):
            problems.append(f"missing section: {sec}")

    # variant view must state both sides of the disagreement
    vv = pack.get("variant_view")
    if isinstance(vv, dict):
        for k in ("market_believes", "we_believe"):
            if not _present(vv.get(k)):
                problems.append(f"variant_view.{k} missing")

    # every risk must carry a mitigation or a wrong-if — a bare risk list is banned
    rm = pack.get("risk_mitigation")
    if isinstance(rm, list) and rm:
        for i, item in enumerate(rm):
            if not isinstance(item, dict) or not _present(item.get("risk")):
                problems.append(f"risk_mitigation[{i}] has no risk")
            elif not (_present(item.get("mitigation")) or _present(item.get("wrong_if"))):
                problems.append(f"risk_mitigation[{i}] '{str(item.get('risk'))[:20]}' has no mitigation/wrong_if")

    # execution gate posture must come from the enum
    eg = pack.get("execution_gate")
    if isinstance(eg, dict) and _present(eg.get("posture")):
        if eg["posture"] not in EXECUTION_POSTURES:
            problems.append(f"execution_gate.posture '{eg['posture']}' not in enum")

    # portfolio impact must address single-beta + paper risk budget
    pi = pack.get("portfolio_impact")
    if isinstance(pi, dict):
        if "single_beta_overlap" not in pi:
            problems.append("portfolio_impact.single_beta_overlap missing")
        if not _present(pi.get("paper_risk_budget")):
            problems.append("portfolio_impact.paper_risk_budget missing")

    # paper plan: no_trade_flag mandatory; a long setup must be stop < entry < target
    pp = pack.get("paper_plan")
    if isinstance(pp, dict) and _present(pp):
        if pp.get("no_trade_flag") is not True:
            problems.append("paper_plan.no_trade_flag must be true")
        e, s, t = pp.get("entry_review"), pp.get("stop_reference"), pp.get("take_profit_reference")
        if all(isinstance(x, (int, float)) for x in (e, s, t)):
            if not (s < e < t):
                problems.append(f"paper_plan mutilated: need stop<entry<target, got {s}/{e}/{t}")

    # self-audit must actually be answered, not a placeholder
    sa = pack.get("self_audit")
    if isinstance(sa, (list, dict)) and len(sa) < MIN_SELF_AUDIT_ANSWERS:
        problems.append(f"self_audit has {len(sa)} answers (<{MIN_SELF_AUDIT_ANSWERS})")

    return (len(problems) == 0), problems


def verdict(pack):
    ok, problems = validate_pack(pack)
    return "REPORT_COMPLETE" if ok else "REPORT_INCOMPLETE: " + "; ".join(problems[:6])


def _complete_pack():
    """A minimal pack that satisfies the contract — also serves as the template."""
    return {
        "variant_view": {"market_believes": "X", "we_believe": "Y", "measured_by": "Z"},
        "clean_valuation": {"caliber": "科技=PE/ROE-TTM/GM/OCF", "pe_ttm": 20.0,
                            "盈利位置": "normal"},
        "catalyst_map": [{"window": "1m", "event": "半年报", "verifies": "毛利率"}],
        "risk_mitigation": [{"risk": "需求不及预期", "wrong_if": "H1 营收<x / 半年报 / 8月"}],
        "execution_gate": {"posture": "HOLD_OBSERVE", "levels": {"承接": 1, "破坏": 0.9, "上攻": 1.1}},
        "portfolio_impact": {"single_beta_overlap": False, "correlation_note": "低相关",
                             "paper_risk_budget": "paper_small"},
        "paper_plan": {"entry_review": 10.0, "stop_reference": 9.0,
                       "take_profit_reference": 12.0, "invalidation": 8.9,
                       "no_trade_flag": True},
        "self_audit": ["no buy/sell", "no alpha claim", "fund flow checked",
                       "sector confirmed", "no look-ahead"],
    }


def selftest():
    checks = []

    def ck(n, c):
        checks.append((n, bool(c)))

    ok, problems = validate_pack(_complete_pack())
    ck("complete pack passes", ok and not problems)
    ck("complete verdict", verdict(_complete_pack()) == "REPORT_COMPLETE")

    # each missing section fails
    for sec in REQUIRED_SECTIONS:
        p = _complete_pack(); p.pop(sec)
        ok, problems = validate_pack(p)
        ck(f"missing {sec} -> INCOMPLETE", not ok and any(sec in x for x in problems))

    # bare risk list (no mitigation/wrong_if) is banned
    p = _complete_pack(); p["risk_mitigation"] = [{"risk": "只有风险没有对策"}]
    ok, problems = validate_pack(p)
    ck("risk without mitigation refused", not ok and any("mitigation" in x for x in problems))

    # posture must be in enum
    p = _complete_pack(); p["execution_gate"]["posture"] = "BUY_NOW"
    ok, _ = validate_pack(p)
    ck("posture outside enum refused", not ok)

    # paper plan discipline
    p = _complete_pack(); p["paper_plan"]["no_trade_flag"] = False
    ck("no_trade_flag=false refused", not validate_pack(p)[0])
    p = _complete_pack(); p["paper_plan"]["stop_reference"] = 11.0   # stop > entry
    ck("mutilated paper plan refused", not validate_pack(p)[0])

    # portfolio impact needs single-beta answer + budget
    p = _complete_pack(); p["portfolio_impact"] = {"correlation_note": "x"}
    ok, problems = validate_pack(p)
    ck("portfolio impact without single-beta/budget refused",
       not ok and any("single_beta" in x for x in problems) and any("budget" in x for x in problems))

    # placeholder self-audit refused
    p = _complete_pack(); p["self_audit"] = ["ok"]
    ck("placeholder self-audit refused", not validate_pack(p)[0])

    # verdict message carries the reasons
    p = _complete_pack(); p.pop("catalyst_map")
    ck("verdict names the gap", "catalyst_map" in verdict(p))

    passed = sum(1 for _, okk in checks if okk)
    for n, okk in checks:
        print(f"  [{'PASS' if okk else 'FAIL'}] {n}")
    print(f"\nselftest: {passed}/{len(checks)} passed")
    return passed == len(checks)


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    print("usage: python3 decision_pack.py --selftest")
