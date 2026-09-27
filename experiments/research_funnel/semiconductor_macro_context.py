"""Pure offline projection of frozen M1-B evidence, never a funnel ranking input."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from experiments.macro_os import m1b


class ContextError(ValueError):
    pass


def context_hash(payload: dict[str, Any]) -> str:
    return m1b.content_hash({key: value for key, value in payload.items() if key != "context_hash"})


def build_context(
    *, industry_bytes: bytes, expected_sha256: str, run_id: str, target_trade_date: str,
) -> dict[str, Any]:
    """The expected byte hash must come from the caller's verified frozen manifest.

    No source paths, wall clock, network, file writes or stock-selection inputs
    enter this projection. It supplements, but never reseals, an existing packet.
    """
    actual_hash = hashlib.sha256(industry_bytes).hexdigest()
    # governance-mutation: SEMI_MACRO_CONTEXT_SOURCE_HASH
    if actual_hash != expected_sha256:
        raise ContextError("industry source hash differs from frozen manifest")
    try:
        industry = json.loads(industry_bytes)
        # governance-mutation: SEMI_MACRO_CONTEXT_CONTRACT
        m1b.validate_industry(industry)
    except (m1b.M1BError, ValueError, TypeError, KeyError) as exc:
        raise ContextError(f"invalid M1-B industry contract: {exc}") from exc
    # governance-mutation: SEMI_MACRO_CONTEXT_RUN
    if not run_id or industry["run_id"] != run_id:
        raise ContextError("industry run binding differs from frozen bundle")
    try:
        as_of = datetime.fromisoformat(industry["as_of"].replace("Z", "+00:00"))
        valid_date = bool(re.fullmatch(r"[0-9]{8}", target_trade_date))
        # governance-mutation: SEMI_MACRO_CONTEXT_TIMEZONE
        operational_day = as_of.astimezone(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ContextError("invalid source trade date") from exc
    # governance-mutation: SEMI_MACRO_CONTEXT_DATE
    if as_of.tzinfo is None or not valid_date or operational_day != target_trade_date:
        raise ContextError("industry trade date differs from frozen bundle")
    spec = m1b.load_spec()
    # governance-mutation: SEMI_MACRO_CONTEXT_SPEC
    if industry["spec_hash"] != spec["spec_hash"]:
        raise ContextError("industry spec binding differs from registered mapping")
    alias = spec["theme_aliases"]["半导体"]
    matches = [row for row in industry["data"]["subsectors"]
               if (row["industry"], row["subsector"]) == (alias["industry"], alias["subsector"])]
    # governance-mutation: SEMI_MACRO_CONTEXT_EXACT_SUBSECTOR
    if len(matches) != 1:
        raise ContextError("exactly one registered semiconductor subsector is required")
    row = matches[0]
    current = sum(relation["data_status"] == "CURRENT" for relation in row["relations"])
    # governance-mutation: SEMI_MACRO_CONTEXT_PARTIAL
    quality = "DATA_BLOCKED" if not current else "COMPLETE" if current == len(row["relations"]) else "PARTIAL"
    result = {
        "schema": "ar.semiconductor_macro_context.v1",
        "sample_purpose": "WORKFLOW_DEBUG", "mode": "CALIBRATING",
        "validation_status": "UNVALIDATED_V0", "run_id": run_id,
        "target_trade_date": target_trade_date, "source_as_of": industry["as_of"],
        "source_generated_at": industry["generated_at"], "source_sha256": actual_hash,
        "source_m1a_manifest_hash": industry["source_m1a_manifest_hash"],
        "source_m1a_run_id": industry["source_m1a_run_id"], "spec_hash": spec["spec_hash"],
        "industry": alias["industry"], "subsector": alias["subsector"],
        "data_quality": quality, "context_direction": row["context_direction"],
        "coverage": row["coverage"], "blocked_factors": copy.deepcopy(row["blocked_factors"]),
        "relations": copy.deepcopy(row["relations"]),
        # governance-mutation: SEMI_MACRO_CONTEXT_AUTHORITY
        "authority": {name: False for name in (
            "ranking_allowed", "selection_authority", "formal_blocking_authority",
            "trade_authority", "claim_allowed", "production_authority",
        )},
        "disclaimer": m1b.DISCLAIMER,
    }
    result["context_hash"] = context_hash(result)
    return result


def validate_context(payload: dict[str, Any], **source: Any) -> None:
    expected = build_context(**source)
    # governance-mutation: SEMI_MACRO_CONTEXT_TYPES
    same_contract = _canonical(payload) == _canonical(expected)
    # governance-mutation: SEMI_MACRO_CONTEXT_REDERIVE
    if not same_contract:
        raise ContextError("macro supplement differs from reopened evidence")


def _canonical(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ContextError("macro supplement is not valid JSON") from exc
