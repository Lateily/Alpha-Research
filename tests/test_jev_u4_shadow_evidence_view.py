from __future__ import annotations

import copy
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "experiments" / "research_funnel"))
sys.path.insert(0, str(ROOT / "experiments" / "execution_tracker"))

import u4_pre_decision as pre  # noqa: E402
from evidence_view import (  # noqa: E402
    DirectoryCapability,
    EvidenceError,
    EvidenceView,
)
from test_u4_pre_decision_runtime import (  # noqa: E402
    GENERATED_AT,
    _build,
    _fixture_tree,
    _rehash_packet,
    _write,
    _write_cyclical_flags,
)


PACKET_REF = "u4-pre-decision.json"
DIAGNOSTIC_REF = "u4_pre_decision_diagnostic.json"
FEATURE_REF = "public/data/v2/feature_store_health.json"
FUNNEL_REF = "public/data/v2/funnel_health.json"


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _refs(root: Path, bundle: Path) -> dict[str, str]:
    return {
        "bundle_ref": bundle.relative_to(root).as_posix(),
        "feature_health_ref": FEATURE_REF,
        "funnel_health_ref": FUNNEL_REF,
    }


def _write_packet(root: Path, packet: dict, diagnostic: dict) -> None:
    (root / PACKET_REF).write_bytes(_json_bytes(packet))
    (root / DIAGNOSTIC_REF).write_bytes(_json_bytes(diagnostic))


def _capture(root: Path, bundle: Path, *, cyclical_ref: str | None = None) -> EvidenceView:
    with DirectoryCapability.open(root) as capability:
        return EvidenceView.capture_u4(
            capability,
            packet_ref=PACKET_REF,
            diagnostic_ref=DIAGNOSTIC_REF,
            cyclical_flags_ref=cyclical_ref,
            **_refs(root, bundle),
        )


def _build_from_evidence(
    view: EvidenceView,
    refs: dict[str, str],
    *,
    cyclical_ref: str | None = None,
) -> tuple[dict, dict]:
    return pre.build_packet(
        evidence=view,
        diagnostic_ref=DIAGNOSTIC_REF,
        industry="TECH",
        method_version=pre.DEFAULT_METHOD_VERSION,
        generated_at=GENERATED_AT,
        cyclical_flags_ref=cyclical_ref,
        **refs,
    )


def _validate_from_evidence(
    view: EvidenceView,
    refs: dict[str, str],
    *,
    cyclical_ref: str | None = None,
) -> None:
    pre.validate_packet(
        evidence=view,
        packet_ref=PACKET_REF,
        diagnostic_ref=DIAGNOSTIC_REF,
        industry="TECH",
        method_version=pre.DEFAULT_METHOD_VERSION,
        cyclical_flags_ref=cyclical_ref,
        **refs,
    )


def _validate_from_paths(
    root: Path,
    packet: dict,
    bundle: Path,
    feature_health: Path,
    funnel_health: Path,
    *,
    cyclical_path: Path | None = None,
) -> None:
    pre.validate_packet(
        packet,
        bundle_dir=bundle,
        feature_health_path=feature_health,
        funnel_health_path=funnel_health,
        diagnostic_path=root / DIAGNOSTIC_REF,
        diagnostic_ref=DIAGNOSTIC_REF,
        industry="TECH",
        method_version=pre.DEFAULT_METHOD_VERSION,
        cyclical_flags_path=cyclical_path,
    )


