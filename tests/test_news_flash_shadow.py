"""Offline news-flash evidence gates; all source rows are synthetic."""
import copy
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.research_workflows import news_flash_shadow as news


def cassette():
    return {
        "schema": "ar.news-flash-cassette.v1",
        "sample_purpose": "WORKFLOW_DEBUG",
        "provider": "tushare.news",
        "src": "sina",
        "window_start": "2026-09-30T09:30:00+08:00",
        "window_end": "2026-09-30T09:35:00+08:00",
        "checked_at": "2026-09-30T09:35:10+08:00",
        "source_status": "OK",
        "rows": [{"datetime": "2026-09-30 09:32:00", "title": "Synthetic company note",
                  "content": "Synthetic source text", "channels": "market"}],
    }


class NewsFlashShadowTests(unittest.TestCase):
    def test_deduplicates_and_never_grants_authority(self):
        source = cassette()
        source["rows"].append(copy.deepcopy(source["rows"][0]))
        result = news.normalize(source)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["source_authenticity"], "UNVERIFIED_CASSETTE")
        self.assertFalse(result["licensed_team_display"])
        self.assertEqual(len(result["events"]), 1)
        event = result["events"][0]
        self.assertEqual(event["evidence_tier"], "E2_UNVERIFIED")
        self.assertEqual(event["entity_refs"], [])
        self.assertIsNone(event["source_url"])
        self.assertEqual(event["published_at"], "2026-09-30T01:32:00+00:00")
        self.assertFalse(any(result["authority"].values()))

    def test_denied_source_is_data_blocked_not_empty_valid(self):
        source = cassette()
        source["source_status"] = "ACCESS_DENIED"
        source["rows"] = []
        result = news.normalize(source)
        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertEqual(result["reason"], "ACCESS_DENIED")
        self.assertEqual(result["events"], [])

    def test_denied_source_cannot_carry_rows(self):
        source = cassette()
        source["source_status"] = "ACCESS_DENIED"
        with self.assertRaises(news.NewsFlashError):
            news.normalize(source)

    def test_saturated_window_is_partial_not_complete(self):
        source = cassette()
        source["rows"] = [dict(source["rows"][0], title=f"Synthetic {n:04d}")
                          for n in range(1500)]
        result = news.normalize(source)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["reason"], "POSSIBLE_SOURCE_TRUNCATION")
        self.assertEqual(len(result["events"]), 1500)

    def test_future_and_out_of_window_rows_are_rejected(self):
        for published in ("2026-09-30 09:35:11", "2026-09-30 09:29:59"):
            source = cassette()
            source["rows"][0]["datetime"] = published
            with self.subTest(published=published), self.assertRaises(news.NewsFlashError):
                news.normalize(source)

    def test_duplicate_identity_with_changed_content_is_rejected(self):
        source = cassette()
        changed = dict(source["rows"][0], content="Conflicting revision")
        source["rows"].append(changed)
        with self.assertRaises(news.NewsFlashError):
            news.normalize(source)

    def test_capture_verify_tamper_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "batch"
            news.capture(cassette(), directory, sandbox_root=root)
            receipt = news.verify(directory)
            self.assertTrue(receipt["ok"])
            self.assertEqual(receipt["status"], "OK")
            with self.assertRaises(news.NewsFlashError):
                news.capture(cassette(), directory, sandbox_root=root)
            normalized = directory / "news_flash.json"
            value = json.loads(normalized.read_text(encoding="utf-8"))
            value["authority"]["trade_action"] = True
            normalized.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(news.NewsFlashError):
                news.verify(directory)

    def test_partial_directory_without_manifest_is_not_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "batch"
            news.capture(cassette(), directory, sandbox_root=root)
            (directory / "manifest.json").unlink()
            with self.assertRaises(news.NewsFlashError):
                news.verify(directory)

    def test_output_must_be_direct_child_of_declared_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sandbox"
            root.mkdir()
            outside = Path(tmp) / "outside"
            with self.assertRaises(news.NewsFlashError):
                news.capture(cassette(), outside, sandbox_root=root)
            self.assertFalse(outside.exists())
            link = root / "link"
            link.symlink_to(Path(tmp), target_is_directory=True)
            with self.assertRaises(news.NewsFlashError):
                news.capture(cassette(), link / "escaped", sandbox_root=root)
            self.assertFalse((Path(tmp) / "escaped").exists())

    def test_sandbox_root_rebound_never_writes_to_outside_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, moved, outside = (base / name for name in ("root", "moved", "outside"))
            root.mkdir()
            outside.mkdir()
            original_mkdir = os.mkdir
            swapped = False

            def swap_before_create(path, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if not swapped and Path(path).name == "batch":
                    swapped = True
                    root.rename(moved)
                    root.symlink_to(outside, target_is_directory=True)
                if dir_fd is None:
                    return original_mkdir(path, mode)
                return original_mkdir(path, mode, dir_fd=dir_fd)

            with patch.object(news.os, "mkdir", side_effect=swap_before_create):
                error = None
                try:
                    news.capture(cassette(), root / "batch", sandbox_root=root)
                except Exception as exc:
                    error = exc
            self.assertTrue(swapped)
            self.assertFalse((outside / "batch").exists())
            self.assertIsInstance(error, news.NewsFlashError)

    def test_late_collection_is_not_realtime_ok(self):
        source = cassette()
        source["checked_at"] = "2026-09-30T10:00:00+08:00"
        result = news.normalize(source)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["reason"], "COLLECTION_LAG")

    def test_capture_requires_explicit_offline_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "batch"
            with patch.dict("os.environ", {"AR_OFFLINE": "0"}):
                with self.assertRaises(news.NewsFlashError):
                    news.capture(cassette(), output, sandbox_root=root)
            self.assertFalse(output.exists())

    def test_cli_capture_and_verify_use_the_same_frozen_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "synthetic.json"
            source.write_text(json.dumps(cassette()), encoding="utf-8")
            output = root / "batch"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, news.main([
                    "capture", "--input", str(source), "--sandbox-root", str(root),
                    "--output-dir", str(output)]))
                self.assertEqual(0, news.main([
                    "verify", "--output-dir", str(output)]))
            self.assertEqual(news.verify(output)["status"], "OK")


if __name__ == "__main__":
    unittest.main()
