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

    def test_partial_task_never_claims_semantically_validated(self):
        result = self.load()
        self.assertEqual(set(result), {"schema", "request", "source_manifest", "inputs", "bindings",
                                      "quality", "status", "reason_codes", "authority"})
        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertEqual(result["quality"]["structural_input_status"], "STRUCTURALLY_VALID")
        self.assertEqual(result["quality"]["promotion_input_status"], "NOT_EVALUATED")
        self.assertIn("SEMANTIC_VALIDATION_NOT_IMPLEMENTED", result["reason_codes"])
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
        self.seal(register=True)
        result = self.load()
        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertEqual(result["quality"]["roles"]["corporate_actions"]["status"], "STRUCTURALLY_VALID")
        self.assertEqual(result["quality"]["promotion_input_status"], "NOT_EVALUATED")

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
        self.assertEqual(result["quality"]["promotion_input_status"], "NOT_EVALUATED")

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
        self.payloads["bars"]["rows"] *= self.contract.MAX_ROWS + 1
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
