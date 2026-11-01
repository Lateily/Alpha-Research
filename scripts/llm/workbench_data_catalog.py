"""Read-only projections over already verified frozen inputs and sealed jobs."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import uuid
import sys

import workbench_evidence as ev
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.data_governance.catalog import catalog_hash, load_catalog, valid_date
from experiments.data_governance.call_receipts import read_call_receipts
from experiments.data_governance.health import evaluate_health, plan_backfills
from datetime import datetime, timezone

MISSING_TYPES = ["ISSUER_ORIGINAL", "THESIS", "NORMALIZED_VALUATION", "CASE", "PAPER_PLAN"]
SCOPE = "REGISTERED_SNAPSHOTS_AND_SEALED_BRIEFS_ONLY"
HASH = re.compile(r"[0-9a-f]{64}\Z")


def _envelope(value):
    if (value.get("schema") != "ar.shared-input.v1"
            or value.get("source_run_id") != value["snapshot"].get("published_run_id")
            or value.get("source_trade_date") != value["snapshot"].get("target_trade_date")):
        raise ValueError("CARD_ENVELOPE_IDENTITY_CONFLICT")
    return value["snapshot"]


def build_input_card(envelope, *, catalog, health, execution_identity):
    snapshot = _envelope(envelope)
    displayed = ev.view(snapshot)
    digest = catalog_hash(catalog)
    if health is not None and (health.get("catalog_hash") != digest
                               or health.get("target_trade_date") != envelope["source_trade_date"]):
        raise ValueError("CARD_HEALTH_CONTEXT_CONFLICT")
    modules = []
    for module in displayed["module_sources"]:
        payload = snapshot["records"].get(module["path"], {}).get("payload") or {}
        modules.append({**module, "published_at": payload.get("published_at"),
                        "available_at": payload.get("available_at"), "units": payload.get("unit_map"),
                        "missing_fields": [k for k in ("published_at", "available_at", "unit_map") if payload.get(k) is None]})
    sources = [{"path": path, "binding": row.get("binding"), "status": row.get("status"),
                "source_sha256": row.get("source_sha256"),
                "provenance": snapshot.get("publication_provenance", {}).get(path)}
               for path, row in sorted(snapshot["records"].items())]
    return {"schema": "ar.input-card.v1", "view_scope": "DERIVED_READ_ONLY_VIEW",
            **{k: envelope[k] for k in ("snapshot_id", "input_hash", "source_run_id", "source_trade_date", "validation_scope")},
            "latest_attempt_identity": displayed["run_identity"]["latest_attempt"],
            "last_published_identity": displayed["run_identity"]["last_published"],
            "consumer_code_sha": execution_identity["code_sha"], "catalog_hash": digest,
            "governance_status": "NOT_ATTACHED" if health is None else "ATTACHED_VERIFIED",
            "instrumentation_status": "NOT_INSTRUMENTED" if health is None else "SEE_SOURCE_HEALTH",
            "health_ref": None if health is None else {"sha256": ev.sealed(health), "scope": "CANONICAL_HEALTH_JSON"},
            "health": health, "backfill_plans": [] if health is None else plan_backfills(health, now=datetime.now(timezone.utc)),
            "modules": modules, "sources": sources, "missing_material_types": MISSING_TYPES[:],
            "human_review": "PENDING", "research_quality": "NOT_EVALUATED",
            "sample_purpose": "WORKFLOW_DEBUG", "production_authority": False, "trading_authority": False}


def _material(kind, envelope, source_ref, artifact_hash, *, ticker=None, industry=None,
              taxonomy="UNSPECIFIED", version="UNSPECIFIED", job_id=None, quality="NOT_EVALUATED", actor=None):
    identity = {"kind": kind, "snapshot_id": envelope["snapshot_id"], "job_id": job_id, "source_ref": source_ref}
    return {**identity, "material_id": ev.sealed(identity), "artifact_hash": artifact_hash,
            "input_hash": envelope["input_hash"], "trade_date": envelope["source_trade_date"],
            "source_run_id": envelope["source_run_id"], "ts_code": ticker, "industry_key": industry,
            "industry_taxonomy": taxonomy, "industry_version": version, "quality": quality,
            "access_scope": "TEAM_SHARED_READ_ONLY", "human_review": "PENDING", "actor": actor}


def build_material_index(envelopes, verified_jobs):
    if len(envelopes) > 100 or len(verified_jobs) > 1000:
        raise ValueError("MATERIAL_INDEX_CAPACITY")
    rows, inputs, issues = [], {}, []
    for envelope in envelopes:
        snapshot = _envelope(envelope)
        ev.verify(snapshot)
        sid = envelope["snapshot_id"]
        if sid in inputs:
            raise ValueError("DUPLICATE_MATERIAL_INPUT")
        inputs[sid] = envelope
        rows.append(_material("FROZEN_PUBLICATION", envelope, "snapshot:" + sid, envelope["input_hash"]))
        path = next((p for p in snapshot["records"] if p.endswith("/candidate_review.json")), None)
        record = snapshot["records"].get(path, {})
        candidates = (record.get("payload") or {}).get("rows")
        if not isinstance(candidates, list):
            issues.append({"snapshot_id": sid, "trade_date": envelope["source_trade_date"],
                           "source_run_id": envelope["source_run_id"], "error": "UNSUPPORTED_CANDIDATE_ROWS"})
            continue
        for position, item in enumerate(candidates):
            if not isinstance(item, dict):
                raise ValueError("INVALID_MATERIAL_CANDIDATE")
            if (item.get("run_id") is not None and item["run_id"] != envelope["source_run_id"]
                    or any(item.get(field) is not None and item[field] != envelope["source_trade_date"]
                           for field in ("as_of", "trade_date", "target_trade_date"))):
                raise ValueError("MATERIAL_CANDIDATE_IDENTITY_CONFLICT")
            ticker = item.get("ts_code") if item.get("ts_code") is not None else item.get("ticker")
            if (ticker is not None and (not isinstance(ticker, str) or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", ticker))
                    or item.get("ticker") is not None and item.get("ts_code") is not None and item["ticker"] != item["ts_code"]):
                raise ValueError("MATERIAL_TICKER_CONFLICT")
            industry_value = item.get("industry_key")
            industry = None if industry_value in (None, "", "UNKNOWN", "UNSPECIFIED") else _filter(industry_value)
            taxonomy = _filter(item.get("industry_taxonomy") or None) or "UNSPECIFIED"
            version = _filter(item.get("industry_version") or None) or "UNSPECIFIED"
            rows.append(_material("CANDIDATE_REVIEW", envelope, f"snapshot:{sid}:candidate:{position}",
                                  record.get("source_sha256"), ticker=ticker, industry=industry,
                                  taxonomy=taxonomy, version=version, quality="CANDIDATE_ONLY_NOT_RESEARCH_APPROVAL"))
            if len(rows) > 50000:
                raise ValueError("MATERIAL_INDEX_CAPACITY")
    for job in verified_jobs:
        if job.get("status") != "SUCCEEDED" or job.get("kind") != "snapshot-brief":
            continue
        envelope = inputs.get(job.get("snapshot_id"))
        if envelope is None:
            continue
        if (job.get("input_hash") != envelope["input_hash"] or not isinstance(job.get("report"), str)
                or ev.sha(job["report"].encode()) != job.get("output_hash")):
            raise ValueError("MATERIAL_REPORT_BINDING_INVALID")
        rows.append(_material("SEALED_BRIEF", envelope, "job:" + job["job_id"], job["output_hash"],
                              job_id=job["job_id"], actor=job.get("actor")))
    if len(rows) > 50000:
        raise ValueError("MATERIAL_INDEX_CAPACITY")
    return {"schema": "ar.material-index.v1", "scope": SCOPE, "rows": rows, "issues": issues,
            "missing_material_types": MISSING_TYPES[:], "missing_material_basis": "NOT_INDEXED_IN_THIS_SCOPE"}


def _filter(value):
    if value is None:
        return None
    if (not isinstance(value, str) or not 0 < len(value) <= 128
            or any(ord(c) < 32 for c in value) or "/" in value or "\\" in value or ".." in value):
        raise ValueError("MATERIAL_FILTER_INVALID")
    return value


def query_materials(index, *, industry_key=None, trade_date=None, ts_code=None, page=0):
    if type(page) is not int or not 0 <= page <= 999:
        raise ValueError("MATERIAL_PAGE_INVALID")
    industry_key = _filter(industry_key)
    if trade_date is not None:
        valid_date(trade_date)
    if ts_code is not None and (not isinstance(ts_code, str) or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", ts_code)):
        raise ValueError("MATERIAL_TICKER_INVALID")
    rows = [r for r in index["rows"] if (industry_key is None or r["industry_key"] == industry_key)
            and (trade_date is None or r["trade_date"] == trade_date) and (ts_code is None or r["ts_code"] == ts_code)]
    rows.sort(key=lambda r: r["material_id"])
    rows.sort(key=lambda r: r["trade_date"], reverse=True)
    issues = [i for i in index.get("issues", []) if trade_date is None or i.get("trade_date") in (None, trade_date)]
    return {**{k: v for k, v in index.items() if k != "rows"}, "rows": rows[page * 50:(page + 1) * 50],
            "total": len(rows), "page": page, "page_size": 50, "human_review": "PENDING",
            "issues": issues, "status": "PARTIAL" if issues else "SCOPED_INDEX_AVAILABLE"}


def _owned(path, *, directory=False):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("GOVERNANCE_EVIDENCE_SYMLINK")
    mode = path.lstat()
    if (mode.st_uid != os.getuid() or mode.st_mode & 0o022
            or not (stat.S_ISDIR(mode.st_mode) if directory else stat.S_ISREG(mode.st_mode))):
        raise ValueError("GOVERNANCE_EVIDENCE_OWNERSHIP")


def _registry(value):
    if (not isinstance(value, dict) or set(value) != {"schema", "bindings"}
            or value["schema"] != "ar.governance-attachment-registry.v1"
            or not isinstance(value["bindings"], dict) or len(value["bindings"]) > 100):
        raise ValueError("GOVERNANCE_REGISTRY_INVALID")
    for sid, item in value["bindings"].items():
        if str(uuid.UUID(sid)) != sid or not isinstance(item, dict) or set(item) != {
                "input_hash", "health_sha256", "catalog_sha256", "receipt_catalog_hash"}:
            raise ValueError("GOVERNANCE_BINDING_INVALID")
        if any(not isinstance(v, str) or not HASH.fullmatch(v) for v in item.values()):
            raise ValueError("GOVERNANCE_HASH_INVALID")
    return value


def load_governance_registry(root):
    root = Path(root)
    if not root.exists() and not root.is_symlink():
        return None
    _owned(root, directory=True)
    path = root / "registry.json"
    if not path.exists() and not path.is_symlink():
        return None
    _owned(path)
    return _registry(ev.parse(ev.read_local(root, "registry.json")))


def verify_governance_attachment(envelope, *, registry, root):
    if registry is None:
        return None
    _registry(registry)
    expected = registry["bindings"].get(envelope["snapshot_id"])
    if expected is None:
        return None
    if expected["input_hash"] != envelope["input_hash"] or root is None:
        raise ValueError("GOVERNANCE_INPUT_BINDING_INVALID")
    root = Path(root)
    _owned(root, directory=True)
    bundle = root / envelope["snapshot_id"]
    _owned(bundle, directory=True)
    for number, path in enumerate(bundle.rglob("*")):
        if number >= 3100:
            raise ValueError("GOVERNANCE_EVIDENCE_CAPACITY")
        _owned(path, directory=path.is_dir())
    catalog_raw, health_raw = (ev.read_local(bundle, name) for name in ("catalog.json", "health.json"))
    # External registry, never a hash claimed by the attachment itself.
    if ev.sha(catalog_raw) != expected["catalog_sha256"] or ev.sha(health_raw) != expected["health_sha256"]:
        raise ValueError("GOVERNANCE_EXTERNAL_BINDING_INVALID")
    catalog = load_catalog(bundle / "catalog.json")
    receipts = read_call_receipts(bundle / "receipts")
    if ev.sealed(receipts) != expected["receipt_catalog_hash"]:
        raise ValueError("GOVERNANCE_RECEIPT_CATALOG_INVALID")
    if any(r["context"]["collector_run_id"] != envelope["source_run_id"] or
           r["context"]["target_trade_date"] != envelope["source_trade_date"] for r in receipts):
        raise ValueError("GOVERNANCE_SOURCE_IDENTITY_CONFLICT")
    health = ev.parse(health_raw)
    if health != evaluate_health(catalog, receipts, target_trade_date=envelope["source_trade_date"]):
        raise ValueError("GOVERNANCE_HEALTH_RECOMPUTE_MISMATCH")
    return health
