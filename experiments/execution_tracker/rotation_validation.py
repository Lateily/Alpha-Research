#!/usr/bin/env python3
"""
rotation_validation.py — 轮动实验室推断层(方法论预注册的 Q1-Q3 检验)

回填 N 个交易日的板块-日面板(moneyflow_ind_dc 历史 = PIT 事实),
在跨日数据上跑三个预注册问题 + 双负控制:

  Q1 持续性: HOT 态的 T+1/T+3 存续率(Wilson 95% CI)+ HOT 的前瞻超额
  Q2 龙头广度: HOT ∧ 板块涨停数>=2 vs HOT ∧ <2 的 T+3 超额差
             (Mann-Whitney U, 正态近似, 无 scipy)
  Q3 传导链: 预定义链对 lag1-3 互相关 + BH 校正

负控制: C1 同日横截面标签重排(破坏板块特异性,保留市场日效应)
        C2 特征滞后打乱
诚实边界: 板块-日横截面高相关 => 有效独立样本≈交易日数;一切输出
claim_allowed=false,是描述/校准,不是可交易信号。regime 用"全板块
均值涨跌日"做代理并明示 [proxy]。

缺数 ≠ 0(2026-09 修订):limit_list_d 调用失败或空返回的日子,涨停读数记 None
并写入 rotation_history["limit_up_data_blocked"][d];旧版追加写成 {} 的日子同样按
缺数处理。Q2 与 lead_precursor 校准整日排除并计数(data_coverage / limit_reading),
不用 status 键,避免把本步判 PARTIAL 而跳过 lead_precursor。缺 net_amount /
pct_change 的板块-日直接丢弃并计数(flow_missing_values),不写 0。

不是买卖指令；研究信号，human executes。
"""

import json
import math
import os
import random
import sys
import time
import tushare_rows
from nightly_context import bind, target_trade_date

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "rotation_history.json")
OUT = os.path.join(HERE, "rotation_validation.json")

# 预注册链对(来自两份 Sector OS)。每个节点写成**别名列表** ——
# 数据源里同一条产业链有多个同义名,写死一个就会因该名不存在而整条 DATA_BLOCKED。
# 「光模块(CPO)」这个字面名在 rotation_history 里根本不存在(真名是 光通信模块 /
# CPO概念),于是 Q3 长期缺项,把整个前兆层和轮动检验一起拖住。
# 别名顺序 = 优先级:取第一个在当日数据里存在的名字,并在结果里记下用了哪个。
CHAIN_PAIRS = [
    (["半导体设备"], ["半导体材料"]),
    (["光通信模块", "CPO概念", "光模块(CPO)", "光模块"], ["印制电路板", "PCB"]),
    (["油田服务"], ["油气开采Ⅱ", "油气开采"]),
    (["化学制药"], ["医药流通"]),
    (["黄金"], ["铝"]),
    (["煤炭开采"], ["电力"]),
]


def _resolve(names, sectors):
    """按优先级取第一个真实存在的板块名;都不在则返回 None。"""
    if isinstance(names, str):
        names = [names]
    for n in names:
        if n in sectors:
            return n
    return None
HOT_Q = 0.8                         # 双前1/5分位 [方法论预注册]


def _api(name, token, **params):
    """(rows, None) | (None, reason) — a failed call is never an empty answer."""
    return tushare_rows.fetch_rows(name, token, timeout=40, **params)


# --------------------------------------------------- missing-vs-zero helpers ----
# 涨停读数的三种状态必须分开:真实读数(dict,至少一个行业)/ 调用失败 / 空返回。
# A 股不存在「全市场零涨停」的定盘日,所以空返回同样按 DATA_BLOCKED 处理 ——
# 宁可把一个(理论上的)真零日判成缺数,也不把缺数写成零。
LIMIT_BLOCKED_KEY = "limit_up_data_blocked"
FLOW_MISSING_KEY = "flow_missing_values"


