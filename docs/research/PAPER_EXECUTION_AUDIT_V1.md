# Paper Execution Audit v1

Status: `DELIVERED_OFFLINE / UNVERIFIED_SIMULATION`

This slice audits the inherited paper engine. It does not improve that engine,
rewrite its ledgers, or make historical results valid after the fact. Engine
hardening is a separate PR-B and requires separate Junyan approval.

## What The Receipt Proves

`paper_execution_audit.py` runs deterministic behavior probes against the
engine imported from the audited checkout. It does not infer capabilities from
source text or accept caller-authored pass/fail labels. The receipt binds:

- the exact bytes of `paper_portfolio.py` and `model_paper_fund.py`;
- explicit orders, fund, NAV, and paper-signal snapshot hashes;
- every probe's observed behavior;
- a per-record audit projection for every order and paper signal;
- `claim_allowed=false`, `method_sample_eligible=false`,
  `production_authority=false`, and `no_trade_flag=true`.

Input ledger files are read once and never written. A requested receipt output
is create-only and refuses a byte-different collision.

## Current Main Finding

The committed snapshots contain 5 model-fund orders and 146 paper signals.
Against current main, 13 behavior probes produce 5 PASS and 8 FAIL:

| Capability | Result |
|---|---|
| registration-day cutoff | PASS |
| A-share sell T+1 | PASS |
| 100-share round lot | PASS |
| suspension availability | FAIL |
| one-price limit availability | FAIL |
| adverse entry/stop gaps | PASS |
| later same-bar stop/target conservatism | PASS |
| explicit costs and slippage | FAIL |
| pending expiry/cancel/partial lifecycle | FAIL |
| settled-volume participation bound | FAIL |
| raw corporate-action-consistent execution basis | FAIL |
| explicitly settled bars only | FAIL |
| cash/order/position/NAV reconciliation | FAIL |

These are observations of current behavior, not a repair plan hidden inside an
audit PR. Later engine hardening may change the matrix prospectively, but cannot
retroactively validate fills that were produced without the required execution
facts.

## Historical Status

All existing simulated outcomes remain `UNVERIFIED_SIMULATION` in the receipt.
The projection does not overwrite `orders.json`, `paper_signal_log.json`, NAV,
P&L, or any event ledger. Paper-signal returns remain useful as settled-bar
outcome observations, but they are not executable-fill evidence.

Historical rows can become valid evidence only through a separately approved
policy that binds the original order to contemporaneous raw execution facts.
Simply fixing the current engine is not enough.

## Offline Invocation

Every input path is mandatory. There is no default production path.

```bash
AR_OFFLINE=1 python3 experiments/execution_tracker/paper_execution_audit.py \
  --repo-root "$PWD" \
  --orders experiments/execution_tracker/model_fund/orders.json \
  --fund experiments/execution_tracker/model_fund/fund.json \
  --nav-history experiments/execution_tracker/model_fund/nav_history.json \
  --paper-signals experiments/execution_tracker/paper_signal_log.json \
  --audited-at 2026-08-22T09:00:00+08:00
```

Omit `--output-dir` for stdout-only inspection. When an explicit output
directory is supplied, the audit writes one hash-addressed receipt and never
overwrites it.

## Non-Claims

- No historical P&L or NAV was changed.
- No engine behavior was fixed.
- No production or nightly path was read by default or written.
- No paper result enters the 30-sample method claim set.
- No real order or trading authority is created.

不是买卖指令；研究信号，human executes.
