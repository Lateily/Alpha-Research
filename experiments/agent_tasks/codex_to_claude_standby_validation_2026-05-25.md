# Codex Standby Validation -> Claude

Timestamp: `2026-05-25T10:56:09Z`
Repo HEAD: `c0f9ddf`

## Verdict

T3 Codex watcher is alive and standby. I independently re-verified the three
P2 modules that were landed by T1/Claude:

- `scripts/screen_universe.py`
- `scripts/risk_monitor.py`
- `scripts/portfolio_allocator.py`

Mechanical validation is PASS. Investment validity is NOT established.

## Validation Run

Commands run:

```bash
python3 -m py_compile scripts/screen_universe.py scripts/risk_monitor.py scripts/portfolio_allocator.py
python3 scripts/risk_monitor.py --selftest
python3 scripts/portfolio_allocator.py --selftest
python3 -m json.tool public/data/screen_candidates.json
python3 scripts/screen_universe.py --output /private/tmp/ar-platform-screen_candidates_verify.json
cmp -s public/data/screen_candidates.json /private/tmp/ar-platform-screen_candidates_verify.json
python3 scripts/portfolio_allocator.py --candidates public/data/screen_candidates.json
```

Observed results:

- `py_compile`: PASS.
- `risk_monitor --selftest`: PASS.
- `portfolio_allocator --selftest`: PASS.
- `screen_candidates.json`: valid JSON.
- Screener deterministic rerun to temp output: PASS (`cmp` exit 0).
- Candidate schema spot-check: PASS, 50 candidates, contiguous ranks 1..50,
  descending composite.
- Allocator consumes current candidates: PASS, emits 15 SATELLITE positions,
  0 CORE positions without thesis overlay.

## Blocking Caveats For Claude

1. P1 data foundation is still not locally validated. Prior Codex probe failed
   before Tushare response because the sandbox could not resolve
   `api.waditu.com`. Real proof still needs GHA/networked execution.

2. Current `public/data/universe_a.json` makes the screener output a plumbing
   demo, not an investable list:
   - `quality_non_null=5805`
   - `unique_quality=1`
   - only value/momentum/size/low-vol move the rank today
   - raw `roe`, `gross_margin`, `revenue_growth`, `profit_growth` are all
     zero-populated in the local snapshot

3. `screen_universe.py` does not yet satisfy the full v1 hard-filter spec:
   - no `listed < 12 months` filter because `list_date` is absent
   - no true 20-day ADV filter; current liquidity proxy is one-day
     `price * volume`
   - no sector-neutral scoring because `industry/sector` is absent
   - no earnings-event or limit-up entry filters; those belong downstream but
     must be wired before any real backtest

4. Observability contract is only partially met for the screener. The output
   has top candidates plus an excluded sample and reason counts, but not a full
   per-stock decision log for every included/excluded universe member. The spec
   requires every decision to be locatable.

## Validation Labels

Causal logic is valid for mechanical P2 plumbing because the modules are pure
or controlled functions over local JSON/fixtures, selftests exercise core
branching, and screener/allocator outputs are deterministic.

Specific numbers are mixed:

- Command outcomes, counts, and schema observations above are validated against
  this local run.
- Factor weights, risk thresholds, allocation caps, stop distances, and current
  candidate rankings are unvalidated intuitions until the 20-year PIT,
  survivorship-safe backtest runs on real data.

## Recommended Next Step

Claude should treat the current P2 modules as landed scaffolding, not strategy
truth. The next highest-leverage step is to run/verify the P1 GHA Tushare
backfill, then patch the screener to consume PIT financials, listed dates,
industry fields, and a full per-stock audit log before rebuilding any backtest.
