#!/usr/bin/env python3
"""
scripts/persona_overlay.py — AHF-3 v1: deterministic investor-persona checklists.

PURPOSE
=======
Compute named-investor framework checklists per watchlist ticker as a
cross-check on the VP composite. Each persona is a deterministic rule-based
score against existing data — NO LLM calls, NO theater. The framework value
lives in the SPECIFIC named criteria that force structured evaluation
(e.g., Buffett's "ROE > 15%" forces explicit quality check, regardless of
whether VP says BULLISH).

PROVENANCE
==========
AHF_COMPARISON.md Tier 1 A3 ("Investor-persona perspective overlay").
A1 (fragility) shipped via fragility_score.py + KR2 visual surfacing.
A2 (multi-method valuation) deferred (biotech blind spot, larger scope).
This script implements A3 v1: deterministic checklists only. LLM-prose
layer (api/research.js enhancement) deferred to a future KR pending
deterministic-foundation validation.

INPUTS (graceful degradation if missing — typed error code)
==========
- public/data/market_data.json    yfinance fundamentals (PE, P/B, ROE, D/E,
                                  EV/EBITDA, FCF, margins, current_ratio)
- public/data/rdcf_<safe_id>.json our_growth, implied_growth, delta, wacc
- public/data/fin_<safe_id>.json  balance sheet (for net cash calculation)
- public/data/watchlist.json      ticker enumeration (SOT)

OUTPUT
==========
public/data/persona_overlay.json (single file, atomic update)

Schema:
{
  "_meta": {"generated_at": "...", "schema_version": 1,
            "thresholds_status": "[unvalidated intuition]"},
  "personas": {
    "<ticker>": {
      "buffett":   {"score": int, "max": 6, "criteria": [...],
                    "verdict_e": "...", "verdict_z": "..."},
      "burry":     {"score": int, "max": 4, "criteria": [...],
                    "verdict_e": "...", "verdict_z": "..."},
      "damodaran": {"score": int, "max": 3, "criteria": [...],
                    "verdict_e": "...", "verdict_z": "..."}
    },
    ...
  }
}

Per-criterion shape (auditable — actuals + thresholds visible):
  {"name": "ROE > 15%", "actual": 0.539, "threshold": 0.15,
   "comparator": ">", "passed": true}

On graceful-degradation:
  "personas": {"<ticker>": {"error": "rdcf_missing", "scores": null}}

PERSONA SELECTION (3 of 14 from virattt/ai-hedge-fund — deliberately sparse)
==========
- Buffett   (Quality axis)         — covered
- Burry     (Deep-value axis)      — covered
- Damodaran (Story-vs-Numbers axis)— covered
- Taleb     (Tail-risk axis)       — covered separately by AHF-1 fragility
- Lynch:    skipped (overlaps catalyst_prox)
- Munger:   skipped (overlaps Buffett)
- Pabrai:   skipped (overlaps Burry+risk)
- Druckenmiller: skipped (needs macro data we don't have)
- Fisher:   skipped (scuttlebutt — qualitative, not deterministically scoreable)

THRESHOLD RATIONALE [unvalidated intuition]
==========
**Buffett ROE > 15%** — top-quartile filter for A/HK universes. HSI long-run
ROE average ~10-12%; CSI 300 average ~10-11%. 15% bar puts the filter at
quality regime, not mediocrity. Lowering to 12% would let mid-quality
names slip through; raising to 20% would knock out genuine quality.

**Buffett D/E < 50** — note yfinance reports D/E in PERCENT units (e.g., 32.75
means 32.75%, not 0.3275). Threshold value is 50.0 (= D/E ratio of 0.5).
Buffett rule "D/E < 0.5" is the standard "low leverage" filter.

**Burry P/B < 1.5** — Burry-circa-2008 deep-value framing. NOT current Burry
trading style (which has shifted to growth-shorts + macro). Used here as
cross-check FRAMEWORK, NOT to mimic Burry's contemporary trades. The
deep-value lens is informative as a counterweight to growth-priced
holdings — if our entire portfolio fails Burry, that's signal we're
systematically growth-tilted (not noise).

**Damodaran ±5% gap** — TIGHTER than rdcf's ±10% piecewise mapping band.
Coherence rationale: rdcf treats ±10% as 'moderate gap' for continuous
scoring (expectation_gap score 35-55); Damodaran's framework uses ±5% as
binary 'story-numbers consistent vs not'. Both correct cuts of the same
data — different lenses. The Damodaran check fires HARDER than rdcf's
expectation_gap because it asks "is your DCF input fundamentally
consistent with market price?" which is a stricter sanity check than
"is there a meaningful gap to trade?"

NOT FOLDED INTO VP COMPOSITE — INVARIANT 3 forbids changing VP weights
without Junyan approval. Persona scores are reported as a SEPARATE output
file. Read alongside VP composite for richer perspective.

Author: Night-shift run 2026-04-30-1532 KR3
"""

