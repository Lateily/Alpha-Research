"""Offline contract tests for the provider-neutral AIOS AgentAdapter."""

from __future__ import annotations

import json
import shutil
import socket
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "llm"))

from adapters import (  # noqa: E402
    AgentAdapter,
    AgentRequest,
    AgentStatus,
    DeepSeekAdapter,
    DeterministicAdapter,
    RepositorySkillSelection,
    UsageStatus,
    run_adapter,
)
import adapters.base as base_module  # noqa: E402
import adapters.kimi as kimi_module  # noqa: E402
from ai_os.task_compiler import SPEC_READY, compile_task_manifest  # noqa: E402
from adapters.kimi import KimiAdapter  # noqa: E402
from capability import (  # noqa: E402
    CapabilityRecord,
    CapabilityRegistry,
    CapabilityStatus,
    RouteMode,
    RouteRequest,
    RouteStatus,
    route,
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


def run(
    adapter: AgentAdapter,
    item: AgentRequest,
    *,
    skill_selection: RepositorySkillSelection | None = None,
):
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
        skill_selection=skill_selection,
    )


def skill_selection(
    *,
    skill_ids: tuple[str, ...] = ("ar-divergent-reasoning",),
    executor_role: str = "aios-worker",
) -> RepositorySkillSelection:
    return RepositorySkillSelection(
        skill_ids=skill_ids,
        executor_role=executor_role,
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


def test_verified_skill_context_reaches_worker_and_provenance() -> None:
    captured = {}

    def worker(payload):
        captured.update(payload)
        return {"ok": True}

    original = request(input_payload={"prompt": "compare two architectures"})
    result = run(
        DeterministicAdapter(worker),
        original,
        skill_selection=skill_selection(),
    )

    assert result.status is AgentStatus.SUCCEEDED
    assert captured["messages"][0]["role"] == "system"
    assert '<repository_skill id="ar-divergent-reasoning"' in captured["messages"][0]["content"]
    assert captured["messages"][1] == {
        "role": "user",
        "content": "compare two architectures",
    }
    receipts = captured["_repository_skill_receipts"]
    assert receipts[0]["skill_id"] == "ar-divergent-reasoning"
    assert receipts[0]["prompt_version"] == "ar-divergent-reasoning-v1"
    assert receipts[0]["executor_role"] == "aios-worker"
    assert receipts[0]["context_sha256"].startswith("sha256:")
    assert receipts[0]["resources"] == []
    assert result.input_hash != original.input_hash()
    assert result.evidence_refs[0].startswith(
        "repository-skill:ar-divergent-reasoning@1.0.0:"
    )


def test_tampered_runtime_skill_is_blocked_before_worker() -> None:
    called = False

    def worker(_payload):
        nonlocal called
        called = True
        return {}

    with tempfile.TemporaryDirectory() as temp_dir:
        root = _runtime_fixture_root(Path(temp_dir))
        skill_file = root / ".agents/skills/ar-divergent-reasoning/SKILL.md"
        skill_file.write_text(
            skill_file.read_text(encoding="utf-8") + "\ntampered\n",
            encoding="utf-8",
        )
        with _runtime_root(root):
            result = run(
                DeterministicAdapter(worker),
                request(input_payload={"prompt": "must not execute"}),
                skill_selection=skill_selection(),
            )

    assert result.status is AgentStatus.SPEC_BLOCKED
    assert result.error is not None
    assert result.error.code == "SKILL_CONTEXT_BLOCKED"
    assert result.error.message == "repository skill context could not be verified"
    assert called is False


def test_runtime_role_denial_is_blocked_before_worker() -> None:
    called = False

    def worker(_payload):
        nonlocal called
        called = True
        return {}

    result = run(
        DeterministicAdapter(worker),
        request(input_payload={"prompt": "must not execute"}),
        skill_selection=skill_selection(executor_role="evidence-worker"),
    )

    assert result.status is AgentStatus.SPEC_BLOCKED
    assert result.error is not None
    assert result.error.code == "SKILL_CONTEXT_BLOCKED"
    assert called is False


def test_runtime_skill_cannot_expand_adapter_network_authority() -> None:
    called = False

    def worker(_payload):
        nonlocal called
        called = True
        return {}

    with tempfile.TemporaryDirectory() as temp_dir:
        root = _runtime_fixture_root(Path(temp_dir))
        registry_path = root / "config/aios-skills.v1.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["skills"][0]["network_policy"] = "ALLOWLIST"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        with _runtime_root(root):
            result = run(
                DeterministicAdapter(worker),
                request(
                    input_payload={"prompt": "must not execute"},
                    network_policy="provider_only",
                ),
                skill_selection=skill_selection(),
            )

    assert result.status is AgentStatus.SPEC_BLOCKED
    assert result.error is not None
    assert result.error.code == "SKILL_CONTEXT_BLOCKED"
    assert called is False


def test_oversized_verified_skill_context_is_blocked_before_worker() -> None:
    called = False

    def worker(_payload):
        nonlocal called
        called = True
        return {}

    with tempfile.TemporaryDirectory() as temp_dir:
        root = _runtime_fixture_root(Path(temp_dir))
        skill_file = root / ".agents/skills/ar-divergent-reasoning/SKILL.md"
        oversized = skill_file.read_text(encoding="utf-8") + ("\nlarge" * 12_000)
        skill_file.write_text(oversized, encoding="utf-8")
        registry_path = root / "config/aios-skills.v1.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["skills"][0]["sha256"] = (
            "sha256:" + sha256(oversized.encode("utf-8")).hexdigest()
        )
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        with _runtime_root(root):
            result = run(
                DeterministicAdapter(worker),
                request(input_payload={"prompt": "must not execute"}),
                skill_selection=skill_selection(),
            )

    assert result.status is AgentStatus.SPEC_BLOCKED
    assert result.error is not None
    assert result.error.code == "SKILL_CONTEXT_BLOCKED"
    assert called is False


