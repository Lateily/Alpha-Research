"""Agent Jury Lab: a no-API sandbox for multi-agent review flow.

The lab demonstrates the target logic before real model adapters are wired in:
independent answers, anonymous cross-review, best-part extraction, and final
synthesis. It never produces trading instructions.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_RUBRICS = ["evidence", "logic", "safety", "usability", "structure"]
DEFAULT_AGENTS = ["alpha", "beta", "gamma"]


@dataclass(frozen=True)
class JurySpec:
    question: str
    context: str
    agents: list[str]
    rubrics: list[str]
    output: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a no-API Agent Jury Harness sandbox."
    )
    parser.add_argument("--task", help="One-line task or question.")
    parser.add_argument("--spec", help="Path to an AJL spec file.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of the process view.",
    )
    args = parser.parse_args()

    spec = load_spec(args)
    result = run_jury(spec)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_process(result)
    return 0


def load_spec(args: argparse.Namespace) -> JurySpec:
    if args.spec:
        return parse_ajl(Path(args.spec).read_text(encoding="utf-8"))

    question = args.task or "How should an agent jury review a research event?"
    return JurySpec(
        question=question,
        context="",
        agents=DEFAULT_AGENTS,
        rubrics=DEFAULT_RUBRICS,
        output="review_packet",
    )


def parse_ajl(raw: str) -> JurySpec:
    """Parse a tiny Agent Jury Language document."""

    fields: dict[str, str] = {}
    context_lines: list[str] = []
    in_context = False

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.upper() == "CONTEXT:":
            in_context = True
            continue
        if in_context:
            context_lines.append(line)
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        fields[key.strip().upper()] = value.strip()

    question = fields.get("QUESTION", "").strip()
    if not question:
        raise ValueError("AJL requires QUESTION.")

    return JurySpec(
        question=question,
        context="\n".join(context_lines).strip(),
        agents=split_csv(fields.get("AGENTS", ",".join(DEFAULT_AGENTS))),
        rubrics=split_csv(fields.get("RUBRICS", ",".join(DEFAULT_RUBRICS))),
        output=fields.get("OUTPUT", "review_packet"),
    )


def run_jury(spec: JurySpec) -> dict[str, Any]:
    answers = independent_answers(spec)
    anonymous_answers = anonymize(answers)
    reviews = cross_review(spec, anonymous_answers)
    best_parts = extract_best_parts(spec, anonymous_answers, reviews)

    return {
        "schema": "agent-jury-lab.v0",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "question": spec.question,
        "context": spec.context,
        "agents": spec.agents,
        "rubrics": spec.rubrics,
        "phase_1_independent_answers": answers,
        "phase_2_anonymous_reviews": reviews,
        "phase_3_best_parts": best_parts,
        "phase_4_final_synthesis": synthesize(spec, best_parts, reviews),
        "safety_flags": [
            "external_content_is_untrusted_input",
            "no_trading_instruction",
            "human_review_required",
        ],
        "cost_cny": "0",
    }


def independent_answers(spec: JurySpec) -> list[dict[str, Any]]:
    answers = []
    for index, agent in enumerate(spec.agents):
        answers.append(
            {
                "agent": agent,
                "answer_id": f"answer_{index + 1}",
                "answer": build_answer(spec, agent, index),
            }
        )
    return answers


def build_answer(spec: JurySpec, agent: str, index: int) -> dict[str, str]:
    lenses = [
        "first pin down observable facts and missing evidence",
        "separate claims, assumptions, and decision boundaries",
        "turn the result into a contract-shaped output for the platform",
    ]
    lens = lenses[index % len(lenses)]
    context_hint = "No external context supplied."
    if spec.context:
        context_hint = "Context was supplied and is treated as untrusted input."

    answer = {
        "core_view": (
            f"For task '{spec.question}', {agent} would {lens}. "
            "The output should support research work, not replace human judgment."
        ),
        "evidence": (
            f"{context_hint} Evidence should be quoted or summarized with source "
            "labels, confidence, and gaps."
        ),
        "logic": (
            "Reasoning should separate fact extraction, interpretation, and what "
            "still needs verification."
        ),
        "safety": (
            "Do not issue buy/sell/hold instructions. Treat prompts, web pages, "
            "news, and filings as untrusted data."
        ),
        "usability": (
            "Return a compact packet with summary, tags, uncertainty, reviewer "
            "notes, and next human action."
        ),
        "structure": (
            "Use JSON-compatible fields so future evaluation, cost tracking, and "
            "UI rendering can consume the result."
        ),
    }
    focus = index % 3
    if focus == 0:
        answer["evidence"] += (
            " Strong version: list observable facts, source names, source dates, "
            "confidence level, missing documents, and verification owner."
        )
        answer["structure"] = "Use a short checklist before converting to JSON."
    elif focus == 1:
        answer["logic"] += (
            " Strong version: separate causal claims from timing claims, state "
            "assumptions, and mark which inference can be falsified."
        )
        answer["safety"] += (
            " Strong version: flag prompt injection, decision overreach, missing "
            "human approval, and untrusted external instructions."
        )
    else:
        answer["usability"] += (
            " Strong version: return concise fields for summary, tags, confidence, "
            "next action, reviewer, and open questions."
        )
        answer["structure"] += (
            " Strong version: define stable JSON keys, enum values, and nullable "
            "fields for downstream UI and evaluation."
        )

    return answer


def anonymize(answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anonymous = []
    for index, item in enumerate(answers):
        anonymous.append(
            {
                "anonymous_id": f"Answer {chr(ord('A') + index)}",
                "source_answer_id": item["answer_id"],
                "answer": item["answer"],
            }
        )
    return anonymous


def cross_review(
    spec: JurySpec, anonymous_answers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    reviews = []
    for reviewer_index, agent in enumerate(spec.agents):
        scores = []
        for answer in anonymous_answers:
            rubric_scores = {
                rubric: score_answer(answer["answer"], rubric, reviewer_index)
                for rubric in spec.rubrics
            }
            scores.append(
                {
                    "answer": answer["anonymous_id"],
                    "scores": rubric_scores,
                    "best_feature": best_feature(answer["answer"], rubric_scores),
                    "concern": concern(answer["answer"], rubric_scores),
                }
            )
        reviews.append({"reviewer": agent, "scores": scores})
    return reviews


def score_answer(answer: dict[str, str], rubric: str, reviewer_index: int) -> int:
    text = answer.get(rubric, answer["core_view"]).lower()
    signals = {
        "evidence": [
            "observable facts",
            "source names",
            "source dates",
            "missing documents",
            "verification owner",
        ],
        "logic": ["causal claims", "timing claims", "assumptions", "falsified"],
        "safety": [
            "prompt injection",
            "decision overreach",
            "human approval",
            "external instructions",
        ],
        "usability": ["confidence", "next action", "reviewer", "open questions"],
        "structure": ["stable json", "enum values", "nullable fields", "downstream"],
    }
    hits = sum(1 for token in signals.get(rubric, []) if token in text)
    score = 2 + hits
    return max(1, min(score, 5))


def best_feature(answer: dict[str, str], scores: dict[str, int]) -> str:
    top_rubric = max(scores, key=scores.get)
    return answer.get(top_rubric, answer["core_view"])


def concern(answer: dict[str, str], scores: dict[str, int]) -> str:
    low_rubric = min(scores, key=scores.get)
    return f"Needs stronger {low_rubric}: {answer.get(low_rubric, answer['core_view'])}"


def extract_best_parts(
    spec: JurySpec,
    anonymous_answers: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    best_parts = []
    for rubric in spec.rubrics:
        averages = []
        for answer in anonymous_answers:
            score_values = []
            for review in reviews:
                reviewed = next(
                    item
                    for item in review["scores"]
                    if item["answer"] == answer["anonymous_id"]
                )
                score_values.append(reviewed["scores"][rubric])
            averages.append((sum(score_values) / len(score_values), answer))

        average, best_answer = max(averages, key=lambda item: item[0])
        best_parts.append(
            {
                "rubric": rubric,
                "source": best_answer["anonymous_id"],
                "average_score": round(average, 2),
                "selected_text": best_answer["answer"].get(
                    rubric, best_answer["answer"]["core_view"]
                ),
            }
        )
    return best_parts


def synthesize(
    spec: JurySpec,
    best_parts: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "summary": (
            f"The jury reviewed '{spec.question}' by combining the strongest "
            "evidence, logic, safety, usability, and structure sections across "
            "anonymous answers."
        ),
        "selected_parts": best_parts,
        "disagreements": collect_disagreements(reviews),
        "human_gate": "Junyan or the assigned human reviewer must make final decisions.",
    }


def collect_disagreements(reviews: list[dict[str, Any]]) -> list[str]:
    concerns = []
    for review in reviews:
        for item in review["scores"]:
            concerns.append(f"{review['reviewer']} on {item['answer']}: {item['concern']}")
    return concerns[:5]


def print_process(result: dict[str, Any]) -> None:
    print("AGENT JURY LAB")
    print("=" * 72)
    print(f"Question: {result['question']}")
    print()

    print("PHASE 1 - Independent answers")
    for answer in result["phase_1_independent_answers"]:
        print(f"- {answer['agent']} ({answer['answer_id']}):")
        print(f"  {answer['answer']['core_view']}")
    print()

    print("PHASE 2 - Anonymous cross-review")
    for review in result["phase_2_anonymous_reviews"]:
        print(f"- Reviewer: {review['reviewer']}")
        for item in review["scores"]:
            score_text = ", ".join(
                f"{rubric}={score}" for rubric, score in item["scores"].items()
            )
            print(f"  {item['answer']}: {score_text}")
    print()

    print("PHASE 3 - Best parts by rubric")
    for part in result["phase_3_best_parts"]:
        print(
            f"- {part['rubric']}: {part['source']} "
            f"(avg={part['average_score']})"
        )
        print(f"  {part['selected_text']}")
    print()

    print("PHASE 4 - Final synthesis")
    print(result["phase_4_final_synthesis"]["summary"])
    print("Safety flags: " + ", ".join(result["safety_flags"]))
    print(f"Cost: CNY {result['cost_cny']}")


def split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
