#!/usr/bin/env python3
"""thesis_review_packet.py — W6 (2026-05-08)

Renders a Round 2 review packet from a thesis JSON. Auto-detects
single-agent (existing /api/research output) vs multi-agent
(/api/research-multi output, future Stage 2). Multi-agent SCAN sections
auto-fill from `_bull_thesis` / `_bear_thesis` / `_technical` /
`_forensic` / `_direction` fields when present; otherwise show
explicit pending placeholders.

Per Junyan §6.5 (RESEARCH_AGENT_TEAM v2): "round 2 review 那就是每一个
agent 都全面 scan 一下 并且基于所有信息面去审视和批判 分析技术面等".
Each packet has BULL SCAN / BEAR SCAN / TECHNICAL SCAN / FORENSIC
SCAN / SYNTHESIZER VERDICT sections + human reviewer notes blocks.

Usage:
  python3 scripts/thesis_review_packet.py <ticker> <thesis_json_path>

  # Examples:
  python3 scripts/thesis_review_packet.py 002594.SZ \
    docs/research/factcheck/002594SZ_thesis_2026-05-08_GROUNDED.json

  # Custom output path
  python3 scripts/thesis_review_packet.py 002594.SZ <path> --out custom.md

DEFAULT OUTPUT:
  docs/research/review/<TICKER_NO_DOT>_review_<DATE>.md

WHAT THIS DOES:
  - Loads thesis JSON
  - Loads FC.2 fact-check from public/data/thesis_factcheck/<TICKER>.json
  - Loads Bridge-8 attribution from public/data/thesis_attribution/<TICKER>.json
  - Renders ~16-section markdown packet with reviewer prompts + empty
    REVIEWER NOTES blocks
  - Auto-detects multi-agent output and fills Bull/Bear/Tech/Forensic/Synth
    scan sections from JSON; otherwise leaves explicit "[Pending]"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DATA = REPO_ROOT / 'public' / 'data'


def safe_load(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def to_underscore(ticker: str) -> str:
    return ticker.replace('.', '_')


def to_no_dot(ticker: str) -> str:
    return ticker.replace('.', '')


# ─── Section renderers ──────────────────────────────────────────────


def section_0_source(ticker: str, thesis_path: Path, response: dict, data: dict) -> str:
    """Source data + machine-validation summary."""
    quality = data.get('_quality', {})
    qc = quality.get('qcChecklistResults', {})
    fc1_status = qc.get('step_1_catalyst_date_in_future', '?')

    lines = [
        '## 0. Source data + machine-validation summary',
        '',
        '| Item | Value |',
        '|---|---|',
        f'| Thesis source | [{thesis_path.name}]({thesis_path.relative_to(REPO_ROOT) if str(thesis_path).startswith(str(REPO_ROOT)) else thesis_path}) |',
        f'| Generated | {data.get("_quality", {}).get("date") or "(see thesis JSON)"} via `/api/research` |',
        f'| Model | {response.get("model") or "claude-opus-4-7"} |',
        f'| Tokens | input {response.get("usage", {}).get("input_tokens", "?")} / output {response.get("usage", {}).get("output_tokens", "?")} |',
        f'| `_quality.score` | **{quality.get("score", "?")}** ({quality.get("severity", "?")}) |',
        f'| FC.1 catalyst future-anchored | {"✓ TRUE" if fc1_status is True else "✗ FALSE" if fc1_status is False else "?"} |',
        f'| `enrichment_used` | {response.get("enrichment_used", "?")} |',
        f'| `fundamentals_used` | {response.get("fundamentals_used", "?")} |',
        f'| `extras_used` (W4) | {response.get("extras_used", "?")} |',
        f'| Repair attempted | {quality.get("repairAttempted", "?")} |',
    ]

    failed = [k for k, v in qc.items() if v is False and not k.endswith('_below_threshold')]
    if failed:
        lines.append(f'| Failed `_quality` checks | {", ".join(failed)} |')

    return '\n'.join(lines)


def section_1_at_a_glance(data: dict) -> str:
    """Thesis at-a-glance: catalyst + variant view + R/R + horizon."""
    s1 = data.get('step_1_catalyst', {}) or {}
    s7 = data.get('step_7_variant_view', {}) or {}
    pnl = s7.get('expected_pnl_asymmetry', {}) or {}
    direction = data.get('_direction') or data.get('dir') or '(not set)'

    lines = [
        '## 1. Thesis at-a-glance',
        '',
        f'**Direction:** {direction}',
        f'**Catalyst:** {s1.get("catalyst_event", "(missing)")}',
        f'**Catalyst window:** `{s1.get("catalyst_date_or_window", "(missing)")}`',
        '',
        f'**Variant view (one sentence):**',
        f'> {s7.get("variant_view_one_sentence", "(missing)")}',
        '',
        f'**Reward / Risk:** {pnl.get("reward_to_risk", "?")} (upside {pnl.get("upside_if_right", "?")} / downside {pnl.get("downside_if_wrong", "?")})',
        f'**Time to resolution:** {s7.get("time_to_resolution", "?")}',
        f'**Confidence (model self-report):** {data.get("step_4_quantification", {}).get("confidence", "?")}',
    ]
    return '\n'.join(lines)


def section_step1(data: dict) -> str:
    """Step 1 — Catalyst with reviewer prompts."""
    s1 = data.get('step_1_catalyst', {}) or {}
    return f"""## 2. Step 1 — Catalyst