def test_runtime_rejects_spoofed_skill_receipts_before_worker() -> None:
    called = False

    def worker(_payload):
        nonlocal called
        called = True
        return {}

    result = run(
        DeterministicAdapter(worker),
        request(
            input_payload={
                "prompt": "must not execute",
                "_repository_skill_receipts": [{"skill_id": "spoofed"}],
            }
        ),
        skill_selection=skill_selection(),
    )

    assert result.status is AgentStatus.SPEC_BLOCKED
    assert result.error is not None
    assert result.error.code == "SKILL_CONTEXT_BLOCKED"
    assert called is False


def test_runtime_selection_cannot_override_repository_root() -> None:
    try:
        RepositorySkillSelection(
            root=Path("/tmp/untrusted-repository"),
            skill_ids=("ar-divergent-reasoning",),
            executor_role="aios-worker",
        )
    except TypeError:
        pass
    else:
        raise AssertionError("repository root must not be caller-controlled")


def test_unexpected_skill_preflight_error_fails_closed_before_worker() -> None:
    called = False

    def worker(_payload):
        nonlocal called
        called = True
        return {}

    original = base_module._bind_repository_skills

    def fail_preflight(_request, _selection):
        raise RuntimeError("secret filesystem detail")

    base_module._bind_repository_skills = fail_preflight
    try:
        result = run(
            DeterministicAdapter(worker),
            request(input_payload={"prompt": "must not execute"}),
            skill_selection=skill_selection(),
        )
    finally:
        base_module._bind_repository_skills = original

    assert result.status is AgentStatus.SPEC_BLOCKED
    assert result.error is not None
    assert result.error.code == "SKILL_CONTEXT_BLOCKED"
    assert "secret filesystem detail" not in json.dumps(result.to_dict())
    assert called is False


def test_shared_skill_runtime_task_contract_is_spec_ready() -> None:
    source = json.loads(
        (REPO_ROOT / "scripts/llm/fixtures/shared_skill_runtime.task.json").read_text(
            encoding="utf-8"
        )
    )
    result = compile_task_manifest(
        source,
        now=datetime(2026, 8, 23, 14, 0, tzinfo=timezone.utc),
    )

    assert result.status == SPEC_READY
    assert result.errors == ()


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


def test_deepseek_offline_stub_uses_common_envelope() -> None:
    def offline_completion(payload, timeout_seconds):
        assert payload["model"] == "deepseek-v4-flash"
        assert payload["messages"] == [{"role": "user", "content": "summarize this packet"}]
        assert timeout_seconds == 3
        return {
            "choices": [
                {"message": {"content": "offline DeepSeek packet"}, "finish_reason": "stop"}
            ],
            "usage": {
                "prompt_tokens": 100,
                "prompt_cache_hit_tokens": 20,
                "prompt_cache_miss_tokens": 80,
                "completion_tokens": 10,
            },
        }

    offline_completion.offline_stub = True

    result = run(
        DeepSeekAdapter(completion=offline_completion),
        request(input_payload={"prompt": "summarize this packet"}),
    )

    assert result.status is AgentStatus.SUCCEEDED
    assert result.provider == "deepseek"
    assert result.model == "deepseek-v4-flash"
    assert result.output == {
        "text": "offline DeepSeek packet",
        "finish_reason": "stop",
        "provider_mode": "offline_stub",
        "no_trade_flag": True,
    }
    assert result.usage.status is UsageStatus.REPORTED
    assert result.usage.input_tokens == 100
    assert result.usage.cached_input_tokens == 20
    assert result.usage.output_tokens == 10
    assert result.usage.estimated_cost_cny == "0.000101"


