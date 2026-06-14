#!/usr/bin/env python3
"""deep_thesis_prepare.py — PR-G extractor + AI beta forward screen.

This is the first engineering step after DEEP_THESIS_FACTORY_v0_SPEC.md:

1. Build a deterministic, committed-data price/valuation snapshot for any
   ticker that will enter a deep-thesis or beta-forward-validation pack.
2. Refuse stale snapshots instead of letting LLM prose paper over old prices.
3. Golden-regress against the two hand-verified deep theses (688008/688072).
4. Produce an AI-infrastructure beta candidate pack from the current universe
   snapshot. This is a research/forward-validation list, NOT a buy list.

The script deliberately uses committed data first. A later PR may add an
explicit dated live-quote second source, but it must be labeled as such.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
REPORT_DIR = REPO / "docs" / "research" / "decision_sheets"

MAX_COMMITTED_PRICE_AGE_DAYS = 4


@dataclass(frozen=True)
class CandidateSeed:
    ticker: str
    layer: str
    role: str
    thesis_points: tuple[str, str, str]
    catalysts: tuple[str, ...]
    risks: tuple[str, ...]
    target_low_mult: float
    target_high_mult: float
    bear_low_mult: float
    bear_high_mult: float
    crowding: str
    evidence_status: str


AI_CANDIDATES: tuple[CandidateSeed, ...] = (
    CandidateSeed(
        "300308.SZ", "AI optical interconnect", "800G/1.6T optical module leader",
        (
            "AI cluster bottleneck shifts from compute-only to high-speed interconnect; optical modules remain one of the most direct data-center capex pass-through layers.",
            "中际 has scale, customer qualification, and cycle leverage, but the stock is already treated as a consensus AI winner.",
            "The investable question is no longer 'is it a good AI asset' but whether 1.6T ramp and margin can exceed crowded expectations.",
        ),
        ("NVDA/ASIC rack shipment mix", "1.6T order/ramp disclosures", "quarterly GM and overseas customer concentration"),
        ("hyperscaler capex pause", "single-product/single-customer crowding", "valuation compression if 1.6T becomes consensus not surprise"),
        0.95, 1.15, 0.55, 0.70, "extreme", "existing watchlist + committed market snapshot",
    ),
    CandidateSeed(
        "000988.SZ", "AI optical / industrial laser", "optical-device and laser equipment supplier",
        (
            "华工 is a less extreme optical-chain exposure than pure optical-module winners, with a broader laser/equipment base.",
            "Current valuation is materially less demanding than the most crowded optical names while still linked to AI interconnect spend.",
            "The key variant is whether optical-device exposure can offset cyclicality in legacy laser/equipment businesses.",
        ),
        ("AI optical component demand", "laser/equipment margin trend", "semiannual segment disclosure"),
        ("legacy business drag", "AI exposure overstated vs optical-module peers", "margin dilution from mix"),
        1.10, 1.35, 0.70, 0.82, "medium", "committed market snapshot; needs E1 segment check",
    ),
    CandidateSeed(
        "002281.SZ", "AI optical components", "optical-device supplier",
        (
            "光迅 offers upstream optical-device exposure, which could benefit if bottleneck rents move from module assembly to devices.",
            "The role is strategically relevant, but current PE is high and the market already recognizes optical upside.",
            "The thesis needs proof that device-level scarcity, not just module beta, is accruing to the company.",
        ),
        ("device ASP/margin disclosure", "AI optical device capacity announcements", "semiannual order commentary"),
        ("valuation already prices scarcity", "margin fails to expand", "lower bargaining power than module primes"),
        0.95, 1.20, 0.55, 0.70, "high", "committed market snapshot; source appendix pending",
    ),
    CandidateSeed(
        "603083.SH", "AI optical interconnect", "optical transceiver/high-speed module beta",
        (
            "剑桥 is a high-beta optical-chain candidate with strong price momentum, useful as a sentiment and execution stress test.",
            "The investable edge is weak unless fresh evidence proves real 800G/1.6T share gain rather than theme beta.",
            "Its main value for the beta list is to show the model can separate momentum from evidence quality.",
        ),
        ("customer/order evidence", "gross margin after ramp", "AI optical news flow"),
        ("momentum reversal", "theme-beta without issuer confirmation", "PE multiple compression"),
        0.85, 1.10, 0.45, 0.62, "extreme", "committed market snapshot; high-risk theme beta",
    ),
    CandidateSeed(
        "688498.SH", "AI optical upstream", "laser/optical chip exposure",
        (
            "源杰 is closer to the upstream optical scarcity story, but its valuation embeds a large scarcity premium.",
            "If AI optical bottlenecks migrate upstream to lasers/devices, this layer has theoretical operating leverage.",
            "The hurdle is proving revenue/margin capture with primary disclosures rather than riding the optical basket.",
        ),
        ("laser/device capacity proof", "customer qualification disclosure", "quarterly margin acceleration"),
        ("very high PE/PB", "small-cap liquidity/capacity risk", "scarcity premium reverses"),
        0.90, 1.20, 0.45, 0.62, "extreme", "committed market snapshot; needs deep E1 proof",
    ),
    CandidateSeed(
        "688008.SH", "AI memory/interconnect", "DDR5/MRCD/Retimer interface chip",
        (
            "澜起 has one of the cleanest AI-server second-curve disclosures: new products increased from 11.9% to 19% of interconnect revenue.",
            "The Retimer/MRCD mechanism is real, but FY26 upside is already near bull-case pricing at the committed snapshot.",
            "The thesis is high quality but presently price-gated: it remains a WATCH until the entry math improves or H1 print raises the band.",
        ),
        ("2026 H1 product-mix print", "Retimer/MRCD revenue share", "gross margin resilience"),
        ("Q1 profit boosted by non-operating gain", "sell-side FY26 revenue too aggressive", "price remains above base/bull risk-adjusted band"),
        0.98, 1.13, 0.42, 0.50, "high", "full deep thesis registered; committed price snapshot",
    ),
    CandidateSeed(
        "688041.SH", "AI compute silicon", "domestic CPU/GPU/data-center processor exposure",
        (
            "海光 is a core domestic compute-sovereignty exposure, relevant to AI infrastructure even if its bottleneck status is less direct than interconnect/equipment.",
            "The market prices strategic scarcity heavily; PE and market cap imply a large future-profit bridge already.",
            "It belongs in the forward pack as a high-quality strategic watch, not as an entry candidate without a valuation reset.",
        ),
        ("server CPU/DCU shipment evidence", "国产算力政策 orders", "gross margin and inventory trend"),
        ("policy beta already capitalized", "sanction/supply-chain limits", "valuation de-rating"),
        0.95, 1.20, 0.50, 0.66, "high", "committed market snapshot; needs E1 financial bridge",
    ),
    CandidateSeed(
        "688256.SH", "AI accelerator", "domestic AI chip pure play",
        (
            "寒武纪 is the purest AI-chip beta in A shares, but purity is not the same as investability.",
            "For the model, it is a crowding/discipline test: if the stock is non-bottleneck or too expensive, it should not advance just because the theme is hot.",
            "It can remain in the pack as a NOT_ADVANCED reference unless primary evidence shows revenue quality catching up to valuation.",
        ),
        ("AI chip order conversion", "customer concentration disclosure", "profit quality and cash burn"),
        ("extreme crowding", "valuation disconnected from realized earnings", "policy/competition risk"),
        0.85, 1.10, 0.35, 0.55, "extreme", "committed market snapshot; downgrade control",
    ),
    CandidateSeed(
        "688072.SH", "AI semiconductor equipment", "thin-film deposition / hybrid bonding option",
        (
            "拓荆 has genuine semi-equipment bottleneck exposure, but the deep thesis showed Q1 reported profit was dominated by investment gains.",
            "The second curve in hybrid bonding is strategically important but still an option, not current earnings.",
            "At the committed price the stock is above the bull-case band; it is a high-quality WATCH, not a starter.",
        ),
        ("2026 H1 clean profit/cash flow", "contract liabilities conversion", "hybrid bonding shipment validation"),
        ("reported profit quality", "order-to-revenue delay", "valuation above bull case"),
        0.90, 1.03, 0.35, 0.42, "high", "full deep thesis registered; committed price snapshot",
    ),
    CandidateSeed(
        "688120.SH", "AI semiconductor equipment", "CMP equipment / advanced packaging supply chain",
        (
            "华海 has direct equipment scarcity exposure and a registered thesis, but the post-scan price rally damaged R/R.",
            "The variant is whether process equipment demand can beat conservative H1 assumptions without requiring heroic multiples.",
            "It stays on the forward list because the evidence quality is strong; entry requires price discipline or a higher E1 band.",
        ),
        ("H1 order/revenue conversion", "CMP equipment gross margin", "advanced packaging customer validation"),
        ("rally already paid for thesis", "order digestion lag", "domestic equipment basket de-rating"),
        0.98, 1.18, 0.55, 0.68, "high", "registered deep thesis + committed data",
    ),
    CandidateSeed(
        "688012.SH", "AI semiconductor equipment", "etch/MOCVD equipment platform",
        (
            "中微 is one of the highest-quality semiconductor equipment platforms, but quality is widely recognized.",
            "The thesis requires an information edge: either an underappreciated product line or a segment margin surprise.",
            "Without that edge it is a benchmark-quality WATCH, useful for comparing equipment names rather than a standalone starter.",
        ),
        ("new tool acceptance", "etch/MOCVD order growth", "institutional crowding change"),
        ("no defensible variant", "already crowded by institutions", "multiple compression"),
        1.02, 1.22, 0.60, 0.75, "high", "committed market snapshot; quick-screen evidence only",
    ),
    CandidateSeed(
        "688019.SH", "AI semiconductor materials", "CMP slurry / materials localization",
        (
            "安集 sits in a materials layer where localization and process qualification can create sticky revenue.",
            "Valuation is less extreme than many AI-semiconductor names, but the quick screen flagged margin pressure in polishing liquid.",
            "It is a candidate for deeper work because it may offer a better thesis/price balance than headline equipment names.",
        ),
        ("polishing liquid margin trend", "customer qualification progress", "new material revenue mix"),
        ("margin pressure persists", "localization already priced", "customer concentration"),
        1.10, 1.35, 0.70, 0.82, "medium", "committed market snapshot; needs deep thesis",
    ),
    CandidateSeed(
        "300054.SZ", "AI advanced materials", "CMP pad / HBM-related materials",
        (
            "鼎龙 has one of the strongest registered evidence packs: CMP pad revenue and gross margin already print in E1 data.",
            "The issue is price: after the run-up, current R/R is weak despite strong fundamentals.",
            "It remains an important forward-validation name because upcoming forecasts can test whether E1 growth is durable.",
        ),
        ("创业板半年度预告", "CMP pad gross margin", "new-material revenue mix"),
        ("current price paid for FY26 consensus", "margin mean reversion", "theme crowding"),
        0.95, 1.15, 0.55, 0.70, "high", "registered deep thesis + committed data",
    ),
    CandidateSeed(
        "600584.SH", "AI advanced packaging", "OSAT / 2.5D packaging exposure",
        (
            "长电 is the listed OSAT proxy for advanced packaging, but key bottleneck economics may sit in subsidiaries or unlisted entities.",
            "The thesis is not 'AI packaging good'; it is whether public shareholders capture the 2.5D/CoWoS-style value chain.",
            "It deserves watch status because the role is relevant but attribution is muddy.",
        ),
        ("advanced packaging capex/revenue disclosure", "subsidiary economics", "H1 gross margin"),
        ("value captured outside listed parent", "cycle downturn in legacy packaging", "sell-side target disagreement"),
        1.00, 1.25, 0.60, 0.78, "medium", "committed market snapshot; source appendix needed",
    ),
    CandidateSeed(
        "002916.SZ", "AI PCB / substrate", "high-speed PCB for servers/networking",
        (
            "深南 is a high-quality PCB name exposed to AI servers and high-speed networking, with less narrative heat than optical pure plays.",
            "The investable question is whether AI PCB mix can offset cyclic telecom/consumer pockets at a reasonable multiple.",
            "It is a useful beta-pack candidate because it broadens the AI stack beyond semicap and optical.",
        ),
        ("AI server PCB mix", "gross margin by segment", "networking/customer capex trend"),
        ("AI mix not separately disclosed", "valuation already anticipates recovery", "telecom/consumer cyclic drag"),
        1.08, 1.32, 0.68, 0.82, "medium", "committed market snapshot; needs E1 mix proof",
    ),
    CandidateSeed(
        "600845.SH", "AI industrial software / IDC ops", "industrial software and data infrastructure",
        (
            "宝信 is a lower-valuation AI-adjacent infrastructure candidate: software/data-center operations rather than headline chips.",
            "Its role is less explosive but potentially more valuation-disciplined, which is exactly what the current AI-semi pool lacks.",
            "This is one of the better candidates for deeper work if the goal is good thesis plus good price, not theme purity.",
        ),
        ("IDC/software revenue mix", "Baowu digitalization demand", "cash-flow and margin trend"),
        ("AI linkage too indirect", "steel-cycle parent exposure", "low growth multiple trap"),
        1.15, 1.45, 0.78, 0.90, "low", "committed market snapshot; needs deep thesis",
    ),
    CandidateSeed(
        "002335.SZ", "AI data-center power", "UPS / power infrastructure for data centers",
        (
            "科华 is an AI-adjacent power-infrastructure candidate, a different bottleneck from chips and optical modules.",
            "If data-center capex shifts attention to power reliability and backup systems, this layer can benefit with less semiconductor crowding.",
            "The thesis needs proof of AI/data-center revenue mix; otherwise it is just a generic power-equipment story.",
        ),
        ("data-center power order disclosure", "margin by power segment", "new IDC/customer wins"),
        ("AI link unproven", "competition in UPS/power systems", "working-capital stress"),
        1.12, 1.38, 0.70, 0.85, "medium", "committed market snapshot; needs E1 mix proof",
    ),
)


def _load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _parse_snapshot_date(raw: str | None) -> date | None:
    if not raw:
        return None
    raw = str(raw)[:10]
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw.replace("-", "") if fmt == "%Y%m%d" else raw, fmt).date()
        except ValueError:
            pass
    return None


def _age_days(snapshot_date: date | None, today: date | None = None) -> int | None:
    if snapshot_date is None:
        return None
    today = today or datetime.now(timezone.utc).date()
    return (today - snapshot_date).days


def _universe() -> dict[str, dict[str, Any]]:
    uni = _load(D / "universe_a.json", {}) or {}
    return {s.get("ticker"): s for s in uni.get("stocks", []) if s.get("ticker")}


def _universe_meta() -> dict[str, Any]:
    return (_load(D / "universe_a.json", {}) or {}).get("_meta", {}) or {}


def price_snapshot(ticker: str, strict: bool = True) -> dict[str, Any]:
    safe = ticker.replace(".", "_")
    ohlc = _load(D / f"ohlc_{safe}.json", {}) or {}
    bars = ohlc.get("data") or []
    if bars:
        last = bars[-1]
        raw_date = last.get("date")
        snap = {
            "ticker": ticker,
            "price": last.get("close"),
            "date": raw_date,
            "source": f"public/data/ohlc_{safe}.json",
        }
    else:
        row = _universe().get(ticker)
        meta = _universe_meta()
        if not row:
            raise SystemExit(f"no committed price source for {ticker}")
        snap = {
            "ticker": ticker,
            "price": row.get("price"),
            "date": (meta.get("fetched_at") or "")[:10],
            "source": "public/data/universe_a.json",
        }
    d = _parse_snapshot_date(snap.get("date"))
    snap["age_days"] = _age_days(d)
    snap["freshness_gate"] = (
        "PASS" if snap["age_days"] is not None and snap["age_days"] <= MAX_COMMITTED_PRICE_AGE_DAYS
        else "FAIL_STALE_OR_UNDATED"
    )
    if strict and snap["freshness_gate"] != "PASS":
        raise SystemExit(f"stale/undated price for {ticker}: {snap}")
    return snap


def market_snapshot(ticker: str) -> dict[str, Any]:
    row = _universe().get(ticker, {})
    snap = price_snapshot(ticker)
    return {
        **snap,
        "name": row.get("name"),
        "pe": row.get("pe"),
        "pb": row.get("pb"),
        "market_cap": row.get("market_cap"),
        "float_cap": row.get("float_cap"),
        "change_pct": row.get("change_pct"),
        "turnover": row.get("turnover"),
        "turnover_rate": row.get("turnover_rate"),
        "alpha_score": row.get("alpha_score"),
        "factors": row.get("factors"),
    }


def _target_band(seed: CandidateSeed, px: float) -> dict[str, Any]:
    target_low = round(px * seed.target_low_mult, 2)
    target_high = round(px * seed.target_high_mult, 2)
    bear_low = round(px * seed.bear_low_mult, 2)
    bear_high = round(px * seed.bear_high_mult, 2)
    bull_mid = (target_low + target_high) / 2.0
    bear_mid = (bear_low + bear_high) / 2.0
    entry_2to1 = round((bull_mid + 2 * bear_mid) / 3.0, 2)
    rr = round((bull_mid - px) / (px - bear_mid), 2) if px > bear_mid else None
    return {
        "bear": [bear_low, bear_high],
        "research_target": [target_low, target_high],
        "reward_to_risk_at_snapshot": rr,
        "starter_review_price_2to1": entry_2to1,
        "valuation_basis": "heuristic beta-pack band from current committed price; NOT calibrated, must be replaced by a deep earnings bridge before registration",
    }


def _stance(seed: CandidateSeed, row: dict[str, Any], band: dict[str, Any]) -> str:
    if "registered" in seed.evidence_status:
        return "WATCH_ONLY_REGISTERED"
    pe = row.get("pe")
    pb = row.get("pb")
    rr = band.get("reward_to_risk_at_snapshot")
    if seed.crowding == "extreme" and (pe is None or pe > 120 or (pb or 0) > 30):
        return "NOT_ADVANCED_PRICE_OR_CROWDING"
    if rr is not None and rr >= 2 and seed.crowding in {"low", "medium"}:
        return "STARTER_REVIEW_PENDING_DEEP_THESIS"
    return "WATCH_ONLY_PENDING_DEEP_THESIS"


def build_ai_screen(limit: int = 15) -> dict[str, Any]:
    rows = []
    for seed in AI_CANDIDATES:
        snap = market_snapshot(seed.ticker)
        if snap.get("price") is None:
            continue
        band = _target_band(seed, float(snap["price"]))
        valuation_score = 0
        pe = snap.get("pe")
        pb = snap.get("pb")
        if pe is not None and pe > 0:
            valuation_score += max(0, 35 - min(35, pe / 5))
        if pb is not None and pb > 0:
            valuation_score += max(0, 15 - min(15, pb / 3))
        layer_score = {
            "AI optical interconnect": 25,
            "AI optical / industrial laser": 19,
            "AI optical components": 18,
            "AI optical upstream": 20,
            "AI memory/interconnect": 24,
            "AI compute silicon": 18,
            "AI accelerator": 12,
            "AI semiconductor equipment": 23,
            "AI semiconductor materials": 22,
            "AI advanced materials": 22,
            "AI advanced packaging": 19,
            "AI PCB / substrate": 18,
            "AI industrial software / IDC ops": 17,
            "AI data-center power": 17,
        }.get(seed.layer, 15)
        crowding_penalty = {"low": 0, "medium": 4, "high": 9, "extreme": 16}[seed.crowding]
        quant_score = round(layer_score + valuation_score - crowding_penalty + (snap.get("alpha_score") or 0) * 0.15, 1)
        rows.append({
            "ticker": seed.ticker,
            "name": snap.get("name"),
            "layer": seed.layer,
            "role": seed.role,
            "price_snapshot": {k: snap.get(k) for k in ("price", "date", "source", "age_days", "freshness_gate")},
            "market": {k: snap.get(k) for k in ("pe", "pb", "market_cap", "change_pct", "turnover_rate", "alpha_score", "factors")},
            "thesis_points": list(seed.thesis_points),
            "catalysts": list(seed.catalysts),
            "risks": list(seed.risks),
            "valuation": band,
            "suggested_entry_framework": {
                "not_an_order": True,
                "starter_review_trigger": band["starter_review_price_2to1"],
                "condition": "only after full deep thesis + fresh price reconciliation + no wrong_if; human executes",
            },
            "crowding": seed.crowding,
            "evidence_status": seed.evidence_status,
            "quant_research_score": quant_score,
            "stance": _stance(seed, snap, band),
        })
    rows.sort(key=lambda r: (r["stance"].startswith("STARTER"), r["quant_research_score"]), reverse=True)
    selected = rows[:limit]
    return {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "layer": "AI beta forward-validation candidate screen",
            "data_as_of": _universe_meta().get("fetched_at"),
            "input_universe": "public/data/universe_a.json current committed snapshot",
            "screen_method": (
                "current committed A-share universe snapshot intersected with an explicit "
                "AI/AI-infrastructure value-chain seed list; concept_membership.json has "
                "0 current concepts in this checkout, so the industry taxonomy is explicit "
                "and auditable rather than silently inferred"
            ),
            "disclaimer": "research candidate pack only; not a buy list, not validated alpha, not personalized advice; human executes",
            "freshness_gate_max_age_days": MAX_COMMITTED_PRICE_AGE_DAYS,
        },
        "candidates": selected,
        "excluded_after_screen": rows[limit:],
    }


def golden_test() -> int:
    expected = {
        "688008.SH": {"price": 229.28, "rr": 0.11, "entry": 150.83, "lock": "f7e3b135"},
        "688072.SH": {"price": 664.42, "rr": -0.06, "entry": 383.33, "lock": "297c7f58"},
    }
    errs = []
    for ticker, exp in expected.items():
        safe = ticker.replace(".", "_")
        sheet = _load(D / "decision_sheets" / f"{safe}.json", {}) or {}
        lock = (sheet.get("content_lock_sha256") or "")[:8]
        rr = sheet.get("reward_to_risk") or {}
        px = (sheet.get("auto_context") or {}).get("last_price", {}).get("close")
        snap = price_snapshot(ticker)
        checks = [
            (lock == exp["lock"], f"{ticker} lock {lock} != {exp['lock']}"),
            (round(float(px), 2) == exp["price"], f"{ticker} sheet price {px} != {exp['price']}"),
            (round(float(snap["price"]), 2) == exp["price"], f"{ticker} snapshot price {snap['price']} != {exp['price']}"),
            (round(float(rr.get("reward_to_risk")), 2) == exp["rr"], f"{ticker} rr {rr.get('reward_to_risk')} != {exp['rr']}"),
            (round(float(rr.get("entry_where_bar_met")), 2) == exp["entry"], f"{ticker} entry {rr.get('entry_where_bar_met')} != {exp['entry']}"),
        ]
        errs.extend(msg for ok, msg in checks if not ok)
    if errs:
        print("[deep_thesis_prepare] GOLDEN FAIL")
        for e in errs:
            print("  -", e)
        return 1
    pack = build_ai_screen(15)
    stale = [c["ticker"] for c in pack["candidates"]
             if c["price_snapshot"]["freshness_gate"] != "PASS"]
    if stale:
        print("[deep_thesis_prepare] SELFTEST FAIL — stale candidates:", stale)
        return 1
    registered = {c["ticker"]: c["stance"] for c in pack["candidates"]
                  if "registered" in c["evidence_status"]}
    for ticker, stance in registered.items():
        if stance != "WATCH_ONLY_REGISTERED":
            print(f"[deep_thesis_prepare] SELFTEST FAIL — {ticker} registered but stance={stance}")
            return 1
    print("[deep_thesis_prepare] GOLDEN PASS — 688008/688072 reconciled")
    return 0


def _fmt_money(v: Any) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v)/1e9:.1f}bn"
    except Exception:
        return str(v)


def render_report(pack: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for c in pack["candidates"]:
        counts[c["stance"]] = counts.get(c["stance"], 0) + 1
    lines = [
        "# AI / AI-Infrastructure Beta Forward-Validation Candidate Pack",
        "",
        f"> Generated: {pack['_meta']['generated_at']}",
        f"> Data as-of: {pack['_meta'].get('data_as_of')}",
        "> **Use:** beta forward-validation research candidates. This is not a buy list, not validated alpha, and not personalized investment advice. Human executes.",
        "",
        "## Read This First",
        "",
        "- This pack was re-screened from the current committed A-share universe snapshot; prior AI-semi reports are not reused as stale stances.",
        f"- Screen method: {pack['_meta']['screen_method']}",
        f"- Stance counts: {', '.join(f'{k}={v}' for k, v in sorted(counts.items()))}.",
        "- Every price below carries a source/date/freshness gate. If the gate fails, the name cannot enter a beta list.",
        "- `starter_review_trigger` is a research trigger price where the heuristic band reaches roughly 2:1 reward/risk; it is **not** an automatic order.",
        "- A name can be high-quality and still be WATCH_ONLY if price is too close to its bull case.",
        "",
        "## Candidate Table",
        "",
        "| # | ticker | name | layer | stance | px/date | PE/PB | target band | starter review trigger | quant score |",
        "|---:|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for i, c in enumerate(pack["candidates"], 1):
        px = c["price_snapshot"]["price"]
        pdate = c["price_snapshot"]["date"]
        pe = c["market"].get("pe")
        pb = c["market"].get("pb")
        tgt = c["valuation"]["research_target"]
        entry = c["valuation"]["starter_review_price_2to1"]
        lines.append(
            f"| {i} | {c['ticker']} | {c['name']} | {c['layer']} | {c['stance']} | "
            f"{px} / {pdate} | {pe} / {pb} | {tgt[0]}-{tgt[1]} | {entry} | {c['quant_research_score']} |"
        )
    lines += ["", "## Per-Name Research Cards", ""]
    for c in pack["candidates"]:
        lines += [
            f"### {c['ticker']} {c['name']} — {c['stance']}",
            "",
            f"- **Role:** {c['role']}",
            f"- **Price source:** {c['price_snapshot']['source']} @ {c['price_snapshot']['date']} "
            f"(age {c['price_snapshot']['age_days']}d, {c['price_snapshot']['freshness_gate']})",
            f"- **Market snapshot:** price {c['price_snapshot']['price']}; PE {c['market'].get('pe')}; "
            f"PB {c['market'].get('pb')}; market cap {_fmt_money(c['market'].get('market_cap'))}; "
            f"alpha_score {c['market'].get('alpha_score')}",
            "- **Three-point thesis:**",
            f"  1. {c['thesis_points'][0]}",
            f"  2. {c['thesis_points'][1]}",
            f"  3. {c['thesis_points'][2]}",
            f"- **Catalysts to monitor:** {'; '.join(c['catalysts'])}",
            f"- **Risks / wrong-if candidates:** {'; '.join(c['risks'])}",
            f"- **Valuation frame:** bear {c['valuation']['bear'][0]}-{c['valuation']['bear'][1]}; "
            f"research target {c['valuation']['research_target'][0]}-{c['valuation']['research_target'][1]}; "
            f"R/R at snapshot {c['valuation']['reward_to_risk_at_snapshot']}. "
            f"Basis: {c['valuation']['valuation_basis']}",
            f"- **Suggested entry framework:** starter review only at/under ~{c['suggested_entry_framework']['starter_review_trigger']} "
            f"and only after full deep thesis + fresh price reconciliation + no wrong_if. Human executes.",
            f"- **Evidence status:** {c['evidence_status']}",
            "",
        ]
    lines += [
        "## Quant Engineering Scope",
        "",
        "- This pack includes a deterministic cross-sectional score, but it is **not** a validated quant alpha.",
        "- The quant layer now contributes: freshness gate, valuation/crowding penalties, layer scoring, and forward-state logging.",
        "- Any true quant strategy still needs Strategy Lab manifest → PIT data audit → negative controls → trials ledger → forward paper court.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker")
    ap.add_argument("--screen-ai", action="store_true")
    ap.add_argument("--write-report", action="store_true")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--golden-test", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return golden_test()
    if args.golden_test:
        return golden_test()
    if args.ticker:
        print(json.dumps(market_snapshot(args.ticker), ensure_ascii=False, indent=2))
        return 0
    if args.screen_ai or args.write_report:
        pack = build_ai_screen(args.limit)
        out_json = D / "ai_forward_validation_candidates.json"
        out_json.write_text(json.dumps(pack, ensure_ascii=False, indent=2))
        print(f"[deep_thesis_prepare] wrote {out_json}")
        if args.write_report:
            out_md = REPORT_DIR / "AI_FORWARD_VALIDATION_CANDIDATES_2026-06-14.md"
            out_md.write_text(render_report(pack))
            print(f"[deep_thesis_prepare] wrote {out_md}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
