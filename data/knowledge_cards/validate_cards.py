#!/usr/bin/env python3
"""Dependency-free validator for AR knowledge cards v1 (mirrors knowledge_card.schema.json)."""
import json, re, sys
from pathlib import Path

REQ = ["card_id","sub_sector","variable","why_it_matters","data_source","judgment_logic",
       "evidence_tier","literature","falsification","channel_binding","status","authored_by","reviewed_by","as_of"]
SUB = {"MATERIALS","EQUIPMENT","DESIGN","FOUNDRY","OSAT"}
AVAIL = {"AUTO","SEMI","MANUAL"}
LOGIC = {"THRESHOLD","TREND","STAGE_LADDER","RATIO_VS_PEER","CYCLE_POSITION"}
TIER = {"E1","E2"}
CH = {"E1_EVENT","PRICE_VOLUME","FUND_FLOW_CHIPS","FUNDAMENTAL_VALUATION","INDUSTRY_VALUE_CHAIN","MACRO_CROSS_ASSET",
      "BATTERY_基本面","BATTERY_估值","BATTERY_消息面","BATTERY_资金","BATTERY_技术面","BATTERY_行情","LLM_MUST_CHECK"}
STATUS = {"DRAFT","REVIEWED","ENCODED","VALIDATED","RETIRED"}

def check(card, i):
    e = []
    p = f"card[{i}]"
    for k in REQ:
        if k not in card: e.append(f"{p}: missing {k}")
    if e: return e
    if not re.fullmatch(r"SEMI_(MAT|EQP|DSN|FDY|OSAT)_\d{3}", card["card_id"]): e.append(f"{p}: bad card_id {card['card_id']}")
    if card["sub_sector"] not in SUB: e.append(f"{p}: bad sub_sector")
    if len(card["why_it_matters"]) < 20: e.append(f"{p}: why_it_matters too short")
    ds = card["data_source"]
    for k in ["availability","primary","tushare_api","tushare_field","manual_required"]:
        if k not in ds: e.append(f"{p}: data_source missing {k}")
    if ds.get("availability") not in AVAIL: e.append(f"{p}: bad availability")
    if ds.get("availability") == "AUTO" and not ds.get("tushare_field"): e.append(f"{p}: AUTO requires tushare_field")
    if ds.get("availability") == "MANUAL" and ds.get("manual_required") is not True: e.append(f"{p}: MANUAL must set manual_required=true")
    jl = card["judgment_logic"]
    for k in ["type","positive_if","negative_if","lookback"]:
        if k not in jl: e.append(f"{p}: judgment_logic missing {k}")
    if jl.get("type") not in LOGIC: e.append(f"{p}: bad logic type")
    if jl.get("type") == "STAGE_LADDER" and not jl.get("stages"): e.append(f"{p}: STAGE_LADDER needs stages")
    if card["evidence_tier"] not in TIER: e.append(f"{p}: bad tier")
    if not card["literature"] or not all(isinstance(x,str) and x.strip() for x in card["literature"]): e.append(f"{p}: literature must be non-empty strings")
    if len(card["falsification"]) < 10: e.append(f"{p}: falsification too short")
    if not card["channel_binding"] or not set(card["channel_binding"]) <= CH: e.append(f"{p}: bad channel_binding")
    if card["status"] not in STATUS: e.append(f"{p}: bad status")
    if not re.fullmatch(r"\d{8}", card["as_of"]): e.append(f"{p}: as_of must be YYYYMMDD")
    if card["status"] != "DRAFT" and not card["reviewed_by"]: e.append(f"{p}: non-DRAFT requires reviewed_by")
    return e

def main(path):
    cards = json.loads(Path(path).read_text())
    if not isinstance(cards, list): print("top-level must be array"); return 2
    ids = [c.get("card_id") for c in cards]
    errs = []
    if len(ids) != len(set(ids)): errs.append("duplicate card_id")
    for i, c in enumerate(cards): errs += check(c, i)
    for x in errs: print("ERR", x)
    n_auto = sum(1 for c in cards if c["data_source"]["availability"]=="AUTO")
    print(f"{'OK' if not errs else 'FAIL'}: {len(cards)} cards, AUTO={n_auto}, "
          f"by status={ {s: sum(1 for c in cards if c['status']==s) for s in STATUS if any(c['status']==s for c in cards)} }")
    return 0 if not errs else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "semiconductor_materials.json"))
