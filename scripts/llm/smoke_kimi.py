"""Smoke test for the Moonshot Kimi K3 adapter."""

from __future__ import annotations

from adapter import USAGE_PATH, chat_completion


def main() -> int:
    result = chat_completion(
        task_name="k0_smoke_intro",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a Kimi K3 adapter smoke test. Introduce yourself "
                    "in one short sentence and do not provide investment advice."
                ),
            },
            {"role": "user", "content": "Introduce yourself in one sentence."},
        ],
        prompt_version="k0_smoke_v1",
        max_tokens=80,
        reasoning_effort="low",
    )
    usage_record = result["usage_record"]

    print("Kimi K3 answer:")
    print(result["text"])
    print()
    print(f"Estimated cost: CNY {usage_record['estimated_cost_cny']}")
    print(f"Usage logged to: {USAGE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