from __future__ import annotations
import json
import pathlib
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"


# ─────────────────────────────────────────────────────────────────────────
# Helpers — SOT, JSON load, comparator evaluation
# ─────────────────────────────────────────────────────────────────────────

def _load_json(name: str, default: Any = None) -> Any:
    p = DATA / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_watchlist_tickers() -> list[str]:
    """Single source of truth — never hardcode tickers."""
    wl = _load_json("watchlist.json", {})
    return list(wl.get("tickers", {}).keys())


def _safe_id(ticker: str) -> str:
    return ticker.replace(".", "_")


def _eval_comparator(actual, threshold, comparator: str) -> bool | None:
    """Returns True/False/None. None = cannot evaluate (actual is None)."""
    if actual is None:
        return None
    try:
        if comparator == ">":
            return actual > threshold
        if comparator == ">=":
            return actual >= threshold
        if comparator == "<":
            return actual < threshold
        if comparator == "<=":
            return actual <= threshold
        if comparator == "in":
            lo, hi = threshold
            return lo <= actual <= hi
    except Exception:
        return None
    return None


def _criterion(name: str, actual, threshold, comparator: str) -> dict:
    """Build a per-criterion dict with auditable {actual, threshold, passed}."""
    passed = _eval_comparator(actual, threshold, comparator)
    return {
        "name":       name,
        "actual":     actual,                    # raw value (or None if missing)
        "threshold":  threshold,                 # scalar or [lo, hi] for "in"
        "comparator": comparator,
        "passed":     passed,                    # True / False / None
    }


def _summarize(criteria: list[dict], max_score: int,
               verdict_e: str, verdict_z: str) -> dict:
    """Convert criteria list → persona dict with score/max/verdicts."""
    score = sum(1 for c in criteria if c["passed"] is True)
    return {
        "score":     score,
        "max":       max_score,
        "criteria":  criteria,
        "verdict_e": verdict_e,
        "verdict_z": verdict_z,
    }


# ─────────────────────────────────────────────────────────────────────────
# Derived metrics — FCF yield, net cash ratio, |delta|
# ─────────────────────────────────────────────────────────────────────────

def _fcf_yield(fund: dict, mcap: float | None) -> float | None:
    """FCF / market_cap. Returns None if either missing."""
    fcf = fund.get("free_cash_flow")
    if fcf is None or mcap is None or mcap <= 0:
        return None
    return fcf / mcap


def _net_cash(fin: dict) -> float | None:
    """Most-recent-year cash + short-term investments - total debt.

    Reads fin_<safe_id>.json balance_sheet. Returns None if no balance
    sheet data available (typed error caught upstream).
    """
    bs_dict = (fin or {}).get("balance_sheet") or {}
    if not bs_dict:
        return None
    # latest year (max date string)
    try:
        latest = max(bs_dict.keys())
    except Exception:
        return None
    bs = bs_dict[latest] or {}
    cash = bs.get("Cash And Cash Equivalents")
    sti  = bs.get("Other Short Term Investments") or 0.0
    debt = bs.get("Total Debt")
    if cash is None or debt is None:
        return None
    return float(cash) + float(sti) - float(debt)


