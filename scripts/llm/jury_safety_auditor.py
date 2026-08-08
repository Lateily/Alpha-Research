"""Rule-based Safety Auditor for Agent Jury outputs.

This auditor is deterministic and does not call any model API. It catches common
red-line violations before final synthesis is shown or stored.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RISK_WEIGHTS = {"low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    severity: str
    category: str
    pattern: re.Pattern[str]
    message: str


RULES = [
    Rule(
        "trade_instruction_buy_sell",
        "high",
        "decision_overreach",
        re.compile(r"\b(buy|sell|hold|short|long)\b|买入|卖出|持有|做多|做空|建仓|清仓|加仓|减仓"),
        "Detected wording that may be read as a trading instruction.",
    ),
    Rule(
        "position_sizing",
        "high",
        "decision_overreach",
        re.compile(r"仓位|position sizing|[0-9]+%.*(仓|position)|配置.*[0-9]+%"),
        "Detected possible position sizing or allocation wording.",
    ),
    Rule(
        "execution_language",
        "high",
        "decision_overreach",
        re.compile(r"立即执行|下单|交易指令|execute trade|place order|order now"),
        "Detected execution-like language.",
    ),
    Rule(
        "prompt_injection_ignore",
        "high",
        "prompt_injection",
        re.compile(r"ignore (all )?(previous|prior) instructions|忽略(以上|之前|所有)指令", re.I),
        "Detected instruction-override language from untrusted content.",
    ),
    Rule(
        "prompt_injection_role",
        "medium",
        "prompt_injection",
        re.compile(r"you are now|act as|system prompt|developer message|你现在是|扮演|系统提示词", re.I),
        "Detected role or system-prompt manipulation language.",
    ),
    Rule(
        "secret_openai_like",
        "high",
        "secret_leak",
        re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}\b"),
        "Detected a string that looks like an API key.",
    ),
    Rule(
        "secret_github_like",
        "high",
        "secret_leak",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
        "Detected a string that looks like a GitHub token.",
    ),
    Rule(
        "secret_bearer",
        "high",
        "secret_leak",
        re.compile(r"Authorization:\s*Bearer\s+[A-Za-z0-9_\-.]+", re.I),
        "Detected a bearer token pattern.",
    ),
    Rule(
        "bypass_human_gate",
        "high",
        "governance",
        re.compile(r"绕过.*Junyan|无需.*Junyan|skip.*human review|bypass.*review", re.I),
        "Detected wording that may bypass human review or Junyan's gate.",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit text or JSON for Agent Jury safety risks."
    )
    parser.add_argument("--text", help="Text to audit.")
    parser.add_argument("--file", help="UTF-8 text or JSON file to audit.")
    parser.add_argument(
        "--fail-on",
        choices=("none", "medium", "high"),
        default="high",
        help="Exit non-zero when at least this severity appears.",
    )
    args = parser.parse_args()

    if not args.text and not args.file:
        parser.error("Provide --text or --file.")

    raw = args.text if args.text is not None else Path(args.file).read_text(encoding="utf-8")
    report = audit_text(raw)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if should_fail(report, args.fail_on) else 0


def audit_text(raw: str) -> dict[str, Any]:
    findings = []
    for rule in RULES:
        for match in rule.pattern.finditer(raw):
            findings.append(
                {
                    "rule_id": rule.rule_id,
                    "severity": rule.severity,
                    "category": rule.category,
                    "message": rule.message,
                    "match_preview": mask_preview(match.group(0)),
                }
            )

    max_severity = "none"
    for finding in findings:
        if RISK_WEIGHTS[finding["severity"]] > RISK_WEIGHTS.get(max_severity, 0):
            max_severity = finding["severity"]

    return {
        "schema": "agent-jury.safety-audit.v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "risk_level": max_severity,
        "blocked": max_severity == "high",
        "findings": findings,
        "required_action": required_action(max_severity),
        "non_decision_notice": (
            "This is evidence processing only, not investment advice or a trading instruction."
        ),
    }


def should_fail(report: dict[str, Any], fail_on: str) -> bool:
    if fail_on == "none":
        return False
    threshold = RISK_WEIGHTS[fail_on]
    return RISK_WEIGHTS.get(report["risk_level"], 0) >= threshold


def required_action(risk_level: str) -> str:
    if risk_level == "high":
        return "Block final synthesis until a human reviews and removes the red-line risk."
    if risk_level == "medium":
        return "Allow only with visible warning and human review."
    if risk_level == "low":
        return "Allow, but keep the audit report attached."
    return "Allow."


def mask_preview(raw: str) -> str:
    compact = " ".join(raw.split())
    if len(compact) <= 12:
        return compact
    return f"{compact[:6]}...{compact[-4:]}"


if __name__ == "__main__":
    raise SystemExit(main())
