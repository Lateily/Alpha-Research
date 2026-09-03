#!/usr/bin/env python3
from __future__ import annotations

import copy
import io
import json
import runpy
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FUNNEL = ROOT / "experiments" / "research_funnel"
if str(FUNNEL) not in sys.path:
    sys.path.insert(0, str(FUNNEL))

import knowledge_cards as cards  # noqa: E402


CARD_DIR = ROOT / "data" / "knowledge_cards"
COMMITTED_CARDS = CARD_DIR / "semiconductor_materials.json"
COMMITTED_SCHEMA = CARD_DIR / "knowledge_card.schema.json"
MIGRATED_VALIDATOR = CARD_DIR / "validate_cards.py"


def _card(
    *,
    card_id: str = "SEMI_MAT_900",
    status: str = "REVIEWED",
    logic_type: str = "THRESHOLD",
) -> dict:
    logic = {
        "type": logic_type,
        "positive_if": "Structured source observation meets the display threshold.",
        "negative_if": "Structured source observation does not meet the display threshold.",
        "lookback": "fixture",
        "threshold": 10.0,
    }
    if logic_type == "STAGE_LADDER":
        logic["stages"] = ["SAMPLE", "VERIFIED", "BATCH"]
        logic["threshold"] = "fixture_unvalidated"
    elif logic_type != "THRESHOLD":
        logic["threshold"] = "fixture_unvalidated"
    return {
        "card_id": card_id,
        "sub_sector": "MATERIALS",
        "variable": "Fixture variable",
        "why_it_matters": "Long enough fixture explanation for strict validation.",
        "data_source": {
            "availability": "SEMI",
            "primary": "Frozen fixture",
            "tushare_api": None,
            "tushare_field": None,
            "manual_required": True,
        },
        "judgment_logic": logic,
        "evidence_tier": "E1",
        "literature": ["Frozen fixture source"],
        "falsification": "A contrary frozen observation falsifies this fixture.",
        "channel_binding": ["LLM_MUST_CHECK"],
        "status": status,
        "authored_by": "Fixture author",
        "reviewed_by": None if status == "DRAFT" else "Junyan",
        "as_of": "20260903",
    }


