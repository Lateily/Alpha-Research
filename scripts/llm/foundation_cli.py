"""Offline foundation commands; not a workbench dispatcher or approval surface."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import workbench_evidence as evidence


class Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("FOUNDATION_ARGUMENTS_INVALID")


def arguments(argv=None):
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory")
    inventory.add_argument("--config", required=True)
    workflows = commands.add_parser("workflows")
    workflows.add_argument("--catalog")
    workflows.add_argument("--kind")
    pin = commands.add_parser("pin")
    pin.add_argument("--request", required=True)
    pin.add_argument("--write-root")
    sources = commands.add_parser("sources")
    sources.add_argument("--repository", required=True)
    sources.add_argument("--inventory")
    ingest = commands.add_parser("material-ingest")
    ingest.add_argument("--request", required=True)
    ingest.add_argument("--write-root", required=True)
    batch = commands.add_parser("cninfo-intake")
    batch.add_argument("--request", required=True)
    batch.add_argument("--write-root", required=True)
    endpoint_health = commands.add_parser("endpoint-health")
    endpoint_health.add_argument("--receipts-root", required=True)
    endpoint_health.add_argument("--target-date", required=True)
    endpoint_health.add_argument("--catalog")
    materials = commands.add_parser("materials")
    materials.add_argument("--library-root", required=True)
    materials.add_argument("--industry")
    materials.add_argument("--date")
    materials.add_argument("--ticker")
    for name in ("preservation", "preservation-verify", "reconcile"):
        commands.add_parser(name).add_argument("--request", required=True)
    return parser.parse_args(argv)


def request_json(filename, *, required, optional=()):
    path = Path(filename).absolute()
    if ".." in path.parts or "://" in str(filename):
        raise ValueError("FOUNDATION_PATH_INVALID")
    value = evidence.parse(evidence.read_local(path.parent, path.name))
    if (not isinstance(value, dict) or not set(required) <= set(value)
            or set(value) - set(required) - set(optional)):
        raise ValueError("FOUNDATION_REQUEST_INVALID")
    return value


def execute(args):
    if args.command == "inventory":
        from foundation_runtime import collect_runtime_inventory
        value = request_json(args.config, required=("repositories", "observed_at"),
                             optional=("services", "scheduler_timezone", "market_timezone"))
        return collect_runtime_inventory(value["repositories"], value.get("services", []),
                                         observed_at=value["observed_at"],
                                         scheduler_timezone=value.get("scheduler_timezone", "Europe/London"),
                                         market_timezone=value.get("market_timezone", "Asia/Shanghai"))
    if args.command == "workflows":
        from foundation_workflows import get_workflow, load_workflow_catalog
        catalog = load_workflow_catalog(Path(args.catalog) if args.catalog else None)
        return get_workflow(args.kind, catalog=catalog) if args.kind else catalog
    if args.command == "sources":
        from foundation_sources import build_source_coverage
        return build_source_coverage(args.repository, inventory_path=args.inventory)
    if args.command == "material-ingest":
        from foundation_materials import ingest_material
        value = request_json(args.request, required=("source_root", "manifest"))
        source, destination = Path(value["source_root"]).absolute(), Path(args.write_root).absolute()
        if source == destination or source in destination.parents or destination in source.parents:
            raise ValueError("FOUNDATION_MATERIAL_ROOT_OVERLAP")
        return ingest_material(value["source_root"], args.write_root, value["manifest"])
    if args.command == "cninfo-intake":
        from foundation_intake import REQUEST_KEYS, run_cninfo_intake
        value = request_json(args.request, required=REQUEST_KEYS)
        return run_cninfo_intake(value, args.write_root)
    if args.command == "endpoint-health":
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from experiments.data_governance.endpoints import load_catalog, project_endpoint_health, propose_backfills
        from experiments.data_governance.endpoint_calls import read_endpoint_receipts
        catalog = load_catalog(Path(args.catalog) if args.catalog else Path(__file__).resolve().parents[2] / "config/data-endpoint-contracts.v1.json")
        health = project_endpoint_health(catalog, read_endpoint_receipts(args.receipts_root), target_trade_date=args.target_date)
        return {"health": health, "backfill_proposals": propose_backfills(health)}
    if args.command == "materials":
        from foundation_materials import query_library
        return query_library(args.library_root, industry_key=args.industry, trade_date=args.date, ts_code=args.ticker)
    if args.command == "preservation":
        from foundation_preservation import build_preservation_manifest
        value = request_json(args.request, required=("packages", "created_at"))
        return build_preservation_manifest(value["packages"], created_at=value["created_at"])
    if args.command == "preservation-verify":
        from foundation_preservation import verify_preservation_copy
        value = request_json(args.request, required=("manifest", "package_roots", "expected_preservation_hash"))
        return verify_preservation_copy(value["manifest"], value["package_roots"],
                                        expected_preservation_hash=value["expected_preservation_hash"])
    if args.command == "reconcile":
        from foundation_release import reconcile_deployments
        value = request_json(args.request, required=("inventory", "release"))
        return reconcile_deployments(value["inventory"], value["release"])
    if args.command == "pin":
        from foundation_retention import build_retention_pin, write_retention_pin
        value = request_json(args.request,
                             required=("backup_root", "expected_backup_hash", "snapshot_ids", "job_ids", "created_at"),
                             optional=("case_refs",))
        if args.write_root:
            archive = Path(value["backup_root"]).absolute()
            destination = Path(args.write_root).absolute()
            if archive == destination or archive in destination.parents or destination in archive.parents:
                raise ValueError("FOUNDATION_PIN_ROOT_OVERLAP")
        pin = build_retention_pin(value["backup_root"], expected_backup_hash=value["expected_backup_hash"],
                                  snapshot_ids=value["snapshot_ids"], job_ids=value["job_ids"],
                                  case_refs=value.get("case_refs", []), created_at=value["created_at"])
        return {"pin": pin, "write_receipt": write_retention_pin(args.write_root, pin) if args.write_root else None}
    raise ValueError("FOUNDATION_COMMAND_INVALID")


def main(argv=None):
    try:
        args = arguments(argv)
        result = {"schema": "ar.foundation-command.v1", "command": args.command, "result": execute(args),
                  "sample_purpose": "WORKFLOW_DEBUG", "testing_status": "NOT_RUN", "human_review": "PENDING",
                  "production_authority": False, "trading_authority": False, "deployment_authority": False}
        raw = json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError):
        print('{"error":"FOUNDATION_REQUEST_REFUSED","production_authority":false}', file=sys.stderr)
        return 2
    print(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
