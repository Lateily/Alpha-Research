# Workbench Daily Brief Contract V1

Status: `DRAFT_NONPRODUCTION / WORKFLOW_DEBUG / WB-01`

Owner: Jason. First consumer review: Better. Runtime consumer: Simon. Final
merge and deployment authority: Junyan.

This contract freezes the first Portfolio × Market daily-brief exchange format.
It is a data and acceptance contract, not a scheduler, UI, research conclusion,
human approval or production publication mechanism.

## 1. The four clocks and identities are separate

| Field | Meaning | Never substitute with |
| --- | --- | --- |
| `latest_attempt` | most recent execution attempt, including failure | last green result |
| `last_successful_publication` | most recent successfully published bundle | latest attempt |
| `displayed_run_id` | source bundle currently rendered | an implicit “today” |
| each source `source_date` / `data_cutoff` | date and time covered by that source | page generation time |

The accepted fixture displays the same run that was published. A later failed
attempt may coexist with that older publication, but the receipt then sets
`displayed_is_latest_attempt=false` and retains the failed status. It must not
label the old publication as the latest successful attempt.

## 2. Frozen input

The authoritative machine contract is
`workbench_daily_brief_input.v1.schema.json`. The envelope requires:

- one explicit `run_id` and `target_trade_date`;
- generation time, data cutoff and code/fixture version;
- `WORKFLOW_DEBUG`, synthetic origin and false production/trade authority;
- separate latest-attempt, publication and displayed-run records;
- exactly one `MARKET`, `PORTFOLIO`, `ORDERS`, `MACRO` and `FUNNEL` source;
- each source path, date, cutoff, SHA256 and quality state;
- evidence references that resolve to fields inside frozen sources;
- explicit `NOT_ESTABLISHED` market-to-portfolio causal attribution.

The five source payloads must bind the same run and trade date. Source bytes are
read as regular files without following symlinks, hashed before parsing and
rejected on missing files, duplicate JSON keys, non-finite numbers, path drift,
secret-like content or identity mismatch.

## 3. Deterministic arithmetic

Portfolio acceptance recomputes, rather than trusts:

```text
position market value = shares × close
NAV = cash + sum(position market value)
NAV change = current NAV - previous NAV
NAV change % = NAV change / previous NAV × 100
```

Filled paper orders recompute cash effect and position change. An unfilled order
must have zero shares, fee and cash effect and a null fill price. Aggregated
order cash and share changes must reconcile to the two portfolio snapshots.

An existing orders source with `orders=[]` is valid only when it is explicitly
marked `NO_ACTIVITY` and the portfolio shows no order-driven cash or share
change. A missing or unbound orders file is `SPEC_BLOCKED`; it is never treated
as a quiet day.

## 4. Missing-data semantics

`DATA_BLOCKED` and `PARTIAL` are valid observations, not zeros and not contract
success for research quality. The canonical fixture is structurally accepted
while its research-quality result remains `PARTIAL` because Macro is
`DATA_BLOCKED` and Funnel is `PARTIAL`.

The receipt always includes `missing_values_zero_filled=false`. Market and
portfolio movement may be displayed together, but causal attribution remains
`NOT_ESTABLISHED` unless a later separately reviewed contract supplies that
evidence.

## 5. Output and receipt

`workbench_daily_brief_output.v1.schema.json` describes the deterministic
acceptance receipt:

- `ACCEPTED` includes traced run state, source rows, recomputed arithmetic,
  explicit quality gaps and evidence references;
- `SPEC_BLOCKED` contains one stable error code and no partial result;
- `formal_authority` is always false;
- `receipt_hash` binds the complete receipt body without wall-clock fields.

The receipt hash is stable when input bytes and code are unchanged. It is not a
human-review receipt and cannot approve research, U4, paper, publication or a
production write.

## 6. Fixture provenance

The source package supplied for WB-01 had outer ZIP SHA256:

```text
67d09ccdc74919e9ae19bc4a25b3789306c935170d677bc3ea4522fe04e6b201
```

Before import, Jason verified the outer hash, archive CRC, safe paths, absence
of symlinks and every original internal hash. The five committed source JSON
files preserve the supplied bytes and hashes. WB-01 adds the versioned envelope,
negative-case catalog and local checksum manifest. All instruments are `.TEST`.

## 7. Acceptance and handoff

```bash
python3 tests/test_workbench_daily_brief.py
python3 scripts/llm/workbench_daily_brief.py \
  --bundle tools/nonprod_workbench/fixtures/daily_brief_v1
python3 scripts/llm/ai_os/cli.py compile \
  --input scripts/llm/fixtures/wb01_daily_brief_contract.task.json
python3 scripts/governance_mutation_gate.py
python3 tests/test_no_network_guard.py
git diff --check
```

Simon may build isolated execution and durable receipts around this contract,
but must not redefine its fields. Better may build the page from this fixture,
but must not infer missing values or collapse the four identities above. Any
interface change returns to this Issue/PR and receives cross-review before
runtime or UI changes.

No model, external network, production engine, ledger or real market/account
data is used by WB-01. This document contains no trading instruction.
