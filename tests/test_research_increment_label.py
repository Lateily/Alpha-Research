#!/usr/bin/env python3
"""Research-increment label ledger (contract L v1.0): propose / record / verify / report.

Pins the doctrine: two human axes only, provenance machine-filled, NONE needs
real content, no label on after-as-of items, one authorization per batch that
quotes the batch hash, blind pairs only, rates withheld below n=20, and no
posture/gate authority anywhere.

不是买卖指令；研究信号，human executes。
"""
from __future__ import annotations

import copy
import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))

import funnel_dag as dag  # noqa: E402
import funnel_pipeline as fp  # noqa: E402
import test_funnel_dag_offline as dag_fixture  # noqa: E402
from experiments.execution_tracker import event_ledger  # noqa: E402
from experiments.research_funnel import research_increment_label as ril  # noqa: E402

AS_OF = "20260923"
RUN_ID = "20260923_203000_1790000000000000000_label001"
GENERATED = "2026-09-23T12:31:00+00:00"
CAPTURED = "2026-09-23T12:30:00+00:00"
LABELED = "2026-09-24T09:00:00+08:00"
DECIDED = "2026-09-24T09:10:00+08:00"
THESIS = "000001.SZ"      # decision sheet dated before as_of
WATCH_ONLY = "000002.SZ"  # execution watchlist only → NO_LIVE_THESIS
BLOCKED = "000004.SZ"     # thesis ticker whose news source was blocked
OUTSIDE = "000009.SZ"     # no live thesis anywhere
NOT_CANDIDATE = "000007.SZ"  # live thesis but not a candidate tonight → no capture at all
E1_RULE = "loss guidance for the period"
FORBIDDEN_KEY = re.compile(r"return|hit|alpha|pnl|score|composite", re.IGNORECASE)


def _capture(code, items, *, status="OK", err=None):
    return {"ts_code": code, "source_channel": "EASTMONEY_ANN_A" if items is not None else None,
            "items": items, "status": status, "err": err, "captured_at": CAPTURED}


class Sandbox:
    """A minimal bundle with a stage-hashed feed plus a local scope tree."""

    def __init__(self, root: Path):
        self.root = root
        self.bundle = root / "data_history" / "funnel" / AS_OF / RUN_ID
        self.ledger = root / "labels" / "label_events.jsonl"
        self.sheets = root / "decision_sheets"
        self.watchlist = root / "watch_dynamic.json"
        self.u4 = root / "no_u4_ledger.jsonl"
        self.sheets.mkdir(parents=True)
        (self.sheets / "000001_SZ_2026-09-01.md").write_text("# sheet", encoding="utf-8")
        (self.sheets / "000004_SZ_DEEP_2026-09-02.md").write_text("# sheet", encoding="utf-8")
        (self.sheets / "000003_SZ_2026-09-30.md").write_text("# after as_of", encoding="utf-8")
        (self.sheets / "000007_SZ_2026-06-14.md").write_text("# old sheet", encoding="utf-8")
        self.watchlist.write_text(json.dumps({"watch": [{"ticker": WATCH_ONLY}]}), encoding="utf-8")
        codes = [THESIS, WATCH_ONLY, "000003.SZ", BLOCKED, OUTSIDE]
        manifest = {"ts_codes": codes, "manifest_hash": "m" * 64}
        rows = []
        for code in codes:
            row = dag_fixture.complete_row(code, AS_OF)
            if code == BLOCKED:
                row["dims"]["消息面"] = {"status": "DATA_BLOCKED", "err": "source down",
                                        "verdict_v0_unvalidated": None}
            if code == WATCH_ONLY:
                row["dims"]["消息面"]["verdict_v0_unvalidated"] = "SPIKE"
            rows.append(row)
        battery = {"as_of": AS_OF, "run_id": RUN_ID, "results": rows, "rows_hash": fp._hash(rows),
                   "generated_at": GENERATED}
        captures = {
            THESIS: _capture(THESIS, [["2026-09-24", "明日公告"], ["2026-09-23", "今日董事会决议公告"],
                                      ["2026-09-22", "昨日股东减持计划公告"], ["2026-09-20", "三日前公告"]]),
            WATCH_ONLY: _capture(WATCH_ONLY, [["2026-09-23", "关注名单公司公告"]]),
            "000003.SZ": _capture("000003.SZ", [["2026-09-23", "未来决策书公司公告"]]),
            # A blocked source that still returned one in-window row (e.g. an unverified page).
            BLOCKED: _capture(BLOCKED, [["2026-09-23", "阻断票部分公告"]],
                              status="DATA_BLOCKED", err="source down"),
            OUTSIDE: _capture(OUTSIDE, [["2026-09-23", "无命题公司公告"]]),
        }
        feed = ril.feed_contract.build_feed(
            as_of=AS_OF, run_id=RUN_ID, generated_at=GENERATED, manifest=manifest,
            battery=battery, captures=captures, not_collected={})
        dag._write_stage(self.bundle, "candidates", {"candidate_manifest.json": manifest},
                         as_of=AS_OF, run_id=RUN_ID, generated_at=GENERATED,
                         binds={"candidate_manifest_hash": manifest["manifest_hash"]})
        dag._write_stage(self.bundle, "battery",
                         {"candidate_battery.json": battery, ril.feed_contract.FEED_FILE: feed},
                         as_of=AS_OF, run_id=RUN_ID, generated_at=GENERATED,
                         binds={"candidate_manifest_hash": manifest["manifest_hash"],
                                "battery_rows_hash": battery["rows_hash"]})
        self.feed = feed
        self.e1_layer = None

    def write_e1_layer(self, evidence, *, as_of=AS_OF):
        rows = [{"ts_code": THESIS, "evidence": evidence}]
        path = self.root / "e1_event_layer.json"
        path.write_text(json.dumps({"as_of": as_of, "rows": rows, "rows_hash": fp._hash(rows)}),
                        encoding="utf-8")
        return path

    def kwargs(self):
        return {"u4_ledger": self.u4, "decision_sheets": self.sheets, "watchlist": self.watchlist,
                "e1_layer": self.e1_layer}

    @staticmethod
    def sheet_ref(code):
        name = {THESIS: "000001_SZ_2026-09-01.md", BLOCKED: "000004_SZ_DEEP_2026-09-02.md"}[code]
        return {"kind": "DECISION_SHEET", "ref": f"docs/research/decision_sheets/{name}"}

    def e1_label(self, item_id, **overrides):
        entry = {"item_id": item_id, "target_kind": "E1_EVENT", "thesis_ref": self.sheet_ref(THESIS),
                 "thesis_relevance": "THESIS_RELEVANT", "research_increment": "NONE",
                 "increment_ref": None, "note": "业绩预告已在命题预期内", "labeled_at": LABELED,
                 "future_seen": False, "saw_other_label": False}
        entry.update(overrides)
        return entry

    def item(self, title):
        return next(row for row in self.feed["rows"] if row["title"] == title)

    def propose(self, **extra):
        return ril.propose(self.bundle, ledger=self.ledger, **self.kwargs(), **extra)

    def label(self, title, **overrides):
        row = self.item(title)
        live = row["ts_code"] in (THESIS, BLOCKED)
        thesis = self.sheet_ref(row["ts_code"]) if live else {"kind": "NONE", "ref": None}
        entry = {"item_id": row["item_id"], "target_kind": "ANNOUNCEMENT", "thesis_ref": thesis,
                 "thesis_relevance": "THESIS_RELEVANT" if live else "NO_LIVE_THESIS",
                 "research_increment": "NONE", "increment_ref": None,
                 "note": "只是例行程序公告，未改变判断", "labeled_at": LABELED,
                 "future_seen": False, "saw_other_label": False}
        entry.update(overrides)
        return entry

    def batch(self, labels, *, reviewer="Junyan", authorization=None, decided_at=DECIDED):
        raw = {"schema": ril.INPUT_SCHEMA, "schema_version": ril.SCHEMA_VERSION,
               "as_of": AS_OF, "run_id": RUN_ID,
               "human_decision": {"claimed_reviewer": reviewer, "identity_verification": "UNAVAILABLE",
                                  "decided_at": decided_at, "authorization_text": "",
                                  "authorization_evidence_ref": "conversation:2026-09-24-labels"},
               "labels": labels}
        if authorization is None:
            dry = ril.record(self.bundle, raw, ledger=self.ledger, dry_run=True, **self.kwargs())
            authorization = f"批准离线登记本批公告标签 batch {dry['batch_hash'][:12]}，仅作研究语料"
        raw["human_decision"]["authorization_text"] = authorization
        return raw

    def record(self, raw):
        return ril.record(self.bundle, raw, ledger=self.ledger, **self.kwargs())


