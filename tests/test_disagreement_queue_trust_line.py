#!/usr/bin/env python3
"""Nightly machine-vs-machine disagreement queue (Q v0.1) and research trust line (T v1.0).

Pins, one by one:
  · offline replay of the retained 9/29 production bundle + same-run E1 layer:
    46 U3 red flags, all E1-clear, 43 E1-confirmed SUPERSEDED + 3 OUT_OF_E1_WINDOW,
    T1 43/46, T2 0/46, T6 0/181, 46 U3 rows + 2 controls, 10 routed; 9/24: 39 U3 red flags
  · an E1 layer from another night/run is never used; its absence is UNAVAILABLE/null, never 0
  · rates below MIN_N are withheld (null), never 0; no performance/claim keys, no authority
  · the trust ledger is hash-chained, idempotent per run_id and never fails finalize
  · finalize writes both files through the finalize stage only (manifest artifact set
    unchanged), health gets new top-level keys, and the nightly verifier recomputes them
  · U4 pre-decision accepts exactly these optional finalize files and nothing else

不是买卖指令；研究信号，human executes。
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "experiments" / "execution_tracker"))
sys.path.insert(0, str(REPO_ROOT / "experiments" / "research_funnel"))

import disagreement_queue as dq  # noqa: E402
import event_ledger  # noqa: E402
import funnel_dag as dag  # noqa: E402
import funnel_pipeline as fp  # noqa: E402
import nightly_funnel  # noqa: E402
import research_trust as rt  # noqa: E402
import run_nightly as nightly  # noqa: E402
import test_funnel_dag_offline as dagtests  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "research_trust"
GENERATED_AT = "2026-09-29T14:27:06+00:00"


# ── compact production replay fixtures ────────────────────────────────────

def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def inputs_from_fixture(fx: dict) -> dict:
    """Rebuild the minimal bundle payload shapes the queue/trust code reads."""
    results = []
    for row in fx["battery_rows"]:
        news = {"status": row["news_status"]} if row["news_status"] else {"fixture": "payload elided"}
        results.append({
            "ts_code": row["ts_code"],
            "dims": {"基本面": dict(row["fundamental"]), "消息面": news},
            "completeness": {"verdict": row["completeness_verdict"]},
        })
    battery = {"results": results, "rows_hash": fp._hash(results)}
    scan = {
        "generated_at": fx["scan_generated_at"],
        "rows": [
            {"channel": "E1_EVENT", "ts_code": code,
             "feature_values": {"verdict": view["verdict"], "latest_e1_date": view["latest_e1_date"]},
             "reason_codes": view["reason_codes"]}
            for code, view in sorted(fx["scan_e1"].items())
        ],
    }
    review_rows = [{"ts_code": code, "review_status": "EXCLUDED_RED_FLAG"}
                   for code in fx["excluded_red_flag_codes"]]
    review_rows += [{"ts_code": row["ts_code"], "review_status": "MAIN_CHANNEL"} for row in results]
    e1_raw = None
    if "e1" in fx:
        rows = fx["e1"]["rows"]
        e1 = {"schema": "ar.e1_event_layer", "as_of": fx["e1"]["as_of"],
              "generated_at": fx["e1"]["generated_at"], "status": fx["e1"]["status"],
              "source": {"periods": fx["e1"]["periods"]}, "rows_hash": fp._hash(rows), "rows": rows}
        e1_raw = json.dumps(e1, ensure_ascii=False).encode("utf-8")
    return {
        "as_of": fx["as_of"], "run_id": fx["run_id"], "battery": battery, "scan": scan,
        "candidate_review": {"rows": review_rows},
        "candidate_manifest": {"manifest_hash": "fixture:" + fx["source"]["bundle_hash"]},
        "registry": {"rows": [{"ts_code": c, "name": n} for c, n in fx["names"].items()]},
        "deep_queue": {"ready_pool": [{"ts_code": r["ts_code"], "ready": False} for r in results]},
        "e1_raw": e1_raw,
    }


def replay(inputs: dict, *, e1_raw: bytes | None = None, run_manifest=None,
           macro=None, u4=None, adjudication=None, prior=()):
    raw = inputs["e1_raw"] if e1_raw is None else e1_raw
    codes = rt._e1_codes(inputs["battery"], inputs["candidate_review"], inputs["as_of"])
    basis, e1, reason = dq.resolve_e1_basis(raw, as_of=inputs["as_of"], scan=inputs["scan"],
                                            codes=codes, run_manifest=run_manifest)
    queue = dq.build_queue(
        as_of=inputs["as_of"], run_id=inputs["run_id"], generated_at=GENERATED_AT,
        candidate_manifest=inputs["candidate_manifest"], battery=inputs["battery"],
        candidate_review=inputs["candidate_review"], scan=inputs["scan"],
        registry_projected=inputs["registry"], e1=e1, e1_basis=basis,
    )
    line, members = rt.build_trust_line(
        as_of=inputs["as_of"], run_id=inputs["run_id"], generated_at=GENERATED_AT, queue=queue,
        battery=inputs["battery"], scan=inputs["scan"], deep_queue=inputs["deep_queue"],
        candidate_manifest=inputs["candidate_manifest"], e1=e1, e1_basis=basis,
        macro=macro or {"status": "ABSENT", "events": None, "manifest_sha256": None, "reason": "TEST"},
        u4=u4 or {"status": "ABSENT", "events": [], "head": None, "error": None},
        adjudication=adjudication or {"status": "ABSENT", "labels": {}, "head": None, "error": None},
        prior=prior,
    )
    return basis, reason, queue, line, members


def by_id(line: dict) -> dict:
    return {m["metric_id"]: m for m in line["metrics"]}


class ProductionReplayTests(unittest.TestCase):
    """The acceptance numbers come from the archived production bundles, not from design text."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fx29 = inputs_from_fixture(load_fixture("replay_20260929_150751"))
        cls.fx24 = inputs_from_fixture(load_fixture("replay_20260924_203004"))

    def test_20260929_queue_lists_every_u3_vs_e1_disagreement_and_two_controls(self) -> None:
        basis, reason, queue, _line, _members = replay(self.fx29)
        self.assertEqual((dq.E1_SAME_AS_OF, None), (basis, reason))
        self.assertEqual({
            "battery_dispatched_rows": 181, "u3_red_flag_rows": 46,
            "u3_red_flag_vs_e1_clear_rows": 46, "superseded_rows": 43,
            "out_of_e1_window_rows": 3, "active_rows": 0, "e1_coverage_empty_rows": 0,
            "undetermined_rows": 0, "control_rows": 2, "human_routed_rows": 10,
            "unobservable_cells": ["U3_PASS_VS_E1_RED_FLAG"],
        }, queue["counts"])
        self.assertEqual(48, len(queue["rows"]))
        self.assertEqual([dq.CLASS_CONTROL] * 2,
                         [row["disagreement_class"] for row in queue["rows"][:2]])
        oow = sorted(row["ts_code"] for row in queue["rows"]
                     if row["evidence_staleness"] == dq.OUT_OF_WINDOW)
        self.assertEqual(["301047.SZ", "688072.SH", "688261.SH"], oow)
        self.assertTrue(all(row["adjudication_status"] == "PENDING" for row in queue["rows"]))
        self.assertEqual(dq.AUTHORITY, queue["authority"])
        self.assertTrue(queue["disclaimer"].endswith("human executes。"))

    def test_20260929_trust_line_reads_the_stale_red_flags_the_same_night(self) -> None:
        _basis, _reason, _queue, line, _members = replay(self.fx29)
        metrics = by_id(line)
        t1 = metrics["red_flag_stale_evidence_share"]
        self.assertEqual((43, 46, round(43 / 46, 6), rt.MISSES, "ADVISORY_SHOW_STALE_SHARE"),
                         (t1["numerator"], t1["denominator"], t1["rate"], t1["level"], t1["reliance"]))
        t2 = metrics["red_flag_cross_model_confirmed_share"]
        self.assertEqual((0, 46, 0.0, rt.MISSES), (t2["numerator"], t2["denominator"], t2["rate"], t2["level"]))
        t6 = metrics["news_channel_available_share"]
        self.assertEqual((0, 181, rt.MISSES, "COVERAGE_GAP_DISCLOSE"),
                         (t6["numerator"], t6["denominator"], t6["level"], t6["reliance"]))
        self.assertEqual(rt.NC_LEDGER_FORCES_AGREEMENT,
                         metrics["red_flag_human_confirmed_share"]["not_computable_reason"])
        for metric_id in ("u4_ready_false_ready_share", "complete_label_defect_share"):
            self.assertEqual(rt.NC_NO_HUMAN_LABELS, metrics[metric_id]["not_computable_reason"])
            self.assertIsNone(metrics[metric_id]["rate"])
            self.assertIsNone(metrics[metric_id]["numerator"])
        self.assertEqual(rt.NC_NO_MACRO, metrics["macro_event_consensus_coverage"]["not_computable_reason"])
        self.assertEqual(("DESCRIPTIVE_ONLY", "LOCAL_ONLY_UNBACKED"),
                         (line["claim_status"], line["retention_status"]))
        self.assertEqual({"claim_allowed": False, "performance_claim": None,
                          "u4_selection_authority": False}, line["authority"])

    def test_20260929_macro_consensus_coverage_is_counted_when_the_same_run_manifest_exists(self) -> None:
        events = [{"context_id": f"src:{i}", "consensus": None, "consensus_status": "DATA_BLOCKED"}
                  for i in range(25)]
        _b, _r, _q, line, _m = replay(self.fx29, macro={"status": "OK", "events": events,
                                                         "manifest_sha256": "a" * 64, "reason": None})
        t7 = by_id(line)["macro_event_consensus_coverage"]
        self.assertEqual((0, 25, rt.MISSES), (t7["numerator"], t7["denominator"], t7["level"]))

    def test_20260924_counts_39_red_flags_and_refuses_the_later_e1_layer(self) -> None:
        # The only retained E1 layer is 9/29's: comparing it with 9/24 would be lookahead.
        basis, reason, queue, line, _members = replay(self.fx24, e1_raw=self.fx29["e1_raw"])
        self.assertEqual((dq.E1_UNAVAILABLE, "E1_AS_OF_MISMATCH"), (basis, reason))
        self.assertEqual(39, queue["counts"]["u3_red_flag_rows"])
        self.assertEqual(39, queue["counts"]["u3_red_flag_vs_e1_clear_rows"])
        self.assertEqual(39, queue["counts"]["undetermined_rows"])
        for key in ("superseded_rows", "out_of_e1_window_rows", "active_rows", "e1_coverage_empty_rows"):
            self.assertIsNone(queue["counts"][key], key)
        self.assertIsNone(queue["source_bindings"]["e1_layer_rows_hash"])
        for metric_id in ("red_flag_stale_evidence_share", "red_flag_cross_model_confirmed_share"):
            self.assertEqual(rt.NC_E1_UNAVAILABLE, by_id(line)[metric_id]["not_computable_reason"])
        self.assertEqual(164, by_id(line)["news_channel_available_share"]["denominator"])

    def test_queue_and_line_are_deterministic_and_content_hash_ignores_generated_at(self) -> None:
        _b, _r, q1, l1, _m = replay(self.fx29)
        _b, _r, q2, l2, _m = replay(self.fx29)
        self.assertEqual(q1["rows_hash"], q2["rows_hash"])
        self.assertEqual(json.dumps(q1, sort_keys=True), json.dumps(q2, sort_keys=True))
        moved = dict(l1, generated_at="2030-01-01T00:00:00+00:00")
        self.assertEqual(rt.content_hash(l1), rt.content_hash(moved))
        self.assertEqual(rt.content_hash(l1), rt.content_hash(l2))