def limit_counts_from_rows(rows, err):
    """limit_list_d 结果 -> (cnt_dict, None) 或 (None, reason)。"""
    if err:
        return None, err
    cnt = {}
    for r in rows or []:
        if r.get("limit") == "U":
            key = r.get("industry") or "?"
            cnt[key] = cnt.get(key, 0) + 1
    if not cnt:
        return None, "EMPTY_LIMIT_LIST_IMPLAUSIBLE_FOR_SETTLED_DAY"
    return cnt, None


def flows_from_rows(rows):
    """moneyflow_ind_dc 行 -> ({name: [net, pct]}, n_dropped)。缺值板块-日直接丢弃,不写 0。"""
    out, dropped = {}, 0
    for r in rows or []:
        name = r.get("name")
        net = tushare_rows.optional_float(r.get("net_amount"))
        pct = tushare_rows.optional_float(r.get("pct_change"))
        if not name or net is None or pct is None:
            dropped += 1
            continue
        out[name] = [net, pct]
    return out, dropped


def limit_reading(hist, d):
    """当日涨停读数:有效 dict 或 None(调用失败 / 空 / 旧版 {} / 缺键 / 显式标记)。"""
    if d in (hist.get(LIMIT_BLOCKED_KEY) or {}):
        return None
    row = (hist.get("limit_up_by_industry") or {}).get(d)
    if not isinstance(row, dict) or not row:
        return None
    return row


def limit_blocked_days(hist):
    return [d for d in hist.get("days", []) if limit_reading(hist, d) is None]