class EvidenceViewTests(unittest.TestCase):
    def test_view_is_immutable_and_strict_json_rejects_duplicate_keys(self) -> None:
        source = {"valid.json": b'{"value":1}', "duplicate.json": b'{"x":1,"x":2}'}
        view = EvidenceView(source)
        source["valid.json"] = b'{"value":2}'

        self.assertEqual({"value": 1}, view.json_object("valid.json"))
        with self.assertRaises(TypeError):
            view.files["new.json"] = b"{}"  # type: ignore[index]
        with self.assertRaisesRegex(EvidenceError, "duplicate JSON key: x"):
            view.json_object("duplicate.json")

    def test_valid_path_and_evidence_builds_have_identical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, diagnostic, bundle, feature_health, funnel_health = _build(root)
            _write_packet(root, packet, diagnostic)
            refs = _refs(root, bundle)
            view = _capture(root, bundle)

            evidence_packet, evidence_diagnostic = _build_from_evidence(view, refs)

            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            expected_refs = {
                PACKET_REF,
                DIAGNOSTIC_REF,
                FEATURE_REF,
                FUNNEL_REF,
                f"{refs['bundle_ref']}/manifest.json",
                *(f"{refs['bundle_ref']}/{name}" for name in manifest["artifacts"]),
                *(f"{refs['bundle_ref']}/stage_{stage}.json" for stage in (
                    "candidates", "battery", "finalize"
                )),
            }

            self.assertEqual(expected_refs, set(view.files))
            self.assertEqual(_json_bytes(packet), _json_bytes(evidence_packet))
            self.assertEqual(_json_bytes(diagnostic), _json_bytes(evidence_diagnostic))
            _validate_from_paths(
                root, packet, bundle, feature_health, funnel_health
            )
            _validate_from_evidence(view, refs)

    def test_captured_validation_never_reopens_the_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            packet, diagnostic, bundle, _feature, _funnel = _build(root)
            _write_packet(root, packet, diagnostic)
            refs = _refs(root, bundle)
            view = _capture(root, bundle)
            root.rename(Path(tmp) / "renamed-away")

            denied = AssertionError("filesystem access after EvidenceView capture")
            with mock.patch.object(Path, "read_bytes", side_effect=denied), mock.patch.object(
                Path, "read_text", side_effect=denied
            ), mock.patch.object(Path, "is_file", side_effect=denied), mock.patch.object(
                Path, "is_dir", side_effect=denied
            ):
                _validate_from_evidence(view, refs)

            self.assertEqual(_json_bytes(packet), view.bytes(PACKET_REF))
            self.assertEqual(_json_bytes(diagnostic), view.bytes(DIAGNOSTIC_REF))

    def test_capability_rejects_unsafe_refs_symlinks_and_special_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "sentinel.json").write_text("{}", encoding="utf-8")
            (root / "directory").mkdir()
            os.symlink(outside / "sentinel.json", root / "final-link.json")
            os.symlink(outside, root / "ancestor-link")
            fifo = root / "pipe"
            os.mkfifo(fifo)
            socket_path = root / "socket"
            listener = socket.socket(socket.AF_UNIX)
            try:
                special_refs = ["directory", "pipe"]
                try:
                    listener.bind(str(socket_path))
                except OSError:
                    pass
                else:
                    special_refs.append("socket")
                with DirectoryCapability.open(root) as capability:
                    for ref in (
                        "/absolute.json",
                        "../traversal.json",
                        "nul\0name",
                        "final-link.json",
                        "ancestor-link/sentinel.json",
                        "ancestor-link/missing.json",
                        *special_refs,
                    ):
                        with self.subTest(ref=ref):
                            with self.assertRaises(EvidenceError):
                                capability.read_file(ref)
            finally:
                listener.close()

    def test_packet_and_diagnostic_rejections_match_path_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, diagnostic, bundle, feature_health, funnel_health = _build(root)
            refs = _refs(root, bundle)

            resealed = copy.deepcopy(packet)
            resealed["candidate_rows"].pop()
            _rehash_packet(resealed)
            _write_packet(root, resealed, resealed["diagnostic"])
            view = _capture(root, bundle)
            with self.assertRaises(pre.PreDecisionError) as path_error:
                _validate_from_paths(
                    root, resealed, bundle, feature_health, funnel_health
                )
            with self.assertRaises(pre.PreDecisionError) as evidence_error:
                _validate_from_evidence(view, refs)
            self.assertEqual(str(path_error.exception), str(evidence_error.exception))

            _write_packet(root, packet, {**diagnostic, "u4_ready_rows": -1})
            view = _capture(root, bundle)
            with self.assertRaises(pre.PreDecisionError) as path_error:
                _validate_from_paths(
                    root, packet, bundle, feature_health, funnel_health
                )
            with self.assertRaises(pre.PreDecisionError) as evidence_error:
                _validate_from_evidence(view, refs)
            self.assertEqual(str(path_error.exception), str(evidence_error.exception))

    def test_source_rejections_match_for_health_stage_and_missing_evidence(self) -> None:
        cases = (
            "forged_health",
            "mixed_run",
            "stage_hash",
            "stage_timestamp",
            "missing",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                packet, diagnostic, bundle, feature_health, funnel_health = _build(root)
                _write_packet(root, packet, diagnostic)
                refs = _refs(root, bundle)

                if case == "forged_health":
                    health = json.loads(funnel_health.read_text(encoding="utf-8"))
                    health["counts"]["candidate_rows"] += 1
                    _write(funnel_health, health)
                elif case in {"mixed_run", "stage_hash", "stage_timestamp"}:
                    stage_path = bundle / "stage_battery.json"
                    stage = json.loads(stage_path.read_text(encoding="utf-8"))
                    if case == "mixed_run":
                        stage["run_id"] = "another-run"
                    elif case == "stage_hash":
                        stage["stage_hash"] = "0" * 64
                    else:
                        stage["generated_at"] = "2026-08-12T09:31:00+00:00"
                    if case != "stage_hash":
                        stage["stage_hash"] = pre.funnel._hash(
                            {key: value for key, value in stage.items() if key != "stage_hash"}
                        )
                    _write(stage_path, stage)
                else:
                    (bundle / "stage_battery.json").unlink()

                with self.assertRaises(pre.PreDecisionError) as path_error:
                    _validate_from_paths(
                        root, packet, bundle, feature_health, funnel_health
                    )
                try:
                    view = _capture(root, bundle)
                except EvidenceError as exc:
                    evidence_message = str(exc)
                else:
                    with self.assertRaises(pre.PreDecisionError) as evidence_error:
                        _validate_from_evidence(view, refs)
                    evidence_message = str(evidence_error.exception)
                self.assertTrue(str(path_error.exception))
                self.assertTrue(evidence_message)
                if case != "missing":
                    self.assertEqual(str(path_error.exception), evidence_message)

    def test_capture_rejects_bundle_bytes_that_drift_from_the_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, diagnostic, bundle, _feature, _funnel = _build(root)
            _write_packet(root, packet, diagnostic)
            artifact = bundle / "candidate_review.json"
            artifact.write_bytes(artifact.read_bytes() + b" ")

            with self.assertRaisesRegex(EvidenceError, "bundle artifact hash mismatch"):
                _capture(root, bundle)

    def test_cyclical_explicit_absent_and_legacy_default_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, feature_health, funnel_health = _fixture_tree(root)
            baseline, diagnostic = pre.build_packet(
                bundle_dir=bundle,
                feature_health_path=feature_health,
                funnel_health_path=funnel_health,
                diagnostic_ref=DIAGNOSTIC_REF,
                industry="TECH",
                method_version=pre.DEFAULT_METHOD_VERSION,
                generated_at=GENERATED_AT,
            )
            code = baseline["candidate_rows"][0]["ts_code"]
            default_path = pre._default_cyclical_flags_path(feature_health)
            _write_cyclical_flags(default_path, {
                code: {
                    "peak_earnings_risk": True,
                    "needs_normalized_bridge": True,
                    "roe_ttm_vs_median": 1.4,
                    "gm_ttm_vs_median": 1.2,
                }
            })
            explicit_ref = default_path.relative_to(root).as_posix()
            legacy_default, _ = pre.build_packet(
                bundle_dir=bundle,
                feature_health_path=feature_health,
                funnel_health_path=funnel_health,
                diagnostic_ref=DIAGNOSTIC_REF,
                industry="TECH",
                method_version=pre.DEFAULT_METHOD_VERSION,
                generated_at=GENERATED_AT,
            )
            _write_packet(root, legacy_default, legacy_default["diagnostic"])
            refs = _refs(root, bundle)
            absent_view = _capture(root, bundle)
            explicit_view = _capture(root, bundle, cyclical_ref=explicit_ref)

            absent, _ = _build_from_evidence(absent_view, refs)
            explicit, _ = _build_from_evidence(
                explicit_view, refs, cyclical_ref=explicit_ref
            )
            legacy_explicit, _ = pre.build_packet(
                bundle_dir=bundle,
                feature_health_path=feature_health,
                funnel_health_path=funnel_health,
                diagnostic_ref=DIAGNOSTIC_REF,
                industry="TECH",
                method_version=pre.DEFAULT_METHOD_VERSION,
                generated_at=GENERATED_AT,
                cyclical_flags_path=default_path,
            )

            absent_row = next(row for row in absent["candidate_rows"] if row["ts_code"] == code)
            default_row = next(
                row for row in legacy_default["candidate_rows"] if row["ts_code"] == code
            )
            self.assertIsNone(absent_row["peak_earnings"]["flag"])
            self.assertTrue(default_row["peak_earnings"]["flag"])
            self.assertEqual(_json_bytes(legacy_explicit), _json_bytes(explicit))


if __name__ == "__main__":
    unittest.main()