class E1BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fx = inputs_from_fixture(load_fixture("replay_20260929_150751"))

    def resolve(self, raw, *, run_manifest=None, scan=None):
        codes = rt._e1_codes(self.fx["battery"], self.fx["candidate_review"], self.fx["as_of"])
        return dq.resolve_e1_basis(raw, as_of=self.fx["as_of"], scan=scan or self.fx["scan"],
                                   codes=codes, run_manifest=run_manifest)

    def _e1(self) -> dict:
        return json.loads(self.fx["e1_raw"].decode("utf-8"))

    def _raw(self, payload: dict) -> bytes:
        payload = copy.deepcopy(payload)
        payload["rows_hash"] = fp._hash(payload["rows"])
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def test_missing_layer_is_unavailable_not_an_error(self) -> None:
        self.assertEqual((dq.E1_UNAVAILABLE, None, "E1_LAYER_MISSING"), self.resolve(None))
        self.assertEqual("E1_LAYER_UNREADABLE", self.resolve(b"{not json")[2])

    def test_a_layer_from_another_night_is_refused(self) -> None:
        other = dict(self._e1(), as_of="20260930")
        basis, payload, reason = self.resolve(self._raw(other))
        self.assertEqual((dq.E1_UNAVAILABLE, None, "E1_AS_OF_MISMATCH"), (basis, payload, reason))

    def test_run_manifest_digest_binds_or_refuses(self) -> None:
        raw = self.fx["e1_raw"]
        digest = hashlib.sha256(raw).hexdigest()
        bound = {"run_id": self.fx["run_id"], "artifacts": {dq.E1_RUN_MANIFEST_KEY: digest}}
        self.assertEqual(dq.E1_SAME_RUN, self.resolve(raw, run_manifest=bound)[0])
        other = {"run_id": self.fx["run_id"], "artifacts": {dq.E1_RUN_MANIFEST_KEY: "0" * 64}}
        self.assertEqual((dq.E1_UNAVAILABLE, "E1_DIGEST_NOT_THIS_RUN"),
                         self.resolve(raw, run_manifest=other)[::2])

    def test_a_layer_generated_after_the_scan_cannot_be_same_night_evidence(self) -> None:
        later = dict(self._e1(), generated_at="2026-09-29T20:00:00+00:00")
        self.assertEqual("E1_NOT_BEFORE_SCAN", self.resolve(self._raw(later))[2])

    def test_verdicts_must_match_the_scan_projection(self) -> None:
        changed = self._e1()
        target = next(row for row in changed["rows"] if row["verdict"] == "NO_RED_FLAG_FOUND")
        target["verdict"] = "RED_FLAG"
        self.assertEqual("E1_PROJECTION_MISMATCH", self.resolve(self._raw(changed))[2])

    def test_partial_e1_is_a_valid_same_night_basis(self) -> None:
        self.assertEqual("PARTIAL", self._e1()["status"])
        self.assertEqual(dq.E1_SAME_AS_OF, self.resolve(self.fx["e1_raw"])[0])


