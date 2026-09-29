#!/usr/bin/env python3
"""Announcement feed sidecar (contract L v0.1): battery side channel → funnel stage → verifiers.

Pins:
  · the watchlist battery row is byte-identical with and without the sink
  · item identity binds the full title; DATA_BLOCKED is a null count, never 0
  · the sidecar is hashed by stage_battery.json, not by bundle_hash / final files
  · run_nightly, U4 pre-decision and the EvidenceView all fail closed on a
    tampered or unlisted sidecar, and old bundles without one still verify

不是买卖指令；研究信号，human executes。
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))

import announcement_feed as af  # noqa: E402
import full_battery  # noqa: E402
import funnel_dag as dag  # noqa: E402
import funnel_pipeline as fp  # noqa: E402
import red_flag_gate  # noqa: E402
import tushare_https  # noqa: E402
import run_nightly as nightly  # noqa: E402
import test_full_battery_evidence as battery_fixture  # noqa: E402
import test_funnel_dag_offline as dag_fixture  # noqa: E402
import test_u4_pre_decision_runtime as u4_fixture  # noqa: E402
import u4_pre_decision as pre  # noqa: E402
from evidence_view import DirectoryCapability, EvidenceView  # noqa: E402

AS_OF = "20260923"
RUN_ID = "20260923_203000_1790000000000000000_feed0001"
CAPTURED = "2026-09-23T12:30:00+00:00"
LONG_TITLE = "关于公司控股股东部分股份解除质押及再质押的公告（第二次更正后的完整标题，超过三十六个字符）"


def run_battery(titles, *, sink=None, provider=None):
    with mock.patch.object(red_flag_gate, "check_ticker", return_value={
        "verdict": "PASS", "reasons": [], "latest_e1_date": "20260820",
    }), mock.patch.object(full_battery, "_fetch_anns_eastmoney", return_value=titles):
        kwargs = {} if sink is None else {"announcement_sink": sink}
        return full_battery.battery(provider or battery_fixture.FakeProvider(),
                                    battery_fixture.CODE, battery_fixture.TARGET, **kwargs)


def capture(code, items, *, status="OK", err=None, channel="EASTMONEY_ANN_A"):
    return {"ts_code": code, "source_channel": channel if items is not None else None,
            "items": items, "status": status, "err": err, "captured_at": CAPTURED}


def captured_worker(code, target):
    """Module-level funnel worker for the real spawn collector (picklable by name)."""
    import funnel_dag
    import test_funnel_dag_offline as fixtures
    date = target[:4] + "-" + target[4:6] + "-" + target[6:]
    return funnel_dag.CapturedRow((fixtures.complete_row(code, target),
                                   capture(code, [[date, f"spawned filing {code}"]])))


def manifest_for(codes):
    return {"ts_codes": list(codes), "manifest_hash": "m" * 64}


def battery_for(codes, *, blocked=()):
    rows = []
    for code in codes:
        row = dag_fixture.complete_row(code, AS_OF)
        if code in blocked:
            row["dims"]["消息面"] = {"status": "DATA_BLOCKED", "err": "fixture blocked"}
        rows.append(row)
    return {"as_of": AS_OF, "run_id": RUN_ID, "results": rows, "rows_hash": fp._hash(rows)}


def build(codes, captures, *, not_collected=None, blocked=()):
    manifest, battery = manifest_for(codes), battery_for(codes, blocked=blocked)
    feed = af.build_feed(as_of=AS_OF, run_id=RUN_ID, generated_at=CAPTURED, manifest=manifest,
                         battery=battery, captures=captures, not_collected=not_collected or {})
    return feed, manifest, battery


class BatterySideChannelTests(unittest.TestCase):
    def setUp(self):
        offline = mock.patch.dict(os.environ, {"AR_OFFLINE": "1"})
        offline.start()
        self.addCleanup(offline.stop)

    def test_watchlist_row_is_byte_identical_with_and_without_sink(self):
        titles = [("2026-09-23", LONG_TITLE), ("2026-09-10", "older")]
        plain = run_battery(titles)
        sink = []
        with_sink = run_battery(titles, sink=sink)
        self.assertEqual(json.dumps(plain, ensure_ascii=False, sort_keys=True),
                         json.dumps(with_sink, ensure_ascii=False, sort_keys=True))
        self.assertEqual({"ts_code", "checked_at", "dims", "completeness"}, set(plain))
        self.assertEqual(1, len(sink))
        parameter = inspect.signature(full_battery.battery).parameters["announcement_sink"]
        self.assertIs(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIsNone(parameter.default)
        # The watchlist entry point never passes a sink.
        self.assertNotIn("announcement_sink", inspect.getsource(full_battery.main))

    def test_capture_keeps_full_titles_and_mirrors_the_dimension(self):
        sink = []
        run_battery([("2026-09-23", LONG_TITLE)], sink=sink)
        record = sink[0]
        self.assertEqual(af.CAPTURE_KEYS, set(record))
        self.assertEqual("EASTMONEY_ANN_A", record["source_channel"])
        self.assertEqual([["2026-09-23", LONG_TITLE]], record["items"])
        self.assertGreater(len(record["items"][0][1]), 36)
        self.assertEqual("OK", record["status"])

    def test_fallback_channel_is_named_and_blocked_source_has_no_items(self):
        sink = []
        provider = battery_fixture.FakeProvider(announcements=[("20260923", "fallback filing")])
        run_battery(None, sink=sink, provider=provider)
        self.assertEqual("TUSHARE_ANNS_D", sink[0]["source_channel"])
        blocked = []
        run_battery(None, sink=blocked)
        self.assertIsNone(blocked[0]["source_channel"])
        self.assertIsNone(blocked[0]["items"])
        self.assertEqual("DATA_BLOCKED", blocked[0]["status"])
        self.assertTrue(blocked[0]["err"])

    def test_worker_writes_the_capture_beside_the_row(self):
        row = dag_fixture.complete_row("000001.SZ", AS_OF)
        record = capture("000001.SZ", [["2026-09-23", "x"]])
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "0.json"
            dag._execute(lambda _c, _t: dag.CapturedRow((row, record)), "000001.SZ", AS_OF, str(output))
            payload = json.loads(output.read_text("utf-8"))
        self.assertEqual(row, payload["row"])
        self.assertEqual(record, payload["announcement_capture"])

    def test_real_collector_carries_the_capture_through_spawned_workers(self):
        import test_announcement_feed as fixtures
        codes = ["000001.SZ", "000002.SZ"]
        outcomes = dag.collect_rows(codes, AS_OF, fixtures.captured_worker, max_workers=2,
                                    row_seconds=30, budget_seconds=60)
        self.assertEqual(codes, [outcome["ts_code"] for outcome in outcomes])
        for outcome in outcomes:
            self.assertIsNone(outcome["reason"], outcome)
            self.assertEqual(outcome["ts_code"], outcome["row"]["ts_code"])
            self.assertEqual(f"spawned filing {outcome['ts_code']}",
                             outcome["announcement_capture"]["items"][0][1])

    def test_funnel_worker_passes_a_sink_and_returns_the_last_capture(self):
        received = []

        def fake_battery(pro, tk, today, *, announcement_sink=None):
            received.append(announcement_sink)
            if isinstance(announcement_sink, list):
                announcement_sink.append(capture(tk, [["2026-09-22", "first"]]))
                announcement_sink.append(capture(tk, [["2026-09-23", "last"]]))
            return dag_fixture.complete_row(tk, today)

        with mock.patch.object(full_battery, "battery", fake_battery), \
                mock.patch.object(tushare_https, "TushareHTTPS", lambda token: object()):
            result = dag._read_battery_capture("offline-token", "000001.SZ", AS_OF)
        self.assertIsInstance(received[0], list, "the funnel worker must pass a list sink")
        self.assertIsInstance(result, dag.CapturedRow)
        self.assertEqual("000001.SZ", result[0]["ts_code"])
        self.assertIsNotNone(result[1], "a missing sink would make every ticker DATA_BLOCKED")
        self.assertEqual([["2026-09-23", "last"]], result[1]["items"])


class FeedContractTests(unittest.TestCase):
    def test_item_id_changes_with_title(self):
        first = af.item_id("000001.SZ", "EASTMONEY_ANN_A", "2026-09-23", "A")
        second = af.item_id("000001.SZ", "EASTMONEY_ANN_A", "2026-09-23", "B")
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("sha256:"))

    def test_eligibility_same_day_and_after_as_of_are_explicit(self):
        feed, _m, _b = build(["000001.SZ"], {"000001.SZ": capture("000001.SZ", [
            ["2026-09-24", "tomorrow"], ["2026-09-23", "today"], ["2026-09-22", "yesterday"],
            ["2026-09-22", "yesterday"]])})
        by_title = {row["title"]: row for row in feed["rows"]}
        self.assertEqual(3, len(feed["rows"]), "an identical (date, title) is one item")
        self.assertEqual({"000001.SZ": 1}, feed["duplicate_titles_collapsed"], "the collapse is disclosed")
        self.assertEqual("AFTER_AS_OF_EXCLUDED", by_title["tomorrow"]["eligibility"])
        self.assertFalse(by_title["tomorrow"]["same_day_as_as_of"])
        self.assertEqual("AT_OR_BEFORE_AS_OF", by_title["today"]["eligibility"])
        self.assertTrue(by_title["today"]["same_day_as_as_of"])
        self.assertFalse(by_title["yesterday"]["same_day_as_as_of"])
        self.assertEqual(3, feed["per_ticker"][0]["item_count"])

    def test_tushare_dates_normalize_and_bad_dates_are_unverifiable(self):
        feed, _m, _b = build(["000001.SZ"], {"000001.SZ": capture("000001.SZ", [
            ["20260923", "compact"], ["unknown", "undated"]], channel="TUSHARE_ANNS_D")})
        by_title = {row["title"]: row for row in feed["rows"]}
        self.assertEqual("2026-09-23", by_title["compact"]["notice_date"])
        self.assertEqual("DATE_UNVERIFIABLE", by_title["undated"]["eligibility"])

    def test_blocked_tickers_are_null_counts_never_zero(self):
        codes = ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"]
        try:
            feed, _m, _b = build(codes, {
                "000001.SZ": capture("000001.SZ", None, status="DATA_BLOCKED", err="source down"),
                "000002.SZ": capture("000002.SZ", [["2026-09-23", "partial"]]),
                "000004.SZ": capture("000004.SZ", []),
            }, not_collected={"000003.SZ": "CANDIDATE_TIMEOUT"}, blocked={"000001.SZ", "000002.SZ"})
        except af.AnnouncementFeedError as exc:
            self.fail(f"a blocked ticker must build as DATA_BLOCKED, not fail: {exc}")
        per = {entry["ts_code"]: entry for entry in feed["per_ticker"]}
        for code in ("000001.SZ", "000002.SZ", "000003.SZ"):
            self.assertEqual("DATA_BLOCKED", per[code]["status"], code)
            self.assertIsNone(per[code]["item_count"], code)
            self.assertTrue(per[code]["err"], code)
        self.assertEqual("ROW_NOT_COLLECTED:CANDIDATE_TIMEOUT", per["000003.SZ"]["err"])
        self.assertEqual({"ts_code": "000004.SZ", "status": "OK", "err": None, "item_count": 0},
                         per["000004.SZ"], "a verified empty window is a real zero")

    def test_missing_or_malformed_capture_is_blocked(self):
        feed, _m, _b = build(["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"], {
            "000002.SZ": dict(capture("000002.SZ", [["2026-09-23", 7]])),
            "000003.SZ": dict(capture("000003.SZ", [["2026-09-23", "t"]]), captured_at=12345),
            "000004.SZ": dict(capture("000004.SZ", [["2026-09-23", "t"]]), status="MAYBE")})
        per = {entry["ts_code"]: entry for entry in feed["per_ticker"]}
        self.assertEqual("ANNOUNCEMENT_CAPTURE_MISSING", per["000001.SZ"]["err"])
        for code in ("000002.SZ", "000003.SZ", "000004.SZ"):
            self.assertEqual("ANNOUNCEMENT_CAPTURE_INVALID", per[code]["err"], code)
            self.assertIsNone(per[code]["item_count"], code)
        self.assertEqual([], feed["rows"], "a malformed capture degrades, it never fails the stage")

    def test_tampered_content_or_bindings_are_refused(self):
        feed, manifest, battery = build(["000001.SZ"], {"000001.SZ": capture(
            "000001.SZ", [["2026-09-23", "real title"]])})
        af.validate_feed(feed, manifest, battery)
        retitled = copy.deepcopy(feed)
        retitled["rows"][0]["title"] = "forged title"
        retitled["rows_hash"] = af._hash(retitled["rows"])
        with self.assertRaisesRegex(af.AnnouncementFeedError, "item_id"):
            af.validate_feed(retitled, manifest, battery)
        future_feed, future_manifest, future_battery = build(["000001.SZ"], {"000001.SZ": capture(
            "000001.SZ", [["2026-09-24", "tomorrow"]])})
        relabeled = copy.deepcopy(future_feed)
        relabeled["rows"][0]["eligibility"] = "AT_OR_BEFORE_AS_OF"
        relabeled["rows_hash"] = af._hash(relabeled["rows"])
        with self.assertRaisesRegex(af.AnnouncementFeedError, "not recomputable"):
            af.validate_feed(relabeled, future_manifest, future_battery)
        unhashed = copy.deepcopy(feed)
        unhashed["rows"][0]["same_day_as_as_of"] = False
        with self.assertRaisesRegex(af.AnnouncementFeedError, "rows_hash"):
            af.validate_feed(unhashed, manifest, battery)
        other = dict(battery, rows_hash="0" * 64)
        with self.assertRaisesRegex(af.AnnouncementFeedError, "bound to another"):
            af.validate_feed(feed, manifest, other)
        zero = copy.deepcopy(feed)
        zero["per_ticker"][0].update(status="DATA_BLOCKED", err="x", item_count=0)
        with self.assertRaisesRegex(af.AnnouncementFeedError, "null count"):
            af.validate_feed(zero, manifest, battery)
        blocked_battery = battery_for(["000001.SZ"], blocked={"000001.SZ"})
        claimed = dict(copy.deepcopy(feed), battery_rows_hash=blocked_battery["rows_hash"])
        with self.assertRaisesRegex(af.AnnouncementFeedError, "claims OK"):
            af.validate_feed(claimed, manifest, blocked_battery)


class FunnelStageTests(unittest.TestCase):
    """run_battery → stage_battery lists the sidecar; finalize/bundle_hash do not."""

    def _run(self, root, outcomes_for):
        harness = dag_fixture.FinalizeEndToEndTests()
        pv, obs = harness._run_stages(root, "candidates")
        with mock.patch.dict(os.environ, harness._env(root, obs)), \
                mock.patch.object(dag, "REPO_ROOT", root), \
                mock.patch.object(dag, "_battery_provider", return_value=(dag_fixture.complete_row, "")), \
                mock.patch.object(dag, "collect_rows", outcomes_for, create=True):
            self.assertEqual(0, dag.run_battery())
            self.assertEqual(0, dag.run_finalize())
        return pv, obs / dag_fixture.TARGET / dag_fixture.RUN_ID

    def _outcomes(self, order, target, worker, **_kwargs):
        outcomes = []
        for index, code in enumerate(order):
            outcome = {"ts_code": code, "reason": None, "row": dag_fixture.complete_row(code)}
            if index % 2 == 0:
                outcome["announcement_capture"] = capture(code, [[
                    target[:4] + "-" + target[4:6] + "-" + target[6:], f"filing {code}"]])
            outcomes.append(outcome)
        return outcomes

    def test_sidecar_is_stage_hashed_and_outside_the_final_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, bundle = self._run(root, self._outcomes)
            stage = json.loads((bundle / "stage_battery.json").read_text("utf-8"))
            self.assertEqual({"candidate_battery.json", af.FEED_FILE}, set(stage["artifacts"]))
            raw = (bundle / af.FEED_FILE).read_bytes()
            self.assertEqual(stage["artifacts"][af.FEED_FILE], hashlib.sha256(raw).hexdigest())
            top = json.loads((bundle / "manifest.json").read_text("utf-8"))
            self.assertNotIn(af.FEED_FILE, top["artifacts"])
            self.assertEqual(set(dag._final_bundle_files()), set(top["artifacts"]))
            health = json.loads((pv / "funnel_health.json").read_text("utf-8"))
            self.assertNotIn("announcement", json.dumps(health["battery_coverage"]))
            feed = json.loads(raw)
            manifest = json.loads((bundle / "candidate_manifest.json").read_text("utf-8"))
            statuses = [entry["status"] for entry in feed["per_ticker"]]
            self.assertEqual(len(manifest["ts_codes"]), len(statuses))
            self.assertIn("DATA_BLOCKED", statuses)
            self.assertIn("OK", statuses)
            self.assertEqual(stage["generated_at"], feed["generated_at"])

    def test_nightly_verifier_checks_sidecar_and_skips_old_bundles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, bundle = self._run(root, self._outcomes)
            health = json.loads((pv / "funnel_health.json").read_text("utf-8"))
            durable = root / "data_history/funnel" / dag_fixture.TARGET / dag_fixture.RUN_ID
            durable.parent.mkdir(parents=True)
            shutil.copytree(bundle, durable)
            nightly._verify_funnel_bundle(health, str(root), str(pv / "funnel_health.json"))
            feed_path = durable / af.FEED_FILE
            original = feed_path.read_bytes()
            feed = json.loads(original)
            feed["rows"][0]["title"] = "tampered after the stage wrote it"
            feed["rows"][0]["item_id"] = af.item_id(feed["rows"][0]["ts_code"],
                                                    feed["rows"][0]["source_channel"],
                                                    feed["rows"][0]["notice_date"],
                                                    feed["rows"][0]["title"])
            feed["rows_hash"] = af._hash(feed["rows"])
            feed_path.write_text(json.dumps(feed, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "announcement_feed"):
                nightly._verify_funnel_bundle(health, str(root), str(pv / "funnel_health.json"))
            feed_path.unlink()
            with self.assertRaisesRegex(ValueError, "announcement_feed"):
                nightly._verify_funnel_bundle(health, str(root), str(pv / "funnel_health.json"))
            # A pre-sidecar bundle: the stage never listed a feed and none exists.
            stage_path = durable / "stage_battery.json"
            stage = json.loads(stage_path.read_text("utf-8"))
            stage["artifacts"].pop(af.FEED_FILE)
            stage_path.write_text(json.dumps(stage), encoding="utf-8")
            nightly._verify_funnel_bundle(health, str(root), str(pv / "funnel_health.json"))
            # An unlisted sidecar next to an old stage manifest is refused.
            feed_path.write_bytes(original)
            with self.assertRaisesRegex(ValueError, "announcement_feed"):
                nightly._verify_funnel_bundle(health, str(root), str(pv / "funnel_health.json"))

    def test_sidecar_listing_must_agree_with_the_stage_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            _pv, bundle = self._run(Path(tmp), self._outcomes)
            payloads = {name: json.loads((bundle / name).read_text("utf-8"))
                        for name in ("candidate_manifest.json", "candidate_battery.json")}
            self.assertIsNotNone(af.verify_bundle_sidecar(bundle, payloads))
            original = (bundle / af.FEED_FILE).read_bytes()
            (bundle / af.FEED_FILE).unlink()
            try:
                with self.assertRaisesRegex(af.AnnouncementFeedError, "disagree"):
                    af.verify_bundle_sidecar(bundle, payloads)
            except OSError as exc:
                self.fail(f"a listed-but-missing sidecar must be refused by name: {exc!r}")
            stage_path = bundle / "stage_battery.json"
            stage = json.loads(stage_path.read_text("utf-8"))
            stage["artifacts"].pop(af.FEED_FILE)
            stage_path.write_text(json.dumps(stage), encoding="utf-8")
            self.assertIsNone(af.verify_bundle_sidecar(bundle, payloads), "old bundles skip")
            (bundle / af.FEED_FILE).write_bytes(original)
            with self.assertRaisesRegex(af.AnnouncementFeedError, "disagree"):
                af.verify_bundle_sidecar(bundle, payloads)

    def test_sidecar_generated_at_must_match_the_battery_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            _pv, bundle = self._run(Path(tmp), self._outcomes)
            payloads = {name: json.loads((bundle / name).read_text("utf-8"))
                        for name in ("candidate_manifest.json", "candidate_battery.json")}
            feed = json.loads((bundle / af.FEED_FILE).read_text("utf-8"))
            feed["generated_at"] = "2026-01-01T00:00:00+00:00"
            raw = json.dumps(feed, ensure_ascii=False).encode("utf-8")
            (bundle / af.FEED_FILE).write_bytes(raw)
            stage_path = bundle / "stage_battery.json"
            stage = json.loads(stage_path.read_text("utf-8"))
            stage["artifacts"][af.FEED_FILE] = hashlib.sha256(raw).hexdigest()
            stage.pop("stage_hash")
            stage["stage_hash"] = fp._hash(stage)
            stage_path.write_text(json.dumps(stage), encoding="utf-8")
            with self.assertRaisesRegex(af.AnnouncementFeedError, "not written by this battery stage"):
                af.verify_bundle_sidecar(bundle, payloads)

    def test_label_reader_rereads_both_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            _pv, bundle = self._run(Path(tmp), self._outcomes)
            feed, manifest, battery = af.load_bundle_feed(bundle)
            self.assertEqual(manifest["manifest_hash"], feed["manifest_hash"])
            self.assertEqual(battery["rows_hash"], feed["battery_rows_hash"])
            path = bundle / "candidate_manifest.json"
            edited = dict(json.loads(path.read_text("utf-8")), edited_locally=True)
            path.write_text(json.dumps(edited), encoding="utf-8")  # manifest_hash kept
            with self.assertRaisesRegex(af.AnnouncementFeedError, "stages are unreadable"):
                af.load_bundle_feed(bundle)
            elsewhere = Path(tmp) / "20990101" / bundle.name
            shutil.copytree(bundle, elsewhere)
            with self.assertRaisesRegex(af.AnnouncementFeedError, "stages are unreadable"):
                af.load_bundle_feed(elsewhere)

    def test_ready_path_ignores_the_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            with_feed = self._run(Path(tmp) / "a", self._outcomes)[1]
            without = self._run(Path(tmp) / "b", lambda order, target, worker, **_: [
                {"ts_code": c, "reason": None, "row": dag_fixture.complete_row(c)} for c in order])[1]
            for name in ("deep_research_queue.json", "candidate_battery.json"):
                first = json.loads((with_feed / name).read_text("utf-8"))
                second = json.loads((without / name).read_text("utf-8"))
                for payload in (first, second):
                    payload.pop("generated_at", None)
                self.assertEqual(first, second, name)


def add_feed_to_fixture_bundle(bundle: Path, *, tamper: bool = False, extra: str | None = None,
                               stage_name: str = "battery") -> None:
    manifest = json.loads((bundle / "candidate_manifest.json").read_text("utf-8"))
    battery = json.loads((bundle / "candidate_battery.json").read_text("utf-8"))
    stage_path = bundle / f"stage_{stage_name}.json"
    stage = json.loads(stage_path.read_text("utf-8"))
    code = manifest["ts_codes"][0]
    feed = af.build_feed(as_of=battery["as_of"], run_id=battery["run_id"],
                         generated_at=stage["generated_at"], manifest=manifest, battery=battery,
                         captures={code: capture(code, [["2026-08-11", "fixture filing"]])},
                         not_collected={})
    if tamper:
        feed["battery_rows_hash"] = "0" * 64
    name = extra or af.FEED_FILE
    raw = json.dumps(feed, ensure_ascii=False).encode("utf-8")
    (bundle / name).write_bytes(raw)
    stage["artifacts"][name] = hashlib.sha256(raw).hexdigest()
    stage.pop("stage_hash")
    stage["stage_hash"] = fp._hash(stage)
    stage_path.write_text(json.dumps(stage, ensure_ascii=False), encoding="utf-8")


class U4ReaderTests(unittest.TestCase):
    def _tree(self, tmp, **kwargs):
        root = Path(os.path.realpath(tmp))
        bundle, feature_health, funnel_health = u4_fixture._fixture_tree(root)
        add_feed_to_fixture_bundle(bundle, **kwargs)
        return root, bundle, feature_health, funnel_health

    def _packet(self, bundle, feature_health, funnel_health):
        return pre.build_packet(
            bundle_dir=bundle, feature_health_path=feature_health,
            funnel_health_path=funnel_health, diagnostic_ref="u4_pre_decision_diagnostic.json",
            industry="TECH", method_version=pre.DEFAULT_METHOD_VERSION,
            generated_at=u4_fixture.GENERATED_AT)

    def test_u4_accepts_a_bound_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            _root, bundle, feature_health, funnel_health = self._tree(tmp)
            packet, _diagnostic = self._packet(bundle, feature_health, funnel_health)
            self.assertTrue(packet["candidate_rows"])

    def test_u4_refuses_a_sidecar_bound_to_another_battery(self):
        with tempfile.TemporaryDirectory() as tmp:
            _root, bundle, feature_health, funnel_health = self._tree(tmp, tamper=True)
            with self.assertRaisesRegex(pre.PreDecisionError, "sidecar"):
                self._packet(bundle, feature_health, funnel_health)

    def test_u4_refuses_an_unknown_stage_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            _root, bundle, feature_health, funnel_health = self._tree(tmp, extra="surprise.json")
            with self.assertRaisesRegex(pre.PreDecisionError, "stage receipt contract"):
                self._packet(bundle, feature_health, funnel_health)

    def test_u4_accepts_the_feed_only_on_the_battery_stage(self):
        for stage_name in ("candidates", "finalize"):
            with tempfile.TemporaryDirectory() as tmp:
                _root, bundle, feature_health, funnel_health = self._tree(tmp, stage_name=stage_name)
                with self.assertRaisesRegex(pre.PreDecisionError, "stage receipt contract",
                                            msg=stage_name):
                    self._packet(bundle, feature_health, funnel_health)

    def test_evidence_view_captures_stage_only_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, bundle, _feature_health, _funnel_health = self._tree(tmp)
            (root / "u4-pre-decision.json").write_text("{}", encoding="utf-8")
            (root / "u4_pre_decision_diagnostic.json").write_text("{}", encoding="utf-8")
            bundle_ref = bundle.relative_to(root).as_posix()
            with DirectoryCapability.open(root) as capability:
                view = EvidenceView.capture_u4(
                    capability, packet_ref="u4-pre-decision.json",
                    diagnostic_ref="u4_pre_decision_diagnostic.json", bundle_ref=bundle_ref,
                    feature_health_ref="public/data/v2/feature_store_health.json",
                    funnel_health_ref="public/data/v2/funnel_health.json",
                    cyclical_flags_ref=None)
            try:
                _manifest, payloads = dag._read_stage_from_evidence(
                    view, bundle_ref, "battery", as_of=u4_fixture.AS_OF, run_id=u4_fixture.RUN_ID)
            except dag.FunnelError as exc:
                self.fail(f"the stage-only sidecar was not captured in the same pass: {exc}")
            self.assertIn(af.FEED_FILE, payloads)


if __name__ == "__main__":
    unittest.main()
