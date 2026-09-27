"""Immutable, descriptor-captured evidence for U4 validation."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping


class EvidenceError(RuntimeError):
    pass


def normalize_ref(ref: str) -> str:
    if not isinstance(ref, str) or not ref or "\0" in ref:
        raise EvidenceError("evidence ref must be a non-empty string")
    path = PurePosixPath(ref)
    if not path.parts or path.is_absolute() or path.as_posix() != ref or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise EvidenceError(f"evidence ref must be normalized and root-relative: {ref}")
    return ref


def join_ref(parent: str, child: str) -> str:
    normalize_ref(parent)
    normalize_ref(child)
    if len(PurePosixPath(child).parts) != 1:
        raise EvidenceError(f"bundle artifact name must be one component: {child}")
    return normalize_ref(f"{parent}/{child}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_object(raw: bytes, ref: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot decode JSON object from {ref}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"JSON root must be an object: {ref}")
    return value


class DirectoryCapability:
    """A retained directory descriptor acquired component-by-component from `/`."""

    def __init__(self, descriptor: int, label: str) -> None:
        self._descriptor = descriptor
        self._label = label

    @classmethod
    def open(cls, root: os.PathLike[str] | str) -> "DirectoryCapability":
        raw = os.fspath(root)
        if (
            not isinstance(raw, str)
            or not raw
            or "\0" in raw
            or not os.path.isabs(raw)
            or os.path.normpath(raw) != raw
        ):
            raise EvidenceError(f"capability root must be one normalized absolute path: {raw}")
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory_flags |= getattr(os, "O_CLOEXEC", 0)
        descriptor = -1
        try:
            descriptor = os.open("/", directory_flags)
            for component in PurePosixPath(raw).parts[1:]:
                expected = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                if not stat.S_ISDIR(expected.st_mode):
                    raise EvidenceError(
                        f"capability root component is not a directory: {component}"
                    )
                next_descriptor = os.open(
                    component,
                    directory_flags,
                    dir_fd=descriptor,
                )
                try:
                    actual = os.fstat(next_descriptor)
                    if _inode_identity(expected) != _inode_identity(actual):
                        raise EvidenceError(
                            f"capability root changed during acquisition: {raw}"
                        )
                except BaseException:
                    os.close(next_descriptor)
                    raise
                previous_descriptor = descriptor
                descriptor = next_descriptor
                os.close(previous_descriptor)
            result = cls(descriptor, raw)
            descriptor = -1
            return result
        except EvidenceError:
            raise
        except (OSError, ValueError) as exc:
            raise EvidenceError(f"cannot acquire directory capability {raw}: {exc}") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def close(self) -> None:
        if self._descriptor >= 0:
            os.close(self._descriptor)
            self._descriptor = -1

    def __enter__(self) -> "DirectoryCapability":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def read_file(self, ref: str) -> bytes:
        normalized = normalize_ref(ref)
        if self._descriptor < 0:
            raise EvidenceError("directory capability is closed")
        parts = PurePosixPath(normalized).parts
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory_flags |= getattr(os, "O_CLOEXEC", 0)
        file_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        file_flags |= getattr(os, "O_CLOEXEC", 0)
        parent = os.dup(self._descriptor)
        descriptor = -1
        try:
            for component in parts[:-1]:
                expected = os.stat(component, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISDIR(expected.st_mode):
                    raise EvidenceError(
                        f"evidence ref ancestor is not a directory: {normalized}"
                    )
                next_parent = os.open(component, directory_flags, dir_fd=parent)
                try:
                    actual = os.fstat(next_parent)
                    if _inode_identity(expected) != _inode_identity(actual):
                        raise EvidenceError(
                            f"evidence ref changed during directory acquisition: {normalized}"
                        )
                except BaseException:
                    os.close(next_parent)
                    raise
                previous_parent = parent
                parent = next_parent
                os.close(previous_parent)
            expected = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(expected.st_mode):
                raise EvidenceError(f"evidence ref is not a regular file: {normalized}")
            descriptor = os.open(parts[-1], file_flags, dir_fd=parent)
            before = os.fstat(descriptor)
            if _inode_identity(expected) != _inode_identity(before):
                raise EvidenceError(f"evidence changed before capture: {normalized}")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
            identity = lambda value: (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )
            if identity(before) != identity(after) or len(raw) != after.st_size:
                raise EvidenceError(f"evidence changed while being captured: {normalized}")
            return raw
        except EvidenceError:
            raise
        except OSError as exc:
            raise EvidenceError(
                f"cannot read evidence ref {normalized} from {self._label}: {exc}"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent)


def _inode_identity(value: os.stat_result) -> tuple[int, int, int]:
    return value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode)


class EvidenceView:
    """An immutable mapping from logical refs to the exact captured bytes."""

    def __init__(self, files: Mapping[str, bytes]) -> None:
        captured: dict[str, bytes] = {}
        for ref, raw in files.items():
            normalized = normalize_ref(ref)
            if not isinstance(raw, bytes):
                raise EvidenceError(f"evidence bytes are invalid: {normalized}")
            captured[normalized] = raw
        self._files = MappingProxyType(captured)

    @property
    def files(self) -> Mapping[str, bytes]:
        return self._files

    def bytes(self, ref: str) -> bytes:
        normalized = normalize_ref(ref)
        try:
            return self._files[normalized]
        except KeyError as exc:
            raise EvidenceError(f"missing evidence: {normalized}") from exc

    def json_object(self, ref: str) -> dict[str, Any]:
        normalized = normalize_ref(ref)
        return _decode_object(self.bytes(normalized), normalized)

    def sha256(self, ref: str) -> str:
        return hashlib.sha256(self.bytes(ref)).hexdigest()

    @classmethod
    def capture_u4(
        cls,
        capability: DirectoryCapability,
        *,
        packet_ref: str,
        diagnostic_ref: str,
        bundle_ref: str,
        feature_health_ref: str,
        funnel_health_ref: str,
        cyclical_flags_ref: str | None,
    ) -> "EvidenceView":
        refs = {
            normalize_ref(packet_ref),
            normalize_ref(diagnostic_ref),
            normalize_ref(feature_health_ref),
            normalize_ref(funnel_health_ref),
        }
        bundle_ref = normalize_ref(bundle_ref)
        manifest_ref = join_ref(bundle_ref, "manifest.json")
        manifest_raw = capability.read_file(manifest_ref)
        manifest = _decode_object(manifest_raw, manifest_ref)
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or any(
            not isinstance(name, str) or not isinstance(digest, str)
            for name, digest in artifacts.items()
        ):
            raise EvidenceError("bundle manifest artifacts must be a string mapping")
        refs.update(join_ref(bundle_ref, name) for name in artifacts)
        refs.update(
            join_ref(bundle_ref, f"stage_{stage}.json")
            for stage in ("candidates", "battery", "finalize")
        )
        if cyclical_flags_ref is not None:
            refs.add(normalize_ref(cyclical_flags_ref))

        refs.discard(manifest_ref)
        captured = {manifest_ref: manifest_raw}
        captured.update({ref: capability.read_file(ref) for ref in sorted(refs)})
        for name, expected in artifacts.items():
            artifact_ref = join_ref(bundle_ref, name)
            actual = hashlib.sha256(captured[artifact_ref]).hexdigest()
            if actual != expected:
                raise EvidenceError(f"bundle artifact hash mismatch: {name}")
        return cls(captured)
