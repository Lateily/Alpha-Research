"""Opt-in, local-only immutable materials; IMPLEMENTED_UNTESTED, not a ledger.

Metadata uses the evidence canonical/parse contract and backup.write_new. Large
originals use the same no-follow descriptor pattern, with bounded streaming.
"""
from __future__ import annotations

import codecs
import fcntl
import hashlib
import os
import re
import stat
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import workbench_backup as backup
import workbench_evidence as ev
from workbench_snapshot_brief import reject_credentials

LABELS = {"sample_purpose": "WORKFLOW_DEBUG", "testing_status": "NOT_RUN",
          "human_review": "PENDING", "production_authority": False,
          "trading_authority": False, "deployment_authority": False,
          "artifact_pit_use": "NOT_ATTESTED", "prospective_sample_eligible": False}
RIGHTS = {"status": "UNVERIFIED", "visibility": "PRIVATE",
          "sharing_allowed": False, "model_use_allowed": False}
LIMITATIONS = {"rights_verified": False, "formal_case_approval": False,
               "credential_detection": "HEURISTIC_NOT_COMPLETE",
               "source_availability": "CALLER_ASSERTED_NOT_INDEPENDENTLY_ATTESTED",
               "off_machine_durability": "NOT_ATTESTED"}
KINDS = {"original", "thesis", "valuation", "case", "strategy", "review", "attribution"}
MAX_MATERIALS = 256
MAX_FILES = 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_LIBRARY_BYTES = 1024 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
CHUNK_BYTES = 512 * 1024
SUFFIXES = {".pdf", ".txt", ".md", ".csv", ".tsv", ".json"}
ROW_KEYS = {"material_id", "kind", "version", "title", "industry_key",
            "industry_taxonomy", "taxonomy_version", "ts_code", "trade_date",
            "run_id", "code_sha", "published_at", "available_at", "cutoff_at",
            "original_refs", "files", "rights", "provenance", *LABELS}
MANIFEST_KEYS = {"schema", "library_id", "created_at", "materials", *LABELS}
SECRET_PATH = re.compile(r"(?i)(?:^|[._-])(?:env|credentials?|secrets?|passwords?|tokens?|cookies?|id_rsa|id_ed25519|private_key)(?:$|[._-])")
ACTIVE_PDF = re.compile(rb"/(?:JavaScript|JS|Launch|EmbeddedFile|OpenAction|AA|Encrypt)\b")


def _fail(code):
    raise ev.EvidenceError("MATERIALS_" + code)


def _json_copy(value):
    pending, nodes, characters = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 100000 or depth > 16:
            _fail("JSON_LIMIT")
        if type(item) is dict:
            if len(item) > 10000 or any(type(key) is not str for key in item):
                _fail("JSON_SHAPE_INVALID")
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            if len(item) > 10000:
                _fail("JSON_LIMIT")
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            characters += len(item)
            if len(item) > 16384 or characters > MAX_JSON_BYTES:
                _fail("JSON_LIMIT")
        elif item is not None and type(item) not in {bool, int}:
            _fail("JSON_SHAPE_INVALID")
    try:
        raw = ev.canonical(value).encode()
    except (ValueError, OverflowError):
        _fail("JSON_SHAPE_INVALID")
    if len(raw) > MAX_JSON_BYTES:
        _fail("JSON_LIMIT")
    result = ev.parse(raw)
    reject_credentials(result)
    return result


def _exact(value, keys):
    if type(value) is not dict or set(value) != keys:
        _fail("FIELDS_INVALID")


def _fixed(value, expected):
    if type(value) is not dict or ev.canonical(value) != ev.canonical(expected):
        _fail("AUTHORITY_OR_RIGHTS_CONFLICT")


def _labels(value):
    for key, expected in LABELS.items():
        if key in value and (type(value[key]) is not type(expected) or value[key] != expected):
            _fail("AUTHORITY_OR_RIGHTS_CONFLICT")
        value[key] = expected


def _identifier(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", value):
        _fail("IDENTITY_INVALID")
    return value


def _hash(value, length=64):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{%d}" % length, value):
        _fail("HASH_INVALID")
    return value


def _date(value):
    if type(value) is not str or not re.fullmatch(r"[0-9]{8}", value):
        _fail("DATE_INVALID")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        _fail("DATE_INVALID")


def _time(value):
    if (type(value) is not str or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})", value)):
        _fail("TIME_INVALID")
    try:
        if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            raise ValueError
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None:
            raise ValueError
        return result
    except ValueError:
        _fail("TIME_INVALID")


