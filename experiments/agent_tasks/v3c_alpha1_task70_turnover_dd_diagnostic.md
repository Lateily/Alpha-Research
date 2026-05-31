# V3C-alpha1 Task 70 Turnover + Drawdown Diagnostic

Read-only diagnostic using existing artifacts only. No production scripts, docs, public/data outputs, or strategy variants were changed or run.

## 1. Headline

- Full 20yr: CAGR -2.81%, final NAV 5,715,140, max DD -59.23%, avg gross 16.89%.
- Turnover gate failure is broad-based: canonical annual turnover 8.52x (851.98%) vs 2.00x gate; annualized trades 379.7.
- Reported same-gross alpha point is 9.39%, CI [-14.16%, 39.95%], p=0.4758; it is not statistically validated.

Specific numbers are validated against data from the listed JSON artifacts unless explicitly marked as proxy or unavailable.

## 2. Turnover Anatomy

- Trade dates: 530 from 2006-04-10 to 2026-05-13; median gap 14.0 calendar days.
- Buys/sells: 3734 buys and 3725 sells. Every sell action is `sell_time_stop`.
- Per trade date: avg buys 7.05, avg sells 7.03, avg traded notional/NAV 31.66%.
- Full-refresh-like dates: 476/530 (89.81%). Avg final carry-over names 1.44; avg untouched carry-over names 0.81.
- Same-day sell/rebuy loops: 334 events, 8.97% of sells. Pure sizing-only dates proxy: 0.
- FIFO holding period proxy: avg 15.5 calendar days / 10.3 trading days; 99.44% closed within 15 trading days.

Top same-day rebuy tickers:
- 600383.SH: same-day rebuys 4, buys 12, sells 12
- 000895.SZ: same-day rebuys 4, buys 11, sells 11
- 600703.SH: same-day rebuys 3, buys 9, sells 9
- 000584.SZ: same-day rebuys 2, buys 5, sells 5
- 600620.SH: same-day rebuys 2, buys 6, sells 6
- 000839.SZ: same-day rebuys 2, buys 4, sells 4
- 000652.SZ: same-day rebuys 2, buys 5, sells 5
- 600369.SH: same-day rebuys 2, buys 5, sells 5

Causal logic is valid because trade replay shows a fixed time-stop close/reopen rhythm: all exits are `sell_time_stop`, most dates trade a large fraction of the book, and same-day rebuy loops are common. Specific numbers are validated against `trade_log_full` and reconstructed holdings.

## 3. Underwater Anatomy

- Peak before max DD: 2008-01-15 NAV 13,082,380.
- Trough: 2024-09-18 NAV 5,333,415, DD -59.23%.
- Final: 2026-05-25 NAV 5,715,140, still DD -56.31%.
- Time below high-water mark: 4810/4950 trading days (97.17%).
- Longest underwater episode: 2008-01-16 to 2026-05-25, 4456 trading days, recovered=False.
- Worst rolling 252d DD: -22.97% ending 2008-11-07.

Yearly path:
| Year | Return | Local Max DD | Full-Curve Min DD | Avg Gross | Avg Pos | Trades | Turnover/Avg NAV |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2006 | 0.33% | -8.91% | -8.91% | 13.22% | 5.8 | 262 | 6.33x |
| 2007 | 20.88% | -8.20% | -8.20% | 15.63% | 7.8 | 379 | 7.95x |
| 2008 | -18.66% | -22.97% | -22.97% | 15.49% | 7.7 | 369 | 7.55x |
| 2009 | 8.07% | -6.45% | -20.63% | 18.10% | 7.8 | 388 | 9.16x |
| 2010 | -6.94% | -14.96% | -26.73% | 17.88% | 8.0 | 350 | 8.69x |
| 2011 | -13.70% | -15.88% | -30.84% | 17.52% | 7.8 | 372 | 8.49x |
| 2012 | -4.64% | -12.22% | -36.36% | 19.72% | 7.7 | 382 | 10.03x |
| 2013 | -1.68% | -6.97% | -35.07% | 18.15% | 7.9 | 356 | 8.33x |
| 2014 | -2.32% | -7.98% | -37.34% | 18.75% | 8.0 | 386 | 9.42x |
| 2015 | 5.55% | -13.42% | -36.52% | 15.18% | 7.6 | 342 | 7.35x |
| 2016 | -10.87% | -11.33% | -40.26% | 16.60% | 7.9 | 376 | 8.27x |
| 2017 | -5.59% | -9.13% | -43.81% | 13.04% | 7.9 | 294 | 6.32x |
| 2018 | -11.12% | -11.79% | -49.54% | 15.90% | 7.9 | 352 | 7.67x |
| 2019 | 6.26% | -2.67% | -49.43% | 18.39% | 8.0 | 400 | 9.11x |
| 2020 | -2.69% | -8.73% | -49.81% | 17.10% | 7.7 | 371 | 8.06x |
| 2021 | -3.02% | -4.83% | -49.33% | 16.13% | 8.0 | 384 | 7.70x |
| 2022 | -8.52% | -8.80% | -53.34% | 16.41% | 8.0 | 400 | 8.22x |
| 2023 | -5.66% | -7.02% | -55.98% | 17.68% | 8.0 | 384 | 8.50x |
| 2024 | -3.94% | -7.72% | -59.23% | 19.22% | 8.0 | 384 | 9.18x |
| 2025 | 1.90% | -4.96% | -58.96% | 17.37% | 8.0 | 384 | 8.31x |
| 2026 | 0.43% | -2.44% | -56.90% | 17.77% | 8.0 | 144 | 3.20x |

