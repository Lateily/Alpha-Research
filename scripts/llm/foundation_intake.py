"""Anchored local CNINFO intake; no acquisition, approval or off-machine transfer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import urlsplit

import foundation_materials as materials
from foundation_quarantine import REASON as QUARANTINE_REASON, create_quarantine
from foundation_preservation import build_preservation_manifest, verify_preservation_copy
from foundation_runtime import collect_runtime_inventory
import workbench_backup as backup
import workbench_evidence as ev

LABELS = {**materials.LABELS, "network_policy": "OFFLINE"}
REQUEST_KEYS = {"schema", "source_root", "manifests", "classification", "run_id",
                "library_id", "research_date", "cutoff_at", "created_at", "code_sha"}
HASH = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\Z")
MAX_ANCHORS = 10


def _fail(code):
    raise ValueError("INTAKE_" + code)


def _exact(value, keys):
    if type(value) is not dict or set(value) != keys:
        _fail("FIELDS_INVALID")


def _identifier(value):
    if type(value) is not str or not ID.fullmatch(value):
        _fail("IDENTITY_INVALID")
    return value


def _hash(value):
    if type(value) is not str or not HASH.fullmatch(value):
        _fail("HASH_INVALID")
    return value


def _relative(value):
    if (type(value) is not str or not 0 < len(value) <= 1024 or "\\" in value or ":" in value
            or value.startswith("/") or any(ord(char) < 32 for char in value)
            or any(part in {".", ".."} for part in value.split("/"))
            or PurePosixPath(value).as_posix() != value):
        _fail("PATH_INVALID")
    return value


def _time(value):
    return materials._time(value)


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_anchor(root, relative, expected):
    raw = ev.read_local(root, _relative(relative))
    if len(raw) > 1024 * 1024 or ev.sha(raw) != _hash(expected):
        _fail("EXTERNAL_ANCHOR_HASH_MISMATCH")
    return raw


def _request(value):
    _exact(value, REQUEST_KEYS)
    if value["schema"] != "ar.cninfo-intake-request.v1":
        _fail("SCHEMA_INVALID")
    for key in ("run_id", "library_id"):
        _identifier(value[key])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,70}", value["library_id"]):
        _fail("PORTABLE_LIBRARY_ID_REQUIRED")
    if type(value["code_sha"]) is not str or not re.fullmatch(r"[0-9a-f]{40}", value["code_sha"]):
        _fail("CODE_SHA_INVALID")
    day = materials._date(value["research_date"])
    created, cutoff = _time(value["created_at"]), _time(value["cutoff_at"])
    if cutoff > created or created > datetime.now(timezone.utc) or cutoff.astimezone(timezone(timedelta(hours=8))).date() > day:
        _fail("TIME_CONFLICT")
    entries = value["manifests"]
    if type(entries) is not list or not 1 <= len(entries) <= MAX_ANCHORS:
        _fail("MANIFEST_LIMIT")
    seen, paths = set(), set()
    for entry in entries:
        _exact(entry, {"ts_code", "relative_path", "expected_sha256"})
        if type(entry["ts_code"]) is not str or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", entry["ts_code"]):
            _fail("TICKER_INVALID")
        _relative(entry["relative_path"])
        _hash(entry["expected_sha256"])
        if entry["ts_code"] in seen or entry["relative_path"] in paths:
            _fail("DUPLICATE_ANCHOR")
        seen.add(entry["ts_code"]); paths.add(entry["relative_path"])
    classification = value["classification"]
    if classification is not None:
        _exact(classification, {"industry_key", "taxonomy_version", "evidence_path", "expected_sha256"})
        _identifier(classification["industry_key"]); _identifier(classification["taxonomy_version"])
        _relative(classification["evidence_path"]); _hash(classification["expected_sha256"])
    return value


def _originals(value):
    if value.get("schema") != "loop_v1.source_manifest.v1":
        _fail("LEGACY_SCHEMA_INVALID")
    variants = [key for key in ("raw_files", "originals", "pdf_originals") if key in value]
    if len(variants) != 1:
        _fail("LEGACY_VARIANT_AMBIGUOUS")
    kind, rows = variants[0], value[variants[0]]
    if kind == "raw_files" and type(rows) is list:
        result = [(row.get("source_name"), row) for row in rows if type(row) is dict]
        if len(result) != len(rows):
            _fail("LEGACY_ROWS_INVALID")
    elif kind in {"originals", "pdf_originals"} and type(rows) is dict:
        result = list(rows.items())
    else:
        _fail("LEGACY_ROWS_INVALID")
    if not 1 <= len(result) <= materials.MAX_MATERIALS:
        _fail("LEGACY_ROW_LIMIT")
    return kind, result


def _field(name, row, metadata):
    candidates = [value[name] for value in (row, *metadata) if name in value and value[name] is not None]
    if not candidates:
        _fail("LEGACY_REQUIRED_METADATA_MISSING")
    if any(ev.canonical(value) != ev.canonical(candidates[0]) for value in candidates[1:]):
        _fail("LEGACY_METADATA_CONFLICT")
    return candidates[0]


def _material(request, anchor, document, source_name, row):
    if type(row) is not dict or type(source_name) is not str or len(source_name) > 160:
        _fail("LEGACY_ROW_INVALID")
    metadata = []
    for key in ("capture_meta", "capture"):
        group = document.get(key, {})
        if type(group) is not dict:
            _fail("CAPTURE_METADATA_INVALID")
        if source_name in group:
            if type(group[source_name]) is not dict:
                _fail("CAPTURE_METADATA_INVALID")
            metadata.append(group[source_name])
    ticker = anchor["ts_code"]
    if row.get("company") != ticker or document.get("ticker", ticker) != ticker:
        _fail("COMPANY_IDENTITY_CONFLICT")
    if row.get("format") != "pdf" or _field("http_status", row, metadata) != 200:
        _fail("ORIGINAL_NOT_CAPTURED_PDF")
    raw_path = _relative(row.get("path"))
    if Path(raw_path).suffix.lower() != ".pdf":
        _fail("ORIGINAL_NOT_PDF")
    source_path = (PurePosixPath(anchor["relative_path"]).parent / raw_path).as_posix()
    _relative(source_path)
    expected = _hash(row.get("sha256"))
    size = _field("bytes", row, metadata)
    if type(size) is not int or not 0 < size <= materials.MAX_FILE_BYTES:
        _fail("ORIGINAL_SIZE_INVALID")
    title = _field("title", row, metadata)
    if type(title) is not str or not 0 < len(title) <= 500:
        _fail("TITLE_INVALID")
    origin = row.get("origin")
    if type(origin) is not str or len(origin) > 2048:
        _fail("ORIGIN_INVALID")
    parsed = urlsplit(origin)
    match = re.search(r"/([0-9]{8,20})\.pdf\Z", parsed.path, re.IGNORECASE)
    if (parsed.scheme not in {"http", "https"} or parsed.hostname != "static.cninfo.com.cn"
            or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or not match):
        _fail("ORIGIN_NOT_PUBLIC_CNINFO")
    published_day = materials._date(row.get("published_on"))
    published = datetime.combine(published_day, datetime.max.time().replace(microsecond=0),
                                 tzinfo=timezone(timedelta(hours=8))).isoformat()
    captured = row.get("observed_at")
    _time(captured)
    classification = request["classification"]
    result = {"material_id": "cninfo-" + ticker[:6] + "-" + match.group(1), "kind": "original",
              "version": "sha256-" + expected[:24], "title": title,
              "industry_key": classification["industry_key"] if classification else "UNSPECIFIED",
              "industry_taxonomy": "AR_RESEARCH_COHORT" if classification else "UNSPECIFIED",
              "taxonomy_version": classification["taxonomy_version"] if classification else "UNSPECIFIED",
              "ts_code": ticker, "trade_date": request["research_date"], "run_id": request["run_id"],
              "code_sha": request["code_sha"], "published_at": published,
              "available_at": captured, "cutoff_at": request["cutoff_at"],
              "provenance": {"publisher": "UNVERIFIED_PUBLISHER_CNINFO_DISCLOSURE", "provider_id": "cninfo",
                             "source_locator": origin, "captured_at": captured,
                             "publication_precision": {"basis": "DATE_ONLY_UPPER_BOUND_NOT_OBSERVED_TIME",
                                                       "published_on": row["published_on"]}},
              "original_refs": [], "rights": dict(materials.RIGHTS),
              "files": [{"source_path": source_path, "sha256": expected, "size_bytes": size}], **materials.LABELS}
    return result


def _manifest(request, rows):
    return {"schema": "ar.material-intake.v1", "library_id": request["library_id"],
            "created_at": request["created_at"], "materials": rows, **materials.LABELS}


def _reason(error):
    message = str(error)
    return message if re.fullmatch(r"[A-Z][A-Z0-9_]{1,120}", message) else "INTAKE_INPUT_REFUSED"


def _execution_identity(request):
    root = Path(__file__).resolve().parents[2]
    inventory = collect_runtime_inventory({"candidate": str(root)}, [], observed_at=request["created_at"])
    row = inventory["repositories"][0]
    if row["status"] != "OBSERVED_LOCAL_ONLY" or row["code_sha"] != request["code_sha"] or row["dirty"] is not False:
        _fail("CLEAN_EXPECTED_CODE_REQUIRED")
    names = ("foundation_intake.py", "foundation_materials.py", "foundation_preservation.py",
             "foundation_quarantine.py", "foundation_runtime.py", "foundation_cli.py", "workbench_backup.py", "workbench_evidence.py")
    files = {"scripts/llm/" + name: ev.sha(ev.read_local(root, "scripts/llm/" + name)) for name in names}
    return {"code_sha": row["code_sha"], "implementation_files": files, "source_tree_hash": ev.sealed(files),
            "python_version": ".".join(map(str, sys.version_info[:3])), "scope": "LOCAL_CLEAN_HEAD_AND_LISTED_FILES_ONLY"}


def run_cninfo_intake(request, output_root):
    """Execute explicit local intake and retain evidence outside the exact library."""
    request = _request(ev.parse(ev.canonical(request).encode()))
    root, source = materials._root(output_root), materials._root(request["source_root"])
    if root == source or root in source.parents or source in root.parents:
        _fail("ROOT_OVERLAP")
    if root.exists() or root.is_symlink() or not root.parent.is_dir():
        _fail("NEW_OUTPUT_ROOT_WITH_EXISTING_PARENT_REQUIRED")
    identity = _execution_identity(request)
    anchors, rows, rejected, source_rows, seen, seen_files = [], [], [], [], set(), set()
    quarantine_rows = []
    for anchor in request["manifests"]:
        raw = _read_anchor(source, anchor["relative_path"], anchor["expected_sha256"])
        document = ev.parse(raw)
        variant, originals = _originals(document)
        anchors.append({"path": anchor["relative_path"], "sha256": anchor["expected_sha256"], "raw": raw})
        source_rows.append({"ts_code": anchor["ts_code"], "manifest_sha256": anchor["expected_sha256"],
                            "variant": variant, "declared_originals": len(originals)})
        if sum(row["declared_originals"] for row in source_rows) > materials.MAX_MATERIALS:
            _fail("TOTAL_MATERIAL_LIMIT")
        for source_name, original in originals:
            row = None
            try:
                row = _material(request, anchor, document, source_name, original)
                key = (row["material_id"], row["version"])
                if key in seen:
                    _fail("DUPLICATE_MATERIAL_IDENTITY")
                if row["files"][0]["sha256"] in seen_files:
                    _fail("DUPLICATE_ORIGINAL_BYTES")
                materials.inspect_material_source(source, _manifest(request, [row]))
                seen.add(key)
                seen_files.add(row["files"][0]["sha256"])
                rows.append(row)
            except (ValueError, TypeError, KeyError, OSError) as error:
                if row is not None and _reason(error) == QUARANTINE_REASON:
                    quarantine_rows.append(row)
                rejected.append({"ts_code": anchor["ts_code"], "source_name": source_name if type(source_name) is str else None,
                                 "source_manifest_hash": anchor["expected_sha256"], "reason": _reason(error)})
    classification = request["classification"]
    if classification:
        raw = _read_anchor(source, classification["evidence_path"], classification["expected_sha256"])
        anchors.append({"path": classification["evidence_path"], "sha256": classification["expected_sha256"], "raw": raw})
    if _execution_identity(request) != identity:
        _fail("CODE_CHANGED_DURING_PREPARATION")
    # Preflight the entire accepted set before any irreversible registration.
    if rows:
        materials._manifest(_manifest(request, rows))
    root.mkdir(mode=0o700)
    records = root / "records"; records.mkdir(mode=0o700)
    backup.fsync_directory(root); backup.fsync_directory(root.parent)
    files = {}

    def record(name, value):
        raw = ev.canonical(value).encode()
        backup.write_new(records / name, raw)
        files[name] = ev.sha(raw)

    for number, anchor in enumerate(anchors):
        name = "source-anchor-" + str(number) + Path(anchor["path"]).suffix
        backup.write_new(records / name, anchor["raw"])
        files[name] = anchor["sha256"]
    record("request.json", request)
    started = {"schema": "ar.material-intake-operation-start.v1", **LABELS, "run_id": request["run_id"],
               "execution_identity": identity, "started_at": _utc_now(), "source_rows": source_rows,
               "accepted_preflight": len(rows), "rejected": rejected}
    record("started.json", started)
    result = None
    quarantined = None
    failure = None
    try:
        if rows:
            manifest = _manifest(request, rows)
            record("normalized-manifest.json", manifest)
            result = materials.ingest_material(source, root / "library", manifest)
            record("library-verification.json", result)
            for ticker in sorted(entry["ts_code"] for entry in request["manifests"]):
                record("query-" + ticker + ".json", materials.query_library(root / "library", trade_date=request["research_date"], ts_code=ticker))
            industry = classification["industry_key"] if classification else "UNSPECIFIED"
            record("query-cohort.json", materials.query_library(root / "library", industry_key=industry,
                                                               trade_date=request["research_date"]))
        packages, package_roots = [], {}
        if result:
            packages.append({"package_id": request["library_id"], "kind": "RESEARCH_LIBRARY", "local_root": str(root / "library"),
                             "expected_content_hash": result["library_hash"]})
            package_roots[request["library_id"]] = str(root / "library")
        if quarantine_rows:
            quarantined = create_quarantine(source, root / "quarantine", quarantine_rows, created_at=request["created_at"])
            record("quarantine-verification.json", quarantined)
            package_id = request["library_id"] + "-quarantine"
            packages.append({"package_id": package_id, "kind": "QUARANTINED_ORIGINALS", "local_root": str(root / "quarantine"),
                             "expected_content_hash": quarantined["quarantine_hash"]})
            package_roots[package_id] = str(root / "quarantine")
        if packages:
            preservation = build_preservation_manifest(
                packages, created_at=request["created_at"])
            record("preservation.json", preservation)
            checked = verify_preservation_copy(preservation, package_roots,
                                                expected_preservation_hash=preservation["preservation_hash"])
            record("preservation-local-reopen.json", checked)
            pin = {"schema": "ar.material-retention-pin.v1", **LABELS,
                   "run_id": request["run_id"], "library_hash": result["library_hash"] if result else None,
                   "quarantine_hash": quarantined["quarantine_hash"] if quarantined else None,
                   "registration_hash": result["registration_hash"] if result else None,
                   "preservation_hash": preservation["preservation_hash"],
                   "policy": "KEEP_UNTIL_EXPLICIT_HUMAN_RELEASE", "deletion_authority": False,
                   "off_machine_retention": "NOT_ATTESTED",
                   "source_anchors": [{"path": value["path"], "sha256": value["sha256"]} for value in anchors]}
            pin["pin_hash"] = ev.sealed(pin)
            record("retention-pin.json", pin)
            if _execution_identity(request) != identity:
                _fail("CODE_CHANGED_DURING_OPERATION")
    except (ValueError, TypeError, KeyError, OSError) as error:
        failure = _reason(error)
    status = "BLOCKED" if failure or not rows else "PARTIAL" if rejected else "LOCAL_MATERIALS_REGISTERED_PENDING_ACCEPTANCE"
    receipt = {"schema": "ar.cninfo-intake-operation.v1", **LABELS, "run_id": request["run_id"],
               "status": status, "operation_executed": True, "completed_at": _utc_now(),
               "execution_identity": identity, "research_date": request["research_date"], "source_cutoff": request["cutoff_at"],
               "date_scope": "RESEARCH_INDEX_DATE_NOT_MARKET_DATA_OR_SESSION_ATTESTATION",
               "source_rows": source_rows, "declared_originals": sum(value["declared_originals"] for value in source_rows),
               "admitted_originals": len(rows), "registered_originals": len(result["materials"]) if result else 0,
               "quarantined_originals": len(quarantined["entries"]) if quarantined else 0,
               "quarantine_hash": quarantined["quarantine_hash"] if quarantined else None,
               "library_hash": result["library_hash"] if result else None, "rejected": rejected, "failure": failure,
               "classification_status": "UNVERIFIED_RESEARCH_COHORT_NOT_PROVIDER_INDUSTRY" if classification else "UNSPECIFIED",
               "publication_time_scope": "SOURCE_DATE_ONLY_UPPER_BOUND_NOT_OBSERVED_TIME",
               "original_availability_scope": "CONSERVATIVE_FIRST_CAPTURE_FROM_EXISTING_MANIFEST",
               "originals_only": True, "research_review": "PENDING", "prospective_sample_eligible": False,
               "external_upload_performed": False, "off_machine_retention": "NOT_ATTESTED", "record_files": dict(files)}
    receipt["receipt_hash"] = ev.sealed(receipt)
    record("receipt.json", receipt)
    backup.fsync_directory(records); backup.fsync_directory(root)
    return receipt
