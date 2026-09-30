"""Nonproduction GDELT metadata ingest and workbench read boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/llm"))
from experiments.research_workflows import gdelt_news_index as news
import nonprod_workbench as wb
import workbench_workspace as ws


NOW = "2026-09-30T16:30:00+00:00"


def article(url="https://example.org/one", title="Foundry capacity update",
            seen="20260930T161200Z"):
    return {"url": url, "title": title, "seendate": seen,
            "domain": "example.org", "language": "English", "sourcecountry": "United States",
            "socialimage": "https://example.org/image.jpg", "summary": "publisher-owned text"}


class GdeltIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []

    def poll(self, rows, now=NOW):
        def fetch(query, start, end):
            self.calls.append((query, start, end))
            return {"articles": rows}
        return news.poll_once(self.root, query_id="semiconductor", query="semiconductor",
                              now=now, fetch=fetch)

    def test_cursor_overlap_dedup_and_metadata_only(self):
        first = self.poll([article()])
        self.assertEqual(first["cursor_end"], "2026-09-30T16:15:00+00:00")
        self.assertEqual(first["status"], "OK")
        self.assertEqual(len(first["events"]), 1)
        self.assertNotIn("summary", first["events"][0])
        self.assertNotIn("content", first["events"][0])
        self.assertEqual(first["content_scope"], "METADATA_ONLY")
        self.assertEqual(first["authority"]["trade_action"], False)
        second = self.poll([article(), article("https://example.org/two", "New article",
                                                "20260930T162200Z")],
                           "2026-09-30T16:45:00+00:00")
        self.assertEqual(self.calls[1][1], "2026-09-30T16:10:00+00:00")
        self.assertEqual(self.calls[1][2], "2026-09-30T16:30:00+00:00")
        self.assertEqual(second["cursor_end"], "2026-09-30T16:30:00+00:00")
        self.assertEqual(len(second["events"]), 2)
        self.assertEqual(second["new_count"], 1)
        self.assertEqual(news.read_snapshot(self.root), second)

    def test_no_new_window_makes_no_provider_call(self):
        self.poll([article()])
        self.poll([article()])
        self.assertEqual(len(self.calls), 1)

    def test_ancestor_alias_cannot_write_into_production_root(self):
        production = self.root / "ar-live"
        sandbox = production / "shadow"
        sandbox.mkdir(parents=True)
        alias = self.root / "alias"
        alias.symlink_to(production, target_is_directory=True)
        with self.assertRaisesRegex(news.IndexError, "NONPRODUCTION_ROOT_REQUIRED"):
            news.poll_once(alias / "shadow", query_id="semiconductor",
                           query="semiconductor", now=NOW,
                           fetch=lambda *_: {"articles": []})
        self.assertFalse((sandbox / "gdelt-news").exists())

    def test_source_failure_does_not_advance_cursor_and_retry_recovers(self):
        self.poll([article()])
        def fail(query, start, end):
            self.calls.append((query, start, end))
            raise news.SourceFailure("SOURCE_DOWN")
        failed = news.poll_once(self.root, query_id="semiconductor", query="semiconductor",
                                now="2026-09-30T16:45:00+00:00", fetch=fail)
        self.assertEqual(failed["status"], "SOURCE_DOWN")
        self.assertEqual(failed["cursor_end"], "2026-09-30T16:15:00+00:00")
        self.assertEqual(failed["last_good_end"], "2026-09-30T16:15:00+00:00")
        recovered = self.poll([article("https://example.org/two", "New article",
                                       "20260930T162200Z")], "2026-09-30T16:45:00+00:00")
        self.assertEqual(recovered["cursor_end"], "2026-09-30T16:30:00+00:00")
        self.assertEqual(self.calls[1][1:], self.calls[2][1:])

    def test_saturated_response_is_partial_and_cursor_stays_put(self):
        saturated = [article(f"https://example.org/{i}", f"Item {i}") for i in range(250)]
        result = self.poll(saturated)
        self.assertEqual(result["status"], "PARTIAL_TRUNCATED")
        self.assertIsNone(result["cursor_end"])
        self.assertEqual(result["events"], [])

    def test_query_change_and_changed_duplicate_are_refused(self):
        self.poll([article()])
        with self.assertRaisesRegex(news.IndexError, "QUERY_IDENTITY_CHANGED"):
            news.poll_once(self.root, query_id="semiconductor", query="different",
                           now="2026-09-30T16:45:00+00:00", fetch=lambda *_: {"articles": []})
        conflict = self.poll([article(title="Changed title")], "2026-09-30T16:45:00+00:00")
        self.assertEqual(conflict["status"], "BAD_PROVIDER_PAYLOAD")
        self.assertEqual(conflict["reason"], "EVENT_ID_CONFLICT")
        self.assertEqual(news.read_snapshot(self.root)["cursor_end"],
                         "2026-09-30T16:15:00+00:00")

    def test_invalid_provider_row_is_visible_and_keeps_cursor(self):
        self.poll([article()])
        bad = self.poll([article(url="javascript:alert(1)")],
                        "2026-09-30T16:45:00+00:00")
        self.assertEqual(bad["status"], "BAD_PROVIDER_PAYLOAD")
        self.assertEqual(bad["reason"], "ARTICLE_URL_INVALID")
        self.assertEqual(bad["cursor_end"], "2026-09-30T16:15:00+00:00")

    def test_hash_and_url_tamper_fail_closed(self):
        self.poll([article()])
        path = self.root / "gdelt-news" / "current.json"
        changed = json.loads(path.read_text())
        changed["events"][0]["title"] = "forged"
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(news.IndexError, "SNAPSHOT_HASH_INVALID"):
            news.read_snapshot(self.root)

    def test_network_entry_is_explicit_and_fixed_host(self):
        previous = os.environ.pop("AR_GDELT_NETWORK", None)
        try:
            with self.assertRaisesRegex(news.IndexError, "NETWORK_OPT_IN_REQUIRED"):
                news.fetch_live("semiconductor", "2026-09-30T16:00:00+00:00",
                                "2026-09-30T16:15:00+00:00")
        finally:
            if previous is not None:
                os.environ["AR_GDELT_NETWORK"] = previous

    def test_network_cli_refuses_before_creating_state(self):
        with mock.patch.dict(os.environ, {"AR_GDELT_NETWORK": "0", "AR_OFFLINE": "1"}):
            with self.assertRaisesRegex(news.IndexError, "NETWORK_OPT_IN_REQUIRED"):
                news.main(["--sandbox-root", str(self.root), "--query-id", "semiconductor",
                           "--query", "semiconductor", "--network"])
        self.assertFalse((self.root / "gdelt-news").exists())

    def test_live_fetch_uses_one_fixed_endpoint_and_bounded_read(self):
        outer = self
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self, limit):
                self_limit.append(limit)
                return b'{"articles":[]}'
        self_limit = []
        class Opener:
            def open(self, request, timeout):
                outer.assertEqual(timeout, 10)
                outer.assertTrue(request.full_url.startswith(news.ENDPOINT + "?"))
                outer.assertNotIn("example.org", request.full_url)
                return Response()
        with mock.patch.dict(os.environ, {"AR_GDELT_NETWORK": "1"}):
            with mock.patch.dict(os.environ, {"AR_OFFLINE": "0"}):
                with mock.patch.object(news.urllib.request, "build_opener", return_value=Opener()) as build:
                    data = news.fetch_live("semiconductor", "2026-09-30T16:00:00+00:00",
                                           "2026-09-30T16:15:00+00:00")
        self.assertEqual(data, {"articles": []})
        self.assertEqual(self_limit, [news.MAX_RESPONSE + 1])
        self.assertIs(build.call_args.args[0], news._NoRedirect)

    def test_workbench_is_read_only_and_displays_source_failure(self):
        self.poll([article()])
        before = (self.root / "gdelt-news" / "current.json").read_bytes()
        store = wb.Store(self.root / "workbench-state")
        system = ws.Workspace(store, news_index_snapshot=self.root / "gdelt-news" / "current.json")
        projected = system.snapshot()["news_index"]
        self.assertEqual(projected["status"], "OK")
        self.assertEqual(projected["attribution_url"], "https://www.gdeltproject.org/")
        self.assertEqual((self.root / "gdelt-news" / "current.json").read_bytes(), before)
        path = self.root / "gdelt-news" / "current.json"
        tampered = json.loads(path.read_text())
        tampered["authority"]["trade_action"] = True
        path.write_text(json.dumps(tampered))
        broken = system.snapshot()
        self.assertEqual(broken["news_index_error"], "NEWS_INDEX_INTEGRITY_ERROR")
        self.assertIsNone(broken["news_index"])

    def test_workbench_rejects_self_resealed_authority_and_source_overlap(self):
        self.poll([article()])
        path = self.root / "gdelt-news" / "current.json"
        payload = json.loads(path.read_text())
        payload["authority"]["trade_action"] = True
        payload["snapshot_hash"] = news.digest({key: value for key, value in payload.items()
                                                 if key != "snapshot_hash"})
        path.write_text(json.dumps(payload))
        store = wb.Store(self.root / "state")
        system = ws.Workspace(store, news_index_snapshot=path)
        self.assertEqual(system.snapshot()["news_index_error"], "NEWS_INDEX_INTEGRITY_ERROR")
        with self.assertRaisesRegex(ws.WorkspaceError, "NEWS_INDEX_SOURCE_MUST_BE_DISJOINT"):
            ws.Workspace(store, news_index_snapshot=self.root / "state/gdelt-news/current.json")

    def test_ui_classifies_index_degradation(self):
        module = (ROOT / "tools/nonprod_workbench/ui/status-tone.mjs").as_uri()
        script = (f"import {{ statusTone }} from {json.dumps(module)};"
                  "console.log(JSON.stringify(['SOURCE_DOWN','ACCESS_DENIED',"
                  "'PARTIAL_TRUNCATED','E3_UNVERIFIED_NEWS_INDEX'].map(statusTone)));" )
        result = subprocess.run(["node", "--input-type=module", "-e", script],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), ["red", "red", "amber", "amber"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