| Field | Value |
|---|---|
| catalyst_event | {s1.get("catalyst_event", "(missing)")} |
| catalyst_date_or_window | `{s1.get("catalyst_date_or_window", "(missing)")}` |
| catalyst_type | {s1.get("catalyst_type", "(missing)")} |
| catalyst_source | {s1.get("catalyst_source", "(missing)")} |

### Reviewer prompts

- Is the catalyst date plausible per company's actual reporting calendar?
- Is the event specific enough to verify outcome from public data?
- Is the catalyst important enough to drive the thesis (vs incidental)?

REVIEWER NOTES:
```
(your assessment of catalyst quality, real/hallucinated, observability)
```"""


def section_step2(data: dict) -> str:
    """Step 2 — Mechanism chain."""
    chain = data.get('step_2_mechanism', {}).get('mechanism_chain', []) or []
    if not chain:
        return '## 3. Step 2 — Mechanism chain\n\n*(missing)*'
    lines = ['## 3. Step 2 — Mechanism chain', '']
    for i, step in enumerate(chain, 1):
        lines.append(f'> **[{i}]** {step}\n')
    lines.extend([
        '### Reviewer prompts',
        '',
        '- Each step a logical consequence of prior?',
        '- Any unfounded leaps (correlation treated as causation)?',
        '- Each step independently verifiable?',
        '',
        'REVIEWER NOTES (per step):',
        '```',
    ] + [f'[{i}] _______________' for i in range(1, len(chain) + 1)] + ['```'])
    return '\n'.join(lines)


def section_step3(data: dict) -> str:
    """Step 3 — Evidence with contrarian view."""
    s3 = data.get('step_3_evidence', {}) or {}
    cv = s3.get('contrarian_view', {}) or {}

    lines = ['## 4. Step 3 — Evidence', '', '### Quantitative']
    quant = s3.get('evidence_quantitative', []) or []
    for i, e in enumerate(quant, 1):
        lines.append(f'> [{i}] {e}')
    lines.append('')

    lines.append('### Qualitative')
    qual = s3.get('evidence_qualitative', []) or []
    for i, e in enumerate(qual, 1):
        lines.append(f'> [{i}] {e}')
    lines.append('')

    lines.append('### Contrarian view')
    lines.append('')
    lines.append('| Field | Value |')
    lines.append('|---|---|')
    mc = cv.get('market_consensus', {})
    if isinstance(mc, dict):
        lines.append(f'| market_consensus | {mc.get("e", mc.get("z", str(mc)))[:200]} |')
    else:
        lines.append(f'| market_consensus | {str(mc)[:200]} |')
    ov = cv.get('our_variant', {})
    if isinstance(ov, dict):
        lines.append(f'| our_variant | {ov.get("e", ov.get("z", str(ov)))[:200]} |')
    else:
        lines.append(f'| our_variant | {str(ov)[:200]} |')
    lines.append(f'| what_changes_our_mind | {cv.get("what_changes_our_mind", "(missing)")[:200]} |')
    lines.append('')

    lines.extend([
        '### Reviewer prompts',
        '',
        '- Each quantitative claim verifiable against filings (per FC.2 cross-check)?',
        '- Variant view actually contrarian, or rephrased consensus?',
        '- what_changes_our_mind concrete + observable?',
        '',
        'REVIEWER NOTES:',
        '```',
        'evidence integrity:        ___________',
        'contrarian-ness assessment: ___________',
        '```',
    ])
    return '\n'.join(lines)


def section_step4(data: dict) -> str:
    """Step 4 — Quantification."""
    s4 = data.get('step_4_quantification', {}) or {}
    pr = s4.get('predicted_range', {}) or {}
    return f"""## 5. Step 4 — Quantification

