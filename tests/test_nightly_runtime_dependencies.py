#!/usr/bin/env python3
"""Offline integration regressions for staged imports and nightly HTTPS readers."""
import contextlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ET = ROOT / "experiments/execution_tracker"
RF = ROOT / "experiments/research_funnel"
sys.path[:0] = [str(ET), str(RF)]
import nightly_publish
import fund_source
import full_battery
import red_flag_gate
import overnight_anchor
import funnel_dag


class RuntimeDependenciesTest(unittest.TestCase):
    def layout(self, root):
        repo = root / "repo"
        for rel in ("execution_tracker", "research_funnel", "macro_os"):
            shutil.copytree(ROOT / "experiments" / rel, repo / "experiments" / rel,
                            ignore=shutil.ignore_patterns("__pycache__", "runs", "*.pyc"))
        (repo / "scripts").mkdir()
        for name in ("decision_sheet.py", "universe_data_health.py"):
            shutil.copy2(ROOT / "scripts" / name, repo / "scripts" / name)
        (repo / "scripts/private.env").write_text("must-not-copy")
        return repo

    def stage(self, repo, root):
        return nightly_publish.prepare_stage(str(repo / "experiments/execution_tracker"),
                                             str(repo), str(root / "run"))

    def test_real_staged_paper_preflight_imports_without_source_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.layout(root)
            stage = self.stage(repo, root)
            moved = root / "source-hidden"
            repo.rename(moved)
            code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                    "from experiments.research_funnel import paper_registration_bridge; "
                    "print('STAGED_IMPORT_OK')")
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code, stage["repo"]],
                                    cwd=stage["repo"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("STAGED_IMPORT_OK", result.stdout)
            self.assertEqual(sorted(p.name for p in (Path(stage["repo"]) / "scripts").iterdir()),
                             ["decision_sheet.py", "universe_data_health.py"])

    def test_missing_staged_dependency_refuses_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.layout(root)
            (repo / "scripts/universe_data_health.py").unlink()
            with self.assertRaisesRegex(RuntimeError, "staging dependency missing"):
                self.stage(repo, root)

    def test_linked_staged_dependency_refuses_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.layout(root)
            dep = repo / "scripts/decision_sheet.py"
            dep.unlink()
            dep.symlink_to(ROOT / "scripts/decision_sheet.py")
            with self.assertRaisesRegex(RuntimeError, "staging dependency.*symlink"):
                self.stage(repo, root)

    def client_module(self):
        self.assertIsNotNone(importlib.util.find_spec("tushare_https"),
                             "nightly HTTPS adapter is not implemented")
        return importlib.import_module("tushare_https")

    def test_https_reader_preserves_request_and_provider_rows(self):
        client = self.client_module().TushareHTTPS("fixture-token")
        seen = []
        def transport(**kwargs):
            seen.append(kwargs)
            return {"code": 0, "data": {"fields": ["trade_date", "close"],
                                        "items": [["20260907", 2.5], ["20260904", None]]}}
        with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                mock.patch.object(fund_source, "_http_json", side_effect=transport):
            frame = client.daily(ts_code="TEST.SZ", end_date="20260907", fields="trade_date,close")
        self.assertEqual(frame.trade_date.tolist(), ["20260907", "20260904"])
        self.assertTrue(frame.close.isna().iloc[1])
        self.assertEqual(seen[0]["url"], "https://api.tushare.pro")
        body = json.loads(seen[0]["data"])
        self.assertEqual(body, {"api_name": "daily", "token": "fixture-token",
                               "params": {"ts_code": "TEST.SZ", "end_date": "20260907"},
                               "fields": "trade_date,close"})
        self.assertEqual(seen[0]["attempts"], 3)

    def test_offline_reader_never_reaches_transport(self):
        client = self.client_module().TushareHTTPS("fixture-token")
        with mock.patch.dict(os.environ, {"AR_OFFLINE": "1"}), \
                mock.patch.object(fund_source, "_tushare_call", return_value={"fields": [], "items": []}) as call:
            with self.assertRaisesRegex(RuntimeError, "OFFLINE"):
                client.daily(ts_code="TEST.SZ")
            call.assert_not_called()

    def test_endpoint_drift_refuses_before_credentials_are_sent(self):
        client = self.client_module().TushareHTTPS("fixture-token")
        with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                mock.patch.object(fund_source, "TUSHARE_URL", "http://api.waditu.com/dataapi"), \
                mock.patch.object(fund_source, "_tushare_call", return_value={"fields": [], "items": []}) as call:
            with self.assertRaisesRegex(RuntimeError, "HTTPS_ENDPOINT"):
                client.daily(ts_code="TEST.SZ")
            call.assert_not_called()

    def test_unknown_api_is_not_dispatched(self):
        client = self.client_module().TushareHTTPS("fixture-token")
        with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                mock.patch.object(fund_source, "_tushare_call", return_value={"fields": [], "items": []}) as call:
            with self.assertRaises((ValueError, AttributeError)):
                client.unknown_api()
            call.assert_not_called()

    def test_malformed_provider_rows_are_not_silently_padded(self):
        client = self.client_module().TushareHTTPS("fixture-token")
        with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                mock.patch.object(fund_source, "_tushare_call", return_value={
                    "fields": ["trade_date", "close"], "items": [["20260907"]]}):
            with self.assertRaisesRegex(ValueError, "ROW_SHAPE"):
                client.daily()

    def test_duplicate_provider_columns_refuse(self):
        client = self.client_module().TushareHTTPS("fixture-token")
        with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                mock.patch.object(fund_source, "_tushare_call", return_value={
                    "fields": ["close", "close"], "items": [[1, 2]]}):
            with self.assertRaisesRegex(ValueError, "FIELD_SHAPE"):
                client.daily()

    def test_empty_rows_remain_empty(self):
        client = self.client_module().TushareHTTPS("fixture-token")
        with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                mock.patch.object(fund_source, "_tushare_call", return_value={
                    "fields": ["trade_date", "close"], "items": []}):
            frame = client.daily()
            self.assertTrue(frame.empty)
            self.assertEqual(list(frame.columns), ["trade_date", "close"])

    def test_upstream_errors_do_not_expose_token(self):
        client = self.client_module().TushareHTTPS("fixture-token")
        with mock.patch.dict(os.environ, {"AR_OFFLINE": ""}), \
                mock.patch.object(fund_source, "_tushare_call", side_effect=RuntimeError("fixture-token")):
            with self.assertRaises(RuntimeError) as raised:
                client.daily()
            self.assertNotIn("fixture-token", str(raised.exception))
            self.assertTrue(raised.exception.__suppress_context__)

    def consumer_context(self):
        module = self.client_module()
        stack = contextlib.ExitStack()
        factory = stack.enter_context(mock.patch.object(module, "TushareHTTPS", return_value=object()))
        legacy = types.SimpleNamespace(pro_api=mock.Mock(side_effect=RuntimeError("legacy SDK used")))
        stack.enter_context(mock.patch.dict(sys.modules, {"tushare": legacy}))
        stack.enter_context(mock.patch.dict(os.environ, {"TUSHARE_TOKEN": "fixture-token", "AR_OFFLINE": ""}))
        return stack, factory

    def test_red_flag_cli_uses_https_reader(self):
        stack, factory = self.consumer_context()
        with stack, mock.patch.object(sys, "argv", ["red_flag_gate.py", "TEST.SZ"]), \
                mock.patch.object(red_flag_gate, "check_ticker", return_value={}) as check, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(red_flag_gate.main(), 0)
            self.assertIs(check.call_args.args[0], factory.return_value)

    def test_watchlist_battery_cli_uses_https_reader(self):
        stack, factory = self.consumer_context()
        with stack, mock.patch.object(sys, "argv", ["full_battery.py", "TEST.SZ"]), \
                mock.patch.object(full_battery, "battery", return_value={}) as check, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(full_battery.main(), 0)
            self.assertIs(check.call_args.args[0], factory.return_value)

    def test_funnel_battery_provider_uses_https_reader(self):
        stack, factory = self.consumer_context()
        with stack, mock.patch.object(full_battery, "battery", return_value={"dims": {}}) as check:
            provider, why = funnel_dag._battery_provider()
            self.assertEqual(why, "")
            self.assertIsNotNone(provider)
            provider("TEST.SZ", "20260907")
            self.assertIs(check.call_args.args[0], factory.return_value)

    def test_overnight_uses_https_reader_and_preserves_pit_proxy_gates(self):
        import pandas as pd
        stack, factory = self.consumer_context()
        with stack:
            factory.return_value = types.SimpleNamespace(index_global=lambda **_: pd.DataFrame([
                {"trade_date": "20260907", "pct_chg": 99},
                {"trade_date": "20260904", "pct_chg": 1.5}]))
            actual = overnight_anchor.fetch_auto_anchors(today="20260907")
            self.assertEqual(set(actual), {"A50", "IXIC", "TWII"})
            self.assertEqual({r["as_of"] for r in actual.values()}, {"20260904"})
            self.assertTrue(actual["TWII"]["proxy"])
            self.assertEqual(actual["TWII"]["proxy_for"], "SOX")
            self.assertNotIn("SOX", actual)


if __name__ == "__main__":
    unittest.main(verbosity=2)