Causal logic is valid because the max drawdown is a long unrecovered underwater regime, not one isolated crash: the strategy remains below HWM for most trading days and the longest episode is still unrecovered at sample end. Specific numbers are validated against `equity_curve`.

## 4. Regime/Subperiod Attribution

Subperiod dates are explicit diagnostic proxies, not calibrated regime boundaries.

| Regime | Period | Strat Ret | Same-Gross Ret | Approx SG Excess | Strat Max DD | Avg Gross | Turnover/Avg NAV | CSI300 | CSI500 | CSI1000 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2008_crash | 2007-10-16 to 2008-11-04 | -18.62% | -14.52% | -4.09% | -22.78% | 14.11% | 7.57x | -72.30% | -69.38% | -68.79% |
| 2015_bubble_crash | 2014-11-21 to 2016-01-28 | -2.95% | 8.01% | -10.95% | -16.63% | 15.28% | 8.99x | 10.46% | 4.80% | 13.78% |
| 2018_trade_war | 2018-01-24 to 2019-01-04 | -10.99% | -7.56% | -3.43% | -11.79% | 15.84% | 7.30x | -30.84% | -34.15% | -36.40% |
| 2020_covid | 2020-01-02 to 2020-04-30 | -6.61% | -1.37% | -5.24% | -8.73% | 15.80% | 2.43x | -5.77% | -0.23% | 0.03% |
| 2022_selloff | 2021-12-13 to 2022-10-31 | -8.61% | -5.54% | -3.08% | -9.27% | 16.48% | 6.91x | -30.98% | -21.02% | -21.19% |
| 2024_trough | 2023-05-08 to 2024-02-05 | -6.68% | -6.97% | 0.29% | -8.15% | 16.32% | 5.90x | -21.22% | -28.62% | -35.95% |

Causal logic is valid for descriptive attribution because returns/DD/gross/turnover are directly measured over named windows. Causal claims about why each regime behaved that way are unestablished without factor/holding snapshots beyond trades and curves. Specific numbers are validated against curves; same-gross subperiod alpha is an approximation from equity curves.

## 5. Benchmark Comparison

| Curve | Total Return | CAGR | Max DD | Peak | Trough | End Equity |
|---|---:|---:|---:|---|---|---:|
| strategy | -42.85% | -2.71% | -59.23% | 2008-01-15 | 2024-09-18 | 5,715,140 |
| ew_500 | -56.08% | -3.96% | -95.30% | 2008-01-15 | 2024-09-18 | 4,435,168 |
| ew_500_same_gross | 77.66% | 2.86% | -18.34% | 2015-06-12 | 2024-09-18 | 17,767,061 |
| cash_2pct | 47.54% | 1.93% | 0.00% | 2006-01-04 | 2006-01-04 | 14,754,753 |
| csi300 | 422.78% | 8.45% | -72.30% | 2007-10-16 | 2008-11-04 | 52,278,001 |
| zz500 | 898.46% | 11.95% | -72.42% | 2008-01-15 | 2008-11-04 | 99,846,169 |
| csi1000 | 932.14% | 12.13% | -72.51% | 2008-01-15 | 2008-11-04 | 103,213,978 |

