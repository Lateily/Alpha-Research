# Owner-Only Private Workbench

Goal: use the existing Mac and owner-controlled Tailscale account for one private
trial. No production cutover, team access, billing change or model call.

1. Add failing in-memory HTTP regressions for owner-only identity at all entry
   points, exact HTTPS origin, duplicate security headers, loopback proxy peer,
   Secure session cookies and unchanged CSRF/capability boundaries.
2. Extend the existing handler with explicit optional private access. Validate
   both CLI settings before opening state. Preserve local-only defaults. Trust
   Serve-injected identity only at the loopback backend; it is not formal approval.
3. Add mutation pins, CI registration and operating documentation. Run all
   affected suites, the whole gate, and every local python-ci step. Obtain an
   independent bounded review. Do not merge without Junyan.
4. Build a separately pinned trial release with a fresh state directory and only
   frozen historical evidence. Existing snapshots, viewer and production stay
   untouched. Restrict runtime writes to the new trial directory.
5. Check Serve configuration is empty, then configure private HTTPS only. Stop
   for human HTTPS/account consent if needed. Verify owner access and denial
   paths on this Mac. Cross-device acceptance remains pending, not assumed.

Trust boundary: Tailscale Serve strips client-supplied identity headers. The
application is not reachable on LAN, only loopback. This does not defend against
a malicious same-host OS user or host administrator. Separate OS identities are
required before adding untrusted local workers. No account-wide ACL, invites,
Funnel or production scheduling change is in scope.
