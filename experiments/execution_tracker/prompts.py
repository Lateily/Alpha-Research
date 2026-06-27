"""Repo-resident discipline layer (P0.5 of MODEL_UPGRADE_TREE).

Loads the execution-discipline system prompt (``discipline_prompt.md``) so that
cloud-side / frontend LLM summaries enforce the SAME discipline as the local
``ar-weekly-trading-factory`` SKILL. The local skill is invisible to GitHub
Actions / Pages / cloud Claude API; this module makes the discipline
cloud-readable and importable by the report runners (P1.x).

Usage:
    from prompts import load_discipline_prompt
    system_prompt = load_discipline_prompt()        # feed as the LLM system prompt

    python prompts.py --selftest                     # CI guard: discipline intact
    python prompts.py --print                        # dump the prompt
"""
from __future__ import annotations

from pathlib import Path

_PROMPT_PATH = Path(__file__).with_name("discipline_prompt.md")

# Load-bearing markers the discipline prompt MUST contain. --selftest asserts
# every one is present, so a careless edit can't silently strip the discipline.
REQUIRED_MARKERS = [
    # the closing invariant
    "不是买卖指令",
    # execution-gate posture enum
    "NO_CHASE", "HOLD_OBSERVE", "WARNING", "RECLAIM_REVIEW", "DE_RISK_REVIEW", "EXIT_REVIEW",
    # research posture ladder
    "WATCH_CONSTRUCTIVE", "STARTER_CANDIDATE",
    # global-risk state (Gate 0)
    "GLOBAL_RISK_OFF", "NEWS_UNRELIABLE",
    # evidence tiers
    "E1", "E2", "E3", "E4",
    # the data-integrity iron laws
    "no look-ahead", "定盘", "sample_eligible",
    # the pipeline order + red-team
    "factpack", "red-team",
    # the no-claim-before-30 rule
    "30",
]

# Phrases a *generated summary* must never contain as guidance. Exposed for the
# summary validators (P1.x) to check LLM output against — NOT asserted on the
# prompt itself (the prompt legitimately lists them under "Forbidden phrases").
FORBIDDEN_IN_GENERATED_OUTPUT = [
    "buy now", "sell now", "cut loss", "割肉", "满仓", "立即买入", "立即卖出",
]


def load_discipline_prompt() -> str:
    """Return the execution-discipline system prompt text."""
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _selftest() -> int:
    txt = load_discipline_prompt()
    missing = [m for m in REQUIRED_MARKERS if m not in txt]
    assert not missing, f"discipline prompt missing required markers: {missing}"
    assert "Forbidden phrases" in txt, "discipline prompt lost its Forbidden-phrases clause"
    assert "不是买卖指令" in txt and "human executes." in txt[-160:], "discipline prompt must end with the literal closing line"
    print(
        f"prompts.py selftest: OK "
        f"({len(REQUIRED_MARKERS)} required markers present, "
        f"{len(FORBIDDEN_IN_GENERATED_OUTPUT)} forbidden-output phrases registered, "
        f"{len(txt)} chars loaded from {_PROMPT_PATH.name})"
    )
    return 0


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if "--print" in sys.argv:
        print(load_discipline_prompt())
        raise SystemExit(0)
    print("usage: python prompts.py --selftest | --print")
