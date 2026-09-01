#!/usr/bin/env python3
"""Seal and verify offline semiconductor post-U4 research freeze proposals.

The artifact produced here is a content-review proposal. It cannot select U4
names, create a paper order, mutate production data, or impersonate Junyan's
content approval. Thesis facts are point-in-time at the U4 cutoff; manual SMC
may use only later settled E3 observations whose cutoff is explicit.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for candidate in (
    ROOT / "scripts",
    ROOT / "experiments" / "execution_tracker",
    ROOT / "experiments" / "research_funnel",
):
    sys.path.insert(0, str(candidate))

import decision_pack as decision_pack_contract  # noqa: E402
import decision_sheet as decision_sheet_contract  # noqa: E402
import research_method as method_contract  # noqa: E402


SCHEMA = "ar.semiconductor_research_freeze_bundle.v1"
CASE_SCHEMA = "ar.semiconductor_research_freeze_proposal.v1"
MANIFEST_SCHEMA = "ar.semiconductor_research_freeze_manifest.v1"
DISCLAIMER = "不是买卖指令；研究信号，human executes."
EXPECTED_PACKET_HASH = (
    "7ea6b5764541c380baa5f727618662f37eca75dd1780a8099bf5342254a7c7ff"
)
EXPECTED_LEDGER_SHA256 = (
    "9a6e6b2a26834520fbf30bb2da6eb43e4da39a20ad2d5579e766e74be006d30e"
)
EXPECTED_RECEIPT_SHA256 = (
    "37578115f352fb1ae9f6bc2ee038efd620aa5f0cc8137bd3c332f14cc2443d3a"
)
EXPECTED_BUNDLE_HASH = (
    "8e59cd5474fb22e5843efa35d9f6b62f0494fb3a8f5320d56545e0ffa345de7d"
)
EXPECTED_CASES = {
    "300236.SZ": {
        "name": "上海新阳",
        "u2": "f02290c0e65fb1fc99e92a34379d48daf9b131fd95adbb2dd3f2cb1748dec038",
        "u3": "8f0bff13f34dc072c1b7b9384385e1c3f9f142043c56a9fe24636f3864c2dd66",
        "case": "f11618864f4324c6fc6e67aec09d3572668cab6e5455b2e6c3791b7c0b93de23",
    },
    "300623.SZ": {
        "name": "捷捷微电",
        "u2": "cdae96a151305a57002c2820894a6503dbf21c8240f80b31d9b58b775bd17778",
        "u3": "49c31779dd643e6f006e45dcad231c9fd88ccea1caf726972a9d421ca37267da",
        "case": "be62d0e88693fbcf538eb77b643e4b3480ef63da54f98ac36d49f619d5ff06be",
    },
    "688279.SH": {
        "name": "峰岹科技",
        "u2": "834a4800712a00d571aa925fb6174385ebbf888b8f86a3b47bf1681d1a3e7ddf",
        "u3": "971dd3e4a5e5e278a55662348b435ef2f02fb4129ff1248583f75dd7e818ec19",
        "case": "7173c6d7c54e34981a545da0384235cff79574302a7ff2269edc71e467137725",
    },
}
AUTHORITY = {
    "u4_selection_authority": "HUMAN_JUNYAN_ONLY",
    "paper_registration_authority": "HUMAN_JUNYAN_ONLY",
    "production_authority": False,
    "trade_authority": False,
    "claim_allowed": False,
    "no_trade_flag": True,
}
FORBIDDEN_KEYS = {
    "trade_action",
    "real_order",
    "real_capital_authority",
    "formal_blocking_authority",
}
AXES = {
    "FACT_COMPLETENESS",
    "VARIANT_THESIS",
    "FALSIFIABILITY",
    "VALUATION_DISCIPLINE",
    "TIMING_REGISTRATION",
    "REVIEWABILITY",
}


class FreezeError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FreezeError(f"non-canonical JSON: {exc}") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _without(value: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {name: item for name, item in value.items() if name != key}


def _date8(value: Any, label: str) -> str:
    raw = str(value or "").strip()
    try:
        if len(raw) == 8 and raw.isdigit():
            datetime.strptime(raw, "%Y%m%d")
            return raw
        if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
            return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise FreezeError(f"{label} is not a valid date") from exc
    raise FreezeError(f"{label} must be YYYYMMDD or YYYY-MM-DD")


def _walk_keys(value: Any):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key).casefold()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FreezeError(f"{label} must be numeric")
    output = float(value)
    if not math.isfinite(output):
        raise FreezeError(f"{label} must be finite")
    return output


def _technical_summary(bars: list[Mapping[str, Any]]) -> dict[str, Any]:
    if len(bars) != 20:
        raise FreezeError("settled_e3.bars must contain exactly 20 sessions")
    dates = [_date8(row.get("trade_date"), "bar.trade_date") for row in bars]
    if dates != sorted(dates) or len(set(dates)) != 20:
        raise FreezeError("settled_e3 bars must be unique and chronological")
    true_ranges: list[float] = []
    for index, row in enumerate(bars):
        high = _finite(row.get("high"), "bar.high")
        low = _finite(row.get("low"), "bar.low")
        open_ = _finite(row.get("open"), "bar.open")
        close = _finite(row.get("close"), "bar.close")
        volume = _finite(row.get("vol"), "bar.vol")
        # governance-mutation: SEMICONDUCTOR_FREEZE_E3_BAR_SHAPE
        if not low <= min(open_, close) <= max(open_, close) <= high or volume < 0:
            raise FreezeError("settled E3 bar shape is invalid")
        previous = (
            _finite(bars[index - 1].get("close"), "previous close")
            if index
            else _finite(row.get("pre_close"), "bar.pre_close")
        )
        true_ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
    close = float(bars[-1]["close"])
    range_low = min(float(row["low"]) for row in bars)
    range_high = max(float(row["high"]) for row in bars)
    if range_high <= range_low:
        raise FreezeError("settled E3 range must have positive width")
    volume_5 = sum(float(row["vol"]) for row in bars[-5:]) / 5.0
    volume_20 = sum(float(row["vol"]) for row in bars) / 20.0
    return {
        "settled_trade_date": dates[-1],
        "close": round(close, 4),
        "ma20": round(sum(float(row["close"]) for row in bars) / 20.0, 4),
        "atr14": round(sum(true_ranges[-14:]) / 14.0, 4),
        "range20_low": round(range_low, 4),
        "range20_high": round(range_high, 4),
        "range20_equilibrium": round((range_low + range_high) / 2.0, 4),
        "range_location_pct": round((close - range_low) / (range_high - range_low) * 100.0, 2),
        "volume_5v20": round(volume_5 / volume_20, 3),
    }


def _flow_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise FreezeError("settled_e3.moneyflow must be non-empty")
    ordered = sorted(rows, key=lambda row: str(row.get("trade_date") or ""))
    dates = [_date8(row.get("trade_date"), "moneyflow.trade_date") for row in ordered]
    if len(dates) != len(set(dates)):
        raise FreezeError("moneyflow dates must be unique")
    rates = [_finite(row.get("net_amount_rate"), "moneyflow.net_amount_rate") for row in ordered]
    return {
        "settled_trade_date": dates[-1],
        "positive_sessions": sum(rate > 0 for rate in rates),
        "observed_sessions": len(rates),
        "latest_net_amount_rate": round(rates[-1], 4),
        "five_session_net_amount_rate_sum": round(sum(rates[-5:]), 4),
    }


def _seal_derived(case: dict[str, Any]) -> None:
    for item in case["source_evidence"]["financial_records"]:
        item["source_record_hash"] = _hash(_without(item, "source_record_hash"))
    e3 = case["source_evidence"]["settled_e3"]
    e3["technical_summary"] = _technical_summary(e3["bars"])
    e3["flow_summary"] = _flow_summary(e3["moneyflow"])
    e3["evidence_hash"] = _hash(_without(e3, "evidence_hash"))

    core = case["thesis_core"]
    timing = case["timing_ticket"]
    pack = case["decision_pack"]
    draft = case["method_registration_draft"]
    wrong_if = core["wrong_if"]["triggers"]
    draft["thesis_core_hash"] = _hash(core)
    draft["timing_ticket_hash"] = _hash(timing)
    draft["decision_pack_hash"] = _hash(pack)
    draft["wrong_if_hash"] = _hash(wrong_if)
    invalidations = [
        claim for claim in draft["thesis_expectations"]
        if claim["kind"] == "INVALIDATION"
    ]
    if len(invalidations) != len(wrong_if):
        raise FreezeError("each wrong-if trigger needs one invalidation claim")
    for claim, trigger in zip(invalidations, wrong_if):
        claim["wrong_if_trigger_hash"] = _hash(trigger)
    draft["valuation"]["scenario_band_hash"] = _hash(core["valuation_target_range"])
    draft["smc"]["thesis_line_hash"] = _hash(wrong_if)
    draft["smc"]["evidence_hash"] = e3["evidence_hash"]
    try:
        registration = method_contract.seal_registration(
            draft,
            thesis_core=core,
            timing_ticket=timing,
            decision_pack=pack,
        )
    except method_contract.MethodError as exc:
        raise FreezeError(f"method registration draft is invalid: {exc}") from exc
    case["prospective_registration_hash"] = registration["registration_hash"]
    scorecard = case["quality_scorecard"]
    scorecard["artifact_ref"]["hash"] = "sha256:" + _hash(core)
    scorecard["average_score"] = round(
        sum(float(axis["score"]) for axis in scorecard["axes"]) / len(scorecard["axes"]),
        1,
    )
    case["case_hash"] = _hash(_without(case, "case_hash"))


def seal_bundle(payload: Mapping[str, Any]) -> dict[str, Any]:
    bundle = copy.deepcopy(dict(payload))
    for case in bundle.get("cases") or []:
        _seal_derived(case)
    bundle["selected_tickers"] = sorted(case["ticker"] for case in bundle.get("cases") or [])
    bundle["bundle_hash"] = _hash(_without(bundle, "bundle_hash"))
    errors = validate_bundle(bundle)
    if errors:
        raise FreezeError("sealed bundle is invalid: " + "; ".join(errors[:8]))
    return bundle


def _validate_case(case: Mapping[str, Any], bundle: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    ticker = str(case.get("ticker") or "")
    expected = EXPECTED_CASES.get(ticker)
    if expected is None:
        return [f"unexpected ticker: {ticker}"]
    if case.get("schema") != CASE_SCHEMA or case.get("schema_version") != "1.0":
        errors.append(f"{ticker}: case schema/version mismatch")
    if case.get("name") != expected["name"]:
        errors.append(f"{ticker}: display name mismatch")
    if case.get("status") != "AWAITING_JUNYAN_CONTENT_REVIEW":
        errors.append(f"{ticker}: content review status was overstated")
    if FORBIDDEN_KEYS.intersection(_walk_keys(case)):
        errors.append(f"{ticker}: forbidden authority/action field present")
    binding = case.get("u4_binding") or {}
    expected_binding = {
        "packet_hash": EXPECTED_PACKET_HASH,
        "ledger_snapshot_sha256": EXPECTED_LEDGER_SHA256,
        "decision_receipt_sha256": EXPECTED_RECEIPT_SHA256,
        "decision": "SELECT",
        "u2_candidate_row_hash": expected["u2"],
        "u3_battery_row_hash": expected["u3"],
        "as_of": "20260824",
        "method_version": "SEMICONDUCTOR_WORKFLOW_DEBUG_V1",
    }
    # governance-mutation: SEMICONDUCTOR_FREEZE_U4_BINDING
    if any(binding.get(key) != value for key, value in expected_binding.items()):
        errors.append(f"{ticker}: U4 binding differs from the frozen SELECT")
    if binding.get("production_authority") is not False or binding.get("no_trade_flag") is not True:
        errors.append(f"{ticker}: U4 authority boundary changed")

    source = case.get("source_evidence") or {}
    if _date8(source.get("factpack_cutoff"), "factpack_cutoff") != bundle["fact_cutoff"]:
        errors.append(f"{ticker}: factpack cutoff differs from bundle")
    records = source.get("financial_records") or []
    if not records:
        errors.append(f"{ticker}: financial evidence is empty")
    record_ids: set[str] = set()
    for index, item in enumerate(records):
        record_id = str(item.get("record_id") or "")
        if not record_id or record_id in record_ids:
            errors.append(f"{ticker}: financial record ids are empty or duplicated")
        record_ids.add(record_id)
        try:
            source_date = _date8(item.get("source_date"), f"record[{index}].source_date")
        except FreezeError as exc:
            errors.append(f"{ticker}: {exc}")
            continue
        # governance-mutation: SEMICONDUCTOR_FREEZE_PIT_CUTOFF
        if source_date > bundle["fact_cutoff"]:
            errors.append(f"{ticker}: post-cutoff fact leaked into thesis evidence")
        if item.get("tier") not in {"E1", "E2"}:
            errors.append(f"{ticker}: financial record tier is invalid")
        # governance-mutation: SEMICONDUCTOR_FREEZE_SOURCE_RECORD_HASH
        if item.get("source_record_hash") != _hash(_without(item, "source_record_hash")):
            errors.append(f"{ticker}: financial source record hash mismatch")

    e3 = source.get("settled_e3") or {}
    try:
        technical = _technical_summary(e3.get("bars") or [])
        flow = _flow_summary(e3.get("moneyflow") or [])
    except FreezeError as exc:
        errors.append(f"{ticker}: {exc}")
        technical, flow = {}, {}
    if e3.get("technical_summary") != technical or e3.get("flow_summary") != flow:
        errors.append(f"{ticker}: settled E3 summary is not derived from rows")
    if technical.get("settled_trade_date") != bundle["settled_e3_cutoff"]:
        errors.append(f"{ticker}: settled E3 cutoff differs from bundle")
    if e3.get("evidence_hash") != _hash(_without(e3, "evidence_hash")):
        errors.append(f"{ticker}: settled E3 evidence hash mismatch")
    sector = e3.get("sector_breadth") or {}
    if sector.get("trade_date") != bundle["settled_e3_cutoff"]:
        errors.append(f"{ticker}: sector breadth is not same-session settled E3")
    if not 0 <= int(sector.get("up", -1)) <= int(sector.get("observed", -1)):
        errors.append(f"{ticker}: sector breadth counts are invalid")

    core = case.get("thesis_core") or {}
    core_errors = decision_sheet_contract.qualify(core)
    if core_errors:
        errors.append(f"{ticker}: thesis core is not qualified: {core_errors[0]}")
    if _date8((core.get("identity") or {}).get("as_of"), "thesis as_of") != bundle["fact_cutoff"]:
        errors.append(f"{ticker}: thesis identity was backdated or moved")
    evidence_sources = {
        str(item.get("source") or "")
        for item in (core.get("evidence") or {}).get("items") or []
    }
    if not evidence_sources or not all(
        source_ref in record_ids or source_ref.startswith("DERIVATION:")
        for source_ref in evidence_sources
    ):
        errors.append(f"{ticker}: thesis evidence is not bound to frozen source records")

    pack = case.get("decision_pack") or {}
    pack_ok, pack_errors = decision_pack_contract.validate_pack(pack)
    if not pack_ok:
        errors.append(f"{ticker}: decision pack incomplete: {pack_errors[0]}")
    timing = case.get("timing_ticket") or {}
    if timing.get("status") != "WAIT" or timing.get("no_trade_flag") is not True:
        errors.append(f"{ticker}: timing must remain WAIT/no-trade before human review")
    draft = case.get("method_registration_draft") or {}
    try:
        registration = method_contract.seal_registration(
            draft,
            thesis_core=core,
            timing_ticket=timing,
            decision_pack=pack,
        )
    except Exception as exc:
        errors.append(f"{ticker}: method registration draft invalid: {exc}")
    else:
        if case.get("prospective_registration_hash") != registration["registration_hash"]:
            errors.append(f"{ticker}: prospective registration hash mismatch")
        if draft["smc"].get("status") != "WAIT":
            errors.append(f"{ticker}: manual SMC cannot be promoted before review")

    scorecard = case.get("quality_scorecard") or {}
    axes = scorecard.get("axes") or []
    if {axis.get("axis") for axis in axes} != AXES:
        errors.append(f"{ticker}: quality scorecard axes are incomplete")
    if scorecard.get("status") != "QUALITY_PASS" or scorecard.get("next_state") != "READY_FOR_HUMAN_REVIEW":
        errors.append(f"{ticker}: quality scorecard next state is invalid")
    if scorecard.get("blockers") != []:
        errors.append(f"{ticker}: QUALITY_PASS cannot carry blockers")
    if axes:
        average = round(sum(float(axis["score"]) for axis in axes) / len(axes), 1)
        if average < 70 or any(float(axis["score"]) < 50 for axis in axes):
            errors.append(f"{ticker}: QUALITY_PASS thresholds are not met")
        if scorecard.get("average_score") != average:
            errors.append(f"{ticker}: scorecard average is not derived")
    if scorecard.get("artifact_ref", {}).get("hash") != "sha256:" + _hash(core):
        errors.append(f"{ticker}: scorecard is not bound to the thesis core")
    if scorecard.get("authority") != AUTHORITY:
        errors.append(f"{ticker}: scorecard authority boundary changed")
    if case.get("case_hash") != _hash(_without(case, "case_hash")):
        errors.append(f"{ticker}: case hash mismatch")
    # governance-mutation: SEMICONDUCTOR_FREEZE_CASE_CONTENT_LOCK
    elif case.get("case_hash") != expected["case"]:
        errors.append(f"{ticker}: frozen case content hash changed; Junyan re-review is required")
    return errors


def validate_bundle(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema") != SCHEMA or payload.get("schema_version") != "1.0":
        errors.append("bundle schema/version mismatch")
    if payload.get("artifact_status") != "AWAITING_JUNYAN_CONTENT_REVIEW":
        errors.append("bundle content review status was overstated")
    try:
        fact_cutoff = _date8(payload.get("fact_cutoff"), "fact_cutoff")
        smc_date = _date8(payload.get("smc_assessment_date"), "smc_assessment_date")
        settled = _date8(payload.get("settled_e3_cutoff"), "settled_e3_cutoff")
        if (fact_cutoff, settled, smc_date) != ("20260824", "20260831", "20260901"):
            errors.append("fact/settled-E3/SMC chronology is invalid")
    except FreezeError as exc:
        errors.append(str(exc))
    if payload.get("u4_packet_hash") != EXPECTED_PACKET_HASH:
        errors.append("bundle U4 packet hash mismatch")
    if payload.get("u4_ledger_snapshot_sha256") != EXPECTED_LEDGER_SHA256:
        errors.append("bundle U4 ledger snapshot hash mismatch")
    if payload.get("u4_decision_receipt_sha256") != EXPECTED_RECEIPT_SHA256:
        errors.append("bundle U4 decision receipt hash mismatch")
    if payload.get("authority") != AUTHORITY:
        errors.append("bundle authority boundary changed")
    if payload.get("disclaimer") != DISCLAIMER:
        errors.append("bundle disclaimer mismatch")
    cases = payload.get("cases") or []
    tickers = [str(case.get("ticker") or "") for case in cases]
    if sorted(tickers) != sorted(EXPECTED_CASES) or len(tickers) != len(set(tickers)):
        errors.append("bundle must freeze exactly the three U4 SELECT names")
    if payload.get("selected_tickers") != sorted(EXPECTED_CASES):
        errors.append("selected_tickers is not derived from cases")
    for case in cases:
        try:
            errors.extend(_validate_case(case, payload))
        except (FreezeError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"{case.get('ticker', '?')}: validation crashed closed: {exc}")
    if payload.get("bundle_hash") != _hash(_without(payload, "bundle_hash")):
        errors.append("bundle hash mismatch")
    # governance-mutation: SEMICONDUCTOR_FREEZE_BUNDLE_CONTENT_LOCK
    elif payload.get("bundle_hash") != EXPECTED_BUNDLE_HASH:
        errors.append("frozen bundle content hash changed; Junyan re-review is required")
    return errors


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(root: Path) -> dict[str, Any]:
    bundle = _load(root / "freeze_proposals.json")
    paths = [
        "freeze_proposals.json",
        *(f"{ticker}.json" for ticker in sorted(EXPECTED_CASES)),
        "JUNYAN_CONTENT_REVIEW.md",
    ]
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "schema_version": "1.0",
        "artifact_status": "AWAITING_JUNYAN_CONTENT_REVIEW",
        "bundle_hash": bundle.get("bundle_hash"),
        "files": [
            {"path": name, "sha256": _file_sha256(root / name)} for name in paths
        ],
        "authority": dict(AUTHORITY),
        "disclaimer": DISCLAIMER,
        "manifest_hash": "",
    }
    manifest["manifest_hash"] = _hash(_without(manifest, "manifest_hash"))
    return manifest


def validate_directory(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        manifest = _load(root / "manifest.json")
        bundle = _load(root / "freeze_proposals.json")
    except (OSError, json.JSONDecodeError, FreezeError) as exc:
        return [f"freeze directory cannot be read: {exc}"]
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("schema_version") != "1.0":
        errors.append("freeze manifest schema/version mismatch")
    if manifest.get("artifact_status") != "AWAITING_JUNYAN_CONTENT_REVIEW":
        errors.append("freeze manifest status was overstated")
    if manifest.get("authority") != AUTHORITY or manifest.get("disclaimer") != DISCLAIMER:
        errors.append("freeze manifest authority/disclaimer mismatch")
    if manifest.get("manifest_hash") != _hash(_without(manifest, "manifest_hash")):
        errors.append("freeze manifest hash mismatch")
    expected_paths = {
        "freeze_proposals.json",
        *(f"{ticker}.json" for ticker in EXPECTED_CASES),
        "JUNYAN_CONTENT_REVIEW.md",
    }
    rows = manifest.get("files") or []
    observed_paths = [str(row.get("path") or "") for row in rows]
    if set(observed_paths) != expected_paths or len(observed_paths) != len(set(observed_paths)):
        errors.append("freeze manifest file set is incomplete or duplicated")
    for row in rows:
        name = str(row.get("path") or "")
        path = root / name
        if Path(name).name != name or name not in expected_paths:
            errors.append(f"unsafe or unexpected freeze manifest path: {name}")
            continue
        if not path.is_file() or row.get("sha256") != _file_sha256(path):
            errors.append(f"freeze artifact hash mismatch: {name}")
    errors.extend(validate_bundle(bundle))
    if manifest.get("bundle_hash") != bundle.get("bundle_hash"):
        errors.append("manifest is not bound to the freeze bundle")
    by_ticker = {str(case.get("ticker") or ""): case for case in bundle.get("cases") or []}
    for ticker in EXPECTED_CASES:
        try:
            case_copy = _load(root / f"{ticker}.json")
        except (OSError, json.JSONDecodeError, FreezeError) as exc:
            errors.append(f"{ticker}: case copy cannot be read: {exc}")
            continue
        # governance-mutation: SEMICONDUCTOR_FREEZE_SPLIT_CASE_BINDING
        if case_copy != by_ticker.get(ticker):
            errors.append(f"{ticker}: case copy differs from bundle")
    return errors


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        # governance-mutation: SEMICONDUCTOR_FREEZE_DUPLICATE_JSON
        if key in output:
            raise FreezeError(f"duplicate JSON key: {key}")
        output[key] = value
    return output


def _load(path: Path) -> dict[str, Any]:
    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--seal-output")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--verify-dir")
    args = parser.parse_args(argv)
    if args.verify_dir:
        errors = validate_directory(Path(args.verify_dir))
        print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False))
        return 0 if not errors else 1
    if not args.input:
        parser.error("--input is required unless --verify-dir is used")
    source = _load(Path(args.input))
    if args.seal_output:
        sealed = seal_bundle(source)
        Path(args.seal_output).write_text(
            json.dumps(sealed, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"ok": True, "bundle_hash": sealed["bundle_hash"]}))
        return 0
    if not args.verify:
        parser.error("choose --verify or --seal-output")
    errors = validate_bundle(source)
    print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
