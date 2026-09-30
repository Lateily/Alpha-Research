#!/usr/bin/env python3
"""红旗闸门 v1 — 任何名单产出前的强制 E1 最低核查(与 E1 事件层同一套判定函数)。

失败案例驱动:2026-07-27 赛力斯(601127.SH)带着 8 天前的中报首亏预告
(-15~-18亿)被放进 ✅核心 名单。本闸门的回归测试就是这个案例。

v1(2026-09-29 复审 P1 #2/#3 修正):判定不再在本文件里另写一套,而是调用
experiments/research_funnel/e1_event_layer.classify_ticker —— 与全市场 E1 事件层
(R036_E1_RULES_V1,修订 RULE_REVISION)同一套判定函数:相同的行必得相同的判定。
注意取数窗口不同(本闸门按公告日回看 800 天;批量层只取 as_of 前 4 个报告期),
所以输入本身可能不同 —— 例如本闸门能看到 as_of 之后报告期的预告,批量层看不到。
  - 快报 yoy_net_profit 是「上年同期净利润金额」,不是百分比;同比取 yoy_dedu_np,
    否则用 (n_income - yoy_net_profit)/|yoy_net_profit| 计算(旧版把
    -74,400,964.91 元读成 -74400965% 的误杀就此消失)。
  - 已披露的正式财报(同期或更晚报告期)取代预告/快报;其余每个未被取代的报告期
    各取最新公告逐一判定,任一期为负面即红旗(晚一期的预增不能掩盖更早一期的首亏)。
  - 最新已披露期早于「法定披露截止日已过的最近一期」→ DATA_BLOCKED
    (FILED_PERIOD_STALE),不拿一年前的季度判 PASS。
  - 季度规则锚定「最新已披露期」与其日历相邻上一季;归母净利为空/NaN →
    DATA_BLOCKED(INCOME_VALUE_MISSING),缺期 → DATA_BLOCKED,绝不 PASS,
    也绝不退回更旧的一对季度。
  - 空值预告/快报行不算证据(不可评分 → DATA_BLOCKED)。

对外输出键保持兼容:verdict ∈ {PASS, RED_FLAG, DATA_BLOCKED}(E1 的
NO_RED_FLAG_FOUND 映射为 PASS)、reasons(可读文本,前缀仍为 最新预告 /
最新快报净利同比 / 最近季度归母,供下游按前缀归类)、latest_e1_date。新增
reason_codes(封闭代码)与 evidence_coverage。红旗文本末尾带 [code=...];
DATA_BLOCKED 文本以代码开头(电池只保留前 60 字)。

红旗≠禁入:逆向/复活候选可以带旗出现,但必须亮旗,且不得佩戴 ✅核心 层级。
名单模板必须携带本闸门的 stamp(时间戳+结果+最新E1日期),无戳名单=违宪。
不是买卖指令;研究信号,human executes.
"""
import os, sys, json, datetime
from nightly_context import bind, target_trade_date

_FUNNEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research_funnel")
if _FUNNEL_DIR not in sys.path:
    sys.path.append(_FUNNEL_DIR)
import e1_event_layer as e1  # noqa: E402  (shared rule set; no network at import)