class ReasonParsingTests(unittest.TestCase):
    def test_prefixes_and_closed_codes_both_parse(self) -> None:
        cases = {
            "最新预告[预减] 20260711 期末20260630 净利下限0.0亿": ("forecast", "20260630"),
            "最新快报净利同比-45% (20260128)": ("express", None),
            "最近季度归母-1.2亿为负且环比恶化(前季-0.3亿)": ("income", None),
            "FORECAST_NEGATIVE:期末20250630": ("forecast", "20250630"),
            "EXPRESS_YOY_BELOW_MINUS_30": ("express", None),
            "INCOME_QUARTER_NEGATIVE_WORSENING": ("income", None),
        }
        for reason, expected in cases.items():
            self.assertEqual(expected, dq.parse_reason(reason), reason)
        self.assertEqual(("forecast", "20241231"),
                         dq.parse_reason({"code": "FORECAST_NEGATIVE", "end_date": "20241231"}))
        self.assertEqual(("unparsed", None), dq.parse_reason("零证据可查"))
        self.assertEqual(("unparsed", None), dq.parse_reason(42))

    def test_reason_staleness_maps_the_e1_coverage_vocabulary(self) -> None:
        cov = {"forecast": "SUPERSEDED", "express": "PRESENT", "income": "COMPLETE"}
        self.assertEqual(dq.SUPERSEDED, dq.reason_staleness("forecast", "20260630", cov, "20250930")[1])
        self.assertEqual(dq.OUT_OF_WINDOW, dq.reason_staleness("forecast", "20250630", cov, "20250930")[1])
        self.assertEqual(dq.ACTIVE, dq.reason_staleness("express", None, cov, "20250930")[1])
        self.assertEqual(dq.ACTIVE, dq.reason_staleness("income", None, cov, "20250930")[1])
        self.assertEqual(dq.COVERAGE_EMPTY,
                         dq.reason_staleness("express", None, {"express": "EMPTY_VALID"}, None)[1])
        self.assertEqual(dq.UNDETERMINED,
                         dq.reason_staleness("income", None, {"income": "DATA_BLOCKED"}, None)[1])
        self.assertEqual((None, dq.UNDETERMINED), dq.reason_staleness("forecast", "20260630", None, None))

    def test_row_precedence_is_conservative(self) -> None:
        item = lambda s: {"staleness": s}
        self.assertEqual(dq.ACTIVE, dq.row_staleness([item(dq.SUPERSEDED), item(dq.ACTIVE)]))
        self.assertEqual(dq.ACTIVE, dq.row_staleness([item(dq.UNDETERMINED), item(dq.ACTIVE)]))
        self.assertEqual(dq.UNDETERMINED, dq.row_staleness([item(dq.SUPERSEDED), item(dq.UNDETERMINED)]))
        self.assertEqual(dq.SUPERSEDED, dq.row_staleness([item(dq.SUPERSEDED), item(dq.SUPERSEDED)]))
        self.assertEqual(dq.OUT_OF_WINDOW, dq.row_staleness([item(dq.SUPERSEDED), item(dq.OUT_OF_WINDOW)]))
        self.assertEqual(dq.COVERAGE_EMPTY, dq.row_staleness([item(dq.SUPERSEDED), item(dq.COVERAGE_EMPTY)]))
        self.assertEqual(dq.UNDETERMINED, dq.row_staleness([]))


def tiny_inputs(fundamentals: dict, *, news=None, e1_rows=None, excluded=("900001.SH", "900002.SH")):
    """Synthetic single-night inputs; fundamentals maps ts_code → 基本面 dict."""
    results = []
    for code, fundamental in fundamentals.items():
        results.append({"ts_code": code, "dims": {
            "基本面": fundamental, "消息面": (news or {}).get(code, {"近7日公告条数": 1})},
            "completeness": {"verdict": "COMPLETE"}})
    codes = list(fundamentals) + list(excluded)
    e1_rows = e1_rows or [
        {"ts_code": code, "verdict": "RED_FLAG" if code in excluded else "NO_RED_FLAG_FOUND",
         "reason_codes": [], "latest_e1_date": "20260801",
         "evidence_coverage": {"forecast": "SUPERSEDED", "express": "EMPTY_VALID",
                               "income": "COMPLETE", "filed_quarters": 3}}
        for code in codes
    ]
    e1 = {"schema": "ar.e1_event_layer", "as_of": "20260929", "generated_at": "2026-09-29T14:00:00+00:00",
          "status": "PARTIAL", "source": {"periods": ["20260630", "20250930"]},
          "rows": e1_rows, "rows_hash": fp._hash(e1_rows)}
    scan = {"generated_at": "2026-09-29T14:10:00+00:00", "rows": [
        {"channel": "E1_EVENT", "ts_code": row["ts_code"],
         "feature_values": {"verdict": row["verdict"], "latest_e1_date": row["latest_e1_date"]},
         "reason_codes": row["reason_codes"]} for row in e1_rows]}
    return {
        "as_of": "20260929", "run_id": "20260929_000000_1_testrun0",
        "battery": {"results": results, "rows_hash": fp._hash(results)}, "scan": scan,
        "candidate_review": {"rows": [{"ts_code": c, "review_status": "EXCLUDED_RED_FLAG"} for c in excluded]},
        "candidate_manifest": {"manifest_hash": "m" * 64}, "registry": {"rows": []},
        "deep_queue": {"ready_pool": [{"ts_code": c, "ready": True} for c in fundamentals]},
        "e1_raw": json.dumps(e1, ensure_ascii=False).encode("utf-8"),
    }