| Field | Value |
|---|---|
| metric_target | {s4.get("metric_target", "(missing)")} |
| current_value | {s4.get("current_value", "(missing)")} |
| predicted_value | {s4.get("predicted_value", "(missing)")} |
| predicted_range.low | {pr.get("low", "(missing)")} |
| predicted_range.mid | {pr.get("mid", "(missing)")} |
| predicted_range.high | {pr.get("high", "(missing)")} |
| predicted_horizon | {s4.get("predicted_horizon", "(missing)")} |
| confidence | {s4.get("confidence", "(missing)")} |

### Reviewer prompts
- Is current_value cross-checkable to today's market data?
- Is predicted_range falsifiably distinct from current_value at horizon?
- Confidence calibrated or hand-wavy?

REVIEWER NOTES: ___________"""


def section_step56(data: dict) -> str:
    """Steps 5/6 — proves_right_if + proves_wrong_if."""
    right = data.get('step_5_proves_right_if', []) or []
    wrong = data.get('step_6_proves_wrong_if', []) or []

    lines = ['## 6. Step 5 — proves_right_if', '', '```']
    for i, c in enumerate(right, 1):
        lines.append(f'[{i}] {c}')
    lines.append('```')
    lines.extend([
        '',
        '## 7. Step 6 — proves_wrong_if',
        '',
        '```',
    ])
    for i, c in enumerate(wrong, 1):
        lines.append(f'[{i}] {c}')
    lines.append('```')

    lines.extend([
        '',
        '### Reviewer prompts (apply to BOTH §6 and §7)',
        '',
        '- Each condition truly observable at the named horizon?',
        '- Symmetry: do rightIf / wrongIf address the same metric pairwise?',
        '- Any condition vague or unfalsifiable (e.g., "meaningfully", "materially")?',
        '',
        'REVIEWER NOTES (per condition):',
        '```',
    ])
    for i in range(1, max(len(right), len(wrong)) + 1):
        lines.append(f'rightIf [{i}]: ____   wrongIf [{i}]: ____')
    lines.append('```')

    return '\n'.join(lines)


def section_step7(data: dict) -> str:
    """Step 7 — variant view summary."""
    s7 = data.get('step_7_variant_view', {}) or {}
    pnl = s7.get('expected_pnl_asymmetry', {}) or {}
    return f"""## 8. Step 7 — variant view