Diagnosis: drawdown is not just absolute market beta. Strategy final NAV is below cash and far below CSI300/CSI500/CSI1000 curves in the same artifact. It also trails the same-gross EW-500 curve on terminal equity, even though the stored bootstrap same-gross alpha point is positive and statistically unvalidated. Causal logic is valid for benchmark-relative underperformance because curves are in the artifact; specific alpha significance remains unestablished because CI straddles zero.

## 6. Position-Level Attribution

Sector map status: no PIT sector field exists in the required artifacts. `concept_membership.json` is available only as a current thematic proxy, so sector attribution is marked unavailable; ticker-level FIFO P&L is the safe proxy.

Worst realized round trips:
| Ticker | Name | Entry | Exit | P&L | Return | Hold Days | Concepts Proxy |
|---|---|---|---:|---:|---:|---:|---|
| 600166.SH | 福田汽车 | 2011-04-29 | 2011-05-16 | -164460 | -50.10% | 17 |  |
| 002019.SZ | 亿帆医药 | 2016-05-06 | 2016-05-20 | -130980 | -64.10% | 14 | 银屑病 |
| 600109.SH | 国金证券 | 2009-05-22 | 2009-06-09 | -127007 | -45.27% | 18 |  |
| 600783.SH | 鲁信创投 | 2011-06-28 | 2011-07-12 | -99824 | -43.60% | 14 |  |
| 600022.SH | 山东钢铁 | 2009-04-09 | 2009-04-23 | -99020 | -38.00% | 14 |  |
| 000979.SZ | 中弘退 | 2011-02-16 | 2011-03-02 | -95431 | -46.49% | 14 |  |
| 000776.SZ | 广发证券 | 2010-04-30 | 2010-05-17 | -89829 | -29.91% | 17 |  |
| 002024.SZ | ST易购 | 2008-08-22 | 2008-09-05 | -86788 | -25.10% | 14 | 阿里巴巴概念 |
| 000836.SZ | ST富通 | 2009-05-22 | 2009-06-09 | -82680 | -36.45% | 18 |  |
| 600591.SH | *ST上航 | 2008-01-14 | 2008-01-28 | -81753 | -26.76% | 14 |  |
| 000831.SZ | 中国稀土 | 2015-06-26 | 2015-07-14 | -79220 | -47.78% | 18 |  |
| 300381.SZ | 溢多利 | 2016-09-29 | 2016-10-20 | -77959 | -55.72% | 21 | 饲料 |
| 000563.SZ | 陕国投Ａ | 2013-07-09 | 2013-07-23 | -77882 | -49.96% | 14 | 陕西自贸区 |
| 000036.SZ | 华联控股 | 2008-01-14 | 2008-01-28 | -76363 | -16.61% | 14 |  |
| 000897.SZ | 津滨发展 | 2008-05-15 | 2008-05-29 | -73107 | -37.30% | 14 | 雄安地产 |

Worst tickers by aggregate realized FIFO P&L:
| Ticker | Name | P&L | Trades | Return on Buy Notional | Gross Loss | Concepts Proxy |
|---|---|---:|---:|---:|---:|---|
| 600166.SH | 福田汽车 | -164613 | 3 | -25.00% | -167880 |  |
| 600703.SH | 三安光电 | -160309 | 9 | -8.87% | -174891 | 集成电路概念 |
| 000776.SZ | 广发证券 | -126258 | 2 | -20.12% | -126258 |  |
| 600783.SH | 鲁信创投 | -126007 | 4 | -16.46% | -142686 |  |
| 600868.SH | 梅雁吉祥 | -119821 | 4 | -10.88% | -128948 |  |
| 600022.SH | 山东钢铁 | -117384 | 2 | -25.82% | -117384 |  |
| 002019.SZ | 亿帆医药 | -114926 | 2 | -28.12% | -130980 | 银屑病 |
| 002500.SZ | 山西证券 | -113777 | 4 | -14.39% | -113777 |  |
| 000979.SZ | 中弘退 | -105914 | 2 | -26.38% | -105914 |  |
| 000920.SZ | 沃顿科技 | -100546 | 2 | -24.00% | -100546 | 高性能膜 |
| 002252.SZ | 上海莱士 | -99824 | 4 | -13.70% | -100970 | 阿尔茨海默概念 |
| 600515.SH | 海南机场 | -96042 | 4 | -11.63% | -96042 |  |
| 000783.SZ | 长江证券 | -94887 | 6 | -5.98% | -132827 |  |
| 600692.SH | 亚通股份 | -93811 | 3 | -11.47% | -93811 |  |
| 000722.SZ | 湖南发展 | -91890 | 7 | -6.45% | -132026 | 页岩气, 长江经济带 |

