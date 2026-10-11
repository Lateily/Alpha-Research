# Synthetic technical input contract fixtures and operator notes

Task 1 only. `tests/test_technical_contract.py` builds all packages and operator
registries in temporary directories, using invented rows and invented evidence.
There is no real market data here, no clean prospective sample, and no authority.
No fixture is installed into runtime, production, a case, U4, or paper state.

## Scope and readiness

The three public interfaces are `load_profile(profile_id)`,
`load_registered_pack(registry_path, pack_id, evidence_roots)` and
`validate_pack(pack_root, trusted_binding, evidence_roots, profile)`.
The validation result has exactly
`schema/request/source_manifest/inputs/bindings/quality/status/reason_codes/authority`.

Task 1 NEVER returns `VALIDATED`. Structurally accepted packages return
`DATA_BLOCKED`, `SEMANTIC_VALIDATION_NOT_IMPLEMENTED`,
`quality.semantic_coverage=NOT_IMPLEMENTED`,
`quality.promotion_input_status=NOT_EVALUATED`, and
`bindings.semantic_bindings_status=NOT_EVALUATED`. Role statuses describe syntax
and byte integrity only. They do not authenticate identities, human review,
cutoff eligibility, settled status, red-flag verdicts, or calendar/action coverage.
Malformed/linked/tampered inputs return `REFUSED` with empty `inputs` and
`bindings`; they must never reach a calculation engine.
Missing context may leave structurally valid bars observable, but NEVER promotes
a proposal. Missing roles are null with per-role reasons; null flow has
`main_net_flow_missing_reason`. Missing thesis/valuation carry `missing_reason`.
Nullable U4 references are merely syntax slots at this stage; Task 2 must derive
their historical/prospective authority and explicit absence reasons from originals.

No Task 2 semantic routines, no calculation, no Task 3 CLI/snapshot/output writer,
and no mutation-gate/CI registration are implemented in Task 1.

## Operator trust boundary

The registry is a separately provisioned, operator-controlled JSON file, outside
EVERY registered pack and configured evidence tree. Its deployment permissions
and provenance are the operator's responsibility; bytes cannot authenticate an
operator. Browser/package fields must NEVER be passed as trusted configuration.
Use dedicated nonproduction frozen roots, not production installations.

Registry schema version is `technical-registry.v1` with exact fields:

- `schema_version`
- `packs`: map from identifier `pack_id` to a trusted binding
- `evidence_roots`: map from alias to operator-configured absolute directory

Each trusted binding has exactly
`pack_root/request_hash/source_manifest_hash/profile_id/profile_hash/mode`.
`pack_root` is the absolute, nonlinked pack directory. `request_hash` and
`source_manifest_hash` pin original FILE BYTES; `profile_hash` pins separately
derived canonical PROFILE SEMANTICS. `mode` is `HISTORICAL_REPLAY` or
`PROSPECTIVE_RESEARCH`. The request must match the registry pack ID, pinned mode
and approved profile. There is NO registration or write API. Rehashing all
package files cannot update the operator binding.

The passed `evidence_roots` must exactly match the registry's alias/path map.
Evidence aliases are not URLs and cannot be overridden from an input. Evidence
roots cannot overlap the selected pack. References reopen bytes with the same
bounded no-follow reader. JSON pointers have syntactic validation only; Task 2
must validate the referenced content and exact U4 rows using pure routines or
isolated copies. Old public U4 readers that create `.lock` files MUST NOT run on
frozen originals. No readers here import or call those old routines.

All ancestors and file leaves are opened through retained directory descriptors
with `O_NOFOLLOW`. Only regular files with one hard link are accepted. Parent
links, hard links, FIFOs and path traversal are refused. File identity, size,
mtime and ctime are checked across each read and against its directory entry.
This is not a snapshot publication protocol: Task 3 must reverify original bytes
at its snapshot boundary, and enforce its independent output boundaries.
On systems without POSIX directory-descriptor/no-follow support, this reader is
not an approved portable fallback. `/tmp` or `/var` aliases on macOS must be
configured using their physical nonlinked paths (for example `/private/tmp`).

