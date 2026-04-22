#!/usr/bin/env python3
"""
Local output verification script — run after fetch_data.py to sanity-check
all generated JSON files.

Usage: python scripts/verify_outputs.py
"""

import json, sys
from pathlib import Path

DATA = Path("public/data")

OK   = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m⚠\033[0m"

def check(label, condition, msg=""):
    icon = OK if condition else FAIL
    print(f"  {icon}  {label}" + (f"  [{msg}]" if msg else ""))
    return condition


# ── RDCF ──────────────────────────────────────────────────────────────────────
print("\n=== Reverse DCF (rdcf_*.json) ===")
rdcf_tickers = ["300308_SZ", "700_HK", "9999_HK", "6160_HK", "002594_SZ"]
for safe_id in rdcf_tickers:
    path = DATA / f"rdcf_{safe_id}.json"
    if not path.exists():
        print(f"  {FAIL}  {safe_id}: FILE MISSING")
        continue
    d = json.loads(path.read_text())
    ticker = d.get("ticker", safe_id)
    err = d.get("error")
    if err:
        print(f"  {WARN}  {ticker}: error={err}")
        continue
    model = d.get("model_type", "?")
    signal = d.get("signal", "?")
    delta  = d.get("delta")
    score  = d.get("expectation_gap_score")
    wacc   = d.get("wacc_detail", {}).get("wacc")

    if model == "standard_fcf":
        impl  = d.get("implied_fcf_growth")
        our   = d.get("our_fcf_growth")
        g_label = "FCF"
    else:
        impl  = d.get("implied_rev_growth")
        our   = d.get("our_rev_growth")
        g_label = "Rev"

    print(f"  {OK}  {ticker:12s}  signal={signal:13s}  "
          f"implied {g_label}={impl:.1%}  our={our:.1%}  "
          f"δ={delta:+.1%}  gap={score:.0f}/100  WACC={wacc:.1%}")


# ── Stress test ────────────────────────────────────────────────────────────────
print("\n=== Stress Test (stress_test.json) ===")
st_path = DATA / "stress_test.json"
if st_path.exists():
    st = json.loads(st_path.read_text())
    worst   = st.get("worst_scenario", "?")
    exp_ret = st.get("expected_portfolio_return", 0)
    print(f"  {OK}  Expected portfolio return: {exp_ret:+.1%}")
    for k, v in st.get("scenarios", {}).items():
        ret = v["portfolio_return"]
        icon = "⬆" if ret > 0 else "⬇"
        print(f"       {icon} {k:22s}: {ret:+.1%}  (p={v['probability']:.0%})")
    print(f"       Worst case: {worst}")
else:
    print(f"  {FAIL}  stress_test.json missing")


# ── EQR ───────────────────────────────────────────────────────────────────────
print("\n=== EQR Ratings (eqr_*.json) ===")
eqr_ids = ["300308_SZ", "700_HK", "9999_HK", "6160_HK", "002594_SZ"]
for safe_id in eqr_ids:
    path = DATA / f"eqr_{safe_id}.json"
    if not path.exists():
        print(f"  {FAIL}  {safe_id}: FILE MISSING")
        continue
    d = json.loads(path.read_text())
    overall = d.get("overall", "?")
    gen_at  = d.get("generated_at", "")[:10]
    print(f"  {OK}  {d.get('ticker', safe_id):12s}  overall={overall:8s}  generated={gen_at}")


# ── Prediction log ─────────────────────────────────────────────────────────────
print("\n=== Prediction Log (prediction_log.json) ===")
pl_path = DATA / "prediction_log.json"
if pl_path.exists():
    pl = json.loads(pl_path.read_text())
    preds = pl.get("predictions", [])
    resolved = [p for p in preds if p["status"] in ("VERIFIED","FALSIFIED","INCONCLUSIVE")]
    open_p   = [p for p in preds if p["status"] == "OPEN"]
    if resolved:
        hits = sum(1 for p in resolved if p["status"] == "VERIFIED")
        rate = hits / len(resolved) * 100
        print(f"  {OK}  Hit rate: {hits}/{len(resolved)} = {rate:.0f}%")
    else:
        print(f"  {WARN}  No resolved predictions yet")
    for p in preds:
        icon = {"OPEN":"○","VERIFIED":OK,"FALSIFIED":FAIL,"INCONCLUSIVE":"?"}.get(p["status"],"?")
        print(f"       {icon}  {p['id']}  {p['ticker']:12s}  {p['status']:12s}  target={p['target_date']}")
else:
    print(f"  {FAIL}  prediction_log.json missing")


print("\n" + "="*60)
print("Tip: fields to use in rdcf JSON:")
print("  implied growth : implied_fcf_growth  (standard) / implied_rev_growth (biotech)")
print("  our estimate   : our_fcf_growth       (standard) / our_rev_growth      (biotech)")
print("  gap            : delta (float), expectation_gap_score (0-100)")
print("  WACC           : wacc_detail.wacc")
print("  NO scipy needed: pure-Python bisection is built-in")