def _ticker(value):
    if value is not None and (type(value) is not str or not re.fullmatch(
            r"(?:[0-9]{6}\.(?:SH|SZ|BJ)|[0-9]{5}\.HK)", value)):
        _fail("TICKER_INVALID")


def _relative(value):
    if (type(value) is not str or len(value) > 1024 or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}(?:/[A-Za-z0-9][A-Za-z0-9_.-]{0,150}){0,7}", value)
            or any(part in {".", ".."} or SECRET_PATH.search(part) for part in value.split("/"))):
        _fail("SOURCE_PATH_INVALID")
    suffix = Path(value).suffix
    if suffix not in SUFFIXES:
        _fail("FILE_TYPE_REFUSED")
    return suffix


def _provenance(value, *, available, created):
    _exact(value, {"publisher", "provider_id", "source_locator", "captured_at"})
    publisher = value["publisher"]
    if (type(publisher) is not str or not publisher.strip() or len(publisher) > 500
            or any(ord(char) < 32 or ord(char) == 127 for char in publisher)):
        _fail("PUBLISHER_INVALID")
    _identifier(value["provider_id"])
    locator = value["source_locator"]
    if type(locator) is not str or not 1 <= len(locator) <= 2048:
        _fail("SOURCE_LOCATOR_INVALID")
    decoded = locator
    for _iteration in range(3):
        decoded = unquote(decoded)
    reject_credentials(decoded)
    if (any(ord(char) <= 32 or ord(char) == 127 for char in decoded)
            or "\\" in decoded or re.search(
                r"(?i)(?:token|api[_-]?key|secret|password|authorization|signature|credential)\s*[=:]", decoded)):
        _fail("SOURCE_LOCATOR_CREDENTIALS_OR_CONTROL")
    if decoded.startswith("document:"):
        _identifier(decoded.removeprefix("document:"))
    else:
        try:
            parsed = urlsplit(decoded)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.query or parsed.fragment
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", parsed.hostname)
                    or parsed.port is not None and not 1 <= parsed.port <= 65535):
                _fail("SOURCE_LOCATOR_INVALID")
        except ValueError:
            _fail("SOURCE_LOCATOR_INVALID")
    if not available <= _time(value["captured_at"]) <= created:
        _fail("CAPTURE_TIME_INVALID")