Top 5 loss tickers explain 2.65% of gross realized losses; top 10 explain 4.90%.

Causal logic is questionable for sector attribution because no true sector map is present. Causal logic is valid for ticker-level loss concentration because it is reconstructed from executed trades. Specific ticker P&L numbers are validated against `trade_log_full` using FIFO; sector/concept labels are proxy only.

## 7. Major Hypotheses

- Turnover is caused primarily by fixed time-stop full close/reopen cadence rather than small sizing adjustments. Causal logic is valid because every sell in trade_log_full has action=sell_time_stop; trade dates average roughly one rebalance every two to three weeks; same-day sell+buy loops are common; pure sizing-only dates are near absent by holdings reconstruction. Specific numbers are validated against data.
- Turnover is full-refresh-like basket replacement with partial carry-over/rebuy, not a stable basket with occasional bottom swaps. Causal logic is valid because most trade dates liquidate a large share of the pre-date book and open a large share of the post-date book; carry-over often occurs through same-day sell/rebuy rather than untouched holding continuity. Specific numbers are validated against data.
- The -59% drawdown is not one isolated crash; it is a permanent underwater path after a pre-2010/early-cycle high with repeated failed recoveries. Causal logic is valid because drawdown trough occurs years after the prior high, time below high-water mark dominates the sample, and the longest underwater episode is unrecovered at the sample end. Specific numbers are validated against data.
- Drawdown is not pure absolute market beta. Causal logic is valid because full-period strategy loses capital while CSI300/CSI500/CSI1000 curves compound strongly in the same artifact set; same-gross EW comparison also does better in terminal NAV. Specific numbers are validated against data.
- Stored same-gross alpha proves α1 is economically ready. Causal logic is unestablished because bundle same_gross alpha point is positive but CI straddles zero and BY/raw p is high; terminal same-gross benchmark curve still materially exceeds strategy NAV. Specific numbers are validated against data for reported point/CI/p; interpretation remains unestablished.
- Sector losses explain the failure. Causal logic is questionable because no true sector map is available in required artifacts; concept_membership is a thematic proxy only and current universe_a is a point-in-time snapshot, not PIT sector classification. Specific numbers are unvalidated intuition for sector; ticker P&L is validated against trade_log_full.

## 8. Implications For alpha1.1 Design

- Add explicit hold-continuation/rank-buffer or replacement-band mechanics before adding factors; current cadence closes and reopens the book on a time-stop rhythm.
- Separate exit rule from rebalance rule: a 10-day alpha horizon does not require full liquidation/rebuy of surviving names every cycle.
- Risk control must address persistent underwater exposure, likely via volatility scaling/regime gating/hedging; a tighter stop alone is unlikely to fix repeated re-entry drawdowns.
- Keep max_gross unchanged until turnover and DD mechanics are fixed; raising gross would scale the same failure.
- Treat alpha1 as a statistical lead only: same-gross point estimate is not statistically validated and walk-forward consistency is insufficient.

Do not implement alpha1.1 from this report alone. The next manifest should isolate mechanics: hold-continuation/rank buffer, turnover budget, and persistent-underwater risk control, while keeping the factor hypothesis clean enough to avoid p-hacking.

## Files

- Source: `public/data/v3c_alpha1_full_20yr_baseline_0.40_RT.json`
- Source: `public/data/v3c_alpha1_bundle.json`
- Source: `/tmp/v3c_gate/v3c_alpha1_phaseBfix_gate_eval.json`
- Source: `/tmp/v3_phaseB_fix_report.md`
- JSON report: `experiments/agent_tasks/v3c_alpha1_task70_turnover_dd_diagnostic.json`
- Markdown report: `experiments/agent_tasks/v3c_alpha1_task70_turnover_dd_diagnostic.md`
