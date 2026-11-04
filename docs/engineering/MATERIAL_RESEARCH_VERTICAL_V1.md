# Real Materials To Earnings Tasks V1

This is a local-only continuation of the foundation blueprint, not an expansion
of the private/shared dispatcher. Two-human-device acceptance is deferred, not
passed. Production and the running8443 service remain unchanged.

## Vertical

```text
Externally pinned admitted material library
 -> explicit company/document/version/PDF hash/physical pages
 -> authored draft questions and exact page-line quotations
 -> bounded isolated pypdf extraction and quotation verification
 -> sealed original PDF + extracted pages + source map + historical trial input
 -> externally retained pack hash
 -> existing local earnings-trial job
 -> readable report, source citations, pending human-review template
```

This proves byte/citation flow, not company facts, source authenticity,
investment judgment, a prior thesis registration or a full earnings analysis.
New question drafts use the program-observed preparation date and registered_at=null.
The asserted request timestamp is retained separately, never presented as observed
acquisition/generation evidence. Preparation records its own timezone-aware clock;
new question as_of must match that Shanghai date. Reopening uses the frozen observed
timestamp rather than today's clock. The downstream trial is normalized to UTC+08
and preflighted before its final seal is published.
The source cutoff remains separately visible. Every assessment is UNRESOLVED;
no automatic positive/negative thesis verdict is accepted in the request.

Only admitted originals can be selected. Quarantine is never scanned, read or
promoted. Library rights remain UNVERIFIED/private, sharing_allowed=false and
model_use_allowed=false. No team source-serving or external model transmission
is added. Source publisher identity stays UNVERIFIED; extracted citations receive
E3, never an invented issuer E1 attestation. Hashes prove bytes, not truth.

## Operator Interface

`ar.material-research-request.v1` has exactly schema,company,as_of,
source_cutoff_at,generated_at,expected_library_hash,authoring,documents,questions.
Each document names material_id,version,sha256,pages. Each question has id,
question,criteria,citations,missing_evidence. Each citation pins PDF sha256,
physical page,start/end extraction lines and exact expected text. Missing
evidence is required even when excerpts are present. Criteria are a new draft,
not an approved strategy threshold.

```bash
python3 -B scripts/llm/foundation_cli.py research-pack \
  --library-root /absolute/admitted/library \
  --request /absolute/operator-request.json --write-root /absolute/new-pack
python3 -B scripts/llm/foundation_cli.py research-pack-verify \
  --pack-root /absolute/new-pack --expected-pack-hash <independently-retained-hash>
python3 -B scripts/llm/nonprod_workbench.py --host 127.0.0.1 --port 8792 \
  --state-root /absolute/new-isolated-state \
  --earnings-pack-root /absolute/new-pack --earnings-pack-hash <same-hash>
```

Operator paths never come from HTTP requests. The existing loopback UI can run
earnings-trial and inspect its report; the private/shared whitelist still refuses
that kind. No permission or scheduled earnings entry is enabled. Legacy earnings
packs without material-pack.json, material-pack.intent.json or source-map.json
retain the previous contract. A material pack
requires the independent hash; an expected hash also prevents marker-removal
downgrade. The job verifies the complete original/text/request derivation before
and after rendering and retains failed output evidence without marking success.

## Bounds And Storage

Max8 PDFs,32 selected pages total,16 draft questions,8 citations/question,
4000 characters/quote,256KiB extracted text/page,64MiB pack. Existing12MiB
single-file guard remains. No OCR or missing-text substitution. pypdf6.10.0 is
pinned; extraction runs in a separate clean-environment process with a10-second
per-document timeout and no shell, provider configuration or inherited secrets.
Decoded PDF object names are also inspected, including escaped and compressed
objects; raw-byte scanning alone is not the no-active-PDF check.
This local preparation profile is not the two-slot shared worker's120-second
profile. A future shared research runner needs its own explicit resource contract.

The new output root is exclusive. Original PDFs and selected page texts are
copied unchanged/derived separately; the source library is never edited. The
complete file inventory and marker seal bind all files; the marker is written
last. A persistent material intent is written before any trial content, so a
crash before the final seal cannot silently downgrade into the legacy path.
An interruption retains an uncompleted root, which is never overwritten
or silently retried as a new complete input. Reopening re-extracts original PDF
pages and rebuilds the exact trial request. A coherent re-seal cannot bypass the
external pin. A local pack is not an off-machine backup.

## Acceptance

Use the final candidate's tests/test_foundation_research.py, old materials/CLI/
workspace/trial regressions, full offline CI command replay and behavior mutation
gate. Independent review and real historical demonstration name that same SHA.
Real original content, runtime states and private reports stay outside Git.
Any unverified source, quote, cutoff, path, incomplete write or changed input
must remain a refusal/STOP, not a successful research judgment.
