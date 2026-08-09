#!/usr/bin/env python3
"""Adversarial zero-network tests for Macro OS M0-B."""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from experiments.macro_os import collectors, contracts  # noqa: E402
from experiments.macro_os.storage import (  # noqa: E402
    MacroHistoryStore,
    MacroStoreError,
    Observation,
    source_identity_hash,
)


NOW = datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-08-07T01:00:00Z"


def source_row(source_id: str) -> tuple[dict, str]:
    registry = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(registry)
    return contracts.source_index(registry)[source_id], registry["registry_hash"]


def one_observation(
    series_id: str = "vix_close",
    metric_key: str = "vix_close",
    value: float = 18.5,
    value_text: str = "18.5",
    observation_at: str = "2026-08-06T00:00:00Z",
) -> Observation:
    return Observation(
        series_id=series_id,
        metric_key=metric_key,
        observation_at=observation_at,
        vintage_at=NOW_ISO,
        value_text=value_text,
        value=value,
        unit="index_points",
        attributes={"fixture": True},
    )


def record_vix(
    store: MacroHistoryStore,
    *,
    run_id: str,
    raw: bytes,
    value: float = 18.5,
    fetched_at: str = NOW_ISO,
):
    source, registry_hash = source_row("cboe_vix")
    return store.record_success(
        run_id=run_id,
        request_id="cboe_vix_history",
        source=source,
        registry_hash=registry_hash,
        requested_series=["vix_close"],
        started_at=fetched_at,
        fetched_at=fetched_at,
        public_locator="https://cdn.cboe.com/vix.csv",
        response_url="https://cdn.cboe.com/vix.csv",
        response_status=200,
        media_type="text/csv",
        raw_payload=raw,
        collector_version=collectors.COLLECTOR_VERSION,
        transport_meta={"final_host": "cdn.cboe.com"},
        observations=[
            Observation(
                series_id="vix_close",
                metric_key="vix_close",
                observation_at="2026-08-06T00:00:00Z",
                vintage_at=fetched_at,
                value_text=str(value),
                value=value,
                unit="index_points",
                attributes={"fixture": True},
            )
        ],
    )


def bls_fixture() -> bytes:
    rows = []
    for index, metric in enumerate(collectors.BLS_METRICS):
        rows.append(
            {
                "seriesID": metric.native_series_id,
                "data": [
                    {
                        "year": "2026",
                        "period": "M07",
                        "periodName": "July",
                        "value": str(100 + index),
                        "footnotes": [{}],
                    }
                ],
            }
        )
    return json.dumps(
        {"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": rows}},
        separators=(",", ":"),
    ).encode("utf-8")


