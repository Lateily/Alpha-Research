# Core Thesis Rescan — BYD Removed From Active Sample

Date: 2026-06-13  
Scope: Core Thesis Factory research queue, not Quant Strategy Factory.  
Status: internal research support only; no automated trade, no position size, no buy instruction.

## 中文执行摘要

- **BYD 已移出 active 前向验证样本**:不是删除历史,而是把 `002594.SZ` 的 checkpoint registration 标成 `ARCHIVED`;历史决策书、红队记录、lock 全部保留。
- **当前 active 长线研究样本只剩两只**:华海清科、鼎龙股份,二者仍是 `WATCH_ONLY`,不是买入名单。
- **全 A 股 Core screen 已重跑**:先修掉 stale-price 漏洞,否则退市/长期停牌标的会污染前排;新过滤剔除 300 个 stale-price 名字。
- **重扫结果不是买入清单**:它只回答"下一批值得写完整决策书的是谁",不直接回答"今天买谁"。
- **建议下一批决策书顺序**:华泰证券 → 中国船舶 → 当升科技。这样避免把前排一堆券商误当作多只独立机会。

## Executive Result

BYD (`002594.SZ`) has been removed from the ACTIVE forward-checkpoint sample by archiving its checkpoint registration. Its historical decision sheet, red-team record, and lock remain preserved for audit; it is no longer part of the live Core Thesis validation sample.

The active Core Thesis checkpoint sample is now:

| ticker | name | status | next checkpoint | current decision-sheet posture |
|---|---|---:|---:|---|
| `688120.SH` | 华海清科 | ACTIVE | 2026-07-12 | WATCH_ONLY |
| `300054.SZ` | 鼎龙股份 | ACTIVE | 2026-07-12 | WATCH_ONLY |

A full-market A-share Core screen was rerun after adding a hard stale-price filter. The previous screen could surface stale names; that is now blocked. The refreshed screen is a research-priority queue, not a buy list.

## Validation Boundary

Causal logic is valid for research triage because the screen ranks broad A-share names by currently available fundamental acceleration, mandatory-disclosure catalyst proximity proxy, value/low-volatility, and liquidity-risk features under PIT financial gating.

Causal logic is unestablished for immediate purchase because the screen does not yet produce a complete thesis, target band, wrong-if triggers, live price check, red-team score, or checkpoint registration.

Specific numbers are unvalidated intuitions unless otherwise labeled. The screen weights are inherited from Core Alpha Factory v0 and are not calibrated to realized Core Thesis outcomes. `expectation_revision` and `coverage_gap` remain unavailable full-market and are renormalized out. The local broad panel is as of `2026-05-26`, so this report supports candidate selection for decision sheets, not same-day execution.

## What Changed Mechanically

- Added `--archive` to `scripts/sheet_checkpoints.py` so active-sample removals are reproducible and history-preserving.
- Archived `002594.SZ` with reason: Junyan 2026-06-13 requested removal from the active Core Thesis checkpoint sample.
- Added a stale-price hard filter to `scripts/core_candidate_funnel.py`: candidates must have a last trade date within 5 calendar days of the panel `as_of`.
- Reran `core_candidate_funnel.py --top 50`; 300 stale-price names were excluded by the new filter.
- Reran `factory_progress.py`; the product progress surface now shows 2 ACTIVE Core Thesis names and the BYD archive/rescan milestone.

## Full-Market Screen Top 20

As of panel date `2026-05-26`; all rows are `RUN_THESIS`, meaning "worth producing a forward-validatable thesis to test," not "buy."

