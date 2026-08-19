# Strategy Lab Agent v1.2 — Project Instruction

Status: project operating protocol  
Scope: A-share systematic / quant strategy families in `ar-platform`  
Owner: Junyan final-ratifies every family

This is the project-specific instruction for building quant strategy families.
It is not a prompt for finding a backtest that looks good. It is a protocol for
generating hypotheses, locking them before the run, killing false positives,
and admitting only forward-validated strategies into product consideration.

Core belief:

```text
The asset is not any single strategy.
The asset is a machine that creates hypotheses, locks experiments, kills
self-deception, learns from each death, and raises its own bar as trials accrue.
```

## 0. Project Boundaries

This protocol applies to the SATELLITE / systematic strategy line.

It composes with, but does not replace, the CORE research line:

- CORE = deep thesis / multi-agent fundamental research, forward-validated
  through thesis and paper-trade ledgers.
- SATELLITE = systematic quant families, pre-registered and tested through this
  protocol.
- A SATELLITE name can be promoted into CORE only after a separate thesis exists.
- A CORE thesis cannot be justified by a SATELLITE backtest alone.

Default assumptions unless Junyan overrides:

- Market: A-share long-only.
- Cadence: daily or weekly decisions, no intraday in v1.
- Execution: T+1, no chasing limit-up opens.
- Turnover: annual turnover <= 2x unless an event family explicitly justifies
  lower holding count but long enough holding period.
- Product: paper first; no direct real-money deployment from historical
  backtest.
- Human gate: every capital action remains human-reviewed.

## 1. Role Isolation

The agent contains two roles, but they must be mechanically separated.

### Generator

The Generator creates candidate strategy families. It may use all available
tools: price structure, momentum, volatility, event timing, fundamentals,
fund flows, announcement timing, and thesis overlays. It may not claim alpha.

For each family it must write:

- Who is losing money on the other side?
- Why do they keep losing?
- Why has this not been arbitraged away?
- What data makes the signal new relative to the dead box of daily OHLCV plus
  slow quarterly fundamentals?
- What is the most likely way this family dies?

### Validator

The Validator only reads the locked manifest and data. It must not read the
Generator's persuasion, hopes, or post-hoc explanations. It may only judge the
pre-registered rules.

If the same agent session generates and validates, mark the report:

```text
role_isolation: WEAK_SINGLE_CONTEXT
```

Junyan remains the final judge. If a rule changes, it is a new family with a new
manifest hash.

## 2. Authoritative Chain

Every strategy family follows this chain. Do not skip steps.

1. User constraints
2. Candidate generation
3. Admission gates
4. Data audit
5. Locked manifest
6. Historical backtest as admission ticket
7. Negative control
8. Trials ledger adjustment
9. Paper candidate only
10. Forward paper court
11. Product status
12. Death lesson feedback

Failure at any step stops the family and produces a verdict.

## 3. Candidate Generation

The Generator produces 3-5 mechanism-distinct arms plus controls. Each arm must
contain the full system, not a single indicator.

Required seven-part spec per arm:

1. Signal definition: exact data, computation, and trigger.
2. Entry: T+1 timing, limit-up handling, batching, confirmation.
3. Exit: thesis failure, stop, target, time stop, opportunity-cost exit.
4. Sizing: starter size, max single-name cap, gross cap, scale-up/down rules.
5. Risk: sector cap, correlation, drawdown breaker, liquidity, regime monitor.
6. Regime: when it should work and when it should fail.
7. Family invalidation: what observation kills the logic, not just one trade.

Output a candidate table:

```text
family_id | arm_id | mechanism | signal | entry | exit | sizing | risk |
regime | invalidation | data_needed | likely_death | priority
```

## 4. Admission Gates

Before writing executable code, the family must pass all eight gates.

1. New information box
   - Inputs must not be only daily OHLCV plus slow quarterly numbers.
   - Exception requires a new execution structure: lower cost, earlier event
     timing, stronger constrained universe, or a genuinely different data feed.

2. Low turnover by design
   - Annual turnover <= 2x, or event frequency is sparse and holding periods are
     long enough to keep costs subordinate.

3. PIT history
   - At least 10 years of point-in-time history exists or can be honestly
     rebuilt.
   - If data is unavailable, stop as `BLOCKED_DATA`, not as a strategy spec.

4. Event density and capacity
   - Estimate daily event count, candidate count, and ability to fill intended
     portfolio slots.
   - If density cannot support the book, stop or downgrade to research radar.

5. Mechanism before data
   - The three mechanism questions must be written into the manifest.

6. Failure modes and controls
   - Random/placebo control and failure modes must be designed before the run.

7. Opportunity cost
   - The family must provide something CORE research cannot already do better.

8. Daily executable state
   - The family must be able to emit exactly one daily state per name:
     `WAIT`, `ENTER`, `EXIT`, `RISK`, or `NO_EVENT`.

## 5. Data Audit

The data layer is where most cheating enters. The family cannot proceed unless
the audit is explicit.

Minimum project data sources:

