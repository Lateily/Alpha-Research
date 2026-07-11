# Design Proposal: PriceChart polish — K-line + Intraday (design-002)

> **From:** T4 Claude Design (Opus)
> **For:** T1 design-quality gate → T3 codegen → ship
> **Created:** 2026-05-03
> **Source:** Self-initiated audit per Junyan 2026-05-02 directive
> ("每一处新功能展示在 platform 上由 T4 负责，直接 push")
> **Target component:** `PriceChart` function, `src/Dashboard.jsx` lines 962–1409
> **Scope:** Retrospective polish review — K-line indicator chips, interval
> selector, tier-locked banner, and Intraday (分时) mode (all four shipped
> across `5c91f02` → `9f5fde9`). All recommendations target a follow-on
> polish sprint, not pre-ship gating.
> **Status:** Self-iterated 2 rounds, ready for T1 gate

---

## 1. Current state summary

`PriceChart` is a stacked-card chart component used in the Research drill view.
Three feature waves have landed (or are landing):

| Wave | Commits | What |
|---|---|---|
| K-line v5 multi-timeframe | `5c91f02` | API supports 1m/5m/15m/30m/60m + 1d/1w/1mo intervals |
| Interval selector + tier-lock UI | `244c32c` | Gold-styled minute chips above the blue range chips; gold banner when minute interval requires Tushare 15000 tier |
| 8-indicator suite + 3 subplots | `bfae539` | MA(5/10/20/60) + Bollinger overlays on main chart; MACD/KDJ/RSI subplots toggleable |
| Intraday (分时) mode | `9f5fde9` | Red `[分时]` button in header; close-line + cumulative-avg line; tick-colored volume bars |

Layout today (full-loaded, all subplots on, K-line mode):

```
┌─ Card ─────────────────────────────────────────────────────────────┐
│ Header (price + 4 stats | view/interval/range/refresh + timestamp) │ ~70px
├────────────────────────────────────────────────────────────────────┤
│ Indicator chips: MA5 MA10 MA20 MA60 BOLL MACD KDJ RSI              │ ~26px
├────────────────────────────────────────────────────────────────────┤
│ Main chart (close + MA overlays + Bollinger bands + prev_close ref)│ 180px
├────────────────────────────────────────────────────────────────────┤
│ Volume bars                                                         │ 40px
├────────────────────────────────────────────────────────────────────┤
│ MACD subplot (hist + line + signal)                                 │ 70px
│ KDJ subplot (3 lines on 0–100)                                      │ 70px
│ RSI subplot (1 line + 70/30 reference)                              │ 70px
└────────────────────────────────────────────────────────────────────┘
                                                          ≈ 526px total
```

