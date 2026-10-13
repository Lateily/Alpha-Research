# Bounded Private Shared Brief

This opt-in bridge supersedes the old blanket proxy prohibition only for the
already-approved Tailscale private HTTPS8443 route. The Python listener remains
127.0.0.1 by default and in private mode. No public listener, Tailscale Funnel,
new access grant, cloud deployment or production activation is delivered here.
The old PR382 is not merged or a deployment prerequisite.

The parent operator, not the implementation agent, may later start a fresh
isolated state using the existing approved Serve route. Supply the paired
options `--private-origin` (the exact `https://host.tail.ts.net:8443`
origin), `--owner-login` (Junyan's exact local login), and, for the already
approved Reed access, `--private-allowlist` (an absolute outside-repository
path). Owner-only mode omits the allowlist; the approved Junyan/Reed shared
startup supplies all three options together. Keep actual external logins and
routing configuration local. No other
member is approved by this document. The file is owner-UID-owned, mode 0600,
regular, at most 4096 bytes, and has no symlink parents. Shape example only:

```json
{"members": ["member@example.com"]}
```

`owner@example.com` is the fixture owner, not runtime configuration. Duplicate
JSON keys/logins, unknown fields and listing the owner as a member are rejected.
Restart is needed after operator-approved local allowlist changes. The DB stays
in the single operator-selected `--state-root`; both clients read the same
observations, job events and verified reports. The implementation agent did not
start a server, inspect production, or alter Serve/Funnel/access settings.

Tailscale Serve must supply its trusted `Tailscale-User-Login` header while
proxying from loopback and preserving the exact external Host. Missing, foreign
and duplicate identity/security headers are denied. Each login receives its own
HMAC cookie with Secure, HttpOnly and SameSite=Strict. Writes require the exact
Host, Origin and identity-bound cookie as the CSRF boundary; CORS is not opened.
The private origin accepts only one ar_workbench cookie token, without additional
cookies or whitespace/comma/semicolon aliases. An old single opaque session token
may reach the entry page to be replaced; API access still compares the exact HMAC
for the current login and server secret. Ambiguous cookies never reach execution.
Only the exact entry page mints a cookie, after identity and origin checks, and
records a PRIVATE_LOGIN event with the actor in the same isolated DB. Failed
authentication does not mint a session or execute a job.

Both OWNER and MEMBER are **access roles only**, never human research approval.
They have the same private write boundary: only `POST /api/workspace/job` with
exactly `command_id` and `kind`, and kind `observe` or `snapshot-brief`. All
other writes, including password/owner setup, schedules, providers, deployment
drafts, research drafts, review, replay, U4 and paper operations, are denied
before execution. Reads are the existing `/api/state`, `/api/workspace` and
built assets, not arbitrary files. Source roots/packs are startup-only local
operator configuration, never HTTP arguments or automatic raw-source uploads.

Job start and finish events carry the actor; request_hash includes that actor.
Same-login retries preserve the original job, including interrupted/STOP jobs;
another login reusing that command ID conflicts. Private startup does not start
the scheduler, tick is disabled, and scheduled job claims are denied even if
the state already contains enabled local schedules. No private schedule is
granted. The local-mode event/request/receipt format and legacy operations stay
unchanged. Existing brief/earnings pack options remain supported locally.

The host, service UID and Tailscale administration are trusted. This bridge
cannot resist a same-UID process spoofing a Serve login header on loopback, or
a host administrator rewriting the DB/configuration. It is not independent
SSO, public-internet hardening, an approval signature, or a tamper-proof ledger.
Parent review and later two-device fresh-state acceptance remain required;
zero-network tests do not establish real Tailscale connectivity or GitHub CI.