# ------------------------------------------------------------- backfill ----
def backfill(token, n_days=60, end_exclusive=None):
    cal, err = _api("trade_cal", token, exchange="SSE", is_open="1",
                    start_date="20260301", end_date="20301231")
    if err:
        print(f"DATA_BLOCKED: trade_cal 调用失败 {err},回填中止")
        return None
    dates = sorted(r["cal_date"] for r in cal)
    if end_exclusive is None:                     # 默认:只用已定盘日(≤今天)
        import datetime
        end_exclusive = (datetime.datetime.strptime(target_trade_date(), "%Y%m%d").date()
                         + datetime.timedelta(days=1)).strftime("%Y%m%d")
    dates = [d for d in dates if d < end_exclusive]
    days = dates[-n_days:]
    hist, missing = {}, {}
    for d in days:
        rows, err = _api("moneyflow_ind_dc", token, trade_date=d)
        if err or not rows:
            print(f"DATA_BLOCKED: {d} 无板块资金({err or '空返回'}),回填中止")
            return None
        hist[d], dropped = flows_from_rows(rows)
        if dropped:
            missing[d] = dropped
        time.sleep(0.25)
    lim, lim_blocked = {}, {}
    for d in days:
        rows, err = _api("limit_list_d", token, trade_date=d)
        cnt, why = limit_counts_from_rows(rows, err)
        lim[d] = cnt                                # None = DATA_BLOCKED,绝不写 {}
        if why:
            lim_blocked[d] = why
        time.sleep(0.2)
    payload = {"days": days, "flows": hist, "limit_up_by_industry": lim,
               LIMIT_BLOCKED_KEY: lim_blocked, FLOW_MISSING_KEY: missing,
               "built_at_note": "PIT: 全部为历史定盘事实;涨停读数 None=DATA_BLOCKED(非零)"}
    with open(HIST, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    print(f"[backfill] {len(days)} 日 × ~{len(hist[days[-1]])} 板块 → {HIST}"
          f"(涨停缺数 {len(lim_blocked)} 日)")
    return payload


def append_days(hist, token, target, api=None, window=90):
    """夜链追加:只追加已定盘日,滚动保留 window 日。返回 (hist, report) 或 (None, reason)。

    - 目标日资金或涨停读数缺失/失败 ⇒ 整日 SKIP(不推进 days,次晚作为历史日重取);
    - 历史日资金缺失 ⇒ 中止(与旧行为一致,exit 1);
    - 历史日涨停缺失 ⇒ 资金照常追加,涨停读数记 None + limit_up_data_blocked[d]=原因,
      绝不写成 {}(=零涨停)。
    """
    api = api or _api
    cal, err = api("trade_cal", token, exchange="SSE", is_open="1",
                   start_date=hist["days"][-1], end_date=target)
    if err:
        return None, f"trade_cal 调用失败 {err}"
    new_days = sorted(r["cal_date"] for r in cal
                      if r["cal_date"] > hist["days"][-1] and r["cal_date"] <= target)
    hist.setdefault("limit_up_by_industry", {})
    blocked = dict(hist.get(LIMIT_BLOCKED_KEY) or {})
    missing = dict(hist.get(FLOW_MISSING_KEY) or {})
    report = {"appended": [], "skipped": [], "limit_blocked_appended": []}
    for d in new_days:
        rows, err = api("moneyflow_ind_dc", token, trade_date=d)
        if err or not rows:
            if d >= target:
                # 当日尚未定盘(如早晨运行)或调用失败:优雅跳过,晚间/次晚补
                report["skipped"].append({"date": d, "why": f"moneyflow {err or 'EMPTY'}"})
                continue
            return None, f"{d} 历史日无板块资金({err or '空返回'}),追加中止"
        flows, dropped = flows_from_rows(rows)
        lrows, lerr = api("limit_list_d", token, trade_date=d)
        cnt, why = limit_counts_from_rows(lrows, lerr)
        if why and d >= target:
            report["skipped"].append({"date": d, "why": f"limit_list_d {why}"})
            continue
        hist["flows"][d] = flows
        if dropped:
            missing[d] = dropped
        hist["limit_up_by_industry"][d] = cnt
        if why:
            blocked[d] = why
            report["limit_blocked_appended"].append(d)
        hist["days"].append(d)
        report["appended"].append(d)
    hist["days"] = hist["days"][-window:]
    keep = set(hist["days"])
    hist["flows"] = {d: hist["flows"][d] for d in hist["days"]}
    hist["limit_up_by_industry"] = {d: hist["limit_up_by_industry"].get(d)
                                    for d in hist["days"]}
    hist[LIMIT_BLOCKED_KEY] = {d: v for d, v in blocked.items() if d in keep}
    hist[FLOW_MISSING_KEY] = {d: v for d, v in missing.items() if d in keep}
    return hist, report


# ------------------------------------------------------------- stats core ----
def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (p, max(0, c - h), min(1, c + h))


def mann_whitney(a, b):
    """U 检验正态近似;返回 (u, z, p_two_sided)。无 scipy 环境的保守实现。"""
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return (0, 0.0, 1.0)
    allv = sorted((v, 0) for v in a) + sorted((v, 1) for v in b)
    allv.sort(key=lambda x: x[0])
    ranks, i = {}, 0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        r = (i + j + 1) / 2
        for k2 in range(i, j):
            ranks[k2] = r
        i = j
    r1 = sum(ranks[i] for i, (v, g) in enumerate(allv) if g == 0)
    u = r1 - n1 * (n1 + 1) / 2
    mu = n1 * n2 / 2
    sd = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12) or 1e-9
    z = (u - mu) / sd
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return (u, round(z, 2), round(p, 4))


def pearson(x, y):
    n = len(x)
    if n < 3:
        return 0.0
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((v - mx) ** 2 for v in x)) or 1e-9
    sy = math.sqrt(sum((v - my) ** 2 for v in y)) or 1e-9
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def corr_p(r, n):
    if n < 4 or abs(r) >= 1:
        return 1.0
    t = r * math.sqrt((n - 2) / (1 - r * r))
    # t 分布正态近似(n>=30 时可接受;n 小时偏保守方向标注)
    return round(2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2)))), 4)


def bh_correct(pairs_p, alpha=0.10):
    """Benjamini-Hochberg;返回通过的下标集合。"""
    idx = sorted(range(len(pairs_p)), key=lambda i: pairs_p[i])
    m = len(pairs_p)
    passed, thresh_i = set(), -1
    for rank, i in enumerate(idx, 1):
        if pairs_p[i] <= alpha * rank / m:
            thresh_i = rank
    for rank, i in enumerate(idx, 1):
        if rank <= thresh_i:
            passed.add(i)
    return passed