| rank | ticker | name | score | fundamental | value/lowvol | liquidity | last trade |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | `601108.SH` | 财通证券 | 79.22 | 0.9522 | 0.9496 | 0.8988 | 2026-05-26 |
| 2 | `601688.SH` | 华泰证券 | 78.35 | 0.8860 | 0.9682 | 0.9605 | 2026-05-26 |
| 3 | `600999.SH` | 招商证券 | 77.53 | 0.8542 | 0.9640 | 0.9791 | 2026-05-26 |
| 4 | `601066.SH` | 中信建投 | 76.96 | 0.9358 | 0.8760 | 0.8699 | 2026-05-26 |
| 5 | `601169.SH` | 北京银行 | 76.89 | 0.8378 | 0.9984 | 0.9390 | 2026-05-26 |
| 6 | `600015.SH` | 华夏银行 | 76.19 | 0.8263 | 0.9968 | 0.9216 | 2026-05-26 |
| 7 | `600546.SH` | 山煤国际 | 76.01 | 0.9306 | 0.8056 | 0.8932 | 2026-05-26 |
| 8 | `600150.SH` | 中国船舶 | 75.98 | 0.9672 | 0.6970 | 0.9268 | 2026-05-26 |
| 9 | `002797.SZ` | 第一创业 | 75.90 | 0.9249 | 0.7253 | 0.9788 | 2026-05-26 |
| 10 | `300073.SZ` | 当升科技 | 75.46 | 0.9534 | 0.6366 | 0.9836 | 2026-05-26 |
| 11 | `600030.SH` | 中信证券 | 75.13 | 0.7813 | 0.9483 | 0.9965 | 2026-05-26 |
| 12 | `600906.SH` | 财达证券 | 74.98 | 0.9531 | 0.8400 | 0.7521 | 2026-05-26 |
| 13 | `300457.SZ` | 赢合科技 | 74.77 | 0.9730 | 0.6195 | 0.9202 | 2026-05-26 |
| 14 | `600872.SH` | 中炬高新 | 74.55 | 0.9191 | 0.7532 | 0.8815 | 2026-05-26 |
| 15 | `600570.SH` | 恒生电子 | 74.32 | 0.9714 | 0.5861 | 0.9300 | 2026-05-26 |
| 16 | `002120.SZ` | 韵达股份 | 74.29 | 0.8735 | 0.9033 | 0.8068 | 2026-05-26 |
| 17 | `000686.SZ` | 东北证券 | 74.27 | 0.8468 | 0.9666 | 0.7954 | 2026-05-26 |
| 18 | `600008.SH` | 首创环保 | 74.22 | 0.8301 | 0.9698 | 0.8227 | 2026-05-26 |
| 19 | `000001.SZ` | 平安银行 | 74.10 | 0.7328 | 0.9978 | 0.9820 | 2026-05-26 |
| 20 | `000933.SZ` | 神火股份 | 73.95 | 0.9621 | 0.6796 | 0.8327 | 2026-05-26 |

## Read Of The Screen

The raw top ranks cluster heavily in brokers and banks. That is useful as a market-regime signal, but it is not a diversified buy-decision set. A Core Thesis decision sheet should avoid simply taking the first five financials; otherwise we risk testing one sector beta rather than research quality.

Recommended decision-sheet order:

| priority | ticker | name | reason to test | caveat before buy support |
|---:|---|---|---|---|
| 1 | `601688.SH` | 华泰证券 | Highest-quality representative of the broker cluster after removing pure rank duplication; high value/low-vol and liquidity scores. | Need a concrete catalyst and variant perception; otherwise this is just brokerage beta. |
| 2 | `600150.SH` | 中国船舶 | Non-financial, high fundamental-acceleration score; tests whether the factory can form a cyclical/shipbuilding thesis. | Needs orderbook, margin-cycle, and valuation-band work; screen alone is insufficient. |
| 3 | `300073.SZ` | 当升科技 | Battery-materials candidate with high fundamental and liquidity scores; useful orthogonal test versus existing semiconductor materials sheets. | Requires live price update and commodity/customer-cycle risk work. |
| 4 | `300457.SZ` | 赢合科技 | Battery equipment candidate; high fundamental score and different value-chain exposure from 当升. | Needs capex-cycle and receivables/cash-conversion checks. |
| 5 | `600570.SH` | 恒生电子 | Fintech/market-infrastructure candidate; tests software/market-cycle logic rather than pure financial balance-sheet beta. | Value score is weaker; requires evidence of product-cycle or policy catalyst. |

Names not recommended as the first post-BYD decision sheets despite high raw ranks: multiple additional brokers (`601108.SH`, `600999.SH`, `601066.SH`, `600030.SH`, `002797.SZ`, `600906.SH`, `000686.SZ`) because the cluster likely represents a common financial-sector factor. They can remain in the queue, but they should not all become active theses at once.

## Buy-Decision Support Status

No new stock in this rescan is cleared for a buy decision today.

For a name to support a buy decision under Core Thesis Factory rules, it still needs:

1. A complete decision sheet with base/bull/bear target bands, assumptions, mechanical wrong-if triggers, and execution posture.
2. A live price check, not just the local panel `2026-05-26` snapshot.
3. Junyan five-axis red-team PASS.
4. Checkpoint registration if it becomes part of the forward-validation sample.

Until those gates pass, the correct product state is `RUN_THESIS`, not `BUY`.

## Next Action

Run full decision sheets, in order, for:

1. `601688.SH` 华泰证券
2. `600150.SH` 中国船舶
3. `300073.SZ` 当升科技

That gives one broker/market-infrastructure exposure, one cyclical industrial exposure, and one battery-materials exposure. If any sheet resolves to WATCH_ONLY or fails red-team, move down the queue rather than forcing a buy.
