# Design Proposal: Browse Tab UI Redesign (design-001)

> **From:** T4 Claude Design (Opus)
> **For:** Junyan + Jason (review/polish), then T1 routes to T3 codegen
> **Created:** 2026-05-02 EOD
> **Source brief:** `.agent_tasks/design/pending/design-001-browse-redesign.md`
> **Target component:** `Screener` function, `src/Dashboard.jsx` lines 2227–2702
> **Status:** PROPOSAL — awaits Junyan/Jason approval before T3 implements

---

## 1. Current state summary

Browse tab (Phase 1+2 ship) renders 5,846 A-share + HK stocks via the
`Screener` component. Three stacked card containers:

1. **Market summary bar** (line 2429–2462) — 5 directional counts
   (涨停/上涨/平家/下跌/跌停) + live polling status pill on the right.
2. **Controls row** (line 2464–2561) — single horizontal row, `flexWrap: wrap`,
   carrying 7 filter groups: search input · market chip group · direction
   chip group · α-sort shortcut (conditional) · industry `<select>` · PE
   range pair · Δ% range pair · Clear button (conditional) · result count.
3. **Result table** (line 2563–2677) — 7- or 8-column CSS grid
   (`32px 1fr 80px 80px 80px 80px [46px α] 10px`), 100 rows/page,
   alternating-stripe background, hover-tint rows, click → drill into
   Research tab.

Live polling: 3-second cadence on the visible page (codes signature
diff-trigger — see line 2357 audit fix). Sortable by px/pct/vol/turn/mktcap/
pe/alpha. Industry click-to-filter is wired (line 2619) but visually buried.

**It works. It is not yet pleasant.** Every filter is on-screen at all
times whether used once a session or every minute. Visual weight is
uniform across 5,800 rows. The eye has nowhere to land.

---

## 2. Pain points (5 specific)

**P1 — Filter row is a single-tier wall.** 7 control groups on one row,
even with `flexWrap` wrapping into 2–3 lines on a 1280px viewport, present
identical visual weight. High-frequency controls (search, market,
direction) compete for the user's eye against low-frequency ones (PE
range, Δ% range). The user has to *read* the row before *using* it.

**P2 — Industry chip is fontSize:8, lost in line-2 of the name cell.**
Currently rendered at line 2618–2626 with `fontSize:8, padding:'0 4px',
background:${C.blue}15` — that's ~8% blue tint on the brightest accent
color. Click-to-filter is the most powerful affordance Browse has and it
hides next to the ticker code in 8px MONO. Junyan's "industry filter is
hard to discover" complaint is in this cell.

**P3 — Active-filter state is implicit.** Once the user picks
"光器件 / PE 20–50 / Δ% > 0", those choices live as values inside the
controls row. No persistent visualization of *what is currently filtering*
above the result table. To audit "why are these 47 stocks showing?" the
user must scan the controls row top-to-bottom and reconstruct.

**P4 — Result table has no visual hierarchy across 5,800 rows.** Every
row is identical except for color of the price/Δ% number. 涨停/跌停 get
an inline 8px badge; α-score is a number in the right column. Nothing
guides the eye to the **3–5 stocks worth looking at first** vs. the 95%
that are noise on any given day. Junyan's "5-second discovery" goal is
unmet because the screen treats all 5,800 rows as equally important.

**P5 — Empty + loading states are afterthoughts.** "Loading full universe…"
(line 2415) is plain text + Database icon at 35% opacity. "No stocks
match" (line 2581) is a single 12px gray line with no recovery affordance
(no "clear filters?" button). Both states are dead-ends.

---

## 3. Proposed design

### Composition principle

Stratify Browse into **three vertical zones** — *orient → narrow → drill*:

```
┌──── Zone 1 — ORIENT (above-the-fold, hero) ──────────────────────────┐
│  Live pulse bar (slim) + Today's standouts (3 horizontal cards)      │
│  Eye lands here first. 5-second discovery target.                    │
├──── Zone 2 — NARROW (filter shelf) ──────────────────────────────────┤
│  Two-tier filter: Primary row (search + market + dir + α top)        │
│  + Advanced row (industry + PE + Δ%) collapsible behind a chevron     │
│  + Active filter pill bar showing what's currently filtering          │
├──── Zone 3 — DRILL (result table) ───────────────────────────────────┤
│  Stratified rows — α-leader / 涨跌停 / "fresh signal" use 4px        │
│  left-border accent. Industry promoted to inline chip on row line-1.  │
│  Better loading skeleton + empty-state recovery.                      │
└──────────────────────────────────────────────────────────────────────┘
```