def fred_fixture(value: str = "4.25") -> bytes:
    return json.dumps(
        {
            "realtime_start": "2026-08-07",
            "realtime_end": "2026-08-07",
            "observations": [
                {
                    "realtime_start": "2026-08-07",
                    "realtime_end": "2026-08-07",
                    "date": "2026-08-06",
                    "value": value,
                }
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")


def bea_fixture(line: str, period: str, value: str) -> bytes:
    return json.dumps(
        {
            "BEAAPI": {
                "Results": {
                    "Data": [
                        {
                            "LineNumber": line,
                            "TimePeriod": period,
                            "DataValue": value,
                            "LineDescription": "fixture",
                            "CL_UNIT": "Percent",
                            "UNIT_MULT": "0",
                        }
                    ]
                }
            }
        },
        separators=(",", ":"),
    ).encode("utf-8")


class MappingTransport:
    def __init__(self, mapping: dict[str, collectors.HttpResponse]):
        self.mapping = mapping
        self.calls = 0

    def fetch(self, request: collectors.HttpRequest) -> collectors.HttpResponse:
        self.calls += 1
        return self.mapping[request.public_locator]


class MacroM0BTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "macro.sqlite3"
        self.store = MacroHistoryStore(self.db)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_append_only_store_binds_registry_identity(self) -> None:
        stored = record_vix(self.store, run_id="run_identity", raw=b"raw-v1")
        self.assertFalse(stored.idempotent)
        source, registry_hash = source_row("cboe_vix")
        expected_hash = source_identity_hash(source, registry_hash)
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM source_identities").fetchone()
            snapshot = conn.execute("SELECT * FROM raw_snapshots").fetchone()
        self.assertEqual(expected_hash, row["identity_hash"])
        self.assertEqual(source["provider"], row["provider"])
        self.assertEqual(source["independence_group"], row["independence_group"])
        self.assertEqual(expected_hash, snapshot["source_identity_hash"])
        self.assertEqual([], self.store.verify_integrity())

    def test_same_payload_under_new_source_identity_is_a_new_version(self) -> None:
        record_vix(self.store, run_id="run_identity_v1", raw=b"same-payload")
        original_loader = contracts.load_json
        registry_v2 = copy.deepcopy(original_loader(contracts.SOURCE_REGISTRY))
        source_v2 = next(
            row for row in registry_v2["sources"] if row["source_id"] == "cboe_vix"
        )
        source_v2["provider"] = "Cboe Global Markets Renamed"
        unsigned = {
            key: value for key, value in registry_v2.items() if key != "registry_hash"
        }
        registry_v2["registry_hash"] = contracts.content_hash(unsigned)

        def versioned_loader(path: Path) -> dict:
            if path == contracts.SOURCE_REGISTRY:
                return copy.deepcopy(registry_v2)
            return original_loader(path)

        contracts.load_json = versioned_loader
        try:
            self.store.record_success(
                run_id="run_identity_v2",
                request_id="cboe_vix_history",
                source=copy.deepcopy(source_v2),
                registry_hash=registry_v2["registry_hash"],
                requested_series=["vix_close"],
                started_at="2026-08-08T01:00:00Z",
                fetched_at="2026-08-08T01:00:00Z",
                public_locator="https://cdn.cboe.com/vix.csv",
                response_url="https://cdn.cboe.com/vix.csv",
                response_status=200,
                media_type="text/csv",
                raw_payload=b"same-payload",
                collector_version=collectors.COLLECTOR_VERSION,
                transport_meta={"final_host": "cdn.cboe.com"},
                observations=[
                    Observation(
                        series_id="vix_close",
                        metric_key="vix_close",
                        observation_at="2026-08-06T00:00:00Z",
                        vintage_at="2026-08-08T01:00:00Z",
                        value_text="18.5",
                        value=18.5,
                        unit="index_points",
                        attributes={"fixture": True},
                    )
                ],
            )
        finally:
            contracts.load_json = original_loader
        counts = self.store.counts()
        self.assertEqual(2, counts["source_identities"])
        self.assertEqual(2, counts["raw_snapshots"])
        self.assertEqual(2, counts["observations"])
        stats = self.store.series_version_stats("cboe_vix", "vix_close", "vix_close")
        self.assertEqual(2, stats["snapshots"])

    def test_storage_rejects_source_identity_not_in_canonical_registry(self) -> None:
        source, _registry_hash = source_row("fred_alfred")
        forged = copy.deepcopy(source)
        forged["official"] = True
        forged["evidence_level"] = "E1"
        forged["roles"] = ["OFFICIAL_ACTUAL"]
        with self.assertRaisesRegex(MacroStoreError, "canonical M0-A registry"):
            self.store.record_failure(
                run_id="run_forged_identity",
                request_id="fred_dgs2",
                source=forged,
                registry_hash="a" * 64,
                requested_series=["us_treasury_curve"],
                started_at=NOW_ISO,
                completed_at=NOW_ISO,
                public_locator="source://fred_alfred/fred_dgs2",
                status="DATA_BLOCKED",
                error_code="FIXTURE",
                error_message="fixture",
            )

    def test_store_rejects_unregistered_series(self) -> None:
        source, registry_hash = source_row("cboe_vix")
        with self.assertRaisesRegex(MacroStoreError, "unregistered series"):
            self.store.record_success(
                run_id="run_bad_series",
                request_id="bad",
                source=source,
                registry_hash=registry_hash,
                requested_series=["vix_close"],
                started_at=NOW_ISO,
                fetched_at=NOW_ISO,
                public_locator="https://cdn.cboe.com/vix.csv",
                response_url="https://cdn.cboe.com/vix.csv",
                response_status=200,
                media_type="text/csv",
                raw_payload=b"bad-series",
                collector_version=collectors.COLLECTOR_VERSION,
                transport_meta={"final_host": "cdn.cboe.com"},
                observations=[one_observation(series_id="made_up")],
            )
        self.assertEqual(0, self.store.counts()["raw_snapshots"])

    def test_store_is_idempotent_and_preserves_revisions(self) -> None:
        first = record_vix(self.store, run_id="run_1", raw=b"raw-v1", value=18.5)
        again = record_vix(self.store, run_id="run_2", raw=b"raw-v1", value=18.5)
        revised = record_vix(
            self.store,
            run_id="run_3",
            raw=b"raw-v2",
            value=19.0,
            fetched_at="2026-08-08T01:00:00Z",
        )
        self.assertFalse(first.idempotent)
        self.assertTrue(again.idempotent)
        self.assertFalse(revised.idempotent)
        counts = self.store.counts()
        self.assertEqual(2, counts["raw_snapshots"])
        self.assertEqual(2, counts["observations"])
        self.assertEqual(3, counts["fetch_attempts"])
        stats = self.store.series_version_stats("cboe_vix", "vix_close", "vix_close")
        self.assertEqual(2, stats["snapshots"])
        self.assertEqual(1, stats["revised_periods"])

    def test_same_raw_bytes_can_be_checked_again_at_a_new_vintage(self) -> None:
        record_vix(self.store, run_id="run_day_1", raw=b"unchanged")
        record_vix(
            self.store,
            run_id="run_day_2",
            raw=b"unchanged",
            fetched_at="2026-08-08T01:00:00Z",
        )
        counts = self.store.counts()
        self.assertEqual(1, counts["raw_snapshots"])
        self.assertEqual(1, counts["observations"])
        self.assertEqual(2, counts["fetch_attempts"])
        stats = self.store.series_version_stats("cboe_vix", "vix_close", "vix_close")
        self.assertEqual(1, stats["vintages"])
        latest_attempt = self.store.latest_attempt("cboe_vix", "cboe_vix_history")
        self.assertEqual("2026-08-08T01:00:00Z", latest_attempt["completed_at"])

    def test_duplicate_periods_in_one_response_are_rejected(self) -> None:
        source, registry_hash = source_row("cboe_vix")
        with self.assertRaisesRegex(MacroStoreError, "duplicate series/metric/period"):
            self.store.record_success(
                run_id="run_duplicate_period",
                request_id="cboe_vix_history",
                source=source,
                registry_hash=registry_hash,
                requested_series=["vix_close"],
                started_at=NOW_ISO,
                fetched_at=NOW_ISO,
                public_locator="https://cdn.cboe.com/vix.csv",
                response_url="https://cdn.cboe.com/vix.csv",
                response_status=200,
                media_type="text/csv",
                raw_payload=b"duplicate-periods",
                collector_version=collectors.COLLECTOR_VERSION,
                transport_meta={"final_host": "cdn.cboe.com"},
                observations=[one_observation(), one_observation()],
            )
        self.assertEqual(0, self.store.counts()["raw_snapshots"])

    def test_update_and_delete_are_rejected(self) -> None:
        record_vix(self.store, run_id="run_immutable", raw=b"raw-v1")
        with self.store.connect() as conn:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                conn.execute("UPDATE observations SET value_text='999'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                conn.execute("DELETE FROM raw_snapshots")

    def test_integrity_verifier_detects_external_observation_tamper(self) -> None:
        record_vix(self.store, run_id="run_tamper", raw=b"raw-v1")
        with self.store.connect() as conn:
            conn.execute("DROP TRIGGER observations_no_update")
            conn.execute("UPDATE observations SET value_text='999', value_real=999")
        self.assertTrue(
            any("observation hash mismatch" in item for item in self.store.verify_integrity())
        )

    def test_integrity_verifier_detects_missing_append_only_trigger(self) -> None:
        record_vix(self.store, run_id="run_trigger_tamper", raw=b"raw-v1")
        with self.store.connect() as conn:
            conn.execute("DROP TRIGGER observations_no_update")
        self.assertTrue(
            any("append-only triggers missing" in item for item in self.store.verify_integrity())
        )

    def test_integrity_recomputes_all_four_record_fingerprints(self) -> None:
        mutations = (
            (
                "raw_snapshots_no_update",
                "UPDATE raw_snapshots SET raw_payload = X'74616d7065726564'",
                "raw snapshot hash mismatch",
            ),
            (
                "raw_snapshots_no_update",
                "UPDATE raw_snapshots SET public_locator = 'https://tampered.invalid'",
                "snapshot provenance hash mismatch",
            ),
            (
                "fetch_attempts_no_update",
                "UPDATE fetch_attempts SET row_count = 999",
                "fetch attempt hash mismatch",
            ),
            (
                "source_identities_no_update",
                "UPDATE source_identities SET registry_hash = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'",
                "source identity hash mismatch",
            ),
        )
        for index, (trigger, sql, expected) in enumerate(mutations):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                store = MacroHistoryStore(Path(tmp) / "macro.sqlite3")
                store.initialize()
                record_vix(store, run_id=f"run_integrity_{index}", raw=b"raw-v1")
                with store.connect() as conn:
                    conn.execute(f"DROP TRIGGER {trigger}")
                    conn.execute(sql)
                self.assertTrue(
                    any(expected in item for item in store.verify_integrity()),
                    store.verify_integrity(),
                )

    def test_integrity_reports_missing_table_without_crashing(self) -> None:
        record_vix(self.store, run_id="run_drop_table", raw=b"raw-v1")
        with self.store.connect() as conn:
            conn.execute("DROP TABLE observations")
        problems = self.store.verify_integrity()
        self.assertTrue(any("sqlite structure invalid" in item for item in problems), problems)

    def test_same_period_and_vintage_cannot_carry_conflicting_values(self) -> None:
        record_vix(self.store, run_id="run_vintage_a", raw=b"raw-a", value=18.5)
        with self.assertRaisesRegex(MacroStoreError, "conflicting observation"):
            record_vix(self.store, run_id="run_vintage_b", raw=b"raw-b", value=19.0)

    def test_concurrent_same_fetch_is_single_projection(self) -> None:
        errors: list[Exception] = []

        def worker() -> None:
            try:
                record_vix(self.store, run_id="run_concurrent", raw=b"same")
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([], errors)
        counts = self.store.counts()
        self.assertEqual(1, counts["raw_snapshots"])
        self.assertEqual(1, counts["observations"])
        self.assertEqual(1, counts["fetch_attempts"])

    def test_bls_parser_covers_all_registered_metrics(self) -> None:
        spec = next(row for row in collectors.collection_plan() if row.request_id == "bls_labor_prices")
        rows = spec.parser(bls_fixture(), NOW_ISO, spec)
        self.assertEqual(6, len(rows))
        self.assertEqual(
            {(metric.series_id, metric.metric_key) for metric in spec.metrics},
            {(row.series_id, row.metric_key) for row in rows},
        )

    def test_positive_collection_binds_bls_and_cboe_to_registry(self) -> None:
        plan = {row.request_id: row for row in collectors.collection_plan()}
        specs = (plan["bls_labor_prices"], plan["cboe_vix_history"])
        bls_request = specs[0].build_request(NOW, {})
        cboe_request = specs[1].build_request(NOW, {})
        transport = MappingTransport(
            {
                bls_request.public_locator: collectors.HttpResponse(
                    200,
                    bls_request.public_locator,
                    {"content-type": "application/json"},
                    bls_fixture(),
                ),
                cboe_request.public_locator: collectors.HttpResponse(
                    200,
                    cboe_request.public_locator,
                    {"content-type": "text/csv"},
                    b"DATE,OPEN,HIGH,LOW,CLOSE\n08/06/2026,17,19,16,18.50\n",
                ),
            }
        )
        results = collectors.collect(
            store=self.store,
            transport=transport,
            specs=specs,
            run_id="run_positive",
            now=NOW,
            env={},
        )
        self.assertEqual(["OK", "OK"], [row["status"] for row in results])
        health = collectors.build_health(store=self.store, specs=specs, now=NOW)
        self.assertEqual("COMPLETE", health["report"])
        self.assertEqual(7, health["source_health"]["ok"])
        identities = {
            (row["source_id"], row["provider"], row["independence_group"])
            for row in health["data"]
        }
        self.assertIn(("bls_public_api", "U.S. Bureau of Labor Statistics", "us_bls"), identities)
        self.assertIn(("cboe_vix", "Cboe Global Markets", "cboe"), identities)

    def test_bls_missing_series_is_data_invalid(self) -> None:
        spec = next(row for row in collectors.collection_plan() if row.request_id == "bls_labor_prices")
        payload = json.loads(bls_fixture())
        payload["Results"]["series"].pop()
        with self.assertRaisesRegex(collectors.CollectionError, "omitted requested series"):
            spec.parser(json.dumps(payload).encode("utf-8"), NOW_ISO, spec)

    def test_cboe_fred_and_bea_parsers(self) -> None:
        plan = {row.request_id: row for row in collectors.collection_plan()}
        cboe = plan["cboe_vix_history"].parser(
            b"DATE,OPEN,HIGH,LOW,CLOSE\n08/06/2026,17,19,16,18.50\n",
            NOW_ISO,
            plan["cboe_vix_history"],
        )
        self.assertEqual(18.5, cboe[0].value)
        fred = plan["fred_dgs2"].parser(fred_fixture(), NOW_ISO, plan["fred_dgs2"])
        self.assertEqual("y2", fred[0].metric_key)
        gdp = plan["bea_gdp"].parser(
            bea_fixture("1", "2026Q2", "3.0"), NOW_ISO, plan["bea_gdp"]
        )
        self.assertEqual("real_gdp_qoq_saar", gdp[0].metric_key)
        pce = plan["bea_core_pce"].parser(
            bea_fixture("25", "2026M06", "2.8"), NOW_ISO, plan["bea_core_pce"]
        )
        self.assertEqual("core_pce_price_index", pce[0].metric_key)

    def test_duplicate_json_key_is_rejected(self) -> None:
        spec = next(row for row in collectors.collection_plan() if row.request_id == "fred_dgs2")
        with self.assertRaisesRegex(collectors.CollectionError, "repeats JSON key"):
            spec.parser(b'{"observations":[],"observations":[]}', NOW_ISO, spec)

    def test_unapproved_redirect_is_not_bound_to_official_source(self) -> None:
        spec = next(row for row in collectors.collection_plan() if row.request_id == "cboe_vix_history")
        request = spec.build_request(NOW, {})
        transport = MappingTransport(
            {
                request.public_locator: collectors.HttpResponse(
                    200,
                    "https://example.net/forged.csv",
                    {"content-type": "text/csv"},
                    b"DATE,CLOSE\n08/06/2026,99\n",
                )
            }
        )
        result = collectors.collect(
            store=self.store,
            transport=transport,
            specs=(spec,),
            run_id="run_redirect",
            now=NOW,
            env={},
        )
        self.assertEqual("DATA_INVALID", result[0]["status"])
        self.assertEqual(0, self.store.counts()["raw_snapshots"])
        self.assertEqual(1, self.store.counts()["fetch_attempts"])

    def test_invalid_2xx_payload_is_preserved_but_never_ok(self) -> None:
        spec = next(row for row in collectors.collection_plan() if row.request_id == "cboe_vix_history")
        request = spec.build_request(NOW, {})
        raw = b"not,a,vix,file\n1,2,3,4\n"
        transport = MappingTransport(
            {
                request.public_locator: collectors.HttpResponse(
                    200, request.public_locator, {"content-type": "text/csv"}, raw
                )
            }
        )
        result = collectors.collect(
            store=self.store,
            transport=transport,
            specs=(spec,),
            run_id="run_invalid",
            now=NOW,
            env={},
        )
        self.assertEqual("DATA_INVALID", result[0]["status"])
        self.assertEqual(1, self.store.counts()["raw_snapshots"])
        self.assertEqual(0, self.store.counts()["observations"])
        self.assertEqual("DATA_INVALID", self.store.latest_attempt("cboe_vix", spec.request_id)["status"])

    def test_echoed_bea_key_is_redacted_before_append_only_storage(self) -> None:
        key = "SECRETKEY123BEA"
        spec = next(row for row in collectors.collection_plan() if row.request_id == "bea_gdp")
        request = spec.build_request(NOW, {"BEA_API_KEY": key})
        payload = json.loads(bea_fixture("1", "2026Q2", "3.0"))
        payload["BEAAPI"]["RequestParam"] = {"USERID": key}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        transport = MappingTransport(
            {
                request.public_locator: collectors.HttpResponse(
                    200,
                    "https://apps.bea.gov/api/data/" + key + "?UserID=" + key,
                    {"content-type": "application/json", "etag": key},
                    raw,
                )
            }
        )
        result = collectors.collect(
            store=self.store,
            transport=transport,
            specs=(spec,),
            run_id="run_bea_redaction",
            now=NOW,
            env={"BEA_API_KEY": key},
        )
        self.assertEqual("OK", result[0]["status"])
        with self.store.connect() as conn:
            snapshot = conn.execute("SELECT * FROM raw_snapshots").fetchone()
        self.assertNotIn(key.encode("utf-8"), bytes(snapshot["raw_payload"]))
        self.assertIn(collectors.REDACTION_MARKER, bytes(snapshot["raw_payload"]))
        meta = json.loads(snapshot["transport_meta_json"])
        self.assertTrue(meta["redacted"])
        self.assertEqual(["BEA_API_KEY"], meta["redacted_secret_names"])
        self.assertNotIn(key.encode("utf-8"), self.db.read_bytes())

    def test_missing_credentials_is_explicit_data_blocked(self) -> None:
        spec = next(row for row in collectors.collection_plan() if row.request_id == "fred_dgs2")
        transport = MappingTransport({})
        result = collectors.collect(
            store=self.store,
            transport=transport,
            specs=(spec,),
            run_id="run_no_key",
            now=NOW,
            env={},
        )
        self.assertEqual("DATA_BLOCKED", result[0]["status"])
        self.assertEqual("FRED_API_KEY_MISSING", result[0]["error_code"])
        self.assertEqual(0, transport.calls)
        self.assertEqual(0, self.store.counts()["raw_snapshots"])

    def test_offline_transport_refuses_network(self) -> None:
        spec = next(row for row in collectors.collection_plan() if row.request_id == "cboe_vix_history")
        request = spec.build_request(NOW, {})
        original = os.environ.get("AR_OFFLINE")
        os.environ["AR_OFFLINE"] = "1"
        try:
            with self.assertRaisesRegex(collectors.CollectionError, "disabled by AR_OFFLINE"):
                collectors.UrllibTransport().fetch(request)
        finally:
            if original is None:
                os.environ.pop("AR_OFFLINE", None)
            else:
                os.environ["AR_OFFLINE"] = original

    def test_documented_cli_runs_directly_from_repo_root(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "experiments/macro_os/collectors.py",
                "--db",
                str(Path(self.tmp.name) / "cli.sqlite3"),
                "--health-out",
                str(Path(self.tmp.name) / "health.json"),
                "--source",
                "cboe_vix",
                "--run-id",
                "offline-cli",
            ],
            cwd=REPO_ROOT,
            env={**os.environ, "AR_OFFLINE": "1"},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        health = json.loads((Path(self.tmp.name) / "health.json").read_text())
        self.assertEqual("DATA_BLOCKED", health["report"])
        self.assertEqual("AR_OFFLINE", health["data"][0]["last_error_code"])

    def test_health_is_versioned_and_calibrating_without_block_authority(self) -> None:
        record_vix(self.store, run_id="run_health", raw=b"health")
        spec = next(row for row in collectors.collection_plan() if row.request_id == "cboe_vix_history")
        health = collectors.build_health(store=self.store, specs=(spec,), now=NOW)
        self.assertEqual("COMPLETE", health["report"])
        self.assertEqual("CALIBRATING", health["mode"])
        self.assertEqual(
            {
                "formal_blocking_authority": False,
                "allowed_outputs": ["LABEL", "RISK_BUDGET_CONTEXT"],
                "forbidden_outputs": ["TRADE_ACTION", "DIRECT_BLOCK", "REGIME_CLAIM"],
            },
            health["policy"],
        )
        self.assertEqual(1, health["data"][0]["version_stats"]["snapshots"])
        self.assertEqual(source_row("cboe_vix")[0]["provider"], health["data"][0]["provider"])
        self.assertEqual("DAILY_HISTORY", health["data"][0]["vintage_support"])
        self.assertTrue(health["data"][0]["source_identity_current"])

    def test_health_requires_refetch_after_source_identity_changes(self) -> None:
        record_vix(self.store, run_id="run_old_identity", raw=b"identity-v1")
        spec = next(
            row
            for row in collectors.collection_plan()
            if row.request_id == "cboe_vix_history"
        )
        original_loader = contracts.load_json

        def changed_registry(path: Path) -> dict:
            payload = original_loader(path)
            if path == contracts.SOURCE_REGISTRY:
                payload = copy.deepcopy(payload)
                source = next(
                    row for row in payload["sources"] if row["source_id"] == "cboe_vix"
                )
                source["provider"] = "Cboe Global Markets Renamed"
                unsigned = {key: value for key, value in payload.items() if key != "registry_hash"}
                payload["registry_hash"] = contracts.content_hash(unsigned)
            return payload

        contracts.load_json = changed_registry
        try:
            health = collectors.build_health(store=self.store, specs=(spec,), now=NOW)
        finally:
            contracts.load_json = original_loader
        row = health["data"][0]
        self.assertEqual("STALE", row["status"])
        self.assertFalse(row["source_identity_current"])
        self.assertNotEqual(
            row["source_identity_hash"], row["current_source_identity_hash"]
        )
        self.assertEqual("Cboe Global Markets", row["provider"])
        self.assertEqual("Cboe Global Markets Renamed", row["current_provider"])

    def test_health_marks_old_observation_stale(self) -> None:
        record_vix(
            self.store,
            run_id="run_stale",
            raw=b"stale",
            value=20.0,
        )
        with self.store.connect() as conn:
            conn.execute("DROP TRIGGER observations_no_update")
            conn.execute(
                "UPDATE observations SET observation_at='2026-07-01T00:00:00Z'"
            )
        spec = next(row for row in collectors.collection_plan() if row.request_id == "cboe_vix_history")
        health = collectors.build_health(store=self.store, specs=(spec,), now=NOW)
        self.assertEqual("STALE", health["data"][0]["status"])
        self.assertEqual("PARTIAL", health["report"])

    def test_atomic_health_write_and_secret_free_urls(self) -> None:
        payload = {
            "schema": "ar.macro.source_health",
            "report": "DATA_BLOCKED",
            "mode": "CALIBRATING",
        }
        path = Path(self.tmp.name) / "nested" / "health.json"
        collectors.write_health(path, payload)
        self.assertEqual(payload, json.loads(path.read_text(encoding="utf-8")))
        sanitized = collectors._sanitize_url(
            "https://example.com/path?series=DGS2&api_key=secret&UserID=also-secret"
        )
        self.assertIn("series=DGS2", sanitized)
        self.assertNotIn("secret", sanitized)
        self.assertNotIn("UserID", sanitized)

    def test_failed_attempt_cannot_be_reused_with_new_facts(self) -> None:
        source, registry_hash = source_row("fred_alfred")
        args = dict(
            run_id="same_run",
            request_id="fred_dgs2",
            source=source,
            registry_hash=registry_hash,
            requested_series=["us_treasury_curve"],
            started_at=NOW_ISO,
            completed_at=NOW_ISO,
            public_locator="source://fred_alfred/fred_dgs2",
            status="DATA_BLOCKED",
            error_code="NO_KEY",
            error_message="key missing",
        )
        self.store.record_failure(**args)
        changed = copy.deepcopy(args)
        changed["error_message"] = "different fact"
        with self.assertRaisesRegex(MacroStoreError, "reused with different"):
            self.store.record_failure(**changed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