| Field | Value |
|---|---|
| one_sentence | {s7.get("variant_view_one_sentence", "(missing)")} |
| time_to_resolution | {s7.get("time_to_resolution", "(missing)")} |
| upside_if_right | {pnl.get("upside_if_right", "(missing)")} |
| downside_if_wrong | {pnl.get("downside_if_wrong", "(missing)")} |
| reward_to_risk | {pnl.get("reward_to_risk", "(missing)")} |

### Reviewer prompts

- Is "Market believes X → We believe Y" a clean dichotomy or just degree?
- R/R derived from predicted_range or asserted? (Trace the math.)
- Current price implied in the thesis matches yahoo live? (FC.2 should catch.)

REVIEWER NOTES:
```
contrarian-ness: ___________
math integrity:  ___________
price anchoring: ___________
```"""


def section_step8(data: dict) -> str:
    """Step 8 — phase_and_timing brief."""
    s8 = data.get('step_8_phase_and_timing', {}) or {}
    p1 = s8.get('phase_1_market_belief', {}) or {}
    p2 = s8.get('phase_2_reality_recognition', {}) or {}
    return f"""## 9. Step 8 — phase_and_timing (brief)

```
phase_1_market_belief.duration_estimate:
  "{p1.get("duration_estimate", "(missing)")}"

phase_2_reality_recognition.estimated_timing:
  "{p2.get("estimated_timing", "(missing)")}"
```

(Full phase_1 / phase_2 / position_sizing_curve in raw thesis JSON
under `step_8_phase_and_timing`. Note: position_sizing_curve fails
the structural validator's monotonicity check universally — see
C-1.7 KR queued.)