# ─────────────────────────────────────────────────────────────────────────
# Persona checklists
# ─────────────────────────────────────────────────────────────────────────

def buffett_checklist(fund: dict, mcap: float | None) -> dict:
    """6 criteria — quality + reasonable price.

    NOTE: yfinance reports debt_to_equity in PERCENT units. Threshold 50.0
    means D/E ratio of 0.5 (Buffett's classic low-leverage rule).
    """
    fcfy = _fcf_yield(fund, mcap)
    criteria = [
        _criterion("ROE > 15%",            fund.get("roe"),              0.15, ">"),
        _criterion("Operating margin > 15%", fund.get("operating_margin"), 0.15, ">"),
        _criterion("D/E < 50% (≈ ratio 0.5)", fund.get("debt_to_equity"), 50.0, "<"),
        _criterion("FCF yield > 4%",       fcfy,                          0.04, ">"),
        _criterion("Trailing P/E < 20",    fund.get("pe_trailing"),       20.0, "<"),
        _criterion("Current ratio > 1.5",  fund.get("current_ratio"),     1.5,  ">"),
    ]
    score = sum(1 for c in criteria if c["passed"] is True)
    if score >= 5:
        ve, vz = ("Buffett-style quality across the board.",
                  "巴菲特式高质量全面达标。")
    elif score >= 3:
        ve, vz = ("Mixed quality — passes most ratios, fails a value test.",
                  "质量参差——多数指标达标，估值类未通过。")
    elif score >= 1:
        ve, vz = ("Weak Buffett fit — quality concerns or expensive.",
                  "巴菲特维度偏弱——质量或估值受限。")
    else:
        ve, vz = ("Not a Buffett name on these criteria.",
                  "按此清单非巴菲特类标的。")
    return _summarize(criteria, 6, ve, vz)


def burry_checklist(fund: dict, mcap: float | None, fin: dict) -> dict:
    """4 criteria — deep value + balance-sheet optionality.

    Burry-circa-2008 deep-value framing — see module docstring for why this
    is NOT current Burry trading style.
    """
    fcfy = _fcf_yield(fund, mcap)
    nc = _net_cash(fin)
    nc_ratio = (nc / mcap) if (nc is not None and mcap and mcap > 0) else None
    criteria = [
        _criterion("P/B < 1.5",                 fund.get("pb"),       1.5,  "<"),
        _criterion("FCF yield > 8%",            fcfy,                 0.08, ">"),
        _criterion("EV/EBITDA < 10",            fund.get("ev_ebitda"),10.0, "<"),
        _criterion("Net cash > 20% of mkt cap", nc_ratio,             0.20, ">"),
    ]
    score = sum(1 for c in criteria if c["passed"] is True)
    if score >= 3:
        ve, vz = ("Burry-style deep-value setup present.",
                  "符合伯里式深度价值条件。")
    elif score == 2:
        ve, vz = ("Partial deep-value attributes.",
                  "部分价值属性。")
    elif score == 1:
        ve, vz = ("Mostly growth-priced; one value indicator only.",
                  "整体成长定价；仅一项价值指标通过。")
    else:
        ve, vz = ("Growth-priced; not a deep-value candidate.",
                  "成长定价——非深度价值候选。")
    return _summarize(criteria, 4, ve, vz)