def _payload_for(sandbox, title, **overrides):
    """A fully valid label payload (as record would write it) for direct validator tests."""
    raw = sandbox.batch([sandbox.label(title, **overrides)])
    prepared = ril.prepare_batch(sandbox.bundle, raw, **sandbox.kwargs())
    payload = dict(prepared["labels"][0], batch_id="rilb_" + prepared["batch_hash"][:32],
                   human_decision=dict(raw["human_decision"]))
    payload["record_hash"] = ril._record_hash(payload)
    return payload


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


class LabelTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.sandbox = Sandbox(Path(os.path.realpath(self._tmp.name)))


class ProposeTests(LabelTestCase):
    def test_propose_is_blind_scoped_windowed_and_flags_same_day(self):
        proposal = self.sandbox.propose()
        titles = {item["snapshot"]["title"]: item for item in proposal["items"]}
        self.assertEqual({"今日董事会决议公告", "昨日股东减持计划公告", "关注名单公司公告", "阻断票部分公告"},
                         set(titles))
        self.assertTrue(titles["今日董事会决议公告"]["snapshot"]["same_day_as_as_of"])
        self.assertFalse(titles["昨日股东减持计划公告"]["snapshot"]["same_day_as_as_of"])
        self.assertEqual("E1", titles["今日董事会决议公告"]["provenance_tier"])
        self.assertEqual([{"kind": "NONE", "ref": None}], titles["关注名单公司公告"]["thesis_ref_options"])
        self.assertEqual({self.sandbox.sheet_ref(THESIS)["ref"]: 22},
                         titles["今日董事会决议公告"]["thesis_ref_age_days"], "a sheet's age is visible")
        self.assertEqual(0, titles["今日董事会决议公告"]["capture_lag_days"])
        counts = proposal["excluded_counts"]
        self.assertEqual(1, counts["after_as_of"])
        self.assertEqual(1, counts["outside_window"])
        self.assertEqual(2, counts["out_of_scope"], "no-thesis ticker and a sheet dated after as_of")
        self.assertEqual([BLOCKED], proposal["scope_tickers_news_blocked"])
        self.assertTrue(proposal["blind"])
        for label in proposal["input_template"]["labels"]:
            for axis in ("thesis_relevance", "research_increment", "note", "future_seen",
                         "saw_other_label", "labeled_at"):
                self.assertIsNone(label[axis], "the template never pre-fills a human axis")

    def test_window_is_two_calendar_days_ending_at_as_of(self):
        proposal = self.sandbox.propose()
        self.assertEqual({"start": "2026-09-22", "end": "2026-09-23", "calendar_days": 2},
                         proposal["window"])
        self.assertNotIn("三日前公告", {i["snapshot"]["title"] for i in proposal["items"]})
        with self.assertRaises(ril.LabelError):
            self.sandbox.propose(window_days=3)

    def test_cap_moves_the_rest_to_not_reviewed(self):
        proposal = self.sandbox.propose(cap=1)
        self.assertEqual(1, len(proposal["items"]))
        self.assertEqual(3, len(proposal["not_reviewed_over_cap"]))
        with self.assertRaises(ril.LabelError):
            self.sandbox.propose(cap=21)

    def test_already_labelled_items_are_not_proposed_again(self):
        self.sandbox.record(self.sandbox.batch([self.sandbox.label("今日董事会决议公告")]))
        proposal = self.sandbox.propose()
        self.assertNotIn("今日董事会决议公告", {i["snapshot"]["title"] for i in proposal["items"]})
        self.assertEqual(1, proposal["excluded_counts"]["already_labelled"])

    def test_u4_scope_is_replayed_as_of_not_from_today(self):
        """rev1 SELECT before as_of stays live even when rev2 REJECT lands later; a SELECT
        whose closure was committed after as_of is not yet live."""
        def decision(code, letter, verdict, ts):
            return {"kind": "u4_decision", "ts": ts, "payload": {
                "decision": verdict, "candidate": {"ts_code": code},
                "decision_id": "u4d_" + letter * 32, "registered_at": ts + "+08:00"}}

        def closure(ts):
            return {"kind": "u4_decision_closure", "ts": ts, "payload": {}}

        records = [
            decision(THESIS, "a", "SELECT", "2026-09-09T15:19:09.394439"),
            closure("2026-09-09T15:20:00"),
            decision(OUTSIDE, "b", "SELECT", "2026-09-23T10:00:00"),   # decided before as_of …
            closure("2026-09-24T01:00:00"),                              # … committed after it
            decision(THESIS, "c", "REJECT", "2026-09-24T02:00:00"),     # later revision
            closure("2026-09-24T02:05:00"),
        ]

        def committed_replay(prefix):
            staged, current = {}, {}
            for outer in prefix:
                if outer["kind"] == "u4_decision":
                    staged[outer["payload"]["candidate"]["ts_code"]] = outer["payload"]
                elif outer["kind"] == "u4_decision_closure":
                    current.update(staged)
            return {"current": current}

        self.sandbox.u4.write_text("", encoding="utf-8")
        from experiments.research_funnel import u4_decision_ledger
        with mock.patch.object(u4_decision_ledger, "_snapshot_state", return_value={}), \
                mock.patch.object(u4_decision_ledger, "_read_outer_records", return_value=records), \
                mock.patch.object(u4_decision_ledger, "_replay_records", side_effect=committed_replay):
            scope = ril.live_scope(AS_OF, **{k: v for k, v in self.sandbox.kwargs().items()
                                             if k != "e1_layer"})
        self.assertIn({"kind": "U4_RESEARCH_QUESTION", "ref": "u4d_" + "a" * 32},
                      scope["tickers"][THESIS]["thesis_refs"],
                      "a revision registered after as_of cannot retire a thesis live at as_of")
        self.assertEqual("2026-09-09", scope["tickers"][THESIS]["thesis_ref_dates"]["u4d_" + "a" * 32])
        self.assertNotIn(OUTSIDE, scope["tickers"], "a closure after as_of is not yet a live thesis")

    def test_broken_u4_ledger_is_never_read_as_no_thesis(self):
        self.sandbox.u4.write_text("{not json\n", encoding="utf-8")
        with self.assertRaisesRegex(ril.LabelError, "U4 decision ledger"):
            self.sandbox.propose()

    def test_e1_layer_from_another_as_of_is_refused(self):
        rows = [{"ts_code": THESIS, "evidence": [{
            "kind": "ISSUER_GUIDANCE", "source": "tushare.forecast_vip", "evidence_grade": "E1",
            "ann_date": "20260922", "period": "20260930", "triggered": True, "rule": "loss guidance"}]}]
        layer_path = self.sandbox.root / "e1.json"
        layer_path.write_text(json.dumps({"as_of": "20260922", "rows": rows,
                                          "rows_hash": fp._hash(rows)}), encoding="utf-8")
        status, layer = ril.load_e1_layer(layer_path, AS_OF)
        self.assertEqual("E1_OTHER_AS_OF_REFUSED", status)
        self.assertIsNone(layer)
        layer_path.write_text(json.dumps({"as_of": AS_OF, "rows": rows,
                                          "rows_hash": fp._hash(rows)}), encoding="utf-8")
        self.sandbox.e1_layer = layer_path
        proposal = self.sandbox.propose()
        self.assertEqual("SAME_AS_OF", proposal["e1_basis"])
        self.assertIn("E1_EVENT", {item["target_kind"] for item in proposal["items"]})
        e1_view = next(item for item in proposal["items"] if item["target_kind"] == "E1_EVENT")
        self.assertIsNone(e1_view["source"]["run_id"], "the E1 layer has no run binding")

    def test_proposal_hides_the_machine_display_verdict(self):
        proposal = self.sandbox.propose()
        text = json.dumps(proposal, ensure_ascii=False)
        for machine in ("SPIKE", "NORMAL"):
            self.assertNotIn(machine, text, "the labeler is blind to the signal the report scores")
        for item in proposal["items"]:
            self.assertNotIn("news_display_verdict", item["snapshot"])
            self.assertNotIn("news_status", item["snapshot"])
        self.assertIn("news_display_verdict", proposal["blind_to"])
        # The stored snapshot still carries it, machine-filled at record time.
        self.sandbox.record(self.sandbox.batch([self.sandbox.label("关注名单公司公告")]))
        events = [json.loads(line) for line in self.sandbox.ledger.read_text("utf-8").splitlines()]
        self.assertEqual("SPIKE", events[1]["payload"]["snapshot"]["news_display_verdict"])

    def test_scope_tickers_outside_the_feed_are_disclosed(self):
        proposal = self.sandbox.propose()
        coverage = {entry["ts_code"]: entry["announcement_coverage"]
                    for entry in proposal["scope"]["tickers"]}
        self.assertEqual("NOT_CAPTURED_NOT_A_CANDIDATE", coverage[NOT_CANDIDATE])
        self.assertEqual("DATA_BLOCKED", coverage[BLOCKED])
        self.assertEqual("CAPTURED_OK", coverage[THESIS])
        self.assertEqual([NOT_CANDIDATE], proposal["scope_tickers_not_in_feed"])

    def test_corrupt_watchlist_is_blocked_not_empty(self):
        for raw in ("[1, 2]", '{"watch": "x"}', "{not json"):
            self.sandbox.watchlist.write_text(raw, encoding="utf-8")
            proposal = self.sandbox.propose()
            self.assertEqual("DATA_BLOCKED", proposal["scope"]["source_status"]["EXECUTION_WATCHLIST"], raw)
            self.assertNotIn(WATCH_ONLY, [e["ts_code"] for e in proposal["scope"]["tickers"]])
        many = [{"ticker": f"{600000 + i:06d}.SH"} for i in range(40)]
        self.sandbox.watchlist.write_text(json.dumps({"watch": many}), encoding="utf-8")
        scope = self.sandbox.propose()["scope"]["tickers"]
        self.assertEqual(40, sum("EXECUTION_WATCHLIST" in e["sources"] for e in scope), "no silent cap")

    def test_e1_only_triggered_evidence_and_never_after_as_of(self):
        self.sandbox.e1_layer = self.sandbox.write_e1_layer([
            {"kind": "ISSUER_GUIDANCE", "source": "tushare.forecast_vip", "evidence_grade": "E1",
             "ann_date": "20260922", "period": "20260930", "triggered": True, "rule": E1_RULE},
            {"kind": "ISSUER_EXPRESS", "source": "tushare.express_vip", "evidence_grade": "E1",
             "ann_date": "20260922", "period": "20260930", "triggered": False, "rule": "not triggered"},
            {"kind": "ISSUER_INCOME", "source": "tushare.income_vip", "evidence_grade": "E1",
             "ann_date": "20260924", "period": "20260930", "triggered": True, "rule": "after as_of"}])
        proposal = self.sandbox.propose()
        kinds = [item["snapshot"]["kind"] for item in proposal["items"] if item["target_kind"] == "E1_EVENT"]
        self.assertEqual(["ISSUER_GUIDANCE"], kinds, "untriggered and after-as_of E1 are never proposed")
        future = ril.e1_item_id(THESIS, "ISSUER_INCOME", "tushare.income_vip", "20260924", "20260930")
        with self.assertRaisesRegex(ril.LabelError, "after as_of"):
            self.sandbox.record(self.sandbox.batch(
                [self.sandbox.e1_label(future, research_increment="DATA_BLOCKED")], authorization="x" * 30))

    def test_after_as_of_e1_payload_is_refused_even_as_blocked(self):
        self.sandbox.e1_layer = self.sandbox.write_e1_layer([
            {"kind": "ISSUER_GUIDANCE", "source": "tushare.forecast_vip", "evidence_grade": "E1",
             "ann_date": "20260922", "period": "20260930", "triggered": True, "rule": E1_RULE}])
        present = ril.e1_item_id(THESIS, "ISSUER_GUIDANCE", "tushare.forecast_vip", "20260922", "20260930")
        raw = self.sandbox.batch([self.sandbox.e1_label(present)])
        prepared = ril.prepare_batch(self.sandbox.bundle, raw, **self.sandbox.kwargs())
        payload = dict(prepared["labels"][0], batch_id="rilb_" + prepared["batch_hash"][:32],
                       human_decision=dict(raw["human_decision"]))
        payload["record_hash"] = ril._record_hash(payload)
        ril._validate_label_payload(payload)
        forged = copy.deepcopy(payload)
        forged["snapshot"]["ann_date"] = "20260924"
        forged.update(item_id=ril.e1_item_id(THESIS, "ISSUER_GUIDANCE", "tushare.forecast_vip",
                                             "20260924", "20260930"),
                      research_increment="DATA_BLOCKED", provenance_tier="DATA_BLOCKED")
        forged["record_hash"] = ril._record_hash(forged)
        with self.assertRaisesRegex(ril.LabelError, "after as_of"):
            ril._validate_label_payload(forged)
        bound = copy.deepcopy(payload)
        bound["source"]["run_id"] = RUN_ID
        bound["record_hash"] = ril._record_hash(bound)
        with self.assertRaisesRegex(ril.LabelError, "run_id must be null"):
            ril._validate_label_payload(bound)


