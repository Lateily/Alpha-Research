---
name: ar-adversarial-review
description: Review an AR pull request or implementation claim adversarially, verifying source, behavior, tests, and overselling before a merge decision. Use for audits and PR reviews; do not modify code unless explicitly asked for fix-forward work.
---

# AR Adversarial Review

1. Compare the PR head with its real base and list the net files first.
2. Treat delivery claims as unverified until the referenced file or behavior is
   inspected and the relevant command is rerun.
3. Check both false-pass and false-rejection risk.
4. Exercise the production entry path, not a similarly named helper.
5. For high-risk guards, disable one guard cleanly and confirm the designated
   behavioral test turns red for the intended reason.
6. Check secret handling, network policy, stale-data behavior, provenance,
   append-only semantics, and deployment overstatement.
7. Lead with findings ordered `BLOCKER`, `MAJOR`, `MINOR`. Each finding needs a
   file/line, failing input-to-result scenario, and one concrete repair.
8. Say `PASS` only when blocking findings are closed and remaining limitations
   are stated accurately.

Do not equate a green CI badge with coverage of the claimed guard.
