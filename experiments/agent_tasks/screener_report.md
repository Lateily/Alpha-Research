# Screener Pipeline Report

Task: `2026-05-25-screener-pipeline`

## Funnel

| Stage | Count |
|---|---:|
| total | 5850 |
| after_distress | 5326 |
| after_suspended | 5242 |
| after_valuation | 3959 |
| after_microcap | 3563 |
| after_liquidity | 3292 |

## Top 10

| Rank | Ticker | Name | Composite | Alpha Score |
|---:|---|---|---:|---:|
| 1 | 600742.SH | 富维股份 | 75.860 | 77.9 |
| 2 | 600664.SH | 哈药股份 | 75.405 | 76.5 |
| 3 | 603045.SH | 福达合金 | 75.240 | 75.8 |
| 4 | 300482.SZ | 万孚生物 | 74.115 | 74.6 |
| 5 | 000828.SZ | 东莞控股 | 72.270 | 76.0 |
| 6 | 600587.SH | 新华医疗 | 72.200 | 75.7 |
| 7 | 600790.SH | 轻纺城 | 71.600 | 69.9 |
| 8 | 600033.SH | 福建高速 | 71.590 | 75.5 |
| 9 | 300815.SZ | 玉禾田 | 71.475 | 72.4 |
| 10 | 600368.SH | 五洲交通 | 71.475 | 69.9 |

## Caveats

Causal logic is valid because the screener removes non-actionable distress,
no-trade, valuation, micro-cap, and illiquidity cases before ranking surviving
stocks by precomputed cross-sectional factor scores.

Specific numbers are [unvalidated intuition]. The default factor weights,
PE cap, micro-cap decile, and liquidity floors have not been calibrated
against real trade history.

Data quality caveats observed:
- `source_fetched_at` is `2026-05-08T12:23:55.359808`, so the candidate list
  is based on a stale local universe snapshot.
- Raw fundamental fields such as ROE, gross margin, net margin, revenue growth,
  and profit growth are unpopulated in `universe_a.json`.
- The earnings-trend factor has no source yet; `size` is only a clearly
  labelled temporary stand-in.
- True sector-neutral scoring is not possible until an industry field is joined
  from `data_history/universe_pit.json`.
