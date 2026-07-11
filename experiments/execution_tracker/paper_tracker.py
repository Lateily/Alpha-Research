#!/usr/bin/env python3
"""
paper_tracker.py — Paper Trading Tracker v1 (PR-M2, Junyan-approved 2026-07-09)

EXTENDS the existing paper_signal_log.json ledger — the A4 amendment iron rule:
NO third ledger. Research pre-registrations (rotation_hypothesis /
value_chain_thesis / ...) append to the SAME file, same signal_id convention,
with additive fields. Legacy settle-runner records (official_sample=true) are
untouched and tolerated everywhere (missing new fields => legacy).

Adds:
  register_research_signal(...)  pre-register a hypothesis BEFORE outcome
  append_thought(...)            append-only thought log keyed by signal_id
                                 (reasoning evolution WITHOUT rewriting the
                                 original hypothesis — no-lookahead DNA)
  weekly_rollup(...)             aggregate by setup_type/market_state/line;
                                 any rate metric carries n and claim_allowed
                                 (n >= 30) — below the bar it is a COUNT, not
                                 a claim.

No buy/sell semantics. Every record: no_trade_flag=true.
不是买卖指令；研究信号，human executes。
"""

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SIGNAL_LOG = os.path.join(HERE, "paper_signal_log.json")
THOUGHT_LOG = os.path.join(HERE, "thought_log.json")

MIN_SAMPLE_FOR_CLAIM = 30  # project validation threshold [Junyan-ratified]

RESEARCH_SETUP_TYPES = {
    "rotation_hypothesis",    # Line 1: sector-rotation condition hypothesis
    "value_chain_thesis",     # Line 2: bottleneck-node variant thesis
    "execution_gate",         # gate posture observation
    "risk_warning",           # negative-flow / distribution signature
    "watch_only",             # explicit non-action record
    "blocked_by_regime",      # candidate blocked by CHURN/RISK_OFF gate
    "distribution_warning",
}