class KnowledgeCardTests(unittest.TestCase):
    def test_committed_table_contains_23_reviewed_cards(self) -> None:
        loaded = cards.load_cards(COMMITTED_CARDS)
        self.assertEqual(23, len(loaded))
        self.assertEqual(23, len(cards.participating_cards(loaded)))
        self.assertEqual({"REVIEWED"}, {card["status"] for card in loaded})
        self.assertEqual(23, len({card["card_id"] for card in loaded}))
        self.assertEqual(
            cards.LOGIC_TYPES,
            {card["judgment_logic"]["type"] for card in loaded},
        )

    def test_migrated_schema_validator_and_runtime_accept_the_reviewed_table(self) -> None:
        schema = json.loads(COMMITTED_SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(2, schema["properties"]["variable"]["minLength"])
        self.assertEqual(20, schema["properties"]["why_it_matters"]["minLength"])
        self.assertEqual(10, schema["properties"]["falsification"]["minLength"])
        migrated = runpy.run_path(str(MIGRATED_VALIDATOR))
        loaded = json.loads(COMMITTED_CARDS.read_text(encoding="utf-8"))
        source_errors = [
            error
            for index, card in enumerate(loaded)
            for error in migrated["check"](card, index)
        ]
        self.assertEqual([], source_errors)
        cards.validate_cards(loaded)

    def test_schema_minimum_text_lengths_are_enforced(self) -> None:
        for field, value in (
            ("variable", "x"),
            ("why_it_matters", "too short"),
            ("falsification", "short"),
        ):
            with self.subTest(field=field):
                card = _card()
                card[field] = value
                with self.assertRaisesRegex(cards.KnowledgeCardError, "length >="):
                    cards.validate_card(card)

    def test_empty_table_leaves_full_chain_hash_unchanged(self) -> None:
        payload = {"schema": "fixture.chain", "rows": [{"ts_code": "000001.SZ"}]}
        before = cards.canonical_hash(payload)
        after = cards.attach_evaluations(payload, [], {})
        self.assertIs(payload, after)
        self.assertEqual(before, cards.canonical_hash(after))

    def test_draft_card_does_not_participate(self) -> None:
        draft = _card(status="DRAFT")
        payload = {"schema": "fixture.chain", "rows": []}
        self.assertEqual([], cards.participating_cards([draft]))
        self.assertIs(payload, cards.attach_evaluations(payload, [draft], {}))

    def test_retired_card_does_not_participate(self) -> None:
        retired = _card(status="RETIRED")
        self.assertEqual([], cards.participating_cards([retired]))

    def test_threshold_evaluation_recomputes_from_source_value(self) -> None:
        card = _card()
        row = {"value": 12.0, "comparison_unvalidated": "BELOW"}
        result = cards.evaluate(card, row)
        self.assertEqual("COMPLETE", result["status"])
        self.assertEqual("AT_OR_ABOVE", result["result"]["comparison_unvalidated"])
        self.assertEqual(12.0, result["result"]["observed"])
        self.assertTrue(result["display_only"])
        self.assertFalse(result["thresholds_validated"])

    def test_all_five_logic_types_derive_deterministic_observations(self) -> None:
        fixtures = [
            (_card(card_id="SEMI_MAT_901"), {"value": 9.0}, "comparison_unvalidated", "BELOW"),
            (
                _card(card_id="SEMI_MAT_902", logic_type="TREND"),
                {"series": [2.0, 4.0, 3.0]},
                "direction_unvalidated",
                "UP",
            ),
            (
                _card(card_id="SEMI_MAT_903", logic_type="STAGE_LADDER"),
                {"previous_stage": "SAMPLE", "current_stage": "BATCH"},
                "movement_unvalidated",
                2,
            ),
            (
                _card(card_id="SEMI_MAT_904", logic_type="RATIO_VS_PEER"),
                {"value": 12.0, "peer_value": 8.0},
                "ratio_unvalidated",
                1.5,
            ),
            (
                _card(card_id="SEMI_MAT_905", logic_type="CYCLE_POSITION"),
                {"value": 3.0, "history": [1.0, 2.0, 3.0, 4.0]},
                "percentile_unvalidated",
                62.5,
            ),
        ]
        for card, row, key, expected in fixtures:
            with self.subTest(logic_type=card["judgment_logic"]["type"]):
                first = cards.evaluate(card, row)
                second = cards.evaluate(copy.deepcopy(card), copy.deepcopy(row))
                self.assertEqual(first, second)
                self.assertEqual("COMPLETE", first["status"])
                self.assertEqual(expected, first["result"][key])

    def test_reviewed_prose_threshold_is_explicitly_data_blocked(self) -> None:
        card = _card()
        card["judgment_logic"]["threshold"] = "v0_unvalidated"
        result = cards.evaluate(card, {"value": 12.0})
        self.assertEqual("DATA_BLOCKED", result["status"])
        self.assertEqual(["UNENCODED_THRESHOLD"], result["reason_codes"])
        self.assertIsNone(result["result"])

    def test_missing_active_row_is_not_silently_omitted(self) -> None:
        card = _card()
        output = cards.attach_evaluations({"schema": "fixture.chain"}, [card], {})
        self.assertEqual(1, len(output["knowledge_card_evidence"]))
        self.assertEqual("DATA_BLOCKED", output["knowledge_card_evidence"][0]["status"])

    def test_uncollected_auto_source_is_visible_and_cannot_look_computable(self) -> None:
        card = _card()
        card["data_source"] = {
            "availability": "AUTO",
            "primary": "Fixture API",
            "tushare_api": "daily_basic",
            "tushare_field": "pe_ttm,invented_field",
            "manual_required": False,
        }
        cards.validate_card(card)
        coverage = cards.source_coverage(card)
        self.assertFalse(coverage["collected_by_repo"])
        self.assertIn("daily_basic.invented_field", coverage["uncollected_pairs"])
        result = cards.evaluate(card, {"value": 12.0})
        self.assertEqual("DATA_BLOCKED", result["status"])
        self.assertEqual(["SOURCE_FIELDS_NOT_COLLECTED_BY_REPO"], result["reason_codes"])

    def test_source_coverage_is_checked_per_api_field_pair_not_by_union(self) -> None:
        card = _card()
        card["data_source"] = {
            "availability": "AUTO",
            "primary": "Two exact repository collectors",
            "tushare_api": "daily_basic,fina_indicator",
            "tushare_field": "pe_ttm,roe",
            "manual_required": False,
        }
        coverage = cards.source_coverage(card)
        by_pair = {
            (item["api"], item["field"]): item["collected_by_repo"]
            for item in coverage["declared_pairs"]
        }
        self.assertTrue(by_pair[("daily_basic", "pe_ttm")])
        self.assertFalse(by_pair[("daily_basic", "roe")])
        self.assertFalse(by_pair[("fina_indicator", "pe_ttm")])
        self.assertTrue(by_pair[("fina_indicator", "roe")])
        self.assertFalse(coverage["collected_by_repo"])

    def test_evaluation_verifier_rejects_result_card_and_envelope_hash_drift(self) -> None:
        card = _card()
        rows = {card["card_id"]: {"value": 12.0}}
        original = cards.attach_evaluations({"schema": "fixture.chain"}, [card], rows)
        self.assertTrue(cards.verify_evaluations(original, [card], rows)["ok"])

        result_drift = copy.deepcopy(original)
        result_drift["knowledge_card_evidence"][0]["result"]["observed"] = 999.0
        result_drift["knowledge_card_evidence_hash"] = cards.canonical_hash(
            result_drift["knowledge_card_evidence"]
        )
        with self.assertRaisesRegex(cards.KnowledgeCardError, "source-derived result"):
            cards.verify_evaluations(result_drift, [card], rows)

        card_hash_drift = copy.deepcopy(original)
        card_hash_drift["knowledge_card_evidence"][0]["card_hash"] = "sha256:" + "0" * 64
        card_hash_drift["knowledge_card_evidence_hash"] = cards.canonical_hash(
            card_hash_drift["knowledge_card_evidence"]
        )
        with self.assertRaisesRegex(cards.KnowledgeCardError, "source-derived result"):
            cards.verify_evaluations(card_hash_drift, [card], rows)

        envelope_drift = copy.deepcopy(original)
        envelope_drift["knowledge_card_evidence_hash"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(cards.KnowledgeCardError, "evidence hash mismatch"):
            cards.verify_evaluations(envelope_drift, [card], rows)

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cards.json"
            path.write_text('[{"card_id":"A","card_id":"B"}]', encoding="utf-8")
            with self.assertRaisesRegex(cards.KnowledgeCardError, "duplicate JSON key"):
                cards.load_cards(path)

    def test_cli_reports_closed_authority_and_content_hash(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            rc = cards.main([str(COMMITTED_CARDS)])
        payload = json.loads(output.getvalue())
        self.assertEqual(0, rc)
        self.assertEqual(23, payload["card_count"])
        self.assertEqual(23, payload["participating_count"])
        self.assertEqual(
            {"selection": False, "trade": False, "claim": False, "portfolio": False},
            payload["authority"],
        )
        self.assertRegex(payload["cards_hash"], r"^sha256:[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
