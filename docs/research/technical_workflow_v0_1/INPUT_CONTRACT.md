# Technical Input Contract v0.1

This is the Task 2 engineering contract for offline `WORKFLOW_DEBUG` inspection.
The approved method is the byte-frozen `TECHNICAL_WORKFLOW_V0_1_REVIEW.md`, SHA256
`b4bf29fddbebb94298e8d58b948766697b915611142e0c6ee933b35554c8e9f7`.
No profile parameter, old U4/manual-SMC rule, paper rule or trading rule changes.
No technical calculation, provider, registration, CLI or deployment is delivered
by Task 2. Task 1's fixture README describes that earlier stage; this document
supersedes its NOT_IMPLEMENTED statements and documents the binding delta below.

## API And Trust

`load_registered_pack(registry_path, pack_id, evidence_roots)` and
`validate_pack(pack_root, trusted_binding, evidence_roots, profile)` return exactly:

```text
schema request source_manifest inputs bindings quality status reason_codes authority
```

The schema is `technical-pack-validation.v1`. All authority remains fixed:
`sample_purpose=WORKFLOW_DEBUG`, `claim_allowed=false`, `no_trade_flag=true`, and
production/U4/paper-registration/trade authority false. Validation is not SELECT,
human authentication, manual SMC PASS, registration readiness or a trading signal.

The operator owns a registry outside every pack/evidence tree. The exact registry
fields are `schema_version/packs/evidence_roots`; version `technical-registry.v1`.
Each pack binding has exactly
`pack_root/request_hash/source_manifest_hash/profile_id/profile_hash/mode`.
Request and manifest hashes pin file bytes, not re-encoded JSON. `profile_hash`
pins the approved canonical profile. Passed evidence-root aliases/paths must equal
operator configuration. A browser or package cannot supply trusted bindings,
change roots, register itself or replace an old pack by resealing it.
Operator provenance/permissions remain a deployment responsibility. Human names
alone do not authenticate a source; the reopened receipt is meaningful only as
part of this separately pinned operator-provisioned evidence chain.

Only the six fixed Task 1 role files, request, manifest and SHA256SUMS are allowed.
All Task 1 no-follow, ancestor, hardlink, duplicate-key, exact-field, finite-number,
tick and bounds guards remain. Evidence refs are exact objects:
`root_alias/path/sha256/pointer`. SHA256 is 64 lowercase hex of original bytes;
paths are relative, nonlinked and nonescaping. Pointers are RFC6901-style JSON
locators; a bad locator is refused, not treated as absence.

Resource limits are engineering limits: 2 MiB/file, 16 MiB aggregate pack/evidence,
2,000 rows/calendar dates/ledger records, 64 distinct evidence files, 32 JSON
nesting levels, 100 registry packs, 16 root aliases, 80 decimal-text characters,
100 identifier characters, 512 path/pointer characters, 4,096 text characters,
and 10 package directory entries. They do not tune the approved strategy.

## Exact Package Shapes

Every field below is required, including nullable fields. Unknown nested fields
and duplicate keys are refused. The executable field table is `SCHEMAS` in
`technical_contract.py`; there is no permissive alternate schema.

| Object | Exact fields |
| --- | --- |
| request (`technical-request.v1`) | schema_version, workflow_version, rule_profile_hash, mode, pack_id, ts_code, industry_key, as_of, data_cutoff, generated_at, window_id, exposure_status, source_manifest_hash |
| manifest (`technical-source-manifest.v1`) | schema_version, sources |
| source | role, path, origin, sha256, identity, evidence_grade, published_at, available_at, captured_at, raw_unit, normalized_unit, licensing, missing_reason |
| identity | ts_code, industry_key |
| unit | price, volume, amount |
| licensing | license_id, display_scope |
| bars (`technical-bars.v1`) | schema_version, timeframe, rows |
| bar | ts_code, trade_date, bar_close_at, available_at, open, high, low, close, volume, amount, price_basis, currency |
| calendar (`technical-calendar.v1`) | schema_version, version, source_hash, coverage, days |
| coverage | start, end |
| calendar day | trade_date, is_open, close_at, suspensions |
| suspension | ts_code, status, source_refs |
| actions (`technical-actions.v1`) | schema_version, ts_code, price_basis, coverage, verified, actions |
| action | action_id, effective_date, available_at, kind, verified, source_refs |
| flow (`technical-flow.v1`) | schema_version, ts_code, rows |
| flow row | trade_date, available_at, settlement_status, main_net_flow, main_net_flow_missing_reason, currency |
| context (`technical-sector-context.v1`) | schema_version, context_id, industry_key, as_of, data_cutoff, source_refs, market_state, sector_state, rationale, counter_evidence, authored_by, authored_at, review_status, reviewed_by, reviewed_at, invalidation_conditions, supersedes, context_hash, review_receipt, industry_mapping, is_human_judgment, automated_decision, claim_allowed |
| research binding (`technical-research-binding.v1`) | schema_version, ts_code, industry_key, packet, decision, packet_hash, decision_row_hash, cohort_id, causal_cluster_id, method_version, research_case, thesis, valuation, red_flags, u4_sources |
| thesis/valuation | source_ref, missing_reason |
| red flags | ts_code, as_of, available_at, coverage_start, coverage_end, verdict, reasons, source_refs |