RED = {"红旗闸门": "RED_FLAG", "红旗理由": ["最新预告[预减] 20260711 期末20260630 净利下限0.0亿"],
       "最新E1日期": "20260711"}


class QueueRuleTests(unittest.TestCase):
    def test_blocked_or_passing_fundamentals_are_never_counted_as_red_flags(self) -> None:
        inputs = tiny_inputs({
            "000001.SZ": dict(RED),
            "000002.SZ": {"status": "DATA_BLOCKED", "红旗闸门": "RED_FLAG", "红旗理由": ["x"]},
            "000003.SZ": {"红旗闸门": "PASS", "红旗理由": []},
        })
        _b, _r, queue, _l, _m = replay(inputs)
        self.assertEqual(1, queue["counts"]["u3_red_flag_rows"])
        self.assertEqual(["000001.SZ"], [row["ts_code"] for row in queue["rows"]
                                         if row["disagreement_class"] == dq.CLASS_U3_VS_E1])

    def test_unavailable_e1_publishes_null_staleness_not_zero(self) -> None:
        inputs = tiny_inputs({"000001.SZ": dict(RED)})
        _b, _r, queue, _l, _m = replay(inputs, e1_raw=b"")
        self.assertEqual(dq.E1_UNAVAILABLE, queue["source_bindings"]["e1_basis"])
        self.assertIsNone(queue["counts"]["superseded_rows"])
        self.assertIsNone(queue["counts"]["active_rows"])
        self.assertEqual(1, queue["counts"]["undetermined_rows"])
        forged = copy.deepcopy(queue)
        forged["counts"]["superseded_rows"] = 0
        with self.assertRaisesRegex(dq.DisagreementError, "cannot publish staleness counts"):
            dq.validate_queue(forged)

    def test_only_human_cap_rows_are_routed_and_controls_come_first(self) -> None:
        inputs = tiny_inputs({f"0000{i:02d}.SZ": dict(RED) for i in range(15)})
        _b, _r, queue, _l, _m = replay(inputs)
        routed = [row for row in queue["rows"] if row["routing"]["queue"] == "HUMAN_ADJUDICATION"]
        self.assertEqual(dq.HUMAN_CAP, len(routed))
        self.assertEqual(dq.HUMAN_CAP, queue["counts"]["human_routed_rows"])
        self.assertEqual({dq.CLASS_CONTROL}, {row["disagreement_class"] for row in queue["rows"][:2]})
        self.assertEqual(list(range(1, 18)), [row["routing"]["rank"] for row in queue["rows"]])

    def test_validator_refuses_more_routed_rows_than_the_human_cap(self) -> None:
        inputs = tiny_inputs({f"0000{i:02d}.SZ": dict(RED) for i in range(15)})
        _b, _r, queue, _l, _m = replay(inputs)
        forged = copy.deepcopy(queue)
        for row in forged["rows"]:
            row["routing"]["queue"] = "HUMAN_ADJUDICATION"
        forged["rows_hash"] = fp._hash(forged["rows"])
        forged["counts"]["human_routed_rows"] = len(forged["rows"])
        with self.assertRaisesRegex(dq.DisagreementError, "human cap"):
            dq.validate_queue(forged)

    def test_active_evidence_outranks_superseded_evidence(self) -> None:
        inputs = tiny_inputs({"000001.SZ": dict(RED), "000002.SZ": dict(RED, 红旗理由=[
            "最新预告[预减] 20260711 期末20260630 净利下限0.0亿", "最近季度归母-1.0亿为负且环比恶化(前季0.1亿)"])})
        _b, _r, queue, _l, _m = replay(inputs)
        u3 = [row for row in queue["rows"] if row["disagreement_class"] == dq.CLASS_U3_VS_E1]
        self.assertEqual(["000002.SZ", "000001.SZ"], [row["ts_code"] for row in u3])
        self.assertEqual([dq.ACTIVE, dq.SUPERSEDED], [row["evidence_staleness"] for row in u3])

    def test_queue_cannot_carry_authority_or_a_machine_filled_label(self) -> None:
        _b, _r, queue, _l, _m = replay(tiny_inputs({"000001.SZ": dict(RED)}))
        for mutate in (
            lambda q: q["authority"].__setitem__("u4_admission_authority", True),
            lambda q: q["authority"].__setitem__("changes_machine_verdict", True),
        ):
            forged = copy.deepcopy(queue)
            mutate(forged)
            with self.assertRaisesRegex(dq.DisagreementError, "authority"):
                dq.validate_queue(forged)
        forged = copy.deepcopy(queue)
        forged["rows"][0]["adjudication_status"] = "MACHINE_VERDICT_CONFIRMED"
        forged["rows_hash"] = fp._hash(forged["rows"])
        with self.assertRaisesRegex(dq.DisagreementError, "PENDING"):
            dq.validate_queue(forged)

    def test_control_draw_is_seeded_by_as_of_and_code(self) -> None:
        review = {"rows": [{"ts_code": f"6000{i:02d}.SH", "review_status": "EXCLUDED_RED_FLAG"}
                           for i in range(30)]}
        first = dq.control_codes(review, "20260929")
        self.assertEqual(first, dq.control_codes(review, "20260929"))
        self.assertEqual(2, len(first))
        expected = sorted((r["ts_code"] for r in review["rows"]),
                          key=lambda c: hashlib.sha256(f"20260929|{c}".encode()).hexdigest())[:2]
        self.assertEqual(expected, first)


