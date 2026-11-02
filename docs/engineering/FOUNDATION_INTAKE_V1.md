# Anchored Real Material Intake V1

Implementation is NOT_RUN for unified acceptance. The user separately requested
actual local intake of existing public originals. Successful operational intake
does not promote code testing, source rights, research approval or prospective
sample eligibility. No provider, production/shared service or external upload.

## Explicit Input

The CLI `foundation_cli.py cninfo-intake --request REQUEST --write-root NEW_ROOT`
accepts `ar.cninfo-intake-request.v1` with exactly these fields:

- `source_root`: existing local original research root; never copied recursively.
- `manifests`: up to ten objects with ts_code, relative_path and independently
  supplied expected_sha256. Each manifest must be loop_v1.source_manifest.v1.
- `classification`: null, or industry_key/taxonomy_version/evidence_path/expected_sha256.
  This supports only an explicitly anchored AR_RESEARCH_COHORT, not a verified
  provider industry or point-in-time industry membership. Null stays UNSPECIFIED.
- `run_id`, `library_id`, `research_date`, `cutoff_at`, `created_at`, `code_sha`.

The caller pins source manifest bytes independently; PDF hashes/sizes/URLs are
then obtained from those preexisting manifests, never generated to replace a
missing expectation. The three known historical shapes (raw_files list,
originals dictionary, pdf_originals dictionary) are explicit; mixed variants,
identity disagreements and conflicting capture metadata fail closed.

Only HTTP-200 public static.cninfo.com.cn PDF originals are eligible. Uppercase
extensions remain original byte paths; stored blob suffixes are normalized.
Original issuer/sponsor tier and full historical capture context remain in the
unchanged source-anchor records; intake does not relabel every PDF as issuer E1.
The publisher identity stays UNVERIFIED rather than inferred from a stock code.
Extracted text, scripts, titles-only entries, caches and databases are not copied.

`published_on` has date precision only. The material row explicitly marks a
UTC+08 end-of-day publication upper bound, not an observed release timestamp.
available_at conservatively uses the first capture timestamp in the old manifest.
The old source cutoff and the new intake's research index date remain separate;
the trade_date field here is the research index context, not a market-data or
exchange-calendar attestation. Old filings do not become a new trading packet.

## Operation And Retention

The command requires the exact expected clean local Git HEAD and records hashes
of its execution modules. It rechecks that identity around preparation and actual
operation. Outputs are never allowed inside or above the original root.

All explicitly declared originals receive read-only byte admission before any
registration. Rejected originals stay untouched and appear with precise machine
reasons; a batch containing rejections is PARTIAL, not complete. Zero admitted
files or an operation failure is BLOCKED. Nothing deletes or sanitizes originals
to make admission pass. Failed writes retain their isolated state for inspection.

The new private output root contains:

```text
library/   # exact immutable material-library inventory
records/   # controls outside that inventory, so no circular/self-invalidating seal
quarantine/ # opaque security-refused originals; never research inputs or rendered
```

Records include the original manifest bytes, optional draft-cohort anchor,
request, preflight/start record, normalized intake, actual library verification,
per-ticker/date queries, cohort query, retention pin, preservation manifest,
same-local-root preservation reread and final receipt. The pin requires keeping
the material snapshot until explicit human release; it implements no deletion.
The preservation manifest covers the exact library and any opaque quarantine packages. Control records and
their independently retained receipt/hash must be kept separately alongside it;
they are not silently inserted into the package's exact file set.

Preservation reread of the same local library proves only reopened local bytes
when it actually executes. No other machine, copy, encryption, upload, external
durability, provider retention or restoration is attested. Real transfer remains
separately authorized. All reports retain PENDING and false authorities.

## Security-Refused Originals

The first actual ccf10b1 intake admitted 120/128 PDFs and refused eight with
MATERIALS_ACTIVE_OR_ENCRYPTED_PDF_REFUSED. This rule is not weakened and does not
by itself prove a file is malicious. The guarded library stays incomplete.

Opaque quarantine is a separate exact inventory, not an alternate research
admission path. It rechecks the original expected hash/size and PDF magic, copies
only explicitly listed bytes into non-executable private files, and never parses,
decrypts, renders, extracts, executes, serves or enables research use. Its fixed
policy refuses any resealed promotion of research/render/execution/transfer flags.
An independent quarantine hash and immutable manifest bind its exact file set.
It is bounded to 64 files, 12 MiB per file and 64 MiB in aggregate. Oversize or
hash-mismatched originals remain blocked, not silently substituted.

The final operation may preserve both admitted and quarantined originals, but
its status remains PARTIAL while any document is refused for research. A new
final code SHA and new output root are required; the ccf10b1 first attempt is
retained and never spliced into the later attempt as a single-version success.

## Deferred Acceptance

Tests in test_foundation_intake.py cover actual entry routing with synthetic
original bytes, independent manifest mismatches, original tampering, known
historical shapes, explicit date precision, uppercase PDFs, unknown classification,
cohort-not-industry semantics, output reuse and code identity drift. All remain
NOT_RUN until the same-final-version unified acceptance and independent review.