The only package-field addition to Task 1 is nullable `research_binding.u4_sources`:
a hash-bound external descriptor is necessary to locate original U2/U3 and health
evidence without trusting paths embedded in U4 JSON. No other package field is
added. The existing U4 semantic hash fields now accept the exact legacy spellings
`<64 hex>` or `sha256:<64 hex>`; comparison to the original is exact, not prefix
normalization. Byte-hash fields remain bare 64 hex. New external record forms are
specified below, not new U4 decision formats.

## Daily Coverage And PIT

All dates are real `YYYYMMDD` strings; all timestamps carry explicit timezone.
Market dates use `Asia/Shanghai`, independent of host timezone. `as_of` cannot
exceed `data_cutoff`. Publication and availability must be <= cutoff. Capture can
occur later during historical freezing, but cannot substitute for publication or
availability. Source order is publication <= availability <= capture.

Only `1d` bars are accepted; other timeframes are `REFUSED` with
`UNSUPPORTED_TIMEFRAME`. Session/killzone or any unknown nested field is refused.
Each company-bound bar must close and be available by cutoff, have availability
not before close, match the calendar's exact close instant and Shanghai date,
and represent actual positive-volume trading. Prices retain original decimal
text, use Decimal, and meet the unchanged 0.01 CNY tick. No float conversion of
technical prices occurs.

The calendar is itself a frozen manifest-bound original. `source_hash` is the
bare SHA256 of canonical calendar JSON excluding only `source_hash`; it is a
semantic projection hash, distinct from the manifest's file-byte hash. Explicit
days, including closed days, cover every civil date from the first supplied bar
through request as-of, within declared coverage. Duplicate/unordered dates are
refused. A calendar hole, missing open-day bar or unknown suspension blocks
structure. No interpolation or old bar fill is performed.

A suspension's source refs resolve to exact records with fields
`trade_date/ts_code/status`; the values must match that day's company and
`status=VERIFIED`. All cited records must exist and agree. A suspended day has no
ordinary bar, and is excluded from the last two traded dates. Other-company
suspensions cannot explain a missing company bar.

Action coverage must be verified over the full input-to-as-of interval. Only raw
bars with raw action basis are usable. Every action effective inside that interval
blocks calculation, even if verified: adjusted action mappings are not implemented
in this profile. Mixed raw/adjusted bars remain blocked. Action refs are reopened,
but their labels never override this conservative action-break guard.

Bars must already use shares and CNY with raw/normalized units agreeing. Conversion
proofs are not part of this slice; other units remain `UNIT_CONVERSION_UNVERIFIED`,
not guessed or silently converted. At least the approved 60 actual traded daily
bars are needed. Synthetic calendars in tests are explicitly invented, not actual
exchange calendars or a clean research sample.

Settled flow uses exactly the calendar-derived last two traded dates, not the last
two available rows. Duplicate dates are refused. Missing/null, pending/unknown or
future-available values yield null sum plus a reason, never zero or an older pair.
Two settled CNY values are summed with Decimal; positive is `CONFIRMED`, zero or
negative is `NOT_CONFIRMED`. Structural events are not erased by flow weakness.
Date derivation depends on a present, hash-verified calendar with complete civil
date coverage, verified suspensions, and manifest availability at cutoff. Any
calendar reason blocks dependent flow: nested status `DATA_BLOCKED`,
`trade_dates=[]`, `last_two_sum=null`, and
`missing_reason=FLOW_CALENDAR_DEPENDENCY_BLOCKED`. `dependency_reason_codes`
contains the calendar reasons, which also propagate to the flow role along with
the dependency reason. This does not substitute an older pair, and a late calendar
is not treated as a late flow publication. Flow identity/duplicate-date refusals
still apply before dependency handling.

## Original U4 Binding

`packet` points to the actual original packet object. `decision` points to
`/<zero-based record index>/payload` in the frozen original R-015 ledger, which
may be canonical JSONL or an array preserving every original outer record.
Array export is an engineering transport, not a replacement SELECT contract.
Every record retains the exact original `seq/ts/kind/id/payload/prev/hash` fields.
The complete bounded chain starts at genesis; no filtered rows or invented
singleton SELECT objects are accepted. Original record hashing, chronology,
unique IDs and committed intent/event/closure replay are verified.

