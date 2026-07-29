"""Smoke test for the Moonshot Kimi K3 adapter."""

from __future__ import annotations

from adapter import USAGE_PATH, chat_completion


def main() -> int:
    result = chat_completion(
        task_name="k0_smoke_intro",
        messages=[
            {
                "role": "system",
                "content": "你是 Kimi K3 接入冒烟测试；只用一句中文介绍自己，不提供投资建议。",
            },
            {"role": "user", "content": "请用一句话介绍你自己。"},
        ],
        max_tokens=80,
        reasoning_effort="low",
    )
    usage_record = result["usage_record"]

    print("Kimi K3 answer:")
    print(result["text"])
    print()
    print(f"Estimated cost: ¥{usage_record['estimated_cost_cny']}")
    print(f"Usage logged to: {USAGE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
