"""Nonproduction GDELT RSS metadata ingest and read boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/llm"))
from experiments.research_workflows import gdelt_news_index as news
import nonprod_workbench as wb
import workbench_workspace as ws

NOW = "2026-09-30T16:30:00+00:00"
MODIFIED = "2026-09-30T16:26:00+00:00"


def article(url="https://example.org/one", title="Semiconductor capacity update",
            pub_date="Wed, 30 Sep 2026 15:12:00 GMT"):
    return (f"<item><title>{escape(title)}</title><link>{escape(url)}</link>"
            f"<pubDate>{escape(pub_date)}</pubDate><description>publisher-owned text"
            "</description></item>")


def feed(*items):
    return ("<rss><channel>" + "".join(items) + "</channel></rss>").encode()


class GdeltIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def poll(self, rows=None, now=NOW, modified=MODIFIED, raw=None):
        return news.poll_once(self.root, query_id="semiconductor",
                              query="semiconductor,半导体,芯片", now=now,
                              fetch=lambda: {"raw": raw if raw is not None else feed(*(rows or [])),
                                             "feed_modified_at": modified})

    def test_cursor_overlap_dedup_and_metadata_only(self):
        first = self.poll([article()])
        self.assertEqual(first["cursor_end"], MODIFIED)
        self.assertEqual(first["status"], "OK")
        self.assertEqual(first["events"][0]["indexed_at"], MODIFIED)
        self.assertEqual(first["events"][0]["article_date_or_seen"], "2026-09-30T15:12:00+00:00")
        self.assertNotIn("description", first["events"][0])
        self.assertEqual(first["authority"]["trade_action"], False)
        second = self.poll([article(), article("https://example.org/two", "New 半导体 item")],
                           now="2026-09-30T16:45:00+00:00",
                           modified="2026-09-30T16:41:00+00:00")
        self.assertEqual(second["cursor_end"], "2026-09-30T16:41:00+00:00")
        self.assertEqual(len(second["events"]), 2)
        self.assertEqual(second["new_count"], 1)
        self.assertEqual(news.read_snapshot(self.root), second)

    def test_same_feed_modified_is_no_change(self):
        self.poll([article()])
        same = self.poll([article("https://example.org/two")])
        self.assertEqual((same["status"], same["cursor_end"], same["new_count"], len(same["events"])),
                         ("OK_NO_CHANGE", MODIFIED, 0, 1))

    def test_ancestor_alias_cannot_write_into_production_root(self):
        production = self.root / "ar-live"
        sandbox = production / "shadow"
        sandbox.mkdir(parents=True)
        alias = self.root / "alias"
        alias.symlink_to(production, target_is_directory=True)
        with self.assertRaisesRegex(news.IndexError, "NONPRODUCTION_ROOT_REQUIRED"):
            news.poll_once(alias / "shadow", query_id="semiconductor",
                           query="semiconductor,半导体,芯片", now=NOW,
                           fetch=lambda: {"raw": feed(), "feed_modified_at": MODIFIED})
        self.assertFalse((sandbox / "gdelt-news").exists())

    def test_source_failure_does_not_advance_cursor_and_retry_recovers(self):
        self.poll([article()])
        def fail():
            raise news.SourceFailure("SOURCE_DOWN", "TLS_OR_NETWORK_FAILURE")
        failed = news.poll_once(self.root, query_id="semiconductor",
                                query="semiconductor,半导体,芯片",
                                now="2026-09-30T16:45:00+00:00", fetch=fail)
        self.assertEqual((failed["status"], failed["reason"], failed["cursor_end"]),
                         ("SOURCE_DOWN", "TLS_OR_NETWORK_FAILURE", MODIFIED))
        recovered = self.poll([article("https://example.org/two")],
                              now="2026-09-30T16:45:00+00:00",
                              modified="2026-09-30T16:41:00+00:00")
        self.assertEqual(recovered["cursor_end"], "2026-09-30T16:41:00+00:00")

    def test_saturated_response_is_partial_and_cursor_stays_put(self):
        result = self.poll([article(f"https://example.org/{i}") for i in range(news.MAX_RECORDS)])
        self.assertEqual((result["status"], result["cursor_end"], result["events"]),
                         ("PARTIAL_TRUNCATED", None, []))

    def test_query_change_and_changed_duplicate_are_refused(self):
        self.poll([article()])
        with self.assertRaisesRegex(news.IndexError, "QUERY_IDENTITY_CHANGED"):
            news.poll_once(self.root, query_id="semiconductor", query="different",
                           now=NOW, fetch=lambda: {"raw": feed(), "feed_modified_at": MODIFIED})
        conflict = self.poll([article(title="Changed semiconductor title")],
                             now="2026-09-30T16:45:00+00:00",
                             modified="2026-09-30T16:41:00+00:00")
        self.assertEqual((conflict["status"], conflict["reason"], conflict["cursor_end"]),
                         ("BAD_PROVIDER_PAYLOAD", "EVENT_ID_CONFLICT", MODIFIED))

    def test_stale_feed_and_malformed_xml_do_not_advance(self):
        self.poll([article()])
        stale = self.poll([article("https://example.org/two")],
                          now="2026-09-30T17:00:00+00:00")
        self.assertEqual((stale["status"], stale["cursor_end"]), ("STALE_SOURCE", MODIFIED))
        malformed = self.poll(now="2026-09-30T17:00:00+00:00",
                              modified="2026-09-30T16:56:00+00:00",
                              raw=b"<!DOCTYPE rss [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><rss/>")
        self.assertEqual((malformed["status"], malformed["reason"], malformed["cursor_end"]),
                         ("BAD_PROVIDER_PAYLOAD", "XML_ENTITY_FORBIDDEN", MODIFIED))

    def test_delayed_feed_is_visible_but_not_called_realtime(self):
        result = self.poll([article()], now="2026-09-30T16:38:00+00:00")
        self.assertEqual((result["status"], result["reason"], result["cursor_end"]),
                         ("SOURCE_DELAYED", "FEED_AGE_GT_10M", MODIFIED))
        self.assertEqual(result["latency_class"], "RSS_INDEX_NOT_FLASH")

    def test_metadata_loss_and_gap_are_visible(self):
        self.poll([article()])
        second = self.poll([article("https://example.org/two"), "<item><link>x</link></item>"],
                           now="2026-09-30T16:52:00+00:00",
                           modified="2026-09-30T16:48:00+00:00")
        self.assertEqual((second["status"], second["missing_metadata_count"], second["gap_status"]),
                         ("PARTIAL_METADATA", 1, "POSSIBLE_15M_FEED_GAP"))

    def test_unmatched_article_is_not_included(self):
        result = self.poll([article(title="General market report")])
        self.assertEqual((result["status"], result["feed_item_count"], result["matched_count"],
                          result["events"]), ("EMPTY_VALID", 1, 0, []))

    def test_old_events_age_out_in_new_committed_snapshot(self):
        self.poll([article()])
        later = self.poll([article("https://example.org/two")],
                          now="2026-10-03T16:30:00+00:00",
                          modified="2026-10-03T16:26:00+00:00")
        self.assertEqual(later["gap_status"], "POSSIBLE_15M_FEED_GAP")
        self.assertEqual(len(later["events"]), 1)
        self.assertEqual(later["new_count"], 1)

    def test_hash_and_url_tamper_fail_closed(self):
        self.poll([article()])
        path = self.root / "gdelt-news" / "current.json"
        changed = json.loads(path.read_text())
        changed["events"][0]["title"] = "forged"
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(news.IndexError, "SNAPSHOT_HASH_INVALID"):
            news.read_snapshot(self.root)

    def test_network_entry_is_explicit_and_fixed_host(self):
        with mock.patch.dict(os.environ, {"AR_GDELT_NETWORK": "0", "AR_OFFLINE": "1"}):
            with self.assertRaisesRegex(news.IndexError, "NETWORK_OPT_IN_REQUIRED"):
                news.fetch_live()

    def test_network_cli_refuses_before_creating_state(self):
        with mock.patch.dict(os.environ, {"AR_GDELT_NETWORK": "0", "AR_OFFLINE": "1"}):
            with self.assertRaisesRegex(news.IndexError, "NETWORK_OPT_IN_REQUIRED"):
                news.main(["--sandbox-root", str(self.root), "--query-id", "semiconductor",
                           "--query", "semiconductor", "--network"])
        self.assertFalse((self.root / "gdelt-news").exists())

    def test_live_fetch_uses_one_fixed_endpoint_and_bounded_read(self):
        limits = []
        class Response:
            status = 200
            headers = {"Content-Type": "application/rss+xml", "Last-Modified":
                       "Wed, 30 Sep 2026 16:26:00 GMT"}
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self, limit):
                limits.append(limit)
                return feed(article())
        class Opener:
            def open(self, request, timeout):
                self_assert = unittest.TestCase()
                self_assert.assertEqual((timeout, request.full_url), (10, news.ENDPOINT))
                return Response()
        with mock.patch.dict(os.environ, {"AR_GDELT_NETWORK": "1", "AR_OFFLINE": "0"}):
            with mock.patch.object(news.urllib.request, "build_opener", return_value=Opener()) as build:
                data = news.fetch_live()
        self.assertEqual(data, {"raw": feed(article()), "feed_modified_at": MODIFIED})
        self.assertEqual(limits, [news.MAX_FEED_RESPONSE + 1])
        self.assertIs(build.call_args.args[0], news._NoRedirect)

    def test_offline_requires_frozen_modified_header(self):
        frozen = self.root / "feed.rss"
        frozen.write_bytes(feed(article()))
        with self.assertRaisesRegex(news.IndexError, "OFFLINE_LAST_MODIFIED_REQUIRED"):
            news.main(["--sandbox-root", str(self.root), "--query-id", "semiconductor",
                       "--query", "semiconductor", "--offline-response", str(frozen)])
        self.assertFalse((self.root / "gdelt-news").exists())

    def test_workbench_is_read_only_and_displays_source_failure(self):
        self.poll([article()])
        path = self.root / "gdelt-news" / "current.json"
        before = path.read_bytes()
        store = wb.Store(self.root / "workbench-state")
        system = ws.Workspace(store, news_index_snapshot=path)
        projected = system.snapshot()["news_index"]
        self.assertEqual(projected["status"], "OK")
        self.assertEqual(projected["attribution_url"], "https://www.gdeltproject.org/")
        self.assertEqual(path.read_bytes(), before)
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
                  "console.log(JSON.stringify(['SOURCE_DOWN','STALE_SOURCE','PARTIAL_METADATA','SOURCE_DELAYED',"
                  "'PARTIAL_TRUNCATED','E3_UNVERIFIED_NEWS_INDEX'].map(statusTone)));" )
        result = subprocess.run(["node", "--input-type=module", "-e", script],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), ["red", "red", "amber", "amber", "amber", "amber"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