# ------------------------------------------------------------- panel calc ----
def build_states(hist):
    """hist -> per-day: excess5(板块5日累计超额), flow5, HOT set, 前瞻超额序列."""
    days = hist["days"]
    flows = hist["flows"]
    sectors = sorted(set.intersection(*[set(flows[d]) for d in days]))
    exc = {}                                  # (d, s) -> 当日超额
    for d in days:
        mean_pct = sum(flows[d][s][1] for s in sectors) / len(sectors)
        for s in sectors:
            exc[(d, s)] = flows[d][s][1] - mean_pct
    hot = {}                                  # d -> set(sector)
    for i in range(4, len(days)):
        win = days[i - 4:i + 1]
        e5 = {s: sum(exc[(d, s)] for d in win) for s in sectors}
        f5 = {s: sum(flows[d][s][0] for d in win) for s in sectors}
        eq = sorted(e5.values())[int(len(sectors) * HOT_Q)]
        fq = sorted(f5.values())[int(len(sectors) * HOT_Q)]
        hot[days[i]] = {s for s in sectors if e5[s] >= eq and f5[s] >= fq}
    return sectors, exc, hot


def fwd_excess(exc, days, d, s, k):
    i = days.index(d)
    if i + k >= len(days):
        return None
    return sum(exc[(days[j], s)] for j in range(i + 1, i + 1 + k))


