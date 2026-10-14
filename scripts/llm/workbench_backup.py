"""Portable local research-state backups, without account credentials.

Restore is deliberately a scratch verification, not a live-state replacement.
No SQL from the archive is executed. Fixed tables receive parameterized rows.
"""
import json
import os
import re
import sqlite3
import tempfile
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

import workbench_evidence as ev

TABLES = {
    "receipts": ("id", "request_hash", "receipt"),
    "drafts": ("revision", "payload"),
    "research_runs": ("id", "request_hash", "receipt"),
    "workspace_events": ("seq", "command_id", "request_hash", "body"),
    "workspace_observations": ("snapshot_hash", "body"),
}
BRIEF_PATH = re.compile(r"snapshot-briefs/[A-Za-z0-9_-]{8,100}/(?:snapshot\.json|report\.md|citations\.json|source-manifest\.json|receipt\.json|SHA256SUMS|sources/\d{3}\.json)\Z")
ARTIFACT_ROOTS = {"research-runs", "snapshot-briefs", "brief-trials", "earnings-trials", "workspaces", "shared-jobs", "frozen-inputs"}


@contextmanager
def sqlite_snapshot(store):
    """Freeze cooperative writers, then use SQLite's backup API, including WAL."""
    with closing(store.connect()) as guard, closing(store.connect()) as source, closing(sqlite3.connect(":memory:")) as image:
        guard.execute("BEGIN IMMEDIATE")
        try:
            source.backup(image)
            if image.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ev.EvidenceError("BACKUP_SQLITE_INTEGRITY_FAILED")
            yield image
        finally:
            guard.rollback()


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
        if name != "data.json" and not name.startswith("research-runs/") and not BRIEF_PATH.fullmatch(name):
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
        if name.startswith("research-runs/") or BRIEF_PATH.fullmatch(name):
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
    with sqlite_snapshot(system.store) as db:
        # Snapshot rows and their immutable replay files under the same writer
        # exclusion used by the workbench. An in-flight replay cannot half-copy.
        events = system.events(db)
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
        import workbench_snapshot_brief as brief
        for job in ws.projection(events)["jobs"]:
            if job["kind"] != "snapshot-brief" or job["status"] != "SUCCEEDED":
                continue
            ws.identifier(job["job_id"])
            relative_root = f"snapshot-briefs/{job['job_id']}"
            receipt = brief.verify(system.store.path.parent / relative_root)
            if (receipt["snapshot_hash"] != job["result"]["snapshot_hash"]
                    or receipt["files"]["report.md"] != job["result"]["report_sha256"]):
                raise ev.EvidenceError("BACKUP_BRIEF_EVENT_BINDING_INVALID")
            for name in [*receipt["files"], "receipt.json", "SHA256SUMS"]:
                relative = f"{relative_root}/{name}"
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


def legacy_jobs(rows):
    from workbench_workspace import projection
    jobs = projection([ev.parse(row[3]) for row in rows])["jobs"]
    for job in jobs:
        job.setdefault("actor", "LEGACY_UNATTRIBUTED")
        job.setdefault("workspace_id", None)
        if job["status"] == "STARTED":
            job.update(status="INTERRUPTED", recovery="LEGACY_NOT_RECOVERABLE")
    return jobs


def _safe_artifact(name):
    parts = name.split("/")
    return (len(parts) >= 2 and parts[0] in ARTIFACT_ROOTS
            and all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}", p) and p not in {".", ".."} for p in parts))


