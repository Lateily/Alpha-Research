"""Deferred offline behavior cases. NOT_RUN; no runtime acceptance claimed."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.llm.foundation_sources import build_source_coverage, load_source_inventory


class FoundationSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.inventory = json.loads((ROOT / "config/data-source-inventory.v1.json").read_text())

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def coverage(self, inventory=None):
        path = self.root / "inventory.json"
        path.write_text(json.dumps(self.inventory if inventory is None else inventory))
        return build_source_coverage(self.root, inventory_path=path)

    def test_closed_read_only_api_and_family_catalog(self):
        inventory = load_source_inventory()
        ids = {row["source_id"] for row in inventory["sources"]}
        self.assertTrue({"tushare.http", "tushare.sdk", "akshare.sdk", "yahoo.yfinance",
                         "moonshot.models", "deepseek.models", "news.rss", "bls.macro",
                         "fred.macro", "sec.edgar", "cninfo.filings", "telegram.notifications"} <= ids)
        self.assertGreater(len(ids), 5)
        for row in inventory["sources"]:
            self.assertEqual(row["rights_status"], "UNVERIFIED")
            self.assertEqual(row["endpoint_contract"], "NOT_DECLARED")
        result = self.coverage()
        self.assertEqual(result["testing_status"], "NOT_RUN")
        self.assertEqual(result["human_review"], "PENDING")
        self.assertEqual(result["sample_purpose"], "WORKFLOW_DEBUG")
        self.assertEqual(result["implementation_status"], "IMPLEMENTED_UNTESTED")
        for key in ("production_authority", "trading_authority", "deployment_authority",
                    "network_performed", "source_execution_performed",
                    "complete_source_registration", "endpoint_instrumentation_proven"):
            self.assertIs(result[key], False)

    def test_known_literal_alias_has_independent_file_provenance(self):
        raw = 'import requests as net\nnet.get("https://api.tushare.pro/safe")\n'
        self.write("scripts/market.py", raw)
        result = self.coverage()
        row = next(r for r in result["findings"] if r["kind"] == "NETWORK_OR_PROVIDER_CALL")
        self.assertEqual(row["file"], "scripts/market.py")
        self.assertEqual(row["line"], 2)
        self.assertEqual(row["file_sha256"], hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(row["source_id"], "tushare.http")
        self.assertEqual(row["inventory_status"], "REGISTERED_STATIC")
        self.assertEqual(row["instrumentation"], "NOT_ASSESSED")
        self.assertEqual(row["runtime_evidence"], "NOT_OBSERVED")
        self.assertEqual(row["rights_status"], "UNVERIFIED")
        # The literal reference remains a reference, not a second proven call.
        self.assertTrue(any(r["reason"] == "REFERENCE_NOT_CALL" for r in result["findings"]))

    def test_url_userinfo_query_path_fragment_are_never_returned(self):
        self.write("api/client.py", 'from urllib.request import urlopen as go\n'
                   'go("https://FAKE_USER:FAKE_PASSWORD@api.tushare.pro/FAKE_PATH?key=FAKE_QUERY#FAKE_FRAGMENT")\n')
        result = self.coverage()
        serialized = json.dumps(result)
        for marker in ("FAKE_USER", "FAKE_PASSWORD", "FAKE_PATH", "FAKE_QUERY", "FAKE_FRAGMENT"):
            self.assertNotIn(marker, serialized)
        row = next(r for r in result["findings"] if r["kind"] == "NETWORK_OR_PROVIDER_CALL")
        self.assertEqual(row["host"], "api.tushare.pro")
        self.assertEqual(row["interface_id"], "urllib.request.urlopen")

    def test_unknown_hosts_dynamic_calls_and_alias_shadowing_stay_unresolved(self):
        self.write("scripts/dynamic.py", 'import requests as r\n'
                   'r.get("https://unknown.invalid/x")\n'
                   'r.get(f"https://api.tushare.pro/{endpoint}?key={secret}")\n'
                   'def injected(r):\n    r.get("https://api.tushare.pro")\n'
                   'getattr(pro, endpoint)()\nclient.query(endpoint)\n')
        result = self.coverage()
        self.assertTrue(all(row["inventory_status"] == "UNRESOLVED" for row in result["findings"]))
        self.assertIn("ALIAS_OR_BINDING_AMBIGUOUS", {r["reason"] for r in result["findings"]})
        self.assertIn("DYNAMIC_OR_INDIRECT_METHOD", {r["reason"] for r in result["findings"]})
        self.assertNotIn("secret", json.dumps(result))

    def test_dynamic_known_host_and_unknown_static_host_separate(self):
        self.write("dynamic.py", 'import requests\n'
                   'requests.get(f"https://api.tushare.pro/{name}")\n'
                   'requests.get("https://api.tushare.pro.unknown.invalid/")\n')
        calls = [r for r in self.coverage()["findings"] if r["kind"] == "NETWORK_OR_PROVIDER_CALL"]
        self.assertEqual(calls[0]["reason"], "DYNAMIC_URL_OR_REQUEST_OBJECT")
        self.assertEqual(calls[0]["candidate_source_ids"], ["tushare.http"])
        self.assertEqual(calls[1]["reason"], "UNREGISTERED_SOURCE")

    def test_provider_sdks_wrappers_and_chains_do_not_claim_endpoint_registration(self):
        self.write("sources.py", 'import akshare as ak\nimport yfinance as yf\n'
                   'import tushare as ts\nimport fund_source as fs\n'
                   'ak.stock_zh_a_spot_em()\nyf.Ticker("x").history()\n'
                   'pro = ts.pro_api(token)\npro.daily()\nfs._tushare_call(name, token, {}, "")\n')
        rows = self.coverage()["findings"]
        self.assertTrue(rows)
        self.assertTrue(all(row["inventory_status"] == "UNRESOLVED" for row in rows))
        self.assertTrue(any("akshare.sdk" in row["candidate_source_ids"] for row in rows))
        self.assertTrue(any("tushare.repository-adapters" in row["candidate_source_ids"] for row in rows))
        self.assertTrue(any(row["reason"] == "CHAINED_RECEIVER_NOT_RESOLVED" for row in rows))

    def test_parse_errors_are_counted_without_source_or_error_text(self):
        self.write("bad.py", 'FAKE_SECRET_SYNTAX = (\n')
        result = self.coverage()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["files"][0]["status"], "UNRESOLVED")
        self.assertTrue(any(r["reason"] == "PYTHON_PARSE_ERROR" for r in result["findings"]))
        self.assertGreater(result["summary"]["unresolved_total"], 0)
        self.assertNotIn("FAKE_SECRET_SYNTAX", json.dumps(result))

    def test_bounded_text_inventory_does_not_claim_semantic_calls(self):
        for name, text in {
            "api/news.js": 'fetch(`https://feeds.reuters.com/${path}?key=FAKE_KEY`);',
            "web/model.ts": 'new Anthropic({apiKey: key});',
            "bin/get.sh": 'curl "$PROVIDER_URL"',
            ".github/workflows/data.yml": 'run: wget https://api.bls.gov/private?key=FAKE_KEY',
        }.items():
            self.write(name, text)
        result = self.coverage()
        self.assertEqual(len(result["files"]), 4)
        self.assertTrue(all(r["inventory_status"] == "UNRESOLVED" for r in result["findings"]))
        self.assertTrue(all(r["inspection"] == "BOUNDED_TEXT_ONLY" for r in result["files"]))
        self.assertNotIn("FAKE_KEY", json.dumps(result))

    def test_ambiguous_host_registry_match_stays_unresolved(self):
        row = copy.deepcopy(self.inventory["sources"][0])
        row["source_id"] = "conflicting.provider"
        self.inventory["sources"].append(row)
        self.write("call.py", 'import requests\nrequests.get("https://api.tushare.pro")\n')
        calls = [r for r in self.coverage()["findings"] if r["kind"] == "NETWORK_OR_PROVIDER_CALL"]
        self.assertEqual(calls[0]["reason"], "AMBIGUOUS_REGISTRY_MATCH")
        self.assertIsNone(calls[0]["source_id"])

    def test_missing_roots_and_source_drift_are_visible(self):
        self.inventory["scan"]["roots"] = ["scripts", "missing"]
        path = self.write("scripts/call.py", 'import requests\nrequests.get(url)\n')
        first = self.coverage()
        self.assertTrue(any(r["reason"] == "ROOT_OR_PATH_UNREADABLE" for r in first["scan_issues"]))
        before = first["files"][0]["sha256"]
        path.write_text('import requests\nrequests.post(url)\n')
        second = self.coverage()
        self.assertNotEqual(before, second["files"][0]["sha256"])
        self.assertEqual(second["files"][0]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_file_finding_byte_depth_and_entry_limits_report_partial(self):
        for limit, value in (("max_files", 1), ("max_findings", 1), ("max_file_bytes", 1),
                             ("max_total_bytes", 1), ("max_depth", 1), ("max_entries", 1),
                             ("max_ast_nodes", 1)):
            with self.subTest(limit=limit):
                inventory = copy.deepcopy(self.inventory)
                inventory["scan"][limit] = value
                self.write("scripts/nested/a.py", 'import requests\nrequests.get(url)\n')
                self.write("scripts/nested/b.py", 'import requests\nrequests.get(url)\n')
                result = self.coverage(inventory)
                self.assertGreater(result["summary"]["unresolved_total"], 0)
                self.assertEqual(result["status"], "PARTIAL")
                self.assertLessEqual(len(result["findings"]), inventory["scan"]["max_findings"])
                self.assertLessEqual(result["summary"]["bytes_read"], inventory["scan"]["max_total_bytes"])

    def test_symlinks_and_nonregular_files_not_followed(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside).resolve() / "not_read.py"
            target.write_text('raise RuntimeError("FAKE_OUTSIDE_SECRET")\n')
            (self.root / "link.py").symlink_to(target)
            (self.root / "linked_dir").symlink_to(target.parent, target_is_directory=True)
            result = self.coverage()
            self.assertEqual(result["summary"]["files_read"], 0)
            self.assertEqual(result["summary"]["skipped_or_limited_by_reason"]["SYMLINK_SKIPPED"], 2)
            self.assertNotIn("FAKE_OUTSIDE_SECRET", json.dumps(result))

    def test_no_source_execution_or_writes(self):
        self.write("evil.py", 'from pathlib import Path\nPath("SIDE_EFFECT").write_text("no")\n'
                   'raise RuntimeError("must not import")\n')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        path = self.write("registry.json", json.dumps(self.inventory))
        before[path.relative_to(self.root)] = path.read_bytes()
        build_source_coverage(self.root, inventory_path=path)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_invalid_registry_cannot_expand_rights_authority_or_roots(self):
        mutations = (
            lambda value: value.update(production_authority=True),
            lambda value: value["sources"][0].update(rights_status="TEAM_DISPLAY_ALLOWED"),
            lambda value: value["sources"][0].update(hosts=["user:password@host.invalid?key=secret"]),
            lambda value: value["sources"][0].update(endpoint_contract={"invented": "field"}),
            lambda value: value["scan"].update(roots=["../outside"]),
            lambda value: value["scan"].update(max_files=10001),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                inventory = copy.deepcopy(self.inventory)
                mutate(inventory)
                path = self.write("bad-inventory.json", json.dumps(inventory))
                with self.assertRaises(ValueError):
                    load_source_inventory(path)
        for raw in ('{"schema":"x","schema":"y"}', '{"schema":NaN}'):
            path = self.write("bad-inventory.json", raw)
            with self.assertRaises(ValueError):
                load_source_inventory(path)

    def test_closed_five_catalog_not_changed_or_promoted(self):
        path = ROOT / "config/data-source-catalog.v1.json"
        before = path.read_bytes()
        result = self.coverage()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(result["compatibility_catalog"]["scope"], "CLOSED_FIVE_UNCHANGED_NOT_REVALIDATED")
        self.assertEqual(result["compatibility_catalog"]["receipt_coverage"], "NOT_MEASURED")
        self.assertEqual(len(result["compatibility_catalog"]["source_ids"]), 5)


if __name__ == "__main__":
    unittest.main()
