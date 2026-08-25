#!/usr/bin/env python3
"""Behavioral regressions for append-only semiconductor source repairs."""

from __future__ import annotations

import concurrent.futures
import copy
import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))

import semiconductor_inputs as si  # noqa: E402
import semiconductor_source_repair as repair  # noqa: E402
from security_registry import _sha256  # noqa: E402


DATES = ("20260824", "20260825")
CODES = [f"{index:06d}.SZ" for index in range(1, 21)]


def registry_fixture(as_of: str) -> dict:
    rows = [
        {
            "ts_code": code,
            "name": f"Semi {index}",
            "list_status": "L",
            "industry_key": "半导体",
            "source_presence": "CURRENT",
            "current_stage": "UNSCANNED",
            "qualification": {
                "u1_scan_eligible": True,
                "is_st": False,
                "is_bse": False,
                "liquidity_label": "NORMAL",
            },
            "data_coverage": {
                "identity": "COMPLETE",
                "industry": "COMPLETE",
                "liquidity": "COMPLETE",
            },
        }
        for index, code in enumerate(CODES, 1)
    ]
    return {
        "schema": "ar.security_registry",
        "schema_version": "1.0",
        "status": "COMPLETE",
        "as_of": as_of,
        "generated_at": "2026-08-25T00:00:00+00:00",
        "source": {"errors": []},
        "coverage": {
            "registry_rows": len(rows),
            "listed": len(rows),
            "delisted": 0,
            "prelisted": 0,
            "st_labeled": 0,
            "bse_labeled": 0,
            "low_liquidity_labeled": 0,
            "liquidity_data_blocked": 0,
            "preserved_missing_from_source": 0,
        },
        "eligible_universe_hash": _sha256(CODES),
        "registry_hash": _sha256(rows),
        "rows": rows,
    }


def moneyflow_rows(as_of: str, count: int = len(CODES)) -> list[dict]:
    return [
        {
            "ts_code": code,
            "trade_date": as_of,
            "net_amount": float(index * 10),
            "net_amount_rate": float(index) / 10,
            "buy_elg_amount": float(100 + index),
            "buy_elg_amount_rate": 2.0,
            "buy_lg_amount": float(80 + index),
            "buy_lg_amount_rate": 1.0,
            "buy_md_amount": float(50 + index),
            "buy_md_amount_rate": 0.5,
            "buy_sm_amount": float(20 + index),
            "buy_sm_amount_rate": 0.2,
        }
        for index, code in enumerate(CODES[:count], 1)
    ]


def chip_rows(as_of: str, count: int = len(CODES)) -> list[dict]:
    return [
        {
            "ts_code": code,
            "trade_date": as_of,
            "cost_5pct": 8.0 + index / 100,
            "cost_50pct": 10.0 + index / 100,
            "cost_85pct": 12.0 + index / 100,
            "cost_95pct": 13.0 + index / 100,
            "weight_avg": 10.5 + index / 100,
            "winner_rate": 0.5 + index / 1000,
        }
        for index, code in enumerate(CODES[:count], 1)
    ]


def insert_legacy_batch(
    db: Path,
    source_name: str,
    as_of: str,
    raw_rows: list[dict],
) -> None:
    normalized, conflicts = si.NORMALIZERS[source_name](raw_rows, as_of, set(CODES))
    observed = {row["ts_code"] for row in normalized}
    missing = sorted(set(CODES) - observed)
    body = {
        "rows": normalized,
        "missing_codes": missing,
        "conflict_codes": sorted(conflicts),
    }
    conn = si._connect(db)
    try:
        si.initialize(conn)
        conn.execute("BEGIN IMMEDIATE")
        si._insert_rows(conn, si.SOURCE_TABLE[source_name], normalized)
        conn.execute(
            "INSERT INTO semiconductor_source_batches VALUES(?,?,?,?,?,?,?,?)",
            (
                source_name,
                as_of,
                si._hash(body),
                len(normalized),
                _sha256(CODES),
                json.dumps(missing, separators=(",", ":")),
                json.dumps(sorted(conflicts), separators=(",", ":")),
                f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}T08:00:00+08:00",
            ),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


def build_legacy_store(db: Path, dates: tuple[str, ...] = DATES) -> None:
    for as_of in dates:
        insert_legacy_batch(db, "moneyflow_dc", as_of, moneyflow_rows(as_of, 19))
        insert_legacy_batch(db, "cyq_perf", as_of, [])


def replacement_specs(dates: tuple[str, ...] = DATES) -> list[dict]:
    specs = []
    for as_of in dates:
        captured_at = "2026-08-25T22:00:00+08:00"
        specs.append({
            "source_name": "cyq_perf",
            "as_of": as_of,
            "source_publication_status": "PUBLISHED",
            "source_publication_time": (
                f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}T18:00:00+08:00"
            ),
            "observed_at": captured_at,
            "raw_capture": repair.build_raw_capture(
                "cyq_perf", as_of, chip_rows(as_of), captured_at,
            ),
            "repair_reason": "legacy pre-publication empty batch requires append-only repair",
        })
    return specs