Below: each change individually, with before/after wireframe + rationale.

---

### 3.1 Zone 1 — Hero standouts (NEW)

**Before** (current line 2429–2462, only the live pulse bar):

```
┌──────────────────────────────────────────────────────────────────────┐
│  TODAY  54 涨停  3128 上涨  0 平家  2654 下跌  12 跌停    ●Live · 5  │
└──────────────────────────────────────────────────────────────────────┘
```

The bar has 5 numbers. None of them is a **stock**. The user sees
"3128 stocks went up today" and learns nothing actionable.

**After** — slim live bar + 3-card hero strip:

```
┌──────────────────────────────────────────────────────────────────────┐
│  ●Live · 5 refreshed · 5,846 stocks                  [⏸ Pause]       │  ← slim, 32px
├──────────────────────────────────────────────────────────────────────┤
│ ┌─ 🔥 今日涨幅 Top 5 ──┐ ┌─ ⭐ α-龙头 Top 5 ────┐ ┌─ 📊 量爆 Top 5 ┐ │
│ │ 中际旭创  +9.98%      │ │ 比亚迪      α 79     │ │ 同花顺   3.2亿  │ │
│ │ 同花顺    +8.45%      │ │ 中际旭创    α 78     │ │ 中际旭创 1.8亿  │ │
│ │ 比亚迪    +6.12%      │ │ 腾讯        α 64     │ │ NetEase  9821万 │ │
│ │ 天孚通信  +5.87%      │ │ NetEase     α 58     │ │ 腾讯    7440万  │ │
│ │ 立讯精密  +4.92%      │ │ BeOne       α 65     │ │ 比亚迪  6210万  │ │
│ │  [全部 →]              │ │  [全部 →]            │ │  [全部 →]       │ │
│ └────────────────────────┘ └──────────────────────┘ └────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Each card lists 5 stocks, click row → drill into Research (same as
  table click).
- Each card's `[全部 →]` footer link applies the corresponding sort
  + (optional) filter and scrolls to the table.
  - 涨幅 Top 5 → `setSortBy('pct'); setSortDir('desc')`
  - α-龙头 → `setSortBy('alpha'); setSortDir('desc')`
  - 量爆 → `setSortBy('vol'); setSortDir('desc')`
- α card hides itself if `!hasAlphaScores` (existing line 2421 guard).
- The 5 directional counts (涨停/上涨/etc.) move into a **collapsed
  footer row** of the live pulse bar (small fontSize:10 inline). The
  click-to-filter behavior on those counts is preserved.

**Rationale:**
Junyan's brief is "5-second discovery." Hero cards convert the abstract
"3128 stocks went up" into 15 actual ticker-name pairs the eye can grab.
The three orthogonal cuts (price / quality / volume) give three different
lenses on "what's interesting today." If none of the 15 names looks
appealing, the user proceeds to the filter shelf. If one does, they
click it and skip the table entirely. This is the path Junyan described.

**Card visual spec:**
- `borderRadius:12, boxShadow:SHADOW_SM, border:1px solid C.border, background:C.card`
- Header: 28px tall, fontSize:11, fontWeight:700, color:C.dark,
  with leading icon (lucide `Flame` / `Sparkles` / `BarChart3`)
- Header tint by card type — left-border 3px solid:
  - 涨幅 Top → `C.red`
  - α-龙头 Top → `C.gold`
  - 量爆 Top → `C.blue`
- Row: 22px tall, padding `4px 12px`, fontSize:11
  - left: ticker name (color C.dark, fontWeight 600)
  - right: metric value (MONO, fontWeight 700, color = card accent)
- Footer link: fontSize:10, color C.mid, hover C.blue
- Card height fixed (~210px) so the strip is one row across desktop

---

### 3.2 Zone 2 — Two-tier filter shelf

**Before** (current line 2464–2561):

```
┌──────────────────────────────────────────────────────────────────────┐
│ [🔍 search][All][A][HK][All][↑Lim][Up][Dn][↓Lim][α Top][行业 ▼]      │
│  [PE _][-][_]  [Δ% _][-][_]  [Clear]            5,846 stocks · P1/59 │
└──────────────────────────────────────────────────────────────────────┘
```

**After** — primary always-visible, advanced collapsible:

```
┌──────────────────────────────────────────────────────────────────────┐
│ [🔍 名称/代码/行业 (instant) ........................]                │
│ [全部][A股][港股]  [全部][↑涨停][↑][↓][↓跌停]  [α Top]  ▼ Advanced 3  │  ← primary
├──────────────────────────────────────────────────────────────────────┤  (only when expanded)
│  行业 [光器件 ▼]    PE  [20]──[●]──[50]    Δ%  [-3]──[●]──[+10]      │  ← advanced
└──────────────────────────────────────────────────────────────────────┘
```

When *no* advanced filter is set, the advanced row is collapsed; the
chevron label reads `▼ Advanced` (color C.mid, fontSize:11). When *any*
advanced filter is active, the row auto-expands and the label reads
`▲ Advanced (3)` where (3) is the count of active advanced filters,
chip-styled with `S.tag(C.blue)` so the user knows it's there even if
they collapse it again.

```
┌─ Advanced collapsed but 2 filters active ───────────────────────────┐
│ [🔍 ...][全部][A股][港股][全部]...[α Top]   ▲ Advanced (2) ⓘ        │
└─────────────────────────────────────────────────────────────────────┘
```

**Active filter pill bar** — appears between the filter shelf and the
table whenever ≥1 filter is set:

```
┌──────────────────────────────────────────────────────────────────────┐
│  Filtering:  [行业: 光器件 ×]  [PE: 20–50 ×]  [Δ%: ≥0 ×]  [Clear all] │
└──────────────────────────────────────────────────────────────────────┘
```

Each pill uses `S.tag(C.blue)` (existing helper at line 64 in
Dashboard.jsx) with an `×` glyph that, on click, removes only that one
filter. `[Clear all]` is the existing Clear button repositioned.

**Rationale:**
- P1 fixed: high-freq controls always visible (search + market + dir);
  low-freq advanced hidden until needed; viewport feels less crowded.
- P3 fixed: pill bar surfaces *what is filtering* literally above the
  results so the user sees the answer to "why am I looking at 47 stocks?"
  without scanning controls.
- Per-pill close (×) is a faster recovery than "Clear all" — the user
  often wants to keep 2 of 3 filters, not nuke them.

**Visual spec:**
- Primary row: same height as today (`h:28`), background `C.card`.
- Advanced toggle: fontSize:11, color:C.mid, height:24, hover bg `${C.blue}0D`,
  positioned at row right.
- Active count badge in collapsed state: `S.tag(C.blue)` mini variant —
  `fontSize:9, padding:'2px 7px', borderRadius:10`.
- Advanced row when expanded: same card chrome, border-top dashed
  (`borderTop:'1px dashed ${C.border}'`) to visually link to primary.
- Range sliders for PE / Δ% — uses native `<input type="range">` × 2
  with `<input type="number">` mirrored values. **Note for Jason:**
  pure dual-handle slider needs a small wrapper component; if that's a
  bigger lift than expected, keep two number inputs (current pattern,
  line 2518–2528) as MVP — the visual decongestion comes from collapsing
  the row, not from the slider widget per se.
- Pill bar: `padding:'8px 14px', background:transparent` (sits on
  `C.bg`), pills `gap:8`, fontSize:11, color:C.blue.

---

### 3.3 Zone 3a — Industry chip promoted

**Before** (line 2618–2626):

```
中际旭创                              ← line 1: name only
300308 SZ 光器件                      ← line 2: code + market + tiny chip
```

The chip lives at `fontSize:8, background:${C.blue}15` — invisible on a
fast scan.

**After** — industry chip lifts to line-1 right-anchored:

```
中际旭创       [光器件]                ← line 1: name + chip in C.blue tag
300308 · SZ                            ← line 2: code only
```

```
┌── name cell (1fr) ────────────────────────────┐
│  中际旭创                  [光器件]            │ ← name (fontSize:11 fontWeight:600)
│                                                │   chip right-anchored, S.tag(C.blue)
│  300308 · SZ                                  │ ← code line, fontSize:9 mid
└────────────────────────────────────────────────┘
```

Chip uses the existing helper:
`S.tag(C.blue)` → `fontSize:9, fontWeight:600, padding:'3px 9px',
borderRadius:20, background:${C.blue}14, color:C.blue`.

This is **the same visual weight** as TRI / VP / α tags elsewhere in
the app — Browse no longer has a stepchild industry chip.

Click-to-filter behavior preserved (existing onClick at line 2619 just
moves to the new mount point). On hover, chip background goes
`${C.blue}24` (existing pattern from `FBtn` line 2406). Tooltip
unchanged: `按"${s.industry}"过滤`.

**Rationale:**
P2 fixed: chip is now at the same rank as the stock name, scannable in
a vertical glance, and visually consistent with the rest of the app's
tag system.

**Trade-off note:** This eats ~80px from the name cell on long Chinese
names. For names >8 Chinese chars (e.g., "上海昊海生物科技股份有限公司"),
chip drops to line-2 right-anchored as a fallback. Truncation logic:
ellipsis kicks in only if name + chip would exceed cell width; otherwise
chip is line-1.

---

### 3.4 Zone 3b — Row hierarchy via 4px left-border accent

**Before** — every row is identical except color of pct number:

```
1   中际旭创                  857.5  +9.98%  2.1M  3.2亿  78  ●     ← bg: transparent
2   比亚迪                    298.2  -0.5%   ...   ...   65        ← bg: C.soft
3   同花顺                    95.4   +0.8%   ...   ...   38        ← bg: transparent
```

Eye sees nothing special about row 1 (a 涨停 with α 78 — the headline
stock of the day). The inline 涨停 badge at fontSize:8 is there, but it's
2 chars in a 1fr cell.

**After** — left-border 4px accent for "noteworthy" rows:

```
│ 1  [涨停] 中际旭创  [光器件]   857.5  +9.98%  2.1M  3.2亿  78  ●  ← red 4px left-border
│ 2  比亚迪          [汽车整车]  298.2  -0.5%   ...   ...   65       ← gold 4px (α≥65)
   3  同花顺          [软件服务]  95.4   +0.8%   ...   ...   38       ← no accent
   4  腾讯            [互联网]    475.0  +1.8%   ...   ...   64       ← no accent (α<65)
