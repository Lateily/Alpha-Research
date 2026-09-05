#!/usr/bin/env python3
"""Offline behavioral tests for WO-D1 post-generation fact tracing."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "llm" / "fact_check.py"
SAMPLE_PATH = (
    ROOT
    / "docs"
    / "research"
    / "decision_sheets"
    / "cores"
    / "api_generated"
    / "688120_SH_20260611.json"
)
RESEARCH_API = ROOT / "api" / "research.js"
RESEARCH_MULTI_API = ROOT / "api" / "research-multi.js"
CORE_PATH = ROOT / "scripts" / "llm" / "fact_check_core.mjs"
CUTOFF = "2026-06-11T23:59:59Z"
SOURCE_DATE = "2026-06-10T00:00:00Z"

SPEC = importlib.util.spec_from_file_location("fact_check", MODULE_PATH)
assert SPEC and SPEC.loader
fact_check_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fact_check_module
SPEC.loader.exec_module(fact_check_module)


SDK_LOADER = r"""
const source = `
const thesis = { claim: 'FY2025 order book was RMB 8.3B.' };
export default class Anthropic {
  constructor() {
    this.messages = {
      create: async options => ({
        content: [{ text: options.max_tokens <= 900 ? '[]' : JSON.stringify(thesis) }],
        model: 'offline-stub',
        usage: { input_tokens: 0, output_tokens: 0 },
      }),
    };
  }
}`;

export async function resolve(specifier, context, nextResolve) {
  if (specifier === '@anthropic-ai/sdk') {
    return { url: `data:text/javascript,${encodeURIComponent(source)}`, shortCircuit: true };
  }
  return nextResolve(specifier, context);
}
"""

NODE_RUNNER = r"""
import { pathToFileURL } from 'node:url';

globalThis.fetch = () => { throw new Error('network is forbidden in fact-check tests'); };
const [researchPath] = process.argv.slice(2);
const { attachFactCheck } = await import(pathToFileURL(researchPath).href);
const source = { extras: { context_built_at: '2026-06-10T00:00:00Z', filing: 'FY2025 gross margin was 41.81%.' } };
const cutoff = '2026-06-11T23:59:59Z';
const traced = attachFactCheck({ claim: 'FY2025 gross margin was 41.81%.' }, source, '688120.SH', cutoff);
const mismatch = attachFactCheck({ claim: 'FY2025 gross margin was 44.5%.' }, source, '688120.SH', cutoff);
const blocked = attachFactCheck({ claim: 'FY2025 order book was RMB 8.3B.' }, source, '688120.SH', cutoff);
process.stdout.write(JSON.stringify({ traced, mismatch, blocked }));
"""

NODE_HANDLER_RUNNER = r"""
import { pathToFileURL } from 'node:url';

const [apiPath, mode] = process.argv.slice(2);
const thesis = { claim: 'FY2025 order book was RMB 8.3B.' };
globalThis.fetch = async url => {
  const target = String(url);
  if (target.includes('generativelanguage.googleapis.com')) {
    return {
      ok: true,
      status: 200,
      json: async () => ({ candidates: [{ content: { parts: [{ text: JSON.stringify(thesis) }] } }] }),
      text: async () => '',
    };
  }
  if (target.includes('api.openai.com')) {
    return {
      ok: true,
      status: 200,
      json: async () => ({ choices: [{ message: { content: JSON.stringify(thesis) } }] }),
      text: async () => '',
    };
  }
  return {
    ok: false,
    status: 503,
    json: async () => ({}),
    text: async () => 'offline source unavailable',
  };
};