`u4_sources` resolves to this exact engineering descriptor:

```text
schema_version=technical-u4-sources.v1
files: map of relative logical original reference -> evidence_ref
bundle_ref: logical bundle directory
feature_health_ref: logical file or null
funnel_health_ref: logical file or null
diagnostic_ref: logical file or null
cyclical_flags_ref: logical file or null
```

Every `files` reference uses an empty pointer and pins an entire original file.
For review packets, this includes bundle manifest and all manifest artifacts;
health/diagnostic refs may be null. For pre-decision packets, feature health,
funnel health and diagnostic are mandatory; cyclical flags may be absent exactly
as the existing validator allows. Logical keys match the originals' reference
names, not machine absolute paths. All files are reopened with the bounded reader.

Explicit schema discrimination preserves both old contracts:

- `ar.u4_review_packet` uses the existing original-bundle projection validator
  on a dedicated temporary copy, and pure `_replay_records` for committed state.
- `ar.u4_pre_decision_packet.v0` uses existing `validate_packet` with a captured
  evidence adapter to rederive source-bound rows and health/diagnostic hashes.
  It is discussion material, not a SELECT ledger contract; a decision attached to
  it cannot manufacture SELECT authority.

The public ledger reader creates `.lock`; it is never invoked on originals (or
used here at all). No append writer, SQLite, provider or old-module edit is used.
Copies contain only captured source bytes; original inode/mtime/hash and file
inventory remain unchanged. Snapshot-boundary race checks belong to Task 3.

Company, industry (`candidate.industry_code` for ledger events), cohort, cluster,
method, packet and decision-row semantic hashes must exactly match reopened
originals, request and binding. Case drafts cannot override the U4 industry.
Prospective mode requires `UNEXPOSED` and a bound committed SELECT; missing,
REJECT/DEFER/NO_TRADE/DATA_BLOCKED is not SELECT. Genuine rejected decisions are
legal historical evidence, not malformed events. Registration and packet times
must be <= cutoff; a later closure cannot backdate authority.

Current builders deliberately emit `UNAVAILABLE` cohort and may also emit an
unavailable cluster. These values remain visible, with `U4_COHORT_UNBOUND` and/or
`U4_CLUSTER_UNBOUND`, and block promotion. No clean synthetic prospective
`VALIDATED` result can be manufactured from those originals by filling identity.
Historical no-SELECT remains legal as `HISTORICAL_NO_U4_AUTHORITY`, never prospective
approval. Existing historical SELECT evidence likewise grants no write authority.

## Red Flags And Optional Research

Red-flag source refs resolve to an operator-provisioned descriptor of existing
checks, not a duplicated verdict or a new classifier. The only supported external
descriptor is `technical-red-flag-sources.v1`, with these exact fields:
`schema_version/ts_code/industry_key/as_of/published_at/available_at/e1_ref/u3_ref`.
Both original refs have the ordinary exact `evidence_ref` form. They reopen whole
original JSON objects (empty pointer): E1 `ar.e1_event_layer` and U3 battery in the
existing `target_trade_date` or `data.checked_at` / `data.results` form. All reads
remain bounded, no-follow and byte-hash checked. No ledger reader, classifier
rewrite, provider or writer is invoked. A naked copied CLEAR extraction, missing
original, unsupported adapter, absent company row, or unsupported coverage is
UNKNOWN with `RED_FLAG_COVERAGE_UNKNOWN`; its own hash does not prove coverage.

Descriptor company/industry match the request, its as-of is the Shanghai request
date, and publication/availability are ordered and <= cutoff. E1 is checked by
the existing `validate_event_layer`; its as-of and generation timestamp must be
current/available at cutoff, and its company row must match industry. U3 is
checked by the existing `validate_battery_evidence`, `_battery_rows`, and
`_u3_fundamental_red_flag_active`, including the same-day battery and six-dimension
COMPLETE proof. These are pure original validators, not lock-creating readers.
If present, U3's original `generated_at` must be <= cutoff and a company's
`checked_at` must match the requested date; a descriptor cannot backdate them.

Current original E1 `RED_FLAG` or U3 fundamental `RED_FLAG` derives ACTIVE,
even when the package says CLEAR or the other check is missing. It adds an
`E1_ACTIVE` or `U3_ACTIVE` nested reason and blocks promotion. CLEAR requires both
original negative proofs: E1 `NO_RED_FLAG_FOUND`, complete income with explicit
empty deadline/source-blocked gaps, supported forecast/express coverage, and a
complete successful endpoint/period call matrix without errors/truncation; U3
COMPLETE with a nonblocked fundamental `PASS`. Missing dimensions or a PARTIAL
battery never become clean by absence of an ACTIVE flag. Package as-of/coverage
must include the current date and availability must be <= cutoff for CLEAR.

