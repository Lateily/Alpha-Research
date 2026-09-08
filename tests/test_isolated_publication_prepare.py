#!/usr/bin/env python3
"""Offline tests for freeze-before-build publication preparation."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.macro_os import collectors  # noqa: E402
from scripts import isolated_publication_prepare as prepare  # noqa: E402


NOW = datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc)


def _request(_now, _env):
    return collectors.HttpRequest(
        method="POST",
        url="https://data.example.test/series?api_key=secret",
        public_locator="https://data.example.test/series",
        headers={"Content-Type": "application/json", "Authorization": "secret"},
        body=json.dumps({"series": "S1", "registrationkey": "secret"}).encode(),
        allowed_hosts=("data.example.test",),
    )


def _parser(raw, fetched_at, _spec):
    payload = json.loads(raw)
    if payload != {"series": "S1", "value": 7}:
        raise ValueError("fixture response mismatch")
    return [
        collectors.Observation(
            series_id="series_one",
            metric_key="value",
            observation_at="2026-09-07T00:00:00Z",
            vintage_at=fetched_at,
            value_text="7",
            value=7.0,
            unit="index",
        )
    ]


SPEC = collectors.RequestSpec(
    request_id="fixture_series",
    source_id="fixture_source",
    metrics=(
        collectors.MetricSpec(
            "series_one", "value", "S1", "index", "daily", 86400, 86400
        ),
    ),
    build_request=_request,
    parser=_parser,
)


class FixtureTransport:
    def __init__(self):
        self.calls = 0

    def fetch(self, _request):
        self.calls += 1
        return collectors.HttpResponse(
            status=200,
            final_url="https://data.example.test/series?token=must-not-persist",
            headers={"content-type": "application/json", "set-cookie": "secret"},
            body=json.dumps({"series": "S1", "value": 7}).encode(),
        )


class IsolatedPublicationPreparationTests(unittest.TestCase):
    def test_capture_redacts_request_secrets_and_replays_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "frozen"
            live = FixtureTransport()
            manifest = prepare.freeze_macro_inputs(
                bundle,
                specs=(SPEC,),
                as_of=NOW,
                transport=live,
                environment={"BLS_API_KEY": "secret"},
            )

            self.assertEqual(1, live.calls)
            self.assertEqual("FROZEN", manifest["status"])
            self.assertNotIn("secret", json.dumps(manifest).lower())
            replay = prepare.FrozenTransport(
                bundle,
                specs=(SPEC,),
                as_of=NOW,
                environment={},
            )
            response = replay.fetch(_request(NOW, {}))
            self.assertEqual({"series": "S1", "value": 7}, json.loads(response.body))
            replay.assert_consumed()

    def test_tampered_frozen_bytes_stop_before_run_id_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "frozen"
            prepare.freeze_macro_inputs(
                bundle,
                specs=(SPEC,),
                as_of=NOW,
                transport=FixtureTransport(),
                environment={"BLS_API_KEY": "secret"},
            )
            body = next((bundle / "responses").iterdir())
            body.write_bytes(b"tampered")
            events = []

            with self.assertRaisesRegex(prepare.PreparationError, "hash"):
                prepare.run_after_verified_freeze(
                    bundle,
                    specs=(SPEC,),
                    as_of=NOW,
                    environment={},
                    run_id_factory=lambda: events.append("run_id") or "isolated_run",
                    builder=lambda _run_id, _transport: events.append("build"),
                )

            self.assertEqual([], events)

    def test_verified_freeze_precedes_run_id_and_offline_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "frozen"
            prepare.freeze_macro_inputs(
                bundle,
                specs=(SPEC,),
                as_of=NOW,
                transport=FixtureTransport(),
                environment={"BLS_API_KEY": "secret"},
            )
            events = []

            result = prepare.run_after_verified_freeze(
                bundle,
                specs=(SPEC,),
                as_of=NOW,
                environment={},
                run_id_factory=lambda: events.append("run_id") or "isolated_run",
                builder=lambda run_id, transport: (
                    events.append("build"),
                    transport.fetch(_request(NOW, {})),
                    transport.assert_consumed(),
                    {"run_id": run_id},
                )[-1],
                event_sink=events.append,
            )

            self.assertEqual(
                ["freeze_verified", "run_id", "run_id_created", "build", "build_completed"],
                events,
            )
            self.assertEqual({"run_id": "isolated_run"}, result)

    def test_isolated_macro_build_writes_no_publication_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio = root / "portfolio-template.json"
            portfolio.write_text(
                json.dumps(
                    {
                        "run_id": "HISTORICAL_RUN",
                        "target_trade_date": "20260904",
                        "data": {"paper_only": True},
                    }
                ),
                encoding="utf-8",
            )
            bundle = root / "frozen"
            prepare.freeze_macro_inputs(
                bundle,
                specs=(SPEC,),
                as_of=NOW,
                transport=FixtureTransport(),
                environment={"BLS_API_KEY": "secret"},
                local_inputs={"portfolio_template": portfolio},
            )
            events = []

            def fake_macro_builder(**kwargs):
                events.append("macro_builder")
                transport = kwargs["transport"]
                transport.fetch(_request(NOW, {}))
                output = Path(kwargs["output_dir"])
                output.mkdir(parents=True, exist_ok=True)
                for index in range(10):
                    (output / f"macro-{index}.json").write_text("{}", encoding="utf-8")
                return {"run_id": kwargs["run_id"], "report": "DATA_BLOCKED"}

            receipt = prepare.build_isolated_macro_run(
                bundle,
                output_root=root / "isolated-output",
                target_trade_date="20260904",
                specs=(SPEC,),
                environment={},
                run_id_factory=lambda: events.append("run_id") or "isolated_20260904_test",
                macro_builder=fake_macro_builder,
            )

            self.assertEqual(["run_id", "macro_builder"], events)
            self.assertEqual("ISOLATED_BUILD_COMPLETE", receipt["status"])
            self.assertEqual(False, receipt["authority"]["publication"])
            run_root = root / "isolated-output" / "runs" / "isolated_20260904_test"
            self.assertTrue((run_root / "isolated_preparation_manifest.json").is_file())
            self.assertEqual(receipt, prepare.validate_isolated_run(run_root))
            self.assertFalse((root / "isolated-output" / "current_run.json").exists())
            staged = json.loads(
                (run_root / "inputs" / "model_portfolio_state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("isolated_20260904_test", staged["run_id"])
            self.assertEqual("20260904", staged["target_trade_date"])
            (run_root / "macro" / "macro-0.json").write_text(
                '{"tampered":true}', encoding="utf-8"
            )
            with self.assertRaisesRegex(prepare.PreparationError, "artifact hash"):
                prepare.validate_isolated_run(run_root)

    def test_local_input_tamper_stops_before_run_id_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio = root / "portfolio-template.json"
            portfolio.write_text('{"data":{"paper_only":true}}', encoding="utf-8")
            bundle = root / "frozen"
            prepare.freeze_macro_inputs(
                bundle,
                specs=(SPEC,),
                as_of=NOW,
                transport=FixtureTransport(),
                environment={"BLS_API_KEY": "secret"},
                local_inputs={"portfolio_template": portfolio},
            )
            (bundle / "inputs" / "portfolio_template.json").write_text(
                '{"data":{"paper_only":false}}', encoding="utf-8"
            )
            events = []

            with self.assertRaisesRegex(prepare.PreparationError, "local input hash"):
                prepare.build_isolated_macro_run(
                    bundle,
                    output_root=root / "isolated-output",
                    target_trade_date="20260904",
                    specs=(SPEC,),
                    environment={},
                    run_id_factory=lambda: events.append("run_id") or "must_not_exist",
                    macro_builder=lambda **_kwargs: None,
                )

            self.assertEqual([], events)

    def test_isolated_builder_cannot_create_current_run_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio = root / "portfolio-template.json"
            portfolio.write_text('{"data":{"paper_only":true}}', encoding="utf-8")
            bundle = root / "frozen"
            prepare.freeze_macro_inputs(
                bundle,
                specs=(SPEC,),
                as_of=NOW,
                transport=FixtureTransport(),
                environment={"BLS_API_KEY": "secret"},
                local_inputs={"portfolio_template": portfolio},
            )

            def pointer_writing_builder(**kwargs):
                transport = kwargs["transport"]
                transport.fetch(_request(NOW, {}))
                output = Path(kwargs["output_dir"])
                output.mkdir(parents=True, exist_ok=True)
                (output / "current_run.json").write_text("{}", encoding="utf-8")
                return {"run_id": kwargs["run_id"], "report": "DATA_BLOCKED"}

            with self.assertRaisesRegex(prepare.PreparationError, "current_run"):
                prepare.build_isolated_macro_run(
                    bundle,
                    output_root=root / "isolated-output",
                    target_trade_date="20260904",
                    specs=(SPEC,),
                    environment={},
                    run_id_factory=lambda: "isolated_20260904_pointer_attack",
                    macro_builder=pointer_writing_builder,
                )
            self.assertFalse(
                (
                    root
                    / "isolated-output"
                    / "runs"
                    / "isolated_20260904_pointer_attack"
                ).exists()
            )
            self.assertFalse(
                (root / "isolated-output" / "current_run.json").exists()
            )

    def test_ci_executes_isolated_preparation_regressions(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "python-ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("python3 tests/test_network_layer_diagnostic.py", workflow)
        self.assertIn("python3 tests/test_isolated_publication_prepare.py", workflow)


if __name__ == "__main__":
    unittest.main(verbosity=2)
