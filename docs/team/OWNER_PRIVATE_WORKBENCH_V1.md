# Owner-Only Private Workbench V1

Status: nonproduction trial. One owner account, no team grants or production
cutover. The application still listens only on `127.0.0.1`. Tailscale Serve
provides private HTTPS; Tailscale Funnel (public internet sharing) is forbidden.

## Access Boundary

- Start a new instance with a dedicated state directory and frozen evidence root.
  Never reuse production state or relabel isolated results as published data.
- Supply both `--private-origin https://<device>.<tailnet>.ts.net` and
  `--private-owner-login <exact-login>` in machine-local launch configuration.
  Missing or malformed settings fail before opening state.
- Serve must proxy to this instance's loopback port. It removes incoming user
  identity headers and adds the authenticated `Tailscale-User-Login`. The app
  requires an exact single owner identity for pages, reads and writes, including
  before issuing any browser session. Missing identities, tagged devices and
  other members/shared users are denied, even with a copied session cookie.
- Secure/HttpOnly/SameSite session cookies, exact Host/Origin checks and existing
  CSRF/body/capability checks remain enforced. An owner identity is transport
  authentication, not Junyan's formal U4, registration or production approval.
- Same-host OS users and the host administrator are inside the trust boundary:
  they can connect to loopback. This is not multi-tenant host isolation. Do not
  add untrusted local workers or team members without a separate identity and
  execution-isolation design. Control who can enroll devices in the tailnet.

## One-Mac Trial

1. Build and pin the reviewed release. Hash-check frozen input before use.
2. Start the backend on a free loopback port with a fresh state directory. Keep
   provider secrets absent and runtime writes confined to that new directory.
3. Inspect `tailscale serve status --json`; preserve any pre-existing services.
4. Use `tailscale serve --bg --https=443 http://127.0.0.1:<port>` only after
   owner consent. If HTTPS/account consent is requested, the owner completes it.
   Never run `tailscale funnel`, enable public ports, or change account-wide ACLs.
5. Verify HTTPS access from the connected Mac, private ownership denial tests,
   sandbox replay and read-only historical dates. Inspect status to confirm no
   `AllowFunnel` entry. A successful single-Mac check is not cross-device proof.
6. To withdraw only this endpoint: `tailscale serve --https=443 off`, then stop
   its backend. Do not use `serve reset` to erase unrelated services.

The host must remain awake and online. This is not cloud 24/7 operation. HTTPS
certificate issuance may publish the machine DNS name in certificate transparency
logs; research payloads are not public web content. Tailscale plan eligibility
must be checked separately before business/team use; no billing upgrade is
authorized by this trial.

Official references: https://tailscale.com/docs/features/tailscale-serve and
https://tailscale.com/docs/reference/tailscale-cli/serve.

## Still Disabled

Team access, cloud resources, paid DeepSeek calls, live data collection,
production writes, real trades, formal U4 approval and paper registration stay
disabled. Local research drafts, offline fixtures, local review records and
read-only observations remain `WORKFLOW_DEBUG`, not production evidence.