## Engineering bounds

These are resource limits, NOT signal/lookback/selection parameters:

- Per regular file: 2 MiB, checked before read allocation, plus a bounded read.
- Package and reopened evidence aggregate: 16 MiB; registry separately <= 2 MiB.
- Rows/items per ordinary list: 2,000; per source-ref list: 64.
- Registry: <= 100 packs, <= 16 evidence-root aliases.
- Reopened distinct evidence files: <= 64.
- Package layout: <= 10 directory entries, including the `inputs` directory.
- JSON nesting: <= 32, checked before JSON decoding.
- Decimal text: <= 80 characters; identifiers: <= 100; text: <= 4,096;
  relative paths and JSON pointers: <= 512.

The package allows only `request.json`, `source-manifest.json`, `SHA256SUMS`,
and the six fixed role files below. A manifest declares all six roles exactly
once. A declared missing role has `sha256=null`, a nonempty identifier
`missing_reason`, and no file. Unexpected missing files remain `DATA_BLOCKED`.
`SHA256SUMS` contains exactly the request, manifest and declared present sources;
it never hashes itself. Each line is `<64 lowercase hex>  <relative path>`.
No extra files, hidden alternate registrations, nested directories or links.

## Exact schemas

Every field listed below is required, even nullable fields. Every unlisted field
is refused. `technical_contract.SCHEMAS` is the matching machine field-set table.
All JSON objects reject duplicate keys, including deeply nested objects.
NaN and Infinity are refused at parse time. UTF-8 input and valid Unicode strings
(including escaped string content) are required.

Identifiers are JSON STRINGS matching `[A-Za-z0-9_.-]{1,100}`. Numeric tokens
cannot impersonate identifiers. Dates are real `YYYYMMDD` strings. Timestamps
require ISO date/time with seconds and an explicit `Z` or numeric timezone offset.
Host timezone is never inferred. Cutoff comparisons belong to Task 2.

Decimal fields accept plain decimal strings or JSON numeric tokens, retaining
original decimal text (including trailing zeros) without passing through float.
Exponent notation, nonfinite strings, boolean numbers and excess precision
length are refused. Prices must be positive exact multiples of 0.01 CNY, checked
under a bounded explicit Decimal precision context. Volume/amount are nonnegative;
OHLC must be coherent. Bar dates must be unique and strictly increasing.
Source raw/normalized unit labels are preserved, NOT converted or inferred.

| Record | Exact Fields |
| --- | --- |
| request (`technical-request.v1`) | schema_version, workflow_version, rule_profile_hash, mode, pack_id, ts_code, industry_key, as_of, data_cutoff, generated_at, window_id, exposure_status, source_manifest_hash |
| manifest (`technical-source-manifest.v1`) | schema_version, sources |
| source | role, path, origin, sha256, identity, evidence_grade, published_at, available_at, captured_at, raw_unit, normalized_unit, licensing, missing_reason |
| identity | ts_code, industry_key |
| raw_unit / normalized_unit | price, volume, amount |
| licensing | license_id, display_scope |
| bars (`technical-bars.v1`) | schema_version, timeframe, rows |
| bar row | ts_code, trade_date, bar_close_at, available_at, open, high, low, close, volume, amount, price_basis, currency |
| calendar (`technical-calendar.v1`) | schema_version, version, source_hash, coverage, days |
| coverage | start, end |
| calendar day | trade_date, is_open, close_at, suspensions |
| suspension | ts_code, status, source_refs |
| corporate actions (`technical-actions.v1`) | schema_version, ts_code, price_basis, coverage, verified, actions |
| action | action_id, effective_date, available_at, kind, verified, source_refs |
| flow (`technical-flow.v1`) | schema_version, ts_code, rows |
| flow row | trade_date, available_at, settlement_status, main_net_flow, main_net_flow_missing_reason, currency |
| context (`technical-sector-context.v1`) | schema_version, context_id, industry_key, as_of, data_cutoff, source_refs, market_state, sector_state, rationale, counter_evidence, authored_by, authored_at, review_status, reviewed_by, reviewed_at, invalidation_conditions, supersedes, context_hash, review_receipt, industry_mapping, is_human_judgment, automated_decision, claim_allowed |
| research binding (`technical-research-binding.v1`) | schema_version, ts_code, industry_key, packet, decision, packet_hash, decision_row_hash, cohort_id, causal_cluster_id, method_version, research_case, thesis, valuation, red_flags |
| thesis / valuation | source_ref, missing_reason |
| red flags | ts_code, as_of, available_at, coverage_start, coverage_end, verdict, reasons, source_refs |
| external evidence ref | root_alias, path, sha256, pointer |

