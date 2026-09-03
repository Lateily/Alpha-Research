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
const source = { extras: { filing: 'FY2025 gross margin was 41.81%.' } };
const traced = attachFactCheck({ claim: 'FY2025 gross margin was 41.81%.' }, source, '688120.SH');
const mismatch = attachFactCheck({ claim: 'FY2025 gross margin was 44.5%.' }, source, '688120.SH');
const blocked = attachFactCheck({ claim: 'FY2025 order book was RMB 8.3B.' }, source, '688120.SH');
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
    enrichment_context: { extras: { filing: 'FY2025 gross margin was 41.81%.' } },
  },
}, response);
process.stdout.write(JSON.stringify({ mode, statusCode: response.statusCode, body: response.body }));
"""


def _source_payload(text: str) -> list[tuple[object, str, str]]:
    return [({"filing": text}, "fixture.json", "E1")]


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

    def test_fully_traceable_fixture_passes(self) -> None:
        receipt = fact_check_module.fact_check(
            {"claim": "FY2025 gross margin was 41.81%."},
            ticker="688120.SH",
            source_payloads=_source_payload("FY2025 gross margin was 41.81%."),
        )
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["summary"]["mismatches"], 0)
        self.assertEqual(receipt["summary"]["untraced"], 0)
        self.assertGreater(receipt["summary"]["traced"], 0)

    def test_mismatch_is_visible_but_does_not_block(self) -> None:
        receipt = fact_check_module.fact_check(
            {"claim": "FY2025 gross margin was 44.5%."},
            ticker="688120.SH",
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
        )
        self.assertEqual(receipt["status"], "BLOCKED_PENDING_HUMAN")
        self.assertGreaterEqual(receipt["summary"]["fabrication_suspects"], 1)

    def test_historical_688120_acceptance_sample(self) -> None:
        payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        sources = fact_check_module.load_repo_sources(ROOT, "688120.SH")
        receipt = fact_check_module.fact_check(
            payload["data"], ticker="688120.SH", source_facts=sources
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
                json.dumps({"filing": "FY2025 gross margin was 41.81%."}),
                encoding="utf-8",
            )
            command = [
                "python3", str(MODULE_PATH), "--input", str(thesis_path),
                "--source", str(source_path), "--no-repo-sources",
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

    def test_multi_api_calls_fact_checker_before_returning_generated_thesis(self) -> None:
        output = self._run_node(NODE_HANDLER_RUNNER, RESEARCH_MULTI_API, "multi")
        self.assertEqual(200, output["statusCode"])
        self.assertEqual("BLOCKED_PENDING_HUMAN", output["body"]["_status"])
        self.assertEqual(
            "BLOCKED_PENDING_HUMAN",
            output["body"]["data"]["_fact_check"]["status"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