def approval_for(plan: dict) -> dict:
    return {
        "schema": repair.APPROVAL_SCHEMA,
        "approved_by": "Junyan",
        "approval_ref": "session:semiconductor-source-repair-v0.1",
        "approval_verbatim": repair.approval_verbatim_for(plan),
        "approval_channel": "session_verbatim",
        "evidence_strength": "TRANSCRIPT_ONLY_NOT_CRYPTOGRAPHIC",
        "approved_at": "2026-08-25T22:30:00+08:00",
        "scan_hash": plan["scan_hash"],
        "plan_hash": plan["plan_hash"],
    }


def plan_for(db: Path, dates: tuple[str, ...] = DATES) -> tuple[dict, dict]:
    scan = repair.scan_store(db)
    return scan, repair.build_plan(db, scan, replacement_specs(dates))


def rehash_plan(changed: dict) -> dict:
    output = copy.deepcopy(changed)
    for record in output["repairs"]:
        seed = {
            key: value for key, value in record.items()
            if key not in {"repair_id", "plan_hash"}
        }
        record["repair_id"] = "ssr-" + repair._hash(seed)[:24]
    plan_seed = {
        "schema": output["schema"],
        "schema_version": output["schema_version"],
        "status": output["status"],
        "scan_hash": output["scan_hash"],
        "repairs": [
            {key: value for key, value in record.items() if key != "plan_hash"}
            for record in output["repairs"]
        ],
        "authority": output["authority"],
    }
    output["plan_hash"] = repair._hash(plan_seed)
    for record in output["repairs"]:
        record["plan_hash"] = output["plan_hash"]
    return output


def original_rows(db: Path) -> dict[str, list[tuple]]:
    conn = sqlite3.connect(db)
    try:
        output: dict[str, list[tuple]] = {}
        for table in ("semiconductor_source_batches", *si.SOURCE_TABLE.values()):
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            ordering = ",".join(columns)
            output[table] = list(conn.execute(f"SELECT * FROM {table} ORDER BY {ordering}"))
        return output
    finally:
        conn.close()


def rewrite_single_record(
    db: Path,
    transform,
) -> None:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"DROP TRIGGER {repair.REPAIR_TABLE}_no_update")
        conn.execute(f"DROP TRIGGER {repair.RUN_TABLE}_no_update")
        row = dict(conn.execute(f"SELECT * FROM {repair.REPAIR_TABLE}").fetchone())
        payload = repair._record_payload(row)
        transform(payload)
        payload["repair_id"] = (
            "ssr-"
            + repair._hash(
                {
                    key: value
                    for key, value in payload.items()
                    if key not in {"repair_id", "plan_hash"}
                }
            )[:24]
        )
        run = dict(conn.execute(f"SELECT * FROM {repair.RUN_TABLE}").fetchone())
        unhashed_record = {
            key: value for key, value in payload.items() if key != "plan_hash"
        }
        plan_seed = {
            "schema": repair.PLAN_SCHEMA,
            "schema_version": repair.REPAIR_SCHEMA_VERSION,
            "status": "READY",
            "scan_hash": run["scan_hash"],
            "repairs": [unhashed_record],
            "authority": repair.AUTHORITY,
        }
        payload["plan_hash"] = repair._hash(plan_seed)
        db_row = {
            "repair_id": payload["repair_id"],
            "plan_hash": payload["plan_hash"],
            "repair_class": payload["repair_class"],
            "source_name": payload["source_name"],
            "as_of": payload["as_of"],
            "supersedes_source_hash": payload["supersedes_source_hash"],
            "replacement_source_hash": payload["replacement_source_hash"],
            "universe_hash": payload["universe_hash"],
            "row_count": payload["row_count"],
            "old_batch_ref_json": repair._canonical(payload["old_batch_ref"]),
            "replacement_body_json": repair._canonical(payload["replacement_body"]),
            "source_publication_status": payload["source_publication_status"],
            "source_publication_time": payload["source_publication_time"],
            "observed_at": payload["observed_at"],
            "point_in_time_status": payload["point_in_time_status"],
            "repair_reason": payload["repair_reason"],
            "raw_capture_json": repair._canonical(payload["raw_capture"]),
            "record_hash": repair._hash(payload),
        }
        columns = tuple(db_row)
        conn.execute(
            f"UPDATE {repair.REPAIR_TABLE} SET "
            + ",".join(f"{column}=?" for column in columns)
            + " WHERE repair_id=?",
            [db_row[column] for column in columns] + [row["repair_id"]],
        )
        run["plan_hash"] = payload["plan_hash"]
        run["repair_ids_json"] = repair._canonical([payload["repair_id"]])
        run["approval_verbatim"] = repair.approval_verbatim_for(
            {"scan_hash": run["scan_hash"], "plan_hash": run["plan_hash"]}
        )
        receipt = repair._run_receipt_payload(run)
        run["receipt_hash"] = repair._hash(receipt)
        assignments = ",".join(f"{key}=?" for key in run)
        conn.execute(
            f"UPDATE {repair.RUN_TABLE} SET {assignments}",
            list(run.values()),
        )
        conn.commit()
    finally:
        conn.close()


