# Private Workbench Team Access V1

The workbench listens on `127.0.0.1` only. Tailscale Serve terminates HTTPS and supplies an exact `Tailscale-User-Login` header. This identity grants access to the nonproduction workbench; it is **not** a human research signature, formal U4 approval, paper registration, production authority, or trading authority.

## Operator setup

1. Obtain each person's exact Tailscale login email. Invite that individual to the owner's tailnet and scope tailnet policy to the workbench host and port. Do not share the owner's Tailscale account. No invitation or policy change is implied by a repository merge.
2. Outside the repository, create an owner-owned mode-`0600` JSON file: `{"members":["person1@example.com","person2@example.com"]}`. Use exact lowercase login strings; the owner login is passed separately and must not appear in the list. Do not commit the file or put credentials in it.
3. After independent review and a separate runtime authorization, restart the nonproduction server with its existing `--private-origin` and `--private-owner-login`, plus `--private-team-allowlist /absolute/path/members.json`. The current owner-only server remains unchanged until this step.
4. Test from each named account, then from an unlisted account. Named accounts must reach the same URL; the unlisted account must receive 403. Confirm each browser receives a distinct session cookie and a draft event records the exact account. Confirm owner-only operations reject members.

The allowlist is read at startup. Adding or removing a member requires an intentional restart. A missing, symlinked, group-readable, malformed, duplicated, or repository-resident file fails closed. The service still binds only to loopback; do not replace Serve with a public listener or Funnel.

## Current permissions

Owner: existing nonproduction operations. Member: read the workbench and save/submit research drafts. Member cannot bootstrap the local owner credential, review, schedule, launch local jobs, edit deployment settings, or run synthetic engines. This is a conservative first team gate; additional write capabilities require actor-bound audit and independent tests before enablement.

The event chain attributes member draft/submit writes to the Tailscale login and binds retries to that actor. It is an application audit record, not tamper-proof storage against the Mac administrator. A process already running locally as the same operating-system user is inside the host trust boundary and can spoof loopback proxy headers; this arrangement is for trusted host administration, not hostile local users.

No paid API, model key, production data migration, formal ledger write, or trading operation is enabled by this access change. Browser access does not imply that a teammate has been authorized to run production scripts.
