# Foundation Sources V1

Status: **IMPLEMENTED_UNTESTED**. Sample purpose: **WORKFLOW_DEBUG**.
`testing_status: NOT_RUN`; `human_review: PENDING`.
Production, trading and deployment authority are all **false**.

## Closed APIs

```python
load_source_inventory(path=None) -> dict
build_source_coverage(repository_root, *, inventory_path=None) -> dict
```

Both APIs are read-only. The default inventory is the versioned
`config/data-source-inventory.v1.json` alongside this module's repository, not
an inferred inventory in the target tree. An explicit inventory path replaces
that default. The returned coverage binds the exact inventory bytes by SHA-256.
No source is imported, evaluated, executed or fetched. No subprocess, provider,
environment-secret lookup, Git operation, receipt write or service probe is
part of these APIs. No new scanner command, worker or HTTP path is introduced
here. Invalid registry input raises a fixed `ValueError` code; source discovery
gaps return unresolved accounting, not an automatic CI/deployment blocker.

## Inventory Versus Evidence

The broad inventory registers **provider families and safe host/interface IDs**.
It includes market feeds (Tushare HTTP/SDK/repository adapters, AkShare,
yfinance/Yahoo, Eastmoney, Sina, Tencent, Twelve Data, Alpha Vantage), filings
(CNInfo, HKEX, SEC), news/search/community sources, macro collectors (BLS, CBOE,
FRED, BEA, Census), model adapters/APIs (Moonshot/Kimi, DeepSeek, Anthropic,
OpenAI, Gemini), and operational GitHub/application/Telegram/Resend/Supabase
interfaces. Reference paths are navigation hints from offline code inspection,
not an attestation that every reference is an active call. Unknown/example URLs
and dynamic Supabase hosts are not guessed into the host registry.

`config/data-source-catalog.v1.json` remains the **closed five-source v1 receipt
compatibility reference**. It and the receipt modules are unchanged. Family IDs
in the broad inventory cannot be substituted into its endpoint receipt schema.
The compatibility reference is listed, not revalidated by this scanner.

These are distinct observations:

| Dimension | Meaning |
| --- | --- |
| Inventory match | One explicit host entry matches a syntactic Python HTTP call |
| Interface candidate | A known SDK/adapter family, not a proven endpoint or host |
| Instrumentation | Always `NOT_ASSESSED`; generic HTTP recognition proves nothing |
| Runtime evidence | Always `NOT_OBSERVED`; no provider behavior is exercised |
| Rights | Always `UNVERIFIED`, with no rights evidence or expansion |

The broad inventory deliberately declares **no endpoint field/date/unit
contracts**. `REGISTERED_STATIC` means only one family matches a literal host
on a recognizable HTTP expression. It never means the call succeeded, was
instrumented, was the effective runtime destination, or was licensed. Receipt
coverage is `NOT_MEASURED`. `complete_source_registration` and
`endpoint_instrumentation_proven` are always false, even for an empty scan.

## Bounded Coverage

The default declared root is `.`: it includes repository-level code as well as
`scripts/` (including LLM adapters), `experiments/` (including macro and market
adapters), `api/`, `src/`, `web/`, `tools/`, `bin/`, tests, public code and
`.github/` workflows. Coverage is not limited to the five receipt consumers.

The inventory explicitly excludes runtime/material trees `data/`,
`data_history/`, `public/data/`, documentation and `.superpowers/`, and named
dependency/build/cache/Git/credential directories. Unsupported extensions
(including JSON/config/env files and binary assets) are not read. The configured
extension list covers Python, shell, JS/JSX/MJS/CJS, TS/TSX, YAML and HTML. Both
exclusion policy and unsupported-file counts are returned, not hidden. Symlinks
are skipped, including symlinked directory ancestors during file reads;
nonregular files are refused without blocking. Only declared roots are visited.

Default limits: 6,000 attempted code files, 2 MiB per file, 64 MiB total bytes,
30,000 directory entries, depth 24, 20,000 findings and 100,000 AST nodes per
Python file. Hard ceilings prevent a supplied inventory from removing bounds.
Read failures, missing roots, symlinks, oversized files, depth/node/file/entry/
byte/finding limits are explicit unresolved gaps. Scan issue detail is capped at
1,000 rows; the full issue count and omitted-detail count remain visible.
Sequential reads are not an atomic repository snapshot. Per-file change during
read is rejected; changes after reading require an independent later comparison.

Python is parsed with `ast`, without execution. Findings retain repository-
relative file, source line where available, and SHA-256 of the bytes actually
parsed. Syntax/encoding errors retain only a fixed error code and safe line,
never the exception's source snippet. File inventory also includes bytes and
inspection mode. A supplied absolute path is never emitted as raw source data.

JS/TS/shell/workflow/HTML files receive **bounded text inventory only**, with
URL references and recognizable call/provider tokens. These are always
`UNRESOLVED`, including known hosts and comments. No text match is claimed to
be an executable call. Inline workflow Python is not treated as a Python file.

## Honest Gaps

- Unknown hosts and multiple matching registry rows remain `UNRESOLVED`.
- Dynamic URL expressions, request objects, `getattr`, client receivers,
  repository wrappers, SDK setup/dispatch and chained calls stay unresolved.
- Imported aliases are normalized syntactically. Rebinding, repeated aliases,
  parameters and other ambiguous bindings prevent a registered call result.
  No lexical scope, points-to, interprocedural or cross-file analysis is claimed.
- SDK wildcard entries identify a family only. New/unknown SDK methods do not
  gain endpoint registration merely by matching a module prefix.
- `eval`, `exec`, dynamic imports and module execution are surfaced as gaps;
  generated code, obfuscated calls, arbitrary callable injection, unusual
  library aliases and methods outside the recognizers can still be missed.
- Library redirects, monkey-patching, environment overrides, dependency code,
  actual network destinations and effective runtime permissions are unobserved.
- Host extraction emits only validated hostnames. Userinfo, ports, paths,
  queries, fragments, argument values and source snippets are not emitted.
  A static host hint on a dynamic URL does not resolve that call.

`summary` separates registered-static findings, unresolved findings, unresolved
scan issues and their combined `unresolved_total`; it does not report a
completeness percentage. URL references can coexist with call findings, so
finding totals are not unique logical provider-call counts. All output remains
debug evidence pending human review, not production/trading/deployment authority.

## Deferred Acceptance

`tests/test_foundation_sources.py` authors normal literal-host/alias provenance,
redaction, unknown/dynamic/shadowed calls, SDK/wrapper/chain gaps, ambiguous
registry matches, parse errors, text-only coverage, missing roots, file drift,
all configured bound categories, symlink safety, no source execution/writes,
closed registry rejection and unchanged closed-five compatibility cases.

**None of these tests has run. The scanner and loader have not been invoked.**
Only AST/JSON/diff inspection is permitted in this implementation slice. Still
required: deferred behavioral acceptance (including platform-specific secure
read and race cases), integration with the coordinator's exact APIs, complete
same-HEAD validation and independent review. No runtime PASS, measured live
repository coverage, independent-review PASS or production readiness is claimed.
