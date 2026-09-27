"""Fixed-fixture Jev shadow facade for the loopback workbench."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

import jev_u4_shadow as engine


ROOT = Path(__file__).resolve().parents[2]
SHADOW_SCENARIOS = {
    "synthetic-mixed": ROOT / "scripts/llm/fixtures/jev_u4_shadow/synthetic-mixed",
}
MAX_SHADOW_RUNS = 100
_APPROVED_REQUEST_SHA256 = "0c5ca34d51fb39fb59c8cb752bc4b394c7cbd44e18dc496caed672e96698a05b"
_COMMAND_ID = re.compile(r"[A-Za-z0-9_-]{8,80}\Z")


class ShadowWorkbenchError(ValueError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def validate_run_request(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) != {"command_id", "scenario"}:
        raise ShadowWorkbenchError("SHADOW_REQUEST_INVALID")
    command_id, scenario = payload["command_id"], payload["scenario"]
    if not isinstance(command_id, str) or not _COMMAND_ID.fullmatch(command_id):
        raise ShadowWorkbenchError("SHADOW_COMMAND_ID_INVALID")
    if not isinstance(scenario, str) or scenario not in SHADOW_SCENARIOS:
        raise ShadowWorkbenchError("SHADOW_SCENARIO_INVALID")
    return {"command_id": command_id, "scenario": scenario}


def _index(store: Any) -> None:
    with store.connect() as database:
        database.execute(
            "CREATE TABLE IF NOT EXISTS jev_shadow_runs "
            "(command_id TEXT PRIMARY KEY, scenario TEXT NOT NULL)"
        )


def _indexed_ids(store: Any) -> list[str]:
    _index(store)
    with store.connect() as database:
        return [row[0] for row in database.execute(
            "SELECT command_id FROM jev_shadow_runs ORDER BY rowid DESC"
        )]


def _integrity_only(command_id: str) -> dict[str, str]:
    return {
        "command_id": command_id,
        "status": "INTEGRITY_ERROR",
        "sample_purpose": "WORKFLOW_DEBUG",
        "authority": "SHADOW_ONLY",
    }


def _summary(receipt: dict[str, Any]) -> dict[str, Any]:
    mode = receipt["identity"]["run_mode"]
    return {
        "command_id": receipt["identity"]["command_id"],
        "status": "SIMULATED" if mode == "OFFLINE_FIXTURE" else "POLICY_PREVIEW",
        "sample_purpose": "WORKFLOW_DEBUG",
        "authority": "SHADOW_ONLY",
        "run_mode": mode,
        "observed_at": receipt["identity"]["observed_at"],
        "as_of": receipt["source_binding"]["run_identity"]["as_of"],
        "packet_hash": receipt["source_binding"]["packet_hash"],
        "receipt_hash": receipt["receipt_hash"],
        "provider_contacted": receipt["provider"]["provider_contacted"],
        "counts": receipt["batch_summary"],
    }


def _fixed_request(artifact_root: Path) -> dict[str, Any]:
    path = artifact_root / "request.json"
    descriptor = -1
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("request is not a regular file")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("request changed during open")
        raw = os.read(descriptor, 16385)
        if len(raw) > 16384 or hashlib.sha256(raw).hexdigest() != _APPROVED_REQUEST_SHA256:
            raise ValueError("request differs from committed synthetic fixture")
        request = json.loads(raw)
        if request["mode"] != "OFFLINE_FIXTURE" or request["fixture_id"] != "synthetic-mixed":
            raise ValueError("request is not the approved synthetic mode")
        return request
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ShadowWorkbenchError("FIXTURE_REQUEST_INVALID", 409) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def run_synthetic(store: Any, payload: object) -> dict[str, Any]:
    request = validate_run_request(payload)
    _index(store)
    with store.connect() as database:
        database.execute("BEGIN IMMEDIATE")
        row = database.execute(
            "SELECT scenario FROM jev_shadow_runs WHERE command_id = ?",
            (request["command_id"],),
        ).fetchone()
        if row is not None and row[0] != request["scenario"]:
            raise ShadowWorkbenchError("COMMAND_ID_CONFLICT", 409)
        if row is None and database.execute(
            "SELECT COUNT(*) FROM jev_shadow_runs"
        ).fetchone()[0] >= MAX_SHADOW_RUNS:
            raise ShadowWorkbenchError("SHADOW_RUN_LIMIT", 429)
        artifact_root = SHADOW_SCENARIOS[request["scenario"]]
        frozen = _fixed_request(artifact_root)
        frozen["command_id"] = request["command_id"]
        state_root = store.path.parent
        try:
            if row is None:
                receipt = engine.run_shadow(
                    frozen, artifact_root=artifact_root, state_root=state_root
                )
            shadow = engine.ShadowStore(state_root)
            try:
                if row is None:
                    result = shadow.write(frozen, receipt)
                else:
                    result = {"disposition": "IDEMPOTENT"}
                verified = shadow.read(request["command_id"])
            finally:
                shadow.close()
        except engine.ShadowRunError as exc:
            raise ShadowWorkbenchError(exc.code, 409) from exc
        if row is None:
            database.execute(
                "INSERT INTO jev_shadow_runs (command_id, scenario) VALUES (?, ?)",
                (request["command_id"], request["scenario"]),
            )
    return {
        "disposition": result["disposition"],
        "receipt": verified,
        "display_mode": "SIMULATED",
        "authority": "SHADOW_ONLY",
    }


def register_verified_preview(store: Any, command_id: str) -> str:
    """Index a CLI-written preview only after ShadowStore verifies its receipt."""
    if not isinstance(command_id, str) or not _COMMAND_ID.fullmatch(command_id):
        raise ShadowWorkbenchError("SHADOW_COMMAND_ID_INVALID")
    _index(store)
    with store.connect() as database:
        database.execute("BEGIN IMMEDIATE")
        row = database.execute(
            "SELECT scenario FROM jev_shadow_runs WHERE command_id = ?", (command_id,)
        ).fetchone()
        if row is not None and row[0] != "POLICY_PREVIEW":
            raise ShadowWorkbenchError("COMMAND_ID_CONFLICT", 409)
        if row is None and database.execute(
            "SELECT COUNT(*) FROM jev_shadow_runs"
        ).fetchone()[0] >= MAX_SHADOW_RUNS:
            raise ShadowWorkbenchError("SHADOW_RUN_LIMIT", 429)
        try:
            shadow = engine.ShadowStore(store.path.parent)
            try:
                receipt = shadow.read(command_id)
            finally:
                shadow.close()
        except engine.ShadowRunError as exc:
            raise ShadowWorkbenchError("INTEGRITY_ERROR", 409) from exc
        if receipt["identity"]["run_mode"] != "POLICY_PREVIEW":
            raise ShadowWorkbenchError("PREVIEW_MODE_REQUIRED", 409)
        if row is None:
            database.execute(
                "INSERT INTO jev_shadow_runs (command_id, scenario) VALUES (?, ?)",
                (command_id, "POLICY_PREVIEW"),
            )
    return "IDEMPOTENT" if row is not None else "CREATED"


def get_run(store: Any, command_id: str) -> dict[str, Any]:
    if not isinstance(command_id, str) or not _COMMAND_ID.fullmatch(command_id):
        raise ShadowWorkbenchError("SHADOW_COMMAND_ID_INVALID")
    if command_id not in _indexed_ids(store):
        raise ShadowWorkbenchError("SHADOW_RUN_NOT_FOUND", 404)
    try:
        shadow = engine.ShadowStore(store.path.parent)
        try:
            return shadow.read(command_id)
        finally:
            shadow.close()
    except engine.ShadowRunError as exc:
        raise ShadowWorkbenchError("INTEGRITY_ERROR", 409) from exc


def list_runs(store: Any) -> list[dict[str, Any]]:
    rows = []
    for command_id in _indexed_ids(store):
        try:
            rows.append(_summary(get_run(store, command_id)))
        except (ShadowWorkbenchError, KeyError, TypeError):
            rows.append(_integrity_only(command_id))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["register-preview"])
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--command-id", required=True)
    args = parser.parse_args(argv)
    from nonprod_workbench import Store

    try:
        result = register_verified_preview(Store(args.state_root), args.command_id)
    except ShadowWorkbenchError as exc:
        print(f"REFUSED: {exc.code}", file=sys.stderr)
        return 2
    print(json.dumps({"disposition": result, "command_id": args.command_id}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