def run_q1(hist, sectors, exc, hot, shuffle_labels=False, seed=7):
    days = hist["days"]
    rng = random.Random(seed)
    stay1 = stay3 = tot1 = tot3 = 0
    fwd3_hot, fwd3_all = [], []
    for d in list(hot.keys()):
        i = days.index(d)
        hs = hot[d]
        for s in hs:
            f3 = fwd_excess(exc, days, d, s, 3)
            if shuffle_labels and f3 is not None:
                s2 = rng.choice(sectors)
                f3 = fwd_excess(exc, days, d, s2, 3)
            if i + 1 < len(days) and days[i + 1] in hot:
                tot1 += 1
                stay1 += 1 if s in hot[days[i + 1]] else 0
            if i + 3 < len(days) and days[i + 3] in hot:
                tot3 += 1
                stay3 += 1 if s in hot[days[i + 3]] else 0
            if f3 is not None:
                fwd3_hot.append(f3)
        samp = rng.sample(sectors, min(len(hs), len(sectors)))
        for s in samp:
            f3 = fwd_excess(exc, days, d, s, 3)
            if f3 is not None:
                fwd3_all.append(f3)
    p1, lo1, hi1 = wilson(stay1, tot1)
    p3, lo3, hi3 = wilson(stay3, tot3)
    u, z, pv = mann_whitney(fwd3_hot, fwd3_all)
    return {"persist_T1": {"p": round(p1, 3), "ci": [round(lo1, 3), round(hi1, 3)], "n": tot1},
            "persist_T3": {"p": round(p3, 3), "ci": [round(lo3, 3), round(hi3, 3)], "n": tot3},
            "fwd3_hot_vs_random": {"hot_median": round(sorted(fwd3_hot)[len(fwd3_hot)//2], 2) if fwd3_hot else None,
                                    "rand_median": round(sorted(fwd3_all)[len(fwd3_all)//2], 2) if fwd3_all else None,
                                    "mw_z": z, "mw_p": pv,
                                    "n": [len(fwd3_hot), len(fwd3_all)]}}


def run_q2(hist, sectors, exc, hot):
    days = hist["days"]
    broad, narrow = [], []
    blocked_days = limit_blocked_days(hist)
    excluded_obs = 0
    for d, hs in hot.items():
        lim_d = limit_reading(hist, d)
        for s in hs:
            f3 = fwd_excess(exc, days, d, s, 3)
            if f3 is None:
                continue
            if lim_d is None:
                excluded_obs += 1           # 涨停读数缺失:不判宽/窄,排除并计数
                continue
            n_lim = 0
            for ind, c in lim_d.items():
                if ind and (ind in s or s in ind):
                    n_lim = c
                    break
            (broad if n_lim >= 2 else narrow).append(f3)
    u, z, pv = mann_whitney(broad, narrow)
    med = lambda a: round(sorted(a)[len(a)//2], 2) if a else None
    return {"broad_n": len(broad), "narrow_n": len(narrow),
            "broad_med_fwd3": med(broad), "narrow_med_fwd3": med(narrow),
            "mw_z": z, "mw_p": pv,
            "limit_reading": {"blocked_days_n": len(blocked_days),
                              "valid_days_n": len(days) - len(blocked_days),
                              "blocked_days": blocked_days,
                              "excluded_hot_obs_n": excluded_obs,
                              "basis": "涨停读数缺失(调用失败/空返回/旧版{})的日子不参与宽窄划分"},
            "note": "广度=板块名匹配的当日涨停数>=2 [行业名跨表模糊匹配,匹配失败按narrow计;"
                    "涨停读数缺失日整日排除,不按 0 计]"}


def run_q3(hist, sectors, exc, lag_shuffle=False, seed=11):
    days = hist["days"]
    rng = random.Random(seed)
    results, pvals = [], []
    for a_names, b_names in CHAIN_PAIRS:
        a, b = _resolve(a_names, sectors), _resolve(b_names, sectors)
        label = f"{(a_names if isinstance(a_names, str) else a_names[0])}->" \
                f"{(b_names if isinstance(b_names, str) else b_names[0])}"
        if a is None or b is None:
            miss = [n for n, r in ((a_names, a), (b_names, b)) if r is None]
            results.append({"pair": label,
                            "status": f"DATA_BLOCKED: 板块名缺失,所有别名均不在数据源 {miss}"})
            pvals.append(1.0)
            continue
        xa = [exc[(d, a)] for d in days]
        xb = [exc[(d, b)] for d in days]
        if lag_shuffle:
            rng.shuffle(xa)
        best = max(((lag, pearson(xa[:-lag], xb[lag:])) for lag in (1, 2, 3)),
                   key=lambda t: abs(t[1]))
        p = corr_p(best[1], len(days) - best[0])
        results.append({"pair": label, "resolved": f"{a}->{b}", "best_lag": best[0],
                        "r": round(best[1], 3), "p": p})
        pvals.append(p)
    passed = bh_correct(pvals)
    for i, r in enumerate(results):
        r["bh_pass_10pct"] = i in passed
    return results


def validate(hist):
    sectors, exc, hot = build_states(hist)
    q1 = run_q1(hist, sectors, exc, hot)
    c1 = run_q1(hist, sectors, exc, hot, shuffle_labels=True)
    q2 = run_q2(hist, sectors, exc, hot)
    q3 = run_q3(hist, sectors, exc)
    c2 = run_q3(hist, sectors, exc, lag_shuffle=True)
    blocked = limit_blocked_days(hist)
    return {"window": [hist["days"][0], hist["days"][-1]],
            "n_days": len(hist["days"]), "n_sectors": len(sectors),
            # 计数不用 status 键:整窗旧数据里有缺数日是常态,不能让 run_nightly 把
            # 本步判 PARTIAL 进而跳过 lead_precursor —— 缺数在这里如实计数、在 Q2 里排除。
            "data_coverage": {
                "limit_up_blocked_days_n": len(blocked),
                "limit_up_valid_days_n": len(hist["days"]) - len(blocked),
                "limit_up_blocked_days": blocked,
                "flow_missing_value_sector_days_n": sum(
                    int(v or 0) for d, v in (hist.get(FLOW_MISSING_KEY) or {}).items()
                    if d in set(hist["days"])),
                "legacy_note": "2026-09 之前追加的日子里,调用失败被写成 {};这里一律按缺数处理。",
            },
            "effective_n_note": "横截面高相关,有效独立样本≈交易日数",
            "Q1_persistence": q1,
            "C1_label_shuffle_control": c1,
            "Q2_leader_breadth": q2,
            "Q3_chain_leadlag": q3,
            "C2_lag_shuffle_control": [r for r in c2 if "r" in r][:3],
            "claim_allowed": False,
            "note": "描述/校准统计;真实信号须显著优于双负控制且跨窗稳定,"
                    "才有资格进入 paper 前瞻判分。不是买卖指令。"}


def selftest():
    ok = []

    def ck(name, cond):
        ok.append((name, bool(cond)))
        print(("  ✓ " if cond else "  ✗ ") + name)

    # 合成:板块P持续强(自相关),板块群N=噪声
    rng = random.Random(3)
    days = [f"d{i:02d}" for i in range(30)]
    flows = {}
    for i, d in enumerate(days):
        row = {}
        for s in [f"N{k}" for k in range(18)]:
            row[s] = [rng.uniform(-1, 1), rng.gauss(0, 1)]
        row["P"] = [2.0, 1.5 + 0.3 * rng.random()]      # 持续正流入+正超额
        flows[d] = row
    hist = {"days": days, "flows": flows, "limit_up_by_industry":
            {d: {"P": 3} for d in days}}
    sectors, exc, hot = build_states(hist)
    ck("HOT 态被识别且含持续板块 P",
       any("P" in hs for hs in hot.values()))
    q1 = run_q1(hist, sectors, exc, hot)
    ck("Q1 输出 Wilson CI 结构", "ci" in q1["persist_T1"] and q1["persist_T1"]["n"] > 0)
    ck("持续板块使 T1 存续率显著>0", q1["persist_T1"]["p"] > 0)
    c1 = run_q1(hist, sectors, exc, hot, shuffle_labels=True)
    ck("负控制C1可运行且结构同型", "persist_T1" in c1)
    ck("Wilson 边界: k=0", wilson(0, 10)[0] == 0.0)
    u, z, p = mann_whitney([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
    ck("MW 同分布 p 不显著", p > 0.5)
    u, z, p = mann_whitney([10, 11, 12, 13], [1, 2, 3, 4])
    ck("MW 分离分布 p 显著", p < 0.05)
    ck("BH 校正: 全1不通过", bh_correct([1.0, 1.0, 0.9]) == set())
    ck("BH 校正: 强p通过", 0 in bh_correct([0.001, 0.9, 0.8]))
    v = validate(hist)
    ck("validate 全结构 + claim_allowed=false",
       v["claim_allowed"] is False and "Q3_chain_leadlag" in v)
    passed = sum(1 for _, c in ok if c)
    print(f"rotation_validation selftest: {passed}/{len(ok)}")
    return passed == len(ok)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("DATA_BLOCKED: NO TUSHARE_TOKEN")
        sys.exit(1)
    if "--append" in sys.argv and os.path.exists(HIST):
        # 夜链模式:只追加最新定盘日,滚动保留 90 日
        hist = json.load(open(HIST))
        hist, report = append_days(hist, token, target_trade_date())
        if hist is None:
            print(f"DATA_BLOCKED: {report}")
            sys.exit(1)
        with open(HIST, "w", encoding="utf-8") as fh:
            json.dump(hist, fh, ensure_ascii=False)
        for item in report["skipped"]:
            print(f"SKIP: {item['date']} {item['why']}(晚间/次晚补)")
        for d in report["limit_blocked_appended"]:
            print(f"  WARN {d} 涨停读数 DATA_BLOCKED({hist[LIMIT_BLOCKED_KEY][d]}),"
                  "资金照常追加,Q2 排除该日")
        print(f"[append] +{len(report['appended'])} 日,滚动窗 {len(hist['days'])} 日")
    elif "--backfill" in sys.argv or not os.path.exists(HIST):
        if backfill(token) is None:
            sys.exit(1)
    hist = json.load(open(HIST))
    v = bind(validate(hist), target=hist["days"][-1])
    v["as_of"] = hist["days"][-1]
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(v, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: v[k] for k in ("window", "n_days", "n_sectors",
                                        "Q1_persistence", "Q2_leader_breadth")},
                     ensure_ascii=False, indent=1))
    print("Q3:", json.dumps(v["Q3_chain_leadlag"], ensure_ascii=False)[:400])
    print(f"[written] {OUT}\n不是买卖指令；研究信号，human executes.")


if __name__ == "__main__":
    main()