`quality.red_flags.coverage` retains the original E1 coverage and U3 completeness.
CLEAR means only no active flag in these existing locked checks, not research
approval or exhaustive E1 coverage: E1's original formal-announcement dimension
remains explicitly `DATA_BLOCKED`, exactly as its producer defines it. No new
trading threshold or verdict oracle is introduced. A package ACTIVE claim also
retains a conservative promotion block even if original coverage is UNKNOWN.
Neither technical structure nor context cancels ACTIVE. Historical no-SELECT and
unavailable cohort semantics are unchanged and confer no authority.

Missing thesis/valuation each have `quality.missing_fields.<name>` with null value
and an explicit reason. They do not block standalone structure observation, but
promotion stays blocked and registration is always `NOT_AUTHORIZED`. Present
optional evidence resolves to an exact `technical-research-evidence.v1` record:
`schema_version/kind/ts_code/industry_key/published_at/available_at/content`.
Kind is `THESIS` or `VALUATION` matching the slot; company/industry must match,
both timestamps must be <= cutoff, and content is nonempty text. This is a sealed
engineering evidence form, not a new thesis/valuation method or formal case.
`research_case` remains a reopened reference, not authorization or an industry
override; this slice neither seals nor converts a case.

## Human Context Evidence

These external forms are engineering receipts/extractions, not authentication
protocols or automated sector decisions. All fields are exact and all refs pinned
through the separately provisioned pack/registry chain.

| Original record | Exact fields |
| --- | --- |
| context source (`technical-context-source.v1`) | schema_version, industry_key, as_of, published_at, available_at, content |
| mapping (`technical-industry-mapping.v1`) | schema_version, ts_code, industry_key, coverage_start, coverage_end, published_at, available_at |
| review receipt (`technical-context-review.v1`) | schema_version, context_id, context_hash, review_status, reviewed_by, reviewed_at |

`context_hash` is bare SHA256 of canonical context excluding only `context_hash`
and `review_receipt`. The latter is excluded to avoid a hash cycle; source refs,
mapping ref, authored/reviewed fields, judgment and supersedes remain in the hash.
Reviewed/disputed material must match this hash. PENDING drafts remain unconfirmed
and their claimed hash is not exported as a verified binding.

Source context dates must be the request's Shanghai as-of date; publication and
availability are <= cutoff and correctly ordered. Mapping must match the exact
company/industry, cover that date and be available by cutoff. A receipt matches
context ID/hash/review status/reviewer/time; review cannot predate authoring.
A receipt after cutoff is explicitly blocked, even if the package backdates its
review fields. It cannot make the old context confirmed. Hash/identity/receipt
contradictions are refused; absent or stale evidence is blocked.

Only source-complete, mapped, receipt-bound `REVIEWED` context with market not
RISK_OFF/UNKNOWN and sector CONFIRMED becomes `CONFIRMED`. Missing, PENDING,
DISPUTED, ADVERSE, RISK_OFF, UNKNOWN and NOT_CONFIRMED stay explicit. Late source
manifests cannot display confirmed context/flow despite matching internal claims.
Updates are new versions using supersedes; no old card or review is rewritten.

## Result Interpretation And Handoff

`REFUSED` has empty inputs/bindings, null request/manifest, both input statuses
REFUSED, and no calculable content. Consumers must never calculate refused input.
`DATA_BLOCKED` may retain the six roles (null with reasons for missing roles) and
verified source bytes/identities, but is not globally ready. Its
`structural_input_status=STRUCTURALLY_VALID` permits only standalone observation;
`DATA_BLOCKED` there forbids structure calculation. Promotion is independently
DATA_BLOCKED or VALIDATED. `VALIDATED` requires neither structural nor promotion
blocks; it still grants no authority. Current upstream unbound U4 identities mean
the real existing SELECT fixtures are intentionally DATA_BLOCKED, not VALIDATED.

Per-role `status` retains Task 1 syntax/byte status; `semantic_status` and reasons
describe semantic readiness. `semantic_coverage=IMPLEMENTED` and
`semantic_bindings_status=EVALUATED` do not mean every source is complete.
Bindings distinguish request/manifest/source/evidence byte hashes, approved
profile semantic hash and original U4/context semantic hashes. Quality separately
reports red flags, flow, context, missing research and registration readiness.
No deterministic payload contains host paths, runtime clocks or random IDs.

Focused command: `AR_OFFLINE=1 python3 tests/test_technical_contract.py`.
All fixtures are synthetic and temporary. Real-source acceptance remains pending.
Task 3 owns inspection CLI, failure receipts, snapshots, output/race guards,
CI/no-network registrations, full mutation gate and exact-head CI. This document
does not claim those gates passed or authorize upstream identity amendments.
