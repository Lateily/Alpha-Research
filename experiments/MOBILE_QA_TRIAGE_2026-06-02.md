# Mobile QA Triage — 2026-06-02

Purpose: source-level handoff for Claude after Junyan reported that the live site is very hard to use on mobile. This is not a production patch. It maps the likely mobile blockers in `src/Dashboard.jsx` so screenshots can be matched quickly.

## Scope

- Target: `origin/main` at `b794b16` (after PR #22).
- Surfaces: app shell, Browse, Cockpit.
- Visual browser screenshots were not captured in this Codex pass; this is source-level triage only.
- Investment framing: no change to model logic, no trade advice. This is pure mobile usability/readability.

## Highest-Probability Root Causes

### P0/P1 — Desktop shell squeezes mobile content

`Dashboard.jsx` renders the app root as a fixed desktop shell:

- root: `display:flex`, `height:'100vh'`, `overflow:'hidden'`
- sidebar: `width: collapsed ? 56 : 200`
- `collapsed` defaults to `false`
- main content width on a 390px phone becomes roughly `390 - 200 = 190px`
- bottom status bar is fixed with `left: collapsed ? 56 : 200`

Expected mobile symptom: most tabs feel cramped, clipped, or impossible to operate even if the inner tab is individually correct.

Recommended first fix: add a mobile shell mode below ~768px:

- sidebar defaults collapsed or becomes a top/bottom tab bar
- content gets full viewport width
- bottom status bar left offset becomes `0` or is hidden on mobile
- topbar search/buttons wrap or collapse

### P1 — Browse is still a desktop table on mobile

`Screener` uses fixed multi-column grids:

- `COLS = '32px 1fr 80px 80px 80px 80px 46px 10px'` or 7-column variant
- hero cards: `gridTemplateColumns:'1fr 1fr 1fr'`
- capital-flow cards: `gridTemplateColumns:'1fr 1fr'`
- filter row has many small chips/buttons

PR #20 fixed pulse-bar clipping (`minHeight:32`), but the rest of Browse remains desktop-first.

Expected mobile symptom: table columns squeeze/clip, rows are hard to tap, hero cards become too narrow, filters wrap into dense clutter.

Recommended fix: mobile Browse should render stock rows as cards, not the desktop grid:

- keep desktop grid for >=768px
- mobile row card: name/code + price/change on first line; volume/turnover/alpha/industry on second line
- hero cards stack 1 column or become horizontal scroll chips
- filter controls become a compact drawer or two-row layout

### P1 — Cockpit rows are desktop flex rows

`TradeDecisionCockpit.CandRow` uses a horizontal flex row with fixed `minWidth` segments:

- status badge
- ticker `minWidth:80`
- name `minWidth:56`
- direction `minWidth:86`
- evidence tier
- blocker/catalyst as single-line ellipsis

The M1 review queue rows are also horizontal flex rows with ticker + long reason.

Expected mobile symptom: reason text is truncated, the actual "why this needs review" is hidden, and the queue becomes hard to scan.

Recommended fix: mobile Cockpit rows should stack:

- top line: ticker/name + status badge
- second line: direction/evidence/source
- third line: full blocker/reason, allowed to wrap
- larger tap target (`minHeight >= 44px`)

### P1/P2 — Topbar/search is too dense for mobile

Topbar includes search input, search button, Deep Research button, data badge, theme toggle, and language switch in one row. It has `maxWidth:480` for search but no mobile collapse.

Expected mobile symptom: topbar steals vertical space or horizontally compresses controls; key buttons are small.

Recommended fix: mobile topbar should be two rows or collapsed:

- row 1: title/current tab + language/theme
- row 2: search full width
- hide/defer Deep Research behind Research tab or overflow button

## Suggested Fix Order

1. Mobile shell fix first. If the sidebar still consumes 200px, all inner-tab fixes are partially wasted.
2. Cockpit mobile cards second. Cockpit is the canonical daily decision surface for beta/demo.
3. Browse mobile cards third. Browse is the daily market-tracking entry and likely the second most-used mobile surface.
4. Topbar/search cleanup fourth unless screenshots show it is the main blocker.

## What To Ask Junyan/Claude To Screenshot

Please capture phone screenshots for:

1. initial landing page (Browse) at load
2. Browse after pulse/filter row is visible
3. Cockpit top Human Review Queue
4. Cockpit Needs Attention rows
5. sidebar/nav state with the tab list visible

Map screenshots against the four root causes above before coding. Avoid broad redesign; this should be a mobile usability hardening PR, not a model or product-scope change.

## Validation Standard For The Fix

- `npm run build`
- source grep confirms no BUY/SELL/size language reintroduced
- desktop layout still works
- phone-width manual or browser QA at 390px:
  - no horizontal page scroll
  - primary nav reachable
  - Browse rows readable/tappable
  - Cockpit review reason readable without ellipsis hiding the main point
  - no overlapping fixed bottom bar/sidebar

## Live Phone QA Update — 2026-06-03

Tested the live site at `https://lateily.github.io/Alpha-Research/` with headless Google Chrome:

- viewport: `390x844`
- screenshot: `/private/tmp/alpha-mobile-browse.png`
- live commit: `34e30ba` (PR #23)

### Confirmed Fixed

PR #23 is live and working:

- sidebar now renders as the `56px` icon rail on phone width
- bottom status bar now starts at `left:56px`
- the original `200px` sidebar squeeze is gone

### Still Failing / Needs Next PR

The page is still not comfortably mobile-usable. The screenshot shows the main Browse content is still horizontally clipped:

- topbar search and Deep Research button are cut off to the right
- hero cards continue off-screen horizontally
- Browse table remains a desktop grid and dominates mobile width

New source-level suspicion after the screenshot: the main flex child still lacks `minWidth:0`:

- root is `display:flex`
- sidebar is now `56px`
- main container is `flex:1` but no `minWidth:0`
- wide children like the Browse table grid can force the main flex item wider than the remaining viewport, causing clipping even after the sidebar fix

Recommended next patch before deeper card work:

1. Add `minWidth:0` to the main flex child around the app content.
2. Add `minWidth:0` / `maxWidth:'100%'` discipline to the content scroll area if needed.
3. Re-test Browse at 390px.
4. Then continue with the earlier P2/P3 plan: Cockpit stacked mobile rows and Browse mobile cards.

Do not treat PR #23 as full mobile PASS. It is a correct foundational fix, but live QA shows at least one remaining P1 layout bug.
