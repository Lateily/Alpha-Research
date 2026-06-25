# 06-25 官方样本 · 解释层（Junyan-ratified 2026-06-25）

> This is the human-ratified interpretation layer for `samples/20260625.json` +
> `paper_signal_log.json`. The T+1/T+3/T+5/T+10 forward-return evaluation validates
> THESE specific claims. Research signals only — not buy/sell. Human executes.

## 口径确认（资金门已闭环 — 这是相对 price-only 版的关键升级）
- **市场不是 RISK_ON,是 WEAK_REPAIR:指数全红,但全市场主力 −214亿。**
- **新易盛 / 香农不是单纯价格强,而是 价格强 + 主力真回流**(新易盛 +36.73亿,香农 +7.71亿)。
- **利通不是普通回调,而是 主力 −11.75亿出货 + 小单 +9.15亿接盘 → WARNING 是正确姿态。**
- **组合仍是单一 AI/光模块 beta,不能因为两只强就判定风险解除(DE_RISK_REVIEW)。**

## 4 个验证假设（T+1/3/5/10 回填验证）
| # | 假设 | 验证对象 |
|---|---|---|
| H1 | 新易盛 REL_STRENGTH 有效 | 价格强+主力回流 → 正向 forward return |
| H2 | 香农 REL_STRENGTH 有效 | 同上 |
| H3 | 利通 WARNING 正确预警 | 主力出货 → 后续走弱/跑输 |
| H4 | 市场 WEAK_REPAIR 压制延续性 | 主力 −214亿 → 反抽难持续 |

## 明日 3 个检查点（看验证,不重新判断）
1. **大盘主力是否从 −214亿明显收窄**（反抽能否转修复的总开关）
2. **新易盛能否守 591 + 资金继续回流**（最强锚是否成立）
3. **利通能否站回 218-226,还是继续被资金派发**（WARNING 是否兑现）

**裁决规则:若这 3 点都不改善,今天只能当高 beta 反抽,不能当真正修复。**

## 样本 posture（机器算出,非手判）
| 标的 | 收盘 | 主力定盘 | 资金结构 | posture |
|---|---|---:|---|---|
| 新易盛 300502 | +9.94% | +36.73亿 | 主力回流 | HOLD_OBSERVE · REL_STRENGTH |
| 香农 300475 | +5.75% | +7.71亿 | 主力回流 | HOLD_OBSERVE · REL_STRENGTH |
| 利通 603629 | −5.08% | −11.75亿 | 大单卖小单接 | WARNING（破 205.6 → DE_RISK_REVIEW）|
| 组合 | — | — | 单一 AI beta | DE_RISK_REVIEW |
| 市场 | 指数全红 | −214亿 | — | WEAK_REPAIR |

数据源:Tushare 06-25 定盘（moneyflow_dc + daily + index_daily + moneyflow_mkt_dc）+ 前复权技术位。
