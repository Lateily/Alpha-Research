"""Immutable opaque PDF retention; never admission, rendering or execution."""
from pathlib import Path
import re

import foundation_materials as materials
import workbench_backup as backup
import workbench_evidence as ev

POLICY = {"research_use_allowed": False, "render_allowed": False,
          "execution_allowed": False, "transfer_authority": False,
          "disposition": "QUARANTINED_PENDING_SECURITY_REVIEW"}
REASON = "MATERIALS_ACTIVE_OR_ENCRYPTED_PDF_REFUSED"
ENTRY_KEYS = {"material_id", "ts_code", "source_path", "source_locator", "sha256", "size_bytes", "reason"}
MAX_FILES = 64
MAX_BYTES = 64 * 1024 * 1024


def _fail(code):
    raise ValueError("QUARANTINE_" + code)


def _entry(value):
    if type(value) is not dict or set(value) != ENTRY_KEYS or value["reason"] != REASON:
        _fail("ENTRY_INVALID")
    materials._identifier(value["material_id"])
    materials._ticker(value["ts_code"])
    if value["ts_code"] is None or materials._relative(value["source_path"]) != ".pdf":
        _fail("SOURCE_IDENTITY_INVALID")
    materials._hash(value["sha256"])
    if type(value["size_bytes"]) is not int or not 0 < value["size_bytes"] <= ev.MAX_FILE:
        _fail("FILE_SIZE_LIMIT")
    if (type(value["source_locator"]) is not str or len(value["source_locator"]) > 2048
            or not re.fullmatch(r"https?://static\.cninfo\.com\.cn/finalpage/[0-9-]+/[0-9]+\.[Pp][Dd][Ff]", value["source_locator"])):
        _fail("PUBLIC_ORIGIN_REQUIRED")
    return value


def _body(value):
    fields = {"schema", *materials.LABELS, "policy", "created_at", "entries", "quarantine_hash"}
    if (type(value) is not dict or set(value) != fields or value["schema"] != "ar.material-quarantine.v1"
            or ev.canonical(value["policy"]) != ev.canonical(POLICY)
            or any(type(value[key]) is not type(expected) or value[key] != expected
                   for key, expected in materials.LABELS.items())):
        _fail("MANIFEST_OR_AUTHORITY_INVALID")
    materials._time(value["created_at"])
    entries = value["entries"]
    if type(entries) is not list or not 1 <= len(entries) <= MAX_FILES:
        _fail("ENTRY_LIMIT")
    for entry in entries:
        _entry(entry)
    hashes = [entry["sha256"] for entry in entries]
    if hashes != sorted(set(hashes)) or sum(entry["size_bytes"] for entry in entries) > MAX_BYTES:
        _fail("INVENTORY_LIMIT_OR_DUPLICATE")
    body = {key: item for key, item in value.items() if key != "quarantine_hash"}
    if ev.sealed(body) != value["quarantine_hash"]:
        _fail("MANIFEST_HASH_MISMATCH")
    return value


def verify_quarantine(root, *, expected_quarantine_hash=None):
    root = materials._root(root)
    value = _body(ev.parse(ev.read_local(root, "manifest.json")))
    if expected_quarantine_hash is not None and value["quarantine_hash"] != materials._hash(expected_quarantine_hash):
        _fail("EXTERNAL_HASH_MISMATCH")
    if {path.name for path in root.iterdir()} != {"manifest.json", "objects"}:
        _fail("FILE_SET_MISMATCH")
    expected = {entry["sha256"] + ".pdf" for entry in value["entries"]}
    if {path.name for path in (root / "objects").iterdir()} != expected:
        _fail("FILE_SET_MISMATCH")
    files = {"manifest.json": ev.sha(ev.read_local(root, "manifest.json"))}
    for entry in value["entries"]:
        name = "objects/" + entry["sha256"] + ".pdf"
        raw = ev.read_local(root, name)
        if len(raw) != entry["size_bytes"] or ev.sha(raw) != entry["sha256"] or not raw.startswith(b"%PDF-"):
            _fail("OPAQUE_BYTES_MISMATCH")
        files[name] = entry["sha256"]
    return {"schema": "ar.material-quarantine-verification.v1", **materials.LABELS,
            "policy": dict(POLICY), "quarantine_hash": value["quarantine_hash"],
            "files": files, "entries": value["entries"],
            "validation_scope": "OPAQUE_BYTES_AND_METADATA_ONLY_NO_CONTENT_EXECUTION",
            "hash_binding": "MATCHED_EXTERNAL_EXPECTATION" if expected_quarantine_hash else "SELF_CONSISTENCY_ONLY"}


def create_quarantine(source_root, target_root, rows, *, created_at):
    source, target = materials._root(source_root), materials._root(target_root)
    if (source == target or source in target.parents or target in source.parents
            or target.exists() or target.is_symlink() or not target.parent.is_dir()
            or type(rows) is not list or not 1 <= len(rows) <= MAX_FILES):
        _fail("NEW_DISJOINT_ROOT_AND_BOUNDED_ROWS_REQUIRED")
    materials._time(created_at)
    entries, content, total = [], {}, 0
    for row in rows:
        if (type(row) is not dict or row.get("kind") != "original"
                or type(row.get("files")) is not list or len(row["files"]) != 1):
            _fail("SINGLE_ORIGINAL_ROW_REQUIRED")
        item = row["files"][0]
        entry = _entry({"material_id": row["material_id"], "ts_code": row["ts_code"],
                        "source_path": item["source_path"], "source_locator": row["provenance"]["source_locator"],
                        "sha256": item["sha256"], "size_bytes": item["size_bytes"], "reason": REASON})
        raw = ev.read_local(source, entry["source_path"])
        if (len(raw) != entry["size_bytes"] or ev.sha(raw) != entry["sha256"] or not raw.startswith(b"%PDF-")
                or entry["sha256"] in content):
            _fail("SOURCE_HASH_SIZE_OR_TYPE_MISMATCH")
        total += len(raw)
        if total > MAX_BYTES:
            _fail("BYTE_LIMIT")
        entries.append(entry); content[entry["sha256"]] = raw
    value = {"schema": "ar.material-quarantine.v1", **materials.LABELS, "policy": dict(POLICY),
             "created_at": created_at, "entries": sorted(entries, key=lambda entry: entry["sha256"])}
    value["quarantine_hash"] = ev.sealed(value)
    _body(value)
    materials._create_private_root(target, ("objects",))
    backup.fsync_directory(target.parent)
    for digest, raw in content.items():
        backup.write_new(target / "objects" / (digest + ".pdf"), raw)
    backup.write_new(target / "manifest.json", ev.canonical(value).encode())
    return verify_quarantine(target, expected_quarantine_hash=value["quarantine_hash"])