def _manifest(value):
    value = _json_copy(value)
    _labels(value)
    _exact(value, MANIFEST_KEYS)
    if value["schema"] != "ar.material-intake.v1":
        _fail("MANIFEST_SCHEMA_INVALID")
    _identifier(value["library_id"])
    created = _time(value["created_at"])
    rows = value["materials"]
    if type(rows) is not list or not 1 <= len(rows) <= MAX_MATERIALS:
        _fail("MATERIAL_LIMIT")
    identities, names, hashes = set(), set(), set()
    total, count = 0, 0
    for row in rows:
        if type(row) is not dict:
            _fail("FIELDS_INVALID")
        _labels(row)
        row.setdefault("rights", dict(RIGHTS))
        _exact(row, ROW_KEYS)
        _fixed(row["rights"], RIGHTS)
        identity = (_identifier(row["material_id"]), _identifier(row["version"]))
        if identity in identities:
            _fail("DUPLICATE_IDENTITY")
        identities.add(identity)
        if type(row["kind"]) is not str or row["kind"] not in KINDS:
            _fail("KIND_INVALID")
        if type(row["title"]) is not str or not row["title"].strip() or len(row["title"]) > 500:
            _fail("TITLE_INVALID")
        for key in ("industry_key", "industry_taxonomy", "taxonomy_version", "run_id"):
            _identifier(row[key])
        _hash(row["code_sha"], 40)
        _ticker(row["ts_code"])
        trade = _date(row["trade_date"])
        published, available, cutoff = (_time(row[key]) for key in ("published_at", "available_at", "cutoff_at"))
        if (not published <= available <= created or cutoff > created
                or cutoff.astimezone(timezone(timedelta(hours=8))).date() > trade):
            _fail("FUTURE_CUTOFF_CONTRADICTION")
        if row["kind"] == "original":
            if available > cutoff:
                _fail("ORIGINAL_NOT_AVAILABLE_AT_CUTOFF")
            _provenance(row["provenance"], available=available, created=created)
        elif row["provenance"] is not None:
            _fail("DERIVED_PROVENANCE_MUST_USE_ORIGINAL_REFS")
        refs = row["original_refs"]
        if type(refs) is not list or len(refs) > MAX_FILES:
            _fail("ORIGINAL_REFS_INVALID")
        for reference in refs:
            _hash(reference)
        if len(refs) != len(set(refs)) or (row["kind"] == "original" and refs):
            _fail("ORIGINAL_REFS_INVALID")
        if row["kind"] != "original" and not refs:
            _fail("ORIGINAL_REFS_REQUIRED")
        row["original_refs"] = sorted(refs)
        files = row["files"]
        if type(files) is not list or not 1 <= len(files) <= 16:
            _fail("FILE_COUNT_LIMIT")
        for item in files:
            _exact(item, {"source_path", "sha256", "size_bytes"})
            suffix = _relative(item["source_path"])
            _hash(item["sha256"])
            size = item["size_bytes"]
            if type(size) is not int or not 1 <= size <= MAX_FILE_BYTES or (suffix == ".json" and size > MAX_JSON_BYTES):
                _fail("FILE_SIZE_LIMIT")
            if item["source_path"] in names or item["sha256"] in hashes:
                _fail("DUPLICATE_FILE")
            names.add(item["source_path"])
            hashes.add(item["sha256"])
            total += size
            count += 1
        row["files"] = sorted(files, key=lambda item: item["source_path"])
    if count > MAX_FILES or total > MAX_LIBRARY_BYTES:
        _fail("LIBRARY_LIMIT")
    value["materials"] = sorted(rows, key=lambda row: (row["material_id"], row["version"]))
    return value


def _root(value):
    if not isinstance(value, (str, Path)):
        _fail("ROOT_INVALID")
    raw = str(value)
    if (not raw or len(raw) > 4096 or "://" in raw or "\\" in raw
            or any(part in {".", ".."} for part in raw.split("/"))
            or any(ord(char) < 32 or ord(char) == 127 for char in raw)):
        _fail("ROOT_INVALID")
    result = Path(value).absolute()
    if len(result.parts) > 128 or result == Path(result.anchor):
        _fail("ROOT_INVALID")
    return result


@contextmanager
def _directory(path):
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _child(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        yield fd
    finally:
        os.close(fd)


def _names(fd, limit):
    names = set()
    with os.scandir(fd) as entries:
        for entry in entries:
            names.add(entry.name)
            if len(names) > limit:
                _fail("INVENTORY_LIMIT_OR_UNRECOGNIZED_ROOT")
    return names


def _owned(fd):
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        _fail("LIBRARY_NOT_PRIVATE_OWNED")


@contextmanager
def _regular(parent, name, limit):
    entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if (not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1 or entry.st_mode & 0o111
            or not entry.st_mode & 0o444 or not 1 <= entry.st_size <= limit):
        _fail("FILE_SIZE_TYPE_OR_LINK_INVALID")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = os.fstat(fd)
        if (entry.st_dev, entry.st_ino, entry.st_mode, entry.st_size, entry.st_nlink) != (
                before.st_dev, before.st_ino, before.st_mode, before.st_size, before.st_nlink):
            _fail("FILE_CHANGED_DURING_OPEN")
        yield fd, before
        after = os.fstat(fd)
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        fields = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mode,
                               info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)
        if fields(before) != fields(after) or fields(after) != fields(current):
            _fail("FILE_CHANGED_DURING_READ")
    finally:
        os.close(fd)