const { default: handler } = await import(pathToFileURL(apiPath).href);
const response = {
  statusCode: 200,
  body: null,
  setHeader() {},
  status(code) { this.statusCode = code; return this; },
  json(payload) { this.body = payload; return this; },
  end() { return this; },
};
await handler({
  method: 'POST',
  body: {
    ticker: '688120.SH',
    company: 'offline fixture',
    direction: 'NEUTRAL',
    context: 'offline fact-check wiring probe',
    enrichment_context: { extras: { context_built_at: '2026-06-10T00:00:00Z', filing: 'FY2025 gross margin was 41.81%.' } },
  },
}, response);
process.stdout.write(JSON.stringify({ mode, statusCode: response.statusCode, body: response.body }));
"""


def _source_payload(text: str, *, source_date: str = SOURCE_DATE) -> list[tuple[object, str, str]]:
    return [({"source_date": source_date, "filing": text}, "fixture.json", "E1")]


class FactCheckTest(unittest.TestCase):
    def _run_node(self, runner_source: str, *arguments: Path | str) -> dict[str, object]:
        with tempfile.TemporaryDirectory(prefix="ar-fact-check-node-") as tmp:
            root = Path(tmp)
            loader = root / "anthropic-loader.mjs"
            runner = root / "runner.mjs"
            loader.write_text(SDK_LOADER, encoding="utf-8")
            runner.write_text(runner_source, encoding="utf-8")
            env = {
                key: value
                for key, value in os.environ.items()
                if not any(part in key.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
            }
            env.update(
                {
                    "ANTHROPIC_API_KEY": "offline-test",
                    "OPENAI_API_KEY": "offline-test",
                    "GOOGLE_AI_API_KEY": "offline-test",
                    "AR_OFFLINE": "1",
                }
            )
            completed = subprocess.run(
                [
                    "node",
                    "--no-warnings",
                    "--experimental-loader",
                    str(loader),
                    str(runner),
                    *(str(argument) for argument in arguments),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, "node runner produced no JSON receipt")
        return json.loads(lines[-1])

    def _run_core_request(
        self,
        request: dict[str, object],
        *,
        timezone: str | None = None,
    ) -> dict[str, object]:
        env = os.environ.copy()
        if timezone is not None:
            env["TZ"] = timezone
        completed = subprocess.run(
            ["node", str(CORE_PATH)],
            cwd=ROOT,
            env=env,
            input=json.dumps(request, ensure_ascii=False, sort_keys=True),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_fully_traceable_fixture_passes(self) -> None:
        receipt = fact_check_module.fact_check(
            {"claim": "FY2025 gross margin was 41.81%."},
            ticker="688120.SH",
            cutoff=CUTOFF,
            source_payloads=_source_payload("FY2025 gross margin was 41.81%."),
        )
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["summary"]["mismatches"], 0)
        self.assertEqual(receipt["summary"]["untraced"], 0)
        self.assertGreater(receipt["summary"]["traced"], 0)

    def test_blocking_class_mismatch_blocks_regardless_of_magnitude(self) -> None:
        """A wrong money/order/contract/capacity number is at least as serious as an
        unsourced one — and looks more credible, so it is the easier lie to ship.
        Before this gate, an order book inflated from 8.3B to 99.9B passed as a
        non-blocking MISMATCH because a same-identity number existed in evidence."""
        source = _source_payload("FY2025 order book was RMB 8.3B.")
        for claim, label in (("RMB 9.9B", "19% inflation"), ("RMB 99.9B", "12x inflation")):
            with self.subTest(label):
                receipt = fact_check_module.fact_check(
                    {"claim": f"FY2025 order book was {claim}."},
                    ticker="688120.SH", cutoff=CUTOFF, source_payloads=source,
                )
                self.assertEqual(receipt["status"], "BLOCKED_PENDING_HUMAN")
                self.assertGreaterEqual(receipt["summary"]["blocking_mismatches"], 1)
                self.assertTrue(any(claim in row["raw"] for row in receipt["fabrication_suspects"]))

    def test_truthful_blocking_class_claim_still_passes(self) -> None:
        """The dual failure of reflexive-PASS is reflexive-BLOCK: a number that agrees
        with its source must not be blocked."""
        receipt = fact_check_module.fact_check(
            {"claim": "FY2025 order book was RMB 8.3B."},
            ticker="688120.SH", cutoff=CUTOFF,
            source_payloads=_source_payload("FY2025 order book was RMB 8.3B."),
        )
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["summary"]["blocking_mismatches"], 0)
        self.assertEqual(receipt["summary"]["fabrication_suspects"], 0)

    def test_thousands_separator_is_not_a_mismatch(self) -> None:
        """Without this, the stricter blocking rule would fire on pure formatting."""
        receipt = fact_check_module.fact_check(
            {"claim": "FY2025 revenue was RMB 4.5B."},
            ticker="688120.SH", cutoff=CUTOFF,
            source_payloads=_source_payload("FY2025 revenue was RMB 4,500 million."),
        )
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["summary"]["blocking_mismatches"], 0)

    def test_multi_figure_sentence_is_not_reported_as_a_contradiction(self) -> None:
        """A filing sentence usually carries several figures. When the window cannot say
        which metric a number belongs to, the gate must not assert that the thesis
        contradicts its source — under the blocking-class rule that assertion would stop
        a truthful thesis. It may still be UNTRACED (unconfirmed is not the same as
        contradicted), but it must never be MISMATCH."""
        source = _source_payload(
            "FY2025 revenue was RMB 4.648B and net profit was RMB 1.084B.")
        receipt = fact_check_module.fact_check(
            {"claim": "FY2025 net profit was RMB 1.084B."},
            ticker="688120.SH", cutoff=CUTOFF, source_payloads=source,
        )
        self.assertEqual(receipt["summary"]["mismatches"], 0,
                         "a truthful figure must not be reported as contradicting its source")
        self.assertEqual(receipt["summary"]["blocking_mismatches"], 0)
        # The unambiguous figure in the same sentence still traces cleanly.
        clean = fact_check_module.fact_check(
            {"claim": "FY2025 revenue was RMB 4.648B."},
            ticker="688120.SH", cutoff=CUTOFF, source_payloads=source,
        )
        self.assertEqual(clean["status"], "PASS")
        self.assertGreater(clean["summary"]["traced"], 0)

    def test_ratio_mismatch_remains_visible_but_unblocking(self) -> None:
        receipt = fact_check_module.fact_check(
            {"claim": "FY2025 gross margin was 44.5%."},
            ticker="688120.SH", cutoff=CUTOFF,
            source_payloads=_source_payload("FY2025 gross margin was 41.81%."),
        )
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["summary"]["blocking_mismatches"], 0)
        self.assertGreaterEqual(receipt["summary"]["mismatches"], 1)

    def test_mismatch_is_visible_but_does_not_block(self) -> None:
        receipt = fact_check_module.fact_check(
            {"claim": "FY2025 gross margin was 44.5%."},
            ticker="688120.SH",
            cutoff=CUTOFF,
            source_payloads=_source_payload("FY2025 gross margin was 41.81%."),
        )
        self.assertEqual(receipt["status"], "PASS")
        mismatch = next(row for row in receipt["mismatches"] if row["metric"] == "gross_margin")
        self.assertEqual(mismatch["raw"], "44.5%")
        self.assertEqual(mismatch["source"]["raw"], "41.81%")

    def test_untraced_monetary_claim_blocks(self) -> None:
        receipt = fact_check_module.fact_check(
            {"claim": "FY2025 order book was RMB 8.3B."},
            ticker="688120.SH",
            cutoff=CUTOFF,
            source_payloads=_source_payload("FY2025 gross margin was 41.81%."),
        )
        suspect = next(row for row in receipt["fabrication_suspects"] if "8.3B" in row["raw"])
        self.assertEqual(suspect["state"], "UNTRACED")
        self.assertEqual(suspect["entity_class"], "ORDER")
        self.assertEqual(receipt["status"], "BLOCKED_PENDING_HUMAN")

    def test_model_output_cannot_serve_as_its_own_source(self) -> None:
        receipt = fact_check_module.fact_check(
            {
                "claim": "The contract amount was RMB 2.4B.",
                "claimed_source": "The contract amount was RMB 2.4B.",
            },
            ticker="688120.SH",
            cutoff=CUTOFF,
        )
        self.assertEqual(receipt["status"], "BLOCKED_PENDING_HUMAN")
        self.assertGreaterEqual(receipt["summary"]["fabrication_suspects"], 1)

    def test_high_risk_identity_includes_sign_currency_comparator_and_period(self) -> None:
        evidence = _source_payload("FY2025 order book was above RMB 8.3B.")
        baseline = fact_check_module.fact_check(
            {"claim": "FY2025 order book was above RMB 8.3B."},
            ticker="688120.SH",
            cutoff=CUTOFF,
            source_payloads=evidence,
        )
        self.assertEqual(baseline["status"], "PASS")
        attacks = (
            "FY2025 order book was above RMB -8.3B.",
            "FY2025 order book was above USD 8.3B.",
            "FY2025 order book was below RMB 8.3B.",
            "FY2026 order book was above RMB 8.3B.",
        )
        for claim in attacks:
            with self.subTest(claim=claim):
                receipt = fact_check_module.fact_check(
                    {"claim": claim}, ticker="688120.SH", cutoff=CUTOFF,
                    source_payloads=evidence,
                )
                orders = [row for row in receipt["untraced"] if row["metric"] == "order_book"]
                self.assertEqual(len(orders), 1)
                self.assertEqual(orders[0]["state"], "UNTRACED")
                self.assertEqual(receipt["status"], "BLOCKED_PENDING_HUMAN")
        wrong_entity = fact_check_module.fact_check(
            {"claim": "FY2025 order book was above RMB 8.3B."},
            ticker="688120.SH",
            cutoff=CUTOFF,
            source_payloads=[(
                {
                    "source_date": SOURCE_DATE,
                    "ticker": "000001.SZ",
                    "filing": "FY2025 order book was above RMB 8.3B.",
                },
                "fixture.json",
                "E1",
            )],
        )
        self.assertEqual(wrong_entity["status"], "BLOCKED_PENDING_HUMAN")

    def test_future_or_undated_source_cannot_cross_the_pit_cutoff(self) -> None:
        claim = {"claim": "FY2025 order book was RMB 8.3B."}
        future = fact_check_module.fact_check(
            claim,
            ticker="688120.SH",
            cutoff=CUTOFF,
            source_payloads=_source_payload(
                "FY2025 order book was RMB 8.3B.",
                source_date="2027-01-01T00:00:00Z",
            ),
        )
        undated = fact_check_module.fact_check(
            claim,
            ticker="688120.SH",
            cutoff=CUTOFF,
            source_payloads=_source_payload("FY2025 order book was RMB 8.3B.", source_date=""),
        )
        self.assertEqual(future["status"], "BLOCKED_PENDING_HUMAN")
        self.assertGreater(future["summary"]["future_source_facts"], 0)
        self.assertEqual(undated["status"], "BLOCKED_PENDING_HUMAN")
        self.assertGreater(undated["summary"]["undated_source_facts"], 0)

    def test_latest_of_all_source_dates_controls_pit_admissibility(self) -> None:
        receipt = fact_check_module.fact_check(
            {"claim": "FY2025 order book was RMB 8.3B."},
            ticker="688120.SH",
            cutoff=CUTOFF,
            source_payloads=[(
                {
                    "source_date": "2026-06-10T00:00:00Z",
                    "published_at": "2027-01-01T00:00:00Z",
                    "filing": "FY2025 order book was RMB 8.3B.",
                },
                "conflicting-dates.json",
                "E1",
            )],
        )
        self.assertEqual(receipt["status"], "BLOCKED_PENDING_HUMAN")
        self.assertGreater(receipt["summary"]["future_source_facts"], 0)
        self.assertFalse(any(
            row["state"] == "TRACED" and row["metric"] == "order_book"
            for row in receipt["claims"][0]["observations"]
        ))

    def test_timezone_naive_source_timestamp_is_host_independent_and_blocked(self) -> None:
        request = {
            "thesis": {"claim": "FY2025 order book was RMB 8.3B."},
            "ticker": "688120.SH",
            "cutoff": CUTOFF,
            "source_documents": [{
                "payload": {
                    "published_at": "2026-06-10T12:00:00",
                    "filing": "FY2025 order book was RMB 8.3B.",
                },
                "label": "naive-time.json",
                "tier": "E1",
                "entity": "688120.SH",
                "source_date": SOURCE_DATE,
            }],
        }
        utc = self._run_core_request(request, timezone="UTC")
        los_angeles = self._run_core_request(request, timezone="America/Los_Angeles")
        self.assertEqual(utc, los_angeles)
        self.assertEqual(utc["status"], "BLOCKED_PENDING_HUMAN")
        self.assertGreater(utc["summary"]["undated_source_facts"], 0)

    def test_each_numeric_observation_binds_only_its_local_period(self) -> None:
        receipt = fact_check_module.fact_check(
            {"claim": "FY2024 order book was RMB 8.3B."},
            ticker="688120.SH",
            cutoff=CUTOFF,
            source_payloads=_source_payload(
                "FY2024 order book was RMB 7.0B, while FY2025 order book was RMB 8.3B."
            ),
        )
        order_rows = [
            observation
            for claim in receipt["claims"]
            for observation in claim["observations"]
            if observation["metric"] == "order_book"
        ]
        self.assertEqual(len(order_rows), 1)
        self.assertEqual(order_rows[0]["state"], "MISMATCH")
        self.assertEqual(order_rows[0]["periods"], ["FY2024"])
        self.assertEqual(order_rows[0]["source"]["raw"], "RMB 7.0B")
        self.assertEqual(order_rows[0]["source"]["identity"]["periods"], ["FY2024"])

    def test_inline_ticker_cannot_be_relabelled_by_document_entity(self) -> None:
        receipt = fact_check_module.fact_check(
            {"claim": "688120.SH FY2025 order book was RMB 8.3B."},
            ticker="688120.SH",
            cutoff=CUTOFF,
            source_payloads=_source_payload(
                "000001.SZ FY2025 order book was RMB 8.3B."
            ),
        )
        orders = [row for row in receipt["untraced"] if row["metric"] == "order_book"]
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["entity"], "688120.SH")
        self.assertEqual(receipt["status"], "BLOCKED_PENDING_HUMAN")

    def test_numeric_thesis_leaf_is_checked_instead_of_skipped(self) -> None:
        receipt = fact_check_module.fact_check(
            {"order_book": 8_300_000_000, "currency": "CNY", "period": "FY2025"},
            ticker="688120.SH",
            cutoff=CUTOFF,
        )
        orders = [row for row in receipt["fabrication_suspects"] if row["path"] == "order_book"]
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["normalized"], 8_300_000_000)
        self.assertEqual(receipt["status"], "BLOCKED_PENDING_HUMAN")

    def test_receipt_input_hash_binds_the_evidence_set(self) -> None:
        thesis = {"claim": "FY2025 gross margin was 41.81%."}
        first = fact_check_module.fact_check(
            thesis, ticker="688120.SH", cutoff=CUTOFF,
            source_payloads=_source_payload("FY2025 gross margin was 41.81%."),
        )
        second = fact_check_module.fact_check(
            thesis, ticker="688120.SH", cutoff=CUTOFF,
            source_payloads=_source_payload("FY2025 gross margin was 41.82%."),
        )
        self.assertEqual(first["thesis_hash"], second["thesis_hash"])
        self.assertNotEqual(first["source_set_hash"], second["source_set_hash"])
        self.assertNotEqual(first["input_hash"], second["input_hash"])
        self.assertNotEqual(first["receipt_hash"], second["receipt_hash"])

    def test_source_payload_hash_is_recomputed_not_caller_supplied(self) -> None:
        def request(value: str) -> dict[str, object]:
            return {
                "thesis": {"claim": "FY2025 order book was RMB 8.3B."},
                "ticker": "688120.SH",
                "cutoff": CUTOFF,
                "source_documents": [{
                    "payload": {
                        "source_date": SOURCE_DATE,
                        "filing": f"FY2025 order book was RMB {value}B.",
                    },
                    "label": "declared-hash.json",
                    "tier": "E1",
                    "entity": "688120.SH",
                    "content_hash": "sha256:" + ("0" * 64),
                }],
            }

        first = self._run_core_request(request("8.3"))
        second = self._run_core_request(request("8.4"))
        self.assertNotEqual(first["source_set_hash"], second["source_set_hash"])
        self.assertNotEqual(first["receipt_hash"], second["receipt_hash"])
        traced = next(
            observation
            for claim in first["claims"]
            for observation in claim["observations"]
            if observation["metric"] == "order_book"
        )
        self.assertNotEqual(traced["source"]["content_hash"], "sha256:" + ("0" * 64))

    def test_event_subject_identity_is_not_keyword_only(self) -> None:
        evidence = _source_payload("FDA approval was granted.")
        traced = fact_check_module.fact_check(
            {"claim": "FDA approval was granted."}, ticker="688120.SH",
            cutoff=CUTOFF, source_payloads=evidence,
        )
        wrong_subject = fact_check_module.fact_check(
            {"claim": "Board approval was granted."}, ticker="688120.SH",
            cutoff=CUTOFF, source_payloads=evidence,
        )
        self.assertTrue(any(row["metric"] == "event" and row["state"] == "TRACED" for row in traced["claims"][0]["observations"]))
        self.assertTrue(any(row["metric"] == "event" and row["state"] == "UNTRACED" for row in wrong_subject["untraced"]))
        generic_subject = fact_check_module.fact_check(
            {"claim": "Merger approval was granted."}, ticker="688120.SH",
            cutoff=CUTOFF, source_payloads=_source_payload("Drug approval was granted."),
        )
        self.assertTrue(any(
            row["metric"] == "event" and row["state"] == "UNTRACED"
            for row in generic_subject["untraced"]
        ))

    def test_python_adapter_returns_the_canonical_core_receipt(self) -> None:
        payload = {"source_date": SOURCE_DATE, "filing": "FY2025 gross margin was 41.81%."}
        document = fact_check_module._source_document(
            payload, label="fixture.json", tier="E1", entity="688120.SH"
        )
        request = {
            "thesis": {"claim": "FY2025 gross margin was 41.81%."},
            "ticker": "688120.SH",
            "cutoff": CUTOFF,
            "source_documents": [document],
        }
        python_receipt = fact_check_module.fact_check(
            request["thesis"], ticker="688120.SH", cutoff=CUTOFF,
            source_facts=[document],
        )
        self.assertEqual(python_receipt, self._run_core_request(request))

    def test_historical_688120_acceptance_sample(self) -> None:
        payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        sources = fact_check_module.load_repo_sources(ROOT, "688120.SH")
        receipt = fact_check_module.fact_check(
            payload["data"], ticker="688120.SH", cutoff=CUTOFF, source_facts=sources
        )
        self.assertEqual(receipt["status"], "BLOCKED_PENDING_HUMAN")
        self.assertTrue(
            any("8.3B" in row["raw"] and row["metric"] == "order_book" for row in receipt["fabrication_suspects"])
        )
        self.assertTrue(
            any(
                "44.5" in row["raw"]
                and row["metric"] == "gross_margin"
                and row["source"]["raw"] == "41.81%"
                for row in receipt["mismatches"]
            )
        )

    def test_cli_writes_deterministic_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ar-fact-check-") as tmp:
            root = Path(tmp)
            thesis_path = root / "thesis.json"
            source_path = root / "source.json"
            output_a = root / "a.json"
            output_b = root / "b.json"
            thesis_path.write_text(
                json.dumps({"ticker": "688120.SH", "data": {"claim": "FY2025 gross margin was 41.81%."}}),
                encoding="utf-8",
            )
            source_path.write_text(
                json.dumps({"source_date": SOURCE_DATE, "filing": "FY2025 gross margin was 41.81%."}),
                encoding="utf-8",
            )
            command = [
                "python3", str(MODULE_PATH), "--input", str(thesis_path),
                "--source", str(source_path), "--no-repo-sources", "--cutoff", CUTOFF,
            ]
            first = subprocess.run(
                [*command, "--output", str(output_a)], cwd=ROOT, capture_output=True,
                text=True, timeout=30, check=False,
            )
            second = subprocess.run(
                [*command, "--output", str(output_b)], cwd=ROOT, capture_output=True,
                text=True, timeout=30, check=False,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(output_a.read_bytes(), output_b.read_bytes())

    def test_api_postprocessor_uses_the_same_three_states(self) -> None:
        output = self._run_node(NODE_RUNNER, RESEARCH_API)
        self.assertEqual(output["traced"]["status"], "PASS")
        self.assertEqual(output["traced"]["data"]["_fact_check"]["summary"]["untraced"], 0)
        self.assertEqual(output["mismatch"]["status"], "PASS")
        self.assertEqual(output["mismatch"]["data"]["_fact_check"]["mismatches"][0]["source"]["raw"], "41.81%")
        self.assertEqual(output["blocked"]["status"], "BLOCKED_PENDING_HUMAN")
        self.assertTrue(any("8.3B" in row["raw"] for row in output["blocked"]["data"]["_fact_check"]["fabrication_suspects"]))

    def test_single_api_calls_fact_checker_before_returning_generated_thesis(self) -> None:
        output = self._run_node(NODE_HANDLER_RUNNER, RESEARCH_API, "single")
        self.assertEqual(200, output["statusCode"])
        self.assertEqual("BLOCKED_PENDING_HUMAN", output["body"]["_status"])
        self.assertEqual(
            "BLOCKED_PENDING_HUMAN",
            output["body"]["data"]["_fact_check"]["status"],
        )

    def test_fabrication_caps_the_structural_quality_score(self) -> None:
        """F-029: a thesis can be perfectly well-FORMED and still invent its numbers.
        When the gate holds fabrication suspects, the headline score must not read PASS."""
        runner = """
