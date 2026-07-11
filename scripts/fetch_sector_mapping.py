#!/usr/bin/env python3
"""
Fetch A-share industry classification (ts_code → sector) via Tushare.

Writes data_history/sector_mapping.json with BOTH:
  - SW2021 L1 (preferred; pro.index_classify + pro.index_member, ~30 calls)
  - Tushare-native industry (always available, single stock_basic call)

The 'primary' field flags which to use downstream. SWING_STRATEGY_v1.md §2.2.

Run:
  python3 scripts/fetch_sector_mapping.py
  python3 scripts/fetch_sector_mapping.py --selftest    # reload + print distribution
  python3 scripts/fetch_sector_mapping.py --out PATH.json
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_OUT = Path(__file__).parent.parent / "data_history" / "sector_mapping.json"


def _load_token():
    tok = os.environ.get("TUSHARE_TOKEN", "").strip()
    if tok:
        return tok
    tok_file = Path(__file__).parent.parent / "secrets" / "tushare_token.txt"
    if tok_file.exists():
        return tok_file.read_text().strip()
    return ""


def fetch_sw_l1(pro):
    """Return ts_code → sw_l1_name dict. {} on failure."""
    try:
        l1 = pro.index_classify(level="L1", src="SW2021")
    except Exception as exc:
        print(f"  SW2021 L1 fetch failed: {exc}")
        return {}
    if l1 is None or len(l1) == 0:
        return {}
    print(f"  got {len(l1)} L1 indices; fetching members…")

    sw_map = {}
    for i, row in l1.iterrows():
        code, name = row["index_code"], row["industry_name"]
        members = None
        for attempt in range(3):
            try:
                members = pro.index_member(index_code=code)
                break
            except Exception as exc:
                if attempt == 2:
                    print(f"    fail {name} ({code}): {exc}")
                time.sleep(1.2)
        if members is None or len(members) == 0:
            continue
        for _, m in members.iterrows():
            out_date = m.get("out_date", None)
            # current member if out_date is empty/None/NaN
            still_in = (out_date is None or
                        (isinstance(out_date, str) and out_date == "") or
                        (hasattr(out_date, "__class__") and
                         out_date.__class__.__name__ == "NaTType"))
            if still_in:
                sw_map[m["con_code"]] = name
            else:
                sw_map.setdefault(m["con_code"], name)
        if (i + 1) % 5 == 0:
            print(f"    {i+1}/{len(l1)} sectors, {len(sw_map)} tickers")
    return sw_map


def build(basic_df, sw_map):
    tickers, sec_t, sec_sw = {}, {}, {}
    for _, r in basic_df.iterrows():
        ts_code = r["ts_code"]
        ind_t = r.get("industry") or ""
        ind_sw = sw_map.get(ts_code, "")
        tickers[ts_code] = {
            "name": r.get("name") or "",
            "industry_tushare": ind_t,
            "industry_sw_l1": ind_sw,
            "area": r.get("area") or "",
            "market": r.get("market") or "",
            "list_date": r.get("list_date") or "",
        }
        if ind_t:
            sec_t.setdefault(ind_t, []).append(ts_code)
        if ind_sw:
            sec_sw.setdefault(ind_sw, []).append(ts_code)
    # SW-only tickers (delisted historicals beyond list_status='L')
    for ts_code, ind_sw in sw_map.items():
        if ts_code not in tickers:
            tickers[ts_code] = {
                "name": "", "industry_tushare": "", "industry_sw_l1": ind_sw,
                "area": "", "market": "", "list_date": "",
                "_note": "sw_only_not_in_stock_basic_L",
            }
            sec_sw.setdefault(ind_sw, []).append(ts_code)

    listed_n = len(basic_df)
    sw_listed = sum(1 for t in basic_df["ts_code"] if t in sw_map)
    sw_cov = sw_listed / listed_n if listed_n else 0
    primary = "sw_l1" if sw_cov >= 0.80 else "tushare_industry"

    def bundle(d):
        return {n: {"members": sorted(set(m)), "n": len(set(m))}
                for n, m in d.items()}
    return tickers, bundle(sec_t), bundle(sec_sw), primary, sw_cov


def print_dist(label, sectors, top=15):
    print(f"\n=== {label} — top {top} of {len(sectors)} sectors ===")
    for name, info in sorted(sectors.items(), key=lambda kv: -kv[1]["n"])[:top]:
        print(f"  {name:20s} n={info['n']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--selftest", action="store_true",
                    help="Reload existing --out and print distribution.")
    args = ap.parse_args()
    out = Path(args.out)

    if args.selftest:
        if not out.exists():
            print(f"ERROR: {out} not found; fetch first.", file=sys.stderr); return 1
        obj = json.loads(out.read_text(encoding="utf-8"))
        print(f"_meta: {json.dumps(obj.get('_meta', {}), ensure_ascii=False)}")
        if obj.get("sectors_sw_l1"):
            print_dist("SW L1", obj["sectors_sw_l1"])
        if obj.get("sectors_tushare"):
            print_dist("Tushare industry", obj["sectors_tushare"])
        return 0

    token = _load_token()
    if not token:
        print("ERROR: TUSHARE_TOKEN not set (env or secrets/tushare_token.txt)", file=sys.stderr); return 1
    try:
        import tushare as ts
    except ImportError:
        print("ERROR: pip3 install tushare", file=sys.stderr); return 1

    ts.set_token(token)
    pro = ts.pro_api()

    print("[1/2] pro.stock_basic — Tushare-native industry…")
    basic = pro.stock_basic(exchange="", list_status="L",
                            fields="ts_code,name,industry,area,market,list_date")
    print(f"  got {len(basic)} listed A-shares")

    print("[2/2] pro.index_classify(SW2021,L1) + index_member…")
    sw_map = fetch_sw_l1(pro)
    print(f"  SW L1 mapped {len(sw_map)} tickers")

    tickers, sec_t, sec_sw, primary, sw_cov = build(basic, sw_map)

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Tushare pro.stock_basic + (pro.index_classify SW2021 L1 + index_member)",
        "n_tickers": len(tickers),
        "n_sectors_tushare": len(sec_t),
        "n_sectors_sw_l1": len(sec_sw),
        "sw_l1_coverage_pct_of_listed": round(sw_cov * 100, 2),
        "primary": primary,
        "primary_note": "use 'industry_sw_l1' if primary==sw_l1, else 'industry_tushare'",
        "schema_version": 1,
    }
    obj = {"_meta": meta, "tickers": tickers,
           "sectors_sw_l1": sec_sw, "sectors_tushare": sec_t}

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")
    print(f"_meta: {json.dumps(meta, ensure_ascii=False, indent=2)}")
    if sec_sw:
        print_dist("SW L1", sec_sw)
    print_dist("Tushare-native industry", sec_t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