GATE_VERSION = "red_flag_gate_v1"
# 带修订号:修订前后的产物(分歧队列 staleness_rule_version、信任线滚动窗口)可区分。
RULE_VERSION = f"{GATE_VERSION}/shared:{e1.RULE_REVISION}"
NEG_TYPES = frozenset(e1.NEGATIVE_GUIDANCE_TYPES)
# governance-mutation: U3_RED_FLAG_VERDICT_MAP
VERDICT_MAP = {"RED_FLAG": "RED_FLAG", "NO_RED_FLAG_FOUND": "PASS", "DATA_BLOCKED": "DATA_BLOCKED"}
RED_FLAG_CODES = (
    "NEGATIVE_ISSUER_GUIDANCE",
    "EXPRESS_NET_PROFIT_DROP_GT_30PCT",
    "NEGATIVE_AND_WORSENING_QUARTER_PROFIT",
)
BLOCK_CODES = (
    "INCOME_SOURCE_UNAVAILABLE",
    "E1_SOURCE_PARTIAL",
    "EXPRESS_YOY_METRIC_MISSING",
    "FORECAST_GUIDANCE_UNSCORABLE",
    "INCOME_VALUE_MISSING",
    "FILED_PERIOD_STALE",
    "INSUFFICIENT_FILED_QUARTER_HISTORY",
)
LOOKBACK_DAYS = 800  # ≥ 两个完整财年:最新已披露期的相邻上一季及其累计基数都在窗内
# 与批量层同一组字段:同期同公告日的并列行按整行哈希定胜负,字段不同就会选出不同的行。
FORECAST_FIELDS = e1.FORECAST_FIELDS
EXPRESS_FIELDS = e1.EXPRESS_FIELDS
INCOME_FIELDS = e1.INCOME_FIELDS


def _records(frame):
    """Provider DataFrame → list[dict]; NaN/Inf → None (never 0, never kept as NaN)."""
    if frame is None:
        return []
    to_dict = getattr(frame, "to_dict", None)
    rows = to_dict("records") if callable(to_dict) else list(frame)
    out = []
    for row in rows:
        clean = {}
        for key, value in dict(row).items():
            if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
                value = None
            elif hasattr(value, "item") and not isinstance(value, (str, bytes)):
                try:
                    value = value.item()  # numpy scalar → python
                except (TypeError, ValueError):
                    pass
                if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
                    value = None
            clean[str(key)] = value
        out.append(clean)
    return out


def _yi(value_cny):
    return f"{float(value_cny) / 1e8:.2f}亿"


def _red_flag_text(item):
    """Readable text for one triggered E1 evidence record; prefixes are a downstream contract."""
    obs = item.get("observed") or {}
    kind = item.get("kind")
    if kind == "ISSUER_GUIDANCE":
        # governance-mutation: U3_RED_FLAG_REASON_PREFIX_CONTRACT
        text = f"最新预告[{obs.get('type') or '类型缺失'}] {item['ann_date']} 期末{item['period']}"
        if obs.get("net_profit_min_cny") is not None:
            text += f" 净利下限{_yi(obs['net_profit_min_cny'])}"
        if obs.get("net_profit_max_cny") is not None:
            text += f" 上限{_yi(obs['net_profit_max_cny'])}"
        return text + " [code=NEGATIVE_ISSUER_GUIDANCE]"
    if kind == "EARNINGS_EXPRESS":
        source = obs.get("net_profit_yoy_pct_source") or ""
        basis = "yoy_dedu_np" if source.endswith("yoy_dedu_np") else "由快报净利与上年同期净利额计算"
        return (f"最新快报净利同比{float(obs['net_profit_yoy_pct']):.1f}% "
                f"({item['ann_date']} 期末{item['period']}; 口径={basis}) "
                "[code=EXPRESS_NET_PROFIT_DROP_GT_30PCT]")
    if kind == "FILED_INCOME_TREND":
        return (f"最近季度归母{_yi(obs['latest_standalone_net_profit_cny'])}为负且环比恶化"
                f"(前季{_yi(obs['previous_standalone_net_profit_cny'])}) 期末{item['period']} "
                "[code=NEGATIVE_AND_WORSENING_QUARTER_PROFIT]")
    return f"未知证据类型{kind} [code=UNPARSED]"