import { pathToFileURL } from 'node:url';
const [apiPath] = process.argv.slice(2);
const api = await import(pathToFileURL(apiPath).href);
const quality = { score: 90, severity: 'PASS', missingFields: [], qcChecklistResults: {} };
process.stdout.write(JSON.stringify({
  clean: api.applyFabricationCap(quality, { summary: { fabrication_suspects: 0 } }),
  fabricated: api.applyFabricationCap(quality, { summary: { fabrication_suspects: 106 } }),
  alreadyLow: api.applyFabricationCap({ score: 12, severity: 'FAIL' }, { summary: { fabrication_suspects: 3 } }),
  noReceipt: api.applyFabricationCap(quality, undefined),
}));
"""
        output = self._run_node(runner, RESEARCH_API)
        self.assertEqual(output["clean"]["score"], 90)
        self.assertEqual(output["clean"]["severity"], "PASS")
        self.assertEqual(output["fabricated"]["score"], 40)
        self.assertNotEqual(output["fabricated"]["severity"], "PASS")
        self.assertTrue(output["fabricated"]["fabrication_capped"])
        self.assertEqual(output["fabricated"]["fabrication_suspects"], 106)
        self.assertEqual(output["alreadyLow"]["score"], 12, "the cap must never raise a score")
        self.assertEqual(output["noReceipt"]["score"], 90)

    def test_multi_api_calls_fact_checker_before_returning_generated_thesis(self) -> None:
        output = self._run_node(NODE_HANDLER_RUNNER, RESEARCH_MULTI_API, "multi")
        self.assertEqual(200, output["statusCode"])
        self.assertEqual("BLOCKED_PENDING_HUMAN", output["body"]["_status"])
        # Read defensively: if the synthesis receipt is missing entirely, that is a
        # failed assertion about the gate, not a KeyError about the test.
        synth_receipt = output["body"]["data"].get("_fact_check") or {}
        self.assertEqual("BLOCKED_PENDING_HUMAN", synth_receipt.get("status"))

    def test_multi_api_gates_every_returned_sub_thesis(self) -> None:
        """Gating only the synthesis leaves six other thesis blocks returned and
        quotable; a fabricated number would just move one key to the left."""
        output = self._run_node(NODE_HANDLER_RUNNER, RESEARCH_MULTI_API, "multi")
        data = output["body"]["data"]
        summary = data.get("_fact_check_sub_theses") or {}
        self.assertGreaterEqual(summary.get("checked_blocks", 0), 1)
        for name in ("_bull_thesis", "_bear_thesis", "_technical", "_forensic"):
            block = data.get(name)
            if isinstance(block, dict):
                self.assertIn("_fact_check", block, f"{name} left the API unchecked")


if __name__ == "__main__":
    unittest.main(verbosity=2)