def test_deepseek_offline_stub_receives_verified_skill_system_message() -> None:
    def offline_completion(payload, _timeout_seconds):
        messages = payload["messages"]
        assert messages[0]["role"] == "system"
        assert '<repository_skill id="ar-architecture-map"' in messages[0]["content"]
        assert messages[1] == {"role": "user", "content": "map this module"}
        return {
            "choices": [{"message": {"content": "offline map"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        }

    offline_completion.offline_stub = True
    result = run(
        DeepSeekAdapter(completion=offline_completion),
        request(input_payload={"prompt": "map this module"}),
        skill_selection=skill_selection(skill_ids=("ar-architecture-map",)),
    )

    assert result.status is AgentStatus.SUCCEEDED
    assert any(
        ref.startswith("repository-skill:ar-architecture-map@1.0.0:")
        for ref in result.evidence_refs
    )


def test_deepseek_injected_completion_must_be_declared_offline() -> None:
    def unsafe_completion(_payload, _timeout_seconds):
        return {"choices": [{"message": {"content": "should not run"}}]}

    result = run(
        DeepSeekAdapter(completion=unsafe_completion),
        request(input_payload={"prompt": "hello"}),
    )

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"


def test_deepseek_real_call_requires_provider_network_policy() -> None:
    def real_like_completion(_payload, _timeout_seconds):
        return {
            "choices": [{"message": {"content": "real-like response"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    result = run(
        DeepSeekAdapter(completion=real_like_completion, allow_real_call=True),
        request(input_payload={"prompt": "hello"}, network_policy="deny"),
    )

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"


def test_deepseek_real_call_requires_reported_usage() -> None:
    def real_like_completion(_payload, _timeout_seconds):
        return {"choices": [{"message": {"content": "missing usage"}}]}

    result = run(
        DeepSeekAdapter(completion=real_like_completion, allow_real_call=True),
        request(input_payload={"prompt": "hello"}, network_policy="provider_only"),
    )

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"


def test_deepseek_real_call_rejects_empty_usage() -> None:
    def real_like_completion(_payload, _timeout_seconds):
        return {
            "choices": [{"message": {"content": "empty usage"}}],
            "usage": {},
        }

    result = run(
        DeepSeekAdapter(completion=real_like_completion, allow_real_call=True),
        request(input_payload={"prompt": "hello"}, network_policy="provider_only"),
    )

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"


def test_deepseek_usage_rejects_bad_token_values() -> None:
    bad_usage_payloads = [
        {"prompt_tokens": -1, "completion_tokens": 1},
        {"prompt_tokens": True, "completion_tokens": 1},
        {"prompt_tokens": 1, "completion_tokens": "one"},
    ]

    for usage in bad_usage_payloads:
        def real_like_completion(_payload, _timeout_seconds, usage=usage):
            return {
                "choices": [{"message": {"content": "bad usage"}}],
                "usage": usage,
            }

        result = run(
            DeepSeekAdapter(completion=real_like_completion, allow_real_call=True),
            request(input_payload={"prompt": "hello"}, network_policy="provider_only"),
        )

        assert result.status is AgentStatus.FAILED
        assert result.error is not None
        assert result.error.code == "PROVIDER_ERROR"


def test_deepseek_usage_rejects_cache_mismatch() -> None:
    def real_like_completion(_payload, _timeout_seconds):
        return {
            "choices": [{"message": {"content": "cache mismatch"}}],
            "usage": {
                "prompt_tokens": 10,
                "prompt_cache_hit_tokens": 6,
                "prompt_cache_miss_tokens": 5,
                "completion_tokens": 1,
            },
        }

    result = run(
        DeepSeekAdapter(completion=real_like_completion, allow_real_call=True),
        request(input_payload={"prompt": "hello"}, network_policy="provider_only"),
    )

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"


def test_deepseek_real_call_rejects_unofficial_origin_before_completion() -> None:
    called = False

    def real_like_completion(_payload, _timeout_seconds):
        nonlocal called
        called = True
        return {
            "choices": [{"message": {"content": "should not call"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    result = run(
        DeepSeekAdapter(
            base_url="https://attacker.invalid",
            completion=real_like_completion,
            allow_real_call=True,
        ),
        request(input_payload={"prompt": "hello"}, network_policy="provider_only"),
    )

    assert called is False
    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"


def test_deepseek_real_output_carries_no_trade_flag() -> None:
    def real_like_completion(_payload, _timeout_seconds):
        return {
            "choices": [{"message": {"content": "real-like response"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    result = run(
        DeepSeekAdapter(completion=real_like_completion, allow_real_call=True),
        request(input_payload={"prompt": "hello"}, network_policy="provider_only"),
    )

    assert result.status is AgentStatus.SUCCEEDED
    assert result.output is not None
    assert result.output["no_trade_flag"] is True


def test_deepseek_real_call_rejects_empty_choices() -> None:
    def real_like_completion(_payload, _timeout_seconds):
        return {
            "choices": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    result = run(
        DeepSeekAdapter(completion=real_like_completion, allow_real_call=True),
        request(input_payload={"prompt": "hello"}, network_policy="provider_only"),
    )

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"


def test_deepseek_real_call_rejects_empty_content() -> None:
    def real_like_completion(_payload, _timeout_seconds):
        return {
            "choices": [{"message": {"content": ""}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    result = run(
        DeepSeekAdapter(completion=real_like_completion, allow_real_call=True),
        request(input_payload={"prompt": "hello"}, network_policy="provider_only"),
    )

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"


def test_deepseek_real_call_rejects_zero_live_tokens() -> None:
    def real_like_completion(_payload, _timeout_seconds):
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

    result = run(
        DeepSeekAdapter(completion=real_like_completion, allow_real_call=True),
        request(input_payload={"prompt": "hello"}, network_policy="provider_only"),
    )

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"


def kimi_request(**overrides) -> AgentRequest:
    values = {
        "task_id": "A-013-kimi-test",
        "task_type": "event_tagging",
        "input_payload": {
            "messages": [{"role": "user", "content": "offline fixture"}],
            "max_tokens": 32,
            "reasoning_effort": "low",
        },
        "prompt_version": "kimi_wrapper_test_v1",
        "risk_level": "LOW",
        "timeout_seconds": 5,
        "evidence_grade": "E4",
        "network_policy": "provider_only",
    }
    values.update(overrides)
    return AgentRequest(**values)


def test_kimi_wrapper_maps_reported_usage_without_network() -> None:
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return {
            "text": "offline Kimi result",
            "response": {"must_not": "escape into AgentResult"},
            "usage_record": {
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "output_tokens": 10,
                "estimated_cost_cny": "0.002851",
            },
        }

    result = run(
        KimiAdapter(fake_completion, offline_stub=True),
        kimi_request(),
    )

    assert result.status is AgentStatus.SUCCEEDED
    assert result.provider == "moonshot"
    assert result.model == "kimi-k3"
    assert result.output == {"text": "offline Kimi result"}
    assert result.usage.status is UsageStatus.REPORTED
    assert result.usage.input_tokens == 100
    assert result.usage.cached_input_tokens == 20
    assert result.usage.output_tokens == 10
    assert result.usage.estimated_cost_cny == "0.002851"
    assert captured["task_name"] == "event_tagging"
    assert captured["prompt_version"] == "kimi_wrapper_test_v1"
    assert captured["timeout_seconds"] == 5
    assert "must_not" not in json.dumps(result.to_dict())


def test_kimi_offline_stub_receives_verified_skill_system_message() -> None:
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return {"text": "offline", "usage_record": None}

    result = run(
        KimiAdapter(fake_completion, offline_stub=True),
        kimi_request(),
        skill_selection=skill_selection(skill_ids=("ar-architecture-map",)),
    )

    assert result.status is AgentStatus.SUCCEEDED
    assert captured["messages"][0]["role"] == "system"
    assert (
        '<repository_skill id="ar-architecture-map"'
        in captured["messages"][0]["content"]
    )
    assert captured["messages"][1] == {
        "role": "user",
        "content": "offline fixture",
    }


def test_kimi_wrapper_missing_usage_is_cost_unknown() -> None:
    result = run(
        KimiAdapter(
            lambda **_kwargs: {"text": "offline"},
            offline_stub=True,
        ),
        kimi_request(),
    )
    assert result.status is AgentStatus.SUCCEEDED
    assert result.usage.status is UsageStatus.COST_UNKNOWN
    assert result.usage.estimated_cost_cny is None


def test_kimi_real_mode_requires_reported_usage() -> None:
    original_completion = kimi_module.legacy_kimi.chat_completion
    kimi_module.legacy_kimi.chat_completion = lambda **_kwargs: {"text": "offline"}
    try:
        result = run(KimiAdapter(allow_real_call=True), kimi_request())
    finally:
        kimi_module.legacy_kimi.chat_completion = original_completion

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"
    assert result.usage.status is UsageStatus.COST_UNKNOWN


def test_kimi_injected_callable_real_mode_requires_reported_usage() -> None:
    result = run(
        KimiAdapter(
            lambda **_kwargs: {"text": "offline injected fixture"},
            allow_real_call=True,
        ),
        kimi_request(),
    )

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"
    assert result.usage.status is UsageStatus.COST_UNKNOWN


def test_kimi_real_mode_accepts_complete_reported_usage() -> None:
    def fake_legacy_completion(**_kwargs):
        return {
            "text": "offline real-mode fixture",
            "usage_record": {
                "input_tokens": 8,
                "cached_input_tokens": 2,
                "output_tokens": 3,
                "estimated_cost_cny": "0.000900",
            },
        }

    original_completion = kimi_module.legacy_kimi.chat_completion
    kimi_module.legacy_kimi.chat_completion = fake_legacy_completion
    try:
        result = run(KimiAdapter(allow_real_call=True), kimi_request())
    finally:
        kimi_module.legacy_kimi.chat_completion = original_completion

    assert result.status is AgentStatus.SUCCEEDED
    assert result.output == {"text": "offline real-mode fixture"}
    assert result.usage.status is UsageStatus.REPORTED
    assert result.usage.estimated_cost_cny == "0.000900"


def test_kimi_wrapper_real_call_is_frozen_by_default() -> None:
    result = run(KimiAdapter(), kimi_request())
    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"
    assert result.usage.status is UsageStatus.COST_UNKNOWN


def test_kimi_injected_callable_requires_explicit_offline_stub() -> None:
    result = run(
        KimiAdapter(lambda **_kwargs: {"text": "must not run"}),
        kimi_request(),
    )

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.message == "PermissionError during provider execution"


def test_kimi_offline_stub_cannot_reach_network_through_wrapper() -> None:
    attempted = False

    def wrapped_legacy(**_kwargs):
        nonlocal attempted
        attempted = True
        socket.create_connection(("api.moonshot.cn", 443))
        return {"text": "must not run"}

    result = run(
        KimiAdapter(wrapped_legacy, offline_stub=True),
        kimi_request(),
    )

    assert attempted is True
    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.message == "PermissionError during provider execution"


def test_kimi_rejects_contradictory_execution_flags() -> None:
    try:
        KimiAdapter(
            lambda **_kwargs: {"text": "must not run"},
            allow_real_call=True,
            offline_stub=True,
        )
    except ValueError as exc:
        assert "mutually exclusive" in str(exc)
    else:
        raise AssertionError("contradictory execution flags must be rejected")


def test_kimi_paid_call_ledger_failure_is_preserved_and_not_retryable() -> None:
    preserved = []
    original_read_key = kimi_module.legacy_kimi._read_api_key
    original_post = kimi_module.legacy_kimi._post_chat_completion
    original_append = kimi_module.legacy_kimi.append_usage_record
    original_spool = kimi_module.legacy_kimi.append_usage_spool

    kimi_module.legacy_kimi._read_api_key = lambda: "offline-test-key"
    kimi_module.legacy_kimi._post_chat_completion = lambda *_args, **_kwargs: {
        "choices": [{"message": {"content": "paid offline fixture"}}],
        "usage": {
            "prompt_tokens": 10,
            "cached_tokens": 2,
            "completion_tokens": 3,
        },
    }
    kimi_module.legacy_kimi.append_usage_record = lambda _record: (_ for _ in ()).throw(
        NotADirectoryError("primary ledger unavailable")
    )
    kimi_module.legacy_kimi.append_usage_spool = lambda record: preserved.append(record)
    try:
        result = run(KimiAdapter(allow_real_call=True), kimi_request())
    finally:
        kimi_module.legacy_kimi._read_api_key = original_read_key
        kimi_module.legacy_kimi._post_chat_completion = original_post
        kimi_module.legacy_kimi.append_usage_record = original_append
        kimi_module.legacy_kimi.append_usage_spool = original_spool

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "USAGE_LEDGER_WRITE_FAILED"
    assert result.error.retryable is False
    assert result.usage.status is UsageStatus.REPORTED
    assert len(preserved) == 1
    assert preserved[0]["estimated_cost_cny"] == result.usage.estimated_cost_cny


def test_kimi_legacy_callable_cannot_masquerade_as_offline_stub() -> None:
    result = run(
        KimiAdapter(
            kimi_module.legacy_kimi.chat_completion,
            offline_stub=True,
        ),
        kimi_request(),
    )

    assert result.status is AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == "PROVIDER_ERROR"
    assert result.error.message == "PermissionError during provider execution"


def test_kimi_wrapper_denies_wrong_network_policy() -> None:
    called = False

    def fake_completion(**_kwargs):
        nonlocal called
        called = True
        return {"text": "must not run"}

    result = run(
        KimiAdapter(fake_completion, offline_stub=True),
        kimi_request(network_policy="deny"),
    )
    assert result.status is AgentStatus.FAILED
    assert called is False


def test_kimi_wrapper_timeout_and_secret_error_are_structured() -> None:
    def timeout(**_kwargs):
        raise TimeoutError("sk-SECRET123 ghp_LEAK")

    result = run(KimiAdapter(timeout, offline_stub=True), kimi_request())
    serialized = json.dumps(result.to_dict())

    assert result.status is AgentStatus.TIMEOUT
    assert "sk-SECRET123" not in serialized
    assert "ghp_LEAK" not in serialized


def test_kimi_wrapper_rejects_bad_messages_without_calling_provider() -> None:
    called = False

    def fake_completion(**_kwargs):
        nonlocal called
        called = True
        return {"text": "must not run"}

    result = run(
        KimiAdapter(fake_completion, offline_stub=True),
        kimi_request(input_payload={"messages": []}),
    )

    assert result.status is AgentStatus.FAILED
    assert called is False


def capability(
    agent: str,
    *,
    task_type: str = "schema_check",
    status: CapabilityStatus = CapabilityStatus.PRODUCTION_ELIGIBLE,
    deterministic: bool = False,
    tools=frozenset({"read_repo"}),
    scopes=("docs",),
    networks=frozenset({"deny"}),
    cost="0.10",
    eval_version="eval_v1",
    eval_score="20",
) -> CapabilityRecord:
    return CapabilityRecord(
        agent=agent,
        task_type=task_type,
        tool_access=tools,
        file_scope=scopes,
        network_access=networks,
        status=status,
        cost_cny_per_run=cost,
        eval_version=eval_version,
        eval_score=eval_score,
        deterministic=deterministic,
    )


def route_request(**overrides) -> RouteRequest:
    values = {
        "task_type": "schema_check",
        "mode": RouteMode.PRODUCTION,
        "required_tools": frozenset({"read_repo"}),
        "target_paths": ("docs/llm/example.md",),
        "network_policy": "deny",
        "risk_level": "LOW",
        "budget_max_cny": "1.00",
    }
    values.update(overrides)
    return RouteRequest(**values)


def test_capability_router_prefers_deterministic_worker() -> None:
    registry = CapabilityRegistry(
        [
            capability("kimi", cost="0.01"),
            capability(
                "deterministic",
                deterministic=True,
                cost="0",
                eval_version=None,
                eval_score=None,
            ),
        ]
    )
    decision = route(registry, route_request())
    assert decision.status is RouteStatus.SELECTED
    assert decision.selected_agent == "deterministic"


def test_capability_router_deterministic_priority_beats_lower_model_cost() -> None:
    registry = CapabilityRegistry(
        [
            capability("kimi", cost="1"),
            capability(
                "deterministic",
                deterministic=True,
                cost="5",
                eval_version=None,
                eval_score=None,
            ),
        ]
    )
    decision = route(registry, route_request(budget_max_cny="10"))
    assert decision.status is RouteStatus.SELECTED
    assert decision.selected_agent == "deterministic"


def test_capability_router_blocks_shadow_only_from_production() -> None:
    registry = CapabilityRegistry(
        [capability("kimi", status=CapabilityStatus.SHADOW_ONLY)]
    )
    decision = route(registry, route_request())
    assert decision.status is RouteStatus.NO_ELIGIBLE_CAPABILITY
    assert "kimi: not production eligible" in decision.reasons


def test_capability_router_allows_shadow_only_in_shadow_mode() -> None:
    registry = CapabilityRegistry(
        [capability("kimi", status=CapabilityStatus.SHADOW_ONLY)]
    )
    decision = route(registry, route_request(mode=RouteMode.SHADOW))
    assert decision.status is RouteStatus.SELECTED
    assert decision.selected_agent == "kimi"


def test_capability_router_filters_task_type_before_selection() -> None:
    registry = CapabilityRegistry([capability("translator", task_type="translate")])
    decision = route(registry, route_request(task_type="summarize"))
    assert decision.status is RouteStatus.NO_ELIGIBLE_CAPABILITY
    assert decision.selected_agent is None
    assert "translator: task_type mismatch" in decision.reasons


def test_capability_router_suspended_and_retired_are_kill_switches() -> None:
    for status in (CapabilityStatus.SUSPENDED, CapabilityStatus.RETIRED):
        registry = CapabilityRegistry([capability("kimi", status=status)])
        for mode in (RouteMode.SHADOW, RouteMode.PRODUCTION):
            decision = route(registry, route_request(mode=mode))
            assert decision.status is RouteStatus.NO_ELIGIBLE_CAPABILITY
            assert decision.selected_agent is None
            assert f"kimi: status={status.value}" in decision.reasons


def test_capability_router_enforces_tools_network_scope_and_budget() -> None:
    cases = [
        route_request(required_tools=frozenset({"write_repo"})),
        route_request(network_policy="provider_only"),
        route_request(target_paths=("scripts/llm/adapter.py",)),
        route_request(budget_max_cny="0.01"),
    ]
    registry = CapabilityRegistry([capability("kimi")])
    for request_item in cases:
        decision = route(registry, request_item)
        assert decision.status is RouteStatus.NO_ELIGIBLE_CAPABILITY


def test_capability_router_blocks_unknown_cost_under_budget() -> None:
    registry = CapabilityRegistry([capability("kimi", cost=None)])
    decision = route(registry, route_request())
    assert decision.status is RouteStatus.NO_ELIGIBLE_CAPABILITY
    assert "kimi: cost unknown under finite budget" in decision.reasons


def test_capability_router_blocks_high_risk_until_reviewer_capabilities_are_wired() -> None:
    registry = CapabilityRegistry(
        [capability("codex"), capability("claude", task_type="review")]
    )
    for risk_level in ("HIGH", "CONSTITUTIONAL"):
        for reviewer_agent in (None, "codex", "claude", "nonexistent-reviewer"):
            decision = route(
                registry,
                route_request(
                    risk_level=risk_level,
                    reviewer_agent=reviewer_agent,
                ),
            )
            assert decision.status is RouteStatus.SPEC_BLOCKED
            assert decision.selected_agent is None
            assert (
                "high-risk routing is blocked until reviewer capabilities are wired"
                in decision.reasons
            )


def test_capability_router_blocks_high_risk_even_with_reviewer_name_alias() -> None:
    registry = CapabilityRegistry([capability("Codex")])
    decision = route(
        registry,
        route_request(risk_level="HIGH", reviewer_agent="  codex  "),
    )
    assert decision.status is RouteStatus.SPEC_BLOCKED
    assert (
        "high-risk routing is blocked until reviewer capabilities are wired"
        in decision.reasons
    )


def test_capability_router_blocks_medium_production_without_review_contract() -> None:
    registry = CapabilityRegistry(
        [capability("codex"), capability("claude", task_type="review")]
    )
    for reviewer_agent in (None, "codex", "claude", "nonexistent-reviewer"):
        decision = route(
            registry,
            route_request(
                mode=RouteMode.PRODUCTION,
                risk_level="MEDIUM",
                reviewer_agent=reviewer_agent,
            ),
        )
        assert decision.status is RouteStatus.SPEC_BLOCKED
        assert decision.selected_agent is None
        assert (
            "medium-risk production routing is blocked until reviewer "
            "capabilities are wired"
            in decision.reasons
        )


def test_capability_router_allows_medium_shadow_without_production_authority() -> None:
    registry = CapabilityRegistry(
        [
            capability(
                "event_tagger",
                task_type="event_tagging",
                status=CapabilityStatus.SHADOW_ONLY,
            )
        ]
    )
    decision = route(
        registry,
        route_request(
            task_type="event_tagging",
            mode=RouteMode.SHADOW,
            risk_level="MEDIUM",
        ),
    )
    assert decision.status is RouteStatus.SELECTED
    assert decision.mode is RouteMode.SHADOW
    assert decision.selected_agent == "event_tagger"


def test_capability_router_prefers_lower_cost_then_stable_name() -> None:
    lower_cost = route(
        CapabilityRegistry(
            [capability("alpha", cost="0.20"), capability("zulu", cost="0.10")]
        ),
        route_request(),
    )
    stable_tie = route(
        CapabilityRegistry(
            [capability("Zulu", cost="0.10"), capability("alpha", cost="0.10")]
        ),
        route_request(),
    )
    assert lower_cost.selected_agent == "zulu"
    assert stable_tie.selected_agent == "alpha"


def test_capability_router_rejects_noncanonical_task_types() -> None:
    for task_type in (" schema_check", "schema_check ", "SCHEMA_CHECK"):
        try:
            CapabilityRegistry([capability("codex", task_type=task_type)])
        except ValueError as exc:
            assert "task_type must be a canonical lowercase token" in str(exc)
        else:
            raise AssertionError("noncanonical capability task_type must fail closed")

        decision = route(
            CapabilityRegistry([capability("codex")]),
            route_request(task_type=task_type),
        )
        assert decision.status is RouteStatus.SPEC_BLOCKED
        assert "task_type must be a canonical lowercase token" in decision.reasons


def test_route_decision_preserves_requested_mode() -> None:
    registry = CapabilityRegistry(
        [capability("kimi", status=CapabilityStatus.SHADOW_ONLY)]
    )
    decision = route(registry, route_request(mode=RouteMode.SHADOW))
    assert decision.mode is RouteMode.SHADOW


def test_capability_router_normalizes_file_scopes_before_matching() -> None:
    registry = CapabilityRegistry(
        [capability("deterministic", deterministic=True, scopes=("docs//llm/",))]
    )
    decision = route(
        registry,
        route_request(target_paths=("docs/llm/example.md",)),
    )
    assert decision.status is RouteStatus.SELECTED


def test_capability_registry_rejects_qualification_leaks_and_duplicates() -> None:
    invalid = capability("kimi", eval_version=None, eval_score=None)
    try:
        CapabilityRegistry([invalid])
    except ValueError as exc:
        assert "requires task-specific eval" in str(exc)
    else:
        raise AssertionError("unassessed model must not become production eligible")

    duplicate = capability("kimi")
    try:
        CapabilityRegistry([duplicate, duplicate])
    except ValueError as exc:
        assert "duplicate capability" in str(exc)
    else:
        raise AssertionError("duplicate agent/task capability must be rejected")


def test_capability_router_spec_blocks_unsafe_paths_and_bad_budget() -> None:
    registry = CapabilityRegistry([capability("deterministic", deterministic=True)])
    for request_item in (
        route_request(target_paths=("../../secret",)),
        route_request(target_paths=("/absolute/path",)),
        route_request(budget_max_cny="free"),
    ):
        decision = route(registry, request_item)
        assert decision.status is RouteStatus.SPEC_BLOCKED


def test_capability_registry_rejects_malformed_runtime_types() -> None:
    malformed = [
        capability("kimi", status="PRODUCTION_ELIGIBLE"),
        capability("kimi", tools=["read_repo"]),
        capability("kimi", scopes=["docs"]),
        capability("kimi", networks=["deny"]),
        capability("kimi", deterministic="yes"),
    ]
    for record in malformed:
        try:
            CapabilityRegistry([record])
        except ValueError:
            pass
        else:
            raise AssertionError("malformed capability type must fail closed")


def test_capability_router_spec_blocks_malformed_runtime_types() -> None:
    registry = CapabilityRegistry([capability("deterministic", deterministic=True)])
    malformed = [
        route_request(mode="PRODUCTION"),
        route_request(required_tools=["read_repo"]),
        route_request(target_paths=["docs/llm/example.md"]),
    ]
    for request_item in malformed:
        decision = route(registry, request_item)
        assert decision.status is RouteStatus.SPEC_BLOCKED


def _runtime_fixture_root(temp_root: Path) -> Path:
    root = temp_root / "repo"
    source_skill = REPO_ROOT / ".agents/skills/ar-divergent-reasoning"
    target_skill = root / ".agents/skills/ar-divergent-reasoning"
    target_skill.parent.mkdir(parents=True)
    shutil.copytree(source_skill, target_skill)

    source_registry = json.loads(
        (REPO_ROOT / "config/aios-skills.v1.json").read_text(encoding="utf-8")
    )
    selected = [
        entry
        for entry in source_registry["skills"]
        if entry["skill_id"] == "ar-divergent-reasoning"
    ]
    registry_path = root / "config/aios-skills.v1.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps({"schema": source_registry["schema"], "skills": selected}),
        encoding="utf-8",
    )
    return root


@contextmanager
def _runtime_root(root: Path):
    original = base_module._REPOSITORY_ROOT
    base_module._REPOSITORY_ROOT = root
    try:
        yield
    finally:
        base_module._REPOSITORY_ROOT = original


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