_BLOCK_TEXT = {
    "E1_SOURCE_PARTIAL": "E1 来源不完整(预告/快报接口失败),未见红旗不等于通过",
    "EXPRESS_YOY_METRIC_MISSING": "快报净利同比不可计算(yoy_dedu_np/n_income/yoy_net_profit 为空)",
    "FORECAST_GUIDANCE_UNSCORABLE": "预告行既无类型也无净利上限,不可评分",
    "INCOME_VALUE_MISSING": "最新已披露期或其相邻上一季归母净利为空(NaN),缺数据不等于通过",
    "FILED_PERIOD_STALE": "最新已披露期早于法定截止日已过的最近一期,旧季度不能代替当期",
    "INSUFFICIENT_FILED_QUARTER_HISTORY": "零证据或已披露季度断档(缺最新期的相邻上一季),缺数据不等于通过",
}


def _blocked(out, code, text):
    out["verdict"] = "DATA_BLOCKED"
    out["reason_codes"] = [code]
    out["reasons"] = [f"{code}:{text}"]
    return out


def _unconfirmed_negative(ts_code, forecast_rows, express_rows, as_of):
    """income 取不到时:把仍可见的负面预告/快报列出来(未经财报确认是否已被取代)。"""
    probe = e1.classify_ticker(ts_code, forecast_rows=forecast_rows, express_rows=express_rows,
                               income_rows=[], as_of=as_of)
    items = [item for item in probe["evidence"]
             if item.get("kind") in ("ISSUER_GUIDANCE", "EARNINGS_EXPRESS")]
    items.sort(key=lambda item: (str(item.get("period") or ""), str(item.get("ann_date") or "")),
               reverse=True)
    return [{"kind": item["kind"], "period": item.get("period"), "ann_date": item.get("ann_date"),
             "type": (item.get("observed") or {}).get("type")} for item in items]


def _unconfirmed_hint(items):
    # 不以 最新预告/最新快报 开头:下游前缀解析器不会把它当成红旗理由。
    if not items:
        return ""
    top = items[0]
    if top["kind"] == "ISSUER_GUIDANCE":
        return f"未确认负面预告[{top.get('type') or '类型缺失'}]期末{top['period']}"
    return f"未确认快报降幅期末{top['period']}"