Source roles and paths:

| Role | Fixed Path |
| --- | --- |
| bars | inputs/bars.json |
| calendar | inputs/trade-calendar.json |
| corporate_actions | inputs/corporate-actions.json |
| flow | inputs/settled-flow.json |
| context | inputs/sector-context.json |
| research_binding | inputs/research-binding.json |

Enums: request workflow `technical-workflow.v0.1`; exposure
`EXPOSED/UNEXPOSED/UNKNOWN`; timeframe `1d`; evidence grade `E1/E2/E3/E4`;
display scope `LOCAL_ONLY/PRIVATE_TEAM/NO_DISPLAY`; price basis `RAW/ADJUSTED`;
currency `CNY`; suspension `VERIFIED/UNKNOWN`; action
`SPLIT/DIVIDEND/RIGHTS/OTHER`; flow `SETTLED/UNKNOWN/PENDING`;
market `RISK_ON/WEAK_REPAIR/RISK_OFF/STYLE_ROTATION/UNKNOWN`;
sector `CONFIRMED/NOT_CONFIRMED/ADVERSE/UNKNOWN`; review
`PENDING/REVIEWED/DISPUTED`; red flags `CLEAR/ACTIVE/UNKNOWN`.
These enums validate vocabulary, not truth. In particular `ADJUSTED`, unknown
suspensions/actions, alleged SELECT, reviewed names and future timestamps cannot
grant readiness; Task 2 supplies the blocking semantics.

Units may be null for inapplicable fields. Context `reviewed_by/reviewed_at`,
`supersedes/review_receipt/industry_mapping` may be null. Research
`packet/decision/packet_hash/decision_row_hash/cohort_id/causal_cluster_id/`
`method_version/research_case` may be null. Source refs point at bytes only, and
claimed `packet_hash/decision_row_hash/context_hash/calendar.source_hash` are NOT
verified semantic hashes by Task 1. Only `bindings.*byte_hash*` identifies bytes
actually reopened; `profile_semantic_hash` has its distinct canonical meaning.

## Profile and verification

`DAILY_SWEEP_RECLAIM_CANDIDATE_0_1` records the approved frozen parameters, not
legacy SMC engine defaults. The catalog distinguishes intended enabled methods
from implementation: all executable daily concepts are still `NOT_IMPLEMENTED`;
session/killzone are `UNSUPPORTED_TIMEFRAME`. No old engine capability is adopted.
Canonical encoding is reused from `research_workflows.evidence.canonical`.
Each profile load returns detached values; overrides, including bool-as-int
substitutions, are refused. The approved spec copy preserves its original
candidate-status wording and exact bytes; separate human approval is not rewritten.

Focused verification: `AR_OFFLINE=1 python3 tests/test_technical_contract.py`.
Task 3 must add real CLI tests, register CI/no-network tests and mutation pins,
and run the whole-slice gate. Task 1 tests and synthetic byte bindings do not
replace real-source acceptance or independent review.