REVIEWER NOTES (re phase timing realism):
___________"""


def section_factcheck(ticker: str) -> str:
    """Section 10 — FC.1 + FC.2 cross-check results."""
    safe = to_underscore(ticker)
    fc = safe_load(PUBLIC_DATA / 'thesis_factcheck' / f'{safe}.json')

    lines = ['## 10. Cross-checks done by automation (FC.1 + FC.2)', '']
    if fc:
        summary = fc.get('summary', {})
        lines.append(f'**Multiplier cross-check:** {summary.get("MATCH", 0)} MATCH / {summary.get("MISMATCH", 0)} MISMATCH / {summary.get("UNVERIFIABLE", 0)} UNVERIFIABLE')
        lines.append(f'**Tolerance:** ±{fc.get("tolerance_pct", 5)}%')
        lines.append(f'**Live price (yahoo):** {fc.get("live_price", "?")}')
        lines.append('')
        results = fc.get('results', [])
        if results:
            lines.append('| Path | Claim | Actual (yahoo) | Δ% | Status |')
            lines.append('|---|---|---|---|---|')
            for r in results:
                marker = {'MATCH': '✓', 'MISMATCH': '✗', 'UNVERIFIABLE': '?'}.get(r['status'], '?')
                d = r.get('diff_pct')
                d_str = f'{d:+.1f}%' if d is not None else 'N/A'
                lines.append(f'| {r["thesis_path"]} | {r["claimed_value"]:.2f}x ({r["label"]}) | {r["gt_value"]:.2f}x | {d_str} | {marker} {r["status"]} |')
        else:
            lines.append('No multiplier claims emitted by model. (Either thesis avoids multiples, or pattern set needs expansion.)')
    else:
        lines.append('FC.2 fact-check JSON not found. Run `python3 scripts/thesis_factcheck.py <ticker> <thesis>` first.')

    lines.extend([
        '',
        '### Reviewer prompts',
        '',
        '- Any MISMATCH worth investigating (diff ≥10%)?',
        '- Any UNVERIFIABLE that should have been checked?',
        '- Multiplier claim density: too low (model avoids quantification) or too high (overconfident)?',
        '',
        'REVIEWER NOTES: ___________',
    ])
    return '\n'.join(lines)


def section_attribution(ticker: str) -> str:
    """Section 11 — Bridge-8 attribution snapshot."""
    safe = to_underscore(ticker)
    attr = safe_load(PUBLIC_DATA / 'thesis_attribution' / f'{safe}.json')

    lines = ['## 11. Bridge-8 attribution snapshot', '']
    if attr:
        catalyst = attr.get('catalyst', {})
        pnl = attr.get('expected_pnl_asymmetry', {})
        lines.append(f'**Logged at:** {attr.get("thesis_logged_at", "?")}')
        lines.append(f'**Source commit:** `{attr.get("thesis_source_commit", "?")}`')
        lines.append(f'**Catalyst:** "{(catalyst.get("event") or "")[:100]}"')
        lines.append(f'**Window:** "{catalyst.get("date_or_window", "?")}"')
        lines.append(f'**rightIf conditions:** {len(attr.get("rightIf_conditions", []))}')
        lines.append(f'**wrongIf conditions:** {len(attr.get("wrongIf_conditions", []))}')
        lines.append(f'**reward_to_risk:** {pnl.get("reward_to_risk", "?")}')
        lines.append(f'**time_to_resolution:** {attr.get("time_to_resolution", "?")}')
        lines.append(f'**outcomes_recorded_at:** {attr.get("outcomes_recorded_at", "null (not yet built)")}')
    else:
        lines.append('Bridge-8 attribution log not found. Run `python3 scripts/log_thesis.py <ticker> <thesis>` first.')

    return '\n'.join(lines)


def section_multi_agent_scan(role: str, content: Optional[dict], section_num: int) -> str:
    """Section 12-15 — per-agent SCAN sections.

    role: 'BULL' | 'BEAR' | 'TECHNICAL' | 'FORENSIC'
    content: the per-agent output dict from multi-agent thesis JSON, or None
    """
    label = {
        'BULL': 'Bull Scan (LONG argument from current data)',
        'BEAR': 'Bear Scan (SHORT argument from current data)',
        'TECHNICAL': 'Technical Scan (chart pattern + momentum + chip + volume)',
        'FORENSIC': 'Forensic Scan (factual integrity + cross-checks)',
    }.get(role, role)

    lines = [f'## {section_num}. {label}', '']

    if content is None:
        lines.append('**Status:** [PENDING] — multi-agent endpoint Stage 2 not yet shipped.')
        lines.append('')
        lines.append(f'When `/api/research-multi` ships per RESEARCH_AGENT_TEAM_v1.md v2 §2, this section auto-fills from the thesis JSON\'s `_{role.lower()}` field.')
        lines.append('')
        lines.append(f'**Manual fallback:** Junyan (or T1) can fill this section now by reading the thesis + data context, applying the {role.lower()} role, and writing what arguments emerge.')
        lines.append('')
        lines.append('REVIEWER NOTES:')
        lines.append('```')
        lines.append(f'(Manual {role.lower()}-perspective scan: what does the {role.lower()} argument look like, and is it grounded?)')
        lines.append('```')
    else:
        # Multi-agent output present — render it
        if role in ('BULL', 'BEAR'):
            # Render as 8-step thesis subset
            s7 = content.get('step_7_variant_view', {}) or {}
            pnl = s7.get('expected_pnl_asymmetry', {}) or {}
            lines.append(f'**Direction (per agent):** {content.get("dir", "?")}')
            lines.append(f'**Variant view:** {s7.get("variant_view_one_sentence", "(missing)")}')
            lines.append(f'**R/R:** {pnl.get("reward_to_risk", "?")}')
            lines.append('')
            chain = content.get('step_2_mechanism', {}).get('mechanism_chain', [])
            if chain:
                lines.append('**Mechanism (this agent\'s view):**')
                for i, step in enumerate(chain[:5], 1):
                    lines.append(f'> [{i}] {step}')
            if '_rebuttal' in content:
                lines.append('')
                lines.append(f'**Round 2 rebuttal:** {content["_rebuttal"]}')
        elif role == 'TECHNICAL':
            lines.append(f'**Trend:** {content.get("trend", "?")} (strength {content.get("trend_strength", "?")}/100)')
            lines.append(f'**Momentum:** {(content.get("momentum") or {}).get("interpretation", "?")}')
            kl = content.get('key_levels', {})
            lines.append(f'**Support:** {kl.get("support", "?")}')
            lines.append(f'**Resistance:** {kl.get("resistance", "?")}')
            lines.append(f'**Volume profile:** {content.get("volume_profile", "?")}')
            lines.append(f'**Chip concentration:** {content.get("chip_concentration", "?")}')
            lines.append(f'**Margin trend:** {content.get("margin_trend", "?")}')
            lines.append(f'**Summary:** {content.get("technical_summary_e", "?")}')
        elif role == 'FORENSIC':
            lines.append(f'**Grounding verdict:** {content.get("verdict_on_grounding", "?")}')
            lines.append(f'**Technical vs Bull:** {content.get("technical_vs_bull", "?")}')
            lines.append(f'**Technical vs Bear:** {content.get("technical_vs_bear", "?")}')
            shared = content.get('shared_assumptions_at_risk', [])
            if shared:
                lines.append('**Shared assumptions at risk:**')
                for a in shared:
                    lines.append(f'  - {a}')
        lines.append('')
        lines.append('REVIEWER NOTES (override / disagree / flag):')
        lines.append('```')
        lines.append('___________')
        lines.append('```')

    return '\n'.join(lines)


def section_synth_verdict(data: dict, section_num: int) -> str:
    """Section 16 — Synthesizer verdict (single or multi-agent)."""
    direction = data.get('_direction')
    divergence = data.get('_divergence_score')
    forensic = data.get('_forensic')

    lines = [f'## {section_num}. Synthesizer Verdict', '']
    if direction:
        lines.append(f'**Final direction:** {direction}')
    else:
        lines.append('**Final direction:** *(not set — single-agent thesis; direction inferred from variant view)*')
    if divergence is not None:
        lines.append(f'**Divergence score (Bull vs Bear disagreement):** {divergence}/100')
    if forensic:
        lines.append(f'**Forensic verdict on grounding:** {forensic.get("verdict_on_grounding", "?")}')

    lines.extend([
        '',
        'REVIEWER VERDICT:',
        '```',
        'catalyst quality:                  ___________',
        'mechanism causal integrity:        ___________',
        'evidence integrity (numbers):      ___________',
        'contrarian-ness:                   ___________',
        'falsification observability:       ___________',
        'factual integrity (vs FC tools):   ___________',
        'multi-agent disagreement (if any): ___________',
        '',
        'Overall hand-rating:               ___________',
        '',
        'Action items / follow-ups:',
        '  - ',
        '  - ',
        '```',
    ])
    return '\n'.join(lines)


def section_red_flags(ticker: str, data: dict) -> str:
    """Section 17 — Open red flags + Junyan reviewer notes."""
    return f"""## {17}. Open red flags / questions for hand review