class RecordTests(LabelTestCase):
    def test_valid_batch_replays_and_reports(self):
        sandbox = self.sandbox
        out = sandbox.record(sandbox.batch([
            sandbox.label("今日董事会决议公告"),
            sandbox.label("昨日股东减持计划公告", research_increment="CHANGES_POSTURE",
                          increment_ref="decision_sheet_revision:000001_SZ_2026-09-24"),
            sandbox.label("关注名单公司公告")]))
        self.assertEqual(3, out["labels"])
        verified = ril.verify(sandbox.ledger, bundle_root=sandbox.root / "data_history" / "funnel")
        self.assertTrue(verified["ok"], verified)
        self.assertEqual("VERIFIED_AGAINST_SOURCE", verified["sources"][0]["source_status"])
        report = ril.report(sandbox.ledger)
        self.assertEqual(3, report["labels_closed"])
        share = report["relevant_but_no_increment_share"]
        self.assertEqual((1, 2), (share["numerator"], share["denominator"]))
        self.assertIsNone(share["rate"], "n below 20 is withheld, never 0")
        self.assertEqual("RATE_WITHHELD_N_BELOW_MIN", share["level"])
        self.assertEqual(1, report["no_live_thesis_share"]["numerator"])
        rows = report["news_display_vs_increment_crosstab"]["rows"]
        self.assertEqual({"ANY_INCREMENT": 1, "NO_INCREMENT": 0, "ONLY_DATA_BLOCKED": 0}, rows["NORMAL"])
        self.assertEqual({"ANY_INCREMENT": 0, "NO_INCREMENT": 1, "ONLY_DATA_BLOCKED": 0}, rows["SPIKE"])
        self.assertFalse(report["authority"]["claim_allowed"])
        self.assertEqual("DESCRIPTIVE_ONLY", report["claim_status"])
        forbidden = [key for key in _walk_keys(report) if FORBIDDEN_KEY.search(key)]
        self.assertEqual([], forbidden)
        events = [json.loads(line) for line in sandbox.ledger.read_text("utf-8").splitlines()]
        self.assertEqual([ril.INTENT_KIND] + [ril.LABEL_KIND] * 3 + [ril.CLOSURE_KIND],
                         [event["kind"] for event in events])
        label = events[1]["payload"]
        self.assertEqual(ril.LABEL_KEYS, set(label))
        self.assertEqual({"posture_authority": False, "gate_authority": False}, label["authority"])
        self.assertEqual("UNAVAILABLE_NO_EXCHANGE_CALENDAR", label["exposure"]["bars_basis"])
        self.assertEqual("E1", label["provenance_tier"])

    def test_null_human_axes_are_refused(self):
        payload = _payload_for(self.sandbox, "今日董事会决议公告")
        for axis in ("thesis_relevance", "research_increment"):
            with self.assertRaisesRegex(ril.LabelError, "both human axes"):
                ril.validate_label_semantics(dict(payload, **{axis: None}), AS_OF)
        raw = self.sandbox.batch([self.sandbox.label("今日董事会决议公告")])
        raw["labels"][0]["future_seen"] = None
        with self.assertRaisesRegex(ril.LabelError, "declared explicitly"):
            self.sandbox.record(raw)

    def test_none_requires_readable_content_per_target_kind(self):
        payload = _payload_for(self.sandbox, "今日董事会决议公告")
        undated = copy.deepcopy(payload)
        undated["snapshot"]["eligibility"] = "DATE_UNVERIFIABLE"
        with self.assertRaisesRegex(ril.LabelError, "only be DATA_BLOCKED"):
            ril.validate_label_semantics(undated, AS_OF)
        untitled = copy.deepcopy(payload)
        untitled["snapshot"]["title"] = "  "
        with self.assertRaisesRegex(ril.LabelError, "only be DATA_BLOCKED"):
            ril.validate_label_semantics(untitled, AS_OF)
        e1 = dict(payload, target_kind="E1_EVENT", snapshot={
            "kind": "ISSUER_GUIDANCE", "source": "tushare.forecast_vip", "evidence_grade": "E1",
            "ann_date": "20260924", "period": "20260930", "triggered": True, "rule": "r"})
        with self.assertRaisesRegex(ril.LabelError, "only be DATA_BLOCKED"):
            ril.validate_label_semantics(e1, AS_OF)
        e1["snapshot"]["ann_date"] = "20260922"
        ril.validate_label_semantics(e1, AS_OF)
        ril.validate_label_semantics(dict(undated, research_increment="DATA_BLOCKED"), AS_OF)

    def test_no_live_thesis_if_and_only_if_thesis_ref_none(self):
        payload = _payload_for(self.sandbox, "今日董事会决议公告")
        with self.assertRaisesRegex(ril.LabelError, "NO_LIVE_THESIS if and only if"):
            ril.validate_label_semantics(dict(payload, thesis_relevance="NO_LIVE_THESIS"), AS_OF)
        with self.assertRaisesRegex(ril.LabelError, "NO_LIVE_THESIS if and only if"):
            ril.validate_label_semantics(
                dict(payload, thesis_ref={"kind": "NONE", "ref": None}), AS_OF)

    def test_increment_requires_relevance_and_a_human_record(self):
        payload = _payload_for(self.sandbox, "今日董事会决议公告")
        with self.assertRaisesRegex(ril.LabelError, "requires a thesis-relevant"):
            ril.validate_label_semantics(dict(payload, thesis_relevance="NOT_RELEVANT",
                                              research_increment="RESOLVES_WAIT",
                                              increment_ref="u4_missing_evidence:X"), AS_OF)
        with self.assertRaisesRegex(ril.LabelError, "point at the human record"):
            ril.validate_label_semantics(dict(payload, research_increment="CHANGES_POSTURE"), AS_OF)
        with self.assertRaisesRegex(ril.LabelError, "WRONG_IF_RELEVANT"):
            ril.validate_label_semantics(dict(payload, research_increment="TRIGGERS_WRONG_IF",
                                              increment_ref="wrong_if:x"), AS_OF)
        with self.assertRaisesRegex(ril.LabelError, "no increment_ref"):
            ril.validate_label_semantics(dict(payload, increment_ref="x"), AS_OF)

    def test_provenance_is_machine_filled(self):
        payload = _payload_for(self.sandbox, "今日董事会决议公告")
        ril._validate_label_payload(payload)
        forged = dict(payload, provenance_tier="DATA_BLOCKED")
        forged["record_hash"] = ril._record_hash(forged)
        with self.assertRaisesRegex(ril.LabelError, "machine-derived"):
            ril._validate_label_payload(forged)

    def test_after_as_of_item_cannot_be_labeled_even_as_blocked(self):
        payload = _payload_for(self.sandbox, "今日董事会决议公告")
        future = self.sandbox.item("明日公告")
        forged = copy.deepcopy(payload)
        forged.update(item_id=future["item_id"], research_increment="DATA_BLOCKED",
                      provenance_tier="DATA_BLOCKED")
        forged["snapshot"].update(notice_date=future["notice_date"], title=future["title"],
                                  eligibility="AFTER_AS_OF_EXCLUDED", same_day_as_as_of=False)
        forged["record_hash"] = ril._record_hash(forged)
        with self.assertRaisesRegex(ril.LabelError, "after as_of"):
            ril._validate_label_payload(forged)
        raw = self.sandbox.batch([self.sandbox.label("今日董事会决议公告")])
        raw["labels"][0].update(item_id=future["item_id"], research_increment="DATA_BLOCKED")
        with self.assertRaisesRegex(ril.LabelError, "after as_of"):
            self.sandbox.record(raw)

    def test_label_cannot_predate_capture_or_postdate_decision(self):
        payload = _payload_for(self.sandbox, "今日董事会决议公告")
        early = copy.deepcopy(payload)
        early["exposure"]["labeled_at"] = "2026-09-23T20:00:00+08:00"  # 12:00Z < captured 12:30Z
        early["record_hash"] = ril._record_hash(early)
        with self.assertRaisesRegex(ril.LabelError, "predate the capture"):
            ril._validate_label_payload(early)
        late = copy.deepcopy(payload)
        late["exposure"]["labeled_at"] = "2026-09-25T09:00:00+08:00"
        late["record_hash"] = ril._record_hash(late)
        with self.assertRaisesRegex(ril.LabelError, "postdate the batch decision"):
            ril._validate_label_payload(late)
        naive = copy.deepcopy(payload)
        naive["exposure"]["labeled_at"] = "2026-09-24T09:00:00"
        naive["record_hash"] = ril._record_hash(naive)
        with self.assertRaisesRegex(ril.LabelError, "timezone-aware"):
            ril._validate_label_payload(naive)

    def test_authorization_must_quote_the_batch_and_be_offline(self):
        labels = [self.sandbox.label("今日董事会决议公告")]
        with self.assertRaisesRegex(ril.LabelError, "batch-bound"):
            self.sandbox.record(self.sandbox.batch(labels, authorization="批准离线登记这一批公告标签，没有引用批次哈希"))
        dry = ril.record(self.sandbox.bundle, self.sandbox.batch(labels, authorization="x" * 20),
                         ledger=self.sandbox.ledger, dry_run=True, **self.sandbox.kwargs())
        with self.assertRaisesRegex(ril.LabelError, "batch-bound"):
            self.sandbox.record(self.sandbox.batch(
                labels, authorization=f"approve batch {dry['batch_hash'][:12]} for the record"))
        self.assertFalse(self.sandbox.ledger.exists(), "a refused batch writes nothing")

    def test_reviewer_is_a_claimed_name_from_the_closed_list(self):
        labels = [self.sandbox.label("今日董事会决议公告")]
        with self.assertRaisesRegex(ril.LabelError, "reviewer identity"):
            self.sandbox.record(self.sandbox.batch(labels, reviewer="Reed", authorization="x" * 30))
        raw = self.sandbox.batch(labels)
        raw["human_decision"]["identity_verification"] = "VERIFIED"
        with self.assertRaisesRegex(ril.LabelError, "reviewer identity"):
            self.sandbox.record(raw)
        with self.assertRaisesRegex(ril.LabelError, "reviewer identity"):
            ril._validate_human_decision(dict(raw["human_decision"], claimed_reviewer="Reed",
                                              identity_verification="UNAVAILABLE"), "0" * 64)

    def test_thesis_ref_must_be_live_for_that_ticker(self):
        wrong = self.sandbox.label("关注名单公司公告", thesis_relevance="THESIS_RELEVANT",
                                   thesis_ref={"kind": "DECISION_SHEET", "ref": "docs/x.md"})
        with self.assertRaisesRegex(ril.LabelError, "not a live thesis"):
            self.sandbox.record(self.sandbox.batch([wrong], authorization="x" * 30))
        hidden = self.sandbox.label("今日董事会决议公告", thesis_relevance="NO_LIVE_THESIS",
                                    thesis_ref={"kind": "NONE", "ref": None})
        with self.assertRaisesRegex(ril.LabelError, "not a live thesis"):
            self.sandbox.record(self.sandbox.batch([hidden], authorization="x" * 30))
        outside = self.sandbox.label("无命题公司公告")
        with self.assertRaisesRegex(ril.LabelError, "no live thesis scope"):
            self.sandbox.record(self.sandbox.batch([outside], authorization="x" * 30))

    def test_note_is_human_words_not_a_machine_copy(self):
        copied = self.sandbox.label("今日董事会决议公告", note="今日董事会决议公告")
        with self.assertRaisesRegex(ril.LabelError, "machine string"):
            self.sandbox.record(self.sandbox.batch([copied], authorization="x" * 30))

    def test_decision_cannot_predate_the_feed(self):
        raw = self.sandbox.batch([self.sandbox.label(
            "今日董事会决议公告", labeled_at="2026-09-23T12:30:30+00:00")],
            decided_at="2026-09-23T12:30:45+00:00")
        with self.assertRaisesRegex(ril.LabelError, "predate the feed"):
            self.sandbox.record(raw)

    def test_same_reviewer_cannot_label_an_item_twice(self):
        sandbox = self.sandbox
        sandbox.record(sandbox.batch([sandbox.label("今日董事会决议公告")]))
        again = sandbox.batch([sandbox.label("今日董事会决议公告", note="第二次看，仍然只是程序性公告")])
        with self.assertRaisesRegex(ril.LabelError, "already labeled"):
            sandbox.record(again)
        # Forge past the writer's pre-check: the replay itself must refuse the duplicate.
        real_replay = ril.replay
        calls = []

        def first_call_empty(path):
            calls.append(path)
            if len(calls) == 1:
                return {"closed": [], "abandoned": [], "open": None}
            return real_replay(path)

        with mock.patch.object(ril, "replay", side_effect=first_call_empty):
            with self.assertRaises(ril.LabelError):
                sandbox.record(again)
        verified = ril.verify(sandbox.ledger)
        self.assertFalse(verified["ok"])
        self.assertIn("twice", verified["errors"][0])

    def test_closure_must_seal_the_authorized_labels(self):
        sandbox = self.sandbox
        authorized = sandbox.batch([sandbox.label("今日董事会决议公告")])
        prepared = ril.prepare_batch(sandbox.bundle, authorized, **sandbox.kwargs())
        swapped = sandbox.batch([sandbox.label("今日董事会决议公告",
                                               research_increment="DATA_BLOCKED")],
                                authorization=authorized["human_decision"]["authorization_text"])
        other = ril.prepare_batch(sandbox.bundle, swapped, **sandbox.kwargs())
        batch_hash = prepared["batch_hash"]
        batch_id = "rilb_" + batch_hash[:32]
        human = dict(authorized["human_decision"])

        def intent(ts):
            payload = {"schema": ril.INTENT_SCHEMA, "schema_version": ril.SCHEMA_VERSION,
                       "batch_id": batch_id, "batch_hash": batch_hash, "as_of": AS_OF,
                       "run_id": RUN_ID, "feed_rows_hash": prepared["feed_rows_hash"],
                       "e1_rows_hash": None, "item_ids": [prepared["labels"][0]["item_id"]],
                       "human_decision": human, "registered_at": ril._registered_at(ts),
                       "authority": dict(ril.AUTHORITY)}
            payload["record_hash"] = ril._record_hash(payload)
            return batch_id, payload

        label = dict(other["labels"][0], batch_id=batch_id, human_decision=human)
        label["record_hash"] = ril._record_hash(label)

        def closure(ts):
            payload = {"schema": ril.CLOSURE_SCHEMA, "schema_version": ril.SCHEMA_VERSION,
                       "batch_id": batch_id, "batch_hash": batch_hash,
                       "label_record_hashes": [label["record_hash"]],
                       "registered_at": ril._registered_at(ts)}
            payload["record_hash"] = ril._record_hash(payload)
            return "rilc_" + batch_hash[:32], payload

        path = str(sandbox.ledger)
        sandbox.ledger.parent.mkdir(parents=True)
        event_ledger.append_stamped(ril.INTENT_KIND, intent, path=path)
        event_ledger.append_stamped(ril.LABEL_KIND,
                                    lambda _ts: ("ril_" + label["record_hash"][7:39], label), path=path)
        event_ledger.append_stamped(ril.CLOSURE_KIND, closure, path=path)
        verified = ril.verify(sandbox.ledger)
        self.assertFalse(verified["ok"])
        self.assertIn("authorized batch", verified["errors"][0])

    def test_interrupted_batch_is_abandoned_and_excluded(self):
        sandbox = self.sandbox
        raw = sandbox.batch([sandbox.label("今日董事会决议公告")])
        real_append = event_ledger.append_stamped
        calls = []

        def crash_after_intent(kind, build, path):
            calls.append(kind)
            if kind == ril.LABEL_KIND:
                raise RuntimeError("simulated crash")
            return real_append(kind, build, path=path)

        with mock.patch.object(ril.event_ledger, "append_stamped", side_effect=crash_after_intent):
            with self.assertRaises(RuntimeError):
                sandbox.record(raw)
        self.assertEqual(0, ril.report(sandbox.ledger)["labels_closed"])
        sandbox.record(sandbox.batch([sandbox.label("今日董事会决议公告",
                                                    note="重新登记：程序性公告")]))
        verified = ril.verify(sandbox.ledger)
        self.assertTrue(verified["ok"], verified)
        self.assertEqual(1, len(verified["batches_abandoned"]))
        self.assertEqual(1, ril.report(sandbox.ledger)["labels_closed"])

    def test_abandoned_batch_items_are_proposed_again(self):
        sandbox = self.sandbox
        raw = sandbox.batch([sandbox.label("今日董事会决议公告"), sandbox.label("昨日股东减持计划公告")])
        real_append = event_ledger.append_stamped
        labels_written = []

        def crash_on_second_label(kind, build, path):
            if kind == ril.LABEL_KIND:
                labels_written.append(kind)
                if len(labels_written) == 2:
                    raise RuntimeError("simulated crash")
            return real_append(kind, build, path=path)

        with mock.patch.object(ril.event_ledger, "append_stamped", side_effect=crash_on_second_label):
            with self.assertRaises(RuntimeError):
                sandbox.record(raw)
        sandbox.record(sandbox.batch([sandbox.label("关注名单公司公告")]))  # abandons the crashed batch
        self.assertEqual(1, len(ril.verify(sandbox.ledger)["batches_abandoned"]))
        proposal = sandbox.propose()
        titles = {item["snapshot"]["title"] for item in proposal["items"]}
        self.assertIn("今日董事会决议公告", titles, "a label in an abandoned batch was never closed")
        self.assertIn("昨日股东减持计划公告", titles)
        self.assertNotIn("关注名单公司公告", titles)
        self.assertEqual(1, proposal["excluded_counts"]["already_labelled"])
        self.assertEqual(2, proposal["reproposed_from_unclosed_batch"])

    def test_verify_reports_per_kind_and_never_overclaims(self):
        sandbox = self.sandbox
        layer = sandbox.write_e1_layer([
            {"kind": "ISSUER_GUIDANCE", "source": "tushare.forecast_vip", "evidence_grade": "E1",
             "ann_date": "20260922", "period": "20260930", "triggered": True, "rule": E1_RULE},
            {"kind": "ISSUER_EXPRESS", "source": "tushare.express_vip", "evidence_grade": "E1",
             "ann_date": "20260923", "period": "20260930", "triggered": True, "rule": "express"}])
        sandbox.e1_layer = layer
        guidance = ril.e1_item_id(THESIS, "ISSUER_GUIDANCE", "tushare.forecast_vip", "20260922", "20260930")
        express = ril.e1_item_id(THESIS, "ISSUER_EXPRESS", "tushare.express_vip", "20260923", "20260930")
        sandbox.record(sandbox.batch([sandbox.label("今日董事会决议公告"), sandbox.e1_label(guidance)]))
        sandbox.record(sandbox.batch([sandbox.e1_label(express, note="快报数字与命题一致")]))
        root = sandbox.root / "data_history" / "funnel"
        mixed, e1_only = ril.verify(sandbox.ledger, bundle_root=root)["sources"]
        self.assertEqual(ril.VERIFIED, mixed["per_kind"]["ANNOUNCEMENT"]["source_status"])
        self.assertEqual(ril.SNAPSHOT_ONLY, mixed["per_kind"]["E1_EVENT"]["source_status"])
        self.assertEqual(ril.PARTIAL, mixed["source_status"], "an unchecked E1 label is not verified")
        self.assertEqual(ril.SNAPSHOT_ONLY, e1_only["source_status"])
        verified = ril.verify(sandbox.ledger, bundle_root=root, e1_layer=layer)
        self.assertTrue(verified["ok"], verified)
        self.assertEqual([ril.VERIFIED, ril.VERIFIED], [s["source_status"] for s in verified["sources"]])
        other = sandbox.write_e1_layer([])
        self.assertEqual(ril.SNAPSHOT_ONLY, ril.verify(sandbox.ledger, e1_layer=other)["sources"][1]
                         ["source_status"], "a layer with another rows_hash is not the source")


