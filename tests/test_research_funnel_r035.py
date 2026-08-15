#!/usr/bin/env python3
"""Behavioral regressions for R-035 aligned-return funnel evaluation."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FUNNEL = ROOT / "experiments" / "research_funnel"
sys.path.insert(0, str(FUNNEL))
sys.path.insert(0, str(ROOT / "tests"))

import funnel_pipeline as fp  # noqa: E402
import r035_evaluation as r035  # noqa: E402
from test_research_funnel_closure import (  # noqa: E402
    GENERATED_AT,
    TRADE_DATE,
    battery_fixture,
    build_scan,
)


SESSIONS = [
    "20260811", "20260812", "20260813", "20260814", "20260817", "20260818",
    "20260819", "20260820", "20260821", "20260824", "20260825",
]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class R035Fixture:
    def __init__(self, root: Path, *, sessions: list[str] | None = None):
        self.root = root
        self.bundle = root / "bundle"
        self.battery_path = root / "battery.json"
        self.db = root / "feature.sqlite3"
        self.sessions = list(sessions or SESSIONS)
        self.registry, self.features, self.scan = build_scan(top_n=8, n=180)
        self.candidates = fp.build_candidate_review(
            registry=self.registry,
            scan=self.scan,
            features=self.features,
            trade_date=TRADE_DATE,
            generated_at=GENERATED_AT,
            target_size=100,
            slow_bull_quota=5,
            contrarian_quota=5,
            control_quota=10,
        )
        active_codes = [
            row["ts_code"] for row in self.candidates["rows"]
            if row["review_status"] != "EXCLUDED_RED_FLAG"
        ]
        self.battery = battery_fixture(active_codes)
        for index, row in enumerate(self.battery["data"]["results"]):
            row["completeness"]["verdict"] = "COMPLETE" if index % 2 == 0 else "PARTIAL"
        self._write_bundle()
        write_json(self.battery_path, self.battery)
        self._write_db()

    def _write_bundle(self) -> None:
        self.bundle.mkdir(parents=True, exist_ok=True)
        queue = fp.build_deep_research_queue(
            candidate_review=self.candidates,
            battery=self.battery,
            selected_tickers=[],
            trade_date=TRADE_DATE,
            generated_at=GENERATED_AT,
        )
        payloads = {
            "all_market_scan.json": self.scan,
            "candidate_review.json": self.candidates,
            "deep_research_queue.json": queue,
            "security_registry_projected.json": self.registry,
        }
        for name, payload in payloads.items():
            write_json(self.bundle / name, payload)
        artifacts = {
            name: hashlib.sha256((self.bundle / name).read_bytes()).hexdigest()
            for name in payloads
        }
        write_json(self.bundle / "manifest.json", {
            "schema": "ar.research_funnel_bundle",
            "schema_version": fp.SCHEMA_VERSION,
            "rule_version": fp.RULE_VERSION,
            "as_of": TRADE_DATE,
            "generated_at": GENERATED_AT,
            "artifacts": artifacts,
            "bundle_hash": fp._hash(artifacts),
        })

    def rewrite_candidates(self) -> None:
        write_json(self.bundle / "candidate_review.json", self.candidates)
        manifest = json.loads((self.bundle / "manifest.json").read_text(encoding="utf-8"))
        manifest["artifacts"]["candidate_review.json"] = hashlib.sha256(
            (self.bundle / "candidate_review.json").read_bytes()
        ).hexdigest()
        manifest["bundle_hash"] = fp._hash(manifest["artifacts"])
        write_json(self.bundle / "manifest.json", manifest)

    def _growth_rate(self, code: str) -> float:
        candidate = next(row for row in self.candidates["rows"] if row["ts_code"] == code)
        if candidate["review_status"] == "RANDOM_CONTROL":
            return 0.0
        battery = next(row for row in self.battery["data"]["results"] if row["ts_code"] == code)
        return 0.01 if battery["completeness"]["verdict"] == "COMPLETE" else -0.005

    def _write_db(self) -> None:
        conn = sqlite3.connect(self.db)
        conn.executescript(
            """
            CREATE TABLE store_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE source_batches(
              endpoint TEXT NOT NULL, trade_date TEXT NOT NULL,
              source_hash TEXT NOT NULL, row_count INTEGER NOT NULL,
              universe_hash TEXT NOT NULL, ingested_at TEXT NOT NULL,
              PRIMARY KEY(endpoint, trade_date)
            );
            CREATE TABLE raw_daily(
              ts_code TEXT, trade_date TEXT, close REAL,
              PRIMARY KEY(ts_code, trade_date)
            );
            CREATE TABLE raw_daily_basic(
              ts_code TEXT, trade_date TEXT,
              PRIMARY KEY(ts_code, trade_date)
            );
            CREATE TABLE raw_adj_factor(
              ts_code TEXT, trade_date TEXT, adj_factor REAL,
              PRIMARY KEY(ts_code, trade_date)
            );
            """
        )
        conn.execute("INSERT INTO store_meta VALUES('schema_version','1')")
        conn.executemany(
            "INSERT INTO source_batches VALUES(?,?,?,?,?,?)",
            [
                (endpoint, date, f"hash-{endpoint}-{date}", 1, "universe", GENERATED_AT)
                for date in self.sessions
                for endpoint in ("daily", "daily_basic", "adj_factor")
            ],
        )
        codes = [
            row["ts_code"] for row in self.candidates["rows"]
            if row["review_status"] != "EXCLUDED_RED_FLAG"
        ]
        for code in codes:
            rate = self._growth_rate(code)
            for index, date in enumerate(self.sessions):
                close = 10.0 * (1.0 + rate) ** index
                conn.execute(
                    "INSERT INTO raw_daily VALUES(?,?,?)", (code, date, close)
                )
                conn.execute(
                    "INSERT INTO raw_adj_factor VALUES(?,?,?)", (code, date, 1.0)
                )
        conn.commit()
        conn.close()

    def evaluate(self) -> dict:
        return r035.build_evaluation(
            bundle_dir=self.bundle,
            battery_path=self.battery_path,
            feature_db=self.db,
            generated_at="2026-08-25T09:00:00+00:00",
        )


class R035EvaluationTests(unittest.TestCase):
    def test_aligned_returns_use_one_t0_and_all_preregistered_horizons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = R035Fixture(Path(tmp))
            receipt = fixture.evaluate()
            self.assertTrue(receipt["rows"])
            self.assertTrue(all(row["t0"]["trade_date"] == TRADE_DATE for row in receipt["rows"]))
            self.assertTrue(all(tuple(row["aligned_return"]) == r035.HORIZON_KEYS for row in receipt["rows"]))
            main = next(row for row in receipt["rows"] if row["u1_u2_group"] == "MAIN_CANDIDATE")
            expected = (1.0 + fixture._growth_rate(main["ts_code"])) ** 5 - 1.0
            self.assertAlmostEqual(main["aligned_return"]["T+5"]["value"], expected, places=10)

    def test_suspension_uses_last_settled_close_and_marks_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = R035Fixture(Path(tmp))
            code = next(
                row["ts_code"] for row in fixture.candidates["rows"]
                if row["review_status"] == "MAIN_CHANNEL"
            )
            conn = sqlite3.connect(fixture.db)
            conn.execute("DELETE FROM raw_daily WHERE ts_code=? AND trade_date=?", (code, SESSIONS[3]))
            conn.execute("DELETE FROM raw_adj_factor WHERE ts_code=? AND trade_date=?", (code, SESSIONS[3]))
            conn.commit()
            conn.close()
            receipt = fixture.evaluate()
            row = next(item for item in receipt["rows"] if item["ts_code"] == code)
            self.assertEqual("TRUNCATED", row["aligned_return"]["T+3"]["status"])
            self.assertEqual(SESSIONS[2], row["aligned_return"]["T+3"]["observed_trade_date"])

    def test_u12_and_u3_statistics_are_separate_and_batch_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipt = R035Fixture(Path(tmp)).evaluate()
            self.assertEqual(
                ["MAIN_CANDIDATE", "RANDOM_CONTROL"],
                receipt["tests"]["u1_u2_discovery"]["groups"],
            )
            self.assertEqual(
                ["BATTERY_PASS", "BATTERY_NON_PASS"],
                receipt["tests"]["u3_battery_separation"]["groups"],
            )
            self.assertEqual(
                {receipt["control_batch_id"]},
                {row["control_batch_id"] for row in receipt["rows"]},
            )
            self.assertFalse(any(
                row["u3_group"] for row in receipt["rows"]
                if row["u1_u2_group"] == "RANDOM_CONTROL"
            ))

    def test_missing_battery_is_excluded_and_reported_not_silently_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = R035Fixture(Path(tmp))
            removed = fixture.battery["data"]["results"].pop()
            write_json(fixture.battery_path, fixture.battery)
            receipt = fixture.evaluate()
            self.assertEqual("PARTIAL", receipt["status"])
            self.assertIn(removed["ts_code"], receipt["coverage"]["missing_battery_tickers"])
            self.assertNotIn(removed["ts_code"], {item["ts_code"] for item in receipt["rows"]})

    def test_open_future_window_is_not_fabricated_as_zero_return(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipt = R035Fixture(Path(tmp), sessions=SESSIONS[:3]).evaluate()
            self.assertEqual("PARTIAL", receipt["status"])
            self.assertTrue(all(
                row["aligned_return"]["T+5"]["status"] == "WINDOW_OPEN"
                and row["aligned_return"]["T+5"]["value"] is None
                for row in receipt["rows"]
            ))

    def test_missing_common_t0_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = R035Fixture(Path(tmp))
            code = next(row["ts_code"] for row in fixture.candidates["rows"] if row["review_status"] == "MAIN_CHANNEL")
            conn = sqlite3.connect(fixture.db)
            conn.execute("DELETE FROM raw_daily WHERE ts_code=? AND trade_date=?", (code, TRADE_DATE))
            conn.execute("DELETE FROM raw_adj_factor WHERE ts_code=? AND trade_date=?", (code, TRADE_DATE))
            conn.commit()
            conn.close()
            with self.assertRaisesRegex(r035.EvaluationError, "common U2 t0"):
                fixture.evaluate()

    def test_partial_feature_store_batch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = R035Fixture(Path(tmp))
            conn = sqlite3.connect(fixture.db)
            conn.execute(
                "DELETE FROM source_batches WHERE endpoint='adj_factor' AND trade_date=?",
                (SESSIONS[1],),
            )
            conn.commit()
            conn.close()
            with self.assertRaisesRegex(r035.EvaluationError, "partial source batches"):
                fixture.evaluate()

    def test_price_rows_without_a_committed_source_batch_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = R035Fixture(Path(tmp))
            code = next(
                row["ts_code"] for row in fixture.candidates["rows"]
                if row["review_status"] == "MAIN_CHANNEL"
            )
            conn = sqlite3.connect(fixture.db)
            conn.execute("INSERT INTO raw_daily VALUES(?,?,?)", (code, "20260815", 99.0))
            conn.execute("INSERT INTO raw_adj_factor VALUES(?,?,?)", (code, "20260815", 1.0))
            conn.commit()
            conn.close()
            with self.assertRaisesRegex(r035.EvaluationError, "not backed"):
                fixture.evaluate()

    def test_cross_batch_control_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = R035Fixture(Path(tmp))
            control = next(row for row in fixture.candidates["rows"] if row["review_status"] == "RANDOM_CONTROL")
            control["control_batch_id"] = "CTRL_OTHER_v1"
            fixture.candidates["rows_hash"] = fp._hash(fixture.candidates["rows"])
            fixture.rewrite_candidates()
            with self.assertRaisesRegex(r035.EvaluationError, "batch"):
                fixture.evaluate()

    def test_control_frame_must_be_bound_to_candidate_asof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = R035Fixture(Path(tmp))
            fixture.candidates["control_sampling_frame"]["control_batch_id"] = "CTRL_OTHER_v1"
            for row in fixture.candidates["rows"]:
                if row["review_status"] == "RANDOM_CONTROL":
                    row["control_batch_id"] = "CTRL_OTHER_v1"
            fixture.candidates["rows_hash"] = fp._hash(fixture.candidates["rows"])
            fixture.rewrite_candidates()
            with self.assertRaisesRegex(r035.EvaluationError, "bound to the candidate as_of"):
                fixture.evaluate()

    def test_candidate_bundle_must_remain_outcome_blind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = R035Fixture(Path(tmp))
            fixture.candidates["rows"][0]["aligned_return"] = {"T+5": 0.99}
            fixture.candidates["rows_hash"] = fp._hash(fixture.candidates["rows"])
            fixture.rewrite_candidates()
            with self.assertRaisesRegex(r035.EvaluationError, "outcome data"):
                fixture.evaluate()

    def test_bundle_artifact_hash_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = R035Fixture(Path(tmp))
            candidate_path = fixture.bundle / "candidate_review.json"
            candidate_path.write_bytes(candidate_path.read_bytes() + b"\n")
            with self.assertRaisesRegex(r035.EvaluationError, "artifact hash drift"):
                fixture.evaluate()

    def test_statistics_are_recomputed_from_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipt = R035Fixture(Path(tmp)).evaluate()
            mutated = copy.deepcopy(receipt)
            mutated["tests"]["u1_u2_discovery"]["horizons"]["T+5"]["group_a"]["n"] += 1
            with self.assertRaisesRegex(r035.EvaluationError, "statistics"):
                r035.validate_evaluation(mutated)

    def test_preregistered_policy_and_top_level_status_are_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipt = R035Fixture(Path(tmp)).evaluate()
            policy_mutation = copy.deepcopy(receipt)
            policy_mutation["policy"]["entry_basis"] = "SIGNAL_DAY_CLOSE"
            with self.assertRaisesRegex(r035.EvaluationError, "policy drift"):
                r035.validate_evaluation(policy_mutation)
            status_mutation = copy.deepcopy(receipt)
            status_mutation["status"] = "PARTIAL"
            with self.assertRaisesRegex(r035.EvaluationError, "top-level status"):
                r035.validate_evaluation(status_mutation)

    def test_random_controls_cannot_enter_the_u3_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipt = R035Fixture(Path(tmp)).evaluate()
            control = next(
                row for row in receipt["rows"]
                if row["u1_u2_group"] == "RANDOM_CONTROL"
            )
            control["u3_group"] = "BATTERY_PASS"
            control["u3_group_reason"] = "COMPLETE_AND_NO_RED_FLAG"
            receipt["rows_hash"] = r035._hash(receipt["rows"])
            receipt["tests"] = r035._tests_from_rows(receipt["rows"])
            with self.assertRaisesRegex(r035.EvaluationError, "cannot enter the U3 test"):
                r035.validate_evaluation(receipt)

    def test_claim_cannot_be_unlocked_by_sample_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipt = R035Fixture(Path(tmp)).evaluate()
            mutated = copy.deepcopy(receipt)
            mutated["claim_gate"]["status"] = "PASS"
            mutated["claim_gate"]["claim_allowed"] = True
            with self.assertRaisesRegex(r035.EvaluationError, "cannot unlock"):
                r035.validate_evaluation(mutated)

    def test_trade_or_blocking_authority_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipt = R035Fixture(Path(tmp)).evaluate()
            receipt["trade_action"] = "BUY"
            with self.assertRaisesRegex(r035.EvaluationError, "trade authority"):
                r035.validate_evaluation(receipt)

    def test_duplicate_json_keys_and_receipt_overwrite_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"as_of":"one","as_of":"two"}', encoding="utf-8")
            with self.assertRaisesRegex(r035.EvaluationError, "duplicate JSON"):
                r035._load_json(duplicate)
            output = root / "receipt.json"
            r035._atomic_write_new(output, {"ok": True})
            with self.assertRaisesRegex(r035.EvaluationError, "overwrite"):
                r035._atomic_write_new(output, {"ok": False})

    def test_cli_writes_one_receipt_and_never_mutates_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = R035Fixture(root)
            before = {
                "bundle": tree_hash(fixture.bundle),
                "battery": hashlib.sha256(fixture.battery_path.read_bytes()).hexdigest(),
                "db": hashlib.sha256(fixture.db.read_bytes()).hexdigest(),
            }
            output = root / "evaluation.json"
            command = [
                sys.executable,
                str(FUNNEL / "r035_evaluation.py"),
                "--bundle-dir", str(fixture.bundle),
                "--battery", str(fixture.battery_path),
                "--feature-db", str(fixture.db),
                "--output", str(output),
                "--generated-at", "2026-08-25T09:00:00+00:00",
            ]
            first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(0, first.returncode, first.stderr)
            receipt = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(receipt["claim_gate"]["claim_allowed"])
            original_output = output.read_bytes()
            second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(1, second.returncode)
            self.assertIn("refusing to overwrite", second.stderr)
            self.assertEqual(original_output, output.read_bytes())
            self.assertEqual(before["bundle"], tree_hash(fixture.bundle))
            self.assertEqual(
                before["battery"],
                hashlib.sha256(fixture.battery_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(before["db"], hashlib.sha256(fixture.db.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main(verbosity=2)