T1's observations (DATA, NOT JUDGMENTS — for Junyan to resolve):

**Pattern flags from FC tools:**
(See §10 above for FC.1 catalyst-temporal + FC.2 multiplier mismatches.)

**Quantitative claims unverified by automation:**
The thesis contains numerical claims beyond multipliers (segment revenue,
GM growth, capex, store count, etc.) that FC.2 doesn't currently check.
Each such claim is a structurally-invisible factual integrity test.

**Contrarian-ness assessment:**
[FORENSIC SCAN above + your judgment]

**Mechanism plausibility:**
[BULL/BEAR SCAN above + your judgment]

**wrongIf observability at horizon:**
Conditions are mostly concrete (per Bridge-8 attribution). At catalyst
date ({data.get("step_1_catalyst", {}).get("catalyst_date_or_window", "?")}), check whether each fired in the predicted direction.

REVIEWER VERDICT:
```
overall thesis quality (your hand-rating, not score):  ___________
top concern:                                            ___________
should this thesis be acted upon?                       Y / N / NEEDS_MORE_DATA
```"""


# ─── Top-level orchestration ────────────────────────────────────────


def render_packet(ticker: str, thesis_path: Path) -> str:
    """Render the full Round 2 review packet."""
    raw = json.load(thesis_path.open())
    data = raw.get('data', raw)
    response = raw  # full /api/research response (has model, usage, etc.)

    # Multi-agent detection
    bull_thesis = data.get('_bull_thesis')
    bear_thesis = data.get('_bear_thesis')
    technical = data.get('_technical')
    forensic = data.get('_forensic')
    has_multi = any(x is not None for x in [bull_thesis, bear_thesis, technical, forensic])

    # Header
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    multi_label = '(MULTI-AGENT v2)' if has_multi else '(SINGLE-AGENT)'
    header = f"""# Thesis Review Packet — {ticker} {multi_label}, {today}