Default state (BOLL + MACD on, KDJ + RSI off): ~366px. On a 768px laptop
screen (Junyan's stated dev env), one stock's PriceChart consumes ~48% of
the visible viewport before the user scrolls. K-line mode is dense by
design; the audit below targets *visual hygiene* and *information
architecture*, not feature scope.

Intraday mode (`viewMode === 'fenshi'`) replaces the K-line main chart
with a 2-line chart (close + cumulative avg) and recolors volume bars by
tick direction. It currently shares the indicator-chips row, range-chips
row, and all subplot toggles with K-line mode — but those are hidden
when in 分时 because the code gates them on `viewMode === 'kline'`.

---

## 2. Pain points (7 specific)

**P1 — Color semantics broken: `[分时]` button uses `C.red`.**
Line 1180 sets `background: viewMode==='fenshi' ? C.red : 'transparent'`
and `border: 1px solid C.red` when active. `C.red` (#D94040) is the
frozen system's "danger / down" token. A stock that's down +0% gets a
red price number on line 1141; a button next to it that means "show me
the intraday view" also being red collides semantically. Worse, when the
stock is up (+1.2%), the right side of the header has the red 分时
button and the green pct number side by side — the eye reads "warning"
where there is none.

**P2 — Three chip groups on three rows compete for visual weight.**
Header right column stacks:
- Row A: `[分时][1m 5m 15m 30m 60m 日 周 月]` (9 chips, fontSize:9, gap:6)
- Row B: `[1d 5d 1mo 3mo 1y][↻]` (6 chips, fontSize:10, gap:3)
- Row C: `Updated 14:32 · auto` (8px text)

Three rows × ~9 elements per row = 27 micro-controls in <120px vertical
space. The user has to learn which group does what (interval = K-line
period; range = window; 分时 = mode toggle) without visual grouping
beyond color (gold = interval, blue = range, red = mode). Color is doing
the entire wayfinding job and is overloaded.

**P3 — Indicator chip color overload.**
8 chips with 5 different active colors:
- MA5 / KDJ → C.gold
- MA10 / MACD / RSI → C.blue
- MA20 → C.green
- MA60 → C.red
- BOLL → C.dark

This collides with: interval-active = C.gold (chip group A), range-active
= C.blue (group B), `[分时]` active = C.red, price-up = C.green,
price-down = C.red. Six places use C.red across the component, four use
C.gold. A user can't tell at-a-glance whether "the gold thing" is
"highlighted MA5" or "selected interval" or "MACD signal line."

**P4 — Subplot stack consumes vertical without payoff.**
MACD + KDJ + RSI default OFF for KDJ/RSI but ON for MACD. So default
total height = 366px. Three subplots opened = 526px. On a 768px laptop
viewport, this is the entire screen — the user can see *one stock* and
nothing else. Subplots are also visually identical at a glance (all
70px, all line charts) — eye can't quickly tell which one it's looking
at without reading the (tiny) Y-axis labels. 70px also crops the
informative range: KDJ values 50–100 in a bull market become a flat
line near the top of the cell.

**P5 — Intraday mode is visually undifferentiated from K-line.**
Today's 分时 implementation = `<LineChart>` with close (C.dark) + avgPrice
(C.gold) + prev_close ref. Compared to a real 分时 from 同花顺/东财, this
is missing:
- Cumulative-volume axis (right-side, paired to the price axis)
- Buy/sell strength indicator (tick imbalance) — no data yet, but
  visually at least we should reserve space for it
- Day-of-trading-session vertical guides at 09:30 / 11:30 / 13:00 / 15:00
- "Now" cursor (last-tick highlight)
- Above-prev-close vs below-prev-close fill (red above prev / green
  below — Chinese convention: 红涨绿跌 actually flipped vs Western)

Without these, a user opening 分时 sees *almost the same chart* as 1m
K-line and may not understand what 分时 even adds. The code carries the
mode but the design doesn't earn the extra button.

**P6 — viewMode ↔ interval ↔ range coupling is implicit.**
Click `[分时]` → forces `interval=1m`, `range=1d`, `viewMode=fenshi`.
Click any K-line interval chip → forces `viewMode=kline`. Click any
range chip → also forces `viewMode=kline`.

This is logically correct (分时 only makes sense at 1m/1d), but visually
*nothing tells the user about the coupling*. They click 5m while in 分时,
the chart silently becomes K-line, and they wonder where 分时 went.
Recovery: click `[分时]` again. A user has to learn the rule by trial.

**P7 — Indicator parameters are hardcoded with no escape.**
`bollinger(closes, 20, 2)`, `macd(closes, 12, 26, 9)`, `kdj(_, _, _, 9)`,
`rsi(closes, 14)` — all line 1050–1053. These are reasonable defaults,
but ar-platform's user (Junyan, plus any future power user) will at some
point want MACD(5,13,4) for short-term trades or RSI(7) for fast oscill.
The current UI offers no way to access this without editing source.
This is not a bug — but it's a known polish-layer gap and the design
should reserve a slot for it (a ⚙ gear icon next to chip group, future
popover).

---

## 3. Proposed design

### Composition principle

Reorganize the header right column into **two clear groups** with one
unifying mental model:

```
mode → period → range
 │       │        │
 K线 ◀──┴────►   sub-chip row (visible only in K-line mode)
 分时           (locked: 1m + 1d implicit, no chips needed)
```

i.e., **mode is top-tier** (K线 / 分时 — mutually exclusive segmented
control), **period is mid-tier** (only relevant in K-line: 1m/5m/.../月),
**range is bottom-tier** (1d/5d/1mo/3mo/1y). Mode swap reveals/hides
period chips — the coupling becomes visual.

Below: the seven changes individually, with before/after wireframes +
rationale.

---

### 3.1 Mode toggle: segmented control replaces colored button

**Before** (line 1174–1183):

```
[分时]  1m  5m  15m  30m  60m  日  周  月
  ↑
  red filled button when active, transparent border when inactive
```

**After** — paired segmented control:

```
[ K线 │ 分时 ]   1m  5m  15m  30m  60m  日  周  月
   ↑
   single segmented control, blue underline-bar marks active half;
   period chips dim/hide when 分时 is active
```

**Spec:**
- Width fixed at 88px (44px per half), height 24px
- Background `C.soft`, border `1px solid C.border`, borderRadius 5
- Active half: text `C.dark` (or `#FFF` in DARK theme), bottom-border
  2px solid `C.blue` (NOT a solid fill — keep red/green free for price
  semantics)
- Inactive half: text `C.mid`, no bottom-border
- fontSize 10, fontWeight 700, click area is the whole half
- ZERO red. Mode is structural, not semantic — no danger color.

**When 分时 active:**
- Period chip row dims to 30% opacity AND `pointerEvents:none` (visual
  proof of the coupling, P6 fix)
- A small label `· 1m · 1d locked` appears between the segmented
  control and the (dimmed) period row, fontSize 9, color C.mid
- Range chips also dim (range is implicit in 分时)

This makes the lock visible. The user no longer has to learn it by trial.

**Rationale:**
P1 fixed (no more red button), P2 partially fixed (one fewer chip group
demanding equal weight), P6 fixed (coupling shown visually).

---

### 3.2 Indicator chips: regrouped + recolored to one accent per group

**Before** (line 1260–1279) — 8 chips, 5 colors:

```
MA5(gold)  MA10(blue)  MA20(green)  MA60(red)  BOLL(dark)  │  MACD(blue)  KDJ(gold)  RSI(blue)
                                                          ↑
                                              no visual separator
```

**After** — two groups, one color per group, opacity steps for sub-items:

```
[ Overlays ─────────────────────────┐  [ Subplots ──────────┐
│  MA5  MA10  MA20  MA60   BOLL    │  │  MACD  KDJ  RSI    │
└───── all C.blue accent ──────────┘  └── all C.gold accent ┘
   ↑                                       ↑
   active chip: bg ${C.blue}14, fg C.blue   active: bg ${C.gold}14, fg C.gold
   inactive: transparent + C.mid border     inactive: same
```

- Group label (small, fontSize:8, color:C.mid, marginRight:8) precedes
  each group: `Overlays:` and `Subplots:`
- A 1px vertical divider (`borderRight:1px solid C.border`, height:18px)
  separates groups
- All chips fontSize:9, padding:`2px 8px`, borderRadius:4 (existing
  pattern preserved)
- Active visual: `background:${color}14, color:color, border:1px solid color`
- Inactive: `background:transparent, color:C.mid, border:1px solid C.border`

**Lines on the main chart:** keep the existing color assignment
(MA5 gold, MA10 blue, etc.) — *those colors live on the chart, not on
the chip*. Chip color = group identity (overlay vs subplot). Line color
on chart = which series (MA5 vs MA20). Decoupling fixes the overload.

**Rationale:**
P3 fixed (chip color is now group-identity, not series-identity).
Spillover benefit: when the user toggles MA5 on, they see "an Overlays
chip lit up + a gold line appeared on the main chart" — the relationship
is clean. Today they see "a gold chip lit up + a gold line + an unrelated
gold KDJ chip + an unrelated gold interval chip" — the gold-ness is
overloaded across four independent meanings.

**Trade-off note:** This pulls the chip colors away from matching the
line colors. Some users may prefer the literal "chip color = line color"
mapping. Counter: that's exactly the overload P3 describes. The line
color is on the *legend region of the chart* — see §3.4 for inline
legend with color swatches.

---

### 3.3 Header reflow: 2 rows instead of 3

**Before** — 3 rows (mode + interval + range + timestamp):

```
                                    ┌──────────────────────────────────┐
                                    │ [分时][1m 5m 15m 30m 60m 日 周 月]│
                                    │ [1d 5d 1mo 3mo 1y]  [↻]          │
                                    │ Updated 14:32 · auto              │
                                    └──────────────────────────────────┘
```

**After** — 2 rows (mode-period combined; range + meta on row 2):

```
                                    ┌──────────────────────────────────┐
                                    │ [K线│分时]  1m 5m 15m 30m 60m 日 周 月  ↻│
                                    │ [1d 5d 1mo 3mo 1y]    Updated 14:32 · auto│
                                    └──────────────────────────────────┘
```

Refresh button `↻` moves to the end of the period row (sits adjacent to
its own group's actions). Timestamp moves to the right of the range row,
fontSize:9, color:C.mid — same line as range chips, no longer floats on
its own.

**Rationale:**
P2 fixed: 3→2 rows, vertical density reduced ~25px without losing any
control. Also: time-to-scan is now linear (mode → period → range) which
matches the conceptual hierarchy.

---

### 3.4 Inline legend on the main chart

**Before:** indicator chips above chart show *what's enabled*, but the
chart itself has no legend — the user has to infer "the gold dashed line
is MA5 because the gold chip is on" by mapping mentally.

**After** — small inline legend in chart top-left:

```
┌─ Main chart (180px) ───────────────────────────────────────┐
│ ● Close  ─ MA5  ─ MA10  ─ MA20  ─ MA60  ╴BOLL              │  ← legend, fontSize:8, color:C.mid
│                                                              │
│  [the actual price chart]                                    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

- Position: absolute at top:6, left:60 (clears the Y-axis label area)
- Each item: a 12px-wide stroke sample in the matching color +
  fontSize:8 series name + 6px gap between items
- Only enabled overlays render in the legend (so it stays compact when
  user has 1–2 lines on)
- Subplot legends (MACD line/signal/hist; KDJ K/D/J; RSI) appear inside
  their own subplot top-left, same pattern

**Rationale:**
Pairs with §3.2 — separating chip group-identity from line-identity
needs a clear way to see line identity on the chart itself. Inline
legend is the standard solution. Doesn't add height (overlays the chart
margin area). `Tooltip` already shows individual values on hover; legend
shows series identity at-a-glance.

---

### 3.5 Subplots: tab strip instead of stack

**Before** — vertical stack of up to 3 × 70px subplots:

```
Volume      40px
─────────
MACD        70px (default ON)
─────────
KDJ         70px (toggleable)
─────────
RSI         70px (toggleable)
                      total: 250px when all 3 + volume on
```

**After** — single 90px subplot region with **tab strip switcher**:

```
[ Volume │ MACD │ KDJ │ RSI ]   ← tab strip, fontSize:9, height:22
─────────────────────────────
                              ↑
[active tab content]          90px (taller than current 70 since now only 1 visible)
─────────────────────────────
```

- Tab strip: 4 tabs, each fontSize:9 fontWeight:600, padding:`3px 12px`
- Active tab: `borderBottom:2px solid C.blue, color:C.dark, fontWeight:700`
- Inactive: `borderBottom:2px solid transparent, color:C.mid`
- Active subplot renders in 90px height (more vertical resolution per
  signal — KDJ in particular benefits)
- Default selected tab: `Volume` (always present anyway)
- Tab visibility ties to indicator-chip toggle: if user disables MACD
  chip, MACD tab disappears; the active tab falls back to the leftmost
  remaining

**This replaces the indicator chips' MACD/KDJ/RSI half** — those become
*tab visibility* toggles instead of *render visibility* toggles. The
Overlays group (MA + BOLL) stays as render toggles since they live on
the main chart and can co-exist freely.

**Net height impact:**
- Before, all 3 subplots + volume on: 250px (3 × 70 + 40)
- After, tab strip + 1 active + tab persists: 22 + 90 = 112px
- Savings: 138px when fully subscribed; equal-or-less in all states.

**Rationale:**
P4 fixed. The "I want to see all three at once" use case is rare;
99% of the time the user is looking at *one* signal. Tab strip honors
the actual usage pattern. For the rare power-user "compare KDJ + RSI"
case, deferred to Phase 2 polish (could be a "Compare" link that
re-stacks).

**Trade-off:** users accustomed to 同花顺 / 东财 see all subplots
stacked. This is a bigger UX departure than the rest of design-002.
Junyan-escalation candidate (see §10) — recommend tab strip as MVP, but
Junyan vetoes if he prefers the stack.

---

### 3.6 Intraday mode: chart-content earns its name

The biggest gap. Today 分时 ≈ 1m K-line minus the candles. After
redesign:

**Wireframe:**

```
┌─ Intraday mode (分时) ──────────────────────────────────────┐
│ ¥857.50  +1.20%   ●Live · 14:32:45                         │  ← header (live cursor in seconds)
├──────────────────────────────────────────────────────────────┤
│ ¥860 ┤                       ╱╲                  cum¥1.2亿   │  Right-axis: cumulative
│      │                  ╱╲ ╱╱  ╲╱╲           ╱──            │  turnover (light)
│ ¥855 ┤  ─ avg ─ ─ ─ ─ ─ ╱─ ─ ─ ─ ─ ─ ─ ─ ─ ─    ╱── 1.0亿   │  Left-axis: price
│      │ ╱╱  ╲╱╲                                ╱             │
│ ¥850 ┤╱─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ╱──   prev close│
│      │                                  ╱──                  │
│ ¥845 ┤                            ╱─────                     │
│      │                       ╱────                           │
│      └─┬────────┬────────┬──────────┬────┬─────                │
│       9:30   10:30   11:30/13:00  14:00  15:00              │
│        ↑       ↑      ↑ session    ↑      ↑                  │
│        morning open   midday break  pm    close              │
├──────────────────────────────────────────────────────────────┤
│  [tick-colored volume bars, opacity 0.6]                     │ 40px
└──────────────────────────────────────────────────────────────┘
```

**Changes from current:**

1. **Right-axis cumulative turnover line** — secondary y-axis showing
   accumulated `Σ turnover`. Color `C.mid` strokeWidth:1, opacity 0.6.
   Tells the user "is volume ramping?" without leaving the chart.
2. **Session vertical guides** — `<ReferenceLine x={...}/>` at
   `09:30:00`, `11:30:00`, `13:00:00`, `15:00:00` (Asian markets) or
   `09:30 / 16:00` for HK/US (when applicable). Color `${C.border}`,
   strokeDasharray '2 2'. Visually segments morning / midday-break /
   afternoon. Hidden if range != 1d.
3. **Above-prev-close fill** — `<Area>` between close-line and
   prev_close ref-line: fill `${C.green}1A` when close > prev,
   `${C.red}1A` when below. Western convention (green-up). For Chinese
   convention (red-up) — flagged for Junyan §10.
4. **"Now" cursor** — live position last-tick: a 4px circle
   `fill:lineC, stroke:#fff strokeWidth:1.5` at the last data point.
   Pulsing scale animation if `market_state === 'REGULAR'`.
5. **Live timestamp in header** — when in 分时 mode and market open,
   timestamp shows `HH:MM:SS` instead of just `HH:MM`. The seconds
   display is what tells the user "the data is moving" even when price
   is still.

**State derivation needed:**
- `cumTurnover` array — derived from `chartData[i].turnover` summed
- `marketState` for live cursor — already in `meta.market_state` (line 1144)
- session times — hardcoded by exchange (extract from ticker prefix:
  `.SZ/.SH` → 09:30/11:30/13:00/15:00; `.HK` → 09:30/12:00/13:00/16:00)

All compute in pure JS, no API change required.

**Rationale:**
P5 fixed. 分时 now has 4 visual elements that K-line doesn't (cum
turnover, session guides, above/below fill, live cursor). User opens
分时 and immediately sees it's a different lens, not a different chart
type with same content.

---

### 3.7 Tier-locked banner: scoped + recoverable

**Before** (line 1232–1248) — when minute interval requires Tushare 15000:

```
┌─ Banner (full card width, gold border, gold background tint) ─────┐
│ 🔒 需升级套餐                                                       │
│ 当前 15分 周期需要 Tushare 15000 积分套餐 (当前 6000 积分)。         │
│ API: pro.stk_mins  Msg: tier insufficient                         │
└────────────────────────────────────────────────────────────────────┘
```

The banner is informative but currently stands alone. After it: empty
chart space. The user has nothing actionable other than "manually click
back to 1d."

**After** — banner + recovery CTA pinned right:

```
┌─────────────────────────────────────────────────────────────────────┐
│ 🔒 15分 K-line 需 Tushare 15000 积分套餐 (当前 6000)。              │
│    [使用 1日 K-line →]                          API: pro.stk_mins ⓘ│  ← CTA
└─────────────────────────────────────────────────────────────────────┘
```

**Spec changes:**
- Banner height shrinks to ~52px (from current ~78px, saved ~26px when
  shown)
- Recovery CTA: button `[使用 1日 K-line →]` — fontSize 11, color C.blue,
  border 1px C.blue, padding 4px 12px, clicking calls
  `setIntervalState('1d'); setRange('1mo')`
- Debug info (API endpoint, Tushare msg) collapses into a `ⓘ`
  popover-on-hover. Tooltip shows API + msg in MONO text.
- The 🔒 tier-locked icon stays at start of the message (already a
  recognizable affordance pattern).

**Rationale:**
Users hit the tier lock by clicking interval chips. Recovery should be
one click, not a hunt back through the chips for "1d". CTA does the
revert. Debug info is for power users / Junyan reading; default-hidden.

---

## 4. Color, spacing, font choices

### 4.1 Frozen design system tokens — usage map after redesign

| Element | Token | Reason |
|---|---|---|
| Mode segmented control bottom-bar | `C.blue` | Mode is a structural choice, blue = primary action color |
| Mode toggle bg | `C.soft` | Standard input/control bg |
| Mode toggle border | `C.border` | Standard subtle structure |
| Period chip active | `C.gold` (kept) | Already shipped; keep momentum |
| Period chip inactive | `C.soft` bg, `C.mid` text | Standard inactive |
| Range chip active | `C.blue` (kept) | Already shipped; keep momentum |
| Indicator chip — Overlays group active | `C.blue` accent | Group identity |
| Indicator chip — Subplots group active | `C.gold` accent | Group identity |
| Subplot tab active underline | `C.blue` | Same as mode segmented; consistent |
| Cumulative turnover line (分时) | `C.mid` | Auxiliary info, not primary |
| Above-prev-close fill | `${C.green}1A` (Western) or `${C.red}1A` (Chinese) | Junyan §10 chooses |
| Below-prev-close fill | `${C.red}1A` (Western) or `${C.green}1A` (Chinese) | mirrored |
| Tier-lock banner | `C.gold` border + `${C.gold}14` bg | Existing pattern preserved |
| Tier-lock CTA | `C.blue` border + text | Recovery action, primary blue |
| Live cursor | `lineC` (= `C.green` or `C.red` based on isUp) | Match the price color, that's its identity |
| Session vertical guides | `C.border` strokeDasharray | Background structural marker |

Net result: in K-line view, `C.blue` carries "mode + range + overlays
group + subplot tab" — i.e., one color for "structural choices the user
makes." `C.gold` carries "period + subplots group" — i.e., one color
for "secondary configuration." `C.red` and `C.green` reserved purely
for *price semantics*. Color overload: resolved.

### 4.2 Spacing

- Card chrome: `borderRadius:10, border:1px solid C.border` (unchanged)
- Header padding: `12px 16px 8px` (unchanged)
- Mode segmented control: 88px × 24px
- Period chips: padding `2px 8px`, gap 6, fontSize 9 (unchanged)
- Range chips: padding `3px 9px`, gap 3, fontSize 10 (unchanged)
- Indicator chips: padding `2px 8px`, gap 4, fontSize 9 (unchanged); group divider 1px×18px borderRight
- Subplot tab strip: padding `3px 12px` per tab, height 22px
- Subplot active panel: 90px (was 70px per stacked subplot)
- Inline legend: position absolute, top:6 left:60, fontSize:8, gap:6

### 4.3 Fonts

- All text Inter (system default, unchanged)
- Numbers + tickers + axis labels: `MONO` (unchanged)
- Mode segmented control labels: fontSize:10 fontWeight:700
- Inline legend: fontSize:8 (this is the smallest text; below-table-row
  density is OK because it's reference-only)
- Subplot tab label: fontSize:9 fontWeight:600 (active fontWeight:700)

---

## 5. Implementation hints (T3 task spec)

### 5.1 New constants / shared

```js
// near line 53–55
const SESSION_TIMES = {
  CN_AHK: ['09:30','11:30','13:00','15:00'],  // .SZ .SH (and used as fallback for HK)
  HK:     ['09:30','12:00','13:00','16:00'],  // .HK
  US:     ['09:30','16:00'],                  // future US support
};
const TURNOVER_RIGHT_AXIS_COLOR = 'C.mid';    // not new, but documented use
```

### 5.2 New sub-components (extracted, below `PriceChart`)

```js
function ModeSegmented({ mode, onChange, C, L })          // §3.1
function ChipGroupOverlays({ indicators, onToggle, C })   // §3.2 - left half
function ChipGroupSubplots({ indicators, onToggle, C })   // §3.2 - right half
function InlineLegend({ enabled, C })                     // §3.4
function SubplotTabStrip({ active, available, onChange, C })  // §3.5
function FenshiChart({ chartData, meta, C, L, ccy })      // §3.6 — new dedicated chart
function TierLockedBanner({ tierLocked, currentInterval, onRecover, L, C })  // §3.7
```

### 5.3 Edits to existing `PriceChart`

| Lines | Change |
|---|---|
| 970 | viewMode state: keep, but rename internally — it's now a "mode" not just "view" |
| 1170–1222 | Header right column: replace 3-row block with `<ModeSegmented>` + chip rows + `<RefreshButton>` (extracted) |
| 1232–1248 | Replace tier-lock banner with `<TierLockedBanner onRecover={() => { setIntervalState('1d'); setRange('1mo'); }}/>` |
| 1259–1280 | Replace single chip row with `<ChipGroupOverlays>` + divider + `<ChipGroupSubplots>` |
| 1281–1295 | Replace 分时 chart block with `<FenshiChart>` (richer per §3.6) |
| 1296–1342 | K-line main chart: add `<InlineLegend>` overlay top-left |
| 1361–1406 | Subplot region: replace 3 stacked subplots with `<SubplotTabStrip>` + 1 active subplot panel @ 90px height |

Estimate: ~350 LOC across the 7 new sub-components + ~30 LOC of edits
to `PriceChart` body. Total bundle add ≈ 380 LOC. Net height saved per
PriceChart instance: ~138px when fully subscribed.

### 5.4 Test harness gates (for T2 review)

- `npm run build` exits 0
- JSX balance script returns 0
- Mode toggle: K线 ↔ 分时 swaps without manual interval/range click
- Mode toggle: while in 分时, period chips appear dimmed @ 30% opacity
  AND `pointer-events:none`
- Click 5m chip while in 分时 → silently goes to K-line + 5m (current
  behavior preserved; coupling lock visualized but not enforced)
- Indicator chip toggle: Overlays chip OFF removes that line from main
  chart but keeps subplot tab strip intact
- Indicator chip toggle: Subplots chip OFF removes that tab from
  subplot tab strip; if it was the active tab, falls back to leftmost
- Subplot tab strip: clicking each tab swaps the 90px panel content
- Inline legend: only enabled overlays render
- 分时 chart: cumulative turnover line draws on right axis with
  separate scale; session guides at 09:30/11:30/13:00/15:00 (for .SZ);
  above/below-prev fill; live cursor dot when market_state === 'REGULAR'
- Tier-locked CTA: clicking `[使用 1日 K-line →]` resets to 1d/1mo
- Debug info popover shows API + Tushare msg on hover of `ⓘ`
- Refresh button (`↻`) still triggers `fetchChart()`
- Auto-refresh on minute intervals still works (30s for 1m, 60s for 5m+)

---

## 6. Trade-offs

| Decision | Cost | Benefit |
|---|---|---|
| Mode = segmented control (not red button) | New component (~30 LOC) | Color semantics reclaimed; coupling visualizable; mode is structurally clear |
| Chip groups by purpose, not series | Chip color now uses just C.blue + C.gold | Color overload solved; chart legend handles series identity |
| Inline legend in chart top-left | Tiny fontSize:8 text overlays chart edge | Series identity preserved cleanly without adding height |
| Subplots → tab strip | Departs from 同花顺 stacked convention | -138px height when fully subscribed; matches actual usage (1 signal at a time); compare-mode deferred |
| 分时 enriched (right axis + guides + fill + live cursor) | ~120 LOC new component | 分时 finally earns its own button — visually distinct from K-line; matches user expectation from 同花顺 |
| Tier-lock banner + CTA + debug popover | Banner shrinks 26px; debug nested | One-click recovery; debug remains accessible |
| Header: 3 rows → 2 rows | Tighter horizontal packing per row | -25px vertical |

**Trade-offs we explicitly REJECT:**
- ❌ "Compare" mode that re-stacks subplots — Phase 2 polish, not MVP
- ❌ Indicator parameter popover (⚙ gear) — Phase 2 polish, slot reserved
- ❌ Tick-by-tick (逐笔) panel under 分时 — needs backend data not in
  current `price-chart` API; deferred to backend KR
- ❌ Buy/sell strength bar — same as above
- ❌ Drag-to-zoom on chart — recharts supports it but adds dep weight
  in interaction layer; defer
- ❌ Multi-stock overlay on same chart — separate feature, out of scope

---

## 7. Phasing

### MVP — this sprint (~3–4h T3 codegen + ~30min T2)

1. **Mode segmented control** (§3.1) — biggest semantic win, smallest LOC
2. **Indicator chip regroup + recolor** (§3.2) — color overload fix
3. **Header reflow 3→2 rows** (§3.3) — vertical density
4. **Subplot tab strip** (§3.5) — biggest height save
5. **Tier-locked banner CTA + popover** (§3.7) — recovery affordance

### MVP+ — same sprint if time (~1h)

6. **Inline legend on main chart** (§3.4) — pairs with chip regroup
7. **分时 enriched chart** (§3.6) — biggest UX delta in 分时 mode

### Polish — Jason layer (~1h)

- Animation: live cursor pulse, mode toggle bottom-bar slide, chip
  hover tilt
- Mode segmented control microinteraction (subtle press effect)
- Inline legend hover-to-isolate (hover MA10 → other lines fade to 30%)
- Subplot tab swap transition (200ms cross-fade)

### Phase 2 — separate session

- Indicator parameter popover (⚙) — exposes MACD(12,26,9) etc. for tuning
- "Compare" mode in subplot region — opt-in re-stack of 2+ subplots
- Drag-to-zoom on main chart
- Tick-by-tick panel (after backend KR provides data)

---

## 8. Test plan (T2 + Junyan UI verification)

### Functional (T2)

- All §5.4 gates pass.
- 7 sub-components each render with valid props in isolation (props
  table can be spec'd in the codegen task).

### Visual / qualitative (Junyan validates SHIPPED UI)

1. **Mode test:** Open Research drill, K-line vs 分时 distinct in <2 seconds.
   Clicking either tab swaps the chart cleanly. Period chips dim in 分时.
2. **Color overload test:** Hold up a print of the chart. Identify what
   each color represents in 5 sec. Pre-redesign: red ∈ {price-down,
   MA60, 分时-active, BOLL-band, MACD-hist-down} = ambiguous.
   Post-redesign: red ∈ {price-down, MACD-hist-down} only.
3. **Subplot scan test:** With Volume/MACD/KDJ/RSI all enabled, find
   "where am I looking right now?" in 2 sec. Pre: 4 stacked panels eye-
   pinpoint. Post: 1 panel + tab label.
4. **Intraday recognition test:** Show user 分时 vs 1m K-line side by
   side without labels. They identify which is which. Pre: hard. Post:
   cum turnover + session guides + above/below fill = obvious.
5. **Tier-lock recovery test:** Click 15分 chip. See banner. Click CTA.
   Returns to 1d K-line in 1 click. Pre: had to find 1d chip manually.
6. **Density test:** Default load on 768px laptop. Count vertical
   headroom remaining after PriceChart. Pre: ~50% screen consumed.
   Post: ~38% screen consumed (~138px savings × ~25% screen).
7. **Dark mode parity:** Switch theme. All 7 sub-components retain
   contrast. Mode toggle bottom-bar still visible against `C.bg`.

### Regression (T2)

- All existing PriceChart functionality unchanged: minute-interval
  auto-refresh (30s/60s), tier-lock detection, `meta` displays
  (price/H/L/Vol/Prev/market_state), refresh button, X-axis time
  formatter for each range, Y-axis tick formatter (1k+ values).

---

## 9. Self-iteration log (per Junyan 5/2 directive)

### Round 1 — Steel-man weakest section

**Weakest section identified:** §3.5 (Subplot tab strip) — biggest
departure from the prevailing 同花顺/东财 convention. Power users may
push back ("I want to see MACD + KDJ at the same time").

**Steel-man:** the convention is right *for traders watching live
ticks*. It's wrong *for an equity research tool whose Research drill
is not a trading screen*. Junyan opens Research to write a thesis, not
to scalp. In thesis-writing mode, "look at MACD, then look at KDJ,
then look at RSI" is a sequential read, not a parallel one. The tab
strip honors how *Junyan* uses the tool, not how a 同花顺 day-trader uses
it. Rebuttal acknowledged; tradeoff accepted; flagged for §10
escalation in case Junyan disagrees.

**Mitigation added:** Phase 2 "Compare mode" (§7) — opt-in re-stack for
the rare cross-signal comparison. This means the change is reversible
without re-architecting.

### Round 2 — Design-system fidelity check

Audited every color reference in §3 and §4:
- ✅ All chart-element colors use `C.{...}` tokens
- ✅ All chip backgrounds use `${C.X}14` opacity-suffix pattern (existing
  convention, line 64 helper)
- ✅ No new hex values introduced
- ✅ Outlier colors from design-001 §4.4 (#EF4444, #9333EA) — not used
  here; design-002 stays inside frozen palette
- ✅ All fontSize values use the existing 8/9/10/11/13/22 scale (no new sizes)
- ✅ All borderRadius values use 4/5/6/10 (existing scale)
- ✅ All paddings reuse existing patterns (`2px 8px`, `3px 9px`, etc.)

One small expansion: **inline legend uses fontSize:8** which is the
smallest in the system; this matches the existing 8px usage for "8px
badges" (e.g., 涨停 inline badge before design-001 dropped it). Within
existing scale.

---

## 10. Junyan-escalation triggers (per onboarding §"Self-iteration protocol")

The 4 escalation categories from `DESIGN_AGENT_ONBOARDING.md` (per
commit `a23653a`):

1. **Information-architecture decision that materially changes user
   workflow** — §3.5 (subplot tab strip) qualifies. Departure from
   stacked-subplots convention. **Junyan-flag.**
2. **Frozen-system token expansion or violation** — none triggered.
3. **Behavior change that affects existing user habits** — §3.6 fill
   color: Western convention (green-up) vs Chinese (red-up) — needs
   Junyan call. **Junyan-flag.**
4. **Cross-component impact** — none in this proposal (PriceChart is
   self-contained; only sub-components added).

**Two Junyan flags total.** All other decisions self-iterated and
ready to ship.

---

## Appendix A — Why this stops where it does

- **No code written** — T4 produces spec; T3 implements
- **No new colors / fonts / packages** — frozen system respected
- **Only PriceChart in scope** — does not touch Research/Desk/Browse/etc.
- **Self-iterated 2 rounds, ready for T1 gate**
- **2 Junyan flags surfaced, neither blocks shipping the rest**

---

**Done. Ready for T1 design-quality gate.**