def _read_json(fd, name):
    with _regular(fd, name, MAX_JSON_BYTES) as (source, _info):
        raw = bytearray()
        while True:
            chunk = os.read(source, min(CHUNK_BYTES, MAX_JSON_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > MAX_JSON_BYTES:
                _fail("JSON_LIMIT")
    value = _json_copy(ev.parse(bytes(raw)))
    if ev.canonical(value).encode() != raw:
        _fail("METADATA_NOT_CANONICAL")
    return value, ev.sha(bytes(raw))


def _stream(fd, *, size, suffix, destination=None):
    digest, length, tail = hashlib.sha256(), 0, b""
    decoder = None if suffix == ".pdf" else codecs.getincrementaldecoder("utf-8")("strict")
    json_bytes = bytearray() if suffix == ".json" else None
    while True:
        chunk = os.read(fd, CHUNK_BYTES)
        if not chunk:
            break
        length += len(chunk)
        if length > size or length > MAX_FILE_BYTES:
            _fail("FILE_SIZE_LIMIT")
        if length == len(chunk):
            if suffix == ".pdf" and not chunk.startswith(b"%PDF-"):
                _fail("PDF_SIGNATURE_INVALID")
            if chunk.startswith((b"MZ", b"\x7fELF", b"PK\x03\x04", b"#!")):
                _fail("FILE_TYPE_REFUSED")
        window = tail + chunk
        reject_credentials(window.decode("latin-1"))
        if suffix == ".pdf" and ACTIVE_PDF.search(window):
            _fail("ACTIVE_OR_ENCRYPTED_PDF_REFUSED")
        if decoder is not None:
            try:
                text = decoder.decode(chunk)
            except UnicodeDecodeError:
                _fail("TEXT_ENCODING_INVALID")
            if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
                _fail("BINARY_DISGUISED_AS_TEXT")
        if json_bytes is not None:
            json_bytes.extend(chunk)
            if len(json_bytes) > MAX_JSON_BYTES:
                _fail("JSON_LIMIT")
        digest.update(chunk)
        if destination is not None:
            remaining = memoryview(chunk)
            while remaining:
                written = os.write(destination, remaining)
                if not written:
                    _fail("WRITE_INCOMPLETE")
                remaining = remaining[written:]
        tail = window[-4096:]
    if decoder is not None:
        try:
            decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            _fail("TEXT_ENCODING_INVALID")
    if json_bytes is not None:
        _json_copy(ev.parse(bytes(json_bytes)))
    if length != size:
        _fail("FILE_SIZE_MISMATCH")
    return digest.hexdigest()


def _blob_name(item):
    return item["sha256"] + Path(item["source_path"]).suffix


def _lineage(rows):
    identities, originals, hashes, stable = set(), {}, set(), {}
    total, count = 0, 0
    for row in rows:
        identity = (row["material_id"], row["version"])
        if identity in identities:
            _fail("DUPLICATE_IDENTITY")
        identities.add(identity)
        binding = tuple(row[key] for key in ("kind", "industry_key", "industry_taxonomy", "taxonomy_version", "ts_code"))
        if row["material_id"] in stable and stable[row["material_id"]] != binding:
            _fail("IDENTITY_TAXONOMY_CONFLICT")
        stable[row["material_id"]] = binding
        for item in row["files"]:
            if item["sha256"] in hashes:
                _fail("DUPLICATE_FILE")
            hashes.add(item["sha256"])
            count += 1
            total += item["size_bytes"]
            if row["kind"] == "original":
                originals[item["sha256"]] = row
    if len(rows) > MAX_MATERIALS or count > MAX_FILES or total > MAX_LIBRARY_BYTES:
        _fail("LIBRARY_LIMIT")
    for row in rows:
        for reference in row["original_refs"]:
            original = originals.get(reference)
            if original is None:
                _fail("ORIGINAL_NOT_REGISTERED")
            if (_time(original["available_at"]) > _time(row["cutoff_at"])
                    or _time(original["available_at"]) > _time(row["available_at"])):
                _fail("ORIGINAL_NOT_AVAILABLE_AT_CUTOFF")


def _capture_statuses(rows):
    originals = {item["sha256"]: row for row in rows if row["kind"] == "original" for item in row["files"]}
    for row in rows:
        sources = [row] if row["kind"] == "original" else [originals[reference] for reference in row["original_refs"]]
        late = any(_time(source["provenance"]["captured_at"]) > _time(row["cutoff_at"]) for source in sources)
        row["point_in_time_capture_status"] = ("RETROSPECTIVE_CAPTURE" if late
                                               else "CAPTURED_BY_CUTOFF_NOT_INDEPENDENTLY_ATTESTED")


def _marker(library_id):
    return {"schema": "ar.material-library.v1", "library_id": library_id,
            **LABELS, "limitations": dict(LIMITATIONS)}


def _verify_open(root_fd, *, expected_library_hash=None):
    if expected_library_hash is not None:
        _hash(expected_library_hash)
    if _names(root_fd, 2) != {"library.json", "registrations"}:
        _fail("UNRECOGNIZED_OR_INTERRUPTED_LIBRARY")
    marker, marker_hash = _read_json(root_fd, "library.json")
    _identifier(marker.get("library_id"))
    _fixed(marker, _marker(marker["library_id"]))
    files, rows, registrations = {"library.json": marker_hash}, [], []
    with _child(root_fd, "registrations") as registered:
        for identity in sorted(_names(registered, MAX_MATERIALS)):
            _hash(identity)
            with _child(registered, identity) as directory:
                if _names(directory, 2) != {"registration.json", "files"}:
                    _fail("INTERRUPTED_REGISTRATION_QUARANTINED")
                receipt, receipt_hash = _read_json(directory, "registration.json")
                _exact(receipt, {"schema", "manifest", "registration_hash", *LABELS})
                _labels(receipt)
                if receipt["schema"] != "ar.material-registration.v1" or receipt["registration_hash"] != identity:
                    _fail("REGISTRATION_IDENTITY_INVALID")
                body = {key: value for key, value in receipt.items() if key != "registration_hash"}
                if ev.sealed(body) != identity:
                    _fail("REGISTRATION_HASH_MISMATCH")
                manifest = _manifest(receipt["manifest"])
                if manifest != receipt["manifest"] or manifest["library_id"] != marker["library_id"]:
                    _fail("REGISTRATION_MANIFEST_CONFLICT")
                _lineage_limits([*rows, *manifest["materials"]])
                prefix = "registrations/" + identity + "/"
                files[prefix + "registration.json"] = receipt_hash
                expected = {_blob_name(item): item for row in manifest["materials"] for item in row["files"]}
                with _child(directory, "files") as blobs:
                    if _names(blobs, MAX_FILES) != set(expected):
                        _fail("FILE_INVENTORY_MISMATCH")
                    for name, item in expected.items():
                        with _regular(blobs, name, MAX_FILE_BYTES) as (fd, _info):
                            actual = _stream(fd, size=item["size_bytes"], suffix=Path(name).suffix)
                        if actual != item["sha256"]:
                            _fail("ORIGINAL_HASH_MISMATCH")
                        files[prefix + "files/" + name] = actual
                rows.extend({**row, "registration_hash": identity} for row in manifest["materials"])
                registrations.append(identity)
                # Enforce cross-registration bounds before scanning the next one.
                _lineage_limits(rows)
    _lineage(rows)
    _capture_statuses(rows)
    files = dict(sorted(files.items()))
    library_hash = ev.sealed({"schema": "ar.material-library-inventory.v1", "files": files})
    if expected_library_hash is not None and library_hash != expected_library_hash:
        _fail("EXPECTED_LIBRARY_HASH_MISMATCH")
    return {"schema": "ar.material-library-verification.v1", **LABELS,
            "status": "IMPLEMENTED_UNTESTED", "library_id": marker["library_id"],
            "library_hash": library_hash, "files": files,
            "materials": sorted(rows, key=lambda row: (row["material_id"], row["version"])),
            "registrations": registrations, "limitations": dict(LIMITATIONS),
            "hash_binding": "MATCHED_EXTERNAL_EXPECTATION" if expected_library_hash else "SELF_CONSISTENCY_ONLY"}


def _lineage_limits(rows):
    if (len(rows) > MAX_MATERIALS or sum(len(row["files"]) for row in rows) > MAX_FILES
            or sum(item["size_bytes"] for row in rows for item in row["files"]) > MAX_LIBRARY_BYTES):
        _fail("LIBRARY_LIMIT")


def verify_library(library_root, *, expected_library_hash=None) -> dict:
    """Read exact inventory and actual bytes; no write, import, extraction or DB."""
    root = _root(library_root)
    with _directory(root) as fd:
        fcntl.flock(fd, fcntl.LOCK_SH)
        return _verify_open(fd, expected_library_hash=expected_library_hash)


def ingest_material(source_root, library_root, manifest) -> dict:
    """Explicit create-only intake; any interrupted directory blocks later use.

    Invalid writes are deliberately retained, never silently repaired/deleted.
    Registration metadata is the final commit record, not human approval.
    """
    manifest = _manifest(manifest)
    if _time(manifest["created_at"]) > datetime.now(timezone.utc):
        _fail("FUTURE_CREATED_AT")
    source, root = _root(source_root), _root(library_root)
    if source == root or source in root.parents or root in source.parents:
        _fail("ROOTS_MUST_BE_DISJOINT")
    receipt = {"schema": "ar.material-registration.v1", **LABELS, "manifest": manifest}
    identity = ev.sealed(receipt)
    receipt["registration_hash"] = identity
    _json_copy(receipt)
    # Require an existing explicit parent; never create an arbitrary ancestor tree.
    with _directory(source) as source_fd, _directory(root.parent) as parent:
        try:
            os.mkdir(root.name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
        with _child(parent, root.name) as root_fd:
            _owned(root_fd)
            fcntl.flock(root_fd, fcntl.LOCK_EX)
            names = _names(root_fd, 2)
            if not names:
                backup.write_new(root / "library.json", ev.canonical(_marker(manifest["library_id"])).encode())
                os.mkdir("registrations", mode=0o700, dir_fd=root_fd)
                os.fsync(root_fd)
            existing = _verify_open(root_fd)
            if existing["library_id"] != manifest["library_id"]:
                _fail("LIBRARY_IDENTITY_CONFLICT")
            if identity in existing["registrations"]:
                _fail("REGISTRATION_ALREADY_EXISTS")
            _lineage([*existing["materials"], *manifest["materials"]])
            with _child(root_fd, "registrations") as registered:
                os.mkdir(identity, mode=0o700, dir_fd=registered)
                os.fsync(registered)
                with _child(registered, identity) as directory:
                    os.mkdir("files", mode=0o700, dir_fd=directory)
                    os.fsync(directory)
                    seen_inodes = set()
                    with _child(directory, "files") as blobs:
                        for row in manifest["materials"]:
                            for item in row["files"]:
                                parts = item["source_path"].split("/")
                                # Source traversal is manifest-only; never a recursive crawl.
                                fd = os.dup(source_fd)
                                try:
                                    for component in parts[:-1]:
                                        child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                                        os.close(fd)
                                        fd = child
                                    with _regular(fd, parts[-1], MAX_FILE_BYTES) as (original, info):
                                        inode = (info.st_dev, info.st_ino)
                                        if inode in seen_inodes:
                                            _fail("DUPLICATE_SOURCE_INODE")
                                        seen_inodes.add(inode)
                                        target = os.open(_blob_name(item), os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                                                         0o600, dir_fd=blobs)
                                        try:
                                            actual = _stream(original, size=item["size_bytes"],
                                                             suffix=Path(item["source_path"]).suffix, destination=target)
                                            if actual != item["sha256"]:
                                                _fail("ORIGINAL_HASH_MISMATCH")
                                            os.fsync(target)
                                        finally:
                                            os.close(target)
                                finally:
                                    os.close(fd)
                        os.fsync(blobs)
                    # write_new publishes a durable no-replacement metadata inode.
                    destination = root / "registrations" / identity / "registration.json"
                    backup.write_new(destination, ev.canonical(receipt).encode())
            result = _verify_open(root_fd)
    return {**result, "schema": "ar.material-intake-result.v1", "registration_hash": identity}


def query_library(library_root, *, industry_key=None, trade_date=None, ts_code=None) -> dict:
    """Exact metadata filters, only after a full actual-byte reopen verification."""
    if industry_key is not None:
        _identifier(industry_key)
    if trade_date is not None:
        _date(trade_date)
    if ts_code is not None:
        _ticker(ts_code)
    result = verify_library(library_root)
    selected = [row for row in result["materials"]
                if (industry_key is None or row["industry_key"] == industry_key)
                and (trade_date is None or row["trade_date"] == trade_date)
                and (ts_code is None or row["ts_code"] == ts_code)]
    return {**result, "schema": "ar.material-library-query.v1", "materials": selected,
            "query": {"industry_key": industry_key, "trade_date": trade_date, "ts_code": ts_code}}
