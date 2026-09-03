#!/usr/bin/env python3
"""Strict, offline reader and display-only evaluator for research knowledge cards.

Knowledge cards describe reviewed research methods.  This module validates their
shape and can derive small, type-specific observations from caller-supplied
evidence.  It does not parse prose into rules, rank securities, or grant U4,
trade, claim, or portfolio authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


CARD_SCHEMA = "ar.knowledge_card.v1"
EVALUATION_SCHEMA = "ar.knowledge_card_evaluation.v1"
DISCLAIMER = "It is not a recommendation list. Research evidence only; human review required."

STATUS_ORDER = ("DRAFT", "REVIEWED", "ENCODED", "VALIDATED", "RETIRED")
PARTICIPATING_STATUSES = frozenset({"REVIEWED", "ENCODED", "VALIDATED"})
SUB_SECTORS = frozenset({"MATERIALS", "EQUIPMENT", "DESIGN", "FOUNDRY", "OSAT"})
AVAILABILITY = frozenset({"AUTO", "SEMI", "MANUAL"})
LOGIC_TYPES = frozenset(
    {"THRESHOLD", "TREND", "STAGE_LADDER", "RATIO_VS_PEER", "CYCLE_POSITION"}
)
EVIDENCE_TIERS = frozenset({"E1", "E2"})
CHANNEL_BINDINGS = frozenset(
    {
        "E1_EVENT",
        "PRICE_VOLUME",
        "FUND_FLOW_CHIPS",
        "FUNDAMENTAL_VALUATION",
        "INDUSTRY_VALUE_CHAIN",
        "MACRO_CROSS_ASSET",
        "BATTERY_基本面",
        "BATTERY_估值",
        "BATTERY_消息面",
        "BATTERY_资金",
        "BATTERY_技术面",
        "BATTERY_行情",
        "LLM_MUST_CHECK",
    }
)

CARD_REQUIRED_FIELDS = frozenset(
    {
        "card_id",
        "sub_sector",
        "variable",
        "why_it_matters",
        "data_source",
        "judgment_logic",
        "evidence_tier",
        "literature",
        "falsification",
        "channel_binding",
        "status",
        "authored_by",
        "reviewed_by",
        "as_of",
    }
)
CARD_OPTIONAL_FIELDS = frozenset({"review_notes"})
DATA_SOURCE_FIELDS = frozenset(
    {"availability", "primary", "tushare_api", "tushare_field", "manual_required"}
)
LOGIC_REQUIRED_FIELDS = frozenset({"type", "positive_if", "negative_if", "lookback"})
LOGIC_OPTIONAL_FIELDS = frozenset({"threshold", "stages"})
CARD_ID_RE = re.compile(r"^SEMI_(MAT|EQP|DSN|FDY|OSAT)_[0-9]{3}$")
DATE8_RE = re.compile(r"^[0-9]{8}$")
CARD_TEXT_MIN_LENGTHS = {
    "variable": 2,
    "why_it_matters": 20,
    "falsification": 10,
}


class KnowledgeCardError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _reject_constant(value: str) -> None:
    raise KnowledgeCardError(f"non-finite JSON constant is not allowed: {value}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise KnowledgeCardError(f"duplicate JSON key: {key}")
        output[key] = value
    return output


def _load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeCardError(f"cannot read knowledge cards: {path}") from exc


def _exact_fields(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = set(value)
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        raise KnowledgeCardError(f"{label} fields mismatch: missing={missing} extra={extra}")


def _required_and_optional_fields(
    value: Mapping[str, Any],
    required: frozenset[str],
    optional: frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    missing = sorted(set(required) - actual)
    extra = sorted(actual - set(required) - set(optional))
    if missing or extra:
        raise KnowledgeCardError(f"{label} fields mismatch: missing={missing} extra={extra}")


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeCardError(f"{label} must be a non-empty string")
    return value


def _split_csv(value: str, label: str) -> tuple[str, ...]:
    parts = tuple(part.strip() for part in value.split(","))
    if not parts or any(not part for part in parts) or len(set(parts)) != len(parts):
        raise KnowledgeCardError(f"{label} must be a unique comma-separated list")
    return parts


def _field_names(raw: str | Sequence[str]) -> frozenset[str]:
    values = raw.split(",") if isinstance(raw, str) else raw
    return frozenset(str(value).strip() for value in values if str(value).strip())


def repo_collected_tushare_fields() -> dict[str, frozenset[str]]:
    """Build the field catalog from the collectors that declare exact fields.

    ``scripts/fetch_tushare.py`` stores provider-default raw rows and therefore
    has no stable field-level contract to contribute here.  Its API calls are
    not treated as proof that any particular field is available to the
    all-market feature store.
    """
    import feature_store
    import semiconductor_inputs

    collected = {
        api: set(_field_names(fields))
        for api, fields in feature_store.ENDPOINT_FIELDS.items()
    }
    exact_semiconductor_sources = {
        "moneyflow_dc": semiconductor_inputs.MONEYFLOW_FIELDS,
        "cyq_perf": semiconductor_inputs.CHIPS_FIELDS,
        "fina_indicator": semiconductor_inputs.FINANCIAL_FIELDS,
    }
    for api, fields in exact_semiconductor_sources.items():
        collected.setdefault(api, set()).update(_field_names(fields))
    return {api: frozenset(fields) for api, fields in sorted(collected.items())}


def source_coverage(card: Mapping[str, Any]) -> dict[str, Any]:
    """Report every declared API/field pair without claiming missing collection."""
    source = card.get("data_source") or {}
    api_value = source.get("tushare_api")
    field_value = source.get("tushare_field")
    if api_value is None or field_value is None:
        return {
            "collected_by_repo": False,
            "declared_pairs": [],
            "uncollected_pairs": [],
        }
    apis = _split_csv(str(api_value), "data_source.tushare_api")
    fields = _split_csv(str(field_value), "data_source.tushare_field")
    catalog = repo_collected_tushare_fields()
    pairs = [
        {
            "api": api,
            "field": field,
            "collected_by_repo": field in catalog.get(api, frozenset()),
        }
        for api in apis
        for field in fields
    ]
    missing = [f"{pair['api']}.{pair['field']}" for pair in pairs if not pair["collected_by_repo"]]
    return {
        # governance-mutation: CARD_SOURCE_FIELD_COVERAGE
        "collected_by_repo": bool(pairs) and not missing,
        "declared_pairs": pairs,
        "uncollected_pairs": missing,
    }


def _validate_source(source: Any, label: str) -> None:
    if not isinstance(source, Mapping):
        raise KnowledgeCardError(f"{label} must be an object")
    _exact_fields(source, DATA_SOURCE_FIELDS, label)
    availability = source["availability"]
    if availability not in AVAILABILITY:
        raise KnowledgeCardError(f"{label}.availability is invalid")
    _nonempty_string(source["primary"], f"{label}.primary")
    if not isinstance(source["manual_required"], bool):
        raise KnowledgeCardError(f"{label}.manual_required must be boolean")

    api_value = source["tushare_api"]
    field_value = source["tushare_field"]
    if api_value is None and field_value is not None:
        raise KnowledgeCardError(f"{label}.tushare_field requires tushare_api")
    if api_value is not None and field_value is None:
        raise KnowledgeCardError(f"{label}.tushare_api requires tushare_field")
    if availability == "AUTO" and field_value is None:
        raise KnowledgeCardError(f"{label}: AUTO requires a known Tushare field")
    if availability == "MANUAL" and source["manual_required"] is not True:
        raise KnowledgeCardError(f"{label}: MANUAL requires manual_required=true")
    if api_value is None:
        return

    _split_csv(_nonempty_string(api_value, f"{label}.tushare_api"), f"{label}.tushare_api")
    _split_csv(
        _nonempty_string(field_value, f"{label}.tushare_field"),
        f"{label}.tushare_field",
    )


def _validate_logic(logic: Any, label: str) -> None:
    if not isinstance(logic, Mapping):
        raise KnowledgeCardError(f"{label} must be an object")
    _required_and_optional_fields(
        logic, LOGIC_REQUIRED_FIELDS, LOGIC_OPTIONAL_FIELDS, label
    )
    logic_type = logic["type"]
    if logic_type not in LOGIC_TYPES:
        raise KnowledgeCardError(f"{label}.type is invalid")
    for field in ("positive_if", "negative_if", "lookback"):
        _nonempty_string(logic[field], f"{label}.{field}")
    threshold = logic.get("threshold")
    if threshold is not None and (
        isinstance(threshold, bool) or not isinstance(threshold, (int, float, str))
    ):
        raise KnowledgeCardError(f"{label}.threshold has an invalid type")
    stages = logic.get("stages")
    if logic_type == "STAGE_LADDER":
        if (
            not isinstance(stages, list)
            or not stages
            or any(not isinstance(stage, str) or not stage.strip() for stage in stages)
            or len(stages) != len(set(stages))
        ):
            raise KnowledgeCardError(f"{label}.stages must be a non-empty unique list")
    elif stages is not None:
        raise KnowledgeCardError(f"{label}.stages is only valid for STAGE_LADDER")


def validate_card(card: Any) -> None:
    if not isinstance(card, Mapping):
        raise KnowledgeCardError("knowledge card must be an object")
    _required_and_optional_fields(card, CARD_REQUIRED_FIELDS, CARD_OPTIONAL_FIELDS, "card")
    card_id = _nonempty_string(card["card_id"], "card.card_id")
    if CARD_ID_RE.fullmatch(card_id) is None:
        raise KnowledgeCardError(f"card.card_id is invalid: {card_id}")
    if card["sub_sector"] not in SUB_SECTORS:
        raise KnowledgeCardError(f"{card_id}.sub_sector is invalid")
    for field in ("variable", "why_it_matters", "falsification", "authored_by"):
        text = _nonempty_string(card[field], f"{card_id}.{field}")
        minimum = CARD_TEXT_MIN_LENGTHS.get(field)
        # governance-mutation: CARD_SCHEMA_MIN_LENGTHS
        if minimum is not None and len(text) < minimum:
            raise KnowledgeCardError(f"{card_id}.{field} must have length >= {minimum}")
    if card["status"] not in STATUS_ORDER:
        raise KnowledgeCardError(f"{card_id}.status is invalid")
    if card["status"] != "DRAFT":
        _nonempty_string(card["reviewed_by"], f"{card_id}.reviewed_by")
    elif card["reviewed_by"] is not None and not isinstance(card["reviewed_by"], str):
        raise KnowledgeCardError(f"{card_id}.reviewed_by has an invalid type")
    if not isinstance(card["as_of"], str) or DATE8_RE.fullmatch(card["as_of"]) is None:
        raise KnowledgeCardError(f"{card_id}.as_of must be YYYYMMDD")
    if card["evidence_tier"] not in EVIDENCE_TIERS:
        raise KnowledgeCardError(f"{card_id}.evidence_tier is invalid")
    literature = card["literature"]
    if not isinstance(literature, list) or not literature:
        raise KnowledgeCardError(f"{card_id}.literature must be non-empty")
    for index, item in enumerate(literature):
        _nonempty_string(item, f"{card_id}.literature[{index}]")
    bindings = card["channel_binding"]
    if (
        not isinstance(bindings, list)
        or not bindings
        or len(bindings) != len(set(bindings))
        or not set(bindings).issubset(CHANNEL_BINDINGS)
    ):
        raise KnowledgeCardError(f"{card_id}.channel_binding is invalid")
    if "review_notes" in card and not isinstance(card["review_notes"], str):
        raise KnowledgeCardError(f"{card_id}.review_notes must be a string")
    _validate_source(card["data_source"], f"{card_id}.data_source")
    _validate_logic(card["judgment_logic"], f"{card_id}.judgment_logic")


def validate_cards(cards: Any) -> None:
    if not isinstance(cards, list):
        raise KnowledgeCardError("knowledge card table must be an array")
    seen: set[str] = set()
    for card in cards:
        validate_card(card)
        card_id = str(card["card_id"])
        if card_id in seen:
            raise KnowledgeCardError(f"duplicate card_id: {card_id}")
        seen.add(card_id)


def load_cards(path: str | Path) -> list[dict[str, Any]]:
    payload = _load_json(Path(path))
    validate_cards(payload)
    return payload


def participating_cards(cards: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    validate_cards(list(cards))
    # governance-mutation: CARD_STATUS_GATE
    selected = [card for card in cards if card["status"] in PARTICIPATING_STATUSES]
    return sorted(selected, key=lambda card: str(card["card_id"]))


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KnowledgeCardError(f"{label} must be numeric")
    output = float(value)
    if not math.isfinite(output):
        raise KnowledgeCardError(f"{label} must be finite")
    return output


def _blocked(card: Mapping[str, Any], row: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "schema": EVALUATION_SCHEMA,
        "card_id": card["card_id"],
        "logic_type": card["judgment_logic"]["type"],
        "status": "DATA_BLOCKED",
        "display_only": True,
        "thresholds_validated": False,
        "reason_codes": [reason],
        "result": None,
        "card_hash": canonical_hash(card),
        "source_row_hash": canonical_hash(row),
        "source_coverage": source_coverage(card),
        "disclaimer": DISCLAIMER,
    }


def evaluate(card: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Derive one display-only observation without interpreting research prose."""
    validate_card(card)
    if card["status"] not in PARTICIPATING_STATUSES:
        return None
    if not isinstance(row, Mapping):
        raise KnowledgeCardError("evaluation row must be an object")
    coverage = source_coverage(card)
    if card["data_source"]["availability"] == "AUTO":
        # governance-mutation: CARD_AUTO_SOURCE_COLLECTION_GATE
        if not coverage["collected_by_repo"]:
            return _blocked(card, row, "SOURCE_FIELDS_NOT_COLLECTED_BY_REPO")
    logic = card["judgment_logic"]
    logic_type = logic["type"]

    try:
        if logic_type == "THRESHOLD":
            threshold_raw = logic.get("threshold")
            if isinstance(threshold_raw, bool) or not isinstance(threshold_raw, (int, float)):
                return _blocked(card, row, "UNENCODED_THRESHOLD")
            observed = _finite_number(row.get("value"), "row.value")
            threshold = _finite_number(threshold_raw, "judgment_logic.threshold")
            # governance-mutation: CARD_EVAL_DERIVES_FROM_SOURCE
            comparison = "AT_OR_ABOVE" if observed >= threshold else "BELOW"
            result = {
                "observed": observed,
                "threshold_unvalidated": threshold,
                "comparison_unvalidated": comparison,
            }
        elif logic_type == "TREND":
            raw_series = row.get("series")
            if not isinstance(raw_series, list) or len(raw_series) < 2:
                return _blocked(card, row, "TREND_SERIES_MISSING")
            series = [_finite_number(value, "row.series") for value in raw_series]
            delta = series[-1] - series[0]
            result = {
                "first": series[0],
                "latest": series[-1],
                "delta": delta,
                "direction_unvalidated": "UP" if delta > 0 else "DOWN" if delta < 0 else "FLAT",
            }
        elif logic_type == "STAGE_LADDER":
            stages = list(logic["stages"])
            current = row.get("current_stage")
            previous = row.get("previous_stage")
            if current not in stages:
                return _blocked(card, row, "CURRENT_STAGE_MISSING")
            if previous is not None and previous not in stages:
                return _blocked(card, row, "PREVIOUS_STAGE_UNKNOWN")
            current_index = stages.index(current)
            previous_index = stages.index(previous) if previous is not None else None
            movement = None if previous_index is None else current_index - previous_index
            result = {
                "current_stage": current,
                "current_index": current_index,
                "previous_stage": previous,
                "movement_unvalidated": movement,
            }
        elif logic_type == "RATIO_VS_PEER":
            observed = _finite_number(row.get("value"), "row.value")
            peer = _finite_number(row.get("peer_value"), "row.peer_value")
            if peer == 0:
                return _blocked(card, row, "PEER_VALUE_ZERO")
            result = {
                "observed": observed,
                "peer_value": peer,
                "ratio_unvalidated": observed / peer,
                "relation_unvalidated": "ABOVE" if observed > peer else "BELOW" if observed < peer else "EQUAL",
            }
        else:
            observed = _finite_number(row.get("value"), "row.value")
            raw_history = row.get("history")
            if not isinstance(raw_history, list) or not raw_history:
                return _blocked(card, row, "CYCLE_HISTORY_MISSING")
            history = [_finite_number(value, "row.history") for value in raw_history]
            below = sum(value < observed for value in history)
            equal = sum(value == observed for value in history)
            result = {
                "observed": observed,
                "history_count": len(history),
                "percentile_unvalidated": (below + 0.5 * equal) / len(history) * 100.0,
            }
    except KnowledgeCardError as exc:
        return _blocked(card, row, str(exc))

    return {
        "schema": EVALUATION_SCHEMA,
        "card_id": card["card_id"],
        "logic_type": logic_type,
        "status": "COMPLETE",
        "display_only": True,
        "thresholds_validated": False,
        "reason_codes": [],
        "result": result,
        "card_hash": canonical_hash(card),
        "source_row_hash": canonical_hash(row),
        "source_coverage": coverage,
        "disclaimer": DISCLAIMER,
    }


