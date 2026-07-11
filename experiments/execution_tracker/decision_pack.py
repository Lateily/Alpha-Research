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
VARIANT_STANCES = {"VARIANT", "CONSENSUS_RIDE", "NO_EDGE"}

REQUIRED_SECTIONS = ("variant_view", "clean_valuation", "catalyst_map",
                     "risk_mitigation", "execution_gate", "portfolio_impact",
                     "paper_plan", "self_audit")

MIN_SELF_AUDIT_ANSWERS = 4


VALUATION_ANCHORS = ("pe_ttm", "pe", "pb", "ps", "ev_ebitda", "dividend_yield",
                     "股息", "normalized_bridge", "dcf", "rdcf")

# Codex adversarial review of PR #118 (blocking): presence-only checks let a WRONG
# TYPE bypass every quality rule (`execution_gate="BUY_NOW"` passed because the
# posture check only ran `if isinstance(dict)`). Fix: every section has a REQUIRED
# TYPE; wrong type is itself a violation, and typed rules then always apply.
SECTION_TYPES = {
    "variant_view": dict, "clean_valuation": dict, "catalyst_map": list,
    "risk_mitigation": list, "execution_gate": dict, "portfolio_impact": dict,
    "paper_plan": dict, "self_audit": (list, dict),
}


def _present(v):
    """A value is present if it is a non-empty dict/list/str."""
    if v is None:
        return False
    if isinstance(v, (dict, list, str)):
        return len(v) > 0
    return True


