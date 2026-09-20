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

    def test_prefixed_capture_refs_keep_legacy_canonical_packet_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "snapshot"
            packet, diagnostic, bundle, feature_health, funnel_health = _build(snapshot)
            _write_packet(snapshot, packet, diagnostic)
            lookup_refs = {
                "bundle_ref": bundle.relative_to(root).as_posix(),
                "feature_health_ref": feature_health.relative_to(root).as_posix(),
                "funnel_health_ref": funnel_health.relative_to(root).as_posix(),
            }
            packet_lookup_ref = f"snapshot/{PACKET_REF}"
            diagnostic_lookup_ref = f"snapshot/{DIAGNOSTIC_REF}"
            with DirectoryCapability.open(root) as capability:
                view = EvidenceView.capture_u4(
                    capability,
                    packet_ref=packet_lookup_ref,
                    diagnostic_ref=diagnostic_lookup_ref,
                    cyclical_flags_ref=None,
                    **lookup_refs,
                )

            evidence_packet, evidence_diagnostic = _build_from_evidence(
                view, lookup_refs
            )

            self.assertEqual(_json_bytes(packet), _json_bytes(evidence_packet))
            self.assertEqual(_json_bytes(diagnostic), _json_bytes(evidence_diagnostic))
            pre.validate_packet(
                evidence=view,
                packet_ref=packet_lookup_ref,
                diagnostic_evidence_ref=diagnostic_lookup_ref,
                diagnostic_ref=DIAGNOSTIC_REF,
                industry="TECH",
                method_version=pre.DEFAULT_METHOD_VERSION,
                cyclical_flags_ref=None,
                **lookup_refs,
            )
            _validate_from_paths(
                snapshot, packet, bundle, feature_health, funnel_health
            )

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

    def test_root_acquisition_rejects_symlinks_and_real_directory_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "artifact-root"
            outside = parent / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "inside.json").write_bytes(b'{"source":"inside"}')
            sentinel = outside / "inside.json"
            sentinel.write_bytes(b'{"source":"outside"}')

            root_link = parent / "root-link"
            os.symlink(outside, root_link)
            ancestor_link = parent / "ancestor-link"
            os.symlink(parent, ancestor_link)
            with self.assertRaises(EvidenceError):
                DirectoryCapability.open(root_link)
            with self.assertRaises(EvidenceError):
                DirectoryCapability.open(ancestor_link / root.name)
            self.assertEqual(b'{"source":"outside"}', sentinel.read_bytes())

            real_open = os.open
            real_close = os.close
            opened: list[int] = []
            closed: list[int] = []
            swapped = False

            def racing_open(path, flags, *args, **kwargs):
                nonlocal swapped
                if path == root.name and not swapped:
                    root.rename(parent / "original-root")
                    outside.rename(root)
                    swapped = True
                descriptor = real_open(path, flags, *args, **kwargs)
                opened.append(descriptor)
                return descriptor

            def tracking_close(descriptor):
                closed.append(descriptor)
                return real_close(descriptor)

            capability = None
            try:
                with mock.patch.object(os, "open", side_effect=racing_open), mock.patch.object(
                    os, "close", side_effect=tracking_close
                ):
                    with self.assertRaises(EvidenceError):
                        capability = DirectoryCapability.open(root)
            finally:
                if capability is not None:
                    capability.close()

            self.assertTrue(swapped)
            self.assertCountEqual(opened, closed)
            self.assertEqual(
                b'{"source":"outside"}', (root / "inside.json").read_bytes()
            )

    def test_retained_root_rejects_file_replacement_and_concurrent_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            target = root / "target.json"
            target.write_bytes(b'{"source":"inside"}')
            outside = root / "outside.json"
            outside.write_bytes(b'{"source":"outside"}')

            with DirectoryCapability.open(root) as capability:
                real_open = os.open
                swapped = False

                def racing_open(path, flags, *args, **kwargs):
                    nonlocal swapped
                    if path == target.name and not swapped:
                        target.rename(root / "original.json")
                        outside.rename(target)
                        swapped = True
                    return real_open(path, flags, *args, **kwargs)

                with mock.patch.object(os, "open", side_effect=racing_open):
                    with self.assertRaises(EvidenceError):
                        capability.read_file(target.name)
                self.assertTrue(swapped)
                self.assertEqual(b'{"source":"outside"}', target.read_bytes())

                racing = root / "racing.json"
                original = b"A" * (1024 * 1024 + 7)
                racing.write_bytes(original)
                real_read = os.read
                mutated = False

                def racing_read(descriptor, size):
                    nonlocal mutated
                    chunk = real_read(descriptor, size)
                    if chunk and not mutated:
                        racing.write_bytes(b"B" * len(original))
                        mutated = True
                    return chunk

                with mock.patch.object(os, "read", side_effect=racing_read):
                    with self.assertRaisesRegex(EvidenceError, "changed while being captured"):
                        capability.read_file(racing.name)
                self.assertTrue(mutated)

    def test_retained_root_reads_original_bytes_after_directory_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "root"
            outside = parent / "outside"
            ref = "nested/evidence.json"
            original = b'{"source":"original"}'
            sentinel = b'{"source":"outside"}'
            (root / "nested").mkdir(parents=True)
            (outside / "nested").mkdir(parents=True)
            (root / ref).write_bytes(original)
            outside_path = outside / ref
            outside_path.write_bytes(sentinel)
            outside_identity = os.stat(outside_path)

            with DirectoryCapability.open(root) as capability:
                root.rename(parent / "retained-root")
                outside.rename(root)
                real_read = os.read

                def reject_outside_read(descriptor, size):
                    observed = os.fstat(descriptor)
                    self.assertNotEqual(
                        (outside_identity.st_dev, outside_identity.st_ino),
                        (observed.st_dev, observed.st_ino),
                        "read attempted on outside replacement sentinel",
                    )
                    return real_read(descriptor, size)

                with mock.patch.object(os, "read", side_effect=reject_outside_read):
                    self.assertEqual(original, capability.read_file(ref))

    def test_retained_root_reads_original_bytes_after_symlink_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "root"
            outside = parent / "outside"
            ref = "nested/evidence.json"
            original = b'{"source":"original"}'
            sentinel = b'{"source":"outside"}'
            (root / "nested").mkdir(parents=True)
            (outside / "nested").mkdir(parents=True)
            (root / ref).write_bytes(original)
            outside_path = outside / ref
            outside_path.write_bytes(sentinel)
            outside_identity = os.stat(outside_path)

            with DirectoryCapability.open(root) as capability:
                root.rename(parent / "retained-root")
                os.symlink(outside, root)
                real_read = os.read

                def reject_outside_read(descriptor, size):
                    observed = os.fstat(descriptor)
                    self.assertNotEqual(
                        (outside_identity.st_dev, outside_identity.st_ino),
                        (observed.st_dev, observed.st_ino),
                        "read attempted on outside replacement sentinel",
                    )
                    return real_read(descriptor, size)

                with mock.patch.object(os, "read", side_effect=reject_outside_read):
                    self.assertEqual(original, capability.read_file(ref))

    def test_read_oserror_closes_each_opened_descriptor_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            ref = "nested/evidence.json"
            (root / "nested").mkdir(parents=True)
            (root / ref).write_bytes(b'{"source":"original"}')

            with DirectoryCapability.open(root) as capability:
                real_dup = os.dup
                real_open = os.open
                real_close = os.close
                duplicated: list[int] = []
                opened: list[int] = []
                closed: list[int] = []

                def tracking_dup(descriptor):
                    duplicate = real_dup(descriptor)
                    duplicated.append(duplicate)
                    return duplicate

                def tracking_open(path, flags, *args, **kwargs):
                    descriptor = real_open(path, flags, *args, **kwargs)
                    opened.append(descriptor)
                    return descriptor

                def tracking_close(descriptor):
                    closed.append(descriptor)
                    return real_close(descriptor)

                def failing_read(descriptor, size):
                    self.assertEqual(1, len(duplicated))
                    self.assertEqual(2, len(opened))
                    raise OSError("injected read failure")

                with mock.patch.object(os, "dup", side_effect=tracking_dup), mock.patch.object(
                    os, "open", side_effect=tracking_open
                ), mock.patch.object(os, "close", side_effect=tracking_close), mock.patch.object(
                    os, "read", side_effect=failing_read
                ):
                    with self.assertRaisesRegex(
                        EvidenceError, r"cannot read evidence ref nested/evidence.json from "
                    ):
                        capability.read_file(ref)

            self.assertEqual(1, len(duplicated))
            self.assertEqual(2, len(opened))
            self.assertCountEqual([*duplicated, *opened], closed)

    def test_malformed_root_has_stable_error_and_balanced_descriptors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            malformed = f"{tmp}/bad\0component"
            real_open = os.open
            real_close = os.close
            opened: list[int] = []
            closed: list[int] = []

            def tracking_open(path, flags, *args, **kwargs):
                descriptor = real_open(path, flags, *args, **kwargs)
                opened.append(descriptor)
                return descriptor

            def tracking_close(descriptor):
                closed.append(descriptor)
                return real_close(descriptor)

            with mock.patch.object(os, "open", side_effect=tracking_open), mock.patch.object(
                os, "close", side_effect=tracking_close
            ):
                with self.assertRaises(EvidenceError):
                    DirectoryCapability.open(malformed)

            self.assertCountEqual(opened, closed)

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
