# Multi-Agent Phase 1.5 — Business-Mechanism Contrarian View Achieved

> **Headline:** Junyan's BYD packet hand-review (2026-05-08) flagged
> theses as "valuation-pitch dressed as research" — agents compared
> P/E / DCF / OHLC numbers but never articulated WHY consensus is
> wrong via business mechanism. After 2 prompt + 1 data-render
> iteration (commits 34b3edd → 03dd31d), **3 of 4 watchlist tickers
> now produce business-level contrarian theses citing specific
> broker reports, institutional visits, and business mechanisms.**
> BYD specifically achieved score 100 PASS with LONG direction
> backed by 4-broker-citation mechanism.

---

## 1. The breakthrough — BYD synthesizer's variant view

Direct quote from Synth output (commit 03dd31d post-deploy):

> "Market believes BYD is a domestic price-war hostage with margins
> eroding toward the 15% floor → We believe **Q1's sequential GM
> improvement (per 国联民生证券 2026-04-30)** is the first proof that
> export mix is already re-rating consolidated profitability →
> Mechanism is overseas volume + ASP/margin uplift compounding through
> Q2/Q3, **validated by pre-Q1 institutional diligence from
> 高盛/国寿资产/Value Partners**."

Compare to pre-fix (2026-05-08 17:02 UTC, commit 34b3edd before
Phase 1.5):

> "Market is anchored to backward-looking metrics like the high TTM
> P/E of 51.3x. Consensus forecasts predict massive earnings surge
> for 2024. Stock will re-rate beyond 119.55."

Pre-fix: pure valuation arithmetic, 0 broker citations, "Q3 Q4 2024
results" temporal hallucination.

Post-fix: **specific broker name + report date + Chinese title quote
+ business mechanism + smart-money diligence timeline + falsifiable
prediction**.

---

## 2. What changed — 2-step iteration

### Phase 1 (commit 34b3edd) — surface narrative data + add SYSTEM constraint

**Diagnosis:** rich Tushare data (245 broker reports, 8 institutional
research surveys, chip distribution, holder transactions) was loaded
into JSON but `buildExtrasBlock` only surfaced summary counts. Bull/
Bear agents never saw report titles, broker names, or visit details.

**Fix:**
- `api/research.js buildExtrasBlock` rewritten to render top 8 broker
  reports (with title + broker + rating + target + EPS/NP forecast),
  6 institutional visits (with org + type + visitor), 5 chip price
  levels by % concentration, margin trade detail, capital structure
  signals, recent consensus forecast time-series
- `api/research-multi.js` BULL_ROLE_SYSTEM and BEAR_ROLE_SYSTEM gained
  CONTRARIAN_VIEW_REQUIREMENT block:
  - Forbidden: "P/E low so cheap" / "DCF says cheap" / generic
    "anchored to lagging indicators"
  - Required: business mechanism with specific data citations
  - Allowed exit: emit "INSUFFICIENT_NARRATIVE_DATA" → PASS

**Result:** mixed. Data IS in prompt (verified via local node test
showing 8 broker titles like "海外销量增长势头强劲" rendered correctly).
But Bull r2 / Bear r2 STILL produced valuation-only thesis citing
TTM P/E + Forward P/E, ignoring the broker data entirely. SYSTEM-only
constraint not enough for Gemini/GPT-5.5 to override training-data
templates.

### Phase 1.5 (commit 03dd31d) — HARD CITATION DIRECTIVE in user prompts

**Diagnosis:** SYSTEM_PROMPT carries the constraint, but USER prompt
just says "Produce thesis. Schema: ...". LLM doesn't connect "data
context above contains broker reports" with "system says cite broker
reports". Need to spell it out in the task prompt.

**Fix:** added HARD_CITATION_DIRECTIVE to all 4 task prompts (bullR1,
bearR1, bullR2, bearR2):
- **Rule 1**: mechanism_chain MUST quote 2+ from (a) BROKER report
  title (b) inst visit (c) 龙虎榜 (d) holder tx (e) news event