class SemiconductorSourceRepairTests(unittest.TestCase):
    def test_production_cli_cannot_override_the_shared_nightly_lock(self) -> None:
        parser = repair._parser()
        apply_parser = next(
            action.choices["apply"]
            for action in parser._actions
            if getattr(action, "choices", None) and "apply" in action.choices
        )
        destinations = {action.dest for action in apply_parser._actions}
        self.assertNotIn("nightly_lock", destinations)
        self.assertNotIn("db", destinations)
        self.assertIn("runtime_root", destinations)

    def test_production_apply_binds_store_and_lock_to_one_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtime"
            runner = root / "experiments" / "execution_tracker" / "run_nightly.py"
            runner.parent.mkdir(parents=True)
            runner.write_text("# fixture\n", encoding="utf-8")
            db = root / repair.FEATURE_STORE_RELATIVE_PATH
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            result = repair.apply_plan(
                db,
                plan,
                approval_for(plan),
                runtime_root=root,
                expected_scan_hash=scan["scan_hash"],
                expected_plan_hash=plan["plan_hash"],
            )
            self.assertEqual("APPLIED", result["status"])
            self.assertTrue((root / repair.NIGHTLY_LOCK_RELATIVE_PATH).is_file())

            other_db = Path(tmp) / "other" / "feature_store.sqlite3"
            build_legacy_store(other_db, (DATES[0],))
            other_scan, other_plan = plan_for(other_db, (DATES[0],))
            with self.assertRaisesRegex(repair.SourceRepairError, "one runtime root"):
                repair.apply_plan(
                    other_db,
                    other_plan,
                    approval_for(other_plan),
                    runtime_root=root,
                    expected_scan_hash=other_scan["scan_hash"],
                    expected_plan_hash=other_plan["plan_hash"],
                )

    def test_production_runtime_rejects_a_symlinked_store_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtime"
            runner = root / "experiments" / "execution_tracker" / "run_nightly.py"
            runner.parent.mkdir(parents=True)
            runner.write_text("# fixture\n", encoding="utf-8")
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (root / "data_history").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(repair.SourceRepairError, "escapes"):
                repair.production_runtime_paths(root)

    def test_read_side_import_does_not_require_posix_flock(self) -> None:
        source_path = ROOT / "experiments" / "research_funnel" / "semiconductor_source_repair.py"
        spec = importlib.util.spec_from_file_location("repair_without_fcntl", source_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        original_import = __import__

        def without_fcntl(name, *args, **kwargs):
            if name == "fcntl":
                raise ModuleNotFoundError("fcntl unavailable")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=without_fcntl):
            spec.loader.exec_module(module)
            with self.assertRaisesRegex(module.SourceRepairError, "requires POSIX flock"):
                with module.nightly_lock(Path("unused.lock")):
                    self.fail("non-POSIX repair lock unexpectedly opened")

    def test_class_scan_refuses_an_existing_non_feature_store_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "wrong.sqlite3"
            conn = sqlite3.connect(db)
            try:
                conn.execute("CREATE TABLE unrelated(value TEXT)")
                conn.commit()
            finally:
                conn.close()
            try:
                repair.scan_store(db)
            except repair.SourceRepairError as exc:
                self.assertRegex(str(exc), "extension is absent")
            except Exception as exc:
                self.fail(f"wrong-database scan escaped as an unclassified error: {exc}")
            else:
                self.fail("wrong-database scan produced a valid-looking empty scope")

    def test_self_reported_publication_time_cannot_rewrite_historical_evidence(self) -> None:
        self.assertEqual(
            "LATE_OBSERVED",
            repair._classify_point_in_time(
                DATES[0],
                "2026-08-24T18:00:00+08:00",
                "2026-08-25T22:00:00+08:00",
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan = repair.scan_store(db)
            specs = replacement_specs((DATES[0],))
            plan = repair.build_plan(db, scan, specs)
            self.assertEqual("LATE_OBSERVED", plan["repairs"][0]["point_in_time_status"])
            repair.apply_plan(
                db,
                plan,
                approval_for(plan),
                _test_nightly_lock_path=Path(tmp) / "nightly.lock",
                expected_scan_hash=scan["scan_hash"],
                expected_plan_hash=plan["plan_hash"],
            )
            snapshot = si.build_snapshot(db, registry_fixture(DATES[0]), DATES[0])
            self.assertEqual(
                ["LATE_OBSERVED_REPAIR"], snapshot["sources"]["cyq_perf"]["reason_codes"]
            )
            self.assertTrue(
                all(
                    row["chips"]["status"] == "DATA_BLOCKED"
                    and row["chips"]["reason_codes"] == ["LATE_OBSERVED_REPAIR"]
                    for row in snapshot["rows"]
                )
            )

    def test_capture_receipt_and_required_evidence_values_are_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan = repair.scan_store(db)
            for mutation, message in (
                ("capture_hash", "capture receipt hash"),
                ("empty_values", "required evidence values"),
                ("bad_percentiles", "internally inconsistent"),
            ):
                with self.subTest(mutation=mutation):
                    specs = replacement_specs((DATES[0],))
                    if mutation == "capture_hash":
                        specs[0]["raw_capture"]["capture_hash"] = "0" * 64
                    else:
                        rows = chip_rows(DATES[0])
                        if mutation == "empty_values":
                            for row in rows:
                                for key in (
                                    "cost_5pct", "cost_50pct", "cost_85pct",
                                    "cost_95pct", "weight_avg", "winner_rate",
                                ):
                                    row[key] = None
                        else:
                            rows[0]["cost_5pct"] = 99.0
                        specs[0]["raw_capture"] = repair.build_raw_capture(
                            "cyq_perf", DATES[0], rows, specs[0]["observed_at"]
                        )
                    with self.assertRaisesRegex(repair.SourceRepairError, message):
                        repair.build_plan(db, scan, specs)

    def test_multi_source_receipt_rebuild_uses_plan_semantic_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            date = DATES[0]
            insert_legacy_batch(db, "moneyflow_dc", date, moneyflow_rows(date, 18))
            insert_legacy_batch(db, "cyq_perf", date, [])
            scan = repair.scan_store(db)
            specs = replacement_specs((date,)) + [
                {
                    "source_name": "moneyflow_dc",
                    "as_of": date,
                    "source_publication_status": "PUBLISHED",
                    "source_publication_time": None,
                    "observed_at": "2026-08-25T22:00:00+08:00",
                    "raw_capture": repair.build_raw_capture(
                        "moneyflow_dc", date, moneyflow_rows(date),
                        "2026-08-25T22:00:00+08:00",
                    ),
                    "repair_reason": "repair moneyflow 1",
                }
            ]
            for nonce in range(64):
                specs[-1]["repair_reason"] = f"repair moneyflow {nonce}"
                plan = repair.build_plan(db, scan, specs)
                repair_ids = [row["repair_id"] for row in plan["repairs"]]
                if repair_ids != sorted(repair_ids):
                    break
            self.assertNotEqual(repair_ids, sorted(repair_ids))
            try:
                result = repair.apply_plan(
                    db,
                    plan,
                    approval_for(plan),
                    _test_nightly_lock_path=Path(tmp) / "nightly.lock",
                    expected_scan_hash=scan["scan_hash"],
                    expected_plan_hash=plan["plan_hash"],
                )
            except repair.SourceRepairError as exc:
                self.fail(f"valid multi-source repair failed receipt replay: {exc}")
            self.assertEqual("APPLIED", result["status"])
            self.assertEqual(2, result["repair_count"])

    def test_snapshot_cannot_mix_sources_across_one_atomic_repair_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            original_resolver = si._active_source
            committed = False
            observed_chip_counts = []

            def commit_after_first_source(conn, source_name, as_of):
                nonlocal committed
                active = original_resolver(conn, source_name, as_of)
                if source_name == "cyq_perf" and active is not None:
                    observed_chip_counts.append(active["batch"]["row_count"])
                if not committed:
                    committed = True
                    repair.apply_plan(
                        db,
                        plan,
                        approval_for(plan),
                        _test_nightly_lock_path=Path(tmp) / "nightly.lock",
                        expected_scan_hash=scan["scan_hash"],
                        expected_plan_hash=plan["plan_hash"],
                    )
                return active

            with mock.patch.object(si, "_active_source", commit_after_first_source):
                during_commit = si.build_snapshot(
                    db, registry_fixture(DATES[0]), DATES[0]
                )
            self.assertTrue(committed)
            self.assertEqual([0], observed_chip_counts)
            self.assertTrue(
                all(row["chips"]["status"] == "DATA_BLOCKED" for row in during_commit["rows"])
            )
            after_conn = si._connect(db, readonly=True)
            try:
                after_active = repair.resolve_active_source(
                    after_conn, "cyq_perf", DATES[0]
                )
            finally:
                after_conn.close()
            self.assertEqual(len(CODES), after_active["batch"]["row_count"])

    def test_class_scan_covers_every_registered_daily_source_and_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db)
            try:
                scan = repair.scan_store(db)
            except repair.SourceRepairError as exc:
                self.fail(f"class-wide scan failed instead of covering the class: {exc}")
            self.assertEqual(sorted(si.DAILY_MUST_PUBLISH_SOURCES), scan["daily_sources"])
            self.assertEqual(
                [(source, as_of) for source in sorted(si.DAILY_MUST_PUBLISH_SOURCES) for as_of in DATES],
                [(row["source_name"], row["as_of"]) for row in scan["rows"]],
            )
            by_key = {
                (row["source_name"], row["as_of"]): row for row in scan["rows"]
            }
            self.assertTrue(all(
                by_key[("cyq_perf", as_of)]["state"] == "REPAIR_REQUIRED"
                for as_of in DATES
            ))
            self.assertTrue(all(
                by_key[("moneyflow_dc", as_of)]["state"] == "CLEAN_ACTIVE"
                for as_of in DATES
            ))

    def test_class_scan_exposes_a_missing_registered_source_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            for as_of in DATES:
                insert_legacy_batch(
                    db, "moneyflow_dc", as_of, moneyflow_rows(as_of, 19)
                )
            insert_legacy_batch(db, "cyq_perf", DATES[0], [])
            scan = repair.scan_store(db)
            keys = [
                (row["source_name"], row["as_of"]) for row in scan["rows"]
            ]
            self.assertEqual(
                [
                    (source, as_of)
                    for source in sorted(si.DAILY_MUST_PUBLISH_SOURCES)
                    for as_of in DATES
                ],
                keys,
            )
            missing = next(
                row for row in scan["rows"]
                if (row["source_name"], row["as_of"])
                == ("cyq_perf", DATES[1])
            )
            self.assertEqual("SOURCE_PUBLICATION_PENDING", missing["state"])
            self.assertIsNone(missing["original_source_hash"])
            self.assertEqual("NO_ORIGINAL_BATCH", missing["point_in_time_status"])

    def test_snapshot_consumes_verified_active_repair_and_originals_never_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            lock = Path(tmp) / "nightly.lock"
            build_legacy_store(db, (DATES[0],))
            before = original_rows(db)
            blocked = si.build_snapshot(db, registry_fixture(DATES[0]), DATES[0])
            self.assertTrue(all(row["chips"]["status"] == "DATA_BLOCKED" for row in blocked["rows"]))
            scan, plan = plan_for(db, (DATES[0],))
            result = repair.apply_plan(
                db,
                plan,
                approval_for(plan),
                _test_nightly_lock_path=lock,
                expected_scan_hash=scan["scan_hash"],
                expected_plan_hash=plan["plan_hash"],
            )
            self.assertEqual("APPLIED", result["status"])
            repaired = si.build_snapshot(db, registry_fixture(DATES[0]), DATES[0])
            self.assertTrue(all(row["chips"]["status"] == "DATA_BLOCKED" for row in repaired["rows"]))
            self.assertTrue(all(
                row["chips"]["reason_codes"] == ["LATE_OBSERVED_REPAIR"]
                for row in repaired["rows"]
            ))
            conn = si._connect(db, readonly=True)
            try:
                active = repair.resolve_active_source(conn, "cyq_perf", DATES[0])
            finally:
                conn.close()
            self.assertEqual(len(CODES), active["batch"]["row_count"])
            self.assertEqual(before, original_rows(db))
            self.assertEqual(
                "PIT_BLOCKED", repair.scan_store(db)["rows"][0]["state"],
            )
            repeated = repair.apply_plan(
                db,
                plan,
                approval_for(plan),
                _test_nightly_lock_path=lock,
                expected_scan_hash=scan["scan_hash"],
                expected_plan_hash=plan["plan_hash"],
            )
            self.assertEqual("IDEMPOTENT_VERIFIED", repeated["status"])

    def test_has_batch_verifies_the_repair_chain_before_skipping_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            repair.apply_plan(
                db, plan, approval_for(plan), _test_nightly_lock_path=Path(tmp) / "lock",
                expected_scan_hash=scan["scan_hash"], expected_plan_hash=plan["plan_hash"],
            )
            conn = sqlite3.connect(db)
            try:
                conn.execute(f"DROP TRIGGER {repair.REPAIR_TABLE}_no_update")
                conn.execute(
                    f"UPDATE {repair.REPAIR_TABLE} SET record_hash=?", ("0" * 64,)
                )
                conn.commit()
            finally:
                conn.close()
            with self.assertRaisesRegex(repair.SourceRepairError, "record hash"):
                si._has_batch(db, "cyq_perf", DATES[0])

    def test_has_batch_uses_one_readonly_snapshot_during_a_concurrent_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            setup = si._connect(db)
            try:
                si.initialize(setup)
            finally:
                setup.close()
            original = si._active_source
            committed = False

            def commit_before_source_read(conn, source_name, as_of):
                nonlocal committed
                if not committed:
                    committed = True
                    insert_legacy_batch(db, source_name, as_of, moneyflow_rows(as_of))
                return original(conn, source_name, as_of)

            with mock.patch.object(si, "_active_source", commit_before_source_read):
                self.assertFalse(si._has_batch(db, "moneyflow_dc", DATES[0]))
            self.assertTrue(committed)
            self.assertTrue(si._has_batch(db, "moneyflow_dc", DATES[0]))

    def test_zero_and_undercovered_replacements_never_form_a_ready_plan(self) -> None:
        for count in (0, 18):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as tmp:
                db = Path(tmp) / "features.sqlite3"
                build_legacy_store(db, (DATES[0],))
                scan = repair.scan_store(db)
                specs = replacement_specs((DATES[0],))
                specs[0]["raw_capture"] = repair.build_raw_capture(
                    "cyq_perf", DATES[0], chip_rows(DATES[0], count),
                    specs[0]["observed_at"],
                )
                with self.assertRaises(si.SourcePublicationPending):
                    repair.build_plan(db, scan, specs)

    def test_unpublished_replacement_with_rows_stays_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan = repair.scan_store(db)
            specs = replacement_specs((DATES[0],))
            specs[0]["source_publication_status"] = "SOURCE_PUBLICATION_PENDING"
            with self.assertRaisesRegex(
                repair.SourcePublicationPendingForRepair, "SOURCE_PUBLICATION_PENDING"
            ):
                repair.build_plan(db, scan, specs)

    def test_persisted_undercovered_repair_body_is_rejected_independently(self) -> None:
        normalized, conflicts = si.NORMALIZERS["cyq_perf"](
            chip_rows(DATES[0], 18), DATES[0], set(CODES)
        )
        missing = sorted(set(CODES) - {row["ts_code"] for row in normalized})
        body = {
            "rows": normalized,
            "missing_codes": missing,
            "conflict_codes": sorted(conflicts),
        }
        batch = {
            "source_name": "cyq_perf",
            "as_of": DATES[0],
            "source_hash": si._hash(body),
            "row_count": len(normalized),
            "universe_hash": _sha256(CODES),
            "missing_codes_json": repair._canonical(missing),
            "conflict_codes_json": repair._canonical(sorted(conflicts)),
            "ingested_at": "2026-08-25T22:00:00+08:00",
        }
        with self.assertRaisesRegex(repair.SourceRepairError, "under-covered"):
            repair._body_from_batch(
                "cyq_perf",
                batch,
                {row["ts_code"]: row for row in normalized},
                require_daily_floor=True,
            )

    def test_changed_class_scan_refuses_before_creating_repair_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            insert_legacy_batch(db, "moneyflow_dc", DATES[1], moneyflow_rows(DATES[1], 19))
            with self.assertRaisesRegex(repair.SourceRepairError, "scan changed"):
                repair.apply_plan(
                    db, plan, approval_for(plan), _test_nightly_lock_path=Path(tmp) / "lock",
                    expected_scan_hash=scan["scan_hash"], expected_plan_hash=plan["plan_hash"],
                )
            conn = sqlite3.connect(db)
            try:
                tables = {
                    row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            finally:
                conn.close()
            self.assertTrue(repair.REPAIR_TABLES.isdisjoint(tables))

    def test_every_precommit_failure_rolls_back_schema_receipt_and_repairs(self) -> None:
        for fail_after in ("after_schema", "after_run", "after_repair_1", "before_commit"):
            with self.subTest(fail_after=fail_after), tempfile.TemporaryDirectory() as tmp:
                db = Path(tmp) / "features.sqlite3"
                build_legacy_store(db)
                before = original_rows(db)
                scan, plan = plan_for(db)
                with self.assertRaisesRegex(RuntimeError, "test crash"):
                    repair.apply_plan(
                        db, plan, approval_for(plan), _test_nightly_lock_path=Path(tmp) / "lock",
                        expected_scan_hash=scan["scan_hash"],
                        expected_plan_hash=plan["plan_hash"],
                        fail_after=fail_after,
                    )
                self.assertEqual(before, original_rows(db))
                conn = sqlite3.connect(db)
                try:
                    tables = {
                        row[0] for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                finally:
                    conn.close()
                self.assertTrue(repair.REPAIR_TABLES.isdisjoint(tables))

    def test_after_commit_crash_converges_on_exact_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            approval = approval_for(plan)
            with self.assertRaisesRegex(RuntimeError, "after_commit"):
                repair.apply_plan(
                    db, plan, approval, _test_nightly_lock_path=Path(tmp) / "lock",
                    expected_scan_hash=scan["scan_hash"], expected_plan_hash=plan["plan_hash"],
                    fail_after="after_commit",
                )
            result = repair.apply_plan(
                db, plan, approval, _test_nightly_lock_path=Path(tmp) / "lock",
                expected_scan_hash=scan["scan_hash"], expected_plan_hash=plan["plan_hash"],
            )
            self.assertEqual("IDEMPOTENT_VERIFIED", result["status"])
            self.assertTrue(repair.verify_plan_applied(db, plan)["ok"])

    def test_concurrent_apply_has_one_commit_and_a_verified_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            lock = Path(tmp) / "nightly.lock"
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            approval = approval_for(plan)
            barrier = threading.Barrier(2)

            def run_once(_index: int):
                barrier.wait()
                try:
                    return repair.apply_plan(
                        db, plan, approval, _test_nightly_lock_path=lock,
                        expected_scan_hash=scan["scan_hash"],
                        expected_plan_hash=plan["plan_hash"],
                    )["status"]
                except repair.SourceRepairError as exc:
                    return str(exc)

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(run_once, range(2)))
            self.assertEqual(1, results.count("APPLIED"))
            self.assertEqual(1, sum("nightly.lock is held" in value for value in results))
            retried = repair.apply_plan(
                db, plan, approval, _test_nightly_lock_path=lock,
                expected_scan_hash=scan["scan_hash"], expected_plan_hash=plan["plan_hash"],
            )
            self.assertEqual("IDEMPOTENT_VERIFIED", retried["status"])

    def test_literal_approval_must_bind_both_full_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            _scan, plan = plan_for(db, (DATES[0],))
            for field in ("scan_hash", "plan_hash"):
                with self.subTest(field=field):
                    changed = approval_for(plan)
                    changed["approval_verbatim"] = changed["approval_verbatim"].replace(
                        changed[field], "0" * 64
                    )
                    with self.assertRaisesRegex(repair.SourceRepairError, "literal approval"):
                        repair.validate_approval(changed, plan)
            denied = approval_for(plan)
            denied["approval_verbatim"] = (
                "Junyan 明确不批准执行这次迁移；"
                f"scan_hash={plan['scan_hash']}；plan_hash={plan['plan_hash']}"
            )
            with self.assertRaisesRegex(repair.SourceRepairError, "affirmative template"):
                repair.validate_approval(denied, plan)

    def test_invalid_future_projection_rolls_back_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            original = repair._plan_record_to_db

            def corrupt_written_row(record):
                row = original(record)
                row["repair_reason"] = ""
                return row

            with mock.patch.object(
                repair, "_plan_record_to_db", side_effect=corrupt_written_row
            ):
                with self.assertRaisesRegex(repair.SourceRepairError, "repair reason"):
                    repair.apply_plan(
                        db,
                        plan,
                        approval_for(plan),
                        _test_nightly_lock_path=Path(tmp) / "lock",
                        expected_scan_hash=scan["scan_hash"],
                        expected_plan_hash=plan["plan_hash"],
                    )
            conn = sqlite3.connect(db)
            try:
                tables = {
                    row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertTrue(repair.REPAIR_TABLES.isdisjoint(tables))
            finally:
                conn.close()

    def test_plan_hash_recomputes_after_a_caller_relabels_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            _scan, plan = plan_for(db, (DATES[0],))
            changed = copy.deepcopy(plan)
            changed["plan_hash"] = "0" * 64
            for row in changed["repairs"]:
                row["plan_hash"] = changed["plan_hash"]
            with self.assertRaisesRegex(repair.SourceRepairError, "plan hash"):
                repair.validate_plan(changed)

    def test_rehashed_plan_cannot_commit_an_empty_repair_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            plan["repairs"][0]["repair_reason"] = ""
            changed = rehash_plan(plan)
            with self.assertRaisesRegex(repair.SourceRepairError, "repair reason"):
                repair.validate_plan(changed)
            with self.assertRaisesRegex(repair.SourceRepairError, "repair reason"):
                repair.apply_plan(
                    db,
                    changed,
                    approval_for(changed),
                    _test_nightly_lock_path=Path(tmp) / "lock",
                    expected_scan_hash=scan["scan_hash"],
                    expected_plan_hash=changed["plan_hash"],
                )
            conn = sqlite3.connect(db)
            try:
                tables = {
                    row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertTrue(repair.REPAIR_TABLES.isdisjoint(tables))
            finally:
                conn.close()

    def test_plan_cannot_gain_trade_or_selection_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            _scan, plan = plan_for(db, (DATES[0],))
            changed = copy.deepcopy(plan)
            changed["authority"]["trade_authority"] = True
            with self.assertRaisesRegex(repair.SourceRepairError, "authority"):
                repair.validate_plan(changed)
            changed = copy.deepcopy(plan)
            changed["repairs"][0]["trade_action"] = "BUY"
            with self.assertRaisesRegex(repair.SourceRepairError, "fields"):
                repair.validate_plan(changed)

    def test_hash_drift_and_missing_predecessor_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            repair.apply_plan(
                db, plan, approval_for(plan), _test_nightly_lock_path=Path(tmp) / "lock",
                expected_scan_hash=scan["scan_hash"], expected_plan_hash=plan["plan_hash"],
            )
            rewrite_single_record(
                db,
                lambda payload: payload.update(supersedes_source_hash="1" * 64),
            )
            conn = si._connect(db, readonly=True)
            try:
                with self.assertRaisesRegex(repair.SourceRepairError, "orphan|predecessor"):
                    repair.resolve_active_source(conn, "cyq_perf", DATES[0])
            finally:
                conn.close()

    def test_old_artifact_reference_is_recomputed_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            repair.apply_plan(
                db, plan, approval_for(plan), _test_nightly_lock_path=Path(tmp) / "lock",
                expected_scan_hash=scan["scan_hash"], expected_plan_hash=plan["plan_hash"],
            )

            def alter_old_ref(payload: dict) -> None:
                payload["old_batch_ref"]["row_count"] = 999

            rewrite_single_record(db, alter_old_ref)
            conn = si._connect(db, readonly=True)
            try:
                with self.assertRaisesRegex(repair.SourceRepairError, "predecessor reference"):
                    repair.resolve_active_source(conn, "cyq_perf", DATES[0])
            finally:
                conn.close()

    def test_chain_walker_rejects_forks_cycles_and_orphans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            _scan, plan = plan_for(db, (DATES[0],))
            conn = si._connect(db, readonly=True)
            try:
                active = repair.resolve_active_source(conn, "cyq_perf", DATES[0])
            finally:
                conn.close()
            self.assertIsNotNone(active)
            record = copy.deepcopy(plan["repairs"][0])
            next_batch, next_rows = repair._replacement_batch(record)
            verified = (record, next_batch, next_rows)

            fork = copy.deepcopy(record)
            fork["repair_id"] = "ssr-" + "1" * 24
            with self.assertRaisesRegex(repair.SourceRepairError, "forks"):
                repair._walk_repair_chain(
                    active["original_batch"], active["rows"], [verified, (fork, next_batch, next_rows)]
                )

            cycle = copy.deepcopy(record)
            cycle["repair_id"] = "ssr-" + "2" * 24
            cycle["supersedes_source_hash"] = next_batch["source_hash"]
            with self.assertRaisesRegex(repair.SourceRepairError, "cycle"):
                repair._walk_repair_chain(
                    active["original_batch"],
                    active["rows"],
                    [verified, (cycle, active["original_batch"], active["rows"])],
                )

            orphan = copy.deepcopy(record)
            orphan["supersedes_source_hash"] = "f" * 64
            with self.assertRaisesRegex(repair.SourceRepairError, "orphan|predecessor"):
                repair._walk_repair_chain(
                    active["original_batch"], active["rows"], [(orphan, next_batch, next_rows)]
                )

    def test_repair_tables_are_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            repair.apply_plan(
                db, plan, approval_for(plan), _test_nightly_lock_path=Path(tmp) / "lock",
                expected_scan_hash=scan["scan_hash"], expected_plan_hash=plan["plan_hash"],
            )
            conn = sqlite3.connect(db)
            try:
                for statement in (
                    f"UPDATE {repair.RUN_TABLE} SET approved_by='other'",
                    f"DELETE FROM {repair.RUN_TABLE}",
                    f"UPDATE {repair.REPAIR_TABLE} SET row_count=0",
                    f"DELETE FROM {repair.REPAIR_TABLE}",
                    f"INSERT OR REPLACE INTO {repair.RUN_TABLE} "
                    f"SELECT * FROM {repair.RUN_TABLE}",
                    f"INSERT OR REPLACE INTO {repair.REPAIR_TABLE} "
                    f"SELECT * FROM {repair.REPAIR_TABLE}",
                ):
                    with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                        conn.execute(statement)
            finally:
                conn.close()

    def test_reader_rejects_any_incomplete_or_orphaned_repair_catalog(self) -> None:
        scenarios = ((DATES[0],), DATES)
        for dates in scenarios:
            with self.subTest(dates=dates), tempfile.TemporaryDirectory() as tmp:
                db = Path(tmp) / "features.sqlite3"
                build_legacy_store(db, dates)
                scan, plan = plan_for(db, dates)
                repair.apply_plan(
                    db,
                    plan,
                    approval_for(plan),
                    _test_nightly_lock_path=Path(tmp) / "lock",
                    expected_scan_hash=scan["scan_hash"],
                    expected_plan_hash=plan["plan_hash"],
                )
                conn = sqlite3.connect(db)
                try:
                    conn.execute(f"DROP TRIGGER {repair.REPAIR_TABLE}_no_delete")
                    conn.execute(
                        f"DELETE FROM {repair.REPAIR_TABLE} WHERE repair_id=?",
                        (plan["repairs"][0]["repair_id"],),
                    )
                    conn.commit()
                finally:
                    conn.close()
                reader = si._connect(db, readonly=True)
                try:
                    with self.assertRaisesRegex(
                        repair.SourceRepairError, "receipt does not bind"
                    ):
                        repair.resolve_active_source(reader, "cyq_perf", dates[-1])
                finally:
                    reader.close()

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            repair.apply_plan(
                db,
                plan,
                approval_for(plan),
                _test_nightly_lock_path=Path(tmp) / "lock",
                expected_scan_hash=scan["scan_hash"],
                expected_plan_hash=plan["plan_hash"],
            )
            conn = sqlite3.connect(db)
            try:
                conn.execute(f"DROP TRIGGER {repair.RUN_TABLE}_no_delete")
                conn.execute(f"DELETE FROM {repair.RUN_TABLE}")
                conn.commit()
            finally:
                conn.close()
            reader = si._connect(db, readonly=True)
            try:
                with self.assertRaisesRegex(repair.SourceRepairError, "without a committed run"):
                    repair.resolve_active_source(reader, "cyq_perf", DATES[0])
            finally:
                reader.close()

    def test_reader_recomputes_stored_plan_instead_of_trusting_run_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            repair.apply_plan(
                db, plan, approval_for(plan), _test_nightly_lock_path=Path(tmp) / "lock",
                expected_scan_hash=scan["scan_hash"], expected_plan_hash=plan["plan_hash"],
            )
            fake_hash = "0" * 64
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute(f"DROP TRIGGER {repair.REPAIR_TABLE}_no_update")
                conn.execute(f"DROP TRIGGER {repair.RUN_TABLE}_no_update")
                stored = dict(conn.execute(f"SELECT * FROM {repair.REPAIR_TABLE}").fetchone())
                payload = repair._record_payload(stored)
                payload["plan_hash"] = fake_hash
                conn.execute(
                    f"UPDATE {repair.REPAIR_TABLE} SET plan_hash=?,record_hash=?",
                    (fake_hash, repair._hash(payload)),
                )
                run = dict(conn.execute(f"SELECT * FROM {repair.RUN_TABLE}").fetchone())
                run["plan_hash"] = fake_hash
                run["receipt_hash"] = repair._hash(repair._run_receipt_payload(run))
                conn.execute(
                    f"UPDATE {repair.RUN_TABLE} SET plan_hash=?,receipt_hash=?",
                    (fake_hash, run["receipt_hash"]),
                )
                conn.commit()
            finally:
                conn.close()
            conn = si._connect(db, readonly=True)
            try:
                with self.assertRaisesRegex(repair.SourceRepairError, "plan hash"):
                    repair.resolve_active_source(conn, "cyq_perf", DATES[0])
            finally:
                conn.close()

    def test_reader_rechecks_stored_approval_semantics_after_receipt_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite3"
            build_legacy_store(db, (DATES[0],))
            scan, plan = plan_for(db, (DATES[0],))
            repair.apply_plan(
                db, plan, approval_for(plan), _test_nightly_lock_path=Path(tmp) / "lock",
                expected_scan_hash=scan["scan_hash"], expected_plan_hash=plan["plan_hash"],
            )
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute(f"DROP TRIGGER {repair.RUN_TABLE}_no_update")
                run = dict(conn.execute(f"SELECT * FROM {repair.RUN_TABLE}").fetchone())
                run["approval_verbatim"] = "forged approval without the frozen hashes"
                run["receipt_hash"] = repair._hash(repair._run_receipt_payload(run))
                conn.execute(
                    f"UPDATE {repair.RUN_TABLE} SET approval_verbatim=?,receipt_hash=?",
                    (run["approval_verbatim"], run["receipt_hash"]),
                )
                conn.commit()
            finally:
                conn.close()
            conn = si._connect(db, readonly=True)
            try:
                with self.assertRaisesRegex(repair.SourceRepairError, "literal approval"):
                    repair.resolve_active_source(conn, "cyq_perf", DATES[0])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
