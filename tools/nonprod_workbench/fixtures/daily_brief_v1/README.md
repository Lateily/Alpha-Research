# WB-01 daily brief synthetic fixture

This directory is a deterministic, fully synthetic `WORKFLOW_DEBUG` bundle.
Every instrument ends in `.TEST`; it contains no licensed market data, real
portfolio, production order, account, credential or human approval.

The five source JSON files preserve the exact bytes supplied in
`workbench_brief_fixture_20260922.zip` (outer SHA256
`67d09ccdc74919e9ae19bc4a25b3789306c935170d677bc3ea4522fe04e6b201`).
Jason independently verified the outer ZIP, archive CRC and original internal
`SHA256SUMS` before importing the files. `brief_input.json` is the frozen WB-01
envelope added by this task; it binds each source date, cutoff, quality and
SHA256.

Run:

```bash
python3 scripts/llm/workbench_daily_brief.py \
  --bundle tools/nonprod_workbench/fixtures/daily_brief_v1
```

An accepted receipt is evidence that the synthetic bundle satisfies this
contract. It is not production publication, research approval or trading
authority. Explicit `DATA_BLOCKED` and `PARTIAL` sources remain visible.
`acceptance_receipt.json` is the deterministic output for the committed fixture;
the test suite regenerates it and requires byte-equivalent JSON content.

`negative_cases.json` names the required adversarial cases. The tests create
each case in a temporary copy; they never mutate this canonical fixture.
