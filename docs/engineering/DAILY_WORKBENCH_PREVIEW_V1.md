# Daily Workbench Preview V1

## Approved Design

Junyan approved an isolated, clickable daily interface with five primary views:
Today, Research, Holdings, Macro, and Tests. Keep the existing backend and all
validation unchanged. Show missing data, expired verification and pending human
review next to the affected result. Put hashes, versions and raw metadata in
evidence details. No fabricated numbers, performance claims or pretend actions.

## Scope And Approach

Build a separate React entry, not a replacement for the deployed entry. A
loopback-only read-only preview serves a pinned, sealed projection produced by
the unchanged backend from an independently restored historical archive. It
does not connect to the live service, production source, providers or schedulers.
The prototype supports actual navigation, local search/filtering of the loaded
registered metadata, task selection, citation inspection and permitted metadata
download. Starting new research, submitting comments, executing tests and trading
are not attached to this preview and have no actionable controls.

This choice avoids introducing a synthetic private-network identity bridge or
weakening the existing HTTPS/member/session controls just to show a local UI.
The other options were modifying the live interface (not authorized) and fake
API responses (not acceptable). The production backend files remain byte-identical.

## Data And Presentation

- Consume only existing verified shared-task/card metadata and captured source
  contracts; label their actual source date and capture date, not today's data.
- Preserve original statuses, actor/execution/producer identities and hashes.
- A fresh preview read verifies the pinned projection bytes and seal, not a new
  source collection, human approval, full nightly acceptance or research run.
- Successful response freshness expires at 15,000 ms; failed/late reads cannot
  enable downloads or display a current verification claim.
- Never distribute raw original files or unapproved report/citation bodies.
- Empty holdings, unavailable model execution and incomplete macro fields remain
  empty or blocked, never synthetic zeros or placeholders that look like results.
- Five views use a restrained neutral palette with green, amber and red status
  accents, compact navigation, readable tables and a mobile bottom navigation.

## Acceptance

Behavior tests cover all five routes, partial/unknown/expired/pending states,
search AND filters, original task identity, exact metadata download, rejected
mutations of the projection and read-only server methods. Browser QA at desktop
and 390/360 px widths covers navigation, task evidence and citation expansion,
filters, text containment and no overflow. Negative tests pin the 15-second gate.
Provide screenshots, code diff and evidence. No deployment, merge, network data
collection, production mutation or two-human acceptance is included.