LINES = {"thesis", "execution", "quant", "smc", "rotation", "value_chain"}


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _dump(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


def register_research_signal(*, ticker, name, setup_type, line, market_state,
                             hypothesis, catalyst, invalidation, horizon,
                             created_by, sector="", sector_state="",
                             variant_view="", mechanism_chain=None,
                             evidence=None, flow_fact="", forecast_claim="",
                             trigger_condition="", entry_close=None,
                             registered_at=None, log_path=SIGNAL_LOG):
    """Pre-register a research signal BEFORE outcome. Returns (record, status).

    Refuses: unknown setup_type / line, missing invalidation or hypothesis
    (an unfalsifiable registration is not a signal), duplicate signal_id.
    registered_at: caller supplies 'YYYYMMDD HH:MM' — explicit, testable,
    never invented by this module.
    """
    if setup_type not in RESEARCH_SETUP_TYPES:
        return None, f"refused: unknown setup_type {setup_type!r}"
    if line not in LINES:
        return None, f"refused: unknown line {line!r}"
    if not (hypothesis or "").strip():
        return None, "refused: empty hypothesis"
    if not (invalidation or "").strip():
        return None, "refused: empty invalidation (unfalsifiable registration)"
    if not (registered_at or "").strip():
        return None, "refused: registered_at required (pre-registration timestamp)"

    sid = hashlib.md5(
        f"{ticker}|{registered_at}|{setup_type}|{hypothesis}".encode()
    ).hexdigest()[:12]

    log = _load(log_path, [])
    if any(s.get("signal_id") == sid for s in log):
        return None, f"duplicate: {sid} already registered"

    record = {
        # ---- shared spine with legacy settle-runner records ----
        "signal_id":      sid,
        "ticker":         ticker,
        "name":           name,
        "timestamp":      registered_at,
        "line":           line,
        "market_state":   market_state,
        "setup_type":     setup_type,
        "horizon":        horizon,
        "no_trade_flag":  True,
        "official_sample": False,          # research pre-registration, not settle
        "data_source":    "pre_registered:research",
        "returns":        {},              # backfilled from settle data later
        "entry_close":    entry_close,
        # ---- research-extension fields (additive; absent on legacy) ----
        "created_by":     created_by,
        "sector":         sector,
        "sector_state":   sector_state,
        "hypothesis":     hypothesis,
        "variant_view":   variant_view,
        "catalyst":       catalyst,
        "mechanism_chain": mechanism_chain or [],
        "evidence":       evidence or [],
        "flow_fact":      flow_fact,
        "forecast_claim": forecast_claim,
        "trigger_condition": trigger_condition,
        "invalidation":   invalidation,
        "human_status":   "not_executed",
        "outcome_status": "pending",
    }
    log.append(record)
    _dump(log_path, log)
    return record, "registered"


def append_thought(signal_id, author, thought, changed_action, why,
                   at, log_path=THOUGHT_LOG, signal_path=SIGNAL_LOG):
    """Append-only thought entry. The original hypothesis is NEVER edited."""
    signals = {s.get("signal_id") for s in _load(signal_path, [])}
    if signal_id not in signals:
        return None, f"refused: unknown signal_id {signal_id}"
    log = _load(log_path, [])
    entry = {"signal_id": signal_id, "at": at, "author": author,
             "thought": thought, "changed_action": bool(changed_action),
             "why": why}
    log.append(entry)
    _dump(log_path, log)
    return entry, "appended"


def weekly_rollup(log_path=SIGNAL_LOG):
    """Aggregate the WHOLE ledger (legacy + research records together).

    Every rate is emitted as {hit, n, claim_allowed}; when n < 30 the number
    is a count-in-progress, not a claim — consumers must render it that way.
    """
    log = _load(log_path, [])
    by = {}
    for s in log:
        key = (s.get("setup_type", "?"), s.get("market_state", "?"),
               s.get("line", "?"))
        g = by.setdefault(key, {"n": 0, "official": 0, "research": 0,
                                "pending": 0, "scored_1d": 0, "hit_1d": 0})
        g["n"] += 1
        g["official" if s.get("official_sample") else "research"] += 1
        if s.get("outcome_status", "") == "pending" and not s.get("returns"):
            g["pending"] += 1
        r1 = (s.get("returns") or {}).get("1d")
        if r1 is not None:
            g["scored_1d"] += 1
            direction = s.get("directional_call", "")
            if direction in ("constructive", "cautious"):
                hit = (r1 > 0) if direction == "constructive" else (r1 < 0)
                g["hit_1d"] += 1 if hit else 0
    rows = []
    for (setup, mstate, line), g in sorted(by.items()):
        row = {"setup_type": setup, "market_state": mstate, "line": line, **g}
        n = g["scored_1d"]
        row["hit_rate_1d"] = {"hit": (g["hit_1d"] / n if n else None), "n": n,
                              "claim_allowed": n >= MIN_SAMPLE_FOR_CLAIM}
        rows.append(row)
    return {"groups": rows, "total_signals": len(log),
            "min_sample_for_claim": MIN_SAMPLE_FOR_CLAIM,
            "note": "hit_rate with claim_allowed=false is a count-in-progress,"
                    " never a validated rate. 不是买卖指令。"}


# ------------------------------------------------------------------ selftest --
def selftest():
    import tempfile
    ok = []

    def ck(name, cond):
        ok.append((name, bool(cond)))
        print(("  ✓ " if cond else "  ✗ ") + name)

    with tempfile.TemporaryDirectory() as td:
        sp, tp = os.path.join(td, "sig.json"), os.path.join(td, "tho.json")
        # legacy record tolerance: a settle-runner record without new fields
        _dump(sp, [{"signal_id": "legacy0000ab", "ticker": "002714.SZ",
                    "name": "牧原股份", "timestamp": "20260708 close (official)",
                    "line": "execution", "market_state": "RISK_OFF",
                    "setup_type": "DE_RISK_REVIEW", "no_trade_flag": True,
                    "official_sample": True, "returns": {"1d": -0.012},
                    "directional_call": "cautious", "entry_close": 36.8}])

        rec, st = register_research_signal(
            ticker="600276.SH", name="恒瑞医药", setup_type="value_chain_thesis",
            line="value_chain", market_state="RISK_ON",
            hypothesis="创新药 license-out 现金流被低估", catalyst="H1 财报分部披露",
            invalidation="H1 license 收入 < 10亿", horizon=["20d", "60d"],
            created_by="Claude", registered_at="20260709 22:50",
            log_path=sp)
        ck("research signal registers into the SAME ledger", st == "registered"
           and len(_load(sp, [])) == 2)
        _, st2 = register_research_signal(
            ticker="600276.SH", name="恒瑞医药", setup_type="value_chain_thesis",
            line="value_chain", market_state="RISK_ON",
            hypothesis="创新药 license-out 现金流被低估", catalyst="H1 财报分部披露",
            invalidation="H1 license 收入 < 10亿", horizon=["20d"],
            created_by="Claude", registered_at="20260709 22:50", log_path=sp)
        ck("duplicate registration refused", st2.startswith("duplicate"))
        _, st3 = register_research_signal(
            ticker="X", name="x", setup_type="value_chain_thesis",
            line="value_chain", market_state="RISK_ON", hypothesis="h",
            catalyst="c", invalidation="", horizon=["1d"], created_by="C",
            registered_at="20260709 22:50", log_path=sp)
        ck("empty invalidation refused (unfalsifiable)", st3.startswith("refused"))
        _, st4 = register_research_signal(
            ticker="X", name="x", setup_type="buy_now_lol",
            line="value_chain", market_state="RISK_ON", hypothesis="h",
            catalyst="c", invalidation="i", horizon=["1d"], created_by="C",
            registered_at="20260709 22:50", log_path=sp)
        ck("unknown setup_type refused", st4.startswith("refused"))
        ck("no timestamp invention: registered_at required",
           register_research_signal(
               ticker="X", name="x", setup_type="watch_only", line="execution",
               market_state="RISK_ON", hypothesis="h", catalyst="c",
               invalidation="i", horizon=["1d"], created_by="C",
               registered_at="", log_path=sp)[1].startswith("refused"))

        _, ts = append_thought(rec["signal_id"], "Junyan", "盘中主力回流,但等定盘",
                               False, "intraday data never drives the sample",
                               at="20260709 23:00", log_path=tp, signal_path=sp)
        ck("thought appends", ts == "appended" and len(_load(tp, [])) == 1)
        _, ts2 = append_thought("nonexistent00", "x", "t", False, "w",
                                at="20260709 23:01", log_path=tp, signal_path=sp)
        ck("thought for unknown signal refused", ts2.startswith("refused"))
        ck("original hypothesis untouched after thought",
           _load(sp, [])[1]["hypothesis"] == "创新药 license-out 现金流被低估")

        roll = weekly_rollup(log_path=sp)
        ck("rollup covers legacy + research", roll["total_signals"] == 2)
        legacy_row = [r for r in roll["groups"] if r["setup_type"] == "DE_RISK_REVIEW"][0]
        ck("rate below 30 samples => claim_allowed false",
           legacy_row["hit_rate_1d"]["claim_allowed"] is False
           and legacy_row["hit_rate_1d"]["n"] == 1)
        ck("cautious + negative 1d counts as hit (direction-aware)",
           legacy_row["hit_rate_1d"]["hit"] == 1.0)

    # live-ledger smoke: rollup runs on the real file without touching it
    before = _load(SIGNAL_LOG, [])
    roll = weekly_rollup()
    ck("live rollup runs read-only", _load(SIGNAL_LOG, []) == before
       and roll["total_signals"] == len(before))

    passed = sum(1 for _, c in ok if c)
    print(f"paper_tracker selftest: {passed}/{len(ok)}")
    return passed == len(ok)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    if "--rollup" in sys.argv:
        print(json.dumps(weekly_rollup(), ensure_ascii=False, indent=2))
        print("不是买卖指令；研究信号，human executes。")
        return
    print(__doc__)


if __name__ == "__main__":
    main()
