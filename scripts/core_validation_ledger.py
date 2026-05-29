#!/usr/bin/env python3
"""core_validation_ledger.py — READ-ONLY CORE thesis-validation ledger + attribution.

Per CORE_VALIDATION_PLAN_2026-05-29.md. Builds the thesis_trade_ledger from
existing artifacts, computes A-share forward returns + benchmark-relative alpha
for ELAPSED horizons only, and decomposes the live paper positions into
market-beta vs residual thesis-alpha. Honest by construction: every metric
carries its n and an availability flag; HK names (no repo price) and
not-enough-elapsed-time horizons are marked, never faked.

READ-ONLY: reads thesis/position/price artifacts; writes ONLY the output JSON.
Does not trade, does not mutate thesis/position state.

Usage:
    python3 scripts/core_validation_ledger.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

try:
    from stationary_bootstrap import bootstrap_ci
    _HAVE_BOOT = True
except Exception:
    _HAVE_BOOT = False

from portfolio_thesis_alignment import alignment_of, latest_thesis_labels

PANEL = REPO / "data_history" / "panel" / "daily_prices.parquet"
INDEX = REPO / "data_history" / "panel" / "index_prices.parquet"
HK_PANEL = REPO / "data_history" / "panel" / "hk_prices.parquet"
HK_META = REPO / "data_history" / "panel" / "hk_prices_meta.json"
THESIS_EVAL = REPO / "public" / "data" / "iter9_thesis_eval.json"
POSITIONS = REPO / "public" / "data" / "positions.json"
ATTR_DIR = REPO / "public" / "data" / "thesis_attribution"
BACKFILL = REPO / "public" / "data" / "thesis_direction_backfill.json"
OUT = REPO / "public" / "data" / "core_validation_ledger.json"

CAPITAL_LABELS = {"LONG", "SHORT"}
VALIDATION_LABELS = {"LONG", "SHORT", "WATCH_LONG", "WATCH_SHORT"}

HORIZONS_TD = {"5d": 5, "20d": 20, "60d": 60, "120d": 120}
# A-share benches live in index_prices.parquet (ts_code 000300.SH ...); HK benches
# live in hk_prices.parquet (ts_code HSI / HSTECH, written by fetch_hk_prices.py).
A_BENCHES = {"CSI300": "000300.SH", "CSI500": "000905.SH"}
HK_BENCHES = {"HSI": "HSI", "HSTECH": "HSTECH"}
TODAY = "2026-05-29"


def is_hk(tic: str) -> bool:
    return isinstance(tic, str) and tic.endswith(".HK")


def benches_for(tic: str) -> dict[str, str]:
    return HK_BENCHES if is_hk(tic) else A_BENCHES


def primary_bench(tic: str) -> str:
    return "HSI" if is_hk(tic) else "CSI300"


def _to_dt(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.astype(str), format="%Y%m%d", errors="coerce")


def load_series(parquet: Path, tickers: set[str]) -> dict[str, pd.DataFrame]:
    """Return {ts_code: df[date, close] sorted ascending} for the needed tickers."""
    df = pd.read_parquet(parquet, columns=["ts_code", "trade_date", "close"])
    df = df[df["ts_code"].isin(tickers)].copy()
    df["date"] = _to_dt(df["trade_date"])
    out = {}
    for tic, g in df.groupby("ts_code"):
        g = g.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        out[tic] = g[["date", "close"]]
    return out


def fwd_from_thesis(px: pd.DataFrame, thesis_date: str, htd: int) -> dict:
    """Forward return over htd TRADING days from first trading day >= thesis_date."""
    td = pd.Timestamp(thesis_date)
    idx = px["date"].searchsorted(td, side="left")
    if idx >= len(px):
        return {"status": "no_entry", "ret": None}
    entry = px.iloc[idx]
    exit_i = idx + htd
    if exit_i >= len(px):
        return {"status": "pending_not_enough_time", "ret": None,
                "entry_date": str(entry["date"].date()), "entry_close": float(entry["close"]),
                "elapsed_td": int(len(px) - 1 - idx)}
    ex = px.iloc[exit_i]
    ec, xc = float(entry["close"]), float(ex["close"])
    ret = (xc / ec - 1.0) if ec > 0 else None
    return {"status": "available", "ret": ret,
            "entry_date": str(entry["date"].date()), "entry_close": ec,
            "exit_date": str(ex["date"].date()), "exit_close": xc}


def bench_ret_over(px_b: pd.DataFrame, entry_date: str, exit_date: str) -> float | None:
    a = px_b["date"].searchsorted(pd.Timestamp(entry_date), side="left")
    b = px_b["date"].searchsorted(pd.Timestamp(exit_date), side="left")
    if a >= len(px_b) or b >= len(px_b):
        return None
    ca, cb = float(px_b.iloc[a]["close"]), float(px_b.iloc[b]["close"])
    return (cb / ca - 1.0) if ca > 0 else None


def beta_attribution(px: pd.DataFrame, px_b: pd.DataFrame, entry_date: str) -> dict:
    """Decompose stock return since entry into market-beta vs residual (thesis alpha).

    beta from OLS of daily stock returns on daily benchmark returns over [entry..latest].
    """
    s = px[px["date"] >= pd.Timestamp(entry_date)].reset_index(drop=True)
    b = px_b[px_b["date"] >= pd.Timestamp(entry_date)].reset_index(drop=True)
    if len(s) < 10 or len(b) < 10:
        return {"status": "insufficient_overlap", "n_days": min(len(s), len(b))}
    m = pd.merge(s.rename(columns={"close": "s"}), b.rename(columns={"close": "bm"}),
                 on="date", how="inner").sort_values("date")
    if len(m) < 10:
        return {"status": "insufficient_overlap", "n_days": len(m)}
    rs = m["s"].pct_change().dropna().values
    rb = m["bm"].pct_change().dropna().values
    n = min(len(rs), len(rb))
    rs, rb = rs[:n], rb[:n]
    if n < 8 or np.var(rb) == 0:
        return {"status": "insufficient_overlap", "n_days": n}
    beta = float(np.cov(rs, rb)[0, 1] / np.var(rb))
    total = float(m["s"].iloc[-1] / m["s"].iloc[0] - 1.0)
    bench_total = float(m["bm"].iloc[-1] / m["bm"].iloc[0] - 1.0)
    beta_contrib = beta * bench_total
    return {"status": "ok", "n_days": int(n), "beta": round(beta, 3),
            "total_return": round(total, 4), "bench_total_return": round(bench_total, 4),
            "beta_contribution": round(beta_contrib, 4),
            "residual_thesis_alpha": round(total - beta_contrib, 4),
            "caveat": ("residual is UPPER BOUND on thesis-α: single-factor CSI300 only "
                       "removes broad-market beta, NOT sector/theme beta. An AI-optical "
                       "name's theme rally (not in CSI300) leaks into residual and is "
                       "indistinguishable from thesis skill without a sector/peer benchmark.")}


def main() -> int:
    ev = json.loads(THESIS_EVAL.read_text())
    recs = ev["records"]
    pos = json.loads(POSITIONS.read_text())
    positions = pos.get("positions", [])
    pos_as_of = (pos.get("as_of") or "")[:10]

    thesis_tics = {r["ts_code"] for r in recs}
    pos_tics = {p.get("ticker") for p in positions if p.get("ticker")}
    need = {t for t in (thesis_tics | pos_tics) if isinstance(t, str)}
    a_tics = {t for t in need if not is_hk(t)}
    hk_tics = {t for t in need if is_hk(t)}

    print(f"[core-val] thesis tickers={sorted(thesis_tics)}")
    print(f"[core-val] A-share={sorted(a_tics)} | HK={sorted(hk_tics)}")
    print(f"[core-val] loading price series...")
    px = load_series(PANEL, a_tics)
    bpx = load_series(INDEX, set(A_BENCHES.values()))
    hk_meta = {}
    if HK_PANEL.exists():
        px.update(load_series(HK_PANEL, hk_tics))
        bpx.update(load_series(HK_PANEL, set(HK_BENCHES.values())))
        if HK_META.exists():
            hk_meta = json.loads(HK_META.read_text())
        print(f"[core-val] HK panel loaded: {sorted(t for t in hk_tics if t in px)} "
              f"+ benches {sorted(b for b in HK_BENCHES.values() if b in bpx)}")
    else:
        print(f"[core-val] HK panel MISSING ({HK_PANEL}) — HK names stay blocked. "
              f"Run scripts/fetch_hk_prices.py first.")
    for name, code in {**A_BENCHES, **HK_BENCHES}.items():
        print(f"[core-val] bench {name} ({code}): {'OK' if code in bpx else 'MISSING'}")

    # backfill reclassification (LONG/SHORT/WATCH_*/PASS/UNRESOLVED) keyed by
    # (ts_code, thesis_date, stage==pipeline). Built by backfill_thesis_direction.py.
    reclass = {}
    if BACKFILL.exists():
        for br in json.loads(BACKFILL.read_text()).get("rows", []):
            reclass[(br.get("ts_code"), br.get("thesis_date"), br.get("stage"))] = br.get("reclassified")
        print(f"[core-val] backfill labels loaded: {len(reclass)} rows")
    else:
        print(f"[core-val] backfill MISSING ({BACKFILL}) — run backfill_thesis_direction.py; "
              f"directional tiers fall back to original _direction")

    # structured catalyst/wrongIf where logged
    attr = {}
    if ATTR_DIR.exists():
        for f in ATTR_DIR.glob("*.json"):
            if "_2026" in f.stem:  # skip dated archives, keep latest
                continue
            try:
                a = json.loads(f.read_text())
                attr[a.get("ticker")] = a
            except Exception:
                pass

    # ── ledger ──
    ledger = []
    for r in recs:
        tic = r["ts_code"]
        pbench = primary_bench(tic)            # CSI300 (A) or HSI (HK)
        label = reclass.get((tic, r["thesis_date"], r.get("pipeline"))) or (r.get("_direction") or "PASS")
        row = {
            "ts_code": tic, "market": "HK" if is_hk(tic) else "A", "thesis_date": r["thesis_date"],
            "pipeline": r.get("pipeline"),
            "direction": r.get("_direction"),
            "reclassified": label,
            "directional_for_capital": label in CAPITAL_LABELS,
            "directional_for_validation": label in VALIDATION_LABELS,
            "watch_unvalidated": label.startswith("WATCH_"),
            "actionable": r.get("_direction") in ("LONG", "SHORT"),
            "quality_score": r.get("quality_score"), "reward_to_risk": r.get("reward_to_risk"),
            "data_available": tic in px,
            "primary_bench": pbench,
            "catalyst": (attr.get(tic) or {}).get("catalyst"),
            "wrongIf": (attr.get(tic) or {}).get("wrongIf_conditions"),
            "forward": {}, "alpha_by_bench": {}, "primary_alpha": {},
        }
        if row["data_available"]:
            for hname, htd in HORIZONS_TD.items():
                fr = fwd_from_thesis(px[tic], r["thesis_date"], htd)
                row["forward"][hname] = fr
                if fr.get("status") == "available":
                    row["entry_price"] = fr["entry_close"]
                    for bn, bcode in benches_for(tic).items():
                        if bcode in bpx:
                            br = bench_ret_over(bpx[bcode], fr["entry_date"], fr["exit_date"])
                            alpha = (round(fr["ret"] - br, 4)
                                     if (fr["ret"] is not None and br is not None) else None)
                            row["alpha_by_bench"].setdefault(bn, {})[hname] = alpha
                            if bn == pbench:
                                row["primary_alpha"][hname] = alpha
        ledger.append(row)

    # ── eval metrics on actionable + data_available subset ──
    def metrics_for(hname: str) -> dict:
        rows = [r for r in ledger if r["actionable"] and r["data_available"]
                and r["forward"].get(hname, {}).get("status") == "available"]
        n = len(rows)
        if n == 0:
            return {"n": 0, "status": "no_actionable_with_data_at_horizon"}
        alphas = [r["primary_alpha"].get(hname) for r in rows]
        alphas = [a for a in alphas if a is not None]
        out = {"n": n, "n_alpha": len(alphas),
               "benchmark": "primary (A:CSI300 / HK:HSI)",
               "hit_rate": (round(sum(1 for a in alphas if a > 0) / len(alphas), 3) if alphas else None),
               "mean_alpha": (round(float(np.mean(alphas)), 4) if alphas else None),
               "inferential": len(alphas) >= 8}
        if not out["inferential"]:
            out["WARNING"] = f"n={len(alphas)} < 8 — NOT statistically inferential (descriptive only)"
        return out

    eval_metrics = {h: metrics_for(h) for h in HORIZONS_TD}

    # rank IC (quality vs forward alpha) — guarded
    rank_ic = {}
    for hname in HORIZONS_TD:
        rows = [r for r in ledger if r["data_available"]
                and r["forward"].get(hname, {}).get("status") == "available"
                and r["primary_alpha"].get(hname) is not None
                and r["quality_score"] is not None]
        if len(rows) >= 4:
            q = pd.Series([r["quality_score"] for r in rows])
            a = pd.Series([r["primary_alpha"][hname] for r in rows])
            # Spearman = Pearson on (tie-aware) ranks — avoids scipy dependency.
            ic = float(q.rank().corr(a.rank()))
            rank_ic[hname] = {"n": len(rows), "spearman_ic": round(ic, 4),
                              "inferential": len(rows) >= 8,
                              "note": ("OK" if len(rows) >= 8 else "n<8 NOT inferential")}
        else:
            rank_ic[hname] = {"n": len(rows), "spearman_ic": None,
                              "note": "n<4 — not computable"}

    # Dedupe to latest pipeline stage per ticker (25 records = ~7 tickers × stages;
    # all-snapshots would double-count and mix per-stage label disagreements).
    STAGE_ORDER = {"1255BST": 0, "1438BST": 1, "1530BST": 2, "GROUNDED": 3,
                   "MULTIAGENT": 4, "PHASE1.5": 5, "PHASE2": 6}
    _latest = {}
    for r in ledger:
        key = r["ts_code"]
        rank = (r.get("thesis_date") or "", STAGE_ORDER.get(r.get("pipeline"), -1))
        if key not in _latest or rank > _latest[key][0]:
            _latest[key] = (rank, r)
    latest_ledger = [v[1] for v in _latest.values()]

    # ── directional-correctness on validation set (sign-aware) ──
    # LONG/WATCH_LONG: directional return = +alpha; SHORT/WATCH_SHORT: −alpha.
    # Tests whether the directional CALL (incl. the buried WATCH_* shorts) was right.
    # Latest-stage-per-ticker only (the honest unit).
    def directional_metrics(hname: str, tier: str) -> dict:
        keep = CAPITAL_LABELS if tier == "capital" else VALIDATION_LABELS
        rows = [r for r in latest_ledger if r["reclassified"] in keep and r["data_available"]
                and r["primary_alpha"].get(hname) is not None]
        outs = []
        for r in rows:
            a = r["primary_alpha"][hname]
            sgn = -1 if r["reclassified"] in ("SHORT", "WATCH_SHORT") else 1
            outs.append({"ts_code": r["ts_code"], "label": r["reclassified"],
                         "alpha_vs_bench": a, "directional_return": round(sgn * a, 4),
                         "correct": sgn * a > 0})
        n = len(outs)
        nc = sum(1 for o in outs if o["correct"])
        return {"tier": tier, "horizon": hname, "n": n,
                "hit_rate": (round(nc / n, 3) if n else None),
                "mean_directional_return": (round(float(np.mean([o["directional_return"] for o in outs])), 4) if n else None),
                "inferential": n >= 8,
                "note": ("" if n >= 8 else f"n={n} < 8 — descriptive only, NOT inferential"),
                "rows": outs}

    directional_validation = {
        "capital_tier": {h: directional_metrics(h, "capital") for h in HORIZONS_TD},
        "validation_tier_incl_WATCH": {h: directional_metrics(h, "validation") for h in HORIZONS_TD},
    }

    # ── 5-position attribution + thesis-alignment marker ──
    align_labels = latest_thesis_labels()
    pos_attr = []
    for p in positions:
        tic = p.get("ticker")
        name = p.get("name")
        qty = p.get("quantity")
        side = "LONG" if (qty is None or qty >= 0) else "SHORT"
        thesis_label = align_labels.get(tic)
        algn = alignment_of(side, thesis_label)
        as_of = (p.get("as_of") or pos_as_of or TODAY)[:10]
        hd = p.get("holding_days")
        # entry_date ≈ as_of − holding_days (calendar); searchsorted finds the
        # first trading day on/after it.
        entry_date = None
        if hd is not None:
            entry_date = str((pd.Timestamp(as_of) - pd.Timedelta(days=int(hd))).date())
        bcode = benches_for(tic)[primary_bench(tic)]   # HK→HSI, A→000300.SH
        rec = {"ticker": tic, "name": name, "weight_pct": p.get("weight_pct"),
               "vp_at_entry": p.get("vp_at_entry"), "pnl_pct_reported": p.get("pnl_pct"),
               "holding_days": hd, "entry_date_used": entry_date,
               "benchmark": primary_bench(tic),
               "position_side": side, "latest_thesis_direction": thesis_label,
               "alignment": algn, "requires_human_review": algn in ("WATCH_CONFLICT", "HARD_CONFLICT")}
        if tic not in px:
            rec["attribution"] = {"status": "no_price_run_fetch_hk_prices" if is_hk(tic) else "no_price"}
        elif bcode not in bpx:
            rec["attribution"] = {"status": f"benchmark_{primary_bench(tic)}_missing"}
        elif not entry_date:
            rec["attribution"] = {"status": "no_holding_days"}
        else:
            rec["attribution"] = beta_attribution(px[tic], bpx[bcode], entry_date)
        pos_attr.append(rec)

    out = {
        "_meta": {
            "generated_for": TODAY, "read_only": True,
            "source": {"thesis_eval": str(THESIS_EVAL), "positions": str(POSITIONS),
                       "hk_panel": str(HK_PANEL) if HK_PANEL.exists() else "MISSING"},
            "hk_benchmark_status": (hk_meta.get("benchmarks") if hk_meta else "hk_panel_absent"),
            "honesty": ("PRELIMINARY. n_actionable=4 directional of 25 (21 PASS, synth-gate ratchet); "
                        "theses all dated 2026-05-05→10 so only 5d horizon has elapsed — 20d/60d/120d "
                        "PENDING (not enough time). HK names NOW UNBLOCKED via yfinance (HSI benchmark; "
                        "HSTECH = proxy 3033.HK). No CORE validation verdict is drawn from this — it is "
                        "descriptive + the live-position beta attribution. The position 'residual' is an "
                        "UPPER BOUND on thesis-α (single-factor benchmark leaves sector/theme beta in "
                        "residual). See CORE_VALIDATION_PLAN_2026-05-29.md."),
            "horizons_td": HORIZONS_TD,
            "n_theses": len(recs),
            "n_actionable_original": sum(1 for r in ledger if r["actionable"]),
            "n_directional_for_capital": sum(1 for r in ledger if r["directional_for_capital"]),
            "n_directional_for_validation": sum(1 for r in ledger if r["directional_for_validation"]),
            "n_data_available": sum(1 for r in ledger if r["data_available"]),
        },
        "ledger": ledger,
        "eval_metrics_by_horizon": eval_metrics,
        "rank_ic_quality_vs_alpha": rank_ic,
        "directional_validation": directional_validation,
        "position_attribution": pos_attr,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))

    # ── console summary ──
    print("\n" + "=" * 72)
    print("CORE VALIDATION LEDGER (READ-ONLY, PRELIMINARY)")
    print("=" * 72)
    print(f"theses={len(recs)} (= ~7 tickers × pipeline stages)  with-price={out['_meta']['n_data_available']}")
    print(f"directional_for_capital (LONG/SHORT) = {out['_meta']['n_directional_for_capital']}  |  "
          f"directional_for_validation (+WATCH_*) = {out['_meta']['n_directional_for_validation']}  "
          f"(was n_actionable={out['_meta']['n_actionable_original']})")
    print("\nDirectional-correctness (sign-aware; SHORT correct when stock falls) @5d:")
    for tier_key in ("capital_tier", "validation_tier_incl_WATCH"):
        m = directional_validation[tier_key]["5d"]
        print(f"  {tier_key:<26} n={m['n']} hit_rate={m['hit_rate']} mean_dir_ret={m['mean_directional_return']}  {m['note']}")
        for o in m["rows"]:
            print(f"      {o['ts_code']:<11} {o['label']:<12} α={o['alpha_vs_bench']:+.4f} dir_ret={o['directional_return']:+.4f} {'✓' if o['correct'] else '✗'}")
    print("\nForward-alpha availability by horizon (actionable; A:CSI300 / HK:HSI):")
    for h in HORIZONS_TD:
        m = eval_metrics[h]
        print(f"  {h:<5} n_actionable_with_data={m.get('n')}  "
              + (f"hit={m.get('hit_rate')} mean_α={m.get('mean_alpha')} "
                 f"{m.get('WARNING','')}" if m.get('n') else m.get('status', '')))
    print("\nRank IC (quality vs fwd alpha):")
    for h in HORIZONS_TD:
        print(f"  {h:<5} {rank_ic[h]}")
    print("\n5-position attribution (panel-window since entry; A:CSI300 / HK:HSI):")
    for r in pos_attr:
        a = r["attribution"]
        nm = str(r.get("name") or "?"); tk = str(r.get("ticker") or "?"); w = r.get("weight_pct")
        bm = r.get("benchmark")
        algn = r.get("alignment"); flag = " ⚠REVIEW" if r.get("requires_human_review") else ""
        if a.get("status") == "ok":
            print(f"  {nm:<8} {tk:<11} w={w}% vs {bm:<6} "
                  f"total={a['total_return']*100:+.1f}%  β={a['beta']}  "
                  f"resid={a['residual_thesis_alpha']*100:+.1f}%  [{r['position_side']} vs "
                  f"{r['latest_thesis_direction']} → {algn}{flag}]")
        else:
            print(f"  {nm:<8} {tk:<11} w={w}%  → {a.get('status')}  [{algn}{flag}]")
    print(f"\n[core-val] wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
