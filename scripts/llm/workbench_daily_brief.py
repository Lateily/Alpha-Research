"""Offline, fail-closed validator for the WB-01 synthetic daily brief bundle.

The module validates frozen input bytes and produces a deterministic acceptance
receipt.  It does not read production state, call a provider, or publish data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INPUT_SCHEMA = ROOT / "docs/contracts/workbench_daily_brief_input.v1.schema.json"
OUTPUT_SCHEMA = ROOT / "docs/contracts/workbench_daily_brief_output.v1.schema.json"
MAX_FILE_BYTES = 2 * 1024 * 1024
REQUIRED_ROLES = {"MARKET", "PORTFOLIO", "ORDERS", "MACRO", "FUNNEL"}
ROLE_PATHS = {role: f"sources/{role.lower()}.json" for role in REQUIRED_ROLES}
ROLE_SCHEMAS = {
    "MARKET": "ar.synthetic_market.v1",
    "PORTFOLIO": "ar.synthetic_portfolio.v1",
    "ORDERS": "ar.synthetic_orders.v1",
    "MACRO": "ar.synthetic_macro.v1",
    "FUNNEL": "ar.synthetic_funnel.v1",
}
SECRET_VALUE_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
)
SECRET_KEY_PATTERN = re.compile(
    r"(?i)^(?:api_?key|access_?token|secret|secret_?access_?key|password|authorization)$"
)


class BriefBlocked(ValueError):
    """A contract-safe validation failure with no raw input echo."""

    def __init__(self, code: str, subject: str):
        super().__init__(code)
        self.code = code
        self.subject = subject


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise BriefBlocked("DUPLICATE_JSON_KEY", "json")
        result[key] = value
    return result


def parse_json(raw: bytes, subject: str) -> Any:
    def reject_constant(_value: str) -> None:
        raise BriefBlocked("NONFINITE_NUMBER", subject)

    try:
        value = json.loads(
            raw,
            object_pairs_hook=_json_pairs,
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=reject_constant,
        )
    except BriefBlocked:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise BriefBlocked("MALFORMED_JSON", subject) from None
    _reject_secret_like(value, subject)
    return value


def _reject_secret_like(value: Any, subject: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SECRET_KEY_PATTERN.fullmatch(str(key)) and child not in (None, ""):
                raise BriefBlocked("SECRET_LIKE_INPUT", subject)
            _reject_secret_like(child, subject)
    elif isinstance(value, list):
        for child in value:
            _reject_secret_like(child, subject)
    elif isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
        raise BriefBlocked("SECRET_LIKE_INPUT", subject)


def _read_regular(root: Path, relative: str) -> bytes:
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise BriefBlocked("SOURCE_PATH_INVALID", relative or "source")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(root, flags | os.O_DIRECTORY)
        try:
            for part in parts[:-1]:
                new_fd = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
                os.close(fd)
                fd = new_fd
            file_fd = os.open(parts[-1], flags, dir_fd=fd)
            with os.fdopen(file_fd, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
                    raise BriefBlocked("SOURCE_SIZE_OR_TYPE_INVALID", relative)
                raw = stream.read(MAX_FILE_BYTES + 1)
                after = os.fstat(stream.fileno())
                if len(raw) > MAX_FILE_BYTES or (
                    before.st_size,
                    before.st_mtime_ns,
                ) != (after.st_size, after.st_mtime_ns):
                    raise BriefBlocked("SOURCE_CHANGED_DURING_READ", relative)
                return raw
        finally:
            os.close(fd)
    except FileNotFoundError:
        raise BriefBlocked("SOURCE_MISSING", relative) from None
    except OSError:
        raise BriefBlocked("SOURCE_UNREADABLE", relative) from None


def _load_schema(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise BriefBlocked("CONTRACT_SCHEMA_INVALID", path.name)
    return value


def _validate_schema(value: Any, schema: dict[str, Any], subject: str) -> None:
    try:
        _validate_schema_node(value, schema, schema)
    except (KeyError, TypeError, ValueError, re.error):
        raise BriefBlocked("SCHEMA_INVALID", subject)


def _validate_schema_node(value: Any, node: dict[str, Any], root: dict[str, Any]) -> None:
    """Validate the small closed-world JSON-Schema subset used by WB-01.

    Keeping this subset in-tree makes the acceptance command work on the team's
    stock Python runtime while the committed schemas remain standard Draft 2020-12.
    """

    if "$ref" in node:
        reference = node["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/"):
            raise ValueError("external references are not accepted")
        target: Any = root
        for token in reference[2:].split("/"):
            target = target[token.replace("~1", "/").replace("~0", "~")]
        _validate_schema_node(value, target, root)
        return
    if "oneOf" in node:
        matches = 0
        for option in node["oneOf"]:
            try:
                _validate_schema_node(value, option, root)
            except (KeyError, TypeError, ValueError, re.error):
                continue
            matches += 1
        if matches != 1:
            raise ValueError("oneOf mismatch")
        return
    expected = node.get("type")
    if expected is not None:
        allowed = expected if isinstance(expected, list) else [expected]
        if not any(_json_type_matches(value, name) for name in allowed):
            raise TypeError("type mismatch")
    if "const" in node and value != node["const"]:
        raise ValueError("const mismatch")
    if "enum" in node and value not in node["enum"]:
        raise ValueError("enum mismatch")
    if isinstance(value, dict):
        required = node.get("required", [])
        if any(key not in value for key in required):
            raise ValueError("required property missing")
        properties = node.get("properties", {})
        if node.get("additionalProperties") is False and any(key not in properties for key in value):
            raise ValueError("additional property")
        for key, child in value.items():
            if key in properties:
                _validate_schema_node(child, properties[key], root)
    if isinstance(value, list):
        if len(value) < node.get("minItems", 0) or len(value) > node.get("maxItems", math.inf):
            raise ValueError("array length")
        if "items" in node:
            for child in value:
                _validate_schema_node(child, node["items"], root)
    if isinstance(value, str):
        if len(value) < node.get("minLength", 0) or len(value) > node.get("maxLength", math.inf):
            raise ValueError("string length")
        if "pattern" in node and re.search(node["pattern"], value) is None:
            raise ValueError("pattern mismatch")
        if node.get("format") == "date-time":
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone required")


def _json_type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
    if expected == "integer":
        return (
            isinstance(value, (int, Decimal))
            and not isinstance(value, bool)
            and Decimal(str(value)) == Decimal(str(value)).to_integral_value()
        )
    raise ValueError("unsupported schema type")


def _decimal(value: Any, code: str, subject: str) -> Decimal:
    if isinstance(value, bool):
        raise BriefBlocked(code, subject)
    try:
        result = Decimal(str(value))
    except Exception:
        raise BriefBlocked(code, subject) from None
    if not result.is_finite():
        raise BriefBlocked(code, subject)
    return result


def _timestamp(value: str, code: str, subject: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise BriefBlocked(code, subject) from None
    if parsed.tzinfo is None:
        raise BriefBlocked(code, subject)
    return parsed.astimezone(timezone.utc)


def _trade_date(value: str, subject: str) -> None:
    try:
        datetime.strptime(value, "%Y%m%d")
    except (TypeError, ValueError):
        raise BriefBlocked("TRADE_DATE_INVALID", subject) from None


def _money(value: Decimal) -> str:
    return format(value, "f")


def _validate_source_identity(
    role: str,
    descriptor: dict[str, Any],
    payload: dict[str, Any],
    envelope: dict[str, Any],
) -> str:
    if payload.get("schema") != ROLE_SCHEMAS[role]:
        raise BriefBlocked("SOURCE_SCHEMA_INVALID", role)
    if payload.get("sample_purpose") != "WORKFLOW_DEBUG":
        raise BriefBlocked("SOURCE_PURPOSE_INVALID", role)
    # governance-mutation: WB01_SOURCE_RUN_BINDING
    if payload.get("run_id") != envelope["run_id"]:
        raise BriefBlocked("SOURCE_RUN_ID_MISMATCH", role)
    # governance-mutation: WB01_SOURCE_DATE_BINDING
    if payload.get("as_of") != envelope["target_trade_date"]:
        raise BriefBlocked("SOURCE_DATE_MISMATCH", role)
    if descriptor.get("source_date") != payload.get("as_of"):
        raise BriefBlocked("SOURCE_DESCRIPTOR_DATE_MISMATCH", role)
    if _timestamp(descriptor.get("data_cutoff"), "SOURCE_CUTOFF_INVALID", role) > _timestamp(
        envelope["data_cutoff"], "BRIEF_CUTOFF_INVALID", "brief_input.json"
    ):
        raise BriefBlocked("SOURCE_CUTOFF_AFTER_BRIEF", role)

    if role == "MARKET":
        rows = payload.get("benchmarks")
        if not isinstance(rows, list) or not rows:
            raise BriefBlocked("MARKET_ROWS_INVALID", role)
        if any(
            not isinstance(row, dict)
            or not str(row.get("id", "")).endswith(".TEST")
            or row.get("observation_status") != "AVAILABLE"
            for row in rows
        ):
            raise BriefBlocked("MARKET_ROWS_INVALID", role)
        return "AVAILABLE"
    if role == "PORTFOLIO":
        if payload.get("paper_only") is not True or payload.get("currency") != "CNY":
            raise BriefBlocked("PORTFOLIO_AUTHORITY_INVALID", role)
        return "AVAILABLE"
    if role == "ORDERS":
        if payload.get("paper_only") is not True or not isinstance(payload.get("orders"), list):
            raise BriefBlocked("ORDERS_AUTHORITY_INVALID", role)
        return "NO_ACTIVITY" if not payload["orders"] else "AVAILABLE"
    if role == "MACRO":
        quality = payload.get("data_quality")
        if quality not in {"AVAILABLE", "PARTIAL", "DATA_BLOCKED"}:
            raise BriefBlocked("MACRO_QUALITY_INVALID", role)
        rows = payload.get("source_rows")
        if (
            not isinstance(rows, list)
            or any(not isinstance(row, dict) for row in rows)
            or payload.get("expected_source_count") != len(rows)
            or payload.get("available_source_count")
            != sum(row.get("status") == "AVAILABLE" for row in rows)
        ):
            raise BriefBlocked("MACRO_ROWS_INVALID", role)
        if quality == "AVAILABLE" and payload["available_source_count"] != len(rows):
            raise BriefBlocked("MACRO_QUALITY_INVALID", role)
        return quality
    quality = payload.get("data_quality")
    if quality not in {"AVAILABLE", "PARTIAL", "DATA_BLOCKED"}:
        raise BriefBlocked("FUNNEL_QUALITY_INVALID", role)
    if payload.get("formal_trade_authority") is not False:
        raise BriefBlocked("FUNNEL_AUTHORITY_INVALID", role)
    candidates = payload.get("candidates")
    if (
        not isinstance(candidates, list)
        or payload.get("candidate_count") != len(candidates)
        or any(
            not isinstance(row, dict)
            or not str(row.get("instrument_id", "")).endswith(".TEST")
            for row in candidates
        )
        or payload.get("u4_selected") != []
    ):
        raise BriefBlocked("FUNNEL_ROWS_INVALID", role)
    return quality


def _position_map(snapshot: dict[str, Any], subject: str) -> dict[str, dict[str, Any]]:
    rows = snapshot.get("positions")
    if not isinstance(rows, list):
        raise BriefBlocked("PORTFOLIO_POSITION_SHAPE_INVALID", subject)
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise BriefBlocked("PORTFOLIO_POSITION_SHAPE_INVALID", subject)
        instrument = row.get("instrument_id")
        if not isinstance(instrument, str) or not instrument.endswith(".TEST") or instrument in result:
            raise BriefBlocked("PORTFOLIO_INSTRUMENT_INVALID", subject)
        shares = _decimal(row.get("shares"), "PORTFOLIO_NUMBER_INVALID", subject)
        close = _decimal(row.get("close"), "PORTFOLIO_NUMBER_INVALID", subject)
        market_value = _decimal(row.get("market_value"), "PORTFOLIO_NUMBER_INVALID", subject)
        if shares < 0 or close < 0 or market_value != shares * close:
            raise BriefBlocked("PORTFOLIO_MARKET_VALUE_MISMATCH", subject)
        result[instrument] = row
    return result


def _validate_portfolio(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Decimal]]:
    previous = payload.get("previous_snapshot")
    current = payload.get("current_snapshot")
    if not isinstance(previous, dict) or not isinstance(current, dict):
        raise BriefBlocked("PORTFOLIO_SNAPSHOT_INVALID", "PORTFOLIO")
    previous_positions = _position_map(previous, "previous_snapshot")
    current_positions = _position_map(current, "current_snapshot")
    previous_cash = _decimal(previous.get("cash"), "PORTFOLIO_NUMBER_INVALID", "PORTFOLIO")
    current_cash = _decimal(current.get("cash"), "PORTFOLIO_NUMBER_INVALID", "PORTFOLIO")
    previous_nav = _decimal(previous.get("nav"), "PORTFOLIO_NUMBER_INVALID", "PORTFOLIO")
    current_nav = _decimal(current.get("nav"), "PORTFOLIO_NUMBER_INVALID", "PORTFOLIO")
    nav_change = _decimal(current.get("nav_change"), "PORTFOLIO_NUMBER_INVALID", "PORTFOLIO")
    nav_change_pct = _decimal(current.get("nav_change_pct"), "PORTFOLIO_NUMBER_INVALID", "PORTFOLIO")
    previous_position_value = sum(
        (_decimal(row["market_value"], "PORTFOLIO_NUMBER_INVALID", "PORTFOLIO") for row in previous_positions.values()),
        Decimal("0"),
    )
    current_position_value = sum(
        (_decimal(row["market_value"], "PORTFOLIO_NUMBER_INVALID", "PORTFOLIO") for row in current_positions.values()),
        Decimal("0"),
    )
    if previous_nav != previous_cash + previous_position_value:
        raise BriefBlocked("PORTFOLIO_ARITHMETIC_MISMATCH", "previous_nav")
    # governance-mutation: WB01_PORTFOLIO_ARITHMETIC
    if current_nav != current_cash + current_position_value:
        raise BriefBlocked("PORTFOLIO_ARITHMETIC_MISMATCH", "current_nav")
    if nav_change != current_nav - previous_nav:
        raise BriefBlocked("PORTFOLIO_ARITHMETIC_MISMATCH", "nav_change")
    expected_pct = Decimal("0") if previous_nav == 0 else nav_change / previous_nav * 100
    if nav_change_pct != expected_pct:
        raise BriefBlocked("PORTFOLIO_ARITHMETIC_MISMATCH", "nav_change_pct")
    result = {
        "currency": payload.get("currency"),
        "paper_only": True,
        "previous_cash": _money(previous_cash),
        "current_cash": _money(current_cash),
        "previous_nav": _money(previous_nav),
        "current_nav": _money(current_nav),
        "nav_change": _money(nav_change),
        "nav_change_pct": _money(nav_change_pct),
        "current_position_value": _money(current_position_value),
        "position_count": len(current_positions),
    }
    state = {
        "previous_cash": previous_cash,
        "current_cash": current_cash,
        "previous_positions": previous_positions,
        "current_positions": current_positions,
    }
    return result, state


def _validate_orders(payload: dict[str, Any], portfolio: dict[str, Decimal]) -> dict[str, Any]:
    orders = payload["orders"]
    ids: set[str] = set()
    cash_effect = Decimal("0")
    fees = Decimal("0")
    share_delta: dict[str, Decimal] = {}
    filled = 0
    not_filled = 0
    for row in orders:
        if not isinstance(row, dict):
            raise BriefBlocked("ORDER_SHAPE_INVALID", "ORDERS")
        order_id = row.get("order_id")
        instrument = row.get("instrument_id")
        if not isinstance(order_id, str) or not order_id or order_id in ids:
            raise BriefBlocked("ORDER_ID_INVALID", "ORDERS")
        if not isinstance(instrument, str) or not instrument.endswith(".TEST"):
            raise BriefBlocked("ORDER_INSTRUMENT_INVALID", order_id)
        ids.add(order_id)
        status = row.get("status")
        shares = _decimal(row.get("filled_shares"), "ORDER_NUMBER_INVALID", order_id)
        fee = _decimal(row.get("fee"), "ORDER_NUMBER_INVALID", order_id)
        effect = _decimal(row.get("cash_effect"), "ORDER_NUMBER_INVALID", order_id)
        if shares < 0 or fee < 0:
            raise BriefBlocked("ORDER_NUMBER_INVALID", order_id)
        if status == "NOT_FILLED":
            if shares != 0 or row.get("fill_price") is not None or fee != 0 or effect != 0:
                raise BriefBlocked("UNFILLED_ORDER_HAS_EFFECT", order_id)
            not_filled += 1
            continue
        if status != "FILLED" or shares <= 0:
            raise BriefBlocked("ORDER_STATUS_INVALID", order_id)
        price = _decimal(row.get("fill_price"), "ORDER_NUMBER_INVALID", order_id)
        if price <= 0 or row.get("side") not in {"buy", "sell"}:
            raise BriefBlocked("ORDER_NUMBER_INVALID", order_id)
        expected = shares * price
        delta = shares
        if row["side"] == "buy":
            expected = -(expected + fee)
        else:
            expected = expected - fee
            delta = -shares
        if effect != expected:
            raise BriefBlocked("ORDER_CASH_EFFECT_MISMATCH", order_id)
        cash_effect += effect
        fees += fee
        share_delta[instrument] = share_delta.get(instrument, Decimal("0")) + delta
        filled += 1

    if portfolio["current_cash"] - portfolio["previous_cash"] != cash_effect:
        raise BriefBlocked("ORDER_PORTFOLIO_CASH_MISMATCH", "ORDERS")
    instruments = set(portfolio["previous_positions"]) | set(portfolio["current_positions"]) | set(share_delta)
    for instrument in instruments:
        before = _decimal(
            portfolio["previous_positions"].get(instrument, {}).get("shares", 0),
            "PORTFOLIO_NUMBER_INVALID",
            instrument,
        )
        after = _decimal(
            portfolio["current_positions"].get(instrument, {}).get("shares", 0),
            "PORTFOLIO_NUMBER_INVALID",
            instrument,
        )
        if after - before != share_delta.get(instrument, Decimal("0")):
            raise BriefBlocked("ORDER_PORTFOLIO_POSITION_MISMATCH", instrument)
    return {
        "activity_status": "NO_ACTIVITY" if not orders else "ACTIVITY_PRESENT",
        "order_count": len(orders),
        "filled_count": filled,
        "not_filled_count": not_filled,
        "total_cash_effect": _money(cash_effect),
        "total_fees": _money(fees),
    }


def _resolve_pointer(value: Any, pointer: str) -> Any:
    current = value
    for token in pointer.removeprefix("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise KeyError(pointer)
    return current


def _receipt(status: str, issues: list[dict[str, str]], result: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "ar.workbench_daily_brief_acceptance.v1",
        "status": status,
        "sample_purpose": "WORKFLOW_DEBUG",
        "formal_authority": False,
        "issues": issues,
        "result": result,
    }
    payload["receipt_hash"] = sha256(canonical(payload).encode("utf-8"))
    _validate_schema(payload, _load_schema(OUTPUT_SCHEMA), "acceptance_receipt")
    return payload


def validate_bundle(bundle: Path) -> dict[str, Any]:
    """Validate one frozen synthetic bundle and return a deterministic receipt."""

    bundle = bundle.resolve()
    try:
        raw_manifest = _read_regular(bundle, "brief_input.json")
        envelope = parse_json(raw_manifest, "brief_input.json")
        _validate_schema(envelope, _load_schema(INPUT_SCHEMA), "brief_input.json")
        if not isinstance(envelope, dict):
            raise BriefBlocked("SCHEMA_INVALID", "brief_input.json")
        _trade_date(envelope["target_trade_date"], "brief_input.json")
        generated_at = _timestamp(envelope["generated_at"], "GENERATED_AT_INVALID", "brief_input.json")
        data_cutoff = _timestamp(envelope["data_cutoff"], "BRIEF_CUTOFF_INVALID", "brief_input.json")
        if data_cutoff > generated_at:
            raise BriefBlocked("BRIEF_CUTOFF_AFTER_GENERATION", "brief_input.json")
        descriptors = envelope["sources"]
        by_role = {row["role"]: row for row in descriptors}
        if len(by_role) != len(descriptors) or set(by_role) != REQUIRED_ROLES:
            raise BriefBlocked("SOURCE_ROLE_SET_INVALID", "brief_input.json")
        if envelope["displayed_run_id"] != envelope["run_id"]:
            raise BriefBlocked("DISPLAYED_RUN_BINDING_INVALID", "brief_input.json")
        publication = envelope["last_successful_publication"]
        if publication["run_id"] != envelope["displayed_run_id"]:
            raise BriefBlocked("PUBLICATION_DISPLAY_BINDING_INVALID", "brief_input.json")
        if publication["target_trade_date"] != envelope["target_trade_date"]:
            raise BriefBlocked("PUBLICATION_DATE_MISMATCH", "brief_input.json")
        if envelope["displayed_run_id"] not in {
            envelope["latest_attempt"]["run_id"],
            publication["run_id"],
        }:
            raise BriefBlocked("DISPLAYED_RUN_UNKNOWN", "brief_input.json")
        attempted_at = _timestamp(
            envelope["latest_attempt"]["attempted_at"],
            "LATEST_ATTEMPT_TIME_INVALID",
            "brief_input.json",
        )
        published_at = _timestamp(
            publication["published_at"],
            "PUBLICATION_TIME_INVALID",
            "brief_input.json",
        )
        if attempted_at > generated_at or published_at > generated_at:
            raise BriefBlocked("RUN_STATE_TIME_AFTER_GENERATION", "brief_input.json")
        if (
            envelope["latest_attempt"]["run_id"] != publication["run_id"]
            and attempted_at <= published_at
        ):
            raise BriefBlocked("LATEST_ATTEMPT_ORDER_INVALID", "brief_input.json")

        payloads: dict[str, dict[str, Any]] = {}
        source_rows: list[dict[str, Any]] = []
        for role in sorted(REQUIRED_ROLES):
            descriptor = by_role[role]
            if descriptor["path"] != ROLE_PATHS[role]:
                raise BriefBlocked("SOURCE_ROLE_PATH_MISMATCH", role)
            raw = _read_regular(bundle, descriptor["path"])
            # governance-mutation: WB01_SOURCE_HASH_BINDING
            if sha256(raw) != descriptor["sha256"]:
                raise BriefBlocked("SOURCE_HASH_MISMATCH", role)
            payload = parse_json(raw, role)
            if not isinstance(payload, dict):
                raise BriefBlocked("SOURCE_SCHEMA_INVALID", role)
            actual_quality = _validate_source_identity(role, descriptor, payload, envelope)
            if descriptor["quality_status"] != actual_quality:
                raise BriefBlocked("SOURCE_QUALITY_MISMATCH", role)
            payloads[role] = payload
            source_rows.append(
                {
                    "role": role,
                    "path": descriptor["path"],
                    "source_date": descriptor["source_date"],
                    "data_cutoff": descriptor["data_cutoff"],
                    "source_sha256": descriptor["sha256"],
                    "quality_status": actual_quality,
                }
            )

        portfolio_result, portfolio_state = _validate_portfolio(payloads["PORTFOLIO"])
        orders_result = _validate_orders(payloads["ORDERS"], portfolio_state)
        for ref in envelope["evidence_refs"]:
            try:
                _resolve_pointer(payloads[ref["source_role"]], ref["json_pointer"])
            except KeyError:
                raise BriefBlocked("EVIDENCE_POINTER_INVALID", ref["source_role"]) from None

        blocked_reasons = [
            f"{row['role']}_{row['quality_status']}"
            for row in source_rows
            if row["quality_status"] in {"PARTIAL", "DATA_BLOCKED"}
        ]
        result = {
            "identity": {
                key: envelope[key]
                for key in ("run_id", "target_trade_date", "generated_at", "data_cutoff", "code_version")
            },
            "run_state": {
                "latest_attempt": envelope["latest_attempt"],
                "last_successful_publication": publication,
                "displayed_run_id": envelope["displayed_run_id"],
                # governance-mutation: WB01_RUN_STATE_SEPARATION
                "displayed_is_latest_attempt": envelope["displayed_run_id"] == envelope["latest_attempt"]["run_id"],
            },
            "sources": source_rows,
            "portfolio": portfolio_result,
            "orders": orders_result,
            "quality": {
                "status": "PARTIAL" if blocked_reasons else "COMPLETE",
                "blocked_reasons": blocked_reasons,
                "missing_values_zero_filled": False,
                "market_to_portfolio_attribution": "NOT_ESTABLISHED",
            },
            "evidence_refs": envelope["evidence_refs"],
        }
        return _receipt("ACCEPTED", [], result)
    except BriefBlocked as error:
        return _receipt(
            "SPEC_BLOCKED",
            [{"code": error.code, "subject": error.subject}],
            None,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate one WB-01 daily brief fixture.")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    receipt = validate_bundle(args.bundle)
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0 if receipt["status"] == "ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