def validate_pack(pack):
    """Return (ok, problems). Strict schema: every section must exist, BE THE RIGHT
    TYPE, and satisfy the quality rules that make it mean something."""
    problems = []
    if not isinstance(pack, dict):
        return False, ["pack must be a dict"]

    for sec in REQUIRED_SECTIONS:
        v = pack.get(sec)
        if not _present(v):
            problems.append(f"missing section: {sec}")
        elif not isinstance(v, SECTION_TYPES[sec]):
            tname = getattr(SECTION_TYPES[sec], "__name__", "list/dict")
            problems.append(f"{sec} must be a {tname}, got {type(v).__name__}")

    # View vs Consensus — THREE honest stances (Junyan 2026-07-07: 不能为了 variant
    # 而 variant). A mandatory variant box breeds performative contrarianism, so a
    # VARIANT claim now costs MORE (edge_source required), and agreeing with the
    # market (CONSENSUS_RIDE) or having no view (NO_EDGE) are first-class outputs.
    vv = pack.get("variant_view")
    if isinstance(vv, dict):
        stance = vv.get("stance")
        if stance not in VARIANT_STANCES:
            problems.append("variant_view.stance missing — declare VARIANT / CONSENSUS_RIDE / NO_EDGE")
        elif stance == "VARIANT":
            for k in ("market_believes", "we_believe", "measured_by", "edge_source"):
                if not _present(vv.get(k)):
                    problems.append(f"variant_view.{k} missing (a VARIANT claim must state "
                                    f"the disagreement, how it is measured, and WHY we know "
                                    f"something the market doesn't)")
        elif stance == "CONSENSUS_RIDE":
            if not _present(vv.get("consensus")):
                problems.append("variant_view.consensus missing (state what we agree with)")
            if not _present(vv.get("edge_source")):
                problems.append("variant_view.edge_source missing (riding consensus still needs "
                                "an edge: execution / timing / risk-management — say which)")
        elif stance == "NO_EDGE":
            if not _present(vv.get("reason")):
                problems.append("variant_view.reason missing (why no differentiated view)")

    # clean valuation: sector caliber + 盈利位置 + at least one valuation anchor
    cv = pack.get("clean_valuation")
    if isinstance(cv, dict):
        if not _present(cv.get("caliber")):
            problems.append("clean_valuation.caliber missing (分行业口径)")
        if not _present(cv.get("盈利位置")) and not _present(cv.get("earnings_position")):
            problems.append("clean_valuation.盈利位置 missing")
        if not any(_present(cv.get(a)) or isinstance(cv.get(a), (int, float)) for a in VALUATION_ANCHORS):
            problems.append(f"clean_valuation has no valuation anchor ({'/'.join(VALUATION_ANCHORS[:4])}/...)")

    # catalyst map: structured items, each with window/event/verifies
    cm = pack.get("catalyst_map")
    if isinstance(cm, list):
        for i, item in enumerate(cm):
            if not isinstance(item, dict):
                problems.append(f"catalyst_map[{i}] must be a dict")
                continue
            for k in ("window", "event", "verifies"):
                if not _present(item.get(k)):
                    problems.append(f"catalyst_map[{i}].{k} missing")

    # every risk must carry a mitigation or a wrong-if — a bare risk list is banned
    rm = pack.get("risk_mitigation")
    if isinstance(rm, list):
        for i, item in enumerate(rm):
            if not isinstance(item, dict) or not _present(item.get("risk")):
                problems.append(f"risk_mitigation[{i}] has no risk")
            elif not (_present(item.get("mitigation")) or _present(item.get("wrong_if"))):
                problems.append(f"risk_mitigation[{i}] '{str(item.get('risk'))[:20]}' has no mitigation/wrong_if")

    # execution gate: posture MANDATORY and from the enum
    eg = pack.get("execution_gate")
    if isinstance(eg, dict):
        if not _present(eg.get("posture")):
            problems.append("execution_gate.posture missing")
        elif eg["posture"] not in EXECUTION_POSTURES:
            problems.append(f"execution_gate.posture '{eg['posture']}' not in enum")

    # portfolio impact must address single-beta + paper risk budget
    pi = pack.get("portfolio_impact")
    if isinstance(pi, dict):
        if "single_beta_overlap" not in pi:
            problems.append("portfolio_impact.single_beta_overlap missing")
        if not _present(pi.get("paper_risk_budget")):
            problems.append("portfolio_impact.paper_risk_budget missing")

    # paper plan: numeric entry/stop/target MANDATORY + no_trade_flag + stop<entry<target
    pp = pack.get("paper_plan")
    if isinstance(pp, dict):
        if pp.get("no_trade_flag") is not True:
            problems.append("paper_plan.no_trade_flag must be true")
        e, s, t = pp.get("entry_review"), pp.get("stop_reference"), pp.get("take_profit_reference")
        missing = [k for k, x in (("entry_review", e), ("stop_reference", s),
                                  ("take_profit_reference", t)) if not isinstance(x, (int, float))]
        if missing:
            problems.append(f"paper_plan missing numeric {'/'.join(missing)}")
        elif not (s < e < t):
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
        "variant_view": {"stance": "VARIANT", "market_believes": "X", "we_believe": "Y",
                         "measured_by": "Z", "edge_source": "informational: settle-flow forensics"},
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

    # ---- Codex adversarial probes (PR #118 review, blocking finding) ----
    # wrong TYPES must not bypass the gate: non-empty strings previously passed
    # every isinstance-gated quality rule.
    p = _complete_pack()
    p["risk_mitigation"] = "bare risk string"
    p["execution_gate"] = "BUY_NOW"
    p["portfolio_impact"] = "none"
    p["paper_plan"] = "entry 10 stop 11 target 9"
    p["self_audit"] = "ok"
    ok, problems = validate_pack(p)
    ck("adversarial string-typed pack refused", not ok)
    ck("adversarial finds >=5 type violations", len([x for x in problems if "must be a" in x]) >= 5)
    ck("BUY_NOW cannot slip through as a string", any("execution_gate must be a dict" in x for x in problems))

    p = _complete_pack(); p["paper_plan"] = {"no_trade_flag": True}   # no numbers
    ok, problems = validate_pack(p)
    ck("paper_plan without entry/stop/target refused", not ok and any("missing numeric" in x for x in problems))

    p = _complete_pack(); p["catalyst_map"] = "later"
    ck("catalyst_map as prose refused", not validate_pack(p)[0])
    p = _complete_pack(); p["catalyst_map"] = [{"event": "半年报"}]   # missing window/verifies
    ok, problems = validate_pack(p)
    ck("catalyst item missing window/verifies refused",
       not ok and any("window" in x for x in problems) and any("verifies" in x for x in problems))

    p = _complete_pack(); p["clean_valuation"] = {"note": "x"}        # no caliber/盈利位置/anchor
    ok, problems = validate_pack(p)
    ck("valuation without caliber refused", not ok and any("caliber" in x for x in problems))
    ck("valuation without anchor refused", any("anchor" in x for x in problems))

    p = _complete_pack(); p["variant_view"] = {"market_believes": "X", "we_believe": "Y"}
    ok, problems = validate_pack(p)
    ck("variant_view without stance refused (old style dies)",
       not ok and any("stance missing" in x for x in problems))

    # ---- 不能为了 variant 而 variant (Junyan 2026-07-07) ----
    p = _complete_pack()
    p["variant_view"] = {"stance": "VARIANT", "market_believes": "X", "we_believe": "Y",
                         "measured_by": "Z"}                      # no edge_source
    ok, problems = validate_pack(p)
    ck("VARIANT without edge_source refused (fake variant blocked)",
       not ok and any("edge_source" in x for x in problems))
    p = _complete_pack()
    p["variant_view"] = {"stance": "CONSENSUS_RIDE", "consensus": "trend intact",
                         "edge_source": "execution: breakout-gated entry + 1% risk stops"}
    ck("CONSENSUS_RIDE is a first-class pass", validate_pack(p)[0])
    p = _complete_pack()
    p["variant_view"] = {"stance": "CONSENSUS_RIDE", "consensus": "trend intact"}
    ck("CONSENSUS_RIDE still needs an edge_source", not validate_pack(p)[0])
    p = _complete_pack()
    p["variant_view"] = {"stance": "NO_EDGE", "reason": "no informational or analytical edge on this name"}
    ck("NO_EDGE with reason is a first-class pass", validate_pack(p)[0])
    p = _complete_pack()
    p["variant_view"] = {"stance": "NO_EDGE"}
    ck("NO_EDGE without reason refused", not validate_pack(p)[0])

    p = _complete_pack(); p["execution_gate"] = {"levels": {"承接": 1}}  # dict but no posture
    ok, problems = validate_pack(p)
    ck("execution_gate without posture refused", not ok and any("posture missing" in x for x in problems))

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
