"""Zero-network deterministic adapter for Harness tests and safe tooling."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .base import AdapterOutput, AgentAdapter, AgentRequest, Usage


class DeterministicAdapter(AgentAdapter):
    provider = "deterministic"
    model = None

    def __init__(
        self,
        worker: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ) -> None:
        self._worker = worker or (lambda payload: dict(payload))

    def execute(self, request: AgentRequest) -> AdapterOutput:
        output = self._worker(request.input_payload)
        if not isinstance(output, Mapping):
            raise TypeError("deterministic worker must return a mapping")
        return AdapterOutput(output=dict(output), usage=Usage.not_applicable())