def _validate_tables(tables):
    from workbench_shared_state import ALL_TABLES
    from workbench_workspace import Workspace
    import workbench_snapshot_brief as brief
    if not isinstance(tables, dict) or set(tables) != set(ALL_TABLES):
        raise ev.EvidenceError("BACKUP_TABLE_SET_INVALID")
    for table, columns in ALL_TABLES.items():
        if not isinstance(tables[table], list): raise ev.EvidenceError("BACKUP_TABLE_SHAPE_INVALID")
        for row in tables[table]:
            if not isinstance(row, (list, tuple)) or len(row) != len(columns):
                raise ev.EvidenceError("BACKUP_ROW_SHAPE_INVALID")
            brief.reject_credentials(row)
            for column, value in zip(columns, row):
                if column in {"body", "receipt", "payload"}: brief.reject_credentials(ev.parse(value))
    # Reuse the event-chain boundary against a local fixed-schema scratch image.
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("CREATE TABLE workspace_events(seq, command_id, request_hash, body)")
        db.executemany("INSERT INTO workspace_events VALUES (?, ?, ?, ?)", tables["workspace_events"])
        events = Workspace.events(None, db)
    for identity, raw in tables["workspace_observations"]:
        observation = ev.verify(ev.parse(raw))
        if observation["snapshot_hash"] != identity: raise ev.EvidenceError("BACKUP_OBSERVATION_BINDING_INVALID")
    for login, workspace_id in tables["shared_workspaces"]:
        if not isinstance(login, str) or not login or str(uuid.UUID(workspace_id)) != workspace_id:
            raise ev.EvidenceError("BACKUP_WORKSPACE_ID_INVALID")
    return events[-1]["event_hash"] if events else "0" * 64


