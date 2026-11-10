# Shared Human Review Portal V1

## Intent And Authority

Junyan requested the retained Reed review packet on the isolated private shared
workbench, with source/gap visibility and attributed comments. Retain seals,
hashes and permissions; exact final-SHA acceptance, nonauthor review and remote
CI precede a backed-up, reversible isolated upgrade. Never merge or modify
production. This extends the approved shared-workspace design; it does not
approve research, source rights, raw document distribution or model use.

## Chosen Approach

Reuse private Tailscale identity and the existing workspace event chain. Add a
default-off review portal and operator-admitted, immutable derived packet.
Do not make a public document share, serve arbitrary paths, add a parallel
database, or use a free-form editable research report. Those alternatives lose
existing identity, preservation or version boundaries.

Only the operator can admit a packet with an independently pinned packet
manifest and an exact packet-scoped human-review grant. For this request the
grant admits Junyan and the existing Reed login only. It permits reading the
curated derivative, source metadata and gaps, appending one's own comments,
and reading submitted team comments. Original sharing/model flags remain false.
No raw PDFs, source excerpts, private host paths, arbitrary URLs, HTML execution,
provider calls or automatic source fetching are exposed.

## Contracts

- Storage root: state/review-packets/<packet_hash>/{packet.json,grant.json}.
- Derived packet schema: ar.human-review-packet.v1. Bind original local packet
  manifest SHA256, financial pack/content/basis hashes, financial cutoff, daily
  vintage, draft date, producer version, F/C/R/L attribution, source metadata,
  explicit missingness and exact review item IDs. Sample text is plain text.
- Grant schema: ar.human-review-grant.v1, independently pinned before admission;
  exact audience, exact capabilities, original source-body/model permissions false.
- REVIEW_PACKET_REGISTERED event binds packet/grant byte hashes; file self-reseal
  cannot replace an admitted packet. Every read/write revalidates both.
- REVIEW_ANNOTATION event binds command ID, packet hash, item ID, server login,
  workspace, code SHA, server time, comment text, status and severity. No client
  supplied actor, outcome PASS or downstream approval state.
- Comment statuses: MATCH, ISSUE, NEEDS_SOURCE, OUT_OF_SCOPE. MATCH is a scoped
  content opinion, not research/source approval. Severity: NONE, MINOR, MAJOR,
  BLOCKING. Text is 1..4000 characters, plain text, credential guard retained.
- An exact actor-bound retry is idempotent; changed bytes or another actor using
  the command ID conflicts. Revisions are new comments; no edit/delete endpoint.
- Max 20 admitted packets, 1000 comments per packet, existing global event/file/
  backup limits unchanged. Inputs/outputs and response collections are bounded.

## Interface And Safety

Default-off --shared-review-v1 requires private shared mode. GET review list and
packet endpoints show only admitted audience packets and verified comments.
An exact POST review-comment endpoint reuses Origin/session/CSRF/JSON and length
checks without broadening existing operation routes. Stale actor/workspace/code,
packet tamper, unknown fields, wrong pins and unauthorized audience fail closed.
Admission transforms only the exact hash-checked buffers and captures grant bytes
before validating their independent pin. Later reads may reject changes but never
replace the consumed buffers. Comment timestamps are finite nonnegative server
seconds bounded to year 9999, verified before commit and again during restore.

The page uses existing UI controls/icons, immutable sample and source/gap views,
item/status/severity selectors, textarea and explicit submit. React renders text,
not raw HTML/Markdown. Source links are validated HTTPS cninfo metadata only.
Refresh/login changes invalidate submit callbacks. Unconfirmed submissions retain
the same command ID for retry; never silently duplicate or claim delivery.
Definitive first-attempt validation/auth/size/rate rejections remove the local
pending record and reopen editing. Network/5xx/ambiguous conflicts retain the
original command. Any rejection of an already uncertain retry retains it too:
rejection of a retry cannot prove the original attempt was not committed.
Mounted JSX tests run in the UI CI with its locked esbuild dependency; the Python
mutation runner executes dependency-free client guard/receipt state tests. Neither
suite skips its assertions when dependencies are absent.

Submitted comments are visible to the exact packet audience, never public or
automatically visible to later members. No private autosaved draft sync is added.

## Preservation And Release

Use existing workspace_events, immutable triggers, hash chain, write_new and
backup chunk limits. Include review packet files in complete backup; verify
committed packet/comment bindings during backup and cold restore. Preserve
uncommitted registration files as recovery evidence, not admitted content.

Remote upload contains code and synthetic fixtures only, never real packet data,
filings, comments, runtime databases, credentials or source paths. Open a Draft
PR against the explicit stacked base; inspect exact-HEAD Python/UI CI. No merge.
Upgrade only original private 8443 audience, after fence/drain, complete cold
backup/reopen, new state/runtime and rollback plan that retains post-cutover work.
Source capture remains read-only. Human two-device acceptance remains separate.

## Acceptance

Wrong-pin, audience, body/path, source/grant tamper, forged actor/authority,
stale context, duplicate/retry, response race, XSS, size/capacity and cold-restore
counterexamples must reach their guards. Retain all existing mutation pins.
Run final-SHA complete local workflow-equivalent CI and all declared mutations,
nonauthor review, actual isolated browser submission/reopen and permission checks,
desktop/mobile layout, backup/cold restoration, then exact-HEAD remote CI.
Engineering success never certifies financial contents or changes PENDING/gaps.
