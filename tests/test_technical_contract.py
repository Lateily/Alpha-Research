"""Synthetic, offline contract tests; no market or production data."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROFILE_ID = "DAILY_SWEEP_RECLAIM_CANDIDATE_0_1"
STAMP = "2026-10-09T15:00:00+08:00"
HASH = "a" * 64
ROLE_PATHS = {
    "bars": "inputs/bars.json",
    "calendar": "inputs/trade-calendar.json",
    "corporate_actions": "inputs/corporate-actions.json",
    "flow": "inputs/settled-flow.json",
    "context": "inputs/sector-context.json",
    "research_binding": "inputs/research-binding.json",
}


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class TechnicalContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = importlib.import_module("experiments.research_workflows.technical_contract")
        self.profiles = importlib.import_module("experiments.research_workflows.technical_profiles")
        self.temp = tempfile.TemporaryDirectory(prefix="technical-contract-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.pack = self.root / "pack"
        (self.pack / "inputs").mkdir(parents=True)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.external = encode({"synthetic": True, "decision": "SELECT"})
        (self.evidence / "packet.json").write_bytes(self.external)
        self.ref = {"root_alias": "frozen", "path": "packet.json",
                    "sha256": sha(self.external), "pointer": "/decision"}
        self.profile = self.profiles.load_profile(PROFILE_ID)
        bar = {"ts_code": "600000.SH", "trade_date": "20261009",
               "bar_close_at": STAMP, "available_at": STAMP,
               "open": "10.00", "high": "10.20", "low": "9.90", "close": "10.10",
               "volume": "1000", "amount": "10100.00", "price_basis": "RAW", "currency": "CNY"}
        self.payloads = {
            "bars": {"schema_version": "technical-bars.v1", "timeframe": "1d", "rows": [bar]},
            "calendar": {"schema_version": "technical-calendar.v1", "version": "synthetic-1",
                         "source_hash": HASH, "coverage": {"start": "20261009", "end": "20261009"},
                         "days": [{"trade_date": "20261009", "is_open": True,
                                   "close_at": STAMP, "suspensions": []}]},
            "corporate_actions": {"schema_version": "technical-actions.v1", "ts_code": "600000.SH",
                                  "price_basis": "RAW", "coverage": {"start": "20261009", "end": "20261009"},
                                  "verified": True, "actions": []},
            "flow": {"schema_version": "technical-flow.v1", "ts_code": "600000.SH",
                     "rows": [{"trade_date": "20261009", "available_at": STAMP,
                               "settlement_status": "SETTLED", "main_net_flow": "20.00",
                               "main_net_flow_missing_reason": None, "currency": "CNY"}]},
            "context": {"schema_version": "technical-sector-context.v1", "context_id": "ctx-1",
                        "industry_key": "SYNTHETIC", "as_of": STAMP, "data_cutoff": STAMP,
                        "source_refs": [self.ref], "market_state": "RISK_ON", "sector_state": "CONFIRMED",
                        "rationale": "Synthetic discussion", "counter_evidence": ["Synthetic counterexample"],
                        "authored_by": "synthetic-author", "authored_at": STAMP, "review_status": "PENDING",
                        "reviewed_by": None, "reviewed_at": None,
                        "invalidation_conditions": ["Synthetic invalidation"], "supersedes": None,
                        "context_hash": HASH, "review_receipt": None, "industry_mapping": self.ref,
                        "is_human_judgment": True, "automated_decision": False, "claim_allowed": False},
            "research_binding": {"schema_version": "technical-research-binding.v1", "ts_code": "600000.SH",
                                 "industry_key": "SYNTHETIC", "packet": self.ref, "decision": self.ref,
                                 "packet_hash": sha(self.external), "decision_row_hash": HASH,
                                 "cohort_id": "cohort-1", "causal_cluster_id": "cluster-1",
                                 "method_version": "synthetic-1", "research_case": None,
                                 "thesis": {"source_ref": None, "missing_reason": "NOT_FROZEN"},
                                 "valuation": {"source_ref": None, "missing_reason": "NOT_FROZEN"},
                                 "red_flags": {"ts_code": "600000.SH", "as_of": "20261009",
                                               "available_at": STAMP, "coverage_start": "20261009",
                                               "coverage_end": "20261009", "verdict": "UNKNOWN",
                                               "reasons": ["SYNTHETIC_ONLY"], "source_refs": [self.ref]}},
        }
        # Full synthetic daily coverage; still no upstream research authority.
        dates = [(datetime(2026, 10, 9) - timedelta(days=59-i)).strftime('%Y%m%d') for i in range(60)]
        self.payloads['bars']['rows'] = [dict(bar, trade_date=d, bar_close_at=self.stamp(d),
                                            available_at=self.stamp(d)) for d in dates]
        self.payloads['calendar']['coverage']['start'] = dates[0]
        self.payloads['calendar']['days'] = [dict(trade_date=d, is_open=True,
                                                close_at=self.stamp(d), suspensions=[]) for d in dates]
        self.calendar_hash()
        self.payloads['corporate_actions']['coverage']['start'] = dates[0]
        self.payloads['research_binding'].update(packet=None, decision=None, packet_hash=None,
                                                decision_row_hash=None, cohort_id=None,
                                                causal_cluster_id=None, method_version=None, u4_sources=None)
        self.request = {"schema_version": "technical-request.v1", "workflow_version": "technical-workflow.v0.1",
                        "rule_profile_hash": self.profile["profile_hash"], "mode": "HISTORICAL_REPLAY",
                        "pack_id": "synthetic-1", "ts_code": "600000.SH", "industry_key": "SYNTHETIC",
                        "as_of": STAMP, "data_cutoff": STAMP, "generated_at": STAMP,
                        "window_id": "window-1", "exposure_status": "EXPOSED", "source_manifest_hash": HASH}
        self.manifest = {"schema_version": "technical-source-manifest.v1", "sources": []}
        for role, path in ROLE_PATHS.items():
            self.manifest["sources"].append({
                "role": role, "path": path, "origin": "synthetic-fixture", "sha256": HASH,
                "identity": {"ts_code": "600000.SH", "industry_key": "SYNTHETIC"},
                "evidence_grade": "E3", "published_at": STAMP, "available_at": STAMP, "captured_at": STAMP,
                "raw_unit": {"price": "CNY", "volume": "shares", "amount": "CNY"},
                "normalized_unit": {"price": "CNY", "volume": "shares", "amount": "CNY"},
                "licensing": {"license_id": "synthetic", "display_scope": "LOCAL_ONLY"},
                "missing_reason": None,
            })
        self.registry = self.root / "operator-registry.json"
        self.roots = {"frozen": self.evidence}
        self.seal(register=True)

    @staticmethod
    def stamp(date):
        return datetime.strptime(date, '%Y%m%d').strftime('%Y-%m-%dT15:00:00+08:00')

    def calendar_hash(self):
        calendar = self.payloads['calendar']
        calendar['source_hash'] = sha(encode({k: v for k, v in calendar.items() if k != 'source_hash'}))

    def seal(self, register=False, raw_roles=None):
        raw_roles = raw_roles or {}
        sums = {}
        for source in self.manifest["sources"]:
            role = source["role"]
            path = self.pack / source["path"]
            if source["missing_reason"] is not None:
                source["sha256"] = None
                if path.exists():
                    path.unlink()
                continue
            raw = raw_roles.get(role, encode(self.payloads[role]))
            path.write_bytes(raw)
            source["sha256"] = sums[source["path"]] = sha(raw)
        manifest = encode(self.manifest)
        (self.pack / "source-manifest.json").write_bytes(manifest)
        self.request["source_manifest_hash"] = sha(manifest)
        request = encode(self.request)
        (self.pack / "request.json").write_bytes(request)
        sums.update({"request.json": sha(request), "source-manifest.json": sha(manifest)})
        (self.pack / "SHA256SUMS").write_text(
            "".join(f"{digest}  {path}\n" for path, digest in sorted(sums.items())), encoding="ascii")
        if register:
            self.binding = {"pack_root": str(self.pack), "request_hash": sha(request),
                            "source_manifest_hash": sha(manifest), "profile_id": PROFILE_ID,
                            "profile_hash": self.profile["profile_hash"], "mode": self.request["mode"]}
            self.registry.write_bytes(encode({"schema_version": "technical-registry.v1",
                                              "packs": {"synthetic-1": self.binding},
                                              "evidence_roots": {"frozen": str(self.evidence)}}))

    def load(self):
        return self.contract.load_registered_pack(self.registry, "synthetic-1", self.roots)

    def refused(self, reason):
        result = self.load()
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn(reason, result["reason_codes"])
        self.assertEqual(result["inputs"], {})
        return result

    def test_semantic_result_never_claims_missing_authority(self):
        result = self.load()
        self.assertEqual(set(result), {"schema", "request", "source_manifest", "inputs", "bindings",
                                      "quality", "status", "reason_codes", "authority"})
        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertEqual(result["quality"]["structural_input_status"], "STRUCTURALLY_VALID")
        self.assertEqual(result["quality"]["promotion_input_status"], "DATA_BLOCKED")
        self.assertIn("HISTORICAL_NO_U4_AUTHORITY", result["reason_codes"])
        self.assertNotIn("SEMANTIC_VALIDATION_NOT_IMPLEMENTED", result["reason_codes"])
        self.assertEqual(set(result["inputs"]), set(ROLE_PATHS))
        self.assertEqual(result["authority"], {"sample_purpose": "WORKFLOW_DEBUG", "claim_allowed": False,
                                             "no_trade_flag": True, "production_authority": False,
                                             "u4_authority": False, "paper_registration_authority": False,
                                             "trade_authority": False})

    def test_duplicate_nested_key_refused(self):
        raw = encode(self.payloads["bars"]).replace(b'"close": "10.10"', b'"close": "10.10", "close": "10.10"')
        self.seal(register=True, raw_roles={"bars": raw})
        self.refused("DUPLICATE_JSON_KEY")

    def test_nonfinite_and_bool_price_refused(self):
        for value, reason in (("NaN", "NONFINITE_JSON"), ("Infinity", "NONFINITE_JSON"),
                              ("-Infinity", "NONFINITE_JSON"), ("true", "INVALID_DECIMAL"),
                              ('"NaN"', "INVALID_DECIMAL"), ('"Infinity"', "INVALID_DECIMAL")):
            with self.subTest(value=value):
                raw = encode(self.payloads["bars"]).replace(b'"open": "10.00"', ('"open": ' + value).encode())
                self.seal(register=True, raw_roles={"bars": raw})
                self.refused(reason)

    def test_decimal_tick_precision_preserved(self):
        bar = self.payloads["bars"]["rows"][0]
        for field in ("open", "high", "low", "close"):
            bar[field] = "123456789012345678901234567890.01"
        self.seal(register=True)
        result = self.load()
        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertEqual(result["inputs"]["bars"]["rows"][0]["close"], bar["close"])
        bar["close"] = "123456789012345678901234567890.0100000000000000000001"
        bar["high"] = "123456789012345678901234567890.02"
        self.seal(register=True)
        self.refused("PRICE_OFF_TICK")

    def test_numeric_json_tokens_never_pass_through_float(self):
        raw = encode(self.payloads["bars"])
        for field in ("open", "high", "low", "close"):
            raw = raw.replace(('"' + field + '": "' + self.payloads["bars"]["rows"][0][field] + '"').encode(),
                              ('"' + field + '": 123456789012345678901234567890.0100').encode())
        self.seal(register=True, raw_roles={"bars": raw})
        self.assertEqual(self.load()["inputs"]["bars"]["rows"][0]["close"],
                         "123456789012345678901234567890.0100")

    def test_parent_symlink_refused(self):
        actual = self.pack / "actual-inputs"
        (self.pack / "inputs").rename(actual)
        (self.pack / "inputs").symlink_to(actual, target_is_directory=True)
        self.refused("UNSAFE_PATH")

    def test_pack_ancestor_symlink_refused(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        binding = dict(self.binding, pack_root=str(alias / "pack"))
        result = self.contract.validate_pack(alias / "pack", binding, self.roots, self.profile)
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn("UNSAFE_PATH", result["reason_codes"])

    def test_resealed_package_does_not_change_registry_binding(self):
        self.assertEqual(self.load()["status"], "DATA_BLOCKED")
        before = self.registry.read_bytes()
        self.payloads["bars"]["rows"][0]["close"] = "10.11"
        self.seal()
        self.refused("REGISTRY_MANIFEST_HASH_MISMATCH")
        self.assertEqual(self.registry.read_bytes(), before)

    def test_request_reseal_does_not_change_registry_binding(self):
        self.request["window_id"] = "another-window"
        self.seal()
        self.refused("REGISTRY_REQUEST_HASH_MISMATCH")

    def test_profile_override_refused(self):
        modified = copy.deepcopy(self.profile)
        modified["parameters"]["tick_cny"] = "0.02"
        result = self.contract.validate_pack(self.pack, self.binding, self.roots, modified)
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn("PROFILE_OVERRIDE", result["reason_codes"])
        self.assertEqual(result["inputs"], {})

    def test_profile_boolean_cannot_impersonate_integer_parameter(self):
        modified = copy.deepcopy(self.profile)
        modified["parameters"]["minimum_sweep_ticks"] = True
        result = self.contract.validate_pack(self.pack, self.binding, self.roots, modified)
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn("PROFILE_OVERRIDE", result["reason_codes"])

    def test_unknown_nested_bar_field_refused(self):
        self.assertEqual(self.load()["status"], "DATA_BLOCKED")
        self.payloads["bars"]["rows"][0]["production_authority"] = True
        self.seal(register=True)
        self.refused("EXACT_FIELDS")

    def test_null_flow_has_explicit_missing_reason(self):
        row = self.payloads["flow"]["rows"][0]
        row["main_net_flow"] = None
        self.seal(register=True)
        self.refused("INVALID_IDENTIFIER")
        row["main_net_flow_missing_reason"] = "NOT_AVAILABLE"
        self.seal(register=True)
        result = self.load()
        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertIsNone(result["inputs"]["flow"]["rows"][0]["main_net_flow"])
        self.assertEqual(result["inputs"]["flow"]["rows"][0]["main_net_flow_missing_reason"], "NOT_AVAILABLE")

    def test_all_role_top_levels_reject_unknown_fields(self):
        for role in ROLE_PATHS:
            with self.subTest(role=role):
                self.payloads[role]["unauthorized"] = True
                self.seal(register=True)
                self.refused("EXACT_FIELDS")
                del self.payloads[role]["unauthorized"]

    def test_valid_action_suspension_and_review_reference_shapes(self):
        self.payloads["corporate_actions"]["actions"] = [
            {"action_id": "act-1", "effective_date": "20261009", "available_at": STAMP,
             "kind": "SPLIT", "verified": True, "source_refs": [self.ref]}]
        self.payloads["calendar"]["days"][0]["suspensions"] = [
            {"ts_code": "600000.SH", "status": "VERIFIED", "source_refs": [self.ref]}]
        self.payloads["context"].update(review_receipt=self.ref, reviewed_at=STAMP,
                                        reviewed_by="synthetic-reviewer", review_status="REVIEWED")
        suspension = self.payloads['calendar']['days'][0]['suspensions'][0]
        raw = encode({'trade_date': self.payloads['calendar']['days'][0]['trade_date'],
                      'ts_code': '600000.SH', 'status': 'VERIFIED'})
        (self.evidence / 'suspension.json').write_bytes(raw)
        suspension['source_refs'] = [dict(self.ref, path='suspension.json', sha256=sha(raw), pointer='')]
        # Shape acceptance is not authentication of a human review.
        self.payloads['context'].update(review_status='PENDING', review_receipt=None)
        self.seal(register=True)
        result = self.load()
        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertEqual(result["quality"]["roles"]["corporate_actions"]["status"], "STRUCTURALLY_VALID")
        self.assertEqual(result["quality"]["promotion_input_status"], "DATA_BLOCKED")

    def test_socket_creation_disabled_at_public_loader(self):
        import socket
        from unittest.mock import patch
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
                patch.object(socket, "getaddrinfo", side_effect=AssertionError("network forbidden")):
            self.assertEqual(self.load()["status"], "DATA_BLOCKED")

    def test_profile_is_detached_and_hash_is_semantic(self):
        profile = self.profiles.load_profile(PROFILE_ID)
        expected = sha(encode({key: value for key, value in profile.items() if key != "profile_hash"}))
        self.assertEqual(profile["profile_hash"], expected)
        self.assertEqual(profile["parameters"]["minimum_history_bars"], 60)
        self.assertEqual(profile["parameters"]["pivot_left_bars"], 2)
        self.assertEqual(profile["parameters"]["reclaim_following_bars"], 3)
        self.assertEqual(profile["parameters"]["stop_atr_multiplier"], "0.25")
        self.assertTrue(all(row["implementation_state"] in {"NOT_IMPLEMENTED", "UNSUPPORTED_TIMEFRAME"}
                            for row in profile["method_catalog"]))
        profile["parameters"]["tick_cny"] = "99"
        self.assertEqual(self.profiles.load_profile(PROFILE_ID)["parameters"]["tick_cny"], "0.01")
        with self.assertRaises(ValueError):
            self.profiles.load_profile("unknown")

    def test_exact_nested_schemas_all_roles(self):
        locations = [("bars", ["rows", 0]), ("calendar", ["coverage"]), ("calendar", ["days", 0]),
                     ("corporate_actions", ["coverage"]), ("flow", ["rows", 0]),
                     ("context", []), ("context", ["source_refs", 0]),
                     ("research_binding", ["red_flags"]), ("research_binding", ["thesis"])]
        for role, keys in locations:
            for mutation in ("extra", "missing"):
                with self.subTest(role=role, keys=keys, mutation=mutation):
                    old = copy.deepcopy(self.payloads)
                    target = self.payloads[role]
                    for key in keys:
                        target = target[key]
                    if mutation == "extra":
                        target["unauthorized"] = True
                    else:
                        target.pop(next(iter(target)))
                    self.seal(register=True)
                    self.refused("EXACT_FIELDS")
                    self.payloads = old

    def test_exact_nested_action_and_suspension(self):
        self.payloads["corporate_actions"]["actions"] = [
            {"action_id": "act-1", "effective_date": "20261009", "available_at": STAMP,
             "kind": "SPLIT", "verified": True, "source_refs": [self.ref], "extra": True}]
        self.seal(register=True)
        self.refused("EXACT_FIELDS")
        self.payloads["corporate_actions"]["actions"] = []
        self.payloads["calendar"]["days"][0]["suspensions"] = [
            {"ts_code": "600000.SH", "status": "VERIFIED", "source_refs": [self.ref], "extra": True}]
        self.seal(register=True)
        self.refused("EXACT_FIELDS")

    def test_exact_request_manifest_and_registry(self):
        for location in (self.request, self.manifest, self.manifest["sources"][0],
                         self.manifest["sources"][0]["identity"], self.manifest["sources"][0]["raw_unit"],
                         self.manifest["sources"][0]["licensing"]):
            location["extra"] = True
            self.seal(register=True)
            self.refused("EXACT_FIELDS")
            del location["extra"]
        self.seal(register=True)
        registry = json.loads(self.registry.read_text())
        registry["packs"]["synthetic-1"]["extra"] = True
        self.registry.write_bytes(encode(registry))
        self.refused("EXACT_FIELDS")

    def test_missing_context_preserves_structural_observation_only(self):
        next(s for s in self.manifest["sources"] if s["role"] == "context")["missing_reason"] = "NOT_FROZEN"
        self.seal(register=True)
        result = self.load()
        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertIsNone(result["inputs"]["context"])
        self.assertEqual(result["quality"]["roles"]["context"]["reason_codes"], ["NOT_FROZEN"])
        self.assertEqual(result["quality"]["structural_input_status"], "STRUCTURALLY_VALID")
        self.assertEqual(result["inputs"]["bars"]["rows"][0]["close"], "10.10")

    def test_unexpected_missing_file_is_data_blocked_not_ready(self):
        (self.pack / ROLE_PATHS["context"]).unlink()
        result = self.load()
        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertIn("SOURCE_MISSING", result["reason_codes"])
        self.assertIsNone(result["inputs"]["context"])
        self.assertEqual(result["quality"]["promotion_input_status"], "DATA_BLOCKED")

    def test_external_evidence_reopened_and_byte_hash_checked(self):
        self.assertEqual(self.load()["bindings"]["evidence_byte_hashes"], {"frozen:packet.json": sha(self.external)})
        (self.evidence / "packet.json").write_bytes(b'{"synthetic":true,"decision":"REJECT"}')
        self.refused("EVIDENCE_HASH_MISMATCH")

    def test_root_configuration_cannot_override_registry(self):
        other = self.root / "other"
        other.mkdir()
        result = self.contract.load_registered_pack(self.registry, "synthetic-1", {"frozen": other})
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn("EVIDENCE_ROOT_OVERRIDE", result["reason_codes"])

    def test_double_slash_evidence_root_cannot_hide_registry_in_tree(self):
        self.assertEqual(self.load()["status"], "DATA_BLOCKED")
        inside = self.evidence / "operator-registry.json"
        registry = json.loads(self.registry.read_text())
        inside.write_bytes(encode(registry))
        control = self.contract.load_registered_pack(inside, "synthetic-1", self.roots)
        self.assertEqual(control["status"], "REFUSED")
        self.assertIn("REGISTRY_IN_INPUT_TREE", control["reason_codes"])
        alias = Path("/" + str(self.evidence))
        registry["evidence_roots"]["frozen"] = str(alias)
        inside.write_bytes(encode(registry))
        result = self.contract.load_registered_pack(inside, "synthetic-1", {"frozen": alias})
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn("UNSAFE_PATH", result["reason_codes"])
        self.assertEqual(result["inputs"], {})

    def test_double_slash_evidence_root_cannot_alias_pack(self):
        self.assertEqual(self.load()["status"], "DATA_BLOCKED")
        registry = json.loads(self.registry.read_text())
        registry["evidence_roots"]["frozen"] = str(self.pack)
        self.registry.write_bytes(encode(registry))
        control = self.contract.load_registered_pack(self.registry, "synthetic-1", {"frozen": self.pack})
        self.assertEqual(control["status"], "REFUSED")
        self.assertIn("OVERLAPPING_INPUT_ROOTS", control["reason_codes"])
        alias = Path("/" + str(self.pack))
        registry["evidence_roots"]["frozen"] = str(alias)
        self.registry.write_bytes(encode(registry))
        result = self.contract.load_registered_pack(self.registry, "synthetic-1", {"frozen": alias})
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn("UNSAFE_PATH", result["reason_codes"])
        self.assertEqual(result["inputs"], {})

    def test_double_slash_registry_path_refused(self):
        self.assertEqual(self.load()["status"], "DATA_BLOCKED")
        alias = Path("/" + str(self.registry))
        result = self.contract.load_registered_pack(alias, "synthetic-1", self.roots)
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn("UNSAFE_PATH", result["reason_codes"])
        self.assertEqual(result["inputs"], {})

    def test_out_of_range_timestamp_offsets_refused_by_loader(self):
        for offset in ("Z", "+08:00", "-08:00", "+23:59", "-23:59", "+00:59"):
            with self.subTest(valid_offset=offset):
                self.request["generated_at"] = "2026-10-09T15:00:00" + offset
                self.seal(register=True)
                self.assertEqual(self.load()["status"], "DATA_BLOCKED")
        for offset in ("+08:60", "+01:99", "-08:60", "-01:99", "+24:00", "-24:00", "+99:00"):
            with self.subTest(invalid_offset=offset):
                self.request["generated_at"] = "2026-10-09T15:00:00" + offset
                self.seal(register=True)
                self.refused("INVALID_TIMESTAMP")

    def test_no_input_self_registration(self):
        registry = json.loads(self.registry.read_text())
        registry["packs"] = {}
        self.registry.write_bytes(encode(registry))
        self.refused("PACK_NOT_REGISTERED")

    def test_hashes_are_bytes_not_reencoded_payload(self):
        raw = json.dumps(self.payloads["bars"], separators=(",", ":")).encode()
        self.seal(register=True, raw_roles={"bars": raw})
        result = self.load()
        self.assertEqual(result["bindings"]["source_byte_hashes"][ROLE_PATHS["bars"]], sha(raw))
        self.assertNotEqual(sha(raw), sha(encode(self.payloads["bars"])))

    def test_hardlink_and_leaf_symlink_refused(self):
        path = self.pack / ROLE_PATHS["bars"]
        alias = self.root / "linked"
        os.link(path, alias)
        self.refused("LINKED_FILE")
        alias.unlink()
        path.unlink()
        path.symlink_to(self.evidence / "packet.json")
        self.refused("UNSAFE_PATH")

    def test_path_escape_and_extra_file_refused(self):
        self.manifest["sources"][0]["path"] = "../outside.json"
        manifest = encode(self.manifest)
        (self.pack / "source-manifest.json").write_bytes(manifest)
        self.binding["source_manifest_hash"] = sha(manifest)
        result = self.contract.validate_pack(self.pack, self.binding, self.roots, self.profile)
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn("UNSAFE_PATH", result["reason_codes"])
        self.manifest["sources"][0]["path"] = ROLE_PATHS["bars"]
        self.seal(register=True)
        (self.pack / "rogue.json").write_text("{}")
        self.refused("PACKAGE_LAYOUT")

    def test_bounded_file_and_row_count(self):
        path = self.pack / ROLE_PATHS["bars"]
        with path.open("r+b") as handle:
            handle.truncate(self.contract.MAX_FILE_BYTES + 1)
        self.refused("FILE_TOO_LARGE")
        self.payloads["bars"]["rows"] = [self.payloads['bars']['rows'][0]] * (self.contract.MAX_ROWS + 1)
        self.seal(register=True)
        self.refused("ROW_LIMIT")

    def test_json_depth_and_decimal_length_bounded(self):
        raw = b"[" * 80 + b"0" + b"]" * 80
        self.seal(register=True, raw_roles={"bars": raw})
        self.refused("JSON_DEPTH_LIMIT")
        self.payloads["bars"]["rows"][0]["open"] = "1" * 200
        self.seal(register=True)
        self.refused("INVALID_DECIMAL")

    def test_escaped_invalid_unicode_is_refused_not_returned(self):
        context = copy.deepcopy(self.payloads["context"])
        context["rationale"] = "bad\ud800"
        raw = json.dumps(context, ensure_ascii=True).encode("ascii")
        self.seal(register=True, raw_roles={"context": raw})
        self.refused("INVALID_JSON")

    def test_identifier_timestamp_and_boolean_types_are_exact(self):
        for field, value, reason in (("pack_id", 123, "INVALID_IDENTIFIER"),
                                     ("generated_at", "2026-10-09T15:00:00", "INVALID_TIMESTAMP")):
            old = self.request[field]
            self.request[field] = value
            self.seal(register=True)
            self.refused(reason)
            self.request[field] = old
        self.payloads["context"]["is_human_judgment"] = 1
        self.seal(register=True)
        self.refused("INVALID_BOOLEAN")

    def test_ohlc_and_date_order_are_structural_guards(self):
        bar = self.payloads["bars"]["rows"][0]
        bar["high"] = "9.00"
        self.seal(register=True)
        self.refused("OHLC_INCONSISTENT")
        bar["high"] = "10.20"
        self.payloads["bars"]["rows"].append(copy.deepcopy(bar))
        self.seal(register=True)
        self.refused("BAR_DATE_ORDER")

    def test_sums_and_role_sets_exact(self):
        (self.pack / "SHA256SUMS").write_text("0" * 64 + "  request.json\n")
        self.refused("SUMS_MISMATCH")
        self.manifest["sources"][1]["role"] = "bars"
        self.seal(register=True)
        self.refused("SOURCE_ROLES")

    def test_registry_is_not_inside_input_tree(self):
        inside = self.pack / "operator-registry.json"
        inside.write_bytes(self.registry.read_bytes())
        result = self.contract.load_registered_pack(inside, "synthetic-1", self.roots)
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn("REGISTRY_IN_INPUT_TREE", result["reason_codes"])

    def test_read_only_and_cross_path_results(self):
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.root.rglob("*") if path.is_file()}
        original = self.load()
        other = self.root / "pack-copy"
        import shutil
        shutil.copytree(self.pack, other)
        binding = dict(self.binding, pack_root=str(other))
        replay = self.contract.validate_pack(other, binding, self.roots, self.profile)
        self.assertEqual(original, replay)
        for path, (raw, mtime) in before.items():
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mtime_ns, mtime)


class TechnicalSemanticTests(unittest.TestCase):
    setUp = TechnicalContractTests.setUp
    seal = TechnicalContractTests.seal
    load = TechnicalContractTests.load
    refused = TechnicalContractTests.refused
    stamp = staticmethod(TechnicalContractTests.stamp)
    calendar_hash = TechnicalContractTests.calendar_hash

    def source(self, name, value, pointer=''):
        raw = encode(value)
        (self.evidence / name).write_bytes(raw)
        return dict(root_alias='frozen', path=name, sha256=sha(raw), pointer=pointer)

    def ready_observation(self):
        rb = self.payloads['research_binding']
        flags = dict(rb['red_flags'], verdict='CLEAR', reasons=[], source_refs=[])
        rb['red_flags'] = flags
        self.red_flag_originals()
        context = self.payloads['context']
        context.update(review_status='REVIEWED', reviewed_by='synthetic-reviewer', reviewed_at=STAMP)
        context['source_refs'] = [self.source('discussion.json', {
            'schema_version': 'technical-context-source.v1', 'industry_key': 'SYNTHETIC',
            'as_of': STAMP, 'published_at': STAMP, 'available_at': STAMP,
            'content': 'Synthetic discussion evidence'})]
        context['industry_mapping'] = self.source('mapping.json', {
            'schema_version': 'technical-industry-mapping.v1', 'ts_code': '600000.SH',
            'industry_key': 'SYNTHETIC', 'coverage_start': '20260811', 'coverage_end': '20261009',
            'published_at': STAMP, 'available_at': STAMP})
        self.context_receipt()
        flow = self.payloads['flow']['rows'][-1]
        self.payloads['flow']['rows'] = [dict(flow, trade_date='20261008', available_at=self.stamp('20261008')), flow]

    def red_flag_originals(self, e1_active=False, u3_active=False):
        legacy_path = str(Path(__file__).resolve().parents[1] / 'experiments/research_funnel')
        sys.path.insert(0, legacy_path)
        try:
            from experiments.research_funnel import e1_event_layer as e1
            from experiments.research_funnel import security_registry as registry
            from experiments.research_funnel import closure_experiment as closure
        finally:
            sys.path.remove(legacy_path)
        code, industry = self.request['ts_code'], self.request['industry_key']
        u0 = registry.build_registry([dict(ts_code=code, symbol=code.split('.')[0],
            name='Synthetic', area='Synthetic', industry=industry, market='main', exchange='SSE',
            list_status='L', list_date='20200101', delist_date='')], as_of='20261009',
            generated_at=STAMP, liquidity_by_code={code: [30000000.0] * 10}, traded_as_of={code})
        periods = ['20260630', '20260331', '20251231', '20250930']
        incomes = [dict(ts_code=code, end_date=period, ann_date='20260830', report_type='1',
                        n_income_attr_p=value) for period, value in zip(periods,
                            [-10.0 if e1_active else 60.0, 30.0, 100.0, 80.0])]
        layer = e1.build_event_layer(u0, {'income_vip': incomes}, as_of='20261009',
            generated_at=STAMP, periods=periods, source_calls=[dict(endpoint=endpoint,
                period=period, status='OK', capped=False) for endpoint in e1.ENDPOINTS for period in periods])
        e1.validate_event_layer(layer)
        row = dict(ts_code=code, completeness=dict(verdict='COMPLETE', covered=6, of=6, missing=[]),
                   dims={name: {'synthetic': True} for name in closure.BATTERY_DIMENSIONS})
        row['dims']['基本面'] = {'红旗闸门': 'RED_FLAG' if u3_active else 'PASS'}
        battery = dict(target_trade_date='20261009', data=dict(checked_at='20261009', results=[row]))
        closure.validate_battery_evidence(battery, '20261009')
        descriptor = dict(schema_version='technical-red-flag-sources.v1', ts_code=code,
            industry_key=industry, as_of='20261009', published_at=STAMP, available_at=STAMP,
            e1_ref=self.source('e1-original.json', layer), u3_ref=self.source('u3-original.json', battery))
        self.payloads['research_binding']['red_flags']['source_refs'] = [self.source('flags.json', descriptor)]
        return descriptor

    def context_receipt(self, reviewed_at=STAMP):
        context = self.payloads['context']
        body = {k: v for k, v in context.items() if k not in {'context_hash', 'review_receipt'}}
        context['context_hash'] = sha(encode(body))
        context['review_receipt'] = self.source('review.json', {
            'schema_version': 'technical-context-review.v1', 'context_id': context['context_id'],
            'context_hash': context['context_hash'], 'review_status': context['review_status'],
            'reviewed_by': context['reviewed_by'], 'reviewed_at': reviewed_at})

    def u4(self, selected=True):
        # Existing packet, intent, event and closure builders, never a ledger writer.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        fixtures = importlib.import_module('test_u4_decision_ledger')
        ledger = fixtures.ledger
        packet = fixtures.packet_fixture()
        draft = fixtures.draft_for(packet)
        rows, items = ledger._validate_draft(packet, draft)
        intent = ledger._build_packet_intent(packet, draft, items, rows)
        registered = fixtures.REGISTERED_AT + '+08:00'
        records = [dict(kind=ledger.INTENT_KIND, id=intent['intent_id'],
                        ts=fixtures.REGISTERED_AT, payload=intent)]
        events = []
        for item in intent['candidate_intents']:
            event = ledger._build_event(item, sequence=len(events)+1,
                                        previous_hash=events[-1]['record_hash'] if events else None,
                                        registered_at=registered)
            events.append(event)
            records.append(dict(kind=ledger.EVENT_KIND, id=event['decision_id'],
                                ts=fixtures.REGISTERED_AT, payload=event))
        closed = ledger._build_closure(packet, events, intent, tail_sequence=len(events),
                                       tail_hash=events[-1]['record_hash'])
        records.append(dict(kind=ledger.CLOSURE_KIND, id=closed['closure_id'],
                            ts=fixtures.REGISTERED_AT, payload=closed))
        from experiments.execution_tracker import event_ledger
        for index, record in enumerate(records):
            record.update(seq=index, prev=records[index-1]['hash'] if index else event_ledger.GENESIS_PREV)
            record['hash'] = event_ledger.record_hash(record)
        ledger._replay_records(records)
        code = fixtures.SELECT_CODES[0] if selected else fixtures.REJECT_CODE
        event = next(e for e in events if e['candidate']['ts_code'] == code)
        files = {}
        for path in sorted(fixtures.SOURCE_BUNDLE.iterdir()):
            files['bundle/' + path.name] = self.source('u4-' + path.name, json.loads(path.read_bytes()))
        descriptor = {'schema_version': 'technical-u4-sources.v1', 'files': files,
                      'bundle_ref': 'bundle', 'feature_health_ref': None,
                      'funnel_health_ref': None, 'diagnostic_ref': None, 'cyclical_flags_ref': None}
        rb = self.payloads['research_binding']
        rb.update(packet=self.source('u4-packet.json', packet),
                  decision=self.source('u4-records.json', records, '/1/payload'),
                  packet_hash=packet['packet_hash'], decision_row_hash=event['record_hash'],
                  u4_sources=self.source('u4-sources.json', descriptor),
                  ts_code=code, industry_key=event['candidate']['industry_code'],
                  cohort_id=event['candidate']['cohort_id'],
                  causal_cluster_id=event['candidate']['causal_cluster_id'], method_version=event['method_version'])
        index = next(i for i, r in enumerate(records) if r.get('payload', {}).get('decision_id') == event['decision_id'])
        rb['decision']['pointer'] = f'/{index}/payload'
        self.request.update(ts_code=code, industry_key=rb['industry_key'], mode='PROSPECTIVE_RESEARCH', exposure_status='UNEXPOSED')
        for role in ('bars', 'corporate_actions', 'flow'):
            if role == 'bars':
                for bar in self.payloads[role]['rows']:
                    bar['ts_code'] = code
            else:
                self.payloads[role]['ts_code'] = code
        rb['red_flags']['ts_code'] = code
        # The legacy U4 fixture uses invented non-security codes, not current E1 originals.
        rb['red_flags'].update(verdict='UNKNOWN', source_refs=[])
        self.payloads['context']['industry_key'] = rb['industry_key']
        self.payloads['context']['source_refs'] = [self.source('discussion.json', {
            'schema_version': 'technical-context-source.v1', 'industry_key': rb['industry_key'],
            'as_of': STAMP, 'published_at': STAMP, 'available_at': STAMP, 'content': 'Synthetic evidence'})]
        self.payloads['context']['industry_mapping'] = self.source('mapping.json', {
            'schema_version': 'technical-industry-mapping.v1', 'ts_code': code,
            'industry_key': rb['industry_key'], 'coverage_start': '20260811', 'coverage_end': '20261009',
            'published_at': STAMP, 'available_at': STAMP})
        self.context_receipt()
        for source in self.manifest['sources']:
            source['identity'].update(ts_code=code, industry_key=rb['industry_key'])
        return event

    def check(self, reason, structural='STRUCTURALLY_VALID'):
        self.seal(register=True)
        result = self.load()
        self.assertEqual(result['status'], 'DATA_BLOCKED')
        self.assertIn(reason, result['reason_codes'])
        self.assertEqual(result['quality']['structural_input_status'], structural)
        self.assertEqual(result['quality']['promotion_input_status'], 'DATA_BLOCKED')
        return result

    def test_thesis_missing_still_allows_structure_observation_only(self):
        self.ready_observation()
        result = self.check('THESIS_NOT_FROZEN')
        self.assertIsNone(result['quality']['missing_fields']['thesis']['value'])
        self.assertEqual(result['quality']['flow']['status'], 'CONFIRMED')
        self.assertEqual(result['quality']['context']['status'], 'CONFIRMED')

    def test_historical_no_select_is_legal_without_authority(self):
        self.ready_observation()
        result = self.check('HISTORICAL_NO_U4_AUTHORITY')
        self.assertEqual(result['bindings']['u4_status'], 'HISTORICAL_NO_U4_AUTHORITY')
        self.assertFalse(result['authority']['u4_authority'])

    def test_prospective_requires_reopened_bound_select(self):
        self.ready_observation()
        event = self.u4()
        result = self.check('U4_COHORT_UNBOUND')
        self.assertEqual(result['bindings']['decision_row_hash'], event['record_hash'])
        self.assertEqual(result['bindings']['cohort_id'], event['candidate']['cohort_id'])
        self.assertEqual(result['bindings']['u4_status'], 'SELECT_BOUND')
        self.payloads['research_binding']['decision'] = self.source('fake.json', {'decision': 'SELECT'})
        self.seal(register=True)
        self.refused('U4_DECISION_INVALID')

    def test_prospective_missing_select_refused(self):
        self.request.update(mode='PROSPECTIVE_RESEARCH', exposure_status='UNEXPOSED')
        self.seal(register=True)
        self.refused('PROSPECTIVE_SELECT_REQUIRED')

    def test_case_industry_cannot_override_u4_industry(self):
        self.ready_observation()
        self.u4()
        self.request['industry_key'] = 'WRONG'
        self.payloads['research_binding']['industry_key'] = 'WRONG'
        for source in self.manifest['sources']:
            source['identity']['industry_key'] = 'WRONG'
        context = self.payloads['context']
        context['industry_key'] = 'WRONG'
        for field in ('industry_mapping',):
            value = json.loads((self.evidence / context[field]['path']).read_bytes())
            value['industry_key'] = 'WRONG'
            context[field] = self.source(context[field]['path'], value)
        value = json.loads((self.evidence / context['source_refs'][0]['path']).read_bytes())
        value['industry_key'] = 'WRONG'
        context['source_refs'] = [self.source('discussion.json', value)]
        self.context_receipt()
        self.seal(register=True)
        self.refused('U4_IDENTITY_MISMATCH')

    def test_bound_cluster_method_and_cohort_cannot_be_self_declared(self):
        self.ready_observation()
        self.u4()
        rb = self.payloads['research_binding']
        for field in ('cohort_id', 'causal_cluster_id', 'method_version', 'decision_row_hash', 'packet_hash'):
            with self.subTest(field=field):
                old = rb[field]
                rb[field] = HASH if field.endswith('hash') else 'invented'
                self.seal(register=True)
                self.refused('U4_IDENTITY_MISMATCH')
                rb[field] = old

    def test_rejected_u4_is_not_malformed_or_select(self):
        self.ready_observation()
        self.u4(selected=False)
        self.seal(register=True)
        self.refused('PROSPECTIVE_SELECT_REQUIRED')
        self.request.update(mode='HISTORICAL_REPLAY', exposure_status='EXPOSED')
        self.check('HISTORICAL_NO_U4_AUTHORITY')

    def test_future_available_bar_blocked(self):
        self.ready_observation()
        self.payloads['bars']['rows'][-1]['available_at'] = '2026-10-09T15:01:00+08:00'
        self.check('BAR_AFTER_CUTOFF', 'DATA_BLOCKED')

    def test_bar_close_after_cutoff_and_wrong_market_date_blocked(self):
        self.payloads['bars']['rows'][-1]['bar_close_at'] = '2026-10-09T15:01:00+08:00'
        self.check('BAR_AFTER_CUTOFF', 'DATA_BLOCKED')
        self.payloads['bars']['rows'][-1]['bar_close_at'] = '2026-10-08T23:00:00+08:00'
        self.check('BAR_CALENDAR_CLOSE_MISMATCH', 'DATA_BLOCKED')

    def test_source_publication_available_and_capture_are_distinct(self):
        for field in ('published_at', 'available_at'):
            source = self.manifest['sources'][0]
            old = dict(source)
            source[field] = '2026-10-10T15:00:00+08:00'
            source['available_at'] = source['captured_at'] = source[field]
            self.check('SOURCE_AFTER_CUTOFF', 'DATA_BLOCKED')
            source.update(old)
        self.manifest['sources'][0]['captured_at'] = '2026-10-11T15:00:00+08:00'
        self.check('HISTORICAL_NO_U4_AUTHORITY')

    def test_old_flag_coverage_not_clean(self):
        self.ready_observation()
        rb = self.payloads['research_binding']
        rb['red_flags'].update(as_of='20261008', coverage_end='20261008')
        self.check('RED_FLAG_COVERAGE_UNKNOWN')

    def test_active_red_flag_not_cancelled_by_structure(self):
        self.ready_observation()
        rb = self.payloads['research_binding']
        rb['red_flags'].update(verdict='ACTIVE', reasons=['E1_ACTIVE'])
        self.red_flag_originals(e1_active=True)
        result = self.check('ACTIVE_RED_FLAG')
        self.assertEqual(result['quality']['red_flags']['status'], 'ACTIVE')

    def test_copied_clear_flag_cannot_override_reopened_active_source(self):
        self.ready_observation()
        self.red_flag_originals(e1_active=True)
        self.seal(register=True)
        result = self.load()
        self.assertEqual(result['quality']['red_flags']['status'], 'ACTIVE')
        self.assertIn('ACTIVE_RED_FLAG', result['quality']['roles']['research_binding']['reason_codes'])
        self.assertEqual(result['quality']['roles']['research_binding']['semantic_status'], 'DATA_BLOCKED')
        self.assertIn('E1_ACTIVE', result['quality']['red_flags']['reason_codes'])

    def test_naked_clear_without_original_is_unknown(self):
        self.ready_observation()
        flags = self.payloads['research_binding']['red_flags']
        flags['source_refs'] = [self.source('flags.json', dict(flags, source_refs=[]))]
        self.seal(register=True)
        result = self.load()
        self.assertEqual(result['quality']['red_flags']['status'], 'UNKNOWN')
        self.assertIn('RED_FLAG_COVERAGE_UNKNOWN', result['quality']['roles']['research_binding']['reason_codes'])
        self.assertEqual(result['quality']['roles']['research_binding']['semantic_status'], 'DATA_BLOCKED')

    def test_missing_bound_red_flag_original_is_unknown(self):
        self.ready_observation()
        descriptor = self.red_flag_originals()
        descriptor['e1_ref']['path'] = 'missing-e1.json'
        self.payloads['research_binding']['red_flags']['source_refs'] = [self.source('flags.json', descriptor)]
        result = self.check('RED_FLAG_COVERAGE_UNKNOWN')
        self.assertEqual(result['quality']['red_flags']['status'], 'UNKNOWN')
        self.assertEqual(result['quality']['roles']['research_binding']['semantic_status'], 'DATA_BLOCKED')

    def test_complete_current_original_negative_proof_is_clear(self):
        self.ready_observation()
        self.seal(register=True)
        result = self.load()
        self.assertEqual(result['quality']['red_flags']['status'], 'CLEAR')
        self.assertNotIn('RED_FLAG_COVERAGE_UNKNOWN', result['quality']['roles']['research_binding']['reason_codes'])
        self.assertEqual(result['quality']['red_flags']['coverage']['e1']['income'], 'COMPLETE')
        self.assertEqual(result['quality']['red_flags']['coverage']['e1']['formal_announcements'], 'DATA_BLOCKED')
        for name in ('e1-original.json', 'u3-original.json'):
            self.assertEqual(result['bindings']['evidence_byte_hashes']['frozen:' + name],
                             sha((self.evidence / name).read_bytes()))

    def test_u3_original_active_overrides_copied_clear(self):
        self.ready_observation()
        self.red_flag_originals(u3_active=True)
        result = self.check('ACTIVE_RED_FLAG')
        self.assertEqual(result['quality']['red_flags']['status'], 'ACTIVE')
        self.assertIn('U3_ACTIVE', result['quality']['red_flags']['reason_codes'])
        self.assertEqual(result['quality']['roles']['research_binding']['semantic_status'], 'DATA_BLOCKED')

    def test_partial_u3_negative_proof_is_unknown(self):
        self.ready_observation()
        descriptor = self.red_flag_originals()
        battery = json.loads((self.evidence / 'u3-original.json').read_bytes())
        row = battery['data']['results'][0]
        row['completeness']['verdict'] = 'PARTIAL'
        row['dims']['基本面'] = {'status': 'DATA_BLOCKED', '红旗闸门': 'PASS'}
        descriptor['u3_ref'] = self.source('u3-original.json', battery)
        self.payloads['research_binding']['red_flags']['source_refs'] = [self.source('flags.json', descriptor)]
        result = self.check('RED_FLAG_COVERAGE_UNKNOWN')
        self.assertEqual(result['quality']['red_flags']['status'], 'UNKNOWN')

    def test_e1_negative_without_explicit_gap_coverage_is_unknown(self):
        self.ready_observation()
        descriptor = self.red_flag_originals()
        from experiments.research_funnel import e1_event_layer as e1
        layer = json.loads((self.evidence / 'e1-original.json').read_bytes())
        del layer['rows'][0]['evidence_coverage']['income_period_source_blocked']
        layer['rows_hash'] = e1._sha256(layer['rows'])
        e1.validate_event_layer(layer)  # Older producer form is legal, not negative proof.
        descriptor['e1_ref'] = self.source('e1-original.json', layer)
        self.payloads['research_binding']['red_flags']['source_refs'] = [self.source('flags.json', descriptor)]
        result = self.check('RED_FLAG_COVERAGE_UNKNOWN')
        self.assertEqual(result['quality']['red_flags']['status'], 'UNKNOWN')

    def test_current_original_active_survives_other_missing_check(self):
        self.ready_observation()
        descriptor = self.red_flag_originals(e1_active=True)
        descriptor['u3_ref']['path'] = 'missing-u3.json'
        self.payloads['research_binding']['red_flags']['source_refs'] = [self.source('flags.json', descriptor)]
        result = self.check('ACTIVE_RED_FLAG')
        self.assertEqual(result['quality']['red_flags']['status'], 'ACTIVE')
        self.assertEqual(result['quality']['red_flags']['reason_codes'], ['E1_ACTIVE'])

    def test_final_calendar_hole_never_confirms_older_flow_pair(self):
        self.ready_observation()
        flags = self.payloads['research_binding']['red_flags']
        flags['source_refs'] = [self.source('flags.json', dict(flags, source_refs=[]))]
        rows = self.payloads['flow']['rows']
        rows.insert(0, dict(rows[0], trade_date='20261007', available_at=self.stamp('20261007')))
        self.payloads['calendar']['days'].pop()
        self.calendar_hash()
        self.seal(register=True)
        result = self.load()
        flow = result['quality']['flow']
        self.assertEqual(flow['status'], 'DATA_BLOCKED')
        self.assertEqual(flow['trade_dates'], [])
        self.assertIsNone(flow['last_two_sum'])
        self.assertEqual(flow['missing_reason'], 'FLOW_CALENDAR_DEPENDENCY_BLOCKED')
        self.assertIn('CALENDAR_HOLE', flow['dependency_reason_codes'])
        self.assertEqual(result['quality']['roles']['flow']['semantic_status'], 'DATA_BLOCKED')
        self.assertIn('FLOW_CALENDAR_DEPENDENCY_BLOCKED', result['quality']['roles']['flow']['reason_codes'])

    def test_late_calendar_manifest_blocks_dependent_flow(self):
        self.ready_observation()
        flags = self.payloads['research_binding']['red_flags']
        flags['source_refs'] = [self.source('flags.json', dict(flags, source_refs=[]))]
        source = next(s for s in self.manifest['sources'] if s['role'] == 'calendar')
        source.update(published_at='2026-10-10T15:00:00+08:00',
                      available_at='2026-10-10T15:00:00+08:00', captured_at='2026-10-10T15:00:00+08:00')
        self.seal(register=True)
        result = self.load()
        flow = result['quality']['flow']
        self.assertEqual(flow['status'], 'DATA_BLOCKED')
        self.assertEqual(flow['trade_dates'], [])
        self.assertIsNone(flow['last_two_sum'])
        self.assertEqual(flow['missing_reason'], 'FLOW_CALENDAR_DEPENDENCY_BLOCKED')
        self.assertEqual(flow['dependency_reason_codes'], ['SOURCE_AFTER_CUTOFF'])
        self.assertEqual(result['quality']['roles']['flow']['semantic_status'], 'DATA_BLOCKED')
        self.assertIn('SOURCE_AFTER_CUTOFF', result['quality']['roles']['flow']['reason_codes'])

    def test_complete_calendar_negative_flow_is_not_missing(self):
        self.ready_observation()
        for row in self.payloads['flow']['rows']:
            row['main_net_flow'] = '-0.50'
        result = self.check('FLOW_NOT_POSITIVE')
        flow = result['quality']['flow']
        self.assertEqual(flow['status'], 'NOT_CONFIRMED')
        self.assertEqual(flow['trade_dates'], ['20261008', '20261009'])
        self.assertEqual(flow['last_two_sum'], '-1.00')
        self.assertIsNone(flow['missing_reason'])
        self.assertEqual(flow['dependency_reason_codes'], [])
        self.assertEqual(result['quality']['roles']['flow']['reason_codes'], ['FLOW_NOT_POSITIVE'])

    def test_wrong_company_and_future_red_flag_refused_or_blocked(self):
        self.ready_observation()
        flags = self.payloads['research_binding']['red_flags']
        flags['ts_code'] = '600999.SH'
        self.seal(register=True)
        self.refused('RED_FLAG_IDENTITY_MISMATCH')
        flags['ts_code'] = self.request['ts_code']
        flags['available_at'] = '2026-10-10T15:00:00+08:00'
        self.check('RED_FLAG_COVERAGE_UNKNOWN')

    def test_exposed_window_cannot_be_promoted_to_prospective(self):
        self.ready_observation()
        self.u4()
        self.request['exposure_status'] = 'EXPOSED'
        self.seal(register=True)
        self.refused('EXPOSURE_NOT_PROSPECTIVE')

    def test_intraday_bar_or_session_field_refused(self):
        self.payloads['bars']['timeframe'] = '15m'
        self.seal(register=True)
        self.refused('UNSUPPORTED_TIMEFRAME')
        self.payloads['bars']['timeframe'] = '1d'
        self.payloads['bars']['rows'][0]['session'] = 'killzone'
        self.seal(register=True)
        self.refused('EXACT_FIELDS')

    def test_calendar_hole_and_unknown_suspension_blocked(self):
        days = self.payloads['calendar']['days']
        removed = days.pop(5)
        self.calendar_hash()
        self.check('CALENDAR_HOLE', 'DATA_BLOCKED')
        days.insert(5, removed)
        days[5]['suspensions'] = [dict(ts_code=self.request['ts_code'], status='UNKNOWN', source_refs=[])]
        self.calendar_hash()
        self.check('SUSPENSION_UNVERIFIED', 'DATA_BLOCKED')

    def test_missing_open_bar_and_suspended_day_not_filled(self):
        self.payloads['bars']['rows'].pop(5)
        self.check('OPEN_DAY_BAR_MISSING', 'DATA_BLOCKED')
        day = self.payloads['calendar']['days'][5]
        suspension = dict(ts_code=self.request['ts_code'], status='VERIFIED', source_refs=[])
        day['suspensions'] = [dict(suspension, source_refs=[self.source('suspension.json', {
            'trade_date': day['trade_date'], 'ts_code': self.request['ts_code'], 'status': 'VERIFIED'})])]
        self.calendar_hash()
        result = self.check('INSUFFICIENT_HISTORY', 'DATA_BLOCKED')
        self.assertNotIn('OPEN_DAY_BAR_MISSING', result['reason_codes'])

    def test_action_break_and_mixed_price_basis_blocked(self):
        self.payloads['corporate_actions']['actions'] = [dict(action_id='split', effective_date='20261008',
            available_at=STAMP, kind='SPLIT', verified=True, source_refs=[])]
        self.check('CORPORATE_ACTION_BREAK', 'DATA_BLOCKED')
        self.payloads['corporate_actions']['actions'] = []
        self.payloads['bars']['rows'][5]['price_basis'] = 'ADJUSTED'
        self.check('PRICE_BASIS_UNSUPPORTED', 'DATA_BLOCKED')

    def test_action_coverage_and_verification_required(self):
        actions = self.payloads['corporate_actions']
        actions['verified'] = False
        self.check('ACTION_COVERAGE_UNKNOWN', 'DATA_BLOCKED')
        actions['verified'] = True
        actions['coverage']['start'] = '20261008'
        self.check('ACTION_COVERAGE_UNKNOWN', 'DATA_BLOCKED')

    def test_missing_flow_day_not_zero(self):
        self.ready_observation()
        self.payloads['flow']['rows'].pop()
        result = self.check('FLOW_LAST_TWO_MISSING')
        self.assertIsNone(result['quality']['flow']['last_two_sum'])

    def test_flow_older_pair_duplicate_pending_future_and_zero(self):
        self.ready_observation()
        rows = self.payloads['flow']['rows']
        rows[-1]['trade_date'] = '20261007'
        self.check('FLOW_LAST_TWO_MISSING')
        rows[-1]['trade_date'] = '20261009'
        for field, value, reason in [('settlement_status', 'PENDING', 'FLOW_NOT_SETTLED'),
                                     ('available_at', '2026-10-10T15:00:00+08:00', 'FLOW_AFTER_CUTOFF')]:
            old = rows[-1][field]
            rows[-1][field] = value
            self.check(reason)
            rows[-1][field] = old
        for row in rows:
            row['main_net_flow'] = '0'
        result = self.check('FLOW_NOT_POSITIVE')
        self.assertEqual(result['quality']['flow']['last_two_sum'], '0')
        self.assertEqual(result['quality']['flow']['status'], 'NOT_CONFIRMED')
        self.assertEqual(result['quality']['flow']['trade_dates'], ['20261008', '20261009'])
        self.assertIsNone(result['quality']['flow']['missing_reason'])
        self.assertEqual(result['quality']['roles']['flow']['reason_codes'], ['FLOW_NOT_POSITIVE'])
        rows.append(copy.deepcopy(rows[-1]))
        self.seal(register=True)
        self.refused('FLOW_DATE_DUPLICATE')

    def test_sector_review_after_cutoff_not_backdated(self):
        self.ready_observation()
        self.context_receipt('2026-10-10T15:00:00+08:00')
        result = self.check('CONTEXT_REVIEW_AFTER_CUTOFF')
        self.assertEqual(result['quality']['context']['status'], 'DATA_BLOCKED')

    def test_context_names_without_receipt_disputed_and_adverse(self):
        self.ready_observation()
        context = self.payloads['context']
        context['review_receipt'] = None
        self.check('CONTEXT_REVIEW_MISSING')
        context['review_status'] = 'DISPUTED'
        self.context_receipt()
        self.check('CONTEXT_DISPUTED')
        context.update(review_status='REVIEWED', sector_state='ADVERSE')
        self.context_receipt()
        result = self.check('CONTEXT_ADVERSE')
        self.assertEqual(result['quality']['context']['status'], 'ADVERSE')

    def test_context_hash_receipt_mapping_and_source_cutoff_guards(self):
        self.ready_observation()
        context = self.payloads['context']
        context['context_hash'] = HASH
        self.seal(register=True)
        self.refused('CONTEXT_HASH_MISMATCH')
        self.context_receipt()
        context['industry_mapping'] = self.source('mapping.json', {
            'schema_version': 'technical-industry-mapping.v1', 'ts_code': '600999.SH',
            'industry_key': 'SYNTHETIC', 'coverage_start': '20260811', 'coverage_end': '20261009',
            'published_at': STAMP, 'available_at': STAMP})
        self.context_receipt()
        self.seal(register=True)
        self.refused('CONTEXT_MAPPING_MISMATCH')
        self.ready_observation()
        context['source_refs'] = [self.source('discussion.json', {
            'schema_version': 'technical-context-source.v1', 'industry_key': 'SYNTHETIC',
            'as_of': STAMP, 'published_at': STAMP, 'available_at': '2026-10-10T15:00:00+08:00',
            'content': 'Synthetic late source'})]
        self.context_receipt()
        self.check('CONTEXT_SOURCE_AFTER_CUTOFF')

    def test_frozen_u4_files_are_strictly_unchanged(self):
        self.ready_observation()
        self.u4()
        self.seal(register=True)
        before = {p: (p.stat().st_ino, p.stat().st_mtime_ns, sha(p.read_bytes()))
                  for p in self.evidence.iterdir()}
        from unittest.mock import patch
        ledger = importlib.import_module('experiments.research_funnel.u4_decision_ledger')
        with patch.object(ledger, '_ledger_read_snapshot', side_effect=AssertionError('lock reader forbidden')):
            result = self.load()
        self.assertEqual(result['bindings']['u4_status'], 'SELECT_BOUND')
        self.assertEqual(set(self.evidence.iterdir()), set(before))
        for path, sentinel in before.items():
            self.assertEqual((path.stat().st_ino, path.stat().st_mtime_ns, sha(path.read_bytes())), sentinel)

    def test_actual_u4_jsonl_outer_chain_reopened(self):
        self.ready_observation()
        self.u4()
        from experiments.execution_tracker import event_ledger
        rb = self.payloads['research_binding']
        records = json.loads((self.evidence / rb['decision']['path']).read_bytes())
        raw = ('\n'.join(event_ledger.canonical(r) for r in records) + '\n').encode()
        (self.evidence / 'frozen-ledger.jsonl').write_bytes(raw)
        rb['decision'].update(path='frozen-ledger.jsonl', sha256=sha(raw))
        result = self.check('U4_COHORT_UNBOUND')
        self.assertEqual(result['bindings']['u4_status'], 'SELECT_BOUND')
        records[1]['prev'] = HASH
        raw = ('\n'.join(event_ledger.canonical(r) for r in records) + '\n').encode()
        (self.evidence / 'frozen-ledger.jsonl').write_bytes(raw)
        rb['decision']['sha256'] = sha(raw)
        self.seal(register=True)
        self.refused('U4_OUTER_CHAIN_INVALID')

    def test_missing_original_u4_source_is_not_forged_select(self):
        self.ready_observation()
        self.u4()
        (self.evidence / 'u4-candidate_battery.json').unlink()
        self.check('U4_SOURCE_MISSING')

    def test_fully_resealed_u4_packet_must_match_original_bundle(self):
        self.ready_observation()
        self.u4()
        rb = self.payloads['research_binding']
        packet = json.loads((self.evidence / rb['packet']['path']).read_bytes())
        packet['ready_pool'][0]['industry_key'] = 'WRONG'
        rb['packet'] = self.source('u4-packet.json', packet)
        self.seal(register=True)
        self.refused('U4_ORIGINAL_EVIDENCE_INVALID')

    def test_late_role_source_cannot_display_confirmed_context_or_flow(self):
        self.ready_observation()
        for source in self.manifest['sources']:
            if source['role'] in {'context', 'flow'}:
                source.update(published_at='2026-10-10T15:00:00+08:00',
                              available_at='2026-10-10T15:00:00+08:00', captured_at='2026-10-10T15:00:00+08:00')
        result = self.check('SOURCE_AFTER_CUTOFF')
        self.assertEqual(result['quality']['context']['status'], 'DATA_BLOCKED')
        self.assertEqual(result['quality']['flow']['status'], 'DATA_BLOCKED')
        self.assertIsNone(result['quality']['flow']['last_two_sum'])

    def test_optional_frozen_thesis_still_requires_identity_and_pit(self):
        self.ready_observation()
        thesis = {'schema_version': 'technical-research-evidence.v1', 'kind': 'THESIS',
                  'ts_code': self.request['ts_code'], 'industry_key': self.request['industry_key'],
                  'published_at': STAMP, 'available_at': '2026-10-10T15:00:00+08:00',
                  'content': 'Synthetic sealed thesis'}
        self.payloads['research_binding']['thesis'] = dict(source_ref=self.source('thesis.json', thesis), missing_reason=None)
        self.check('THESIS_AFTER_CUTOFF')
        thesis.update(available_at=STAMP, ts_code='600999.SH')
        self.payloads['research_binding']['thesis']['source_ref'] = self.source('thesis.json', thesis)
        self.seal(register=True)
        self.refused('OPTIONAL_RESEARCH_IDENTITY_MISMATCH')

    def test_predecision_originals_do_not_invent_select_or_cohort(self):
        self.ready_observation()
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        fixture = importlib.import_module('test_u4_pre_decision_runtime')
        packet, diagnostic, bundle, feature, health = fixture._build(self.root / 'predecision')
        row = next(r for r in packet['candidate_rows'] if r['allowed_for_u4_packet'])
        files = {}
        for path in (self.root / 'predecision').rglob('*.json'):
            files[path.relative_to(self.root / 'predecision').as_posix()] = self.source(
                'pre-' + str(len(files)) + '.json', json.loads(path.read_bytes()))
        refs = packet['source_refs']
        diagnostic_name = refs['diagnostic_report_ref']
        files[diagnostic_name] = self.source('pre-diagnostic.json', diagnostic)
        # Logical refs are those in the frozen packet, never absolute paths.
        bundle_name = refs['same_day_bundle_ref']
        for path in bundle.iterdir():
            files[bundle_name + '/' + path.name] = self.source('pre-bundle-' + path.name, json.loads(path.read_bytes()))
        files[refs['feature_store_health_ref']] = self.source('pre-feature.json', json.loads(feature.read_bytes()))
        files[refs['funnel_health_ref']] = self.source('pre-health.json', json.loads(health.read_bytes()))
        descriptor = dict(schema_version='technical-u4-sources.v1', files=files,
                          bundle_ref=bundle_name, feature_health_ref=refs['feature_store_health_ref'],
                          funnel_health_ref=refs['funnel_health_ref'], diagnostic_ref=diagnostic_name,
                          cyclical_flags_ref=None)
        rb = self.payloads['research_binding']
        rb.update(packet=self.source('pre-packet.json', packet), packet_hash=packet['packet_hash'],
                  u4_sources=self.source('pre-sources.json', descriptor), decision=None, decision_row_hash=None,
                  ts_code=row['ts_code'], industry_key='TECH', cohort_id=row['cohort_id'],
                  causal_cluster_id=row['causal_cluster_id'], method_version=packet['method_version'])
        self.request.update(ts_code=row['ts_code'], industry_key='TECH')
        for source in self.manifest['sources']:
            source['identity'].update(ts_code=row['ts_code'], industry_key='TECH')
        for bar in self.payloads['bars']['rows']:
            bar['ts_code'] = row['ts_code']
        for role in ('corporate_actions', 'flow'):
            self.payloads[role]['ts_code'] = row['ts_code']
        flags = rb['red_flags']
        flags.update(ts_code=row['ts_code'], verdict='UNKNOWN', source_refs=[])
        self.payloads['context'].update(industry_key='TECH', review_status='PENDING', review_receipt=None)
        result = self.check('HISTORICAL_NO_U4_AUTHORITY')
        self.assertEqual(result['bindings']['cohort_id'], 'UNAVAILABLE')
        self.assertIn('U4_COHORT_UNBOUND', result['reason_codes'])
        self.request.update(mode='PROSPECTIVE_RESEARCH', exposure_status='UNEXPOSED')
        self.seal(register=True)
        self.refused('PROSPECTIVE_SELECT_REQUIRED')

    def test_review_receipt_cannot_predate_authored_context(self):
        self.ready_observation()
        context = self.payloads['context']
        context['reviewed_at'] = '2026-10-09T14:59:00+08:00'
        self.context_receipt(context['reviewed_at'])
        self.check('CONTEXT_REVIEW_BEFORE_AUTHORING')

    def test_context_external_source_time_order_and_receipt_binding(self):
        self.ready_observation()
        context = self.payloads['context']
        source = json.loads((self.evidence / 'discussion.json').read_bytes())
        source['available_at'] = '2026-10-09T14:59:00+08:00'
        context['source_refs'] = [self.source('discussion.json', source)]
        self.context_receipt()
        self.check('CONTEXT_SOURCE_TIME_ORDER')
        self.ready_observation()
        receipt = json.loads((self.evidence / 'review.json').read_bytes())
        receipt['context_hash'] = HASH
        context['review_receipt'] = self.source('review.json', receipt)
        self.seal(register=True)
        self.refused('CONTEXT_RECEIPT_MISMATCH')

    def test_future_u4_registration_not_backdated_by_packet(self):
        self.ready_observation()
        self.u4()
        rb = self.payloads['research_binding']
        records = json.loads((self.evidence / rb['decision']['path']).read_bytes())
        from experiments.execution_tracker import event_ledger
        records[-1]['ts'] = '2026-10-10T15:00:00'
        records[-1]['hash'] = event_ledger.record_hash(records[-1])
        rb['decision'] = self.source('u4-records.json', records, rb['decision']['pointer'])
        self.check('U4_AFTER_CUTOFF')

    def test_last_two_flow_dates_exclude_verified_suspension(self):
        self.ready_observation()
        day = self.payloads['calendar']['days'][-1]
        suspension = {'trade_date': day['trade_date'], 'ts_code': self.request['ts_code'], 'status': 'VERIFIED'}
        day['suspensions'] = [dict(ts_code=self.request['ts_code'], status='VERIFIED',
                                  source_refs=[self.source('suspension.json', suspension)])]
        self.payloads['bars']['rows'].pop()
        row = self.payloads['flow']['rows'][0]
        self.payloads['flow']['rows'] = [dict(row, trade_date='20261007', available_at=self.stamp('20261007')), row]
        self.calendar_hash()
        result = self.check('INSUFFICIENT_HISTORY', 'DATA_BLOCKED')
        self.assertEqual(result['quality']['flow']['trade_dates'], ['20261007', '20261008'])
        self.assertEqual(result['quality']['flow']['status'], 'CONFIRMED')
        self.assertEqual(result['quality']['flow']['last_two_sum'], '40.00')
        self.assertEqual(result['quality']['roles']['flow']['semantic_status'], 'VALIDATED')

    def test_refused_result_never_exposes_calculable_inputs(self):
        self.ready_observation()
        self.payloads['bars']['rows'][0]['ts_code'] = '600999.SH'
        self.seal(register=True)
        result = self.refused('BAR_IDENTITY_MISMATCH')
        self.assertEqual(result['quality']['promotion_input_status'], 'REFUSED')
        self.assertEqual(result['bindings'], {})
        self.assertIsNone(result['request'])

    def test_missing_research_role_historical_still_has_explicit_no_authority(self):
        self.ready_observation()
        source = next(s for s in self.manifest['sources'] if s['role'] == 'research_binding')
        source['missing_reason'] = 'NOT_FROZEN'
        result = self.check('HISTORICAL_NO_U4_AUTHORITY')
        self.assertEqual(result['bindings']['u4_status'], 'HISTORICAL_NO_U4_AUTHORITY')
        self.assertEqual(result['quality']['red_flags']['status'], 'UNKNOWN')

    def test_partial_suspension_sources_cannot_verify_missing_bar(self):
        self.ready_observation()
        day = self.payloads['calendar']['days'][5]
        value = dict(trade_date=day['trade_date'], ts_code=self.request['ts_code'], status='VERIFIED')
        ref = self.source('suspension.json', value)
        day['suspensions'] = [dict(ts_code=self.request['ts_code'], status='VERIFIED',
                                  source_refs=[ref, dict(ref, path='missing-suspension.json')])]
        self.payloads['bars']['rows'].pop(5)
        self.calendar_hash()
        self.check('SUSPENSION_UNVERIFIED', 'DATA_BLOCKED')

    def test_late_receipt_still_cannot_override_context_identity(self):
        self.ready_observation()
        context = self.payloads['context']
        receipt = json.loads((self.evidence / 'review.json').read_bytes())
        receipt.update(context_hash=HASH, reviewed_at='2026-10-10T15:00:00+08:00')
        context['review_receipt'] = self.source('review.json', receipt)
        self.seal(register=True)
        self.refused('CONTEXT_RECEIPT_MISMATCH')


if __name__ == "__main__":
    unittest.main(verbosity=2)