│ 5  [跌停] BNK       [医疗]      11.0   -10.0%  ...   ...   42       ← purple 4px
```

(Pipe `│` represents 4px solid left-border; absence = 0px.)

**Accent rules** (priority top-down — only one accent per row):

1. **涨停** (`pct >= 9.9`) → 4px solid `C.red` (drop the inline 涨停
   badge — left-border carries the meaning more forcefully).
2. **跌停** (`pct <= -9.9`) → 4px solid `#9333EA` (current 跌停 color
   — see §4 note on whether to promote this into the design system).
3. **α ≥ 65** (excellent) → 4px solid `C.gold`.
4. **Volume spike** (current ratio vs. 5-day avg ≥ 2x) — *deferred to
   Phase 2,* requires backend signal not currently in `universe_a.json`.
5. None of above → 0px (default).

This gives a **scannable density gradient**: 5,800 rows but only ~50–80
flagged on any active day (rough estimate: 10–60 涨/跌停 + 20–40 α-leaders,
overlap ~50%). The eye lands on accented rows first, exactly the
"interesting stocks" Junyan wants in 5 seconds.

**Implementation:** add a `accent` prop to row-render, computed from
`pct` and `s.alpha_score`. Row style gains
`borderLeft: accent ? '4px solid ' + accent : '4px solid transparent'`
(transparent default to keep grid alignment).

