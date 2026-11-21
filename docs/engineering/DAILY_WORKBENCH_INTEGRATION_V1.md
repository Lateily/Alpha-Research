# Daily Workbench Integration V1

## Approved Scope

Junyan approved the five-entry 56a8f1d interface and requests real frozen research
submission, persistent task steps/citations, archive and industry/date/ticker
queries, and append-only comments through the existing authenticated backend.
Use existing React, lucide, Vite and exact versioned API validators. Keep all
backend code, identities, hashes, seals, rights and research authority unchanged.

## Approach

The new private entry reuses the approved presentation components and existing
closed-schema client validators. A small live controller owns independent,
single-flight context/card/detail/review reads. Every response has its own
15,000 ms age and request-generation binding. A fresh identity-only read cannot
refresh result, detail or review evidence. Every write and download rechecks its
relevant evidence at click time. Late/failed responses do not revive old controls.
Retain original command IDs locally for uncertain writes; no automatic POST retry.

Embedding the old multi-tab workspace would preserve behavior but abandon the
approved layout. Building new backend routes would unnecessarily duplicate the
existing contracts. The chosen adapter approach preserves both the interface
direction and server-side validation. No provider, market or model calls occur.

Research uses existing registered frozen cards. Submission means deterministic
recomputation/verification and metadata archival, not newly generated analysis,
human approval or current-day market evidence. Original source/draft/daily dates
and DATA_BLOCKED remain visible. Same-report grouping retains all task IDs.
Exact industry/date/ticker filters query the server; any local fuzzy search is
clearly limited to loaded metadata. Comments may target only a granted packet
matching the selected research input/content/basis, never imply research approval.

Other entries consume existing permitted contracts or show an explicit unavailable
state. Do not bundle the previous local historical projection into the release,
invent performance receipts or add fake model/test/trading execution buttons.

## Delivery Gates

1. Synthetic RED/GREEN and actual retained-handler negative tests, legacy suite,
   complete CI-equivalent regression and original governance mutations.
2. Same final code identity; independent nonauthor source review; remote required
   Python and UI CI. Synthetic PR merge commit/tree identity is disclosed exactly.
3. Restore a fresh isolated state from an approved archive, verify all rows and
   artifacts, use test identities without claiming human signoff, and exercise
   real submission, steps, citations, archival, AND queries and comments on both
   desktop and mobile viewports. No live original state is used for isolation.
4. Before private activation, inspect current process/config and newest state,
   fence ingress, drain and prove writer stopped, back up the final stopped state,
   and cold-start both new and old code against independently restored copies.
5. Restore the candidate from that newest generation; switch only the existing
   8443 target after local authenticated checks. Preserve all old code/state.
   Post-live archive/restore must preserve every old record and every new task
   and comment. Rollback fences/drains/backups the newest generation and starts
   old code on a fresh restore of it; never restore an old database over new work.

Code delivery, private deployment, human research approval, physical phone/two-human
acceptance and formal nightly production are separate. No merge, membership,
formal schedule, paper/U4 or trading change is approved by this task.
