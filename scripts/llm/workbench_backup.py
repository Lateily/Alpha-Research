"""Portable local research-state backups, without account credentials.

Restore is deliberately a scratch verification, not a live-state replacement.
No SQL from the archive is executed. Fixed tables receive parameterized rows.
"""
import json
import os
import tempfile
from pathlib import Path

import workbench_evidence as ev

TABLES = {
    "receipts": ("id", "request_hash", "receipt"),
    "drafts": ("revision", "payload"),
    "research_runs": ("id", "request_hash", "receipt"),
    "workspace_events": ("seq", "command_id", "request_hash", "body"),
    "workspace_observations": ("snapshot_hash", "body"),
}


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def verify(directory):
    manifest = ev.parse(ev.read_local(directory, "manifest.json"))
    if manifest.get("schema") != "ar-workspace-backup.v1" or manifest.get("credentials_included") is not False:
        raise ev.EvidenceError("BACKUP_SCHEMA_OR_CREDENTIALS_INVALID")
    if ev.sealed({k: v for k, v in manifest.items() if k != "backup_hash"}) != manifest.get("backup_hash"):
        raise ev.EvidenceError("BACKUP_MANIFEST_HASH_INVALID")
    catalog = manifest.get("files")
    if not isinstance(catalog, dict) or "data.json" not in catalog:
        raise ev.EvidenceError("BACKUP_FILE_CATALOG_INVALID")
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file() or p.is_symlink()}
    if actual != set(catalog) | {"manifest.json"}:
        raise ev.EvidenceError("BACKUP_FILE_SET_INVALID")
    for name, expected in catalog.items():
        if name != "data.json" and not name.startswith("research-runs/"):
            raise ev.EvidenceError("BACKUP_FILE_PATH_INVALID")
        if ev.sha(ev.read_local(directory, name)) != expected:
            raise ev.EvidenceError("BACKUP_ARTIFACT_HASH_INVALID")
    return manifest


def restore_check(directory, scratch):
    import nonprod_workbench as wb
    import workbench_workspace as ws

    manifest = verify(directory)
    data = ev.parse(ev.read_local(directory, "data.json"))
    if data.get("schema") != "ar-workspace-data-export.v1" or set(data.get("tables", {})) != set(TABLES):
        raise ev.EvidenceError("BACKUP_TABLE_SET_INVALID")
    if scratch.exists() or scratch.is_symlink():
        raise ev.EvidenceError("RESTORE_REQUIRES_NEW_SCRATCH")
    store = wb.Store(scratch)
    system = ws.Workspace(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for table, columns in TABLES.items():
            for row in data["tables"][table]:
                if not isinstance(row, list) or len(row) != len(columns):
                    raise ev.EvidenceError("BACKUP_ROW_SHAPE_INVALID")
                db.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", row)
    for name in manifest["files"]:
        if name.startswith("research-runs/"):
            write_new(scratch / name, ev.read_local(directory, name))
    result = system.verify_all()
    if result["status"] != "LOCAL_INTEGRITY_OK":
        raise ev.EvidenceError("RESTORE_INTEGRITY_FAILED")
    return {**result, "owner_credentials_restored": False, "production_restored": False}


def create(system, command_id):
    import workbench_workspace as ws
    ws.identifier(command_id)
    base = system.store.path.parent / "backups"
    if base.is_symlink():
        raise ev.EvidenceError("BACKUP_DIRECTORY_SYMLINK")
    base.mkdir(exist_ok=True, mode=0o700)
    if len(list(base.iterdir())) >= 30:
        raise ev.EvidenceError("BACKUP_LIMIT_EXPORT_AND_ROTATE_MANUALLY")
    directory = base / command_id
    directory.mkdir(mode=0o700)  # No reuse of a partial or existing backup.
    catalog = {}
    with system.store.connect() as db:
        # Snapshot rows and their immutable replay files under the same writer
        # exclusion used by the workbench. An in-flight replay cannot half-copy.
        db.execute("BEGIN IMMEDIATE")
        system.events(db)
        tables = {table: db.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY rowid").fetchall() for table, columns in TABLES.items()}
        for _identity, raw in tables["workspace_observations"]:
            ev.verify(json.loads(raw))
        for identity, _request, raw in tables["research_runs"]:
            receipt = system.store.verified_research(identity, json.loads(raw))
            for name in [*receipt["artifacts"], "receipt.json"]:
                relative = f"research-runs/{identity}/{name}"
                raw_file = ev.read_local(system.store.path.parent, relative)
                write_new(directory / relative, raw_file)
                catalog[relative] = ev.sha(raw_file)
        data = ev.canonical({"schema": "ar-workspace-data-export.v1", "tables": tables}).encode()
        if len(data) > ev.MAX_FILE:
            raise ev.EvidenceError("BACKUP_DATA_SIZE_LIMIT")
        write_new(directory / "data.json", data)
        catalog["data.json"] = ev.sha(data)
    manifest = {"schema": "ar-workspace-backup.v1", "sample_purpose": "WORKFLOW_DEBUG", "credentials_included": False,
                "production_authority": False, "files": catalog}
    manifest["backup_hash"] = ev.sealed(manifest)
    write_new(directory / "manifest.json", ev.canonical(manifest).encode())
    verify(directory)
    with tempfile.TemporaryDirectory(prefix="restore-check-", dir=base) as temporary:
        restored = restore_check(directory, Path(temporary) / "new-state")
    return {"status": "LOCAL_BACKUP_VERIFIED", "backup_hash": manifest["backup_hash"], "location": f"backups/{command_id}", "files": len(catalog), "restore_check": restored}
