"""Offline checks for the read-only research trust line consumer projection.

The producer is not imported: every line here is synthetic JSON shaped by the
shared contract (T) ``ar.research_trust_line`` 1.0.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.research_funnel import research_trust_view as view

RUN_ID = "20260929_150751_test"
AS_OF = "20260929"
FORBIDDEN = re.compile(r"(?i)(return|hit|alpha|pnl|score|composite)")


def metric(metric_id, kind, numerator, denominator, level, reliance, rate="auto", reason=None):
    tier, direction, threshold = view.METRICS[metric_id]
    if rate == "auto":
        rate = None
        if level in view.RATED_LEVELS:
            rate = round(numerator / denominator, 4)
    return {"metric_id": metric_id, "kind": kind, "numerator": numerator,
            "denominator": denominator, "unparsed_count": 0, "rate": rate,
            "min_n": 20, "threshold": threshold, "direction": direction,
            "level": level, "not_computable_reason": reason, "reliance": reliance,
            "note": f"{tier} synthetic"}


def line(**overrides):
    """A 9/29-shaped line: T1 43/46, T2 0/46, T6 0/181, T7 0/25, T3-T5 not rated."""
    value = {
        "schema": "ar.research_trust_line", "schema_version": "1.0",
        "as_of": AS_OF, "run_id": RUN_ID, "generated_at": "2026-09-29T14:20:00Z",
        "e1_basis": "SAME_RUN_MANIFEST",
        "source_binding": {"candidate_manifest_hash": "sha256:" + "1" * 64,
                           "battery_rows_hash": "sha256:" + "2" * 64,
                           "e1_layer_rows_hash": "sha256:" + "3" * 64,
                           "e1_layer_as_of": AS_OF},
        "metrics": [
            metric("red_flag_stale_evidence_share", "MACHINE_VS_MACHINE", 43, 46,
                   "MISSES_BAR", "ADVISORY_SHOW_STALE_SHARE"),
            metric("red_flag_cross_model_confirmed_share", "MACHINE_VS_MACHINE", 0, 46,
                   "MISSES_BAR", "ADVISORY_SHOW_STALE_SHARE"),
            metric("red_flag_human_confirmed_share", "HUMAN_VS_MACHINE", None, None,
                   "NOT_COMPUTABLE", "UNRATED", reason="LEDGER_FORCES_AGREEMENT"),
            metric("u4_ready_false_ready_share", "HUMAN_VS_MACHINE", None, None,
                   "NOT_COMPUTABLE", "UNRATED", reason="NO_HUMAN_LABELS_FOR_RUN"),
            metric("complete_label_defect_share", "HUMAN_VS_MACHINE", 1, 12,
                   "RATE_WITHHELD_N_BELOW_MIN", "UNRATED"),
            metric("news_channel_available_share", "COVERAGE", 0, 181,
                   "MISSES_BAR", "COVERAGE_GAP_DISCLOSE"),
            metric("macro_event_consensus_coverage", "COVERAGE", 0, 25,
                   "MISSES_BAR", "COVERAGE_GAP_DISCLOSE"),
        ],
        "rolling": {"window_runs": 20, "per_metric": {
            "red_flag_stale_evidence_share": {"distinct_rows": 46, "pooled_numerator": 43,
                                              "pooled_denominator": 46, "level": "MISSES_BAR"},
            "news_channel_available_share": {"distinct_rows": 5, "pooled_numerator": 0,
                                             "pooled_denominator": 5,
                                             "level": "RATE_WITHHELD_N_BELOW_MIN"},
        }},
        "claim_status": "DESCRIPTIVE_ONLY", "retention_status": "LOCAL_ONLY_UNBACKED",
        "authority": {"claim_allowed": False, "performance_claim": None,
                      "u4_selection_authority": False},
    }
    value.update(overrides)
    return value


def health(trust="default"):
    value = {"run_id": RUN_ID, "as_of": AS_OF, "status": "PARTIAL"}
    if trust == "default":
        value["research_trust"] = line()
    elif trust is not None:
        value["research_trust"] = trust
    return value


def by_id(result):
    return {row["metric_id"]: row for row in result["metrics"]}


def keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from keys(item)


class ResearchTrustViewTest(unittest.TestCase):
    def test_valid_line_projects_counts_levels_and_reliance(self):
        result = view.project(health(), RUN_ID, AS_OF)
        self.assertEqual("PRESENT", result["status"])
        rows = by_id(result)
        self.assertEqual(["T1", "T2", "T3", "T4", "T5", "T6", "T7"],
                         [row["tier"] for row in result["metrics"]])
        t1 = rows["red_flag_stale_evidence_share"]
        self.assertEqual((43, 46, "MISSES_BAR", "ADVISORY_SHOW_STALE_SHARE"),
                         (t1["numerator"], t1["denominator"], t1["level"], t1["reliance"]))
        self.assertAlmostEqual(0.9348, t1["rate"], places=3)
        self.assertEqual("LEDGER_FORCES_AGREEMENT",
                         rows["red_flag_human_confirmed_share"]["not_computable_reason"])
        self.assertEqual([], result["missing_metric_ids"])
        self.assertEqual("DESCRIPTIVE_ONLY", result["claim_status"])
        self.assertEqual({"claim_allowed": False, "performance_claim": None,
                          "u4_selection_authority": False}, result["authority"])

    def test_absent_line_is_not_produced_not_zero(self):
        for trust in (None,):
            result = view.project(health(trust=trust), RUN_ID, AS_OF)
            self.assertEqual("NOT_PRODUCED", result["status"])
            self.assertIsNone(result["metrics"])
            self.assertIsNone(result["rolling"])
        explicit_null = view.project({"run_id": RUN_ID, "as_of": AS_OF,
                                      "research_trust": None}, RUN_ID, AS_OF)
        self.assertEqual("NOT_PRODUCED", explicit_null["status"])

    def test_withheld_rate_stays_null_below_min_sample(self):
        result = view.project(health(), RUN_ID, AS_OF)
        self.assertEqual("PRESENT", result["status"])
        rows = by_id(result)
        withheld = rows["complete_label_defect_share"]
        self.assertIsNone(withheld["rate"])
        self.assertEqual((1, 12), (withheld["numerator"], withheld["denominator"]))
        self.assertEqual("RATE_WITHHELD_N_BELOW_MIN", withheld["level"])
        bad = line()
        bad["metrics"][4] = metric("complete_label_defect_share", "HUMAN_VS_MACHINE", 1, 12,
                                   "MEETS_BAR", "TRUSTED_FOR_TRIAGE")
        result = view.project(health(bad), RUN_ID, AS_OF)
        self.assertEqual("REFUSED", result["status"])
        self.assertIn("RATE_SHOWN_BELOW_MIN_SAMPLE", result["reason"])
        self.assertIsNone(result["metrics"])

    def test_rolling_level_needs_distinct_rows_not_row_nights(self):
        bad = line()
        bad["rolling"]["per_metric"]["news_channel_available_share"]["level"] = "MISSES_BAR"
        result = view.project(health(bad), RUN_ID, AS_OF)
        self.assertEqual("REFUSED", result["status"])
        self.assertIn("rolling.news_channel_available_share", result["reason"])

    def test_level_is_recomputed_from_counts(self):
        bad = line()
        bad["metrics"][0]["level"] = "MEETS_BAR"
        bad["metrics"][0]["reliance"] = "TRUSTED_FOR_TRIAGE"
        result = view.project(health(bad), RUN_ID, AS_OF)
        self.assertEqual("REFUSED", result["status"])
        self.assertIn("LEVEL_DIFFERS_FROM_COUNTS", result["reason"])

    def test_rate_must_match_counts(self):
        bad = line()
        bad["metrics"][0]["rate"] = 0.10
        result = view.project(health(bad), RUN_ID, AS_OF)
        self.assertEqual("REFUSED", result["status"])
        self.assertIn("RATE_DIFFERS_FROM_COUNTS", result["reason"])

    def test_performance_shaped_keys_refuse_the_line(self):
        for mutate in (
            lambda value: value.update(hit_rate=0.5),
            lambda value: value["metrics"][0].update(alpha_note="x"),
            lambda value: value["authority"].update(composite=None),
            lambda value: value["source_binding"].update(forward_return_hash="sha256:" + "0" * 64),
        ):
            bad = line()
            mutate(bad)
            result = view.project(health(bad), RUN_ID, AS_OF)
            self.assertEqual("REFUSED", result["status"])
            self.assertIn("FORBIDDEN_KEY_PRESENT", result["reason"])

    def test_projection_itself_carries_no_performance_shaped_key(self):
        for trust in ("default", None, {"schema": "other"}):
            result = view.project(health(trust), RUN_ID, AS_OF)
            self.assertEqual([], [key for key in keys(result) if FORBIDDEN.search(key)])

    def test_line_from_another_run_is_refused(self):
        for override in ({"run_id": "20260928_150000_other"}, {"as_of": "20260928"}):
            result = view.project(health(line(**override)), RUN_ID, AS_OF)
            self.assertEqual("REFUSED", result["status"])
            self.assertEqual("RUN_BINDING_MISMATCH", result["reason"])

    def test_authority_or_claim_flags_refuse_the_line(self):
        for override in (
            {"authority": {"claim_allowed": True, "performance_claim": None,
                           "u4_selection_authority": False}},
            {"authority": {"claim_allowed": False, "performance_claim": None,
                           "u4_selection_authority": True}},
            {"claim_status": "VALIDATED"},
        ):
            result = view.project(health(line(**override)), RUN_ID, AS_OF)
            self.assertEqual("REFUSED", result["status"])
            self.assertEqual("AUTHORITY_OR_CLAIM_INVALID", result["reason"])

    def test_closed_vocabularies_and_contract_constants(self):
        cases = [
            lambda value: value.update(schema_version="0.9"),
            lambda value: value.update(e1_basis="RETRO_NOT_SAME_NIGHT"),
            lambda value: value.update(retention_status="DURABLE"),
            lambda value: value["metrics"][0].update(threshold=0.5),
            lambda value: value["metrics"][0].update(min_n=5),
            lambda value: value["metrics"][0].update(reliance="SKIP_REVIEW"),
            lambda value: value["metrics"][2].update(not_computable_reason=None),
            lambda value: value["metrics"][0].update(numerator=True),
            lambda value: value["metrics"].append(copy.deepcopy(value["metrics"][0])),
            lambda value: value["metrics"][0].update(metric_id="red_flag_new_metric"),
        ]
        for mutate in cases:
            bad = line()
            mutate(bad)
            self.assertEqual("REFUSED", view.project(health(bad), RUN_ID, AS_OF)["status"])

    def test_unavailable_e1_cannot_carry_e1_counts(self):
        bad = line(e1_basis="UNAVAILABLE")
        bad["source_binding"].update(e1_layer_rows_hash=None, e1_layer_as_of=None)
        result = view.project(health(bad), RUN_ID, AS_OF)
        self.assertEqual("REFUSED", result["status"])
        self.assertIn("E1_UNAVAILABLE_BUT_COUNTED", result["reason"])

    def unavailable_line(self):
        value = line(e1_basis="UNAVAILABLE")
        value["source_binding"].update(e1_layer_rows_hash=None, e1_layer_as_of=None)
        for index, metric_id in ((0, "red_flag_stale_evidence_share"),
                                 (1, "red_flag_cross_model_confirmed_share")):
            value["metrics"][index] = metric(metric_id, "MACHINE_VS_MACHINE", None, None,
                                             "NOT_COMPUTABLE", "UNRATED",
                                             reason="E1_UNAVAILABLE")
        return value

    def test_e1_layer_must_be_from_this_run(self):
        # m2: a same-run basis must name this as_of; a stale E1 layer is refused.
        for as_of in ("20260901", None):
            bad = line(e1_basis="SAME_AS_OF")
            bad["source_binding"]["e1_layer_as_of"] = as_of
            result = view.project(health(bad), RUN_ID, AS_OF)
            self.assertEqual(("REFUSED", "E1_BINDING_MISMATCH"),
                             (result["status"], result["reason"]))
        missing = line()
        missing["source_binding"].pop("e1_layer_as_of")
        self.assertEqual("E1_BINDING_MISMATCH", view.project(health(missing), RUN_ID, AS_OF)["reason"])
        # UNAVAILABLE binds no E1 layer at all.
        self.assertEqual("PRESENT", view.project(health(self.unavailable_line()), RUN_ID, AS_OF)["status"])
        bad = self.unavailable_line()
        bad["source_binding"]["e1_layer_rows_hash"] = "sha256:" + "3" * 64
        result = view.project(health(bad), RUN_ID, AS_OF)
        self.assertEqual(("REFUSED", "E1_BINDING_MISMATCH"), (result["status"], result["reason"]))

    def test_reliance_is_derived_from_level_and_family(self):
        # M1: a withheld / not-computable / missed rate can never read as trusted,
        # and a coverage label cannot sit on a red-flag metric (or vice versa).
        ok = line()
        ok["metrics"][0] = metric("red_flag_stale_evidence_share", "MACHINE_VS_MACHINE", 2, 46,
                                  "MEETS_BAR", "TRUSTED_FOR_TRIAGE")
        result = view.project(health(ok), RUN_ID, AS_OF)
        self.assertEqual("PRESENT", result["status"])
        self.assertEqual("TRUSTED_FOR_TRIAGE",
                         by_id(result)["red_flag_stale_evidence_share"]["reliance"])
        cases = [
            (4, metric("complete_label_defect_share", "HUMAN_VS_MACHINE", 5, 10,
                       "RATE_WITHHELD_N_BELOW_MIN", "TRUSTED_FOR_TRIAGE")),
            (2, metric("red_flag_human_confirmed_share", "HUMAN_VS_MACHINE", None, None,
                       "NOT_COMPUTABLE", "TRUSTED_FOR_TRIAGE", reason="LEDGER_FORCES_AGREEMENT")),
            (0, metric("red_flag_stale_evidence_share", "MACHINE_VS_MACHINE", 43, 46,
                       "MISSES_BAR", "TRUSTED_FOR_TRIAGE")),
            (0, metric("red_flag_stale_evidence_share", "MACHINE_VS_MACHINE", 2, 46,
                       "MEETS_BAR", "COVERAGE_HONEST")),
            (5, metric("news_channel_available_share", "COVERAGE", 180, 181,
                       "MEETS_BAR", "TRUSTED_FOR_TRIAGE")),
            (5, metric("news_channel_available_share", "COVERAGE", 0, 181,
                       "MISSES_BAR", "UNRATED")),
            (6, metric("macro_event_consensus_coverage", "COVERAGE", 1, 5,
                       "RATE_WITHHELD_N_BELOW_MIN", "COVERAGE_GAP_DISCLOSE")),
        ]
        for index, row in cases:
            bad = line()
            bad["metrics"][index] = row
            result = view.project(health(bad), RUN_ID, AS_OF)
            self.assertEqual("REFUSED", result["status"], row)
            self.assertIn("RELIANCE_DIFFERS_FROM_LEVEL", result["reason"])
            self.assertIsNone(result["metrics"])
        drift = line()
        drift["metrics"][5]["kind"] = "MACHINE_VS_MACHINE"
        self.assertIn("KIND_DRIFT", view.project(health(drift), RUN_ID, AS_OF)["reason"])

    def test_not_computable_metric_carries_no_counts(self):
        # TI-5 / m3: 0/0 or 43/46 beside 不可算 reads like a measured value.
        for counts in ((0, 0), (43, 46), (None, 46)):
            bad = line()
            bad["metrics"][2]["numerator"], bad["metrics"][2]["denominator"] = counts
            result = view.project(health(bad), RUN_ID, AS_OF)
            self.assertEqual("REFUSED", result["status"], counts)
            self.assertIn("NOT_COMPUTABLE_WITH_COUNTS", result["reason"])

    def test_rolling_pools_distinct_rows_not_row_nights(self):
        # m1: sticky rows recurring nightly must not manufacture a sample.
        for pooled in ({"distinct_rows": 20, "pooled_numerator": 10, "pooled_denominator": 400,
                        "level": "MEETS_BAR"},
                       {"distinct_rows": 46, "pooled_numerator": 47, "pooled_denominator": 46,
                        "level": "MISSES_BAR"},
                       {"distinct_rows": 46, "pooled_numerator": None, "pooled_denominator": 46,
                        "level": "NOT_COMPUTABLE"}):
            bad = line()
            bad["rolling"]["per_metric"]["red_flag_stale_evidence_share"] = pooled
            result = view.project(health(bad), RUN_ID, AS_OF)
            self.assertEqual("REFUSED", result["status"], pooled)
            self.assertIn("ROLLING_NOT_DISTINCT_ROWS", result["reason"])
        ok = line()
        ok["rolling"]["per_metric"]["macro_event_consensus_coverage"] = {
            "distinct_rows": 0, "pooled_numerator": 0, "pooled_denominator": 0,
            "level": "NOT_COMPUTABLE"}
        self.assertEqual("PRESENT", view.project(health(ok), RUN_ID, AS_OF)["status"])

    def test_each_rate_check_refuses_on_its_own(self):
        # TI-3: one case per consumer check, asserted by reason.
        def refusal(value):
            result = view.project(health(value), RUN_ID, AS_OF)
            return result["status"], (result["reason"] or "").split(":", 1)[0]

        rated_null = line()
        rated_null["metrics"][0]["rate"] = None
        self.assertEqual(("REFUSED", "RATED_WITHOUT_RATE"), refusal(rated_null))
        withheld_big = line()
        withheld_big["metrics"][0].update(level="RATE_WITHHELD_N_BELOW_MIN", rate=None,
                                          reliance="UNRATED")
        self.assertEqual(("REFUSED", "RATE_WITHHELD_AT_OR_ABOVE_MIN_SAMPLE"),
                         refusal(withheld_big))
        for value in (1.5, -0.1, float("nan"), float("inf")):
            bad = line()
            bad["metrics"][0]["rate"] = value
            self.assertEqual(("REFUSED", "RATE_INVALID"), refusal(bad), value)
        for value in (1, ["x"], {"a": "b"}):
            bad = line()
            bad["source_binding"]["battery_rows_hash"] = value
            result = view.project(health(bad), RUN_ID, AS_OF)
            self.assertEqual(("REFUSED", "SOURCE_BINDING_INVALID"),
                             (result["status"], result["reason"]), value)

    def test_deeply_nested_line_is_refused_not_raised(self):
        # m5: project() never raises, even on a pathological nesting depth.
        deep = {}
        cursor = deep
        for _ in range(3000):
            cursor["x"] = {}
            cursor = cursor["x"]
        bad = line()
        bad["source_binding"] = deep
        result = view.project(health(bad), RUN_ID, AS_OF)
        self.assertEqual("REFUSED", result["status"])
        self.assertTrue(result["reason"].startswith("LINE_SHAPE_INVALID"))

    def test_missing_metrics_are_listed_not_zeroed(self):
        partial = line()
        partial["metrics"] = partial["metrics"][:2]
        partial["rolling"]["per_metric"].pop("news_channel_available_share")
        result = view.project(health(partial), RUN_ID, AS_OF)
        self.assertEqual("PRESENT", result["status"])
        self.assertEqual(["complete_label_defect_share", "macro_event_consensus_coverage",
                          "news_channel_available_share", "red_flag_human_confirmed_share",
                          "u4_ready_false_ready_share"], sorted(result["missing_metric_ids"]))
        self.assertEqual(2, len(result["metrics"]))

    def test_projection_never_raises_on_malformed_input(self):
        for trust in ([], "x", {"schema": "ar.research_trust_line", "schema_version": "1.0"},
                      line(metrics=[{"metric_id": None}]), line(rolling=None)):
            self.assertEqual("REFUSED", view.project(health(trust), RUN_ID, AS_OF)["status"])
        self.assertEqual("REFUSED", view.project(None, RUN_ID, AS_OF)["status"])


class TrustLineUiHelperTest(unittest.TestCase):
    def call(self, expression):
        module = (ROOT / "tools/nonprod_workbench/ui/trust-line-view.mjs").as_uri()
        script = (f"import * as v from {json.dumps(module)};"
                  f"console.log(JSON.stringify({expression}));")
        result = subprocess.run(["node", "--input-type=module", "-e", script],
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_withheld_and_not_computable_rates_render_as_text_not_zero(self):
        self.assertEqual("— (n<20)", self.call(
            "v.rateText({rate:null,level:'RATE_WITHHELD_N_BELOW_MIN',min_n:20})"))
        self.assertEqual("不可算 · LEDGER_FORCES_AGREEMENT", self.call(
            "v.rateText({rate:null,level:'NOT_COMPUTABLE',"
            "not_computable_reason:'LEDGER_FORCES_AGREEMENT',min_n:20})"))
        self.assertEqual("93.5%", self.call(
            "v.rateText({rate:0.9348,level:'MISSES_BAR',min_n:20})"))
        self.assertEqual("— / —", self.call("v.countText({numerator:null,denominator:null})"))
        self.assertEqual("— / —", self.call(
            "v.countText({numerator:0,denominator:0,level:'NOT_COMPUTABLE'})"))
        self.assertEqual("0 / 181", self.call("v.countText({numerator:0,denominator:181})"))

    def test_levels_are_text_chips_never_green(self):
        chips = self.call("['MEETS_BAR','MISSES_BAR','RATE_WITHHELD_N_BELOW_MIN',"
                          "'NOT_COMPUTABLE'].map(v.levelChip)")
        self.assertEqual(["neutral", "amber", "neutral", "neutral"],
                         [chip["tone"] for chip in chips])
        self.assertTrue(all(level in chip["text"] for level, chip in zip(
            ["MEETS_BAR", "MISSES_BAR", "RATE_WITHHELD_N_BELOW_MIN", "NOT_COMPUTABLE"], chips)))

    def test_absent_trust_line_says_not_produced(self):
        self.assertEqual("NOT_PRODUCED", self.call(
            "v.trustLineStatus({status:'NOT_PRODUCED'}).value"))
        self.assertEqual("NOT_EVALUATED", self.call("v.trustLineStatus(undefined).value"))

    def test_desk_headline_shows_run_completeness_and_data_quality(self):
        pairs = self.call("v.runQualityPairs({report:'COMPLETE',data_quality:'DATA_BLOCKED',"
                          "research_data_quality:'DATA_BLOCKED'})")
        self.assertEqual([["运行完整性", "COMPLETE"], ["数据质量", "DATA_BLOCKED"],
                          ["研究数据质量", "DATA_BLOCKED"]], pairs)
        self.assertEqual([["运行完整性", "NOT_OBSERVED"], ["数据质量", "UNAVAILABLE"],
                          ["研究数据质量", "UNAVAILABLE"]], self.call("v.runQualityPairs({})"))
        self.assertEqual("0 FILE_BINDING_ISSUES", self.call("v.fileBindingText({issues:[]})"))

    def test_workspace_renders_quality_beside_completeness(self):
        source = (ROOT / "tools/nonprod_workbench/ui/workspace.jsx").read_text(encoding="utf-8")
        self.assertNotIn("<strong>{attempt.report || '未观察'}</strong>", source)
        self.assertNotIn("ISSUES` : 'NOT_OBSERVED'", source)
        self.assertEqual(2, source.count("<RunQuality attempt={attempt} />"))
        self.assertIn("attempt.data_quality", source)
        self.assertIn("<TrustLine trust={quality.trust_line} />", source)
        self.assertIn("只读计数，不等于自动轮验收或研究批准", source)
        # TI-2: the table cells go through the withheld-aware helpers, and the
        # metrics table renders only for a PRESENT line (REFUSED has no metrics).
        for wiring in ("<td>{rateText(m)}</td>", "<td>{countText(m)}</td>",
                       "<Chip chip={levelChip(m.level)} />",
                       "<td>{relianceText(m.reliance)}</td>",
                       "trust?.status === 'PRESENT' ?",
                       "level: r.level })"):
            self.assertIn(wiring, source)
        self.assertNotIn("toFixed", source.split("function TrustLine", 1)[1].split("function Table", 1)[0])

    def test_refused_and_not_produced_lines_are_not_neutral(self):
        module = (ROOT / "tools/nonprod_workbench/ui/status-tone.mjs").as_uri()
        script = (f"import {{ statusTone }} from {json.dumps(module)};"
                  "console.log(JSON.stringify(['REFUSED','NOT_PRODUCED','NOT_EVALUATED',"
                  "'PRESENT / DESCRIPTIVE_ONLY'].map(statusTone)));")
        result = subprocess.run(["node", "--input-type=module", "-e", script],
                                capture_output=True, text=True, check=True)
        self.assertEqual(["red", "amber", "amber", "neutral"], json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main(verbosity=2)