def attach_evaluations(
    payload: Mapping[str, Any],
    cards: Sequence[Mapping[str, Any]],
    rows_by_card: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Attach deterministic observations; an empty/inactive table is a no-op."""
    if not isinstance(payload, Mapping) or not isinstance(rows_by_card, Mapping):
        raise KnowledgeCardError("payload and rows_by_card must be objects")
    active = participating_cards(cards)
    if not active:
        return payload
    if "knowledge_card_evidence" in payload or "knowledge_card_evidence_hash" in payload:
        raise KnowledgeCardError("payload already contains knowledge card evidence")
    evaluations = [evaluate(card, rows_by_card.get(str(card["card_id"]), {})) for card in active]
    output = dict(payload)
    output["knowledge_card_evidence"] = evaluations
    output["knowledge_card_evidence_hash"] = canonical_hash(evaluations)
    verify_evaluations(output, cards, rows_by_card)
    return output


def verify_evaluations(
    payload: Mapping[str, Any],
    cards: Sequence[Mapping[str, Any]],
    rows_by_card: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Rebuild every active observation and reject any self-consistent rewrite."""
    if not isinstance(payload, Mapping) or not isinstance(rows_by_card, Mapping):
        raise KnowledgeCardError("payload and rows_by_card must be objects")
    active = participating_cards(cards)
    if not active:
        if "knowledge_card_evidence" in payload or "knowledge_card_evidence_hash" in payload:
            raise KnowledgeCardError("inactive card table cannot carry evaluations")
        return {"ok": True, "count": 0, "evidence_hash": None}
    evidence = payload.get("knowledge_card_evidence")
    if not isinstance(evidence, list):
        raise KnowledgeCardError("knowledge_card_evidence must be an array")
    observed_hash = payload.get("knowledge_card_evidence_hash")
    if observed_hash != canonical_hash(evidence):
        raise KnowledgeCardError("knowledge-card evidence hash mismatch")
    expected = [
        evaluate(card, rows_by_card.get(str(card["card_id"]), {}))
        for card in active
    ]
    # governance-mutation: CARD_EVIDENCE_HASH_VERIFIED
    if evidence != expected:
        raise KnowledgeCardError("knowledge-card evidence differs from source-derived result")
    return {
        "ok": True,
        "count": len(evidence),
        "evidence_hash": observed_hash,
    }


def _summary(cards: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema": CARD_SCHEMA,
        "card_count": len(cards),
        "participating_count": len(participating_cards(cards)),
        "status_counts": {
            status: sum(card["status"] == status for card in cards)
            for status in STATUS_ORDER
            if any(card["status"] == status for card in cards)
        },
        "cards_hash": canonical_hash(cards),
        "source_coverage": [
            {"card_id": card["card_id"], **source_coverage(card)}
            for card in sorted(cards, key=lambda item: str(item["card_id"]))
        ],
        "authority": {
            "selection": False,
            "trade": False,
            "claim": False,
            "portfolio": False,
        },
        "disclaimer": DISCLAIMER,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cards", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        cards = load_cards(args.cards)
    except KnowledgeCardError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(_summary(cards), ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
