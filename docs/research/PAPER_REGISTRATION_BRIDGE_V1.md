# Paper Registration Bridge V1

Status: `DELIVERED_UNWIRED` / `OFFLINE_ONLY`

This bridge closes one narrow gap in Research Closed Loop V1: an already
committed U4 `SELECT` and an already sealed prospective research case can be
registered as one pending order in the existing Model Paper Fund. Registration
is never automatic and never grants real trading authority.

## Boundary

The bridge may:

1. read the current committed U4 decision for the case ticker;
2. validate the sealed research case, thesis/timing gates, valuation and SMC
   references through the existing research-cycle contract;
3. size a paper-only order through `model_paper_fund.register_order`;
4. freeze the complete plan, settled portfolio marks and projected records;
5. require verbatim human authorization containing the full plan hash;
6. append one R-015 intent, converge the two paper projections, and append one
   R-015 commit;
7. let the ordinary daily paper path simulate later fills and exits with the
   existing realistic execution model.

The bridge may not select a security, author research evidence, call a broker,
submit a real order, create an order from the nightly scheduler, or grant
trade/production/formal-blocking authority.

## Transaction

```text
settled marks + current U4 SELECT + sealed prospective case + fund snapshot
  -> exact deterministic plan
  -> verbatim human approval containing the full plan_hash
  -> R-015 paper_registration_intent (complete replayable plan + approval)
  -> orders.json projection
  -> decision_log.json projection
  -> exact post-state verification
  -> R-015 paper_registration_commit + immutable receipt
```

The write path takes the same `nightly.lock` as the production runner. A held
lock refuses immediately. The R-015 typed writer snapshots the payload and
recomputes the intent from the current U4 ledger, closure bundle, case, settled
marks and Model Paper Fund state before append.

The projection is idempotent:

- exact pre-state converges to the frozen post-state;
- an already written order or decision must exactly match its post-state hash;
- a third state is refused;
- a crash after intent, order, decision or commit can be retried without a
  duplicate order, decision, intent or commit;
- a committed retry must present the original plan and original approval.

The daily Model Paper Fund CLI verifies all committed registration projections
and refuses to advance while an intent is pending or immutable provenance has
changed. Fill/exit fields may advance after commit; registration provenance may
not.

## Execution Semantics

The registered order starts as `pending`. It is not an executed trade. The
existing paper engine later applies its settled-bar rules, including no fill on
the registration day, price intersection, adverse gap/slippage treatment,
volume participation, fees, stop/target order and corporate-action freezes.

Every V1 bridge order remains:

- `no_trade_flag: true`
- `trade_authority: false`
- `production_authority: false`
- `claim_allowed: false`
- `sample_eligible: false`
- `method_claim_sample_eligible: false`
- `portfolio_promotion_eligible: false`

The approval artifact records `claimed_approver: Junyan` and
`identity_verification: UNAVAILABLE`. It preserves the authorization evidence;
it does not pretend that local text proves identity.

## Operating Sequence

1. Seal same-session settled marks for every currently filled position.
2. Generate the plan from the current committed U4 `SELECT`, sealed case and
   current Model Paper Fund snapshot.
3. Review the complete plan. Produce a separate approval artifact whose
   verbatim text contains the full `plan_hash` and explicitly says paper or
   simulated registration.
4. Apply under `nightly.lock`.
5. Run `verify` before any daily advancement.

No step in this sequence is wired into the nightly DAG in V1. Production use
requires a separate deployment review and explicit approval.

## Honest Residual Boundary

This bridge transactionally protects registration only. The older daily paper
advance still saves fund, orders, decision log and NAV as separate atomic files;
it is not yet one cross-file WAL transaction. The registration preflight does
not claim to solve a crash halfway through a later daily fill/NAV settlement.

The first semiconductor workflow-debug cycles remain method-claim-ineligible.
No win-rate, alpha, profitability or method-validity statement is permitted
before at least 30 independent, de-clustered closed samples and cross-industry
replication under the existing research constitution.

不是买卖指令；研究信号，human executes.
