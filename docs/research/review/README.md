# Thesis Review Packets — Hand-Review Channel for Junyan

> **Purpose:** Provide Junyan a structured way to do hands-on critique of
> thesis output. Pulls thesis JSON + fact-check + attribution into one
> markdown doc per ticker with reviewer prompts. This is HUMAN judgment
> infrastructure, not another auto-validator.

## Why this exists

After 2 Vercel redeploys + 6 KRs (FC.1–FC.6 + Bridge-8 scaffold), the
fact-check stack catches:
- Catalyst temporal validity (FC.1)
- Multiplier cross-check vs yahoo (FC.2)
- Sized expectations / wrongIf attribution (Bridge-8 log)

What automation does NOT catch (per audit doc §8):
- Whether the catalyst event is real (could be hallucinated)
- Whether mechanism causal chain is sound
- Whether falsification conditions are truly observable
- Whether variant view is truly contrarian
- Whether non-multiplier numbers are accurate (price levels, segment
  revenue, GM trajectory, capex figures, sell-side consensus targets)

Human review is the only way to assess these. This dir holds the
structured artifacts for that review.

## Format

One packet per (ticker, generation date). Filename pattern:
`<TICKER>_review_<YYYY-MM-DD>.md`.

Each packet has 12 sections:
0. Source data + machine-validation summary
1. Thesis at-a-glance
2. Step 1 — Catalyst (with reviewer prompts)
3. Step 2 — Mechanism chain
4. Step 3 — Evidence
5. Step 4 — Quantification
6-7. Step 5/6 — proves_right_if / proves_wrong_if
8. Step 7 — variant view summary
9. Step 8 — phase_and_timing brief
10. Cross-checks done by FC.1 + FC.2
11. Bridge-8 attribution snapshot
12. **Open red flags / questions** — T1's observations (data only, no judgment)

**REVIEWER NOTES blocks** in each section are for Junyan to fill in.

## Discipline

- **No composite "review score".** Composite would be a new Goodhart
  target. Each reviewer note is independent.
- **T1 assembles data; Junyan provides judgments.** §12 contains T1's
  observations — DATA POINTS, not pre-judgments. Anything that reads as
  "this is wrong" should be reformatted as "this might be wrong because
  X — verify against Y".
- **Same-day re-runs produce different theses.** Each packet is a
  snapshot of one specific thesis call. Reviews don't generalize across
  calls.

## What's in here

| Packet | Ticker | Gen date | Status |
|---|---|---|---|
| [700HK_review_2026-05-05.md](700HK_review_2026-05-05.md) | 700.HK (Tencent) | 2026-05-05 15:30 BST | First packet — format trial. SHORT thesis. Awaiting Junyan annotations. |

## Round structure

- **Round 1 (now):** 1 packet (700.HK) showing the format. Manual
  assembly. ~1h cost.
- **Round 2 (gated on Junyan feedback):** if format useful, build
  `scripts/thesis_review_packet.py` to auto-generate from any saved
  thesis JSON, run on the other 3 watchlist tickers
  (002594/9999/6160).
- **Round 3+ (Junyan-led):** Junyan does hand reviews; T1 follows up
  on red flags he surfaces (e.g., price hallucination check, ad-hoc
  data-source cross-check on specific evidence claims).

## Cost discipline

- Packet generation: 0 API spend (uses already-saved artifacts).
- Manual assembly: ~1h per packet.
- Auto-gen script (Round 2 if approved): ~1h to write + 0 per packet
  thereafter.

---

**Created:** 2026-05-05 (post shift-13, fifth wave)
**Author:** T1 Claude
**Maintained by:** Junyan (annotations) + T1 (data assembly + follow-ups)
