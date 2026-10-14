"""Explicit backup-bound migration into a new, atomically promoted state root."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import workbench_evidence as ev
from workbench_backup import TABLES, durable_directory, write_new
from workbench_workspace import Workspace, projection

STORAGE_SCHEMA = "ar.shared-workspace-storage.v2"
SHARED_TABLES = {
    "shared_workspaces": ("login", "workspace_id"),
    "shared_inputs": ("snapshot_id", "input_hash", "body"),
    "shared_jobs": ("job_id", "command_id", "request_hash", "body"),
    "shared_attempts": ("attempt_id", "job_id", "body"),
    "shared_migrations": ("backup_hash", "receipt"),
}
ALL_TABLES = {**TABLES, **SHARED_TABLES}


def initialize(db):
    definitions = {
        "shared_metadata": "singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema TEXT NOT NULL",
        "shared_workspaces": "login TEXT PRIMARY KEY, workspace_id TEXT UNIQUE NOT NULL",
        "shared_inputs": "snapshot_id TEXT PRIMARY KEY, input_hash TEXT UNIQUE NOT NULL, body TEXT NOT NULL",
        "shared_jobs": "job_id TEXT PRIMARY KEY, command_id TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL, body TEXT NOT NULL",
        "shared_attempts": "attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, body TEXT NOT NULL",
        "shared_migrations": "backup_hash TEXT PRIMARY KEY, receipt TEXT NOT NULL",
        "workspace_events": "seq INTEGER PRIMARY KEY, command_id TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL, body TEXT NOT NULL",
        "workspace_observations": "snapshot_hash TEXT PRIMARY KEY, body TEXT NOT NULL",
        "workspace_owner": "singleton INTEGER PRIMARY KEY CHECK(singleton=1), salt TEXT NOT NULL, password_hash TEXT NOT NULL",
    }
    for table, definition in definitions.items():
        db.execute(f"CREATE TABLE IF NOT EXISTS {table} ({definition})")
    db.execute("INSERT OR IGNORE INTO shared_metadata VALUES (1, ?)", (STORAGE_SCHEMA,))
    for table in ("shared_metadata", "shared_workspaces", "shared_inputs", "shared_migrations",
                  "workspace_events", "workspace_observations", "workspace_owner"):
        for action in ("UPDATE", "DELETE"):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'shared immutable'); END")


def _build_state(staging, tables, receipt):
    # The schema, audit rows and migration receipt commit together.
    database = staging / "shared-workbench.sqlite3"
    if database.is_symlink(): raise ev.EvidenceError("MIGRATION_DATABASE_UNSAFE")
    if not database.exists():
        fd = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    with sqlite3.connect(database) as db:
        db.execute("BEGIN IMMEDIATE")
        initialize(db)
        for table, columns in TABLES.items():
            definition = {"receipts": "id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, receipt TEXT NOT NULL",
                          "drafts": "revision INTEGER PRIMARY KEY, payload TEXT NOT NULL",
                          "research_runs": "id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, receipt TEXT NOT NULL"}.get(table)
            if definition: db.execute(f"CREATE TABLE IF NOT EXISTS {table} ({definition})")
        existing = db.execute("SELECT receipt FROM shared_migrations WHERE backup_hash=?", (receipt["backup_hash"],)).fetchone()
        if existing:
            if ev.parse(existing[0]) != receipt: raise ev.EvidenceError("MIGRATION_RECEIPT_CONFLICT")
            return
        for table, columns in ALL_TABLES.items():
            for row in tables.get(table, []):
                db.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", row)
        db.execute("INSERT INTO shared_migrations VALUES (?, ?)", (receipt["backup_hash"], ev.canonical(receipt)))
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ev.EvidenceError("MIGRATION_SQLITE_INTEGRITY_FAILED")
    (staging / "shared-workbench.sqlite3").chmod(0o600)


def _promote(staging, target):
    os.rename(staging, target)
    fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def _ensure(path, raw, *, evidence_root):
    if path.exists() or path.is_symlink():
        if ev.read_local(path.parent, path.name) != raw: raise ev.EvidenceError("MIGRATION_STAGING_CONFLICT")
    else:
        write_new(path, raw, evidence_root=evidence_root)


def _check_historical_evidence(staging, manifest, backup_hash):
    base = staging / "migration-evidence"
    current = base / backup_hash
    expected_dirs = {name for name in manifest["directories"] if name.startswith("migration-evidence/")}
    expected_files = {name: digest for name, digest in manifest["files"].items() if name.startswith("migration-evidence/")}
    directories, files = set(), set()
    for path in base.rglob("*"):
        if path == current or current in path.parents: continue
        name = path.relative_to(staging).as_posix()
        if path.is_symlink(): raise ev.EvidenceError("MIGRATION_HISTORICAL_EVIDENCE_CONFLICT")
        if path.is_dir():
            if name not in expected_dirs: raise ev.EvidenceError("MIGRATION_HISTORICAL_EVIDENCE_CONFLICT")
            directories.add(name)
        elif path.is_file():
            if name not in expected_files or ev.sha(ev.read_local(staging, name)) != expected_files[name]:
                raise ev.EvidenceError("MIGRATION_HISTORICAL_EVIDENCE_CONFLICT")
            files.add(name)
        else: raise ev.EvidenceError("MIGRATION_HISTORICAL_EVIDENCE_CONFLICT")
    # Database creation follows all source artifact writes, so missing history
    # after this boundary is damage, not an unfinished restore to fill in.
    complete = (staging / "shared-workbench.sqlite3").exists()
    # governance-mutation: WORKBENCH_SHARED_HISTORICAL_EVIDENCE_INVENTORY
    if complete and (directories != expected_dirs or files != set(expected_files)):
        raise ev.EvidenceError("MIGRATION_HISTORICAL_EVIDENCE_CONFLICT")


def migrate_legacy(backup_root: Path, target_root: Path) -> dict:
    import workbench_backup as backup
    backup_root, target = Path(backup_root), Path(target_root)
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ev.EvidenceError("MIGRATION_TARGET_SYMLINK")
    source = backup_root.resolve(); destination = target.resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ev.EvidenceError("MIGRATION_REQUIRES_DISJOINT_NEW_TARGET")
    manifest, data = backup.read_shared(backup_root)
    # Limited successful-only exports cannot account for unknown orphan history.
    # governance-mutation: WORKBENCH_SHARED_COMPLETE_MIGRATION_INVENTORY
    if manifest["inventory_scope"] != "ISOLATED_STATE_ARTIFACT_ROOTS":
        raise ev.EvidenceError("BACKUP_COMPLETE_INVENTORY_REQUIRED")
    backup_hash = manifest["backup_hash"]
    staging = target.parent / ("." + target.name + ".migration")
    intent = {"schema": "ar.shared-migration-intent.v1", "backup_hash": backup_hash, "target": target.name}
    evidence_base = staging / "migration-evidence"
    evidence_root = evidence_base / backup_hash
    if "migration-evidence/" + backup_hash in manifest["directories"]:
        raise ev.EvidenceError("MIGRATION_EVIDENCE_BINDING_CONFLICT")
    if target.exists():
        try: prior = ev.parse(ev.read_local(target, "migration-receipt.json"))
        except (OSError, ValueError): raise ev.EvidenceError("MIGRATION_REQUIRES_NEW_TARGET") from None
        # governance-mutation: WORKBENCH_SHARED_MIGRATION_BINDING
        if prior.get("backup_hash") != backup_hash:
            raise ev.EvidenceError("MIGRATION_SOURCE_CONFLICT")
        backup.check_restored(target, manifest, data, prior)
        return prior
    if staging.exists():
        if staging.is_symlink() or not staging.is_dir(): raise ev.EvidenceError("MIGRATION_STAGING_UNSAFE")
        if any(staging.iterdir()):
            has_intent = (staging / "migration-intent.json").exists()
            if has_intent:
                saved = ev.parse(ev.read_local(staging, "migration-intent.json"))
                if saved != intent: raise ev.EvidenceError("MIGRATION_SOURCE_CONFLICT")
            elif any(path.name != "migration-evidence" for path in staging.iterdir()):
                raise ev.EvidenceError("MIGRATION_UNBOUND_STAGING_REQUIRES_RECONCILIATION")
            if evidence_base.exists():
                if evidence_base.is_symlink() or not evidence_base.is_dir(): raise ev.EvidenceError("MIGRATION_STAGING_UNSAFE")
                historical = {name for name in manifest["directories"] if name.startswith("migration-evidence/") and name.count("/") == 1}
                # governance-mutation: WORKBENCH_SHARED_HISTORICAL_EVIDENCE_RETRY
                if any(path.name != backup_hash and (not has_intent or path.relative_to(staging).as_posix() not in historical)
                       for path in evidence_base.iterdir()):
                    raise ev.EvidenceError("MIGRATION_SOURCE_CONFLICT")
            _check_historical_evidence(staging, manifest, backup_hash)
    else:
        durable_directory(staging)
    # A directory entry binds the source before the first byte of intent is written.
    durable_directory(evidence_root)
    _ensure(staging / "migration-intent.json", ev.canonical(intent).encode(), evidence_root=evidence_root)
    jobs = backup.legacy_jobs(data["tables"]["workspace_events"])
    receipt = {"schema": "ar.shared-migration.v1", "status": "SHARED_MIGRATION_VERIFIED",
               "backup_hash": backup_hash, "storage_schema": STORAGE_SCHEMA,
               "source_inventory_scope": manifest["inventory_scope"],
               "table_counts": manifest["table_counts"], "event_tail": manifest["event_tail"],
               "legacy_jobs": jobs,
               "artifact_inventory": [{**row, "source_backup_hash": backup_hash} for row in manifest["artifact_inventory"]],
               "owner_credentials_restored": False, "production_restored": False}
    for name in manifest["directories"]:
        (staging / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in manifest["files"]:
        if name != "data.json": _ensure(staging / name, ev.read_local(backup_root, name), evidence_root=evidence_root)
    fence = staging / "workbench.sqlite3"
    fence.mkdir(exist_ok=True, mode=0o700)
    _build_state(staging, data["tables"], receipt)
    _ensure(staging / "migration-receipt.json", ev.canonical(receipt).encode(), evidence_root=evidence_root)
    backup.check_restored(staging, manifest, data, receipt)
    _promote(staging, target)
    return receipt
