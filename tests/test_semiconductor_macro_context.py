#!/usr/bin/env python3
"""Offline regressions for a source-bound semiconductor research supplement."""

import copy
import hashlib
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.macro_os import m1a, m1b
from experiments.research_funnel import semiconductor_macro_context as subject


class SemiconductorMacroContextTests(unittest.TestCase):
    def setUp(self):
        factors = {region: [] for region in m1a.REGIONS}
        for region, rules in m1a.load_rules()["regions"].items():
            for rule in rules:
                factors[region].append({
                    "factor_id": rule["factor_id"], "data_status": "CURRENT",
                    "signal": "NEUTRAL", "value": 1.0, "unit": rule["unit"],
                    "observation_at": "2026-09-08T10:00:00Z", "snapshot_hash": "a" * 64,
                })
        self.state = {"run_id": "fixture_m1a", "data": {"factors": factors}}

    def payload(self, *, blocked=()):
        state = copy.deepcopy(self.state)
        for rows in state["data"]["factors"].values():
            for row in rows:
                if row["factor_id"] in blocked:
                    row.update(data_status="DATA_BLOCKED", signal="DATA_BLOCKED",
                               value=None, observation_at=None, snapshot_hash=None)
        return m1b.build_industry_contract(
            spec=m1b.load_spec(), state=state, source_manifest_hash="b" * 64,
            as_of=datetime(2026, 9, 8, 12, tzinfo=timezone.utc), run_id="fixture_run",
        )

    def args(self, payload=None):
        raw = json.dumps(self.payload() if payload is None else payload,
                         ensure_ascii=False, sort_keys=True).encode()
        return dict(industry_bytes=raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
                    run_id="fixture_run", target_trade_date="20260908")

    def test_exact_subsector_and_provenance_are_preserved(self):
        args = self.args()
        before = args["industry_bytes"]
        result = subject.build_context(**args)
        row = next(r for r in self.payload()["data"]["subsectors"]
                   if r["subsector"] == "半导体")
        self.assertEqual(("电子", "半导体"), (result["industry"], result["subsector"]))
        self.assertEqual(row["relations"], result["relations"])
        self.assertEqual("COMPLETE", result["data_quality"])
        self.assertEqual(before, args["industry_bytes"])
        self.assertEqual(result, subject.build_context(**args))
        self.assertNotIn("normalized_score_display_only", result)

    def test_changed_source_bytes_are_refused(self):
        args = self.args()
        args["expected_sha256"] = "0" * 64
        with self.assertRaisesRegex(subject.ContextError, "source hash"):
            subject.build_context(**args)

    def test_upstream_contract_is_actually_checked(self):
        payload = self.payload()
        payload["mode"] = "LIVE"
        with self.assertRaises(subject.ContextError):
            subject.build_context(**self.args(payload))

    def test_wrong_run_is_refused(self):
        args = self.args()
        args["run_id"] = "another_run"
        with self.assertRaisesRegex(subject.ContextError, "run binding"):
            subject.build_context(**args)

    def test_wrong_day_is_refused(self):
        args = self.args()
        args["target_trade_date"] = "20260907"
        with self.assertRaisesRegex(subject.ContextError, "trade date"):
            subject.build_context(**args)

    def test_trade_date_uses_china_midnight_boundary(self):
        payload = self.payload()
        payload["as_of"] = payload["generated_at"] = "2026-09-07T16:00:00Z"
        args = self.args(payload)
        try:
            result = subject.build_context(**args)
        except subject.ContextError as exc:
            self.fail(f"valid China-day evidence was rejected: {exc}")
        self.assertEqual("20260908", result["target_trade_date"])
        args["target_trade_date"] = "20260907"
        with self.assertRaisesRegex(subject.ContextError, "trade date"):
            subject.build_context(**args)

    def test_other_spec_is_refused(self):
        payload = self.payload()
        payload["spec_hash"] = "c" * 64
        with self.assertRaisesRegex(subject.ContextError, "spec binding"):
            subject.build_context(**self.args(payload))

    def test_duplicate_subsector_is_refused(self):
        payload = self.payload()
        row = next(r for r in payload["data"]["subsectors"] if r["subsector"] == "半导体")
        payload["data"]["subsectors"].append(copy.deepcopy(row))
        with self.assertRaisesRegex(subject.ContextError, "exactly one"):
            subject.build_context(**self.args(payload))

    def test_missing_subsector_never_falls_back_to_parent(self):
        payload = self.payload()
        payload["data"]["subsectors"] = [r for r in payload["data"]["subsectors"]
                                            if r["subsector"] != "半导体"]
        with self.assertRaises(subject.ContextError):
            subject.build_context(**self.args(payload))

    def test_partial_evidence_stays_partial(self):
        result = subject.build_context(**self.args(self.payload(blocked=("US_GDP",))))
        self.assertEqual(0.75, result["coverage"])
        self.assertEqual("PARTIAL", result["data_quality"])
        self.assertEqual(["US_GDP"], result["blocked_factors"])

    def test_no_evidence_is_data_blocked(self):
        row = next(r for r in self.payload()["data"]["subsectors"] if r["subsector"] == "半导体")
        blocked = [r["factor_id"] for r in row["relations"]]
        result = subject.build_context(**self.args(self.payload(blocked=blocked)))
        self.assertEqual("DATA_BLOCKED", result["data_quality"])
        self.assertEqual(0, result["coverage"])

    def test_authority_is_never_granted(self):
        result = subject.build_context(**self.args())
        self.assertEqual("WORKFLOW_DEBUG", result["sample_purpose"])
        self.assertEqual("CALIBRATING", result["mode"])
        self.assertEqual("UNVALIDATED_V0", result["validation_status"])
        self.assertTrue(result["authority"])
        self.assertTrue(all(value is False for value in result["authority"].values()))

    def test_resealed_supplement_is_rederived_not_trusted(self):
        args = self.args()
        result = subject.build_context(**args)
        subject.validate_context(result, **args)
        for key, value in (("data_quality", "DATA_BLOCKED"), ("trade_action", "BUY")):
            changed = copy.deepcopy(result)
            changed[key] = value
            changed["context_hash"] = subject.context_hash(changed)
            with self.assertRaisesRegex(subject.ContextError, "reopened evidence"):
                subject.validate_context(changed, **args)

    def test_numeric_false_is_not_the_same_contract(self):
        args = self.args()
        result = subject.build_context(**args)
        changed = copy.deepcopy(result)
        changed["authority"]["trade_authority"] = 0
        self.assertNotEqual(subject.context_hash(result), subject.context_hash(changed))
        with self.assertRaisesRegex(subject.ContextError, "reopened evidence"):
            subject.validate_context(changed, **args)
        changed["context_hash"] = subject.context_hash(changed)
        with self.assertRaisesRegex(subject.ContextError, "reopened evidence"):
            subject.validate_context(changed, **args)


if __name__ == "__main__":
    unittest.main(verbosity=2)