def _inventory(root, tables, *, scope="ISOLATED_STATE_ARTIFACT_ROOTS"):
    jobs = {job["job_id"]: job for job in legacy_jobs(tables["workspace_events"])}
    jobs.update({row[0]: ev.parse(row[3]) for row in tables.get("shared_jobs", [])})
    replays = {row[0] for row in tables["research_runs"]}
    files, groups, directories = {}, {}, set()
    for area in sorted(ARTIFACT_ROOTS):
        base = root / area
        if not base.exists() and not base.is_symlink(): continue
        if base.is_symlink() or not base.is_dir(): raise ev.EvidenceError("BACKUP_ARTIFACT_ROOT_UNSAFE")
        directories.add(area)
        for path in sorted(base.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or not _safe_artifact(relative): raise ev.EvidenceError("BACKUP_ORPHAN_UNSAFE")
            if not path.is_dir() and not path.is_file(): raise ev.EvidenceError("BACKUP_ORPHAN_UNSAFE")
            if path.is_dir(): directories.add(relative)
            parts = relative.split("/")
            if area == "workspaces":
                if str(uuid.UUID(parts[1])) != parts[1]: raise ev.EvidenceError("BACKUP_WORKSPACE_PATH_INVALID")
                group = "/".join(parts[:4]) if len(parts) >= 4 else "/".join(parts[:2])
            elif area == "frozen-inputs":
                group = area
            elif area == "shared-jobs":
                group = "/".join(parts[:3])
            else:
                group = "/".join(parts[:2])
            groups.setdefault(group, [])
            if path.is_file():
                raw = ev.read_local(root, relative)
                import workbench_snapshot_brief as brief
                if relative.endswith(".json"): brief.reject_credentials(ev.parse(b'{"artifact":' + raw + b'}'))
                else: brief.reject_credentials(raw.decode("utf-8"))
                files[relative] = raw
                groups[group].append(relative)
    inventory = []
    for group, names in sorted(groups.items()):
        job_id = group.split("/")[-1]
        job = jobs.get(job_id)
        registered_replay = group.startswith("research-runs/") and job_id in replays
        inventory.append({"path": group, "job_id": job_id if job or registered_replay else None,
                          "status": job["status"] if job else "REGISTERED_REPLAY" if registered_replay else "FROZEN_INPUT" if group == "frozen-inputs" else "ORPHAN",
                          "files": sorted(names), "presence": "PRESENT", "source_scope": scope})
    for job_id, job in jobs.items():
        area = {"snapshot-brief": "snapshot-briefs", "brief-trial": "brief-trials", "earnings-trial": "earnings-trials"}.get(job.get("kind"))
        if not area: continue
        group = (f"workspaces/{job['workspace_id']}/" if job.get("workspace_id") else "") + area + "/" + job_id
        if group not in groups:
            inventory.append({"path": group, "job_id": job_id, "status": job["status"], "files": [],
                              "presence": "NOT_PRESENT_IN_ARCHIVED_SCOPE", "source_scope": scope})
    inventory.sort(key=lambda row: row["path"])
    return files, inventory, sorted(directories)


def _verify_completed(root, tables):
    import workbench_snapshot_brief as brief
    import workbench_research as research
    for job in legacy_jobs(tables["workspace_events"]):
        if job["status"] != "SUCCEEDED" or job["kind"] != "snapshot-brief": continue
        base = root
        if job.get("workspace_id"):
            workspace_id = job["workspace_id"]
            if str(uuid.UUID(workspace_id)) != workspace_id: raise ev.EvidenceError("BACKUP_WORKSPACE_ID_INVALID")
            base = base / "workspaces" / workspace_id
        from workbench_workspace import identifier
        identifier(job["job_id"])
        receipt = brief.verify(base / "snapshot-briefs" / job["job_id"])
        if (receipt["snapshot_hash"] != job["result"]["snapshot_hash"]
                or receipt["files"]["report.md"] != job["result"]["report_sha256"]):
            raise ev.EvidenceError("BACKUP_BRIEF_EVENT_BINDING_INVALID")
    for identity, _request, raw in tables["research_runs"]:
        from workbench_workspace import identifier
        identifier(identity)
        receipt = ev.parse(raw)
        if ev.parse(ev.read_local(root, f"research-runs/{identity}/receipt.json")) != receipt:
            raise ev.EvidenceError("BACKUP_REPLAY_RECEIPT_INVALID")
        research.verify_receipt(root / "research-runs" / identity, receipt)
    from workbench_shared_inputs import FrozenInputs
    for snapshot_id, input_hash, body in tables.get("shared_inputs", []):
        try:
            if str(uuid.UUID(snapshot_id)) != snapshot_id: raise ValueError
        except (ValueError, TypeError, AttributeError): raise ev.EvidenceError("BACKUP_SNAPSHOT_ID_INVALID") from None
        FrozenInputs.verify_registered(root / "frozen-inputs", snapshot_id, (input_hash, body))


def backup_shared(store, target_root: Path) -> dict:
    """Export a consistent fixed-table image and every safe isolated artifact."""
    from workbench_shared_state import ALL_TABLES, STORAGE_SCHEMA
    target = Path(target_root)
    if target.exists() or target.is_symlink() or any(p.is_symlink() for p in target.parents):
        raise ev.EvidenceError("BACKUP_REQUIRES_NEW_TARGET")
    source = store.path.parent.resolve(); destination = target.resolve()
    if destination == source or destination in source.parents or source in destination.parents:
        raise ev.EvidenceError("BACKUP_REQUIRES_DISJOINT_TARGET")
    ignored = {"workbench.sqlite3", "shared-workbench.sqlite3", "service.lock", "backups",
               "allowlist.json", "cookie.key", "migration-intent.json", "migration-receipt.json"}
    ignored.update(name + suffix for name in ("workbench.sqlite3", "shared-workbench.sqlite3") for suffix in ("-wal", "-shm", "-journal"))
    if any(p.is_symlink() for p in (store.path.parent, *store.path.parent.parents)):
        raise ev.EvidenceError("BACKUP_SOURCE_SYMLINK")
    if any(p.name not in ARTIFACT_ROOTS | ignored for p in store.path.parent.iterdir()):
        raise ev.EvidenceError("BACKUP_UNCLASSIFIED_ORPHAN_REQUIRES_REVIEW")
    with sqlite_snapshot(store) as db:
        present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = db.execute("SELECT schema FROM shared_metadata WHERE singleton=1").fetchone()[0] if "shared_metadata" in present else "ar-local-workspace.v1"
        if version not in {"ar-local-workspace.v1", "ar.shared-workspace.v1", STORAGE_SCHEMA}:
            raise ev.EvidenceError("BACKUP_STORAGE_SCHEMA_UNSUPPORTED")
        if not set(TABLES).issubset(present) or present - set(ALL_TABLES) - {"shared_metadata", "workspace_owner"}:
            raise ev.EvidenceError("BACKUP_TABLE_SET_INVALID")
        tables = {table: [list(row) for row in db.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY rowid")]
                  if table in present else [] for table, columns in ALL_TABLES.items()}
        tail = _validate_tables(tables)
        files, inventory, directories = _inventory(store.path.parent, tables)
        _verify_completed(store.path.parent, tables)
        target.mkdir(parents=True, mode=0o700)
        for name in directories: (target / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        data = ev.canonical({"schema": "ar-shared-workspace-data-export.v1", "tables": tables}).encode()
        if len(data) > ev.MAX_FILE: raise ev.EvidenceError("BACKUP_DATA_SIZE_LIMIT")
        files["data.json"] = data
        for name, raw in files.items(): write_new(target / name, raw)
        manifest = {"schema": "ar-shared-workspace-backup.v1", "source_storage_schema": version,
                    "credentials_included": False, "sample_purpose": "WORKFLOW_DEBUG", "production_authority": False,
                    "integrity_check": "ok", "table_counts": {t: len(rows) for t, rows in tables.items()},
                    "event_tail": tail, "artifact_inventory": inventory, "directories": directories,
                    "inventory_scope": "ISOLATED_STATE_ARTIFACT_ROOTS",
                    "files": {n: ev.sha(raw) for n, raw in files.items()}}
        manifest = {**manifest, "backup_hash": ev.sealed(manifest)}
        write_new(target / "manifest.json", ev.canonical(manifest).encode())
    verify_shared(target)
    # Scratch restore proves the exported rows and files, not just the source.
    with tempfile.TemporaryDirectory(prefix="shared-restore-check-", dir=target.parent) as temporary:
        checked = restore_shared(target, Path(temporary) / "scratch")
    return {"status": "LOCAL_SHARED_BACKUP_VERIFIED", "backup_hash": manifest["backup_hash"],
            "table_counts": manifest["table_counts"], "event_tail": tail,
            "credentials_included": False, "restore_check": checked}


def read_shared(directory):
    from workbench_shared_state import ALL_TABLES, STORAGE_SCHEMA
    manifest = ev.parse(ev.read_local(directory, "manifest.json"))
    if manifest.get("schema") == "ar-workspace-backup.v1":
        verify(directory)
        data = ev.parse(ev.read_local(directory, "data.json"))
        if data.get("schema") != "ar-workspace-data-export.v1" or set(data.get("tables", {})) != set(TABLES):
            raise ev.EvidenceError("BACKUP_TABLE_SET_INVALID")
        data = {"schema": "ar-shared-workspace-data-export.v1", "tables": {**{t: [] for t in ALL_TABLES}, **data["tables"]}}
        tail = _validate_tables(data["tables"])
        _files, inventory, directories = _inventory(Path(directory), data["tables"], scope="LEGACY_BACKUP_CONTENT_ONLY")
        manifest = {**manifest, "table_counts": {t: len(rows) for t, rows in data["tables"].items()},
                    "event_tail": tail, "artifact_inventory": inventory, "directories": directories,
                    "source_storage_schema": "ar-local-workspace.v1", "inventory_scope": "LEGACY_BACKUP_CONTENT_ONLY"}
        _verify_completed(Path(directory), data["tables"])
        return manifest, data
    if (manifest.get("schema") != "ar-shared-workspace-backup.v1" or manifest.get("credentials_included") is not False
            or manifest.get("production_authority") is not False or manifest.get("integrity_check") != "ok"
            or manifest.get("inventory_scope") != "ISOLATED_STATE_ARTIFACT_ROOTS"
            or manifest.get("source_storage_schema") not in {"ar-local-workspace.v1", "ar.shared-workspace.v1", STORAGE_SCHEMA}
            or ev.sealed({k: v for k, v in manifest.items() if k != "backup_hash"}) != manifest.get("backup_hash")):
        raise ev.EvidenceError("BACKUP_MANIFEST_INVALID")
    catalog = manifest.get("files")
    if not isinstance(catalog, dict) or "data.json" not in catalog: raise ev.EvidenceError("BACKUP_FILE_CATALOG_INVALID")
    actual = {p.relative_to(directory).as_posix() for p in Path(directory).rglob("*") if p.is_file() or p.is_symlink()}
    if actual != set(catalog) | {"manifest.json"}: raise ev.EvidenceError("BACKUP_FILE_SET_INVALID")
    for name, expected in catalog.items():
        if name != "data.json" and not _safe_artifact(name): raise ev.EvidenceError("BACKUP_FILE_PATH_INVALID")
        if expected != ev.sha(ev.read_local(directory, name)): raise ev.EvidenceError("BACKUP_ARTIFACT_HASH_INVALID")
    data = ev.parse(ev.read_local(directory, "data.json"))
    if data.get("schema") != "ar-shared-workspace-data-export.v1": raise ev.EvidenceError("BACKUP_DATA_SCHEMA_INVALID")
    tail = _validate_tables(data.get("tables"))
    _files, inventory, directories = _inventory(Path(directory), data["tables"])
    if ({t: len(rows) for t, rows in data["tables"].items()} != manifest.get("table_counts")
            or tail != manifest.get("event_tail") or inventory != manifest.get("artifact_inventory")
            or directories != manifest.get("directories")):
        raise ev.EvidenceError("BACKUP_COUNTS_CHAIN_OR_INVENTORY_INVALID")
    _verify_completed(Path(directory), data["tables"])
    return manifest, data


def verify_shared(directory):
    return read_shared(Path(directory))[0]


def check_restored(root, manifest, data, receipt):
    from workbench_shared_state import ALL_TABLES, STORAGE_SCHEMA
    database = root / "shared-workbench.sqlite3"
    fence = root / "workbench.sqlite3"
    if database.is_symlink() or not database.is_file() or fence.is_symlink() or not fence.is_dir() or any(fence.iterdir()):
        raise ev.EvidenceError("RESTORE_STATE_FENCE_INVALID")
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as db:
        if (db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
                or db.execute("SELECT schema FROM shared_metadata WHERE singleton=1").fetchone() != (STORAGE_SCHEMA,)):
            raise ev.EvidenceError("RESTORE_SQLITE_INTEGRITY_FAILED")
        for table, columns in ALL_TABLES.items():
            rows = [list(row) for row in db.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY rowid")]
            expected = data["tables"][table]
            if table == "shared_migrations": expected = [*expected, [receipt["backup_hash"], ev.canonical(receipt)]]
            if rows != expected: raise ev.EvidenceError("RESTORE_TABLE_BINDING_INVALID")
        if db.execute("SELECT COUNT(*) FROM workspace_owner").fetchone()[0] != 0:
            raise ev.EvidenceError("RESTORE_OWNER_CREDENTIALS_REFUSED")
    for name, expected in manifest["files"].items():
        if name != "data.json" and ev.sha(ev.read_local(root, name)) != expected:
            raise ev.EvidenceError("RESTORE_ARTIFACT_BINDING_INVALID")
    _files, inventory, directories = _inventory(root, data["tables"], scope=manifest["inventory_scope"])
    if inventory != manifest["artifact_inventory"] or directories != manifest["directories"]:
        raise ev.EvidenceError("RESTORE_ARTIFACT_INVENTORY_INVALID")
    _verify_completed(root, data["tables"])


def restore_shared(backup_root: Path, scratch_root: Path) -> dict:
    from workbench_shared_state import migrate_legacy
    scratch_root = Path(scratch_root)
    if scratch_root.exists() or scratch_root.is_symlink(): raise ev.EvidenceError("RESTORE_REQUIRES_NEW_SCRATCH")
    result = migrate_legacy(Path(backup_root), scratch_root)
    return {**result, "status": "LOCAL_SHARED_RESTORE_VERIFIED"}