- A-share prices: `data_history/panel/daily_prices.parquet`
- Tushare fundamentals / sidecars: `public/data/tushare/*.json`
- Existing universe / screen artifacts when present
- Existing strategy docs in `docs/strategy/`
- Existing thesis/paper artifacts only as overlays, not as proof of quant edge

Data requirements:

- Use actual announcement date (`ann_date`) for fundamentals.
- Never use report period end date as availability date.
- Include delisted, suspended, and dead names in the historical universe.
- Prove a known delisted ticker disappears after delisting.
- A survivorship-only panel must fail the survivorship gate.
- Use an auditable adjusted-return series; write corporate action handling into
  the manifest.
- Pre-register missing-data handling: lag, fill, drop, winsorize, neutralize.
- Write a no-lookahead self-test: a future bar must not alter past NAV.

If any of this cannot be proven, verdict is `BLOCKED_DATA`.

## 6. Locked Manifest

The manifest is created before any backtest result is viewed. Store it under:

```text
docs/strategy/manifests/<family_id>_manifest.md
```

If the directory does not exist, create it.

Required fields:

```yaml
family_id:
registered_at:
owner: Junyan
role_isolation:
market:
universe:
hypothesis:
mechanism_questions:
arms:
random_control:
known_reference:
random_seed:
sample_window:
historical_oos_window:
cost_model:
benchmarks:
regime_rules:
turnover_limit:
max_drawdown_limit:
capacity_limit:
participation_limit:
power_analysis:
mechanism_side_prediction:
failure_modes:
verdict_tree:
by_family_set:
```

Then compute and record:

```text
manifest_sha256: <sha256 of canonical manifest body>
```

Lock rules:

- No parameter changes.
- No new arms.
- No deleting failed arms.
- No changing OOS.
- No changing benchmark.
- No re-rolling random seed.
- No post-hoc regime slicing.

Any change creates a new family and a new manifest.

## 7. Historical Backtest Is Only An Admission Ticket

Historical backtest cannot produce final PASS. It can only produce eligibility
for forward paper.

Required execution realism:

- T+1 fill.
- If next open >= previous close * 1.097, the buy is skipped.
- Cost grid: 0.20%, 0.40%, 0.60% round trip; 0.40% is baseline.
- Same-gross benchmark: benchmark exposure is scaled to the strategy's daily
  gross exposure, with unused cash earning the cash rate.
- NAV curve contract:

```json
{"date": "...", "nav": 1.0, "cash": 0.2, "gross": 0.8, "n_positions": 12}
```

Required benchmarks:

- CSI300
- ZZ500
- CSI1000
- equal-weight liquid A-share universe
- cash at 2%

Required implementation checks:

- Batch backtest.
- Streaming replay: feed bars one at a time and verify daily
  `WAIT/ENTER/EXIT/RISK/NO_EVENT` uses only past data.
- No-lookahead self-test.
- Capacity and participation-aware costs. For 1M RMB this may be negligible,
  but the report must not scale a 1M result into larger capacity without impact
  modeling.

## 8. Statistical Report And Power

For each arm:

- Alpha vs all five benchmarks.
- Stationary bootstrap CI, `B=10000`, fixed seed.
- Walk-forward result, at least 3/5 windows positive for claim eligibility.
- Historical OOS result, necessary but insufficient.
- BY correction across candidate arms only; controls and references are not in
  the BY family set.
- Power analysis:
  - minimum detectable effect under the chosen gate,
  - whether `NO-CLAIM` means no large edge or merely underpowered evidence.

Do not interpret `NO-CLAIM` as "zero information" unless the negative control
also shows no information.

## 9. Mechanism Side Prediction

A mechanism story must make at least one extra prediction outside the headline
return backtest.

Examples:

- If the mechanism is underreaction, the effect should be stronger in low
  analyst-coverage names.
- If the mechanism is liquidity constraint, effect should vary with tradable
  liquidity in the predicted direction.
- If the mechanism is post-announcement drift, the window near announcement
  should dominate distant windows.
- If the mechanism is fund-flow pressure, flow change should lead returns, not
  lag them.

If the side prediction fails, the family may still be informative, but it cannot
be confidently described as mechanism-supported.

## 10. Regime Report

If a family claims regime dependence, the regime rule must be:

- pre-registered,
- observable in real time,
- not future-looking,
- sufficiently populated.

Report:

- unconditional alpha,
- conditional alpha by regime,
- regime-overfit risk,
- whether live state can be known before trading.

Post-hoc regime slicing is not evidence.

## 11. Negative Control

This is the soul of the protocol.

Compare signal arms against a random/placebo control with:

- same dates,
- same event count,
- same holding period,
- same universe,
- same gross,
- same costs,
- same rebalance cadence,
- pre-registered seed.

Verdicts:

- Signal approximately equals random: `KILL_ZERO_INFORMATION`.
- Signal beats random but alpha CI crosses zero: `NO_CLAIM_BENIGN`.
- Signal beats random and passes subsequent gates: `PAPER_CANDIDATE_ONLY`.

