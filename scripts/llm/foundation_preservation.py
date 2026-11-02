"""Read-only, portable preservation handoffs; never storage or restore authority."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path

import workbench_backup as backup
import workbench_evidence as ev

SCHEMA = "ar.preservation-manifest.v1"
LABELS = {"sample_purpose": "WORKFLOW_DEBUG", "testing_status": "NOT_RUN",
          "human_review": "PENDING", "production_authority": False,
          "trading_authority": False, "deployment_authority": False,
          "network_policy": "OFFLINE", "status": "IMPLEMENTED_UNTESTED"}
REQUIREMENTS = {"off_machine_storage": "NOT_ATTESTED", "geographic_separation": "NOT_ATTESTED",
                "encryption": "NOT_ATTESTED", "access_controls": "NOT_ATTESTED",
                "source_rights": "NOT_ATTESTED", "provider_retention": "NOT_ATTESTED",
                "restore": "NOT_ATTESTED", "transmission_approval": "PENDING",
                "restore_approval": "PENDING"}
PRESERVED = {"package_bytes": "EXACT", "lineage_and_seals": "ORIGINAL_VALIDATOR_REQUIRED",
             "unbound_evidence": "PRESERVED_NOT_PROMOTED",
             "rights_and_transmission": "NO_AUTHORITY_GRANTED"}
PACKAGE_FIELDS = {"package_id", "kind", "local_root", "expected_content_hash"}
ROW_FIELDS = {"package_id", "kind", "content_hash", "files", "directories", "total_bytes", "semantics"}
MANIFEST_FIELDS = {"schema", *LABELS, "created_at", "packages", "preserved_semantics",
                   "requirements", "preservation_hash"}
MAX_PACKAGES = 32
MAX_ENTRIES = 16384
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
CHUNK_BYTES = 512 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_JSON_NODES = 300000
MAX_DEPTH = 24


def _fail(code):
    raise ev.EvidenceError("PRESERVATION_" + code)


def _exact(value, fields):
    if type(value) is not dict or len(value) != len(fields) or set(value) != fields:
        _fail("SHAPE_INVALID")


def _json_copy(value, *, max_bytes=MAX_MANIFEST_BYTES):
    pending, nodes, characters = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_DEPTH:
            _fail("JSON_LIMIT")
        if type(item) is dict:
            if len(item) > MAX_JSON_NODES or any(type(key) is not str for key in item):
                _fail("JSON_SHAPE_INVALID")
            pending.extend((child, depth + 1) for child in item.values())
            pending.extend((key, depth + 1) for key in item)
        elif type(item) is list:
            if len(item) > MAX_JSON_NODES:
                _fail("JSON_LIMIT")
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            characters += len(item)
            if characters > max_bytes:
                _fail("JSON_LIMIT")
        elif item is not None and type(item) not in {bool, int, float}:
            _fail("JSON_SHAPE_INVALID")
        elif type(item) is int and item.bit_length() > 64:
            _fail("JSON_NUMBER_INVALID")
    try:
        raw = ev.canonical(value).encode("utf-8")
        if len(raw) > max_bytes:
            _fail("JSON_LIMIT")
        return ev.parse(raw)
    except (OverflowError, RecursionError, UnicodeError, json.JSONDecodeError):
        _fail("JSON_INVALID")


def _hash(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        _fail("HASH_INVALID")
    return value


def _identifier(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", value):
        _fail("PACKAGE_ID_INVALID")
    return value


def _relative(value):
    if type(value) is not str or not value or len(value) > 2048:
        _fail("PATH_INVALID")
    parts = value.split("/")
    if len(parts) > MAX_DEPTH:
        _fail("PATH_INVALID")
    for part in parts:
        if (not re.fullmatch(r"[A-Za-z0-9_.-]{1,151}", part) or part in {".", ".."}
                or part.endswith(".")
                or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)):
            _fail("PATH_INVALID")
    return value


def _time(value):
    if (type(value) is not str or len(value) > 40
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value)):
        _fail("CREATED_AT_INVALID")
    try:
        if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            raise ValueError
        if datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is None:
            raise ValueError
    except ValueError:
        _fail("CREATED_AT_INVALID")
    return value


def _root(value):
    if not isinstance(value, (str, Path)):
        _fail("ROOT_INVALID")
    raw = str(value)
    if (not raw or len(raw) > 4096 or "://" in raw or "\\" in raw
            or any(ord(char) < 32 or ord(char) == 127 for char in raw)):
        _fail("ROOT_INVALID")
    root = Path(value).absolute()
    if ".." in root.parts or len(root.parts) > 128 or root == Path(root.anchor):
        _fail("ROOT_INVALID")
    if any(part.is_symlink() for part in (root, *root.parents)):
        _fail("ROOT_SYMLINK")
    if not root.is_dir():
        _fail("ROOT_INVALID")
    return root


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open_root(root):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    fd = os.open(root.anchor, flags)
    try:
        for part in root.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _inventory(root, *, max_bytes, max_entries):
    """Bound enumeration before delegating to the existing semantic validators."""
    files, directories, total, entries = {}, [], 0, 0

    def walk(fd, prefix=""):
        nonlocal total, entries
        before = os.fstat(fd)
        names, folded = [], set()
        with os.scandir(fd) as scan:
            for entry in scan:
                entries += 1
                if entries > max_entries:
                    _fail("ENTRY_LIMIT")
                name = _relative(prefix + entry.name)
                if entry.name.casefold() in folded:
                    _fail("PORTABLE_PATH_COLLISION")
                folded.add(entry.name.casefold())
                names.append((entry.name, name))
        for child, relative in sorted(names):
            info = os.stat(child, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                _fail("MEMBER_SYMLINK")
            if stat.S_ISDIR(info.st_mode):
                directory_fd = os.open(child, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY, dir_fd=fd)
                try:
                    if _stamp(info) != _stamp(os.fstat(directory_fd)):
                        _fail("PACKAGE_CHANGED")
                    directories.append(relative)
                    walk(directory_fd, relative + "/")
                finally:
                    os.close(directory_fd)
            elif stat.S_ISREG(info.st_mode):
                if not info.st_mode & 0o444 or info.st_size > MAX_FILE_BYTES or total + info.st_size > max_bytes:
                    _fail("BYTE_LIMIT_OR_UNREADABLE")
                file_fd = os.open(child, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(file_fd, "rb") as stream:
                    if _stamp(info) != _stamp(os.fstat(stream.fileno())):
                        _fail("PACKAGE_CHANGED")
                    digest, length = hashlib.sha256(), 0
                    while True:
                        chunk = stream.read(min(CHUNK_BYTES, info.st_size - length + 1))
                        if not chunk:
                            break
                        length += len(chunk)
                        if length > info.st_size:
                            _fail("PACKAGE_CHANGED")
                        digest.update(chunk)
                    if (length != info.st_size
                            or _stamp(info) != _stamp(os.fstat(stream.fileno()))):
                        _fail("PACKAGE_CHANGED")
                total += length
                files[relative] = digest.hexdigest()
            else:
                _fail("MEMBER_NOT_REGULAR")
        if _stamp(before) != _stamp(os.fstat(fd)):
            _fail("PACKAGE_CHANGED")

    root_fd = _open_root(root)
    try:
        identity = _stamp(os.fstat(root_fd))
        walk(root_fd)
        if identity != _stamp(root.stat(follow_symlinks=False)):
            _fail("PACKAGE_CHANGED")
    finally:
        os.close(root_fd)
    return {"files": dict(sorted(files.items())), "directories": sorted(directories), "total_bytes": total}


def _read_json(root, relative, files):
    raw = ev.read_local(root, relative)
    if files.get(relative) != ev.sha(raw):
        _fail("PACKAGE_CHANGED")
    try:
        return _json_copy(ev.parse(raw), max_bytes=ev.MAX_FILE)
    except (RecursionError, UnicodeError, json.JSONDecodeError):
        _fail("PACKAGE_JSON_INVALID")


def _package(package_id, kind, root, expected, *, max_bytes, max_entries):
    inventory = _inventory(root, max_bytes=max_bytes, max_entries=max_entries)
    if kind == "SHARED_BACKUP":
        original = _read_json(root, "manifest.json", inventory["files"])
        _read_json(root, "data.json", inventory["files"])
        if original.get("backup_hash") != expected:
            _fail("EXPECTED_CONTENT_HASH_MISMATCH")
        manifest, _data = backup.read_shared(root)
        if manifest.get("backup_hash") != expected:
            _fail("EXPECTED_CONTENT_HASH_MISMATCH")
        catalog = {**manifest["files"], "manifest.json": inventory["files"]["manifest.json"]}
        semantics = {"validator": "workbench_backup.read_shared/verify_shared",
                     **{key: manifest[key] for key in ("schema", "inventory_scope", "source_storage_schema",
                                                     "credentials_included", "event_tail", "table_counts",
                                                     "artifact_inventory", "directories")}}
        if backup.verify_shared(root) != manifest:
            _fail("PACKAGE_CHANGED")
    else:
        from foundation_materials import verify_library
        library = verify_library(root, expected_library_hash=expected)
        if type(library) is not dict or library.get("library_hash") != expected:
            _fail("EXPECTED_CONTENT_HASH_MISMATCH")
        catalog = library.get("files")
        semantics = {"validator": "foundation_materials.verify_library",
                     "validation_scope": "EXISTING_LIBRARY_BYTES_AND_LINEAGE"}
    if type(catalog) is not dict or catalog != inventory["files"]:
        _fail("VALIDATOR_FILE_SET_MISMATCH")
    if inventory != _inventory(root, max_bytes=max_bytes, max_entries=max_entries):
        _fail("PACKAGE_CHANGED")
    return {"package_id": package_id, "kind": kind, "content_hash": expected,
            **inventory, "semantics": _json_copy(semantics)}


def _requests(packages):
    if type(packages) not in {list, tuple} or not 1 <= len(packages) <= MAX_PACKAGES:
        _fail("PACKAGE_LIMIT_OR_SHAPE")
    result, identities, roots = [], set(), []
    for package in packages:
        _exact(package, PACKAGE_FIELDS)
        identity = _identifier(package["package_id"])
        kind = package["kind"]
        if type(kind) is not str or kind not in {"SHARED_BACKUP", "RESEARCH_LIBRARY"}:
            _fail("PACKAGE_KIND_INVALID")
        if identity.casefold() in identities:
            _fail("PACKAGE_ID_DUPLICATE")
        identities.add(identity.casefold())
        expected = _hash(package["expected_content_hash"])
        root = _root(package["local_root"])
        if any(root == other or root in other.parents or other in root.parents for other in roots):
            _fail("PACKAGE_ROOT_OVERLAP")
        roots.append(root)
        result.append((identity, kind, root, expected))
    return sorted(result)


def build_preservation_manifest(packages, *, created_at) -> dict:
    """Bind existing package bytes to caller-retained hashes; write/copy nothing."""
    created_at = _time(created_at)
    requests = _requests(packages)
    rows, remaining_bytes, remaining_entries = [], MAX_TOTAL_BYTES, MAX_ENTRIES
    for identity, kind, root, expected in requests:
        try:
            row = _package(identity, kind, root, expected,
                           max_bytes=remaining_bytes, max_entries=remaining_entries)
        except (KeyError, TypeError, RecursionError, UnicodeError, json.JSONDecodeError):
            _fail("PACKAGE_VALIDATION_INVALID")
        remaining_bytes -= row["total_bytes"]
        remaining_entries -= len(row["files"]) + len(row["directories"])
        rows.append(row)
    manifest = {"schema": SCHEMA, **LABELS, "created_at": created_at, "packages": rows,
                "preserved_semantics": dict(PRESERVED), "requirements": dict(REQUIREMENTS)}
    manifest = _json_copy(manifest)
    manifest["preservation_hash"] = ev.sealed(manifest)
    return _json_copy(manifest)


def verify_preservation_copy(manifest, package_roots, *, expected_preservation_hash) -> dict:
    """Re-read exact destination package IDs and bytes; never attest remote storage."""
    expected = _hash(expected_preservation_hash)
    manifest = _json_copy(manifest)
    _exact(manifest, MANIFEST_FIELDS)
    if (manifest["schema"] != SCHEMA or manifest["requirements"] != REQUIREMENTS
            or manifest["preserved_semantics"] != PRESERVED
            or any(type(manifest[key]) is not type(value) or manifest[key] != value
                   for key, value in LABELS.items())):
        _fail("LABEL_OR_AUTHORITY_INVALID")
    _time(manifest["created_at"])
    body = {key: value for key, value in manifest.items() if key != "preservation_hash"}
    if _hash(manifest["preservation_hash"]) != expected or ev.sealed(body) != expected:
        _fail("EXPECTED_PRESERVATION_HASH_MISMATCH")
    rows = manifest["packages"]
    if type(rows) is not list or not 1 <= len(rows) <= MAX_PACKAGES:
        _fail("PACKAGE_LIMIT_OR_SHAPE")
    for row in rows:
        _exact(row, ROW_FIELDS)
        _identifier(row["package_id"])
    ids = [row["package_id"] for row in rows]
    if len({identity.casefold() for identity in ids}) != len(ids) or ids != sorted(ids):
        _fail("PACKAGE_ID_DUPLICATE_OR_ORDER")
    if (type(package_roots) is not dict or len(package_roots) != len(ids)
            or set(package_roots) != set(ids)):
        _fail("DESTINATION_PACKAGE_SET_MISMATCH")
    requests = [{"package_id": row["package_id"], "kind": row["kind"],
                 "local_root": package_roots[row["package_id"]],
                 "expected_content_hash": row["content_hash"]} for row in rows]
    reopened = build_preservation_manifest(requests, created_at=manifest["created_at"])
    if ev.canonical(reopened) != ev.canonical(manifest):
        _fail("DESTINATION_PACKAGE_BINDING_MISMATCH")
    return {"schema": "ar.preservation-copy-verification.v1", **LABELS,
            "preservation_hash": expected, "verified_package_ids": ids,
            "verification_scope": "PACKAGE_BYTES_AND_ORIGINAL_VALIDATORS_ONLY",
            "package_bytes": "MATCH", "requirements": dict(REQUIREMENTS),
            "preserved_semantics": dict(PRESERVED)}