class TrustMetricRuleTests(unittest.TestCase):
    def test_rate_below_min_n_is_withheld_never_zero(self) -> None:
        withheld = rt.metric("news_channel_available_share", numerator=0, denominator=19)
        self.assertEqual((None, rt.WITHHELD, "UNRATED"),
                         (withheld["rate"], withheld["level"], withheld["reliance"]))
        self.assertEqual((0, 19), (withheld["numerator"], withheld["denominator"]))
        rated = rt.metric("news_channel_available_share", numerator=0, denominator=20)
        self.assertEqual((0.0, rt.MISSES), (rated["rate"], rated["level"]))
        empty = rt.metric("u4_ready_false_ready_share", numerator=0, denominator=0)
        self.assertEqual((None, rt.WITHHELD), (empty["rate"], empty["level"]))

    def test_t1_counts_only_e1_confirmed_supersession(self) -> None:
        inputs = tiny_inputs({f"0000{i:02d}.SZ": dict(RED) for i in range(20)})
        inputs["battery"]["results"][0]["dims"]["基本面"]["红旗理由"] = [
            "最新预告[预减] 20250124 期末20241231 净利下限1.2亿"]
        inputs["battery"]["rows_hash"] = fp._hash(inputs["battery"]["results"])
        _b, _r, queue, line, _m = replay(inputs)
        t1 = by_id(line)["red_flag_stale_evidence_share"]
        self.assertEqual((19, 20), (t1["numerator"], t1["denominator"]))
        self.assertIn("out_of_e1_window=1", t1["note"])
        self.assertEqual(1, queue["counts"]["out_of_e1_window_rows"])

    def test_news_not_run_is_unavailable_and_unknown_status_is_unparsed(self) -> None:
        news = {"000001.SZ": {"status": "NOT_RUN"}, "000002.SZ": {"status": "DATA_BLOCKED"},
                "000003.SZ": {"status": "SOMETHING_NEW"}, "000004.SZ": {"近7日公告条数": 3}}
        inputs = tiny_inputs({code: {"红旗闸门": "PASS", "红旗理由": []} for code in news}, news=news)
        _b, _r, _q, line, _m = replay(inputs)
        t6 = by_id(line)["news_channel_available_share"]
        self.assertEqual((1, 3, 1), (t6["numerator"], t6["denominator"], t6["unparsed_count"]))

    def test_line_refuses_performance_keys_and_claim_authority(self) -> None:
        _b, _r, _q, line, _m = replay(tiny_inputs({"000001.SZ": dict(RED)}))
        rt.validate_trust_line(line)
        for key in ("hit_rate", "alpha", "forward_return", "pnl", "composite_score"):
            forged = copy.deepcopy(line)
            forged["source_binding"][key] = None
            forged["source_binding"] = {k: forged["source_binding"][k] for k in forged["source_binding"]}
            with self.assertRaisesRegex(rt.TrustLineError, "performance/action keys"):
                rt.validate_trust_line(forged)
        for key, value in (("claim_allowed", True), ("performance_claim", "ok"),
                           ("u4_selection_authority", True)):
            forged = copy.deepcopy(line)
            forged["authority"][key] = value
            with self.assertRaisesRegex(rt.TrustLineError, "cannot claim"):
                rt.validate_trust_line(forged)

    def test_level_rate_and_reliance_are_recomputed_not_self_reported(self) -> None:
        _b, _r, _q, line, _m = replay(tiny_inputs({"000001.SZ": dict(RED)}))
        forged = copy.deepcopy(line)
        t6 = forged["metrics"][rt.METRIC_IDS.index("news_channel_available_share")]
        t6["rate"] = 1.0
        with self.assertRaisesRegex(rt.TrustLineError, "not derived from its counts"):
            rt.validate_trust_line(forged)
        forged = copy.deepcopy(line)
        forged["metrics"][0]["level"] = rt.MEETS
        with self.assertRaisesRegex(rt.TrustLineError, "not derived from its counts"):
            rt.validate_trust_line(forged)

    def test_u4_labels_join_only_on_the_recomputed_battery_row_hash(self) -> None:
        inputs = tiny_inputs({f"0000{i:02d}.SZ": {"红旗闸门": "PASS", "红旗理由": []} for i in range(3)})
        rows = inputs["battery"]["results"]
        events = [
            {"candidate": {"ts_code": rows[0]["ts_code"]}, "decision": "DATA_BLOCKED",
             "reason_codes": ["U3_INCOMPLETE"], "missing_evidence": [],
             "source": {"run_id": inputs["run_id"], "u3_battery_row_hash": "sha256:" + fp._hash(rows[0])}},
            {"candidate": {"ts_code": rows[1]["ts_code"]}, "decision": "REJECT",
             "reason_codes": ["HUMAN_JUDGMENT"], "missing_evidence": [],
             "source": {"run_id": inputs["run_id"], "u3_battery_row_hash": "sha256:" + fp._hash(rows[1])}},
            {"candidate": {"ts_code": rows[2]["ts_code"]}, "decision": "DATA_BLOCKED",
             "reason_codes": ["U3_INCOMPLETE"], "missing_evidence": [],
             "source": {"run_id": inputs["run_id"], "u3_battery_row_hash": "sha256:" + "0" * 64}},
        ]
        _b, _r, _q, line, members = replay(inputs, u4={"status": "OK", "events": events, "head": "h", "error": None})
        t4 = by_id(line)["u4_ready_false_ready_share"]
        self.assertEqual((1, 2, 1), (t4["numerator"], t4["denominator"], t4["unparsed_count"]))
        self.assertEqual({rows[0]["ts_code"]: True, rows[1]["ts_code"]: False},
                         members["u4_ready_false_ready_share"])
        self.assertEqual(rt.WITHHELD, t4["level"])

    def test_human_confirmed_share_uses_only_closed_batches_bound_to_this_queue(self) -> None:
        inputs = tiny_inputs({"000001.SZ": dict(RED), "000002.SZ": dict(RED)})
        _b, _r, queue, _l, _m = replay(inputs)
        u3 = [row for row in queue["rows"] if row["disagreement_class"] == dq.CLASS_U3_VS_E1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root.joinpath(*rt.ADJUDICATION_LEDGER_REL)
            path.parent.mkdir(parents=True)
            authority = {"u4_admission_authority": False, "changes_machine_verdict": False,
                         "claim_allowed": False, "no_trade_flag": True}

            def label(batch, row, verdict, *, run_id=inputs["run_id"]):
                return {"schema": rt.ADJUDICATION_SCHEMA, "batch_id": batch, "run_id": run_id,
                        "queue_rows_hash": queue["rows_hash"], "row_id": row["row_id"],
                        "human_verdict": verdict, "authority": authority}

            event_ledger.append(rt.ADJUDICATION_KIND, "a1", label("b1", u3[0], "MACHINE_VERDICT_REJECTED_STALE_EVIDENCE"), str(path))
            event_ledger.append(rt.ADJUDICATION_CLOSURE_KIND, "c1", {"batch_id": "b1"}, str(path))
            # an open batch and a batch bound to another run never count
            event_ledger.append(rt.ADJUDICATION_KIND, "a2", label("b2", u3[1], "MACHINE_VERDICT_CONFIRMED"), str(path))
            event_ledger.append(rt.ADJUDICATION_KIND, "a3", label("b3", u3[1], "MACHINE_VERDICT_CONFIRMED", run_id="other"), str(path))
            event_ledger.append(rt.ADJUDICATION_CLOSURE_KIND, "c3", {"batch_id": "b3"}, str(path))
            state = rt.read_adjudications(root, inputs["run_id"], queue)
            self.assertEqual("OK", state["status"])
            self.assertEqual({u3[0]["row_id"]: "MACHINE_VERDICT_REJECTED_STALE_EVIDENCE"}, state["labels"])
            _b, _r, _q, line, _m = replay(inputs, adjudication=state)
            t3 = by_id(line)["red_flag_human_confirmed_share"]
            self.assertEqual((0, 1, rt.WITHHELD), (t3["numerator"], t3["denominator"], t3["level"]))
            # a broken chain is never read as labels
            with path.open("a", encoding="utf-8") as handle:
                handle.write('{"garbage": true}\n')
            broken = rt.read_adjudications(root, inputs["run_id"], queue)
            self.assertEqual(("INVALID", {}), (broken["status"], broken["labels"]))
            _b, _r, _q, line, _m = replay(inputs, adjudication=broken)
            self.assertEqual(rt.NC_NO_HUMAN_LABELS,
                             by_id(line)["red_flag_human_confirmed_share"]["not_computable_reason"])

    def test_missing_or_invalid_u4_ledger_is_not_computable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual("ABSENT", rt.read_u4_decisions(root, "r")["status"])
            path = root.joinpath(*rt.U4_LEDGER_REL)
            path.parent.mkdir(parents=True)
            path.write_text('{"not": "a ledger"}\n', encoding="utf-8")
            state = rt.read_u4_decisions(root, "r")
            self.assertEqual("INVALID", state["status"])
            self.assertFalse(Path(f"{path}.lock").exists(), "reading must not create lock files")


class RollingTests(unittest.TestCase):
    def _record(self, as_of, run_id, members):
        return {"as_of": as_of, "run_id": run_id, "members": members}

    def test_rolling_pools_distinct_rows_not_row_nights(self) -> None:
        metrics = [rt.metric(mid, not_computable_reason=rt.NC_E1_UNAVAILABLE) for mid in rt.METRIC_IDS]
        sticky = {"news_channel_available_share": {"000001.SZ": False}}
        prior = [self._record(f"202609{d:02d}", f"r{d}", sticky) for d in range(1, 25)]
        pooled = rt.rolling({}, metrics, prior, as_of="20260929")["per_metric"]["news_channel_available_share"]
        self.assertEqual({"distinct_rows": 1, "pooled_numerator": 0, "pooled_denominator": 1,
                          "level": rt.WITHHELD}, pooled)

    def test_rolling_ignores_later_nights_and_uses_the_latest_state_per_row(self) -> None:
        current = [rt.metric("news_channel_available_share", numerator=0, denominator=0)]
        current += [rt.metric(mid, not_computable_reason=rt.NC_E1_UNAVAILABLE)
                    for mid in rt.METRIC_IDS if mid != "news_channel_available_share"]
        many = {f"{i:06d}.SZ": True for i in range(25)}
        prior = [self._record("20260920", "a", {"news_channel_available_share": dict.fromkeys(many, False)}),
                 self._record("20260921", "b", {"news_channel_available_share": many}),
                 self._record("20261001", "future", {"news_channel_available_share": dict.fromkeys(many, False)})]
        pooled = rt.rolling({}, current, prior, as_of="20260929")["per_metric"]
        self.assertEqual((25, 25, rt.MEETS), (pooled["news_channel_available_share"]["distinct_rows"],
                                              pooled["news_channel_available_share"]["pooled_numerator"],
                                              pooled["news_channel_available_share"]["level"]))
        self.assertEqual(rt.NOT_COMPUTABLE, pooled["red_flag_stale_evidence_share"]["level"])


class TrustLedgerTests(unittest.TestCase):
    def _line(self, run_suffix="0"):
        inputs = tiny_inputs({"000001.SZ": dict(RED)})
        inputs["run_id"] = f"20260929_000000_1_testrun{run_suffix}"
        _b, _r, _q, line, members = replay(inputs)
        return line, members

    def test_append_is_chained_anchored_and_idempotent_per_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            line, members = self._line()
            first = rt.append_trust_line(root, line, members)
            self.assertEqual(("APPENDED", 0), (first["status"], first["seq"]))
            self.assertEqual("LOCAL_ONLY_UNBACKED", first["retention_status"])
            again = rt.append_trust_line(root, dict(line, generated_at="2026-09-30T00:00:00+00:00"), members)
            self.assertEqual("ALREADY_RECORDED", again["status"])
            changed = copy.deepcopy(line)
            changed["metrics"][5] = rt.metric("news_channel_available_share", numerator=0, denominator=1)
            self.assertEqual("CONFLICT_NOT_APPENDED", rt.append_trust_line(root, changed, members)["status"])
            second_line, second_members = self._line("1")
            second = rt.append_trust_line(root, second_line, second_members)
            self.assertEqual(("APPENDED", 1), (second["status"], second["seq"]))
            records, error = rt.read_prior_lines(root)
            self.assertIsNone(error)
            self.assertEqual([0, 1], [r["seq"] for r in records])
            self.assertEqual(records[0]["hash"], records[1]["prev"])
            anchor = json.loads(Path(f"{rt.ledger_path(root)}.anchor.json").read_text())
            self.assertEqual({"n": 2, "head": records[1]["hash"]}, anchor)

    def test_tampered_or_truncated_ledger_is_never_appended_to(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            line, members = self._line()
            rt.append_trust_line(root, line, members)
            path = rt.ledger_path(root)
            text = path.read_text(encoding="utf-8").replace('"as_of":"20260929"', '"as_of":"20260928"', 1)
            path.write_text(text, encoding="utf-8")
            other, other_members = self._line("1")
            self.assertEqual("LEDGER_INVALID_NOT_APPENDED",
                             rt.append_trust_line(root, other, other_members)["status"])
            path.write_text("", encoding="utf-8")
            self.assertEqual("LEDGER_INVALID_NOT_APPENDED",
                             rt.append_trust_line(root, other, other_members)["status"])

    def test_a_line_against_another_nights_e1_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            line, members = self._line()
            forged = copy.deepcopy(line)
            forged["source_binding"]["e1_layer_as_of"] = "20260930"
            result = rt.append_trust_line(Path(tmp), forged, members)
            self.assertEqual("REFUSED_NOT_SAME_RUN", result["status"])
            self.assertFalse(rt.ledger_path(Path(tmp)).exists())

    def test_write_failure_is_reported_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "advisory"
            blocker.write_text("not a directory", encoding="utf-8")
            line, members = self._line()
            result = rt.append_trust_line(blocker, line, members)
            self.assertEqual("WRITE_FAILED", result["status"])
            self.assertTrue(result["error"])


# ── finalize wiring, nightly verifier, U4 compatibility ───────────────────

def red_row(tk: str, today: str) -> dict:
    row = dagtests.complete_row(tk, today)
    row["dims"]["基本面"] = {"ok": True, "红旗闸门": "RED_FLAG",
                           "红旗理由": ["最新预告[预减] 20260711 期末20260630 净利下限0.0亿"],
                           "最新E1日期": "20260711"}
    return row


def restamp_stage(bundle: Path, stage: str, name: str, payload: dict) -> None:
    (bundle / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = bundle / f"stage_{stage}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][name] = hashlib.sha256((bundle / name).read_bytes()).hexdigest()
    manifest.pop("stage_hash")
    manifest["stage_hash"] = fp._hash(manifest)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class FinalizeWiringTests(unittest.TestCase):
    RED_CODES = 3

    def _finalize(self, root: Path, *, e1: bool = True, advisory_blocked: bool = False):
        runner = dagtests.FinalizeEndToEndTests("test_three_stages_run_end_to_end_without_token")
        pv, obs = runner._run_stages(root, "candidates")
        bundle = obs / dagtests.TARGET / dagtests.RUN_ID
        manifest = json.loads((bundle / "candidate_manifest.json").read_text("utf-8"))
        red = set(manifest["ts_codes"][:self.RED_CODES])

        def outcomes(order, target, worker, **_):
            return [{"ts_code": tk, "reason": None,
                     "row": red_row(tk, target) if tk in red else dagtests.complete_row(tk, target)}
                    for tk in order]

        self.assertEqual(0, runner._collect(root, obs, outcomes))
        e1_path = pv / "e1_event_layer.json"
        layer = json.loads(e1_path.read_text("utf-8"))
        if e1:
            # the closure fixture predates generated_at/evidence_coverage; add them, same verdicts
            layer["generated_at"] = "2026-08-11T00:00:00+00:00"
            layer["status"] = "PARTIAL"
            layer["source"] = {"periods": ["20260630", "20250930"]}
            for row in layer["rows"]:
                row["evidence_coverage"] = {"forecast": "SUPERSEDED", "express": "EMPTY_VALID",
                                            "income": "COMPLETE", "filed_quarters": 3}
            layer["rows_hash"] = fp._hash(layer["rows"])
            dagtests.write_json(e1_path, layer)
        else:
            e1_path.unlink()
        if advisory_blocked:
            (root / "research_advisory").write_text("blocked", encoding="utf-8")
        with mock.patch.dict(os.environ, runner._env(root, obs)), mock.patch.object(dag, "REPO_ROOT", root):
            self.assertEqual(0, dag.run_finalize())
        health = json.loads((pv / "funnel_health.json").read_text("utf-8"))
        return pv, obs, bundle, health, red

    def _durable(self, root: Path, bundle: Path) -> tuple[Path, Path]:
        repo = root / "repo"
        durable = repo / "data_history" / "funnel" / dagtests.TARGET / dagtests.RUN_ID
        durable.parent.mkdir(parents=True)
        shutil.copytree(bundle, durable)
        return repo, durable

    def verify(self, health: dict, repo: Path, pv: Path) -> None:
        nightly._verify_funnel_bundle(health, str(repo), str(pv / "funnel_health.json"))

    def test_finalize_writes_both_files_through_the_stage_and_health_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, _obs, bundle, health, red = self._finalize(root)
            stage = json.loads((bundle / "stage_finalize.json").read_text("utf-8"))
            self.assertEqual(set(dag.STAGE3_FILES) | set(dag.STAGE3_OPTIONAL_FILES), set(stage["artifacts"]))
            top = json.loads((bundle / "manifest.json").read_text("utf-8"))
            # The top-level artifact set is compared by exact equality against history.
            self.assertEqual(set(nightly_funnel.BUNDLE_FILES + nightly_funnel.DAG_EVIDENCE_FILES), set(top["artifacts"]))
            queue = json.loads((bundle / dq.QUEUE_FILE).read_text("utf-8"))
            line = json.loads((bundle / rt.TRUST_FILE).read_text("utf-8"))
            self.assertEqual(stage["generated_at"], queue["generated_at"])
            self.assertEqual(stage["generated_at"], line["generated_at"])
            self.assertEqual(dq.E1_SAME_AS_OF, queue["source_bindings"]["e1_basis"])
            self.assertEqual(self.RED_CODES, queue["counts"]["u3_red_flag_rows"])
            self.assertEqual(self.RED_CODES, queue["counts"]["superseded_rows"])
            self.assertEqual(line, health["research_trust"])
            self.assertEqual(dq.summarize(queue), health["disagreement_summary"])
            self.assertEqual("APPENDED", health["research_trust_ledger"]["status"])
            self.assertNotIn("research_trust", health["battery_coverage"])
            records, error = rt.read_prior_lines(root / "research_advisory")
            self.assertIsNone(error)
            self.assertEqual([dagtests.RUN_ID], [r["run_id"] for r in records])
            self.assertEqual(set(red), set(records[0]["members"]["red_flag_stale_evidence_share"]))

    def test_missing_e1_degrades_to_unavailable_without_failing_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pv, _obs, _bundle, health, _red = self._finalize(root, e1=False)
            self.assertEqual(dq.E1_UNAVAILABLE, health["disagreement_summary"]["e1_basis"])
            self.assertIsNone(health["disagreement_summary"]["counts"]["superseded_rows"])
            t1 = by_id(health["research_trust"])["red_flag_stale_evidence_share"]
            self.assertEqual(rt.NC_E1_UNAVAILABLE, t1["not_computable_reason"])

    def test_ledger_failure_is_recorded_in_health_and_finalize_still_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pv, _obs, _bundle, health, _red = self._finalize(root, advisory_blocked=True)
            self.assertEqual("WRITE_FAILED", health["research_trust_ledger"]["status"])
            self.assertIn("research_trust", health)

    def test_verifier_recomputes_queue_summary_and_machine_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, _obs, bundle, health, _red = self._finalize(root)
            repo, durable = self._durable(root, bundle)
            self.verify(health, repo, pv)

            forged = copy.deepcopy(health)
            forged["disagreement_summary"]["counts"]["u3_red_flag_vs_e1_clear_rows"] = 0
            with self.assertRaisesRegex(ValueError, "disagreement_summary"):
                self.verify(forged, repo, pv)

            forged = copy.deepcopy(health)
            forged["research_trust"]["metrics"][5]["note"] = "edited"
            with self.assertRaisesRegex(ValueError, "research_trust"):
                self.verify(forged, repo, pv)

            forged = copy.deepcopy(health)
            del forged["research_trust_ledger"]
            with self.assertRaisesRegex(ValueError, "账本写入状态"):
                self.verify(forged, repo, pv)

    def test_verifier_refuses_a_resealed_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, _obs, bundle, health, _red = self._finalize(root)
            repo, durable = self._durable(root, bundle)
            queue = json.loads((durable / dq.QUEUE_FILE).read_text("utf-8"))
            queue["rows"] = [row for row in queue["rows"] if row["disagreement_class"] == dq.CLASS_CONTROL]
            for rank, row in enumerate(queue["rows"], start=1):
                row["routing"]["rank"] = rank
            queue["rows_hash"] = fp._hash(queue["rows"])
            restamp_stage(durable, "finalize", dq.QUEUE_FILE, queue)
            with self.assertRaisesRegex(ValueError, "disagreement_queue.json"):
                self.verify(health, repo, pv)

    def test_verifier_refuses_resealed_machine_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, _obs, bundle, health, _red = self._finalize(root)
            repo, durable = self._durable(root, bundle)
            line = json.loads((durable / rt.TRUST_FILE).read_text("utf-8"))
            index = rt.METRIC_IDS.index("news_channel_available_share")
            t6 = line["metrics"][index]
            line["metrics"][index] = rt.metric("news_channel_available_share",
                                               numerator=max(0, t6["numerator"] - 1),
                                               denominator=t6["denominator"], note=t6["note"])
            rt.validate_trust_line(line)
            restamp_stage(durable, "finalize", rt.TRUST_FILE, line)
            forged = dict(health, research_trust=line)
            with self.assertRaisesRegex(ValueError, "T1/T2/T6/T7"):
                self.verify(forged, repo, pv)

    def test_files_and_health_keys_must_appear_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, _obs, bundle, health, _red = self._finalize(root)
            repo, _durable = self._durable(root, bundle)
            stripped = {k: v for k, v in health.items() if k not in {"disagreement_summary", "research_trust"}}
            with self.assertRaisesRegex(ValueError, "not bound together"):
                self.verify(stripped, repo, pv)

    def test_optional_finalize_files_are_exactly_the_queue_and_trust_line(self) -> None:
        self.assertEqual(tuple(rt.FINALIZE_EXTRA_FILES), tuple(dag.STAGE3_OPTIONAL_FILES))
        self.assertEqual((dq.QUEUE_FILE, rt.TRUST_FILE), tuple(dag.STAGE3_OPTIONAL_FILES))


class U4CompatibilityTests(unittest.TestCase):
    def _tree(self, root: Path, extra: dict):
        import test_u4_pre_decision_runtime as runtime

        original = dag._write_stage

        def write_stage(bundle_dir, stage, files, **kwargs):
            if stage == "finalize":
                files = dict(files, **extra)
            return original(bundle_dir, stage, files, **kwargs)

        with mock.patch.object(dag, "_write_stage", write_stage):
            return runtime._fixture_tree(root)

    def _build(self, root: Path, extra: dict):
        import u4_pre_decision as pre

        bundle, feature_health, funnel_health = self._tree(root, extra)
        return pre.build_packet(
            bundle_dir=bundle, feature_health_path=feature_health, funnel_health_path=funnel_health,
            diagnostic_ref="u4_pre_decision_diagnostic.json", industry="TECH",
            method_version=pre.DEFAULT_METHOD_VERSION, generated_at="2026-08-12T09:00:00+00:00",
        )

    def test_u4_packet_builds_with_the_finalize_queue_and_trust_line(self) -> None:
        import test_u4_pre_decision_runtime as runtime

        extra = {name: {"generated_at": runtime.GENERATED_AT, "fixture": name}
                 for name in dag.STAGE3_OPTIONAL_FILES}
        with tempfile.TemporaryDirectory() as tmp:
            packet, _diagnostic = self._build(Path(os.path.realpath(tmp)), extra)
            self.assertTrue(packet["packet_hash"])

    def test_u4_packet_refuses_any_other_extra_finalize_file(self) -> None:
        import test_u4_pre_decision_runtime as runtime
        import u4_pre_decision as pre

        extra = {"unexpected.json": {"generated_at": runtime.GENERATED_AT}}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(pre.PreDecisionError, "stage receipt contract is invalid: finalize"):
                self._build(Path(os.path.realpath(tmp)), extra)

    def test_evidence_view_captures_finalize_stage_artifacts(self) -> None:
        import test_u4_pre_decision_runtime as runtime
        from evidence_view import DirectoryCapability, EvidenceView
        import u4_pre_decision as pre

        extra = {name: {"generated_at": runtime.GENERATED_AT, "fixture": name}
                 for name in dag.STAGE3_OPTIONAL_FILES}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(os.path.realpath(tmp))
            bundle, _feature, _funnel = self._tree(root, extra)
            bundle_ref = bundle.relative_to(root).as_posix()
            (root / "packet.json").write_text("{}", encoding="utf-8")
            (root / "diagnostic.json").write_text("{}", encoding="utf-8")
            with DirectoryCapability.open(str(root)) as capability:
                view = EvidenceView.capture_u4(
                    capability, packet_ref="packet.json", diagnostic_ref="diagnostic.json",
                    bundle_ref=bundle_ref, feature_health_ref="public/data/v2/feature_store_health.json",
                    funnel_health_ref="public/data/v2/funnel_health.json", cyclical_flags_ref=None,
                )
            for name in dag.STAGE3_OPTIONAL_FILES:
                self.assertIn(f"{bundle_ref}/{name}", view.files)
            packet, _diagnostic = pre.build_packet(
                evidence=view, bundle_ref=bundle_ref,
                feature_health_ref="public/data/v2/feature_store_health.json",
                funnel_health_ref="public/data/v2/funnel_health.json",
                diagnostic_ref="u4_pre_decision_diagnostic.json", industry="TECH",
                method_version=pre.DEFAULT_METHOD_VERSION, generated_at="2026-08-12T09:00:00+00:00",
            )
            self.assertTrue(packet["packet_hash"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