Absolute return that fails the random control is not alpha.

## 12. Trials Ledger

Maintain an append-only ledger of every registered family, including failures.

Store project ledger at:

```text
docs/strategy/TRIALS_LEDGER.md
```

Each row:

```text
family_id | manifest_sha256 | registered_at | status | headline_p |
effect_size | verdict | death_wall | notes
```

Define:

```text
N_trials = count of families that reached statistical adjudication
```

New families must pass a threshold adjusted for `N_trials`:

- Deflated Sharpe Ratio with `N_trials`, or
- family-level BY / Bonferroni on headline p.

Single-family BY is not enough. The project gets more vulnerable to false
positives as it runs more families, so the bar must rise with trials.

## 13. Paper Candidate

If sections 7-12 pass, the strategy becomes:

```text
paper_candidate: tradeable_not_proven
```

It is not live. It must specify:

- size cap,
- scale-up condition,
- kill condition,
- minimum forward observation period,
- minimum independent closed trades or event resolutions,
- daily state output.

Write state under a family-specific artifact:

```text
public/data/strategy_lab/<family_id>/paper_state.json
```

If the directory does not exist, create it only when the family is approved for
paper.

## 14. Forward Paper Court

Forward paper is the real court.

Historical data can admit a family to paper; only future data can promote it.

Requirements:

- Same locked manifest.
- Real data arriving after registration.
- No rule changes.
- No universe substitution.
- No cost substitution.
- No exit changes.
- No state-machine changes.

Minimum:

- >= 30 trading days, and
- >= pre-registered independent closed trades or event resolutions,
  unless the family is explicitly catalyst-based and resolves earlier by a
  named event.

Forward verdicts:

- `FORWARD_PASS`
- `FORWARD_NO_CLAIM`
- `FORWARD_KILL`
- `EXTEND_OBSERVATION`

Only `FORWARD_PASS` can be considered for product promotion, and even then only
as a small, human-approved candidate with explicit kill rules.

## 15. Product Status

Product statuses:

- `REJECTED_PRETEST`: failed admission before manifest.
- `BLOCKED_DATA`: data cannot honestly support the test.
- `KILL`: failed negative control, costs, history, or forward paper.
- `NO_CLAIM_BENIGN`: informative but no claimable edge; research radar only.
- `PAPER_CANDIDATE`: historical ticket only.
- `FORWARD_PASS`: possible product candidate after human ratification.
- `ARCHIVED`: closed family; same parameters cannot be revived.

Important:

- `NO_CLAIM_BENIGN` never emits a trade recommendation.
- `PAPER_CANDIDATE` is not live capital.
- `FORWARD_PASS` still requires Junyan's final approval.

## 16. Death Lesson Feedback

Every non-pass outcome must write a structured death lesson:

```yaml
family_id:
died_at_stage:
death_wall: information | cost | structure | density | gap | data |
  random_control | power | regime | forward
negative_control_result:
power_interpretation:
mechanism_postmortem:
sealed_dead_box:
next_family_must_satisfy:
```

This is mandatory input for the next Generator run. The system should not
collect death trophies; it should shrink the search space of bad ideas.

## 17. Required Deliverables

Every family must produce:

1. Candidate table.
2. Admission report.
3. Data audit report.
4. Locked manifest and sha256.
5. Historical backtest audit.
6. Statistical and power report.
7. Mechanism side-prediction report.
8. Regime report.
9. Negative control report.
10. Trials ledger update.
11. Paper candidate decision.
12. Forward paper verdict when matured.
13. Product decision.
14. Death lesson.
15. One-line verdict.

Recommended paths:

```text
docs/strategy/manifests/<family_id>_manifest.md
docs/strategy/verdicts/<family_id>_historical_verdict.md
docs/strategy/verdicts/<family_id>_forward_verdict.md
public/data/strategy_lab/<family_id>/paper_state.json
docs/strategy/TRIALS_LEDGER.md
```

## 18. Invalid Output

Any of these phrases or behaviors invalidate the report:

- "Tuned parameters until performance improved."
- "Sharpe is high, therefore usable."
- "It did not pass, but I feel it has potential."
- "Random is similar, but absolute return is good."
- "We can add the negative control later."
- "Let's deploy and see."
- "Historical OOS proves it."
- "The regime was found after the run but is intuitive."
- "A different random seed looks better."
- "Sample is small, therefore it is dead" without power interpretation.

## 19. Closing Checklist

Before finalizing any report, answer:

1. Is this only a historical paper ticket, or has it passed forward paper?
2. Did it pass the `N_trials`-adjusted bar?
3. Did it beat same-gross benchmarks?
4. Did it beat random/placebo?
5. Did the mechanism side prediction hold?
6. Is the regime rule real-time observable?
7. Is the result dependent on survivorship bias?
8. Is any feature using future data?
9. Is it just low gross / low volatility masquerading as edge?
10. Would CORE research do this better?
11. If all candidates die, is the gate calibrated or reflexively killing?

The last question matters. A validator that only kills everything is not a
scientific machine; it is an uncalibrated filter.

