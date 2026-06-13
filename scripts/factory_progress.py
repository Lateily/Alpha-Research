#!/usr/bin/env python3
"""factory_progress.py — aggregate committed factory artifacts into one progress JSON
so the platform can visualize where every line of work stands (Junyan 2026-06-12 ask:
real-time progress tracking in the product).

READ-ONLY over committed artifacts (ledger / scan / quant verdicts / watchlist);
writes only public/data/factory_progress.json. The MILESTONES timeline is maintained
here PR-by-PR (same staleness discipline as STATUS.md — update it when shipping).

Usage:
  python3 scripts/factory_progress.py            # generate
  python3 scripts/factory_progress.py --selftest
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
OUT = D / "factory_progress.json"

DISCLAIMER = ("internal progress dashboard — UNVALIDATED research pipeline state; "
              "nothing here is a recommendation, a buy list, or validated alpha")

# maintained PR-by-PR (newest first) — keep ≤14 entries, prune the tail
MILESTONES = [
    {"date": "2026-06-13", "pr": None, "label_zh": "BYD 从 ACTIVE checkpoint 样本移除;Core full-market screen 重跑(加 stale-price hard filter)", "label_en": "BYD archived from ACTIVE checkpoints; Core full-market screen rerun with stale-price hard filter"},
    {"date": "2026-06-13", "pr": 73, "label_zh": "V2-PEAD 终裁 RATIFIED:v2a/v2b KILL · v2c NO-CLAIM;信号≈随机对照;book 半空(事件密度=容量上限)", "label_en": "V2-PEAD RATIFIED: KILL/NO-CLAIM — signal ≈ random control; event density caps capacity"},
    {"date": "2026-06-12", "pr": 72, "label_zh": "Quant v2 SPEC(V2-PEAD 预注册)+ 60图知识库整合裁决 — 等 ratify", "label_en": "Quant v2 spec (V2-PEAD pre-registration) + KB integration verdict — awaiting ratification"},
    {"date": "2026-06-12", "pr": 71, "label_zh": "华海+鼎龙注册进 checkpoint ledger — 3 票 ACTIVE,前向验证 LIVE", "label_en": "Huahai + Dinglong registered — 3 ACTIVE, forward validation LIVE"},
    {"date": "2026-06-12", "pr": 70, "label_zh": "ohlc tushare 日线回退(新票价格盲区修复)", "label_en": "ohlc tushare daily-bars fallback"},
    {"date": "2026-06-12", "pr": 66, "label_zh": "checkpoint 注册机械上线(红队绑定 + 30/60/90)+ 3 个审计修复", "label_en": "Checkpoint machinery live (red-team-gated, 30/60/90) + 3 audit fixes"},
    {"date": "2026-06-12", "pr": 69, "label_zh": "batch-1 决策书双 PASS(华海 84.4 / 鼎龙 82.6)— 双 WATCH_ONLY", "label_en": "Batch-1 sheets double PASS (84.4 / 82.6) — both WATCH_ONLY"},
    {"date": "2026-06-11", "pr": 68, "label_zh": "Serenity Scan #1 A股AI半导体:22名池/top-5/提名 #2#3", "label_en": "Serenity Scan #1: 22-name pool / top-5 / ticker #2#3 nominations"},
    {"date": "2026-06-11", "pr": 67, "label_zh": "Serenity 方法论并入 Factory A 发现层(三把锁 ratified)", "label_en": "Serenity methodology integrated as the discovery layer (three locks ratified)"},
    {"date": "2026-06-11", "pr": 64, "label_zh": "CTF v1 样本 #1 BYD 决策书(红队 71.8 PASS-LOW)", "label_en": "CTF v1 sample #1 BYD sheet (red team 71.8 PASS-LOW)"},
    {"date": "2026-06-10", "pr": 61, "label_zh": "C1 低换手 tilt 家族 = NO-CLAIM(胜随机对照,CI 跨零)→ quant 线暂停", "label_en": "C1 low-turnover tilt = NO-CLAIM → quant line paused"},
    {"date": "2026-06-09", "pr": 57, "label_zh": "H1 技术择时正式 KILL(α −23%/yr,0/5 WF)— 工厂保留", "label_en": "H1 technical timing formally KILLED — factory kept"},
    {"date": "2026-06-09", "pr": 51, "label_zh": "两工厂分立:研究工厂 vs 交易工厂(验证机械共用)", "label_en": "Two-factory split: research vs trading"},
    {"date": "2026-06-07", "pr": None, "label_zh": "产品转向:每日模型组合 Pilot(unvalidated,验证闭环为卖点)", "label_en": "Product pivot: Daily Model Portfolio Pilot"},
]

QUANT_FAMILIES = [
    {"id": "H1", "name_zh": "H1 技术择时(MA200+RSI 回调)", "verdict": "KILL",
     "date": "2026-06-09", "key_number": "α −23.0%/yr (CI [−31.2,−15.2]) · 0/5 WF · 差于超卖对照",
     "doc": "docs/strategy/QUANT_V0_VERDICT_2026-06-09.md"},
    {"id": "C1", "name_zh": "C1 低换手 quality+low_vol tilt (K=20)", "verdict": "NO-CLAIM",
     "date": "2026-06-10", "key_number": "vs EW +6~+8% 点估计但 CI 跨零 · 决定性胜随机对照 · 换手 1.57-1.80×",
     "doc": "docs/strategy/QUANT_C1_VERDICT_2026-06-10.md"},
    {"id": "V2-PEAD", "name_zh": "V2 盈余公告后漂移(自历史 SUE,事件驱动)", "verdict": "KILL (v2a/v2b) · NO-CLAIM (v2c) — RATIFIED 2026-06-13",
     "date": "2026-06-12", "key_number": "v2a/v2b 双基准显著负(−11.6%/−10.8% vs CSI300)· v2c 跨零 · 0/5 WF · 信号与随机对照无差 → 事件雷达资格不满足",
     "doc": "docs/strategy/QUANT_V2_VERDICT_2026-06-12.md"},
]


def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def build(today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    led = _load(D / "decision_sheet_checkpoints.json", {}) or {}
    regs = []
    next_read = None
    for r in led.get("registrations", []):
        rt = r.get("human_red_team") or {}
        cps = []
        for c in r.get("checkpoints", []):
            try:
                dd = (date.fromisoformat(c["due_date"]) - today).days
            except Exception:
                dd = None
            cps.append({"offset_days": c.get("offset_days"), "due_date": c.get("due_date"),
                        "status": c.get("status"), "days_to_due": dd})
            if r.get("status") == "ACTIVE" and c.get("status") == "PENDING" and dd is not None:
                if next_read is None or c["due_date"] < next_read["date"]:
                    next_read = {"date": c["due_date"], "ticker": r.get("ticker"), "days_to_due": dd}
        regs.append({
            "ticker": r.get("ticker"), "name": r.get("name"), "status": r.get("status"),
            "lock8": (r.get("content_lock") or "")[:8],
            "redteam_avg": rt.get("average"), "redteam_verdict": rt.get("verdict"),
            "stance": r.get("stance_at_registration"), "conviction": r.get("conviction_at_registration"),
            "direction": r.get("direction"), "reference_price": r.get("reference_price"),
            "checkpoints": cps,
        })

    scan = _load(D.parent.parent / "docs" / "research" / "serenity" / "scan_1_scores.json", {}) or {}
    discovery = {
        "scan_id": scan.get("scan_id"), "theme": scan.get("theme"), "scan_date": scan.get("scan_date"),
        "status": "MERGED (#68) — nominations ratified",
        "pool_n": len(scan.get("pool", [])), "layers_n": len(scan.get("layers_ranked", [])),
        "top5": [{"ticker": t.get("ticker"), "name": t.get("name"),
                  "score": t.get("serenity_score"), "tier": t.get("tier")} for t in scan.get("top5", [])],
        "nominated": [v.get("ticker") for k, v in (scan.get("nominations") or {}).items()
                      if k in ("ticker_2", "ticker_3") and isinstance(v, dict)],
        "forward_review_dates": (scan.get("forward_checkpoints") or {}).get("review_dates"),
        "label": scan.get("label"),
    }

    wl = _load(D / "watchlist.json", {}) or {}
    return {
        "_meta": {"generated_at": datetime.now(timezone.utc).isoformat(),
                  "layer": "Factory Progress aggregator (read-only over committed artifacts)",
                  "disclaimer": DISCLAIMER},
        "factory_a": {"title_zh": "研究工厂(Core Thesis + 前向验证)",
                      "n_active": led.get("_meta", {}).get("n_active"),
                      "registrations": regs, "next_read": next_read,
                      "note_zh": "人工红队为 measure of record;检查点是 case-level 读数,不是统计"},
        "discovery": discovery,
        "factory_b": {"title_zh": "交易工厂(Quant Strategy)",
                      "line_status_zh": "V2-PEAD 终裁:v2a/v2b KILL · v2c NO-CLAIM(无 paper 无雷达)— 5 家族 0 幸存,工厂 KEEP;quant 线暂停,V3(倾向业绩预告事件)需新 manifest + Junyan call",
                      "families": QUANT_FAMILIES},
        "watch_universe": {"n_tickers": len(wl.get("tickers", {})), "tickers": list(wl.get("tickers", {}).keys())},
        "milestones": MILESTONES,
    }


def _selftest() -> int:
    errs = []
    snap = build(today=date(2026, 6, 12))
    fa = snap["factory_a"]
    if fa["n_active"] is not None and fa["n_active"] != sum(1 for r in fa["registrations"] if r["status"] == "ACTIVE"):
        errs.append("n_active must equal ACTIVE registrations")
    if fa["registrations"] and fa["next_read"] is None:
        errs.append("next_read must exist when ACTIVE registrations have PENDING checkpoints")
    if fa["next_read"]:
        dues = [c["due_date"] for r in fa["registrations"] if r["status"] == "ACTIVE"
                for c in r["checkpoints"] if c["status"] == "PENDING"]
        if dues and fa["next_read"]["date"] != min(dues):
            errs.append(f"next_read {fa['next_read']['date']} is not the earliest pending due {min(dues)}")
    if not any(f["verdict"] == "KILL" for f in snap["factory_b"]["families"]):
        errs.append("family history must keep the KILL record visible (honesty: dead families stay on the board)")
    if "UNVALIDATED" not in snap["_meta"]["disclaimer"].upper():
        errs.append("disclaimer must carry UNVALIDATED")
    if errs:
        print("factory_progress selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("factory_progress selftest PASSED (n_active consistent; next_read = earliest pending due; "
          "KILLed families stay visible; unvalidated disclaimer present)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    snap = build()
    OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=2))
    nr = snap["factory_a"]["next_read"]
    print(f"[factory-progress] wrote {OUT} | A: {snap['factory_a']['n_active']} ACTIVE, next read "
          f"{nr['date'] if nr else 'n/a'} | B: {snap['factory_b']['families'][-1]['id']} "
          f"{snap['factory_b']['families'][-1]['verdict']} | milestones: {len(snap['milestones'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
