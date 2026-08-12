---
name: ar-product-engineering
description: Build AR product, frontend, API presentation, and data-contract consumer work using the existing UI system and read-only versioned contracts. Use for web/product changes, not research-engine logic.
---

# AR Product Engineering

1. Read `web/AGENTS.md`, the product spec, and the exact producer contract.
2. Confirm field names, schema version, freshness, and status enums against real
   fixtures before building UI.
3. Consume `public/data/v2/` through existing data helpers. Do not call providers
   or write research state from the frontend.
4. Implement loading, empty, partial, blocked, stale, and malformed states.
5. Reuse the design system and installed icon library. Keep operational screens
   dense, restrained, and scannable.
6. Verify text containment and interaction on desktop and mobile viewports.
7. Run focused tests and the production build. Use browser screenshots for
   user-visible changes.
8. Declare any producer or contract change separately in the PR.

Do not hide data-quality limitations to make the interface look complete.
