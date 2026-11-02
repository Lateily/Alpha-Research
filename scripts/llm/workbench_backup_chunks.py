"""Bounded, sealed row chunks for complete portable shared-state exports."""
from pathlib import Path

import workbench_evidence as ev

BACKUP_SCHEMA = "ar-shared-workspace-backup.v2"
INDEX_SCHEMA = "ar-shared-workspace-data-index.v2"
CHUNK_SCHEMA = "ar-shared-workspace-table-chunk.v1"
CHUNK_TARGET_BYTES = 4 * 1024 * 1024
MAX_EXPORT_BYTES = 256 * 1024 * 1024
MAX_CHUNKS = 1024
MAX_ROWS = 100000
INDEX_FIELDS = {"schema", "tables", "table_counts", "row_count", "chunk_count", "total_bytes", "index_hash"}
DESCRIPTOR_FIELDS = {"path", "table", "index", "row_start", "row_count", "bytes", "sha256"}
CHUNK_FIELDS = {"schema", "table", "index", "row_start", "rows", "chunk_hash"}


def _fail(reason):
    raise ev.EvidenceError("BACKUP_CHUNK_" + reason)


def _integer(value, maximum, *, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("COUNT_OR_SIZE_INVALID")
    return value


def _path(table, index):
    return f"data-chunks/{table}-{index:06d}.json"


def _encoded_rows(tables):
    count, total, encoded = 0, 0, {}
    for table, rows in tables.items():
        count += len(rows)
        if count > MAX_ROWS:
            _fail("ROW_LIMIT")
        encoded[table] = []
        for row in rows:
            raw = ev.canonical(row).encode()
            if len(raw) > ev.MAX_FILE:
                _fail("ROW_SIZE_LIMIT")
            total += len(raw)
            if total > MAX_EXPORT_BYTES:
                _fail("TOTAL_SIZE_LIMIT")
            encoded[table].append(raw)
    return encoded


def _encode(tables, encoded):
    files, descriptors, counts = {}, {}, {}
    total = 0
    for table, rows in tables.items():
        descriptors[table], counts[table] = [], len(rows)
        start, ordinal = 0, 0
        while start < len(rows):
            body = {"schema": CHUNK_SCHEMA, "table": table, "index": ordinal,
                    "row_start": start, "rows": []}
            overhead = len(ev.canonical({**body, "chunk_hash": "0" * 64}).encode())
            end, size = start, overhead
            while end < len(rows):
                added = len(encoded[table][end]) + (1 if end > start else 0)
                if end > start and size + added > CHUNK_TARGET_BYTES:
                    break
                if size + added > ev.MAX_FILE:
                    _fail("ROW_SIZE_LIMIT")
                size += added
                end += 1
            body["rows"] = rows[start:end]
            raw = ev.canonical({**body, "chunk_hash": ev.sealed(body)}).encode()
            if len(raw) > ev.MAX_FILE:
                _fail("FILE_SIZE_LIMIT")
            total += len(raw)
            # governance-mutation: WORKBENCH_BACKUP_CHUNK_EXPORT_BOUNDS
            if total > MAX_EXPORT_BYTES or len(files) >= MAX_CHUNKS:
                _fail("TOTAL_SIZE_OR_CHUNK_LIMIT")
            name = _path(table, ordinal)
            files[name] = raw
            descriptors[table].append({"path": name, "table": table, "index": ordinal,
                                       "row_start": start, "row_count": end - start,
                                       "bytes": len(raw), "sha256": ev.sha(raw)})
            start, ordinal = end, ordinal + 1
    index = {"schema": INDEX_SCHEMA, "tables": descriptors, "table_counts": counts,
             "row_count": sum(counts.values()), "chunk_count": len(files), "total_bytes": total}
    raw = ev.canonical({**index, "index_hash": ev.sealed(index)}).encode()
    if len(raw) > ev.MAX_FILE or total + len(raw) > MAX_EXPORT_BYTES:
        _fail("TOTAL_SIZE_LIMIT")
    return {"data.json": raw, **files}


def encode(tables):
    """Encode v2 tables; the caller still validates fixed-table semantics."""
    return _encode(tables, _encoded_rows(tables))


def export(tables):
    encoded = _encoded_rows(tables)
    empty = {"schema": "ar-shared-workspace-data-export.v1", "tables": {table: [] for table in tables}}
    size = len(ev.canonical(empty).encode()) + sum(
        sum(map(len, rows)) + max(0, len(rows) - 1) for rows in encoded.values())
    if size <= ev.MAX_FILE:
        return "ar-shared-workspace-backup.v1", {"data.json": ev.canonical(
            {"schema": "ar-shared-workspace-data-export.v1", "tables": tables}).encode()}
    return BACKUP_SCHEMA, _encode(tables, encoded)


def decode(root, index, catalog, columns):
    """Verify the exact ordered chunk set before exposing normalized rows."""
    if (type(index) is not dict or set(index) != INDEX_FIELDS or index.get("schema") != INDEX_SCHEMA
            or ev.sealed({k: v for k, v in index.items() if k != "index_hash"}) != index.get("index_hash")):
        _fail("INDEX_INVALID")
    if (type(index["tables"]) is not dict or set(index["tables"]) != set(columns)
            or type(index["table_counts"]) is not dict or set(index["table_counts"]) != set(columns)):
        _fail("TABLE_SET_INVALID")
    _integer(index["row_count"], MAX_ROWS)
    _integer(index["chunk_count"], MAX_CHUNKS)
    _integer(index["total_bytes"], MAX_EXPORT_BYTES)
    expected, chunk_count, declared_bytes, row_count = {}, 0, 0, 0
    for table, descriptors in index["tables"].items():
        if type(descriptors) is not list or len(descriptors) > MAX_CHUNKS:
            _fail("DESCRIPTOR_SET_INVALID")
        start = 0
        _integer(index["table_counts"][table], MAX_ROWS)
        for ordinal, descriptor in enumerate(descriptors):
            if type(descriptor) is not dict or set(descriptor) != DESCRIPTOR_FIELDS:
                _fail("DESCRIPTOR_INVALID")
            _integer(descriptor["index"], MAX_CHUNKS)
            _integer(descriptor["row_start"], MAX_ROWS)
            length = _integer(descriptor["row_count"], MAX_ROWS, minimum=1)
            byte_count = _integer(descriptor["bytes"], ev.MAX_FILE, minimum=1)
            name = _path(table, ordinal)
            # governance-mutation: WORKBENCH_BACKUP_CHUNK_ORDER
            if (descriptor["path"] != name or descriptor["table"] != table
                    or descriptor["index"] != ordinal or descriptor["row_start"] != start):
                _fail("ORDER_OR_SPAN_INVALID")
            if catalog.get(name) != descriptor["sha256"]:
                _fail("CATALOG_BINDING_INVALID")
            expected[name] = descriptor
            start += length
            declared_bytes += byte_count
            chunk_count += 1
        if start != index["table_counts"][table]:
            _fail("TABLE_COUNT_INVALID")
        row_count += start
    # governance-mutation: WORKBENCH_BACKUP_CHUNK_AGGREGATE
    if (chunk_count != index["chunk_count"] or chunk_count > MAX_CHUNKS
            or row_count != index["row_count"] or row_count > MAX_ROWS
            or declared_bytes != index["total_bytes"] or declared_bytes > MAX_EXPORT_BYTES):
        _fail("AGGREGATE_INVALID")
    if {name for name in catalog if name.startswith("data-chunks/")} != set(expected):
        _fail("FILE_SET_INVALID")
    directory = Path(root) / "data-chunks"
    if directory.is_symlink() or (directory.exists() and (
            not directory.is_dir() or {"data-chunks/" + p.name for p in directory.iterdir()} != set(expected))):
        _fail("FILE_SET_INVALID")
    index_raw = ev.read_local(root, "data.json")
    if ev.sha(index_raw) != catalog.get("data.json") or declared_bytes + len(index_raw) > MAX_EXPORT_BYTES:
        _fail("TOTAL_SIZE_LIMIT")
    tables, total = {table: [] for table in columns}, 0
    for table, descriptors in index["tables"].items():
        identities = set()
        for descriptor in descriptors:
            raw = ev.read_local(root, descriptor["path"])
            # governance-mutation: WORKBENCH_BACKUP_CHUNK_BYTES
            if len(raw) != descriptor["bytes"] or ev.sha(raw) != descriptor["sha256"]:
                _fail("BYTES_OR_HASH_INVALID")
            total += len(raw)
            body = ev.parse(raw)
            if type(body) is not dict or set(body) != CHUNK_FIELDS or body.get("schema") != CHUNK_SCHEMA:
                _fail("BODY_INVALID")
            # governance-mutation: WORKBENCH_BACKUP_CHUNK_SEAL
            if ev.sealed({k: v for k, v in body.items() if k != "chunk_hash"}) != body.get("chunk_hash"):
                _fail("SEAL_INVALID")
            if (type(body["index"]) is not int or type(body["row_start"]) is not int
                    or any(body[key] != descriptor[key] for key in ("table", "index", "row_start"))
                    or type(body["rows"]) is not list or len(body["rows"]) != descriptor["row_count"]):
                _fail("ROW_BINDING_INVALID")
            for row in body["rows"]:
                if (type(row) is not list or len(row) != len(columns[table])
                        or type(row[0]) not in {str, int}):
                    _fail("ROW_SHAPE_INVALID")
                # governance-mutation: WORKBENCH_BACKUP_CHUNK_DUPLICATE
                if row[0] in identities:
                    _fail("DUPLICATE_ROW")
                identities.add(row[0])
            tables[table].extend(body["rows"])
    if total != declared_bytes:
        _fail("TOTAL_SIZE_LIMIT")
    return tables
