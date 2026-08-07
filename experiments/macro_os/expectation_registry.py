#!/usr/bin/env python3
"""System-clock registration for Macro OS house expectations.

The caller supplies forecast content, never ``registered_at``.  This module
binds the content to the process clock and appends it to the existing R-015
hash-chain ledger implementation.  It does not approve an expectation and it
does not call GitHub.  Approval remains a separate human gate.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.execution_tracker import event_ledger
from experiments.macro_os import contracts, m0b3
from experiments.macro_os.storage import MacroHistoryStore, MacroStoreError


DEFAULT_LEDGER = Path("data_history/macro_expectations.jsonl")
CALLER_FIELDS = {
    "expectation_id",
    "event_id",
    "event_type",
    "event_scheduled_at",
    "snapshot_type",
    "forecast",
    "surprise_bucket",
    "transmission_hypotheses",
    "formula_version",
    "submitted_by",
}


class ExpectationRegistryError(RuntimeError):
    pass


def _utc_iso() -> str:
    value = datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ExpectationRegistryError("registration clock must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _load_specs() -> tuple[dict[str, Any], dict[str, Any]]:
    sources = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(sources)
    tiers = contracts.load_json(contracts.EVENT_TIERS)
    contracts.validate_event_tiers(tiers, sources)
    return sources, tiers


def _calendar_slot(calendar: Mapping[str, Any], event_id: str) -> Mapping[str, Any]:
    if calendar.get("schema") != "ar.macro.release_calendar":
        raise ExpectationRegistryError("expectation requires an M0-B2 release calendar")
    rows = calendar.get("data")
    if not isinstance(rows, list):
        raise ExpectationRegistryError("release calendar data must be a list")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("event_id") == event_id]
    if len(matches) != 1:
        raise ExpectationRegistryError("expectation event_id must match exactly one calendar slot")
    return matches[0]


def build_registered_expectation(
    draft: Mapping[str, Any],
    *,
    calendar: Mapping[str, Any],
    store: MacroHistoryStore,
) -> dict[str, Any]:
    """Build a DRAFT expectation with a trusted registration timestamp."""

    m0b3.validate_calendar(calendar, store)
    if not isinstance(draft, Mapping):
        raise ExpectationRegistryError("expectation draft must be an object")
    unknown = sorted(set(draft) - CALLER_FIELDS)
    missing = sorted(CALLER_FIELDS - set(draft))
    if unknown:
        raise ExpectationRegistryError(
            f"caller cannot supply registration/approval fields: {unknown}"
        )
    if missing:
        raise ExpectationRegistryError(f"expectation draft missing fields: {missing}")

    slot = _calendar_slot(calendar, str(draft["event_id"]))
    if draft["event_type"] != slot.get("event_type"):
        raise ExpectationRegistryError("expectation event_type differs from calendar")
    if draft["event_scheduled_at"] != slot.get("scheduled_at"):
        raise ExpectationRegistryError("expectation scheduled_at differs from calendar")

    payload = copy.deepcopy(dict(draft))
    payload.update(
        {
            "schema": contracts.EXPECTATION_SCHEMA,
            "schema_version": contracts.SCHEMA_VERSION,
            "registered_at": _utc_iso(),
            "status": "DRAFT",
            "approved_by": None,
            "approval_ref": None,
            "approval_commit_sha": None,
            "expectation_hash": "",
        }
    )
    payload["expectation_hash"] = contracts.house_expectation_hash(payload)
    sources, tiers = _load_specs()
    contracts.validate_house_expectation(payload, tiers, sources)
    return payload


def register_expectation(
    draft: Mapping[str, Any],
    *,
    calendar: Mapping[str, Any],
    store: MacroHistoryStore,
    ledger_path: str | Path = DEFAULT_LEDGER,
) -> dict[str, Any]:
    payload = build_registered_expectation(draft, calendar=calendar, store=store)
    registered_at = payload["registered_at"]
    slot = _calendar_slot(calendar, payload["event_id"])
    calendar_hash = hashlib.sha256(m0b3._canonical(calendar)).hexdigest()
    try:
        record = event_ledger.append(
            "register",
            payload["expectation_id"],
            {
                "record_type": "macro_house_expectation",
                "calendar_hash": calendar_hash,
                "calendar": copy.deepcopy(dict(calendar)),
                "source_snapshot_hash": slot["source_snapshot_hash"],
                "expectation": payload,
            },
            path=str(ledger_path),
            now=registered_at,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ExpectationRegistryError(f"expectation ledger refused registration: {exc}") from exc
    return {"expectation": payload, "ledger_record": record}


def verify_expectation_ledger(
    path: str | Path = DEFAULT_LEDGER,
    *,
    store: MacroHistoryStore,
) -> dict[str, Any]:
    chain = event_ledger.verify(str(path))
    anchor = event_ledger.verify_anchor(str(path))
    errors = list(chain.get("errors", [])) + list(anchor.get("errors", []))
    if chain.get("ok") and anchor.get("ok"):
        sources, tiers = _load_specs()
        for index, line in enumerate(event_ledger._read_lines(str(path))):
            try:
                record = json.loads(line)
                envelope = record["payload"]
                expectation = envelope["expectation"]
                expected_envelope = {
                    "record_type",
                    "calendar_hash",
                    "calendar",
                    "source_snapshot_hash",
                    "expectation",
                }
                if set(envelope) != expected_envelope or envelope["record_type"] != "macro_house_expectation":
                    raise ExpectationRegistryError("unexpected expectation ledger envelope")
                calendar = envelope["calendar"]
                if not isinstance(calendar, Mapping):
                    raise ExpectationRegistryError("expectation calendar snapshot is invalid")
                m0b3.validate_calendar(calendar, store)
                calendar_hash = hashlib.sha256(m0b3._canonical(calendar)).hexdigest()
                slot = _calendar_slot(calendar, expectation["event_id"])
                if (
                    envelope["calendar_hash"] != calendar_hash
                    or envelope["source_snapshot_hash"] != slot["source_snapshot_hash"]
                ):
                    raise ExpectationRegistryError("expectation calendar binding is invalid")
                if record["id"] != expectation["expectation_id"]:
                    raise ExpectationRegistryError("ledger id differs from expectation_id")
                if record["ts"] != expectation["registered_at"]:
                    raise ExpectationRegistryError("registered_at differs from ledger clock")
                contracts.validate_house_expectation(expectation, tiers, sources)
            except (KeyError, TypeError, json.JSONDecodeError, contracts.ContractError, ExpectationRegistryError) as exc:
                errors.append(f"line{index}: {exc}")
                break
    return {
        "ok": not errors,
        "records": chain.get("n", 0),
        "head": chain.get("head"),
        "errors": errors,
        "boundary": (
            "hash-chain plus local anchor detects in-file rewrite and truncation; "
            "an operator with write access to both files is outside this guarantee"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft")
    parser.add_argument("--calendar")
    parser.add_argument("--db", default=str(m0b3.DEFAULT_DB))
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        store = MacroHistoryStore(args.db)
        store.initialize()
        if args.verify:
            result = verify_expectation_ledger(args.ledger, store=store)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["ok"] else 1
        if not args.draft or not args.calendar:
            raise ExpectationRegistryError("--draft and --calendar are required")
        draft = contracts.load_json(args.draft)
        calendar = contracts.load_json(args.calendar)
        result = register_expectation(
            draft, calendar=calendar, store=store, ledger_path=args.ledger
        )
        expectation = result["expectation"]
        print(
            f"macro expectation registered: {expectation['expectation_id']} "
            f"at {expectation['registered_at']} status=DRAFT"
        )
        return 0
    except (
        ExpectationRegistryError,
        MacroStoreError,
        m0b3.M0B3Error,
        contracts.ContractError,
        OSError,
        ValueError,
    ) as exc:
        print(f"macro expectation registration REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
