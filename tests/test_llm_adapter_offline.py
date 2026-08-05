"""Offline tests for the K0 LLM adapter.

Run with:
    python tests/test_llm_adapter_offline.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))

import adapter  # noqa: E402
import test_agent_adapter_offline  # noqa: E402


def test_chat_completion_appends_jsonl_usage() -> None:
    messages = [
        {"role": "system", "content": "never store this sensitive system prompt"},
        {"role": "user", "content": "never store this sensitive user prompt"},
    ]

    captured = {}
    original_read_api_key = adapter._read_api_key
    original_post = adapter._post_chat_completion
    original_append = adapter.append_usage_record

    with tempfile.TemporaryDirectory() as tmp_dir:
        usage_path = Path(tmp_dir) / "llm_usage.jsonl"

        def fake_read_api_key() -> str:
            return "offline-test-key"

        def fake_post_chat_completion(api_key, payload, timeout_seconds):
            captured["api_key"] = api_key
            captured["payload"] = payload
            captured["timeout_seconds"] = timeout_seconds
            return {
                "choices": [
                    {"message": {"content": "I am the offline Kimi K3 test double."}}
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "cached_tokens": 20,
                    "completion_tokens": 10,
                },
            }

        def append_to_temp(record):
            original_append(record, usage_path=usage_path)

        try:
            adapter._read_api_key = fake_read_api_key
            adapter._post_chat_completion = fake_post_chat_completion
            adapter.append_usage_record = append_to_temp

            result = adapter.chat_completion(
                task_name="offline_mock",
                prompt_version="test_prompt_v1",
                messages=messages,
                max_tokens=16,
                reasoning_effort="low",
                timeout_seconds=3,
            )
        finally:
            adapter._read_api_key = original_read_api_key
            adapter._post_chat_completion = original_post
            adapter.append_usage_record = original_append

        assert result["text"] == "I am the offline Kimi K3 test double."
        assert captured["api_key"] == "offline-test-key"
        assert captured["payload"]["model"] == "kimi-k3"
        assert captured["payload"]["messages"] == messages
        assert usage_path.exists()

        lines = usage_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert "sensitive system prompt" not in lines[0]
        assert "sensitive user prompt" not in lines[0]

        record = json.loads(lines[0])
        assert record["ledger_schema"] == "llm_usage.v1"
        assert record["provider"] == "moonshot"
        assert record["model"] == "kimi-k3"
        assert record["task_name"] == "offline_mock"
        assert record["prompt_version"] == "test_prompt_v1"
        assert record["input_hash"].startswith("sha256:")
        assert record["input_tokens"] == 100
        assert record["cached_input_tokens"] == 20
        assert record["output_tokens"] == 10
        assert record["estimated_cost_usd"] == "0.00039600"
        assert record["estimated_cost_cny"] == "0.002851"
        assert record["run_id"].startswith("llm_")


if __name__ == "__main__":
    test_chat_completion_appends_jsonl_usage()
    harness_test_count = test_agent_adapter_offline.run_all_tests()
    print(
        "ALL LLM + AGENT ADAPTER OFFLINE TESTS PASS "
        f"({harness_test_count} Harness tests, 0 network calls)"
    )