- **Rule 2**: our_variant MUST reference one of (a)-(e) in format
  "Per [broker] [date] '[exact title]', [business mechanism]"
- **Rule 3**: empty sections → emit INSUFFICIENT_NARRATIVE_DATA + PASS
- **Rule 4**: forbidden chains shown explicitly with ✗
- **Rule 5**: required chains shown with ✓ + worked examples
- **Pre-emit check**: explicit if/then about whether mech_chain[0]
  cites broker name + report title

Each rebuttal (round 2) prompt also gets a "if round 1 didn't cite,
this is your chance" reminder.

**Result:** Phase 1.5 BYD test 2026-05-08 17:14 UTC delivered 100
PASS LONG with all agents citing specific brokers. Synth thesis quoted
above. Forensic auto-populated `bull_contrarian_quality:
BUSINESS_MECHANISM` and `bear_contrarian_quality: BUSINESS_MECHANISM`.

---

## 3. 4-ticker results post Phase 1.5

| Ticker | Score | Sev | Direction | Divergence | Bull quality | Bear quality | Tushare data |
|---|---|---|---|---|---|---|---|
| 002594.SZ BYD | **100** | PASS | **LONG** | 45 | BUSINESS_MECHANISM | BUSINESS_MECHANISM | rich (245 reports, 8 visits, chip OK) |
| 300308.SZ Innolight | 84 | PASS | PASS | 65 | BUSINESS_MECHANISM | BUSINESS_MECHANISM | rich (similar to BYD) |
| 175.HK Geely | 74 | WARN | PASS | 45 | **VALUATION_ONLY** | **VALUATION_ONLY** | thin (HK skip — see §5) |
| 603233.SH Da Shenlin | 78 | WARN | PASS | 70 | BUSINESS_MECHANISM | BUSINESS_MECHANISM | partial |

**3/4 tickers got BUSINESS_MECHANISM verdict.** The ONE failure
(Geely 175.HK) traces to a known Bridge 2 gap: **Tushare API does
not cover HK A-share broker reports / institutional visits / 龙虎榜
data**. Geely's `tushare_suite.broker_recommend` returns
`_status: skipped_hk`, same for `inst_research`, `holdertrade`, etc.
→ agents have NOTHING to cite → fall back to valuation arithmetic.

This isn't a prompt failure. It's a data-source coverage failure.
Bridge 2 next step (Phase 2 of fix path) is to add HK-side data:
- HKEx 披露易 (DII) for HK stock holder/insider data
- AA Stocks / 港交所 announcements
- HK broker note aggregators (Tipranks-HK, FactSet-HK if available)

---

## 4. BYD specifically — investment-grade thesis emerged

From the BYD Phase 1.5 synth output:

**LONG direction with full business mechanism:**
- Bull cited 4 broker reports: 国联民生证券 (毛利率环比改善), 华创证券
  (海外销量势头强劲 强推), 华金证券 (闪充带动产品矩阵升级 买入),
  东方证券 (海外销量高增 买入)
- Bull cited 3 institutional visits: 高盛 2026-04-02, 国寿资产
  2026-04-07, Value Partners 2026-04-09 — all PRE-Q1 release
- Bull mechanism: export mix lifting consolidated GM, smart money
  positioned BEFORE the broker upgrade cycle, technical alignment
- Bear cited 4 broker reports too, argued: fast-charging upgrade
  cycle is margin-negative, narrative crowding (60+ inst visit days)
- Synthesizer chose LONG: Bull's mechanism is more falsifiable
  (specific GM number to watch) vs Bear's narrative-crowding
  (meta-claim)
- Reward/risk: 2.7:1, 25% upside (target 125), 9% downside (stop 91)
- Position-sizing curve: 0% → 30% → 80% (monotonic per spec)

**This is investment-grade output.** Junyan can hand-review and
either:
1. Endorse → consider for paper-trading log (Bridge 8 next phase)
2. Critique specific claims (e.g., disagree with broker
   interpretations, identify missing risks)
