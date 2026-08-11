# Product And Frontend Instructions

These rules apply to `web/` in addition to the repository contract.

- The frontend is a read-only consumer of versioned files under
  `public/data/v2/`. Do not call Tushare, model providers, or research engines.
- Contract fields and status enums are authoritative. Unknown, stale, partial,
  and blocked states must remain visible; do not invent fallback values.
- Keep operational views quiet, dense, and easy to scan. Reuse the existing
  design system and icon library before adding new patterns.
- No nested decorative cards, fake status badges, or instructional marketing
  copy inside the application.
- Verify desktop and mobile layouts, loading/empty/error/degraded states, and the
  production build before requesting review.
- A contract change is not a frontend-only change. Declare the producer,
  consumer, migration, and compatibility effect in the task and PR.
