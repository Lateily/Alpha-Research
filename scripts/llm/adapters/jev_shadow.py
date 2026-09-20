"""Offline-only typed-decision adapters for the Jev U4 shadow workflow."""

from __future__ import annotations

from typing import Any, Mapping

from typed_decision import normalize_typed_response

from .base import (
    AdapterExecutionError,
    AdapterOutput,
    AgentAdapter,
    AgentRequest,
    Usage,
)


class OfflineFixtureDecisionAdapter(AgentAdapter):
    """Return a normalized committed cassette without provider access."""

    provider = "offline_fixture"
    model = None

    def __init__(self, cassettes: Mapping[str, Mapping[str, Any]]) -> None:
        self._cassettes = dict(cassettes)

    def execute(self, request: AgentRequest) -> AdapterOutput:
        if request.network_policy != "deny":
            raise AdapterExecutionError(
                code="NETWORK_POLICY_REFUSED",
                message="offline fixture requires deny",
                retryable=False,
            )
        payload = request.input_payload
        key = f"{payload['state_hash']}:{payload['question_set']['version']}"
        if key not in self._cassettes:
            raise AdapterExecutionError(
                code="MODEL_UNAVAILABLE",
                message="no cassette for exact state",
                retryable=False,
                usage=Usage.not_applicable(),
            )
        output = normalize_typed_response(self._cassettes[key])
        return AdapterOutput(
            output=output,
            usage=Usage.not_applicable(),
            evidence_refs=(f"offline-cassette:{key}",),
        )


class DisabledTypeSafeJevAdapter(AgentAdapter):
    """Reserve the live provider name without making it reachable in v1."""

    provider = "typesafe_jev"
    model = None

    def execute(self, request: AgentRequest) -> AdapterOutput:
        raise AdapterExecutionError(
            code="LIVE_PROVIDER_NOT_INSTALLED",
            message="live TypeSafe Jev provider is not installed",
            retryable=False,
            usage=Usage.not_applicable(),
        )
