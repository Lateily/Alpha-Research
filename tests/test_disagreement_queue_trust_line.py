#!/usr/bin/env python3
"""Nightly machine-vs-machine disagreement queue (Q v0.1) and research trust line (T v1.0).

Pins, one by one:
  · offline replay of the retained 9/29 production bundle + same-run E1 layer:
    46 U3 red flags, all E1-clear, 43 E1-confirmed SUPERSEDED + 3 OUT_OF_E1_WINDOW,
    T1 43/46, T2 0/46 (declared a structural zero), T6 0/181, 46 U3 rows + 2 controls,
    10 routed; 9/24: 39 U3 red flags
  · an E1 layer from another night/run is never used; its absence is UNAVAILABLE/null, never 0
  · rates below MIN_N are withheld (null), never 0; no performance/claim keys, no authority
  · T3 counts only U3-row adjudications that re-pass the contract-A human boundary; T4/T5
    read the ready claim of the reviewed U4 packet and never turn bulk DEFER or a forced
    REJECT into a confirmation
  · finalize only stages the trust line; the hash-chained, idempotent ledger is appended by
    run_nightly after a verified, COMPLETE, published night; rolling pools one line per as_of
  · finalize writes both files through the finalize stage only (manifest artifact set
    unchanged), health gets new top-level keys, and the nightly verifier recomputes them,
    including every source_binding hash; an advisory build failure is declared, not fatal
  · U4 pre-decision accepts exactly these optional finalize files, all or none

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


def _expand_fixture(fx: dict) -> dict:
    """Undo the QT-C9 compaction: every battery/scan/E1 row back, sorted by ts_code."""
    fx = copy.deepcopy(fx)
    rows = list(fx["battery_rows"])
    for code, gate, news, completeness in fx.get("battery_rows_compact") or []:
        fundamental = ({"status": gate.split(":", 1)[1]} if gate.startswith("status:")
                       else {"红旗闸门": gate})
        rows.append({"ts_code": code, "fundamental": fundamental, "news_status": news,
                     "completeness_verdict": completeness})
    fx["battery_rows"] = sorted(rows, key=lambda row: row["ts_code"])
    scan = dict(fx["scan_e1"])
    scan.update({code: {"verdict": verdict, "latest_e1_date": None, "reason_codes": []}
                 for code, verdict in (fx.get("scan_e1_verdict_only") or {}).items()})
    fx["scan_e1"] = scan
    if "e1" in fx:
        e1_rows = list(fx["e1"]["rows"])
        e1_rows += [{"ts_code": code, "verdict": verdict}
                    for code, verdict in (fx["e1"].get("verdict_only") or {}).items()]
        fx["e1"]["rows"] = sorted(e1_rows, key=lambda row: row["ts_code"])
    return fx


def inputs_from_fixture(fx: dict) -> dict:
    """Rebuild the minimal bundle payload shapes the queue/trust code reads."""
    fx = _expand_fixture(fx)
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
             "feature_values": {"verdict": view["verdict"], "latest_e1_date": view.get("latest_e1_date")},
             "reason_codes": view.get("reason_codes") or []}
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
        battery=inputs["battery"], scan=inputs["scan"],
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
            "unobservable_cells": ["U3_PASS_VS_E1_RED_FLAG", "U3_RED_FLAG_VS_E1_RED_FLAG"],
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
        # QT-C2: the zero is structural (E1 red flags never reach U3) and says so.
        self.assertTrue(t2["note"].startswith("STRUCTURAL ZERO"), t2["note"])
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

    def test_a_cited_period_after_the_e1_window_is_undetermined(self) -> None:
        # QT-C5: E1 coverage is per kind; it says nothing about a filing after its window.
        cov = {"forecast": "SUPERSEDED"}
        self.assertEqual(dq.UNDETERMINED,
                         dq.reason_staleness("forecast", "20260930", cov, "20250930", "20260630")[1])
        self.assertEqual(dq.SUPERSEDED,
                         dq.reason_staleness("forecast", "20260630", cov, "20250930", "20260630")[1])

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

    def _u4_state(self, inputs, events, *, ready=None, blocked=None):
        """packet_rows as read_u4_decisions builds them from the decided intent."""
        ready = ready or {}
        blocked = blocked or {}
        packet_rows = {
            f"{e['source']['u4_packet_hash']}|{e['candidate']['ts_code']}": {
                "ready": ready.get(e["candidate"]["ts_code"], True),
                "blocked_reasons": list(blocked.get(e["candidate"]["ts_code"], [])),
            } for e in events
        }
        return {"status": "OK", "events": events, "packet_rows": packet_rows, "head": "h", "error": None}

    @staticmethod
    def _event(inputs, row, decision, reasons, *, missing=(), row_hash=None, run_id=None):
        return {"candidate": {"ts_code": row["ts_code"]}, "decision": decision,
                "reason_codes": list(reasons), "missing_evidence": list(missing),
                "source": {"run_id": run_id or inputs["run_id"], "u4_packet_hash": "sha256:" + "p" * 64,
                           "u3_battery_row_hash": row_hash or "sha256:" + fp._hash(row)}}

    def test_u4_labels_join_only_on_the_recomputed_battery_row_hash(self) -> None:
        inputs = tiny_inputs({f"0000{i:02d}.SZ": {"红旗闸门": "PASS", "红旗理由": []} for i in range(3)})
        rows = inputs["battery"]["results"]
        events = [
            self._event(inputs, rows[0], "DATA_BLOCKED", ["U3_INCOMPLETE"], missing=["U3_SIX_DIMENSION_BATTERY"]),
            self._event(inputs, rows[1], "REJECT", ["RESEARCH_PRIORITY_LOWER"]),
            self._event(inputs, rows[2], "DATA_BLOCKED", ["U3_INCOMPLETE"], row_hash="sha256:" + "0" * 64),
        ]
        _b, _r, _q, line, members = replay(inputs, u4=self._u4_state(inputs, events))
        t4 = by_id(line)["u4_ready_false_ready_share"]
        self.assertEqual((1, 2, 1), (t4["numerator"], t4["denominator"], t4["unparsed_count"]))
        self.assertEqual({rows[0]["ts_code"]: True, rows[1]["ts_code"]: False},
                         members["u4_ready_false_ready_share"])
        self.assertEqual(rt.WITHHELD, t4["level"])

    def test_u4_ready_claim_comes_from_the_reviewed_packet_not_the_deep_queue(self) -> None:
        # QT-C1: a row the human saw as ready=False is not a "ready" machine claim.
        inputs = tiny_inputs({f"0000{i:02d}.SZ": {"红旗闸门": "PASS", "红旗理由": []} for i in range(2)})
        rows = inputs["battery"]["results"]
        events = [self._event(inputs, rows[0], "NO_TRADE", ["U2_NOT_ELIGIBLE"]),
                  self._event(inputs, rows[1], "NO_TRADE", ["U2_NOT_ELIGIBLE"])]
        state = self._u4_state(inputs, events, ready={rows[1]["ts_code"]: False},
                               blocked={rows[1]["ts_code"]: ["NO_POSITIVE_CHANNEL"]})
        _b, _r, _q, line, members = replay(inputs, u4=state)
        # U2_NOT_ELIGIBLE on a packet-ready row is a false-ready label; the packet
        # ready=False row is not in T4 at all.
        self.assertEqual({rows[0]["ts_code"]: True}, members["u4_ready_false_ready_share"])
        # and a missing packet row is unparsed, never read as ready
        del state["packet_rows"][f"sha256:{'p' * 64}|{rows[0]['ts_code']}"]
        _b, _r, _q, line, members = replay(inputs, u4=state)
        self.assertEqual({}, members["u4_ready_false_ready_share"])
        self.assertEqual(1, by_id(line)["u4_ready_false_ready_share"]["unparsed_count"])

    def test_bulk_defer_and_forced_red_flag_reject_are_not_labels(self) -> None:
        # QT-C1: DEFER/HUMAN_JUDGMENT ("其余按审批稿逐票留档") and the ledger-forced
        # REJECT+RED_FLAG_ACTIVE say nothing about ready/COMPLETE: unparsed, never 0 defects.
        inputs = tiny_inputs({f"0000{i:02d}.SZ": {"红旗闸门": "PASS", "红旗理由": []} for i in range(4)})
        rows = inputs["battery"]["results"]
        events = [
            self._event(inputs, rows[0], "DEFER", ["HUMAN_JUDGMENT"]),
            self._event(inputs, rows[1], "REJECT", ["RED_FLAG_ACTIVE"]),
            self._event(inputs, rows[2], "SELECT", ["EVIDENCE_CHAIN_COMPLETE"]),
            self._event(inputs, rows[3], "DEFER", ["QUEUE_CAPACITY"]),
        ]
        state = self._u4_state(inputs, events, ready={rows[1]["ts_code"]: False},
                               blocked={rows[1]["ts_code"]: ["E1_RED_FLAG_REQUIRES_SEPARATE_REVIEW"]})
        _b, _r, _q, line, members = replay(inputs, u4=state)
        self.assertEqual({rows[2]["ts_code"]: False}, members["u4_ready_false_ready_share"])
        self.assertEqual({rows[2]["ts_code"]: False}, members["complete_label_defect_share"])
        t4, t5 = by_id(line)["u4_ready_false_ready_share"], by_id(line)["complete_label_defect_share"]
        self.assertEqual((0, 1, 2), (t4["numerator"], t4["denominator"], t4["unparsed_count"]))
        self.assertEqual((0, 1, 3), (t5["numerator"], t5["denominator"], t5["unparsed_count"]))
        self.assertIsNone(t4["rate"])

    def test_read_u4_decisions_keeps_this_run_and_the_decided_packet_rows(self) -> None:
        # F4 (M8): events from another run never count, even if their row hash matched.
        import u4_decision_ledger as u4

        def event(code, run_id):
            return {"candidate": {"ts_code": code}, "decision_revision": 1, "decision": "SELECT",
                    "source": {"run_id": run_id, "u4_packet_hash": "sha256:" + "a" * 64}}

        state = {
            "current": {("p", "1"): event("000001.SZ", "run-a"), ("p", "2"): event("000002.SZ", "run-b")},
            "intents": {("sha256:" + "a" * 64, 1): {"review_packet": {"ready_pool": [
                {"ts_code": "000001.SZ", "ready": False, "blocked_reasons": ["NO_POSITIVE_CHANNEL"]},
                {"ts_code": "000002.SZ", "ready": True, "blocked_reasons": []}]}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root.joinpath(*rt.U4_LEDGER_REL)
            path.parent.mkdir(parents=True)
            path.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(rt, "_verify_r015", return_value=(True, "head", None)), \
                    mock.patch.object(u4, "_replay_records", return_value=state):
                result = rt.read_u4_decisions(root, "run-a")
        self.assertEqual("OK", result["status"])
        self.assertEqual(["000001.SZ"], [e["candidate"]["ts_code"] for e in result["events"]])
        self.assertEqual({f"sha256:{'a' * 64}|000001.SZ": {"ready": False,
                                                          "blocked_reasons": ["NO_POSITIVE_CHANNEL"]}},
                         result["packet_rows"])

    def _adjudication_ledger(self, root, inputs, queue, rows):
        """rows: [(queue_row, verdict, batch, run_id, closed)] in contract-A shape."""
        path = root.joinpath(*rt.ADJUDICATION_LEDGER_REL)
        path.parent.mkdir(parents=True, exist_ok=True)
        authority = {"u4_admission_authority": False, "changes_machine_verdict": False,
                     "claim_allowed": False, "no_trade_flag": True}
        batches: dict = {}
        # Composition with #392: disagreement_adjudication kinds are typed-only at the
        # writer.  This helper seeds contract-A-shaped records (including forgeries)
        # to prove the reader re-validates them, so it lifts only that writer guard.
        typed_only = getattr(event_ledger, "ADJUDICATION_TYPED_KINDS", frozenset())
        seeding = mock.patch.object(
            event_ledger, "RESERVED_TYPED_KINDS",
            frozenset(getattr(event_ledger, "RESERVED_TYPED_KINDS", frozenset())) - typed_only,
        )
        seeding.start()
        self.addCleanup(seeding.stop)
        for row, verdict, batch, run_id, closed in rows:
            batches.setdefault(batch, {"rows": [], "closed": closed, "run_id": run_id})
            batches[batch]["rows"].append((row, verdict))
        for batch, spec in batches.items():
            batch_hash = hashlib.sha256(batch.encode()).hexdigest()
            human = {"claimed_reviewer": "Junyan", "identity_verification": "UNAVAILABLE",
                     "decided_at": "2026-09-30T01:00:00+00:00",
                     "authorization_text": f"离线裁决批次 {batch_hash[:12]} 由 Junyan 在对话中批准",
                     "authorization_evidence_ref": "conversation:test"}
            for index, (row, verdict) in enumerate(spec["rows"]):
                payload = {"schema": rt.ADJUDICATION_SCHEMA, "batch_id": batch, "run_id": spec["run_id"],
                           "as_of": inputs["as_of"], "information_cutoff": inputs["as_of"],
                           "queue_rows_hash": queue["rows_hash"], "row_id": row["row_id"],
                           "ts_code": row["ts_code"], "disagreement_class": row["disagreement_class"],
                           "human_verdict": verdict, "human_decision": human, "authority": authority}
                event_ledger.append(rt.ADJUDICATION_KIND, f"{batch}-{index}", payload, str(path))
            if spec["closed"]:
                event_ledger.append(rt.ADJUDICATION_CLOSURE_KIND, f"{batch}-c",
                                    {"batch_id": batch, "batch_hash": batch_hash,
                                     "row_ids": [row["row_id"] for row, _v in spec["rows"]]}, str(path))
        seeding.stop()
        return path

    def test_human_confirmed_share_uses_only_closed_batches_bound_to_this_queue(self) -> None:
        inputs = tiny_inputs({"000001.SZ": dict(RED), "000002.SZ": dict(RED)})
        _b, _r, queue, _l, _m = replay(inputs)
        u3 = [row for row in queue["rows"] if row["disagreement_class"] == dq.CLASS_U3_VS_E1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._adjudication_ledger(root, inputs, queue, [
                (u3[0], "MACHINE_VERDICT_REJECTED_STALE_EVIDENCE", "b1", inputs["run_id"], True),
                # an open batch and a batch bound to another run never count
                (u3[1], "MACHINE_VERDICT_CONFIRMED", "b2", inputs["run_id"], False),
                (u3[1], "MACHINE_VERDICT_CONFIRMED", "b3", "other", True),
            ])
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

    def test_control_row_verdicts_never_enter_t3(self) -> None:
        # F1 / QT-C6: control rows' machine side is E1, not the U3 gate.
        inputs = tiny_inputs({"000001.SZ": dict(RED)})
        _b, _r, queue, _l, _m = replay(inputs)
        u3 = [row for row in queue["rows"] if row["disagreement_class"] == dq.CLASS_U3_VS_E1]
        controls = [row for row in queue["rows"] if row["disagreement_class"] == dq.CLASS_CONTROL]
        self.assertEqual(2, len(controls))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._adjudication_ledger(root, inputs, queue, [
                (controls[0], "MACHINE_VERDICT_CONFIRMED", "b1", inputs["run_id"], True),
                (controls[1], "COUNTER_SIDE_REJECTED", "b1", inputs["run_id"], True),
                (u3[0], "MACHINE_VERDICT_REJECTED_STALE_EVIDENCE", "b1", inputs["run_id"], True),
            ])
            state = rt.read_adjudications(root, inputs["run_id"], queue)
            self.assertEqual(3, len(state["labels"]))
            _b, _r, _q, line, members = replay(inputs, adjudication=state)
        t3 = by_id(line)["red_flag_human_confirmed_share"]
        self.assertEqual((0, 1), (t3["numerator"], t3["denominator"]))
        self.assertEqual({"000001.SZ": False}, members["red_flag_human_confirmed_share"])
        self.assertIn("control_rows_adjudicated=2", t3["note"])

    def test_adjudications_failing_the_contract_a_human_boundary_are_not_labels(self) -> None:
        # QT-C6: claimed reviewer, batch-bound offline authorization, evidence ref and
        # information_cutoff are re-checked before a record counts.
        inputs = tiny_inputs({"000001.SZ": dict(RED)})
        _b, _r, queue, _l, _m = replay(inputs)
        u3 = [row for row in queue["rows"] if row["disagreement_class"] == dq.CLASS_U3_VS_E1]
        forgeries = (
            lambda p: p["human_decision"].__setitem__("claimed_reviewer", "someone"),
            lambda p: p["human_decision"].__setitem__("authorization_text", "approved offline, no batch hash"),
            lambda p: p["human_decision"].__setitem__("authorization_evidence_ref", "email:x"),
            lambda p: p.__setitem__("information_cutoff", "20261001"),
        )
        for forge in forgeries:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                original = event_ledger.append

                def forged_append(kind, rid, payload, path, _forge=forge):
                    if kind == rt.ADJUDICATION_KIND:
                        payload = copy.deepcopy(payload)
                        _forge(payload)
                    return original(kind, rid, payload, path)

                with mock.patch.object(event_ledger, "append", forged_append):
                    self._adjudication_ledger(root, inputs, queue, [
                        (u3[0], "MACHINE_VERDICT_CONFIRMED", "b1", inputs["run_id"], True)])
                state = rt.read_adjudications(root, inputs["run_id"], queue)
                self.assertEqual(({}, 1), (state["labels"], state["rejected_records"]))

    def test_e1_data_blocked_rows_are_t2_unparsed_not_denominator(self) -> None:
        # F3 (M11): a bound E1 row that is DATA_BLOCKED is not "E1 disagrees".
        inputs = tiny_inputs({"000001.SZ": dict(RED), "000002.SZ": dict(RED)})
        e1 = json.loads(inputs["e1_raw"].decode("utf-8"))
        for row in e1["rows"]:
            if row["ts_code"] == "000002.SZ":
                row["verdict"] = "DATA_BLOCKED"
        e1["rows_hash"] = fp._hash(e1["rows"])
        for row in inputs["scan"]["rows"]:
            if row["ts_code"] == "000002.SZ":
                row["feature_values"]["verdict"] = "DATA_BLOCKED"
        basis, _r, _q, line, members = replay(inputs, e1_raw=json.dumps(e1).encode("utf-8"))
        self.assertEqual(dq.E1_SAME_AS_OF, basis)
        t2 = by_id(line)["red_flag_cross_model_confirmed_share"]
        self.assertEqual((0, 1, 1), (t2["numerator"], t2["denominator"], t2["unparsed_count"]))
        self.assertEqual({"000001.SZ": False}, members["red_flag_cross_model_confirmed_share"])

    def _macro_dir(self, root: Path, *, run_id: str, as_of: str, bind: bool = True,
                   events_present: bool = True) -> Path:
        macro = root / "macro"
        macro.mkdir()
        events = json.dumps({"run_id": run_id, "data": [
            {"context_id": "a", "consensus": 1.0, "consensus_status": "OK"}]}).encode("utf-8")
        if events_present:
            (macro / "macro_events.json").write_bytes(events)
        digest = hashlib.sha256(events).hexdigest() if bind else "0" * 64
        (macro / "m1c_run_manifest.json").write_text(json.dumps({
            "schema": "ar.macro.m1c_run_manifest", "run_id": run_id, "target_trade_date": as_of,
            "artifacts": {"macro_events.json": digest}}), encoding="utf-8")
        return macro

    def test_macro_manifest_must_be_this_runs_and_hash_its_events(self) -> None:
        # F3 (M7): T7 reads only the same-run M1-C manifest and the bytes it hashes.
        cases = (
            ({}, "OK", None),
            ({"run_id": "another-run"}, "ABSENT", "M1C_MANIFEST_NOT_THIS_RUN"),
            ({"bind": False}, "ABSENT", "MACRO_EVENTS_NOT_BOUND_TO_MANIFEST"),
            ({"events_present": False}, "ABSENT", "MACRO_EVENTS_MISSING"),
        )
        for overrides, status, reason in cases:
            with tempfile.TemporaryDirectory() as tmp:
                kwargs = dict({"run_id": "run-x", "as_of": "20260929"}, **overrides)
                macro = self._macro_dir(Path(tmp), **kwargs)
                result = rt.read_macro(macro, run_id="run-x", as_of="20260929")
                self.assertEqual((status, reason), (result["status"], result["reason"]), overrides)
                if status != "OK":
                    _b, _r, _q, line, _m = replay(tiny_inputs({"000001.SZ": dict(RED)}), macro=result)
                    self.assertEqual(rt.NC_NO_MACRO,
                                     by_id(line)["macro_event_consensus_coverage"]["not_computable_reason"])

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


    def test_rolling_pools_one_line_per_as_of_and_never_this_nights_own_line(self) -> None:
        # QT-C3 / F4 (M9): a re-run with the same run_id, or a sibling run of the same
        # as_of, is replaced by the current line; two runs of one earlier as_of count once.
        current = [rt.metric("news_channel_available_share", numerator=0, denominator=0)]
        current += [rt.metric(mid, not_computable_reason=rt.NC_E1_UNAVAILABLE)
                    for mid in rt.METRIC_IDS if mid != "news_channel_available_share"]
        a = {f"A{i:05d}.SZ": True for i in range(12)}
        b = {f"B{i:05d}.SZ": True for i in range(12)}
        prior = [
            self._record("20260928", "early", {"news_channel_available_share": dict(a)}),
            self._record("20260928", "late", {"news_channel_available_share": dict(b)}),
            self._record("20260929", "sibling", {"news_channel_available_share": dict(a)}),
            self._record("20260929", "me", {"news_channel_available_share": dict(a)}),
        ]
        pooled = rt.rolling({}, current, prior, as_of="20260929", run_id="me")["per_metric"]
        # only 20260928's latest line (b) is pooled: 12 distinct rows, withheld
        self.assertEqual((12, rt.WITHHELD), (pooled["news_channel_available_share"]["distinct_rows"],
                                             pooled["news_channel_available_share"]["level"]))
        self.assertEqual(["late"], [r["run_id"] for r in rt._one_line_per_as_of(prior, as_of="20260929",
                                                                              run_id="me")])


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
            # QT-C8/F7: the class only — never an absolute local path.
            self.assertTrue(result["error"])
            self.assertNotIn("/", result["error"])
            self.assertNotIn(str(tmp), json.dumps(result))

    def _health(self, line):
        return {"run_id": line["run_id"], "as_of": line["as_of"], "research_trust": copy.deepcopy(line)}

    def test_finalize_stages_and_only_acceptance_appends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            line, members = self._line()
            staged = rt.stage_pending_line(root, line, members)
            self.assertEqual("STAGED_PENDING_ACCEPTANCE", staged["status"])
            self.assertEqual(rt.APPEND_POLICY, staged["append_policy"])
            self.assertFalse(rt.ledger_path(root).exists(), "staging never writes the ledger")
            result = rt.accept_pending_line(root, self._health(line))
            self.assertEqual(("APPENDED", 0), (result["status"], result["seq"]))
            self.assertFalse(rt.pending_path(root, line["run_id"]).exists())
            self.assertEqual("PENDING_MISSING", rt.accept_pending_line(root, self._health(line))["status"])

    def test_acceptance_refuses_a_pending_line_that_is_not_the_verified_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            line, members = self._line()
            rt.stage_pending_line(root, line, members)
            # same counts (members stay consistent), different verified bytes
            published = copy.deepcopy(line)
            published["metrics"][5]["note"] = "a different, verified note"
            rt.validate_trust_line(published)
            result = rt.accept_pending_line(root, self._health(published))
            self.assertEqual("PENDING_MISMATCH_NOT_APPENDED", result["status"])
            self.assertFalse(rt.ledger_path(root).exists())
            # members that do not reproduce the counts are refused at staging too
            bad = copy.deepcopy(members)
            bad["news_channel_available_share"] = {}
            self.assertEqual("STAGE_FAILED", rt.stage_pending_line(root, line, bad)["status"])

    def test_staging_refuses_a_line_against_another_nights_e1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            line, members = self._line()
            forged = copy.deepcopy(line)
            forged["source_binding"]["e1_layer_as_of"] = "20260930"
            result = rt.stage_pending_line(Path(tmp), forged, members)
            self.assertEqual("REFUSED_NOT_SAME_RUN", result["status"])
            self.assertFalse(rt.pending_path(Path(tmp), line["run_id"]).exists())


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
            self.assertEqual("STAGED_PENDING_ACCEPTANCE", health["research_trust_ledger"]["status"])
            self.assertNotIn("research_trust", health["battery_coverage"])
            # QT-C3: finalize never appends the durable ledger; it only stages.
            advisory = root / "research_advisory"
            self.assertFalse(rt.ledger_path(advisory).exists())
            pending = json.loads(rt.pending_path(advisory, dagtests.RUN_ID).read_text("utf-8"))
            self.assertEqual(line, pending["trust_line"])
            self.assertEqual(set(red), set(pending["members"]["red_flag_stale_evidence_share"]))

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
            self.assertEqual("STAGE_FAILED", health["research_trust_ledger"]["status"])
            self.assertNotIn("/", health["research_trust_ledger"]["error"])
            self.assertIn("research_trust", health)

    def test_an_advisory_build_failure_is_declared_and_does_not_fail_finalize(self) -> None:
        # F9: the night keeps its U3/U4 health; the failure is a declared status.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            boom = mock.patch.object(rt, "build_finalize_extras", side_effect=KeyError("shape"))
            with boom:
                try:
                    pv, _obs, bundle, health, _red = self._finalize(root)
                except Exception as exc:  # noqa: BLE001 — the advisory side must never fail finalize
                    self.fail(f"finalize failed on an advisory build error: {exc!r}")
            self.assertEqual({"status": "BUILD_FAILED_NOT_STAGED", "error": "KeyError"},
                             {k: health["research_trust_ledger"][k] for k in ("status", "error")})
            self.assertNotIn("research_trust", health)
            stage = json.loads((bundle / "stage_finalize.json").read_text("utf-8"))
            self.assertEqual(set(dag.STAGE3_FILES), set(stage["artifacts"]))
            repo, _durable = self._durable(root, bundle)
            self.verify(health, repo, pv)

    def _res(self, *, finalize="OK", report="COMPLETE", published=True, pv=None):
        manifest = {"artifacts": {}}
        if pv is not None:
            manifest["artifacts"]["public:funnel_health.json"] = hashlib.sha256(
                (pv / "funnel_health.json").read_bytes()).hexdigest()
        return {"run_id": dagtests.RUN_ID, "report": report, "published": published,
                "publication_manifest": manifest,
                "steps": [{"step": "funnel_finalize", "status": finalize}]}

    def test_the_nightly_appends_only_after_an_accepted_published_finalize(self) -> None:
        # QT-C3 / F6: a failed verification, an INCOMPLETE night or an unpublished run
        # leaves no ledger line; an accepted one appends exactly the verified line.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, obs, _bundle, health, _red = self._finalize(root)
            advisory = root / "research_advisory"
            for res in (self._res(finalize="DATA_BLOCKED", pv=pv), self._res(report="INCOMPLETE", pv=pv),
                        self._res(published=False, pv=pv)):
                self.assertEqual("NOT_APPENDED_RUN_NOT_ACCEPTED",
                                 nightly._accept_research_trust_line(res, str(obs), str(pv))["status"])
            self.assertFalse(rt.ledger_path(advisory).exists())
            # a published health that is not the manifest-registered bytes is refused
            self.assertEqual("PENDING_MISMATCH_NOT_APPENDED",
                             nightly._accept_research_trust_line(self._res(), str(obs), str(pv))["status"])
            self.assertFalse(rt.ledger_path(advisory).exists())
            result = nightly._accept_research_trust_line(self._res(pv=pv), str(obs), str(pv))
            self.assertEqual("APPENDED", result["status"])
            records, error = rt.read_prior_lines(advisory)
            self.assertIsNone(error)
            self.assertEqual([dagtests.RUN_ID], [r["run_id"] for r in records])
            self.assertEqual(health["research_trust"], records[0]["trust_line"])

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
            with self.assertRaisesRegex(ValueError, "without a declared trust-line staging status"):
                self.verify(forged, repo, pv)

            forged = copy.deepcopy(health)
            forged["research_trust_ledger"]["status"] = "APPENDED"
            with self.assertRaisesRegex(ValueError, "outside the finalize vocabulary"):
                self.verify(forged, repo, pv)

    def test_verifier_refuses_a_trust_line_resealed_with_another_runs_binding(self) -> None:
        # F3 (M4): identity fields right, source_binding pointing at other evidence.
        for key in ("battery_rows_hash", "queue_rows_hash", "e1_layer_rows_hash", "candidate_manifest_hash"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                pv, _obs, bundle, health, _red = self._finalize(root)
                repo, durable = self._durable(root, bundle)
                line = json.loads((durable / rt.TRUST_FILE).read_text("utf-8"))
                line["source_binding"][key] = "0" * 64
                rt.validate_trust_line(line)
                restamp_stage(durable, "finalize", rt.TRUST_FILE, line)
                with self.assertRaisesRegex(ValueError, "source_binding", msg=key):
                    self.verify(dict(health, research_trust=line), repo, pv)

    def test_verifier_refuses_a_recorded_e1_basis_that_does_not_replay(self) -> None:
        # F4 (M5): recorded SAME_AS_OF, measured UNAVAILABLE (the layer is gone).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, _obs, bundle, health, _red = self._finalize(root)
            repo, _durable = self._durable(root, bundle)
            (pv / "e1_event_layer.json").unlink()
            with self.assertRaisesRegex(ValueError, "E1 basis does not replay"):
                self.verify(health, repo, pv)

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

    def test_a_half_pair_of_files_and_keys_is_refused(self) -> None:
        # F5 (M17): one finalize extra + one health key is not a valid (1,1) night.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, _obs, bundle, health, _red = self._finalize(root)
            repo, durable = self._durable(root, bundle)
            stage_path = durable / "stage_finalize.json"
            stage = json.loads(stage_path.read_text("utf-8"))
            del stage["artifacts"][rt.TRUST_FILE]
            stage.pop("stage_hash")
            stage["stage_hash"] = fp._hash(stage)
            stage_path.write_text(json.dumps(stage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (durable / rt.TRUST_FILE).unlink()
            half = {k: v for k, v in health.items() if k != "research_trust"}
            with self.assertRaisesRegex(ValueError, "not bound together"):
                self.verify(half, repo, pv)

    def test_dropping_both_files_and_keys_cannot_bypass_the_recompute(self) -> None:
        # QT-C7: a receipt from this code declares research_trust_ledger; (0,0) with a
        # staging status other than BUILD_FAILED_NOT_STAGED is refused.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pv, _obs, bundle, health, _red = self._finalize(root)
            repo, durable = self._durable(root, bundle)
            stage_path = durable / "stage_finalize.json"
            stage = json.loads(stage_path.read_text("utf-8"))
            for name in dag.STAGE3_OPTIONAL_FILES:
                del stage["artifacts"][name]
                (durable / name).unlink()
            stage.pop("stage_hash")
            stage["stage_hash"] = fp._hash(stage)
            stage_path.write_text(json.dumps(stage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            dropped = {k: v for k, v in health.items() if k not in {"disagreement_summary", "research_trust"}}
            with self.assertRaisesRegex(ValueError, "extras are missing"):
                self.verify(dropped, repo, pv)

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

    def test_u4_packet_refuses_half_of_the_optional_pair(self) -> None:
        # F5: the queue without the trust line (or vice versa) is not a valid finalize stage.
        import test_u4_pre_decision_runtime as runtime
        import u4_pre_decision as pre

        for name in dag.STAGE3_OPTIONAL_FILES:
            extra = {name: {"generated_at": runtime.GENERATED_AT, "fixture": name}}
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