class ReportTests(LabelTestCase):
    def test_rates_below_min_n_are_withheld(self):
        self.assertIsNone(ril._rate(5, 19)["rate"])
        self.assertEqual("RATE_WITHHELD_N_BELOW_MIN", ril._rate(0, 0)["level"])
        self.assertEqual(0.5, ril._rate(10, 20)["rate"])

    def test_agreement_counts_only_blind_pairs(self):
        sandbox = self.sandbox
        with mock.patch.object(ril, "CLAIMED_REVIEWERS", ("Junyan", "Reed")):
            sandbox.record(sandbox.batch([sandbox.label("今日董事会决议公告")]))
            sandbox.record(sandbox.batch([sandbox.label("今日董事会决议公告", saw_other_label=True,
                                                        note="看过另一位的标签后复核")],
                                         reviewer="Reed"))
            report = ril.report(sandbox.ledger)
        agreement = report["inter_reviewer_agreement"]
        self.assertEqual(0, agreement["blind_pairs"])
        self.assertEqual(1, agreement["excluded_pairs_saw_other_label"])
        self.assertIsNone(agreement["per_axis"]["research_increment"]["rate"])

    def test_blocked_display_verdict_is_its_own_row(self):
        sandbox = self.sandbox
        sandbox.record(sandbox.batch([sandbox.label("阻断票部分公告")]))
        events = [json.loads(line) for line in sandbox.ledger.read_text("utf-8").splitlines()]
        self.assertIsNone(events[1]["payload"]["snapshot"]["news_display_verdict"])
        rows = ril.report(sandbox.ledger)["news_display_vs_increment_crosstab"]["rows"]
        self.assertEqual(1, rows["BLOCKED"]["NO_INCREMENT"], "a blocked verdict is its own row")
        self.assertEqual(0, sum(rows["NORMAL"].values()), "never folded into NORMAL")

    def test_report_evaluates_only_labels_made_without_the_future(self):
        sandbox = self.sandbox
        sandbox.record(sandbox.batch([
            sandbox.label("今日董事会决议公告"),
            sandbox.label("昨日股东减持计划公告", research_increment="CHANGES_POSTURE",
                          increment_ref="decision_sheet_revision:000001_SZ_2026-09-24",
                          future_seen=True, note="看过次日走势后判定为改变判断")]))
        report = ril.report(sandbox.ledger)
        self.assertEqual({"evaluable_labels": 1, "future_seen_excluded": 1},
                         {k: report["evaluation_basis"][k] for k in ("evaluable_labels", "future_seen_excluded")})
        share = report["relevant_but_no_increment_share"]
        self.assertEqual((1, 1), (share["numerator"], share["denominator"]))
        self.assertEqual({"ANY_INCREMENT": 0, "NO_INCREMENT": 1, "ONLY_DATA_BLOCKED": 0},
                         report["news_display_vs_increment_crosstab"]["rows"]["NORMAL"])
        self.assertEqual(1, report["counts"]["future_seen"], "hindsight labels are still counted")

    def test_cli_emits_disclaimer_and_refuses_cleanly(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = ril.main(["report", "--ledger", str(self.sandbox.ledger)])
        self.assertEqual(0, code)
        self.assertIn("不是买卖指令；研究信号，human executes。", stdout.getvalue())
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = ril.main(["propose", "--bundle", str(self.sandbox.root / "missing"),
                             "--ledger", str(self.sandbox.ledger)])
        self.assertEqual(1, code)
        self.assertIn("refused", stdout.getvalue())
        proposal = self.sandbox.propose()
        self.assertEqual([], [k for k in _walk_keys(proposal) if FORBIDDEN_KEY.search(k)])


if __name__ == "__main__":
    unittest.main()