def damodaran_checklist(rdcf: dict) -> dict:
    """3 criteria — DCF model sanity (story-vs-numbers consistency).

    The ±5% gap criterion is intentionally TIGHTER than rdcf's ±10%
    piecewise mapping. See module docstring for coherence rationale.

    For biotech_revenue rdcf model, our_growth comes from `our_rev_growth`
    rather than `our_fcf_growth`.
    """
    delta = rdcf.get("delta")
    abs_delta = abs(delta) if delta is not None else None

    wacc = (rdcf.get("wacc_detail") or {}).get("wacc")

    # support both standard (our_fcf_growth) and biotech (our_rev_growth)
    our_growth = rdcf.get("our_fcf_growth")
    if our_growth is None:
        our_growth = rdcf.get("our_rev_growth")

    criteria = [
        _criterion("|implied vs our growth gap| < ±5%", abs_delta, 0.05,         "<"),
        _criterion("WACC in [8%, 15%]",                  wacc,      [0.08, 0.15], "in"),
        _criterion("Our growth < 25% (terminal sanity)", our_growth,0.25,         "<"),
    ]
    score = sum(1 for c in criteria if c["passed"] is True)
    if score == 3:
        ve, vz = ("rdcf inputs internally consistent.",
                  "rdcf 输入内部一致。")
    elif score == 2:
        ve, vz = ("Two checks pass — minor inconsistency in remaining.",
                  "两项达标——剩余项存小幅不一致。")
    elif score == 1:
        ve, vz = ("Single sanity check — large gap or unusual assumption.",
                  "仅一项达标——存在显著差距或非常规假设。")
    else:
        ve, vz = ("Aggressive thesis: our_growth diverges from market price meaningfully.",
                  "激进假设：我们的增长预期与市场价格意义性背离。")
    return _summarize(criteria, 3, ve, vz)


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def compute_persona_for_ticker(
    ticker: str, market_data: dict
) -> dict:
    """Return per-ticker persona block, or {error, scores: None} if degraded."""
    yahoo = ((market_data or {}).get("yahoo") or {}).get(ticker) or {}
    fund = yahoo.get("fundamentals") or {}
    if not fund:
        return {"error": "fundamentals_missing", "scores": None}

    mcap = fund.get("market_cap")

    rdcf = _load_json(f"rdcf_{_safe_id(ticker)}.json")
    if not rdcf:
        return {"error": "rdcf_missing", "scores": None}

    fin = _load_json(f"fin_{_safe_id(ticker)}.json", {}) or {}
    # fin may be empty — Burry's net-cash criterion will degrade to None
    # (criterion.passed=None) without crashing the persona.

    return {
        "buffett":   buffett_checklist(fund, mcap),
        "burry":     burry_checklist(fund, mcap, fin),
        "damodaran": damodaran_checklist(rdcf),
    }


def main() -> int:
    print("[persona_overlay] AHF-3 v1 — deterministic persona checklists per watchlist ticker...")
    tickers = _load_watchlist_tickers()
    if not tickers:
        print("[persona_overlay] No watchlist tickers; exiting.")
        return 0

    market_data = _load_json("market_data.json", {}) or {}
    if not market_data:
        # global fallback — write an empty-but-well-formed output so
        # verify_outputs.py can still run
        print("[persona_overlay] WARN: market_data.json missing; writing empty output.")
        market_data = {}

    personas = {}
    for t in tickers:
        block = compute_persona_for_ticker(t, market_data)
        if "error" in block:
            print(f"  {t:<12}: degraded ({block['error']})")
        else:
            b = block["buffett"]["score"]
            r = block["burry"]["score"]
            d = block["damodaran"]["score"]
            print(f"  {t:<12}: Buffett={b}/6  Burry={r}/4  Damodaran={d}/3")
        personas[t] = block

    out = {
        "_meta": {
            "generated_at":      datetime.now(timezone.utc).isoformat(),
            "schema_version":    1,
            "thresholds_status": "[unvalidated intuition]",
            "personas_included": ["buffett", "burry", "damodaran"],
            "note": (
                "Deterministic persona checklists from named investor frameworks. "
                "NOT folded into VP composite (INVARIANT 3). "
                "Read alongside VP for richer perspective."
            ),
        },
        "personas": personas,
    }
    DATA.joinpath("persona_overlay.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[persona_overlay] Done. Wrote {len(personas)} ticker entries to persona_overlay.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