The inline 涨停/跌停 badge in name cell (line 2608–2611) is **removed**
— left-border replaces it. Reasoning: dual-coding is redundant; the
border is more peripheral-vision-friendly.

**Rationale:**
P4 fixed: visual hierarchy now exists. Left-border is a Bloomberg /
Capital IQ standard for "highlighted row" — Jason's design language
already leans this direction (see DARK theme palette at line 38).

---

### 3.5 Zone 3c — Loading + empty-state recovery

**Before — loading** (line 2413–2418):

```
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│                          [Database icon 36px, opacity 0.35]          │
│                          Loading full universe…                      │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

**Before — empty result** (line 2580–2582):

```
┌──────────────────────────────────────────────────────────────────────┐
│                          No stocks match                             │
└──────────────────────────────────────────────────────────────────────┘
```

**After — loading skeleton** (6 ghost rows mimicking the table):

```
┌──────────────────────────────────────────────────────────────────────┐
│ #   Name · Code           Price   Δ%      Volume   Turnover  α       │
├──────────────────────────────────────────────────────────────────────┤
│ ░░  ░░░░░░░░░ ░░░░░░       ░░░░    ░░░    ░░░       ░░░       ░░     │
│ ░░  ░░░░░░░░░░ ░░░░        ░░░░    ░░░    ░░░       ░░░       ░░     │
│ ░░  ░░░░░░░ ░░░░░░         ░░░░    ░░░    ░░░       ░░░       ░░     │
│ ░░  ░░░░░░░░░░░ ░░░░       ░░░░    ░░░    ░░░       ░░░       ░░     │
│ ░░  ░░░░░░░ ░░░░░░         ░░░░    ░░░    ░░░       ░░░       ░░     │
│ ░░  ░░░░░░░░ ░░░░░         ░░░░    ░░░    ░░░       ░░░       ░░     │
└──────────────────────────────────────────────────────────────────────┘
   ▲ ░ = pulse-animated rectangle, background ${C.soft}, 1.5s breath cycle