3. Reject for known-but-unsurfaced reasons (e.g., recent news LLM
   doesn't have)

In all three cases, the artifact gives Junyan something **to react
to** rather than dismiss as "valuation arithmetic".

---

## 5. Geely 175.HK — Bridge 2 HK data gap exposed

Geely's synth thesis citation density is dramatically lower:
- Bull mechanism: cites only valuation multiples + chip distribution
  + persona ratings (Buffett/Graham scores from yfinance)
- Bear mechanism: also valuation arithmetic + technical
- Forensic verdict: VALUATION_ONLY × 2

Coverage status for Geely from `_tushare_coverage`:
```
broker_recommend:    skipped_hk
inst_research:       skipped_hk
holdertrade:         skipped_hk
margin:              skipped_hk
top_inst:            skipped_hk
lhb:                 skipped_hk
... (most Tushare endpoints don't cover HK)
```

This is a Bridge 2 KR that we always knew existed but didn't prioritize
until now. Without HK-side narrative data, the LLM team can produce
ABOUT THE SAME quality as a single-agent valuation pitch on HK names.

**Phase 2 KR:** integrate HK data sources for narrative coverage.
Options to evaluate:
1. HKEx Disclosure of Interests (DII) for insider/large-holder
2. AAStocks broker rating aggregator (rate limit constraints)
3. Bloomberg HK research summaries (paid, expensive)
4. Eastmoney HK broker rating (free, scraping-feasible)
5. SCMP / 信报 / 香港经济日报 financial news (paid?)

Recommend evaluating 4 + 5 first as cheapest path.

---

## 6. Cost + verification methodology

This iteration cost: ~$5 ($1 BYD Phase 1 + $1 BYD Phase 1.5 + $3
4-ticker post-fix). 

Total accumulated this shift: ~$13.

Methodology (reproducible):
```bash
# Step 1: regenerate buildExtrasBlock + commit prompts
git push  # triggers Vercel auto-deploy

# Step 2: wait for Vercel ready
until curl -sS .../api/research-multi -X OPTIONS -w "%{http_code}" | grep -q 200; do sleep 4; done

# Step 3: run 1 ticker probe (no parallel waste)
python3 scripts/run_research.py 002594.SZ --endpoint .../api/research-multi --out /tmp/test.json

# Step 4: drill into _bull_thesis / _bear_thesis / _forensic / synth output
python3 -c "import json; d=json.load(open('/tmp/test.json'))['data']; ..."

# Step 5: if BUSINESS_MECHANISM, scale to 4 tickers
# Step 6: regenerate packets, commit
```

---

## 7. What's next

### Immediate (Junyan-action)
1. **Re-review BYD packet** at [`docs/research/review/002594SZ_review_2026-05-10.md`](../review/002594SZ_review_2026-05-10.md)
   — does the Bull's mechanism + broker-citations + smart-money-timeline
   actually persuade you? Is this **investment-grade** thesis?

### Phase 2 KRs (queued)
2. **HK data coverage** (Geely fix) — see §5 above
3. **News pipeline** — currently `flow_data.json` for ticker often
   empty. Need Cailianpress / Tushare news_cct / 东财快讯 integration
   so Bull/Bear can cite recent news events
4. **Sector / competitor cross-section** — auto-load competitor fin
   alongside primary ticker (BYD vs 吉利/NIO/XPeng)
5. **Policy / regulatory context** — separate fetch for NEV policy /
   tariff news / industry mandates

### Multi-shift
6. **Bridge 8 outcome tracker** — when wrongIf conditions resolve,
   record + compute hit rate by thesis_quality bucket
7. **Auto-screening** — universe scan picks candidates worth deep
   research; current 4 tickers are manual

### Recommended sequence
Phase 2 next shift (4-5h): HK coverage (#2) + news (#3). Then Bridge 8
scaffold (#6). Then auto-screen (#7).

---

**Author:** T1 Claude (Phase 1 + 1.5 wave)
**Cost this iteration:** ~$5 / Total this shift: ~$13
**Direction confirmed working:** BYD LONG with investment-grade thesis
**Direction needing more work:** Geely VALUATION_ONLY — Bridge 2 HK gap