def check_ticker(pro, ts_code, today):
    out = {"ts_code": ts_code, "verdict": "DATA_BLOCKED", "reasons": [], "reason_codes": [],
           "latest_e1_date": None, "checked_at": today, "rule_version": RULE_VERSION,
           "evidence_coverage": None, "latest_filed_period": None}
    as_of = e1._date8(today)  # 非法日期是调用方错误,直接抛出(电池会把整维记为 DATA_BLOCKED)
    start = (datetime.datetime.strptime(as_of, "%Y%m%d")
             - datetime.timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    # 财报是取代预告/快报的唯一依据:取不到财报,任何预告红旗都无法确认仍然有效。
    income_error = None
    try:
        income_rows = _records(pro.income(ts_code=ts_code, start_date=start, end_date=as_of,
                                          fields=INCOME_FIELDS))
    except Exception as e:
        # governance-mutation: U3_RED_FLAG_INCOME_SOURCE_REQUIRED
        income_rows = None; income_error = f"income:{e}"
    errors = []
    try:
        forecast_rows = _records(pro.forecast(ts_code=ts_code, start_date=start, end_date=as_of,
                                              fields=FORECAST_FIELDS))
    except Exception as e:  # 预告接口失败 ≠ 没发预告:不得据此 PASS
        # governance-mutation: U3_RED_FLAG_FORECAST_FAILURE_NOT_PASS
        forecast_rows = []; errors.append(f"forecast:{e}")
    try:
        express_rows = _records(pro.express(ts_code=ts_code, start_date=start, end_date=as_of,
                                            fields=EXPRESS_FIELDS))
    except Exception as e:  # 快报接口失败 ≠ 没发快报:不得据此 PASS
        # governance-mutation: U3_RED_FLAG_EXPRESS_FAILURE_NOT_PASS
        express_rows = []; errors.append(f"express:{e}")
    if income_rows is None:
        # 仍然 DATA_BLOCKED(无法判断是否已被财报取代),但负面预告/快报不能在下游消失:
        # 提示放在最前,电池 err 只保留前 60 字。
        unconfirmed = _unconfirmed_negative(ts_code, forecast_rows, express_rows, as_of)
        out["unconfirmed_negative_evidence"] = unconfirmed
        hint = _unconfirmed_hint(unconfirmed)
        return _blocked(out, "INCOME_SOURCE_UNAVAILABLE",
                        ";".join([part for part in (hint, income_error, *errors) if part]))
    row = e1.classify_ticker(ts_code, forecast_rows=forecast_rows, express_rows=express_rows,
                             income_rows=income_rows, as_of=as_of, source_complete=not errors)
    out["verdict"] = VERDICT_MAP[row["verdict"]]
    out["reason_codes"] = list(row["reason_codes"])
    out["latest_e1_date"] = row["latest_e1_date"]
    out["evidence_coverage"] = row["evidence_coverage"]
    out["latest_filed_period"] = row["latest_filed_period"]
    out["latest_due_period"] = row["latest_due_period"]
    out["active_periods"] = row["active_periods"]
    if out["verdict"] == "RED_FLAG":
        out["reasons"] = [_red_flag_text(item) for item in row["evidence"]]
        if errors:
            # 核实的红旗在来源不完整时仍成立,但必须说明哪路来源失败;
            # 不以 最新预告/最新快报净利同比/最近季度归母 开头,前缀解析器不受影响。
            out["reasons"].append("E1_SOURCE_PARTIAL:" + ";".join(errors))
    elif out["verdict"] == "DATA_BLOCKED":
        code = out["reason_codes"][0] if out["reason_codes"] else "INSUFFICIENT_FILED_QUARTER_HISTORY"
        text = _BLOCK_TEXT.get(code, code)
        if code == "E1_SOURCE_PARTIAL":
            text += ";" + ";".join(errors)
        out["reasons"] = [f"{code}:{text}"]
    return out


def watchlist_tickers(limit=25, path=None):
    here = os.path.dirname(os.path.abspath(__file__))
    p = path or os.path.join(here, "watch_dynamic.json")
    try:
        wd = json.load(open(p))
    except (FileNotFoundError, json.JSONDecodeError):
        return []  # 调用方负责报 DATA_BLOCKED
    return [r.get("ticker") for r in (wd.get("watch") or []) if r.get("ticker")][:limit]


def main():
    from tushare_https import TushareHTTPS
    pro = TushareHTTPS(os.environ["TUSHARE_TOKEN"])
    today = target_trade_date()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--from-watchlist" in sys.argv:
        tickers = watchlist_tickers()
        if not tickers:
            print("DATA_BLOCKED: watch_dynamic 缺失或为空"); return 1
    else:
        tickers = args
    if not tickers:
        print("usage: red_flag_gate.py TS_CODE [...] | --from-watchlist"); return 1
    results = [check_ticker(pro, t, today) for t in tickers]
    # "gate" 字段保持 v0 字面值:promoter QC 等消费者按它识别戳;版本看 gate_version/rule_version。
    stamp = bind({"gate": "red_flag_gate_v0", "gate_version": GATE_VERSION,
                  "rule_version": RULE_VERSION, "checked_at": today, "results": results,
                  "disclaimer": "红旗≠禁入,但必须亮旗;无戳名单=违宪。不是买卖指令。"},
                 target=today)
    if "--from-watchlist" in sys.argv:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "red_flags.json"), "w", encoding="utf-8") as fh:
            json.dump(stamp, fh, ensure_ascii=False, indent=1)
        print(f"[written] red_flags.json n={len(results)} "
              f"red={sum(1 for r in results if r['verdict']=='RED_FLAG')}")
        print("不是买卖指令;研究信号,human executes.")
    else:
        print(json.dumps(stamp, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
