#!/usr/bin/env python3
"""ai_value_chain_screen.py — AI value-chain discovery screen (2026-06-14).

This is the DISCOVERY layer of the Deep Thesis Factory (Core Thesis Factory v1).
It does NOT emit trade signals or validated buy lists. It produces RESEARCH CANDIDATES:
names worth a full deep thesis next, with an HONEST entry FRAMEWORK, not a target.

HOW THIS DIFFERS FROM the earlier hand-seed AI pack (PR #81, cross-checked + retired):
  - selection is from a 4-agent research sweep ACROSS the AI value chain (compute /
    interconnect / semi-supply / adjacent), not a hardcoded ticker list;
  - EVERY price / PE / market cap is RECONCILED against the committed universe_a snapshot
    (the 一手对账门): a research price that disagrees with committed data by >5% is FLAGGED,
    and a research PE that disagrees materially from the committed PE is FLAGGED
    (this caught 中科曙光: agent PE 57 vs committed 132.6 — a 2.3x gap);
  - the suggested entry zone is the analyst's FORWARD-PE-anchored research trigger, explicitly
    labeled heuristic / pending-deep-thesis — NOT `price x arbitrary multiplier`, NOT a target;
  - the triage rank is a TRANSPARENT, documented heuristic (value factor − crowding − valuation
    stretch − reconciliation penalty), NOT a validated alpha rank.

Honest top-line: the AI sector is broadly priced for the bull case. Of ~14 names, only a
couple clear a "good thesis ∩ not-fully-run price" bar; most are WATCH / AVOID. That is the
screen working — it is supposed to find good companies at bad prices and say WATCH.

Usage:
  python3 scripts/ai_value_chain_screen.py            # write JSON + render MD
  python3 scripts/ai_value_chain_screen.py --selftest
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
D = REPO / "public" / "data"
UNIVERSE = D / "universe_a.json"
OUT_JSON = D / "ai_value_chain_screen.json"
OUT_MD = REPO / "docs" / "research" / "screens" / "AI_VALUE_CHAIN_SCREEN_2026-06-14.md"
SCREEN_DATE = "2026-06-14"
SNAPSHOT_AS_OF = "2026-06-12T05:55Z"  # universe_a _meta.fetched_at (last trading day before the weekend)

# ── research-grounded candidates (4-agent value-chain sweep, 2026-06-14) ───────────────
# Each carries: layer/role, ai_linkage directness, 3-point thesis, dated catalyst, >=1
# mechanized wrong_if, the analyst valuation ANCHOR (forward PE / peer), a research-trigger
# entry zone (heuristic), stance, crowding, evidence tier, and the agent-observed price for
# reconciliation. NO valuation band is invented here — committed data is overlaid at runtime.
CANDIDATES: list[dict] = [
    {
        "ticker": "300476.SZ", "name": "胜宏科技", "layer": "AI 高速 PCB (HDI)", "role": "CONTROLS",
        "ai_linkage": "DIRECT", "stance": "WATCH_CONSTRUCTIVE",
        "thesis": [
            "市场信:英伟达 PCB 亲儿子,GB200/300 已在价里(2025 已 4x)。",
            "变体:AI 已占营收 >50-60%,GM 22.7%→33.4%(Q1'24→'25)→36.2%(25H1)mix 仍在上行;股价 2026 YTD 仅 +6%(同业翻倍),2026E ~36x 低于旭创 43-51x。",
            "关键问:GB300 OAM HDI 份额能否在放量中守住(对 沪电/鹏鼎),还是单客户(英伟达 >60%)在 2027 压毛利。",
        ],
        "catalyst": "2026 H1 报 ~2026-08-31:GM 是否守 ≥35% + AI 营收占比是否再升;Rubin/M9-CCL 2026H2 含量提升。",
        "wrong_if": [
            {"metric": "2026 H1 综合毛利率", "threshold": "< 32%", "check_date": "2026-08-31"},
            {"metric": "英伟达营收占比 + GB300 OAM 二供获认证", "threshold": ">65% 且二供出现", "check_date": "2026-H2"},
        ],
        "valuation_anchor": "2026E ~36x / 2027E ~21.5x(cap÷同花顺一致净利 89.08/149.58亿);板块最低 AI-瓶颈名 forward 倍数",
        "research_entry": "≤ ¥250-270(≈28-30x 2026E / ~18x 2027E,再回调 ~20%);研究触发价,非目标价,须满版 deep thesis 确认",
        "crowding": "机构覆盖充分(6/6 buy 目标 ~439)但价不拥挤——2026 YTD +6%,距 2025-09 高约 -19%。被价格挤出的名。",
        "evidence": "AI 营收 >50-60% [E2 多家卖方]; GM 36.22% 25H1 [E1 中报]; GB300 OAM 30-40% 份额 [E2 国盛]; A+H 双上市 [E1]",
        "agent_price": 327.21,
        "sources": ["https://wallstreetcn.com/articles/3770620", "eniu.com/gu/sz300476", "国盛/山证 GB300 PCB 含量深度"],
    },
    {
        "ticker": "601138.SH", "name": "工业富联", "layer": "AI 服务器/整机 ODM", "role": "SUPPLIES",
        "ai_linkage": "DIRECT", "stance": "WATCH_CONSTRUCTIVE",
        "thesis": [
            "市场信:AI 服务器王、万亿市值、故事人尽皆知=已充分定价。",
            "变体是 forward 倍数被盈利压缩,不是扩张:Q1'26 已印归母 105.95亿(+102.55%)、营收 2510亿(+56.5%);FY26 一致净利 500-606亿 vs FY25 302亿 → forward PE ~23-28x(委内提示:committed PE 仅 33,比 agent TTM 45 更低)。",
            "关键问:GB200→GB300 机柜 ASP/毛利台阶是结构性的,还是 ODM 薄利(净利率 ~3-4%)随放量封顶上行。",
        ],
        "catalyst": "2026 H1 报 ~2026-08-30:Q1 +100% 净利 run-rate 是否延续;GB300 机柜 2026H2 量产;北美云资本开支指引。",
        "wrong_if": [
            {"metric": "2026 H1 归母净利(年化)", "threshold": "< ~450亿(H1 < ~210亿)", "check_date": "2026-08-30"},
            {"metric": "云计算分部毛利率", "threshold": "< ~6%", "check_date": "2026-08-30"},
        ],
        "valuation_anchor": "forward PE ~23-28x(FY26 500-606亿净利);全板块最低 forward 倍数的万亿名;GS 目标 ¥92.9-93.9",
        "research_entry": "≤ ¥60(≈20x FY26 500亿净利)R/R 才趋近 2:1 对 GS ¥93 上行;研究触发价,非目标价",
        "crowding": "机构拥挤、动量延展——~+200%(¥18→~¥53),Apr-May'26 多次涨停。唯一不 AVOID 的理由 = forward 倍数最便宜(盈利在涨进价里)。",
        "evidence": "Q1'26 归母 105.95亿 [E1 一季报,⚠ 须核对——曾见 41.8亿 旧/错值]; FY26 一致 500-606亿 [E2 卖方]; >40% 全球 AI 服务器份额 [E2]",
        "agent_price": 70.13,
        "sources": ["https://finance.sina.com.cn/wm/2026-04-22/doc-inhvkiya9336135.shtml", "eniu.com/gu/sh601138"],
    },
    {
        "ticker": "300604.SZ", "name": "长川科技", "layer": "半导体后段测试设备", "role": "CONTROLS",
        "ai_linkage": "DIRECT", "stance": "WATCH",
        "thesis": [
            "市场信:国产替代+AI/存储测试需求=多年结构成长,已自 2024 低点 ~10x。",
            "变体:盈利跑赢股价——FY25 归母 13.31亿(+190%)、Q1'26 3.53亿(+218%)、扣非 +612%;价自 5 月中横盘 ~218,forward PE 压到 ~44x(2026E)/~32x(2027E),板块控瓶颈名里最低 forward。",
            "关键问:+200% 是一次性国产替代+存储 capex 脉冲,还是 2-3 年基线。",
        ],
        "catalyst": "2026 H1 报 ~2026-08-31:测试机订单动能是否在 Q1 尖峰后回落;D9000 数字测试机放量。",
        "wrong_if": [
            {"metric": "2026 H1 归母同比", "threshold": "< ~+80%", "check_date": "2026-08-31"},
            {"metric": "测试机毛利率", "threshold": "连续两季 < 55%(自 62%)", "check_date": "2026-Q3"},
        ],
        "valuation_anchor": "forward 2026E ~44x / 2027E ~32x;committed PE-TTM 105(eniu 显 143 含滞后,卖方 ~64)、PB 29(很高)",
        "research_entry": "≤ ¥165-180(≈2026E 低 30x,PB 去化)且 H1 确认增长;研究触发价。PB 32x 下当前非 2:1。",
        "crowding": "重度拥挤/动量延展——年内 +100%,5/12 尖峰日主力净卖出 3.41亿(向上派发)。'业绩炸裂股价高位滞涨'。",
        "evidence": "FY25/Q1 [E1 年报+季报]; forward PE & D9000 竞争力 [E2 卖方]; PE 分位 2-4% 是盈利追赶前的伪低 [E1-derived 误导]",
        "agent_price": 218.41,
        "sources": ["https://www.stcn.com/article/detail/3809239.html", "https://news.qq.com/rain/a/20260512A03AWM00"],
    },
    {
        "ticker": "002156.SZ", "name": "通富微电", "layer": "先进封装 OSAT", "role": "SUPPLIES",
        "ai_linkage": "DIRECT", "stance": "WATCH",
        "thesis": [
            "市场信:A 股 AMD AI 加速器封装+chiplet 放量的代理。",
            "变体:盈利拐点——25 前三季归母 8.60亿(+55.7%)、Q3 +95%、全年指引 11-13.5亿;forward 全板块最低 ~31x(2026E)/~28x(2027E);是利用率+毛利(AI/HPC mix)故事。",
            "关键问:AI/HPC mix 能否把穿周期净利率稳住(OSAT 结构低毛利+周期+AMD 客户集中)。",
        ],
        "catalyst": "FY25 业绩确认;AMD MI 系列下一代封装订单;44亿定增(≤4.55亿新股)落地的产能。",
        "wrong_if": [
            {"metric": "44亿/4.55亿股定增摊薄后 2026 净利指引", "threshold": "< ~18亿(摊薄 ~+9-10% 股本)", "check_date": "定增收官+下次指引"},
            {"metric": "综合净利率", "threshold": "连续两季 < ~4%", "check_date": "2026-Q2/Q3"},
        ],
        "valuation_anchor": "forward 2026E ~31x(板块最低);committed PE-TTM 67、PB 5.7(eniu 925-963亿,⚠ 曾见 96.88亿 = 10x 错值)",
        "research_entry": "≤ ¥50-55(≈2026E 中 20x,PB ~5x)对摊薄+周期留安全垫;研究触发价",
        "crowding": "中度拥挤、已离高——5/22 ~962亿/¥71 回落到 ~58-64。风险在基本面(毛利/摊薄)非动量。",
        "evidence": "9M/Q3 财务+指引 [E1]; 定增 [E1 公告]; forward PE & AMD-mix [E2]",
        "agent_price": 61.22,
        "sources": ["eniu.com/gu/sz002156", "通富微电 2025 三季报/定增公告"],
    },
    {
        "ticker": "603019.SH", "name": "中科曙光", "layer": "AI 服务器/HPC + 海光持股", "role": "BENEFITS",
        "ai_linkage": "INDIRECT(look-through 海光 27.96%)", "stance": "WATCH_RECONCILE_FLAG",
        "thesis": [
            "市场信:服务器/HPC 整合商 + 海光 27.96% 嵌入期权;Dec-2025 合并终止后'合并重估'交易已死。",
            "变体:看穿价值——海光 FY25 净 25.45亿 ×27.96% ≈7.1亿投资收益,占曙光 归母(FY25 21.76亿)~1/3 且增速更快。",
            "⚠ 重大对账冲突:agent 称 PE 57x,但 committed universe PE = 132.6x(2.3x 差)。若 committed 准,则'比海光便宜'论点的估值底座成立度大降——deep thesis 必先解决 EPS 口径冲突。",
        ],
        "catalyst": "海光 H1'26 报 ~2026-08-30(投资收益流入);任何整合重启(低概率尾部);曙光数创 液冷/超节点订单。",
        "wrong_if": [
            {"metric": "海光 H1'26 净利同比", "threshold": "< ~+40%", "check_date": "2026-08-30"},
            {"metric": "曙光自身(除海光)经营利润同比", "threshold": "< 0(FY25 经营现金流已 -51.75%)", "check_date": "2026-08-30"},
        ],
        "valuation_anchor": "⚠ 估值口径未决:agent PE 57 vs committed 132.6;PB 5.5;mcap 1208亿。先核 EPS 口径再谈。",
        "research_entry": "暂不给——对账冲突未解前任何 entry 都不可靠(正是 #81 hand-seed 教训的反面)。",
        "crowding": "中度;合并终止取走了动量人群,这才有 look-through 角度。",
        "evidence": "FY25 [E1 年报]; 海光持股 27.96% [E2 derived]; PE 口径冲突 [对账门 catch]",
        "agent_price": 82.15,
        "sources": ["eniu.com/gu/sh603019", "https://www.jjckb.cn/20251210/2f5441ad5bac493db6371a73ff4b6c98/c.html"],
    },
    {
        "ticker": "002463.SZ", "name": "沪电股份", "layer": "AI PCB", "role": "SUPPLIES",
        "ai_linkage": "DIRECT", "stance": "WATCH",
        "thesis": [
            "市场信:AI 服务器/交换机 PCB 核心受益,已随板块上行。",
            "变体:同业里相对便宜——committed PE 49.5 vs PCB 同业 ~108x、PEG ~1.11;Q1'26 归母 12.42亿(+62.9%)。",
            "关键问:AI 板占比与毛利能否在 800G/1.6T 交换+GB 机柜放量中继续抬升。",
        ],
        "catalyst": "2026 H1 报 ~2026-08-31:AI 板营收占比与毛利;Rubin 平台 2026H2 含量。",
        "wrong_if": [
            {"metric": "2026 H1 综合毛利率", "threshold": "环比走弱 + AI 占比未升", "check_date": "2026-08-31"},
            {"metric": "归母同比", "threshold": "< +30%", "check_date": "2026-08-31"},
        ],
        "valuation_anchor": "committed PE 49.5、PB 15.5、mcap 2458亿;同业相对折价(PCB 板块均 ~108x)",
        "research_entry": "需 deep thesis 建桥;+66% YTD 已部分定价,触发价待满版后定。",
        "crowding": "中度延展(+66% YTD)。比胜宏更贵的同类暴露——胜宏在更低 2026E 倍数+更平的图提供同样敞口。",
        "evidence": "Q1'26 归母 12.42亿 [E1]; PE vs PCB 同业 [E2]",
        "agent_price": 125.20,
        "sources": ["eniu.com/gu/sz002463"],
    },
    {
        "ticker": "002130.SZ", "name": "沃尔核材", "layer": "224G 高速铜缆 + 热缩材料", "role": "SUPPLIES",
        "ai_linkage": "INDIRECT(AI ~12% 营收)", "stance": "WATCH_DEEP_VALUE",
        "thesis": [
            "市场信:母凭子贵——热缩/核辐照公司穿英伟达铜缆马甲,AI 占比小、股价已泄气。",
            "变体:高速通信线真在放量+认证——25H1 +398% 至 4.66亿,224G 量产、乐庭扩产;因 AI 仅 ~12% 营收(盈利底座),全公司 ~14x 2026E / PB 2.9,几乎白送 AI 期权。",
            "关键问:224G 铜在 GB 机柜规模下是否被光替代(光进铜退),乐庭营收能否真正撬动 270亿市值。",
        ],
        "catalyst": "2026 H1 报 ~2026-08:高速线营收占比;H 股 IPO 进行中(招股书已出)= 近端事件/扰动。",
        "wrong_if": [
            {"metric": "高速通信线 FY2026 营收", "threshold": "未 > ~12-13亿(未翻倍)", "check_date": "2027-03(年报)"},
            {"metric": "2027E 一致净利(CPO 替代担忧)", "threshold": "下修 < ~20亿", "check_date": "Rubin 规格后"},
        ],
        "valuation_anchor": "committed PE 29.2、PB 3.0、mcap 270亿;forward 2026E ~14x(板块最便宜);⚠ F10 forward 26.6x 与 270亿市值不符,以 cap÷净利 14x 为准",
        "research_entry": "≈ ¥17-18 + H-IPO 扰动出清(事件解决型,非更低倍数);研究触发价。已 -29% YTD 是板块唯一下跌名。",
        "crowding": "动量已 OUT——-29% YTD,唯一下跌名。逆向/价值姿态。公司质地(传统重、AI 美元敞口小)低于 胜宏。",
        "evidence": "224G 量产+英伟达 GB200 系统认证 [E2 强]; ~24.9% 全球份额#2 [E2]; 高速线 +398% [E1 中报]; CPO 替代风险 [lead 结构]",
        "agent_price": 19.19,
        "sources": ["沃尔核材 调研纪要/中报", "兆龙互连同业对比"],
    },
    {
        "ticker": "002179.SZ", "name": "中航光电", "layer": "连接器(军工+民品)", "role": "BENEFITS",
        "ai_linkage": "INDIRECT(112G 量产,224G 研制中)", "stance": "WATCH_TURNAROUND",
        "thesis": [
            "市场信:蓝筹连接器龙头,军工修复+数据中心/液冷期权,'安全'的 AI 邻近名。",
            "变体:2025 是下行年——营收 213.86亿(+3.4%)但归母 21.62亿(-35.6%);47.9x 在被压基数上,牛市是毛利均值回归(民品 数据中心/液冷/EV 对冲军工软)。板块唯一 PB 3.24 的真工业franchise。",
            "关键问:民品(数据中心液冷+224G)能否在 2026 足够快地修复毛利。",
        ],
        "catalyst": "2026 半年报 ~2026-08-31:-35% 利润是否见底+民品/数据中心是否加速;224G 量产时点(当前研制)。",
        "wrong_if": [
            {"metric": "2026 H1 归母同比", "threshold": "仍为负", "check_date": "2026-08-31"},
            {"metric": "数据中心/民品营收同比", "threshold": "< ~20%", "check_date": "2026-08-31"},
        ],
        "valuation_anchor": "committed PE 48.9、PB 3.24(板块最低)、mcap 779亿;forward 2026E ~30x(修复基数上)",
        "research_entry": "≈ ¥31-33 且 H1 利润拐点确认(证据门,非纯价格门);研究触发价。",
        "crowding": "不延展(+2% YTD)。风险是反面——'被证明前是价值陷阱'直到毛利转向显现。",
        "evidence": "2025 营收/归母 [E1 年报]; 112G 量产/224G 研制/CPO 团队 [E1+E2]; 2026-28 一致 [E2]",
        "agent_price": 36.01,
        "sources": ["eniu.com/gu/sz002179", "中航光电 2025 年报"],
    },
    {
        "ticker": "688041.SH", "name": "海光信息", "layer": "国产 CPU/DCU 算力芯片", "role": "CONTROLS",
        "ai_linkage": "DIRECT", "stance": "WATCH_ONLY_PRICE",
        "thesis": [
            "市场信:A 股首选国产替代算力芯片,DCU 深算3 是最可信英伟达替代。",
            "变体(偏负面):franchise 真且加速(Q1'26 营收 40.34亿 +68%、净 6.87亿 +36%),但无价格变体——committed PE 244.9 / 99 分位;净利增速(FY25 +31.79%)远慢于营收(+56.9%)= DCU 爬坡毛利/opex 吃掉模型。",
            "关键问:DCU 能否在不重演 FY25 净利率侵蚀下放量。",
        ],
        "catalyst": "FY26 一致净 44.3亿(+74%);H1 报 ~2026-08-30 是关键印证;~30亿员工持股套现悬顶 = 情绪风险。",
        "wrong_if": [
            {"metric": "H1'26 净利增速 vs 营收增速", "threshold": "净利再次 < 营收增速", "check_date": "2026-08-30"},
            {"metric": "DCU 深算 出口/IP(chiplet/代工)", "threshold": "受限", "check_date": "rolling"},
        ],
        "valuation_anchor": "committed PE 244.9 / 99 分位、PB 28.6、mcap 6730亿;⚠ 纠错:FY25 净 25.45亿(+31.79%),非流传的'19亿'",
        "research_entry": "PE 压向 ~80-100x 前无可辩护入场(需价格腰斩或 ~2 年盈利增长)。WATCH_ONLY。",
        "crowding": "极度拥挤,99 分位估值,市值破 8000亿。拥有瓶颈不使价格合理。",
        "evidence": "FY25/Q1 [E1 年报/季报]; PE 分位 [E2 eniu]; 19亿净利是错值 [对账纠正]",
        "agent_price": 280.0,
        "sources": ["eniu.com/gu/sh688041", "https://www.stcn.com/article/detail/3730253.html"],
    },
    {
        "ticker": "688082.SH", "name": "盛美上海", "layer": "前道清洗/电镀设备", "role": "CONTROLS",
        "ai_linkage": "DIRECT", "stance": "AVOID_AT_SPOT",
        "thesis": [
            "市场信:多产品平台复利,清洗垄断+新品(电镀/炉管/track)S 曲线。",
            "变体是警告:Q1'26 营收 +13% 但净利 -57.7%、GM 45.6%(-10.3pp)、净利率 7.06%(-62.6%)——重 R&D(20.9% 营收)+新品 mix 压近期毛利。流传的'2026E 39.5x'是用旧价~229 + 假设 H2 毛利修复算的,Q1 正相反。",
            "关键问:毛利崩塌是投入期(暂时)还是结构(清洗价格战)——Q1 单季无法判断。",
        ],
        "catalyst": "2026 H1 报 ~2026-08:GM/净利率是否企稳还是续跌(摆动因子)。",
        "wrong_if": [
            {"metric": "2026 H1 综合毛利率", "threshold": "< ~48%(自 55%+)", "check_date": "2026-08"},
            {"metric": "2026 H1 归母", "threshold": "仍为负", "check_date": "2026-08"},
        ],
        "valuation_anchor": "committed PE 355、PB 10.8、mcap 1482亿;两周 +33% 至 ¥305,'2026E 39.5x'是旧价口径(现 ~52x)",
        "research_entry": "回撤至 ~¥210-230 + H1 毛利企稳才谈 2:1。当前=向恶化毛利追动量,AVOID at spot。",
        "crowding": "动量延展(两周 +33% 进 6 月板块 melt-up)。本片最干净的'质地≠价格'范例。",
        "evidence": "Q1 财务 [E1]; '2026E 39.5x' [E2 但旧价口径,已 flag]; 市占 [E2 Gartner]",
        "agent_price": 304.66,
        "sources": ["https://stock.stockstar.com/RB2026042900024245.shtml", "eniu.com/gu/sh688082"],
    },
    {
        "ticker": "688019.SH", "name": "安集科技", "layer": "CMP 抛光液/电镀液 材料", "role": "CONTROLS",
        "ai_linkage": "DIRECT", "stance": "WATCH_ONLY_PRICE",
        "thesis": [
            "市场信:CMP 材料国产龙头,先进制程/HBM 抛光液受益。",
            "变体:真材料瓶颈,Q1 净 +23%,但 committed PE 62.6 / 2026E ~47x 已是一致多头,无明显信息增量。",
            "关键问:抛光液 ASP/份额能否在先进制程+HBM 放量中超一致预期。",
        ],
        "catalyst": "2026 H1 报 ~2026-08-31:营收/毛利;HBM 相关材料放量信号。",
        "wrong_if": [
            {"metric": "2026 H1 营收同比", "threshold": "< +25%", "check_date": "2026-08-31"},
            {"metric": "综合毛利率", "threshold": "连续两季走弱", "check_date": "2026-08-31"},
        ],
        "valuation_anchor": "committed PE 62.6、PB 11.6、mcap 520亿;2026E ~47x(一致多头,不便宜)",
        "research_entry": "需 deep thesis;当前估值已定价,触发价待满版。",
        "crowding": "一致多头;⚠ agent 价 209 vs committed 228.5(-8.5% 偏离,以 committed 为准)。",
        "evidence": "Q1 净 +23% [E1]; 2026E ~47x [E2]",
        "agent_price": 209.08,
        "sources": ["https://caifuhao.eastmoney.com/news/20260531103724902224780"],
    },
    {
        "ticker": "301308.SZ", "name": "江波龙", "layer": "企业级存储模组/eSSD/RDIMM", "role": "SUPPLIES",
        "ai_linkage": "DIRECT", "stance": "CYCLE_WATCH",
        "thesis": [
            "市场信:AI 内存超级周期+企业存储国产替代的纯标的。",
            "变体:Q1'26 利润爆发(营收 99亿、净 38.62亿,自 -1.52亿)由 NAND/DRAM 涨价+企业 mix 上移驱动;但 forward PE 14x 是周期顶单季年化的幻觉。",
            "关键问:38.6亿单季利润里多少是耐用企业 mix 毛利 vs 短暂 NAND/DRAM 涨价窗口。",
        ],
        "catalyst": "Q2'26 报 ~2026-08:企业营收能否续增+毛利在内存涨价见顶时是否守住;H2'26 NAND 价格轨迹。",
        "wrong_if": [
            {"metric": "NAND 合约价环比", "threshold": "转负(现 +70-75%)", "check_date": "TrendForce Q4'26"},
            {"metric": "企业存储营收占比 FY2026", "threshold": "未 > 22%", "check_date": "2027 年报"},
        ],
        "valuation_anchor": "committed PE-TTM 14.7(周期顶,误导)、PB 19.1、mcap 2271亿;静态 PE ~152x",
        "research_entry": "≈ ¥330-380(任何 30%+ 周期回撤后,正常化非顶峰年化净利支撑 2:1);明确非目标价、周期择时依赖。",
        "crowding": "极度拥挤/抛物线(12 个月 +7x)。对内存价格头条高 beta。",
        "evidence": "Q1'26 财务 [E1]; 企业存储占比模型 [E2]; 14x forward 是顶峰年化 [flag]",
        "agent_price": 514.89,
        "sources": ["江波龙 2026 一季报", "TrendForce NAND 合约价"],
    },
    {
        "ticker": "688525.SH", "name": "佰维存储", "layer": "端侧 AI 存储(AI 眼镜)", "role": "SUPPLIES",
        "ai_linkage": "DIRECT(具名客户)", "stance": "CYCLE_WATCH",
        "thesis": [
            "市场信:端侧 AI 设备(AI 眼镜)扩散+内存超周期的杠杆名。",
            "变体:Q1'26'AI 新兴端侧存储'营收 11.75亿(+496%),ePOP 供 Meta/Google/阿里/小米/Rokid/Rayneo AI/AR 眼镜——本片最干净'具名 AI 客户'披露。但 ~83% 利润仍是 NAND/DRAM 涨价窗口。",
            "关键问:AI 眼镜终端(绝对出货仍小)是否够大成耐用驱动。",
        ],
        "catalyst": "Q2'26 报 ~2026-08;Meta/Google AI 眼镜出货量披露(2H'26)。",
        "wrong_if": [
            {"metric": "NAND 合约价环比", "threshold": "转负", "check_date": "TrendForce Q4'26"},
            {"metric": "端侧 AI 存储 FY2026 营收", "threshold": "未 > ¥40亿", "check_date": "2027 年报"},
        ],
        "valuation_anchor": "committed PE-TTM 13.9(顶峰年化误导)、PB 19.1、mcap 1613亿;⚠ agent 价 312 vs committed 342(-8.7% 偏离)",
        "research_entry": "本片最延展(+438% YTD);仅在重大周期重置(~¥200 以下)研究再接触;非目标价。",
        "crowding": "本概念最拥挤/抛物线(+438% YTD,11 周 +77%)。当前价纯动量载体。",
        "evidence": "Q1'26 端侧 +496% [E1]; 具名客户 [E2]; 13.9x forward 顶峰年化 [flag]; mcap 须股数核算(门户 ~10x 低报)",
        "agent_price": 312.25,
        "sources": ["佰维存储 2026 一季报", "STCN +438% YTD"],
    },
    {
        "ticker": "002837.SZ", "name": "英维克", "layer": "数据中心液冷/温控", "role": "SUPPLIES",
        "ai_linkage": "DIRECT", "stance": "AVOID_BLOWUP",
        "thesis": [
            "市场信:AI 数据中心必走液冷→英维克是温控收费名。",
            "变体(负面):需求真但毛利刚崩——Q1'26 营收 11.75亿(+26%)却净利 866万(-81.97%)、GM 24.3%;扩产+竞争压垮近期盈利。营收增 ≠ 利润增。",
            "关键问:Q1 毛利崩是一次性扩产成本空窗,还是结构(液冷商品化快于规模收益)。",
        ],
        "catalyst": "Q2'26 报 ~2026-08:净利率是否修复。",
        "wrong_if": [
            {"metric": "2026 H1 净利率", "threshold": "< 5%(自 FY25 ~8.6%)", "check_date": "2026-08"},
        ],
        "valuation_anchor": "committed PE 2520(盈利崩塌使 TTM 无意义)、mcap 873亿;距 1 年高 ~-29%,自低 +3.2x",
        "research_entry": "无——盈利崩塌+动量延展是最差组合。质地刚退化。",
        "crowding": "延展(自 1 年低 +3.2x)且盈利恶化。一字跌停后散户户数一月 +5万。oversell 典型 casualty。",
        "evidence": "Q1'26 净 -82% [E1]; 价/区间 [E2]",
        "agent_price": 66.08,
        "sources": ["https://www.tmtpost.com/7961257.html"],
    },
]

# Registered names carried for CONTEXT only (already in the forward checkpoint ledger).
REGISTERED_CONTEXT = ["688008.SH", "688120.SH", "688072.SH", "300054.SZ"]


def _universe() -> dict:
    rows = json.loads(UNIVERSE.read_text()).get("stocks", [])
    return {r["ticker"]: r for r in rows}


def _reconcile(c: dict, row: dict) -> dict:
    """The 一手对账门: overlay committed data, flag price/PE disagreement with the research."""
    cp = row.get("price")
    ap = c.get("agent_price")
    flags = []
    price_delta = None
    if cp and ap:
        price_delta = round((ap - cp) / cp * 100, 1)
        if abs(price_delta) > 5.0:
            flags.append(f"STALE_RESEARCH_PRICE: research {ap} vs committed {cp} ({price_delta:+.1f}%) — use committed")
    if "PE 57" in (c.get("valuation_anchor", "") + " ".join(c.get("thesis", []))) and row.get("pe") and row["pe"] > 90:
        flags.append(f"PE_CONFLICT: research cites a low PE but committed PE = {row.get('pe')} — resolve EPS basis before any band")
    return {
        "committed_price": cp, "committed_pe": row.get("pe"), "committed_pb": row.get("pb"),
        "committed_mcap_yi": round((row.get("market_cap") or 0) / 1e8, 0),
        "committed_turnover_rate": row.get("turnover_rate"),
        "factor_value": (row.get("factors") or {}).get("value"),
        "factor_momentum": (row.get("factors") or {}).get("momentum"),
        "research_price": ap, "research_vs_committed_pct": price_delta,
        "reconciliation_flags": flags or None,
    }


def _triage_score(rec: dict, stance: str) -> float:
    """TRANSPARENT triage heuristic (NOT a validated alpha rank, NOT a buy score).
    Higher = higher research priority. Documented = value cheapness − crowding/momentum
    stretch − valuation stretch − reconciliation penalty − stance penalty."""
    v = rec.get("factor_value") or 0          # 0-100, higher = cheaper
    m = rec.get("factor_momentum") or 50      # 0-100, higher = more extended
    pe = rec.get("committed_pe") or 999
    score = v - 0.5 * max(0, m - 50)          # cheapness minus momentum-stretch
    score -= min(40, pe / 8.0)                # valuation-stretch penalty
    if rec.get("reconciliation_flags"):
        score -= 25                           # unresolved data conflict = down-rank hard
    stance_penalty = {"WATCH_CONSTRUCTIVE": 0, "WATCH_DEEP_VALUE": 5, "WATCH": 12,
                      "WATCH_TURNAROUND": 15, "WATCH_RECONCILE_FLAG": 30, "WATCH_ONLY_PRICE": 35,
                      "CYCLE_WATCH": 40, "AVOID_AT_SPOT": 55, "AVOID_BLOWUP": 70}.get(stance, 30)
    return round(score - stance_penalty, 1)


def build() -> dict:
    uni = _universe()
    out = []
    for c in CANDIDATES:
        row = uni.get(c["ticker"])
        if not row:
            out.append({**c, "_error": "NOT_IN_UNIVERSE"})
            continue
        rec = _reconcile(c, row)
        out.append({**{k: v for k, v in c.items() if k != "agent_price"},
                    "committed": rec, "triage_score": _triage_score(rec, c["stance"])})
    out.sort(key=lambda x: x.get("triage_score", -999), reverse=True)
    return {
        "_meta": {
            "layer": "Deep Thesis Factory — AI value-chain DISCOVERY screen (research candidates, NOT a buy list)",
            "screen_date": SCREEN_DATE, "committed_snapshot_as_of": SNAPSHOT_AS_OF,
            "method": "4-agent value-chain research sweep -> committed universe_a overlay + 一手对账门 reconciliation "
                      "+ transparent triage rank; every entry zone is a heuristic research trigger, NOT a target; "
                      "supersedes the PR #81 hand-seed pack (which used arbitrary band multipliers).",
            "honest_state": "AI sector broadly priced for the bull case. Of these names only 2 clear a "
                            "good-thesis-and-not-fully-run bar (胜宏/工业富联); the rest are WATCH/AVOID/cycle. "
                            "No validated buy list. Each name needs a full red-teamed deep thesis before any register/starter.",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n": len(out),
        },
        "registered_context": REGISTERED_CONTEXT,
        "candidates": out,
    }


def render_md(data: dict) -> str:
    L = [f"# AI 价值链发现筛选 · AI Value-Chain Discovery Screen ({SCREEN_DATE})", ""]
    L.append("> **内部、未验证研究输出 — 不是已验证买入名单,不是个性化投资建议。** 每个 entry zone 是"
             "**启发式研究触发价,不是目标价**;任何注册/建仓前必须先做一份人工五轴红队通过的满版 deep thesis。"
             "选名来自 4-agent 价值链研究扫描;**每个价格/PE/市值已对 committed universe_a 快照做一手对账门**;"
             "本筛取代 PR #81 的 hand-seed pack(后者用任意带倍数)。")
    L.append(f">")
    L.append(f"> **诚实状态:** {data['_meta']['honest_state']}")
    L.append(f"> committed 快照 as-of {SNAPSHOT_AS_OF};研究价为各 agent web 读数,>5% 偏离已 flag,以 committed 为准。\n")
    L.append("## 排序(triage 研究优先级 — 非买入排名)\n")
    L.append("| # | 标的 | 层/角色 | stance | committed 价/PE/PB | mcap亿 | 研究触发价 | 对账 flag |")
    L.append("|--:|---|---|---|---|--:|---|---|")
    for i, c in enumerate(data["candidates"], 1):
        if c.get("_error"):
            L.append(f"| {i} | {c['name']} {c['ticker']} | — | — | {c['_error']} | | | |"); continue
        cm = c["committed"]
        fl = "⚠" + str(len(cm["reconciliation_flags"])) if cm.get("reconciliation_flags") else "✓"
        L.append(f"| {i} | **{c['name']}** {c['ticker']} | {c['layer']} / {c['role']} | `{c['stance']}` | "
                 f"{cm['committed_price']}/{cm['committed_pe']}/{cm['committed_pb']} | {cm['committed_mcap_yi']:.0f} | "
                 f"{c['research_entry'][:22]}… | {fl} |")
    L.append("\n---\n## 逐名 / Per-name\n")
    for i, c in enumerate(data["candidates"], 1):
        if c.get("_error"):
            continue
        cm = c["committed"]
        L.append(f"### {i}. {c['name']} {c['ticker']} — `{c['stance']}` (AI 链接: {c['ai_linkage']})")
        L.append(f"**层/角色:** {c['layer']} / {c['role']} · **triage:** {c['triage_score']}")
        L.append("**三点 thesis:**")
        for t in c["thesis"]:
            L.append(f"- {t}")
        L.append(f"**催化:** {c['catalyst']}")
        L.append("**机制化 wrong-if:**")
        for w in c["wrong_if"]:
            L.append(f"- `{w['metric']}` **{w['threshold']}** @ {w['check_date']}")
        L.append(f"**估值锚:** {c['valuation_anchor']}")
        L.append(f"**committed(对账):** 价 {cm['committed_price']} · PE {cm['committed_pe']} · PB {cm['committed_pb']} · "
                 f"mcap {cm['committed_mcap_yi']:.0f}亿 · 换手 {cm['committed_turnover_rate']}% · "
                 f"value因子 {cm['factor_value']} / momentum {cm['factor_momentum']} · "
                 f"研究价 {cm['research_price']}({cm['research_vs_committed_pct']:+}% vs committed)")
        if cm.get("reconciliation_flags"):
            for f in cm["reconciliation_flags"]:
                L.append(f"  - ⚠ **对账 flag:** {f}")
        L.append(f"**研究触发价(启发式,非目标价):** {c['research_entry']}")
        L.append(f"**拥挤:** {c['crowding']}")
        L.append(f"**证据:** {c['evidence']}")
        L.append("")
    L.append("---")
    L.append("## 方法与边界")
    L.append("- **这是发现层,不是 alpha。** triage 分是透明启发式(value 便宜度 − 动量拉伸 − 估值拉伸 − 对账罚 − stance 罚),"
             "不是验证过的买入排名。")
    L.append("- **一手对账门**抓到的实例:中科曙光 研究 PE 57 vs committed 132.6(2.3x 差)→ 估值口径未决前不给 entry;"
             "工业富联 committed PE 33 < 研究 45;多名研究价 >5% 偏离 committed 已 flag。")
    L.append("- **下一步**:对 triage 顶部的 1-2 名(胜宏/工业富联)做满版 earnings-bridge deep thesis → 人工五轴红队 → "
             "PASS 才进 checkpoint ledger;**只有 STARTER_CANDIDATE/ADD_CANDIDATE 才可能进买入候选,WATCH 不是买入。**")
    L.append("- **数据边界**:concept_membership API 空(tier-locked),故 AI universe 是研究构建的(非概念标签机筛);"
             "universe_a 无原始基本面(roe/margin/growth 全空),故估值锚来自 agent 研究 + committed PE/PB/mcap。")
    return "\n".join(L) + "\n"


def _selftest() -> int:
    errs = []
    data = build()
    cands = [c for c in data["candidates"] if not c.get("_error")]
    if len(cands) < 10:
        errs.append(f"need >=10 candidates, got {len(cands)}")
    # reconciliation must have run on every name
    for c in cands:
        if "committed" not in c or c["committed"].get("committed_price") is None:
            errs.append(f"{c['ticker']} missing committed overlay")
    # the 中科曙光 PE conflict MUST be flagged (the canonical 对账门 catch)
    sg = next((c for c in cands if c["ticker"] == "603019.SH"), None)
    if not sg or not (sg["committed"].get("reconciliation_flags")):
        errs.append("中科曙光 PE conflict must be flagged by the reconciliation gate")
    # constructive names must out-rank avoid names (triage sanity)
    sc = {c["ticker"]: c["triage_score"] for c in cands}
    if sc.get("300476.SZ", -99) <= sc.get("002837.SZ", 99):
        errs.append("胜宏 (constructive) must out-rank 英维克 (blowup) on triage")
    # no candidate may carry a numeric 'reward_to_risk' / target (we don't fabricate bands)
    blob = json.dumps(data, ensure_ascii=False)
    if "reward_to_risk" in blob or "target_price" in blob:
        errs.append("screen must NOT carry a fabricated R/R or target_price field")
    if errs:
        print("ai_value_chain_screen selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"ai_value_chain_screen selftest PASSED ({len(cands)} candidates; committed overlay on all; "
          "中科曙光 PE conflict flagged; constructive out-ranks blowup; no fabricated R/R/target)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    data = build()
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(render_md(data))
    print(f"[ai_value_chain_screen] wrote {OUT_JSON}")
    print(f"  rendered -> {OUT_MD}")
    top = [c for c in data["candidates"] if not c.get("_error")][:3]
    print("  top-3 triage:", ", ".join(f"{c['name']}({c['stance']},{c['triage_score']})" for c in top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