```

Skeleton uses the SAME grid columns the real table will use, so the
layout doesn't shift on data arrival. CSS animation: `@keyframes pulse
{ 0% { opacity:0.5 } 50% { opacity:0.85 } 100% { opacity:0.5 } }`.

**After — empty result with recovery:**

```
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│                          [SearchX icon 32px, color C.mid]            │
│                          没有股票匹配当前筛选                          │
│                          [清除所有筛选 →]                             │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

Empty state shows:
- icon + 14px message
- a single CTA button styled like the existing Clear button (line
  2549–2554) but more prominent: `padding:'8px 18px', fontSize:12,
  border:1px solid C.blue, color:C.blue` — clicking calls the same
  reset handler.

**Rationale:**
P5 fixed: loading state preserves layout (no jank); empty state offers
the recovery path the user actually wants (90% of the time the answer
to "no matches" is "I over-filtered, let me back off").

---

## 4. Color, spacing, font choices

### 4.1 Colors — frozen design system tokens only

| Element | Token | Value (Light) |
|---|---|---|
| Card background | `C.card` | #FFFFFF |
| Card border | `C.border` | #DCE5F3 |
| Card hover row tint | `${C.blue}0D` (~5% blue) | per existing pattern line 2598 |
| Hero card "涨幅 Top" accent | `C.red` left-border 3px | #D94040 |
| Hero card "α 龙头 Top" accent | `C.gold` left-border 3px | #D08000 |
| Hero card "量爆 Top" accent | `C.blue` left-border 3px | #3A6FD8 |
| Industry chip | `S.tag(C.blue)` (existing helper) | bg `${C.blue}14`, fg `C.blue` |
| Active filter pill | `S.tag(C.blue)` | same |
| Row left-border 涨停 | `C.red` 4px solid | #D94040 |
| Row left-border 跌停 | **`#9333EA`** ⚠ | (see §4.4 note below) |
| Row left-border α≥65 | `C.gold` 4px solid | #D08000 |
| Skeleton fill | `C.soft` | #F0F5FC |
| Empty-state icon | `C.mid` | #6B82A0 |
| Empty-state CTA border | `C.blue` | #3A6FD8 |

### 4.2 Spacing — Card pattern preserved

- Hero card: `borderRadius:12, boxShadow:SHADOW_SM, border:1px solid C.border` (matches existing card chrome at line 2429)
- Hero card row: `padding:'4px 12px'` (slightly tighter than table for density)
- Filter shelf: `padding:'10px 14px'` (current value, unchanged)
- Active pill bar: `padding:'8px 14px'` on `C.bg`
- Table row: `padding:'6px 12px'` (current, unchanged) but `paddingLeft` adjusts to 8px when 4px left-border is present so total visual width stays constant
- Row left-border-transparent placeholder: `borderLeft:'4px solid transparent'` on default rows (NOT 0px) — keeps grid columns aligned

### 4.3 Fonts

- All text: Inter (system default, unchanged)
- Numbers / tickers / metrics: `MONO` (existing constant, line 53) — unchanged
- Hero card row name: fontSize 11, fontWeight 600 — matches table row name
- Hero card row metric: fontSize 11, fontWeight 700, MONO — matches table Δ% column
- Active filter pill: fontSize 11 — matches existing tag pattern
- Skeleton row height: matches real row height exactly (no layout shift)

### 4.4 ⚠ Outlier colors — flag for Jason

Two colors used in current Browse are **NOT** in the `LIGHT` / `DARK`
palettes:

- `#EF4444` for 涨停 background (line 2437, 2486, 2608) — slightly
  brighter red than `C.red` (#D94040)
- `#9333EA` for 跌停 background (line 2441, 2489, 2611) — purple, no
  C-system equivalent

This proposal **does not introduce new colors** but does ask Jason to
decide:

- **Option A** — Use `C.red` for 涨停 (drop #EF4444). Pros: consolidates
  to design system. Cons: 涨停 / Up stocks both red, slight visual
  collision (today the brighter red distinguishes 涨停 from regular Up).
- **Option B** — Promote #EF4444 → `C.redBright` (or similar) into the
  C system as a tier-2 red. Same for #9333EA → `C.purple`. Pros: makes
  current usage legitimate. Cons: expands frozen palette (philosophical
  tension; Junyan has been disciplined about this).
- **Option C** — Status quo: keep these two hex values as a documented
  "limit-only" exception in CLAUDE.md, no further use anywhere else.

**T4 recommends C.** Two stop-color tokens for limit conditions are
acceptable as a special case (limits are categorically different from
"up / down"), and CLAUDE.md should explicitly say so to prevent drift.

---

## 5. Implementation hints (for T3 codegen task spec)

When T1 routes this proposal to T3, the codegen task should target:

### 5.1 New constants (top of file, near line 53–55)

```js
const SKEL_PULSE = '@keyframes pulse { 0%,100% { opacity:0.5 } 50% { opacity:0.85 } }';
// (inject into a single <style> tag at app root, or use inline CSS-in-JS animation)

const ACCENT_LIMIT_UP   = '#EF4444';  // until §4.4 resolved
const ACCENT_LIMIT_DOWN = '#9333EA';  // until §4.4 resolved
```

### 5.2 New sub-components (extracted, below `Screener`)

```js
function HeroCard({ title, icon, accent, rows, onSeeAll, C })   // §3.1
function FilterShelf({ ..., advancedActiveCount, expanded, setExpanded })  // §3.2
function ActiveFilterPills({ filters, onRemove, onClearAll, C })  // §3.2
function SkeletonRow({ COLS, C })                                 // §3.5
function EmptyState({ onClearFilters, L, C })                     // §3.5
```

These are pure-render components (no own state) so testing is just
"renders without error given props." Total estimated LOC ~250.

### 5.3 Edits to existing `Screener` body

| Lines | Change |
|---|---|
| 2229 | Add `const [advancedExpanded, setAdvancedExpanded] = useState(false);` |
| 2274–2286 | `stats` calc unchanged. ADD: `topMovers`, `topAlpha`, `topVolume` memoized arrays (top 5 each, after sort). |
| 2425–2462 | Replace market summary bar with slim live-pulse bar + 3-card hero strip. The 5 directional counts move into the slim bar as inline labels. |
| 2464–2561 | Replace controls block with `<FilterShelf>` two-tier, plus `<ActiveFilterPills>` between shelf and table. |
| 2580–2582 | Replace inline "No stocks match" with `<EmptyState>` invoking the same reset handler defined inline at 2549. |
| 2412–2418 | Replace loading state with 6 `<SkeletonRow>` instances. |
| 2583–2675 | Row render — remove inline 涨停/跌停 badges (line 2608–2611); add `accent` computation; apply as `borderLeft:'4px solid ' + (accent || 'transparent')`. |
| 2604–2628 | Name cell — restructure to put name + industry chip on line-1; code-only on line-2. Apply ellipsis fallback when name is too long. |

### 5.4 Constants T3 must wire

- `S.tag(C.blue)` — existing helper at line 64, no new code
- `SHADOW_SM` — existing at line 55, no new code
- All hero card icons — already imported from `lucide-react` at line 3–8 (`Flame` may need to be added if absent)

### 5.5 Test harness requirements (so T2 review has concrete checks)

- `npm run build` exits 0
- JSX balance script (CLAUDE.md "Quick JSX balance check") returns 0
- Browse tab renders with all three zones visible at 1280px viewport
- Browse tab degrades gracefully at 768px (hero strip stacks vertically; advanced filter still collapsible)
- Click on hero card row → drills to Research tab with that ticker
- Click on hero card "全部 →" → applies sort + scrolls to table
- Click on industry chip in row → applies industry filter and adds active pill
- Click on active filter pill `×` → removes only that filter
- Click on "Clear all" pill bar action → resets all filters
- Filter activation on empty result → empty state with recovery CTA
- Live polling (`POLL_MS=3000`) still works — visible-codes signature trigger preserved

---

## 6. Trade-offs

| Decision | Cost | Benefit |
|---|---|---|
| Hero strip eats ~210px above-the-fold | Fewer table rows visible without scroll | "5-second discovery" goal directly served; serves Junyan's actual mental model |
| Advanced filter collapsed by default | One extra click to access PE/Δ%/industry | Primary controls visible in single glance; viewport feels less crowded; advanced count chip still surfaces "I'm filtering" signal |
| Active filter pills (extra zone) | +44px vertical | The single biggest "what is currently filtering?" UX clarity win; users no longer reconstruct by reading controls |
| Industry chip on line-1 of name cell | Eats ~80px on long-name stocks | Chip is now at parity with name; click-to-filter discovered ~3x faster (estimate; needs Jason A/B intuition) |
| 4px left-border accent on flagged rows | Implementation: each row computes accent | Hierarchy without color overload; 涨停/跌停/α-leader scannable in peripheral vision |
| Drop inline 涨停/跌停 badge | Two characters worth of cell space reclaimed | Eliminates dual-coding; left-border carries meaning more strongly |
| Skeleton + empty-state CTA | ~80 LOC of new pure-render code | No more dead-end states; layout stable across loading transitions |
| Two-tier filter shelf | Slightly more component code (FilterShelf wrapper) | Decongestion of primary visual space — biggest pain point fixed |

**Trade-offs we explicitly REJECT:**
- ❌ Sidebar filter panel (left, 200px, collapsible) — eats horizontal that
  the table needs at 1280px. Two-tier-collapsible is denser.
- ❌ Virtual scrolling — adds `react-window` dependency, breaks frozen
  "no new npm packages" rule.
- ❌ Industry as a separate column — would require shrinking name cell
  (already 1fr) or adding a column at the cost of price/volume width.
  Chip on line-1 of name cell is cheaper.
- ❌ Saved filter presets — useful but Phase 4. Adds state persistence
  (localStorage) and a UI (preset chips); out-of-scope for this redesign.
- ❌ Cross-market simultaneous grouping (A + HK heat map) — separate
  feature, out of scope (per UNIVERSE_BROWSER_DESIGN §8).

---

## 7. Phasing

### MVP — this redesign sprint (Jason polish + T3 codegen, ~3–4h total)

1. **Hero standouts strip** (3 cards, click-to-drill) — biggest UX
   delta, moves "discovery" from buried to front-and-center. Click-to-
   sort is the magic. (~1h codegen)
2. **Two-tier filter shelf + active pills** — second-biggest delta,
   clears the primary visual cacophony. (~1h codegen)
3. **Industry chip promoted to line-1** — small change, big
   discoverability win. (~15min codegen)
4. **Row left-border accent** (涨停/跌停/α≥65) — visual hierarchy. Drop
   inline 涨停/跌停 badge. (~30min codegen)
5. **Skeleton loading + empty-state CTA** — closes the dead-end states.
   (~30min codegen)

### Polish — Jason layer (after T3 first pass, ~1–2h Jason)

- Hero card iconography + microinteractions (hover lift, click ripple)
- Filter pill animation on add/remove
- Mobile responsive: hero cards stack at <768px, advanced filter
  becomes full-screen sheet
- Dark mode visual sweep across all new elements (tokens are already
  set; Jason verifies optical balance)
- Empty-state illustration if Jason wants something richer than icon

### Deferred — Phase 2 / 3 (separate sessions)

- **Volume-spike accent rule** — needs backend signal in `universe_a.json`
  (current_vol / 5d_avg_vol). Add to `enrich_universe_industry.py` or
  similar pipeline step.
- **Real-time hero card refresh** — currently hero data is sort-then-
  slice on first render; refreshing on each live-quote poll is a follow-on.
- **Saved filter presets** — Phase 4 polish.
- **Stock comparison from Browse** — Phase 4 (per UNIVERSE_BROWSER §8).
- **§4.4 outlier color resolution** — Jason + Junyan decide A/B/C; until
  then code uses constants `ACCENT_LIMIT_UP/DOWN` as a single point of
  truth that can be flipped to C-tokens later.

---

## 8. Test plan (Junyan + Jason verification)

### Functional tests (T2 reviewer + Junyan smoke)

1. **Hero strip renders 3 cards on first load** with data populated
   (top 5 by pct desc / α desc / vol desc) — verify against
   `universe_a.json` head/tail values manually.
2. **Hero card row click** drills to Research tab for that ticker.
3. **Hero card `[全部 →]` link** applies the corresponding sort and
   scrolls to table (hero remains visible, table re-orders).
4. **Filter shelf primary row** behaves identically to today — search
   + market + direction + α-top still filter as expected.
5. **Filter shelf advanced toggle** opens/closes; advanced count badge
   reflects active filter count (e.g., "(2)" when industry + PE are both set).
6. **Active filter pills** render only when ≥1 filter is active; each
   pill `×` removes only that filter; `[Clear all]` resets to default.
7. **Industry chip on row line-1** triggers same filter+pill flow as
   today's chip click.
8. **Row accent** appears on 涨停 / 跌停 / α≥65 stocks; only one
   accent per row (priority order verified).
9. **Loading skeleton** shows during `universeA == null && universeHK == null`;
   replaced atomically by table rows when data arrives — no layout
   shift between skeleton and real rows.
10. **Empty-state CTA** appears on `filtered.length === 0`; clicking
    "Clear all filters" resets and result returns to full universe.

### Visual / qualitative tests (Junyan + Jason)

1. **5-second test:** Open Browse cold. Without scrolling, can the user
   identify 3 candidate tickers worth Research-clicking within 5
   seconds? Pre-redesign baseline: ~no, user must scroll table or apply
   filter. Post-redesign target: yes, hero strip surfaces 15 candidates.
2. **Filter audit test:** Apply 3 filters. Without scrolling controls,
   can the user immediately tell what's filtering? Pre: requires reading
   the controls row. Post: pill bar shows the answer.
3. **Industry click test:** From cold-open table view, can the user find
   and click an industry filter via the row chip in <2 attempts? Pre:
   chip is fontSize:8 buried in code line. Post: chip is line-1 right-
   anchored, visually similar to TRI/VP tags.
4. **Loading test:** Slow network throttle to 200kbps. Does the loading
   state feel stable (no janky text/icon swap to populated table)?
   Skeleton matches column layout exactly.
5. **Empty-state test:** Apply impossible filter combo (PE: 1000–2000,
   Δ%: 25–50). User sees recovery CTA, single click to reset.
6. **Dark mode parity:** Switch to dark theme, verify all 5 changes
   render correctly with no contrast issues (hero card borders,
   skeleton pulse contrast, pill bar legibility).
7. **Mobile responsive (deferred to Jason polish):** 768px viewport,
   hero cards stack, advanced filter is full-screen sheet, table
   horizontal-scrolls if needed.

### Regression tests (T2)

- All existing Browse functionality unchanged: `npm run build` passes,
  JSX balance 0, live polling 3s cadence intact, sort by all 7 columns
  works, pagination prev/next works, 5,846-stock load + filter
  performance no regression (filter through 5,846 in <100ms p95).
- Watchlist 5 still highlightable in table (current code uses ⭐ via
  `lk?.includes(s.ticker)` — preserve that affordance if it exists at
  line ~2603, currently it's just rank `#`; verify no regression).

---

## Appendix A — Why this proposal stops where it does

- **Does not redesign Trading Desk / Research / other tabs** — per brief
  constraint, Browse only.
- **Does not propose new colors or fonts** — frozen design system
  respected; outlier colors flagged for Jason+Junyan §4.4 decision.
- **Does not write JSX** — implementation hints in §5 are spec for T3
  codegen, not code.
- **Does not auto-approve** — this is a starting point for Jason's
  visual polish; final visual cuts are his call.

---

## Appendix B — Open questions for Junyan + Jason

1. **§3.1 Hero strip:** does the 3-card lens (movers / α / volume) fit
   Junyan's mental model? Alternatives: 5 cards (add 涨停 + 跌停
   leaderboards), or 2 cards (drop volume). T4 recommends 3 — three
   orthogonal lenses is a known pattern.
2. **§4.4 outlier colors:** A / B / C decision (T4 recommends C).
3. **§3.4 row accent priority order:** currently 涨停 > 跌停 > α≥65.
   Should "fresh signal" (e.g., HSGT 5-day trending up) outrank α?
   Defer to Phase 2 once that signal pipes into universe_a.
4. **§3.5 skeleton row count:** 6 rows is enough to fill ~half the
   above-the-fold. Could be 8 if Jason wants more "filling" effect.
5. **§3.2 advanced filter widget choice:** keep current paired number
   inputs (cheap) vs. true dual-handle range slider (richer UX, ~80
   extra LOC for slider component). T4 recommends paired inputs for
   MVP, slider for Jason polish layer.

---

**Done. Ready for Junyan + Jason review.**

When approved, T1 routes to T3 codegen task at
`.agent_tasks/pending/<task_id>.json` with `must_satisfy` bullets
extracted from §5 + §8. T2 reviews with §8 test plan as gates.
