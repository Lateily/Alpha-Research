"""Offline contract tests for the provider-neutral AIOS AgentAdapter."""

from __future__ import annotations

import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))

from adapters import (  # noqa: E402
    AgentAdapter,
    AgentRequest,
    AgentStatus,
    DeterministicAdapter,
    UsageStatus,
    run_adapter,
)


def request(**overrides) -> AgentRequest:
    values = {
        "task_id": "A-013-test",
        "task_type": "low_risk_document",
        "input_payload": {"value": 7},
        "prompt_version": "a013_test_v1",
        "risk_level": "LOW",
        "timeout_seconds": 3,
        "evidence_grade": "E4",
        "network_policy": "deny",
    }
    values.update(overrides)
    return AgentRequest(**values)


def run(adapter: AgentAdapter, item: AgentRequest):
    fixed_times = iter(
        [
            datetime(2026, 8, 5, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 5, 0, 0, 1, tzinfo=timezone.utc),
        ]
    )
    fixed_timer = iter([10.0, 10.125])
    return run_adapter(
        adapter,
        item,
        run_id_factory=lambda: "run_test_001",
        now=lambda: next(fixed_times),
        timer=lambda: next(fixed_timer),
    )


def test_deterministic_success_has_common_envelope() -> None:
    result = run(DeterministicAdapter(), request())
    payload = result.to_dict()

    assert payload["status"] == "SUCCEEDED"
    assert payload["provider"] == "deterministic"
    assert payload["model"] is None
    assert payload["run_id"] == "run_test_001"
    assert payload["prompt_version"] == "a013_test_v1"
    assert payload["evidence_grade"] == "E4"
    assert payload["duration_ms"] == 125
    assert payload["output"] == {"value": 7}
    assert payload["usage"]["status"] == "NOT_APPLICABLE"
    assert payload["error"] is None
    json.dumps(payload)


def test_invalid_request_fails_closed_without_calling_worker() -> None:
    called = False

    def worker(_payload):
        nonlocal called
        called = True
        return {}

    result = run(DeterministicAdapter(worker), request(task_id=""))

    assert result.status is AgentStatus.SPEC_BLOCKED
    assert result.error is not None
    assert result.error.code == "INVALID_REQUEST"
    assert called is False


def test_bad_request_types_fail_closed() -> None:
    invalid_requests = [
        request(input_payload=[]),
        request(input_payload={"not_json": {1, 2}}),
        request(timeout_seconds=True),
        request(timeout_seconds=0),
        request(risk_level="UNKNOWN"),
        request(risk_level=[]),
        request(network_policy="open"),
        request(network_policy={}),
        request(evidence_grade="E5"),
        request(evidence_grade=[]),
    ]
    for item in invalid_requests:
        result = run(DeterministicAdapter(), item)
        assert result.status is AgentStatus.SPEC_BLOCKED
        assert result.error is not None
        assert result.error.code == "INVALID_REQUEST"


def test_unserializable_input_has_safe_hash_sentinel() -> None:
    result = run(
        DeterministicAdapter(),
        request(input_payload={"not_json": {1, 2}}),
    )

    assert result.status is AgentStatus.SPEC_BLOCKED
    assert result.input_hash == "UNAVAILABLE"


def test_timeout_is_structured_and_retryable() -> None:
    def timeout(_payload):
        raise TimeoutError("secret provider body")

    result = run(DeterministicAdapter(timeout), request())

    assert result.status is AgentStatus.TIMEOUT
    assert result.error is not None
    assert result.error.code == "TIMEOUT"
    assert result.error.retryable is True
    assert "secret provider body" not in json.dumps(result.to_dict())


def test_provider_error_is_structured_and_redacted() -> None:
    def fail(_payload):
        raise RuntimeError("Bearer super-secret-token")

    result = run(DeterministicAdapter(fail), request())
    serialized = json.dumps(result.to_dict())

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"
    assert "super-secret-token" not in serialized
    assert "RuntimeError" in result.error.message
    assert result.usage.status is UsageStatus.COST_UNKNOWN


def test_missing_model_attribute_cannot_break_failed_result() -> None:
    class ProviderWithoutModel(AgentAdapter):
        provider = "missing-model-test"

        def execute(self, _request):
            raise RuntimeError("provider failed")

    result = run(ProviderWithoutModel(), request())

    assert result.status is AgentStatus.FAILED
    assert result.provider == "missing-model-test"
    assert result.model is None
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"


def test_worker_must_return_mapping() -> None:
    result = run(DeterministicAdapter(lambda _payload: "bad output"), request())
    assert result.status is AgentStatus.FAILED
    assert result.error is not None


def test_input_hash_is_stable_and_does_not_expose_input() -> None:
    first = request(input_payload={"secret": "do-not-log", "n": 1})
    second = request(input_payload={"n": 1, "secret": "do-not-log"})

    assert first.input_hash() == second.input_hash()
    assert "do-not-log" not in first.input_hash()


def test_adapter_contract_uses_zero_network(monkeypatch=None) -> None:
    original_socket = socket.socket

    def blocked_socket(*_args, **_kwargs):
        raise AssertionError("network access is forbidden in adapter tests")

    socket.socket = blocked_socket
    try:
        result = run(DeterministicAdapter(), request())
    finally:
        socket.socket = original_socket

    assert result.status is AgentStatus.SUCCEEDED


def run_all_tests() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    return len(tests)


if __name__ == "__main__":
    test_count = run_all_tests()
    print(f"ALL AGENT ADAPTER OFFLINE TESTS PASS ({test_count} tests, 0 network calls)")
