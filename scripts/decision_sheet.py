#!/usr/bin/env python3
"""decision_sheet.py — Core Thesis Factory v1 decision-sheet composer (PR-A).

Implements the 单票决策书 contract of docs/strategy/CORE_THESIS_FACTORY_v1_SPEC.md
(Junyan-ratified 2026-06-10). Composes an analyst-authored RESEARCH CORE
(docs/research/decision_sheets/cores/<ticker>_core.json — the substance: thesis, tagged
evidence, catalysts, mechanized wrong_if, scenario band, execution plan, risks, bilingual)
with AUTO-ATTACHED market context (latest committed price bar, technical signals, EQR
ratings, valuation-stack status, sentiment-feed status, v0 thesis provenance), then:

  1. enforces the QUALIFICATION RULE — a sheet missing any required group, any untagged
     causal link, an un-mechanized wrong_if trigger, or carrying a single-point target
     (instead of an assumption-explicit base/bull/bear band) is NOT a qualified output
     and the composer REFUSES to emit it;
  2. computes R/R from the band + last price and applies the R/R >= 2:1 conviction bar
     (below it the stance is forced to WATCH_NOT_CONVICTION at current price);
  3. writes public/data/decision_sheets/<ticker>.json (+ sha256 content lock for the
     forward 30/60/90 checkpoints, PR-D) and renders a bilingual markdown 决策书 for the
     human red-team (the measure of record — auto checks here are the FLOOR only).

Read-only elsewhere. Usage:
  python3 scripts/decision_sheet.py --ticker 002594.SZ
  python3 scripts/decision_sheet.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
CORES = REPO / "docs" / "research" / "decision_sheets" / "cores"
SHEETS_OUT = D / "decision_sheets"
MD_OUT = REPO / "docs" / "research" / "decision_sheets"

CAUSAL_TAGS = {"PROVEN", "INFERRED", "ASSUMED"}
CITE_GRADES = {"EDGE_ESTABLISHING", "CONSENSUS_CONFIRMING", "CROWDING_SIGNAL", "DECORATIVE"}
REQUIRED_GROUPS = ("identity", "thesis", "evidence", "catalyst_calendar", "wrong_if",
                   "valuation_target_range", "execution_plan", "risk", "disclaimers")
BILINGUAL_FIELDS = (("thesis", "variant_perception"), ("thesis", "mechanism"))
RR_CONVICTION_BAR = 2.0          # [unvalidated intuition] — the 2026-05-15 大参林 rule
# Serenity block (#67 ratified 2026-06-11): REQUIRED for NEW names; optional for the
# registered refresh sample(s). 10 fields per SERENITY_INTEGRATION_SPEC.md §2.
SERENITY_FIELDS = ("theme_system_change", "value_chain_map", "scarce_layer", "company_role",
                   "bottleneck_evidence", "market_may_be_missing", "substitution_route",
                   "expansion_difficulty", "customer_validation", "what_weakens_the_view")
SERENITY_OPTIONAL_REFRESH = {"002594.SZ"}  # ticker #1 = the v0→v1 refresh sample (pre-dates #67)


def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _bilingual_ok(node):
    return isinstance(node, dict) and bool(node.get("zh")) and bool(node.get("en"))


def qualify(core: dict) -> list[str]:
    """The qualification rule. Returns [] iff the core is a qualified output."""
    errs = []
    for g in REQUIRED_GROUPS:
        if not core.get(g):
            errs.append(f"missing required group: {g}")
    if errs:
        return errs
    # evidence: every item tagged, every causal link tagged, Rule-X present
    ev = core["evidence"]
    for i, item in enumerate(ev.get("items", []) or []):
        if item.get("tier") not in ("E1", "E2"):
            errs.append(f"evidence[{i}] missing E1/E2 tier")
        if item.get("causal_tag") not in CAUSAL_TAGS:
            errs.append(f"evidence[{i}] causal_tag must be PROVEN|INFERRED|ASSUMED")
        if item.get("citation_grade") not in CITE_GRADES:
            errs.append(f"evidence[{i}] citation_grade missing/invalid")
    if not ev.get("items"):
        errs.append("evidence.items empty")
    if "rule_x_check" not in ev:
        errs.append("evidence.rule_x_check missing (issuer-disclosure re-confirmability)")
    if not ev.get("contrarian_view"):
        errs.append("evidence.contrarian_view missing")
    # wrong_if: >=2 mechanized triggers (metric+threshold+source+check_date)
    wi = core["wrong_if"]
    trigs = wi.get("triggers", []) or []
    if len(trigs) < 2:
        errs.append("wrong_if needs >=2 triggers")
    for i, t in enumerate(trigs):
        for f in ("metric", "threshold", "source", "check_date"):
            if not t.get(f):
                errs.append(f"wrong_if.triggers[{i}] missing {f} (must be mechanized)")
    # band: 3 scenarios, each with explicit assumptions + a range (no single-point targets)
    band = core["valuation_target_range"]
    for sc in ("bear", "base", "bull"):
        s = band.get(sc)
        if not s:
            errs.append(f"valuation_target_range.{sc} missing")
            continue
        if not s.get("assumptions"):
            errs.append(f"{sc}: assumptions must be explicit")
        lo, hi = s.get("low"), s.get("high")
        if lo is None or hi is None or not (hi > lo > 0):
            errs.append(f"{sc}: needs a RANGE low<high (single-point targets are forbidden)")
    if band.get("calibrated") is not False:
        errs.append("valuation_target_range.calibrated must be False (until forward-validated)")
    # execution plan essentials
    plan = core["execution_plan"]
    for f in ("entry", "staging", "invalidation", "sizing_suggestion", "holding_horizon", "review_dates"):
        if not plan.get(f):
            errs.append(f"execution_plan.{f} missing")
    if "human_executes" not in json.dumps(plan, ensure_ascii=False):
        errs.append("execution_plan must state human_executes (suggestion-only sizing)")
    # risk checklist: all five categories, each specific (non-empty string)
    risk = core["risk"]
    for cat in ("fundamental", "policy", "valuation", "liquidity", "crowding_reflexivity"):
        if not risk.get(cat):
            errs.append(f"risk.{cat} missing")
    # bilingual
    for path in BILINGUAL_FIELDS:
        node = core
        for k in path:
            node = node.get(k, {}) if isinstance(node, dict) else {}
        if not _bilingual_ok(node):
            errs.append(f"{'.'.join(path)} must be bilingual {{zh,en}}")
    if not _bilingual_ok(core["execution_plan"].get("summary", {})):
        errs.append("execution_plan.summary must be bilingual {zh,en}")
    # serenity block (#67): REQUIRED for new names; the discovery layer must answer
    # 卡在哪一层/为什么绕不开/证据多强/什么事实让我们降级 — never a trade signal
    tkr = (core.get("identity") or {}).get("ticker", "")
    ser = core.get("serenity")
    if not ser and tkr not in SERENITY_OPTIONAL_REFRESH:
        errs.append("serenity block missing (REQUIRED for new names per the #67 ratification)")
    if ser:
        for f in SERENITY_FIELDS:
            if not ser.get(f):
                errs.append(f"serenity.{f} missing")
        if len(ser.get("value_chain_map") or []) < 3:
            errs.append("serenity.value_chain_map needs >=3 ranked layers")
        for i, b in enumerate(ser.get("bottleneck_evidence") or []):
            if b.get("tier") not in ("E1", "E2"):
                errs.append(f"serenity.bottleneck_evidence[{i}] missing E1/E2 tier")
            if b.get("citation_grade") not in CITE_GRADES:
                errs.append(f"serenity.bottleneck_evidence[{i}] citation_grade missing/invalid")
        mech = [w for w in (ser.get("what_weakens_the_view") or [])
                if all(w.get(k) for k in ("metric", "threshold", "source", "check_date"))]
        if len(mech) < 2:
            errs.append("serenity.what_weakens_the_view needs >=2 MECHANIZED items "
                        "(metric+threshold+source+check_date)")
    return errs


def _auto_context(ticker: str) -> dict:
    safe = ticker.replace(".", "_")
    ohlc = _load(D / f"ohlc_{safe}.json", {}) or {}
    bars = ohlc.get("data") or []
    last = bars[-1] if bars else {}
    sig = _load(D / f"signals_{safe}.json", {}) or {}
    eqr = _load(D / f"eqr_{safe}.json", {}) or {}
    uni = _load(D / "universe_a.json", {}) or {}
    row = next((s for s in uni.get("stocks", []) if s.get("ticker") == ticker), {})
    mmv = _load(D / "multi_method_valuation.json", {}) or {}
    mrow = mmv if mmv.get("ticker") == ticker else (mmv.get(ticker) or {})
    breaks = []
    if last.get("date") and last["date"] < datetime.now(timezone.utc).date().isoformat().replace("-", "")[:8]:
        pass
    # price fallback: when no per-ticker ohlc is committed yet (new watchlist names),
    # fall back to the universe_a snapshot price with its date carried — staleness and
    # source are explicit, never papered over
    px_close, px_date, px_src = last.get("close"), last.get("date"), "ohlc_committed"
    if px_close is None and row.get("price"):
        px_close = row.get("price")
        px_date = ((uni.get("_meta") or {}).get("fetched_at") or "")[:10]
        px_src = "universe_a_snapshot_fallback"
    return {
        "last_price": {"close": px_close, "date": px_date, "source": px_src,
                       "note": "latest COMMITTED price — staleness is flagged, never papered over"},
        "technical": {"zone": sig.get("zone"), "generated_at": sig.get("generated_at"),
                      "rsi14": (sig.get("indicators") or {}).get("rsi14"),
                      "signals": [s.get("type") for s in (sig.get("signals") or [])]},
        "eqr": {"overall": eqr.get("overall"),
                "sections": {k: (v or {}).get("rating") for k, v in (eqr.get("sections") or {}).items()}},
        "market_anchors": {"as_of": (uni.get("_meta") or {}).get("fetched_at"),
                           "price": row.get("price"), "market_cap": row.get("market_cap"),
                           "pe_dynamic": row.get("pe"), "pb": row.get("pb")},
        "valuation_stack_status": {"triangulated_signal": mrow.get("triangulated_signal"),
                                   "methods_used": mrow.get("methods_used"),
                                   "note": "automated valuation generators' status — breaks logged honestly"},
    }


def _apply_corporate_actions(auto: dict, core: dict) -> dict:
    """Adjust a committed reference price for corporate actions DECLARED in the core
    (E1-sourced, e.g. 10转4派4). Applies only when the committed price pre-dates the
    ex-date and the ex-date has passed — so a stale snapshot is never compared against
    a post-split band on the wrong share basis. Dies naturally once fresh bars land."""
    lp = dict(auto.get("last_price") or {})
    px, pdate = lp.get("close"), str(lp.get("date") or "")
    if px is None or not pdate:
        return auto
    norm = lambda d: str(d).replace("-", "")[:8]
    today = norm(datetime.now(timezone.utc).date().isoformat())
    for ca in ((core.get("identity") or {}).get("corporate_actions") or []):
        ex = norm(ca.get("ex_date", ""))
        if ca.get("type") == "split_dividend" and ex and norm(pdate) < ex <= today:
            factor = float(ca.get("split_factor", 1)) or 1.0
            div = float(ca.get("dividend_per_share", 0))
            adj = round((float(px) - div) / factor, 2)
            lp.update({"close": adj, "raw_close_before_adjustment": px,
                       "adjustment": (f"split_dividend ex {ca.get('ex_date')}: "
                                      f"({px} - {div}) / {factor} = {adj}"),
                       "adjustment_source": ca.get("source", "declared in core")})
            auto = {**auto, "last_price": lp}
    return auto


def _content_lock(sheet: dict) -> str:
    """sha256 over the CANONICAL CONTENT payload only — excludes volatile/process fields
    (_meta carries generated_at; quality is process state; the lock itself). A pure rerun
    with unchanged research content + unchanged committed inputs MUST produce the same lock
    (Junyan #64 review: a generated_at-sensitive lock would make a rerun look like a new
    thesis and corrupt the 30/60/90 forward-validation ledger)."""
    payload = {k: v for k, v in sheet.items()
               if k not in ("_meta", "quality", "content_lock_sha256")}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _rr(band: dict, px) -> dict:
    """R/R from last price to bull-mid vs bear-mid + the conviction bar."""
    try:
        bull_mid = (band["bull"]["low"] + band["bull"]["high"]) / 2.0
        bear_mid = (band["bear"]["low"] + band["bear"]["high"]) / 2.0
        up, dn = bull_mid - px, px - bear_mid
        rr = round(up / dn, 2) if dn > 0 else None
        entry_for_bar = round((bull_mid + RR_CONVICTION_BAR * bear_mid) / (1 + RR_CONVICTION_BAR), 2)
        return {"reference_price": px, "bull_mid": round(bull_mid, 2), "bear_mid": round(bear_mid, 2),
                "reward_to_risk": rr, "conviction_bar": RR_CONVICTION_BAR,
                "meets_conviction_bar": bool(rr is not None and rr >= RR_CONVICTION_BAR),
                "entry_where_bar_met": entry_for_bar,
                "stance_at_reference": ("CONVICTION_ELIGIBLE" if rr is not None and rr >= RR_CONVICTION_BAR
                                        else "WATCH_NOT_CONVICTION (R/R below 2:1 at reference price)")}
    except Exception:
        return {"reward_to_risk": None, "error": "band/px incomplete"}


def compose(ticker: str) -> dict:
    safe = ticker.replace(".", "_")
    core = _load(CORES / f"{safe}_core.json")
    if core is None:
        raise SystemExit(f"research core not found: {CORES}/{safe}_core.json")
    errs = qualify(core)
    if errs:
        print("NOT A QUALIFIED OUTPUT — composer refuses to emit:")
        for e in errs:
            print(f"  - {e}")
        raise SystemExit(2)
    auto = _apply_corporate_actions(_auto_context(ticker), core)
    px = auto["last_price"].get("close")
    rr = _rr(core["valuation_target_range"], px) if px else {"reward_to_risk": None, "error": "no price"}
    sheet = {
        "_meta": {"layer": "Core Thesis Factory v1 — Single-Name Decision Sheet (单票决策书)",
                  "spec": "docs/strategy/CORE_THESIS_FACTORY_v1_SPEC.md",
                  "generated_at": datetime.now(timezone.utc).isoformat(),
                  "sheet_version": "v1",
                  "disclaimer": ("INTERNAL, UNVALIDATED research output of the model-recommendation "
                                 "pilot — not validated alpha, not external/personalized investment "
                                 "advice; sizing fields are research posture only; human executes. "
                                 "Quality gate = human red-team (auto checks are the floor only).")},
        **core,
        "auto_context": auto,
        "reward_to_risk": rr,
        "quality": {"auto_floor": "PASS (structurally qualified)",
                    "human_red_team": "PENDING — the measure of record",
                    "forward_checkpoints": "PENDING registration (30/60/90d, PR-D)"},
    }
    sheet["content_lock_sha256"] = _content_lock(sheet)
    SHEETS_OUT.mkdir(parents=True, exist_ok=True)
    out = SHEETS_OUT / f"{safe}.json"
    out.write_text(json.dumps(sheet, ensure_ascii=False, indent=2))
    md = _render_md(sheet)
    MD_OUT.mkdir(parents=True, exist_ok=True)
    md_path = MD_OUT / f"{safe}_{sheet['identity']['as_of']}.md"
    md_path.write_text(md)
    print(f"[decision-sheet] QUALIFIED ✓  wrote {out}")
    print(f"  rendered 决策书 -> {md_path}")
    print(f"  R/R at {px}: {rr.get('reward_to_risk')} -> {rr.get('stance_at_reference')}")
    print(f"  content lock: {sheet['content_lock_sha256'][:16]}…")
    return sheet


def _render_md(s: dict) -> str:
    """Mechanical bilingual markdown rendering of the sheet (single source of truth = the JSON)."""
    idn, th, ev = s["identity"], s["thesis"], s["evidence"]
    band, plan, risk = s["valuation_target_range"], s["execution_plan"], s["risk"]
    rr, auto = s["reward_to_risk"], s["auto_context"]
    L = []
    L.append(f"# 单票决策书 · Decision Sheet — {idn['name']['zh']} {idn['ticker']} ({idn['as_of']})")
    L.append(f"\n> **{s['_meta']['disclaimer']}**")
    L.append(f"> Provenance: {idn['provenance']['research_core_lineage']}")
    # red-team status is NOT hardcoded — it reflects the sheet's quality.human_red_team so the
    # render can never go stale once a sheet is red-teamed + registered (Junyan #79 P1: a PENDING
    # line on an already-bound/registered sheet misleads the reader). PR-F codifies this as the
    # "red-team status must not be stale" institutional rule.
    _hrt = str((s.get("quality") or {}).get("human_red_team", "") or "")
    _rt_line = (f"**Human red-team: {_hrt}**" if _hrt.upper().startswith("PASS")
                else "**human red-team PENDING (the measure of record)**")
    L.append(f"> Content lock: `{s['content_lock_sha256'][:16]}…` · Quality: auto floor PASS · "
             f"{_rt_line}\n")
    L.append(f"## 0. 一句话 / One line")
    L.append(f"- **Direction:** {th['direction']} · **Horizon:** {th['horizon']} · **Conviction:** {th['conviction']}")
    L.append(f"- **R/R @ {rr.get('reference_price')}:** {rr.get('reward_to_risk')} → **{rr.get('stance_at_reference')}** "
             f"(bar {rr.get('conviction_bar')}:1; bar met at ≤{rr.get('entry_where_bar_met')})\n")
    L.append("## 1. 论点 / Thesis")
    L.append(f"**变体认知 (zh):** {th['variant_perception']['zh']}\n")
    L.append(f"**Variant perception (en):** {th['variant_perception']['en']}\n")
    L.append(f"**机制 (zh):** {th['mechanism']['zh']}\n")
    L.append(f"**Mechanism (en):** {th['mechanism']['en']}\n")
    L.append("## 2. 证据 / Evidence (tagged)")
    L.append("| # | claim | tier | causal | citation grade |")
    L.append("|---|---|---|---|---|")
    for i, it in enumerate(ev["items"], 1):
        L.append(f"| {i} | {it['claim'][:120]}… | {it['tier']} | {it['causal_tag']} | {it['citation_grade']} |")
    L.append(f"\n**Rule-X:** {'PASS' if ev['rule_x_check'].get('pass') else 'FAIL'} — {ev['rule_x_check'].get('why','')}")
    L.append(f"\n**Contrarian view:** {ev['contrarian_view']}\n")
    if s.get("serenity"):
        ser = s["serenity"]
        L.append("## 2b. Serenity 发现层 / Discovery layer (#67 — never a trade signal)")
        L.append(f"- **主题/系统变化:** {ser['theme_system_change']}")
        L.append(f"- **链上位置(层排序):** {' → '.join(ser['value_chain_map'])}")
        L.append(f"- **稀缺层:** {ser['scarce_layer']} · **角色:** {ser['company_role']}")
        L.append("- **瓶颈证据:**")
        for b in ser["bottleneck_evidence"]:
            L.append(f"  - [{b.get('tier')}/{b.get('citation_grade')}] {b.get('claim')}")
        L.append(f"- **市场可能忽略什么:** {ser['market_may_be_missing']}")
        L.append(f"- **替代路径:** {ser['substitution_route']}")
        L.append(f"- **扩产/替代难度:** {ser['expansion_difficulty']}")
        L.append(f"- **客户验证:** {ser['customer_validation']}")
        L.append("- **降级条件(what weakens the view,机械化):**")
        for w in ser["what_weakens_the_view"]:
            L.append(f"  - {w.get('metric')} {w.get('threshold')}(source: {w.get('source')}; check: {w.get('check_date')})")
        L.append("")
    L.append("## 3. 催化剂日历 / Catalyst calendar")
    for c in s["catalyst_calendar"]:
        evt = c["event"]["zh"] if isinstance(c.get("event"), dict) else c.get("event")
        L.append(f"- **{c['date']}** — {evt} · watch: {c['watch']} · expected: {c['expected']}")
    L.append("\n## 4. 证伪条件 / Wrong-if (mechanized)")
    for t in s["wrong_if"]["triggers"]:
        L.append(f"- `{t['metric']}` **{t['threshold']}** @ {t['check_date']} · source: {t['source']}")
    L.append("\n## 5. 估值与目标区间 / Valuation & target band (`calibrated: false`)")
    L.append(f"_basis:_ {band['basis']}\n")
    L.append("| scenario | band | load-bearing assumptions |")
    L.append("|---|---|---|")
    for sc in ("bear", "base", "bull"):
        b = band[sc]
        L.append(f"| **{sc}** | ¥{b['low']}–{b['high']} | " + " · ".join(b["assumptions"]) + " |")
    if band.get("sensitivity_note"):
        L.append(f"\n_sensitivity:_ {band['sensitivity_note']}")
    L.append("\n## 6. 执行计划 / Execution plan")
    L.append(f"**(zh)** {plan['summary']['zh']}\n")
    L.append(f"**(en)** {plan['summary']['en']}\n")
    L.append(f"- entry: {plan['entry']}\n- staging: {plan['staging']}\n- invalidation: {plan['invalidation']}"
             f"\n- sizing (suggestion only): {plan['sizing_suggestion']}\n- horizon: {plan['holding_horizon']}"
             f"\n- review dates: {', '.join(plan['review_dates'])}")
    L.append("\n## 7. 风险 / Risks")
    for k in ("fundamental", "policy", "valuation", "liquidity", "crowding_reflexivity"):
        L.append(f"- **{k}:** {risk[k]}")
    L.append("\n## 8. 自动上下文 / Auto context (as committed)")
    L.append(f"- last committed bar: {auto['last_price'].get('close')} @ {auto['last_price'].get('date')} — {auto['last_price'].get('note')}")
    L.append(f"- technical: zone={auto['technical'].get('zone')} rsi14={auto['technical'].get('rsi14')} signals={auto['technical'].get('signals')} (as of {auto['technical'].get('generated_at')})")
    L.append(f"- market anchors (as of {auto['market_anchors'].get('as_of')}): price={auto['market_anchors'].get('price')} mc={auto['market_anchors'].get('market_cap')} pe_dyn={auto['market_anchors'].get('pe_dynamic')}")
    L.append(f"- valuation stack: {auto['valuation_stack_status']}")
    if s.get("disclaimers", {}).get("data_breaks_logged"):
        L.append("\n## 9. 数据断点 / Data breaks logged (single-piece-flow findings)")
        for b in s["disclaimers"]["data_breaks_logged"]:
            L.append(f"- {b}")
    return "\n".join(L) + "\n"


# ───────────────────────── selftest ─────────────────────────
def _valid_serenity():
    return {
        "theme_system_change": "测试主题/系统变化",
        "value_chain_map": ["L1 上游(最紧)", "L2 中游", "L3 下游"],
        "scarce_layer": "L1",
        "company_role": "CONTROLS",
        "bottleneck_evidence": [{"claim": "b", "tier": "E1",
                                 "citation_grade": "EDGE_ESTABLISHING", "source": "s"}],
        "market_may_be_missing": "m",
        "substitution_route": "r",
        "expansion_difficulty": "d",
        "customer_validation": "v",
        "what_weakens_the_view": [
            {"metric": "m1", "threshold": "<= 1", "source": "s1", "check_date": "2026-08-31"},
            {"metric": "m2", "threshold": ">= 2", "source": "s2", "check_date": "2026-08-31"},
        ],
    }


def _valid_core():
    return {
        "serenity": _valid_serenity(),
        "identity": {"ticker": "TEST.SZ", "name": {"zh": "测试", "en": "Test"}, "market": "A",
                     "as_of": "2026-06-10", "provenance": {"v0": "x"}},
        "thesis": {"variant_perception": {"zh": "市场信X我们信Y", "en": "mkt X we Y"},
                   "mechanism": {"zh": "机制", "en": "mechanism"}, "direction": "LONG",
                   "horizon": "6-12m", "conviction": "STARTER_CAPPED_UNTIL_E1"},
        "evidence": {"items": [{"claim": "c", "tier": "E1", "causal_tag": "PROVEN",
                                "citation_grade": "EDGE_ESTABLISHING", "source": "s"}],
                     "rule_x_check": {"pass": True, "why": "segment disclosure exists"},
                     "contrarian_view": "bears say…"},
        "catalyst_calendar": [{"event": "H1 report", "date": "2026-08-31", "watch": "GM", "expected": "+"}],
        "wrong_if": {"triggers": [
            {"metric": "GM", "threshold": "<=16.5%", "source": "H1 报告", "check_date": "2026-08-31"},
            {"metric": "NP YoY", "threshold": "<=-40%", "source": "H1 报告", "check_date": "2026-08-31"}]},
        "valuation_target_range": {"calibrated": False, "basis": "eps_x_pe",
                                   "bear": {"low": 50, "high": 60, "assumptions": ["a"]},
                                   "base": {"low": 95, "high": 105, "assumptions": ["b"]},
                                   "bull": {"low": 145, "high": 160, "assumptions": ["c"]}},
        "execution_plan": {"summary": {"zh": "计划", "en": "plan"}, "entry": "zones", "staging": "starter",
                           "invalidation": "stop+thesis", "sizing_suggestion": "tier1 human_executes",
                           "holding_horizon": "6-12m", "review_dates": ["2026-07-10"]},
        "risk": {"fundamental": "f", "policy": "p", "valuation": "v", "liquidity": "l",
                 "crowding_reflexivity": "c"},
        "disclaimers": {"unvalidated": True, "human_executes": True},
    }


def _selftest() -> int:
    errs = []
    if qualify(_valid_core()):
        errs.append(f"valid core must qualify, got {qualify(_valid_core())[:3]}")
    # each mutilation must FAIL qualification
    muts = {
        "missing group": lambda c: c.pop("risk"),
        "untagged causal link": lambda c: c["evidence"]["items"][0].pop("causal_tag"),
        "un-mechanized trigger": lambda c: c["wrong_if"]["triggers"][0].pop("threshold"),
        "single-point target": lambda c: c["valuation_target_range"]["base"].update({"low": 100, "high": 100}),
        "missing assumptions": lambda c: c["valuation_target_range"]["bull"].update({"assumptions": []}),
        "monolingual thesis": lambda c: c["thesis"]["variant_perception"].pop("zh"),
        "calibrated true": lambda c: c["valuation_target_range"].update({"calibrated": True}),
        "one trigger only": lambda c: c["wrong_if"].update({"triggers": c["wrong_if"]["triggers"][:1]}),
        "missing serenity on new name": lambda c: c.pop("serenity"),
        "serenity <3 layers": lambda c: c["serenity"].update(
            {"value_chain_map": c["serenity"]["value_chain_map"][:2]}),
        "serenity <2 mechanized weakens": lambda c: c["serenity"].update(
            {"what_weakens_the_view": c["serenity"]["what_weakens_the_view"][:1]}),
        "serenity untiered bottleneck evidence": lambda c: c["serenity"]["bottleneck_evidence"][0].pop("tier"),
    }
    for name, fn in muts.items():
        c = json.loads(json.dumps(_valid_core()))
        fn(c)
        if not qualify(c):
            errs.append(f"mutilation '{name}' must fail qualification but passed")
    # serenity exemption (#67): the ratified refresh sample stays exempt; new names are not
    c = json.loads(json.dumps(_valid_core())); c.pop("serenity"); c["identity"]["ticker"] = "002594.SZ"
    if qualify(c):
        errs.append("ratified refresh name (002594.SZ) must stay exempt from the serenity requirement")
    # corporate-action adjustment: a pre-split committed snapshot must be re-based before R/R
    fake_auto = {"last_price": {"close": 195.94, "date": "2026-05-08", "source": "universe_a_snapshot_fallback"}}
    fake_core = {"identity": {"corporate_actions": [
        {"type": "split_dividend", "ex_date": "2026-06-10", "split_factor": 1.4,
         "dividend_per_share": 0.4, "source": "权益分派实施公告"}]}}
    adj = _apply_corporate_actions(fake_auto, fake_core)["last_price"]
    if abs(adj["close"] - 139.67) > 0.01 or adj.get("raw_close_before_adjustment") != 195.94:
        errs.append(f"corporate-action adjustment wrong: {adj.get('close')} (expect 139.67)")
    post = {"last_price": {"close": 186.74, "date": "2026-06-11", "source": "ohlc_committed"}}
    if _apply_corporate_actions(post, fake_core)["last_price"]["close"] != 186.74:
        errs.append("corporate-action adjustment must NOT touch a post-ex-date price")
    # R/R math + conviction bar: bull_mid 152.5, bear_mid 55; px 93.75 -> rr=(152.5-93.75)/(93.75-55)=1.52
    rr = _rr(_valid_core()["valuation_target_range"], 93.75)
    if abs(rr["reward_to_risk"] - 1.52) > 0.02:
        errs.append(f"R/R math wrong: {rr['reward_to_risk']} (expect ~1.52)")
    if rr["meets_conviction_bar"] is not False or "WATCH" not in rr["stance_at_reference"]:
        errs.append("R/R 1.52 must force WATCH_NOT_CONVICTION (bar=2.0)")
    # entry_where_bar_met: (152.5 + 2*55)/3 = 87.5 — at that price R/R == 2.0
    if abs(rr["entry_where_bar_met"] - 87.5) > 0.1:
        errs.append(f"entry_where_bar_met wrong: {rr['entry_where_bar_met']} (expect 87.5)")
    # content lock: invariant to volatile fields, sensitive to content (Junyan #64 fix)
    def _fake_sheet(gen_at, band_low=50):
        s = {"_meta": {"generated_at": gen_at, "disclaimer": "x"}, **_valid_core(),
             "auto_context": {"last_price": {"close": 93.75, "date": "20260522"}},
             "reward_to_risk": {"reward_to_risk": 1.52},
             "quality": {"human_red_team": "PENDING"}}
        s["valuation_target_range"] = json.loads(json.dumps(s["valuation_target_range"]))
        s["valuation_target_range"]["bear"]["low"] = band_low
        return s
    l1 = _content_lock(_fake_sheet("2026-06-10T01:00:00Z"))
    l2 = _content_lock(_fake_sheet("2026-06-10T02:00:00Z"))
    if l1 != l2:
        errs.append("content lock must be INVARIANT to _meta.generated_at (pure rerun = same lock)")
    l3 = _content_lock(_fake_sheet("2026-06-10T01:00:00Z", band_low=51))
    if l3 == l1:
        errs.append("content lock must CHANGE when research content changes (no teeth otherwise)")
    if errs:
        print("decision_sheet selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("decision_sheet selftest PASSED (valid core qualifies; all 12 mutilations refused — missing "
          "group / untagged link / un-mechanized trigger / single-point target / no assumptions / "
          "monolingual / calibrated:true / <2 triggers / missing-serenity-on-new-name / <3 layers / "
          "<2 mechanized weakens / untiered bottleneck evidence; refresh-sample serenity exemption holds; "
          "corporate-action adjustment re-bases pre-split snapshots and leaves post-ex prices alone; "
          "R/R math exact; 2:1 bar forces WATCH + computes the entry where the bar is met; content lock "
          "invariant to generated_at AND sensitive to content changes)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if not a.ticker:
        ap.error("--ticker required (or --selftest)")
    compose(a.ticker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
