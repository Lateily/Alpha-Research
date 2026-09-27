# Team Private Workbench V1

Status: nonproduction team-access implementation. This does not grant anyone
formal research approval, production, trading, or paid model authority. The
existing owner-only instance stays untouched until a reviewed release and
explicit member identities are available.

## Mac Runtime

- Keep the backend on `127.0.0.1` behind Tailscale Serve HTTPS. Never enable
  Funnel or a public listener. The Mac must stay awake and online.
- Pin the reviewed code release and build assets. Use a dedicated nonproduction
  state directory; mount the production artifact root only for allowlisted
  read-only observation. Do not give team members shell access to this host.
- Configure the exact `--private-origin`, `--private-owner-login`, and one
  `--private-developer-login` per approved Serve login. Do not use display names,
  domains, wildcards, GitHub handles, or a shared browser account. Initially
  omit all developer flags: that is the owner-only fail-closed default.
- Junyan supplies and approves the exact Tailscale login of Simon, Jason, and
  Better before adding them. The three logins have the same DEVELOPER role:
  read historical observations, edit and submit local drafts, run allowlisted
  offline probes/replays/jobs. Owner alone may configure the local owner
  password, review local drafts, edit local schedules, and save the deployment
  draft. No role can call production, real market APIs, paid models, formal U4,
  paper registration, or trading through this workbench.
- Every HTTP request rechecks the Serve login. Member browser sessions are
  derived separately from the server secret; a copied cookie cannot change
  identity. Same-host OS users are in the trust boundary because they can
  reach loopback and spoof proxy headers. Do not host untrusted local users.
- Tailscale is the transport identity, not the formal human-signature ledger.
  Existing U4/paper/production gates retain their separate approval process.

## Release And Acceptance

1. Review the exact code commit, run Python tests, mutation gate, and complete
   offline CI; freeze the built assets. Preserve the old owner-only release as
   rollback. No development branch writes into the live release.
2. On this Mac, test owner and each named member via Serve: each sees the same
   run ID and historical source date, can create an isolated draft/job, and
   cannot invoke another role's routes. A nonmember and a copied cookie must be
   denied. Verify no paid or production calls and no production-file changes.
3. Repeat from one other enrolled device. One-Mac HTTPS success alone does not
   prove remote access. Record the checked commit, artifact hashes, identity
   (redacted in shared reports), time, and outcomes.
4. Only after that acceptance, switch the private endpoint to the pinned team
   release. If a check fails, restore the owner-only release and keep production
   untouched. Team membership or ACL changes require a separate Junyan decision.

Code collaboration stays in Git branches and reviewed PRs. Frozen research
inputs move as hash-checked, permitted packages, not ad hoc copies of the
production SQLite, secrets, WAL, or published pointers. Each developer runs
their own local sandbox and CI; the shared Mac hosts the reviewed release.

## Function Compute Extraction

Do not move the full Mac runtime as one function. Start only after team and
historical-read acceptance. Candidate functions are bounded, stateless,
replayable transformations with a frozen input hash and immutable output:
contract validation, source text extraction where licensing permits, daily
brief formatting, and deterministic evidence-card rendering. A function gets
the minimum read-scoped input and writes a result under a unique task ID; an
independent checker compares it with the Mac sandbox before promotion.

Keep the nightly scheduler, market collection, SQLite and append-only ledgers,
published pointer transaction, research approvals, and paper settlement on
the Mac initially. They depend on durable locks, time, state, or licensed data;
moving them requires a separate storage/identity/transaction design and a
fail-closed canary. Function Compute is not a replacement for the workbench's
long-running server or the Mac's current production authority.

No Function Compute resource, data upload, chargeable invocation, or production
cutover is authorized by this document. Cost limits, data rights, region,
secrets, retry/idempotency, audit receipts, and rollback must be decided before
each individual extraction.