> **Purpose:** Round 2 review packet per Junyan §6.5
> (RESEARCH_AGENT_TEAM_v1.md v2). Each section asks an agent (or
> Junyan) to do a full scan + critique based on all available data.
> Empty REVIEWER NOTES blocks are for Junyan to fill.
>
> **Mode:** {'multi-agent (auto-filled from /api/research-multi output)' if has_multi else 'single-agent (multi-agent SCAN sections show pending placeholders; will auto-fill once /api/research-multi ships)'}
> **Discipline:** No composite "review score" — Goodhart risk. Each
> section is independent qualitative judgment.
"""

    sections = [
        header,
        section_0_source(ticker, thesis_path, response, data),
        section_1_at_a_glance(data),
        section_step1(data),
        section_step2(data),
        section_step3(data),
        section_step4(data),
        section_step56(data),
        section_step7(data),
        section_step8(data),
        section_factcheck(ticker),
        section_attribution(ticker),
        # Multi-agent SCAN sections (12-15)
        section_multi_agent_scan('BULL', bull_thesis, 12),
        section_multi_agent_scan('BEAR', bear_thesis, 13),
        section_multi_agent_scan('TECHNICAL', technical, 14),
        section_multi_agent_scan('FORENSIC', forensic, 15),
        section_synth_verdict(data, 16),
        section_red_flags(ticker, data),
        f"""---

**Packet author:** T1 Claude (auto-generated by `scripts/thesis_review_packet.py`)
**Awaiting:** Junyan's hand annotations + (if single-agent) Stage 2 multi-agent endpoint to fill SCAN sections""",
    ]

    return '\n\n'.join(sections)


def main():
    p = argparse.ArgumentParser(description='Render Round 2 review packet from thesis JSON.')
    p.add_argument('ticker', help='Ticker (e.g., 002594.SZ, 175.HK)')
    p.add_argument('thesis_path', help='Path to thesis JSON (raw or full /api/research response)')
    p.add_argument('--out', help='Output path (default: docs/research/review/<TICKER_NO_DOT>_review_<DATE>.md)')
    args = p.parse_args()

    thesis_path = Path(args.thesis_path).resolve()
    if not thesis_path.exists():
        sys.exit(f'ERROR: thesis file not found: {thesis_path}')

    packet = render_packet(args.ticker, thesis_path)

    # Default out path
    if args.out:
        out_path = Path(args.out)
    else:
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        out_dir = REPO_ROOT / 'docs' / 'research' / 'review'
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f'{to_no_dot(args.ticker)}_review_{today}.md'

    out_path.write_text(packet)
    print(f'Wrote {len(packet)} chars to {out_path.relative_to(REPO_ROOT) if str(out_path).startswith(str(REPO_ROOT)) else out_path}', file=sys.stderr)


if __name__ == '__main__':
    main()
