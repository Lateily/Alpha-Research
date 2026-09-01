#!/usr/bin/env python3
"""Build an offline semiconductor same-day rerun operator packet.

This tool composes already-produced source-scan and intake-diagnostic artifacts
into the operator packet required before any semiconductor same-day U1-U3 rerun.
It does not fetch market data, run the nightly pipeline, choose U4 names, create
paper orders, or write production state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence


PACKET_SCHEMA = "ar.semiconductor_rerun_operator_packet.v0"
SOURCE_SCAN_SCHEMA = "ar.semiconductor_source_repair_scan"
DIAGNOSTIC_SCHEMA = "ar.semiconductor_u1_u3_diagnostic.v0"
DISCLAIMER = "不是买卖指令；研究信号，human executes."
AUTHORITY = {
    "authority": "HUMAN_JUNYAN_ONLY",
    "production_authority": False,
    "trade_authority": False,
    "paper_order_authority": False,
    "claim_allowed": False,
    "no_trade_flag": True,
}

HEX_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
HASH_REF_RE = re.compile(r"^(sha256:)?[0-9a-f]{64}$")
DATE8_RE = re.compile(r"^[0-9]{8}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SAFE_REF_RE = re.compile(r"^[^\x00\r\n\t]{1,512}$")
UNTRUSTED_REF_TOKENS = ("raw-model-text", "chat_history", "chat-history", "localstorage")


class PreflightPacketError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key: {key}")
        out[key] = value
    return out


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise PreflightPacketError(f"cannot read valid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise PreflightPacketError("artifact root must be a JSON object")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise PreflightPacketError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise PreflightPacketError(f"{field} must be nonempty")
    return value


def _require_safe_ref(value: Any, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    text = _require_string(value, field)
    lowered = text.casefold()
    if not SAFE_REF_RE.fullmatch(text) or any(token in lowered for token in UNTRUSTED_REF_TOKENS):
        raise PreflightPacketError(f"{field} contains unsupported characters")
    return text


def _require_hash_ref(value: Any, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    text = _require_string(value, field)
    if not HASH_REF_RE.fullmatch(text):
        raise PreflightPacketError(f"{field} must be a sha256 hash")
    return text


def _optional_bare_hash_ref(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return (_require_hash_ref(value, field) or "").removeprefix("sha256:")


def _require_bare_hash(value: Any, field: str) -> str:
    text = _require_string(value, field)
    if not HEX_HASH_RE.fullmatch(text):
        raise PreflightPacketError(f"{field} must be a bare sha256 hash")
    return text


def _require_date8(value: Any, field: str) -> str:
    text = _require_string(value, field)
    if not DATE8_RE.fullmatch(text):
        raise PreflightPacketError(f"{field} must be YYYYMMDD")
    try:
        dt.datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise PreflightPacketError(f"{field} must be a real calendar date") from exc
    return text


def _require_nonnegative_int(value: Any, field: str, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PreflightPacketError(f"{field} must be a nonnegative integer")
    return value


def _parse_aware_utc(value: str | None) -> str:
    if value is None:
        now = dt.datetime.now(dt.timezone.utc)
        return now.isoformat(timespec="seconds")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise PreflightPacketError("prepared_at_utc must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PreflightPacketError("prepared_at_utc must include a timezone")
    return parsed.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git_output(args: Sequence[str], repo_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise PreflightPacketError("git metadata is unavailable") from exc
    return completed.stdout.strip()


def _origin_main_sha(value: str | None, repo_root: Path) -> str:
    observed = _git_output(["rev-parse", "origin/main"], repo_root)
    if not SHA_RE.fullmatch(observed):
        raise PreflightPacketError("origin_main_sha must be a 40-character git sha")
    if isinstance(value, str) and value.strip():
        claimed = value.strip()
        if not SHA_RE.fullmatch(claimed):
            raise PreflightPacketError("origin_main_sha must be a 40-character git sha")
        # governance-mutation: SEMICONDUCTOR_PREFLIGHT_ORIGIN_SHA_MATCH
        if claimed != observed:
            raise PreflightPacketError("origin_main_sha does not match git rev-parse origin/main")
    return observed


def _worktree_state(value: str | None, repo_root: Path) -> tuple[str, list[str]]:
    dirty_files = [line for line in _git_output(["status", "--short"], repo_root).splitlines() if line]
    observed = "CLEAN" if not dirty_files else "DIRTY_WITH_OWNER_LIST"
    if isinstance(value, str) and value.strip():
        claimed = value.strip()
        if claimed not in {"CLEAN", "DIRTY_WITH_OWNER_LIST"}:
            raise PreflightPacketError("worktree_status must be CLEAN or DIRTY_WITH_OWNER_LIST")
        # governance-mutation: SEMICONDUCTOR_PREFLIGHT_WORKTREE_STATUS_MATCH
        if claimed != observed:
            raise PreflightPacketError("worktree_status does not match git status --short")
    return observed, dirty_files


def _artifact_hash_from_ref(ref: str, repo_root: Path) -> tuple[str | None, str | None]:
    path = Path(ref)
    if not path.is_absolute():
        path = repo_root / path
    try:
        data = path.read_bytes()
    except OSError:
        return None, "artifact ref does not point to a readable local file"
    return _sha256_bytes(data), None


def _artifact_binding(
    *,
    ref: Any,
    claimed_hash: Any,
    ref_field: str,
    hash_field: str,
    repo_root: Path,
) -> tuple[str | None, str | None, str | None]:
    safe_ref = _require_safe_ref(ref, ref_field, allow_none=True)
    claimed = _optional_bare_hash_ref(claimed_hash, hash_field)
    if safe_ref is None:
        return None, None, None
    actual, error = _artifact_hash_from_ref(safe_ref, repo_root)
    if actual is None:
        return safe_ref, None, error
    # governance-mutation: SEMICONDUCTOR_PREFLIGHT_ARTIFACT_HASH_RECOMPUTES
    if claimed is not None and claimed != actual:
        return safe_ref, f"sha256:{actual}", "artifact hash does not match readable local file"
    return safe_ref, f"sha256:{actual}", None


def _validate_source_scan(scan: Mapping[str, Any]) -> str:
    if scan.get("schema") != SOURCE_SCAN_SCHEMA:
        raise PreflightPacketError("source scan schema is unsupported")
    claimed = _require_bare_hash(scan.get("scan_hash"), "source_scan.scan_hash")
    unhashed = dict(scan)
    unhashed.pop("scan_hash", None)
    # governance-mutation: SEMICONDUCTOR_PREFLIGHT_SOURCE_SCAN_HASH
    if claimed != _hash(unhashed):
        raise PreflightPacketError("source scan hash does not recompute")
    if not isinstance(scan.get("rows"), list):
        raise PreflightPacketError("source scan rows must be a list")
    return claimed


def _daily_sources(scan: Mapping[str, Any]) -> list[str]:
    raw = scan.get("daily_sources")
    if not isinstance(raw, list) or not raw:
        raise PreflightPacketError("source scan daily_sources must be a nonempty list")
    sources: list[str] = []
    for index, value in enumerate(raw):
        sources.append(_require_string(value, f"source_scan.daily_sources[{index}]"))
    if len(set(sources)) != len(sources):
        raise PreflightPacketError("source scan daily_sources must not contain duplicates")
    return sources


def _scan_stop_conditions(
    scan: Mapping[str, Any],
    *,
    target_trade_date: str,
    repair_approval_ref: str | None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    rows = scan["rows"]
    stops: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    target_row_seen = False
    target_sources_seen: set[str] = set()
    required_daily_sources = set(_daily_sources(scan))
    status = "CLEAN"

    for raw in rows:
        if not isinstance(raw, Mapping):
            raise PreflightPacketError("source scan row must be an object")
        source_name = _require_string(raw.get("source_name"), "source_scan.rows.source_name")
        as_of = _require_date8(raw.get("as_of"), "source_scan.rows.as_of")
        state = _require_string(raw.get("state"), "source_scan.rows.state")
        item = {"source_name": source_name, "as_of": as_of, "state": state}
        states.append(item)
        if as_of == target_trade_date:
            target_row_seen = True
            target_sources_seen.add(source_name)
        if state == "REPAIR_REQUIRED":
            status = "REPAIR_REQUIRED"
            stops.append({
                "code": "SOURCE_REPAIR_REQUIRED",
                "detail": "source scan found a repair-required daily source before rerun",
                **item,
            })
        # governance-mutation: SEMICONDUCTOR_PREFLIGHT_PENDING_STOPS
        elif as_of == target_trade_date and state in {
            "SOURCE_PUBLICATION_PENDING",
            "DATA_BLOCKED",
            "STALE",
            "PIT_BLOCKED",
            "NO_ORIGINAL_BATCH",
        }:
            if status == "CLEAN":
                status = "DATA_BLOCKED"
            stops.append({
                "code": state,
                "detail": "target trade-date daily source is not clean active",
                **item,
            })
        elif state not in {"CLEAN_ACTIVE", "PIT_BLOCKED", "SOURCE_PUBLICATION_PENDING"}:
            if status == "CLEAN":
                status = "DATA_BLOCKED"
            stops.append({
                "code": "UNKNOWN_SOURCE_STATE",
                "detail": "source scan row state is not a supported preflight state",
                **item,
            })

    missing_target_sources = sorted(required_daily_sources - target_sources_seen)
    for source_name in missing_target_sources:
        # governance-mutation: SEMICONDUCTOR_PREFLIGHT_DAILY_SOURCE_TARGET_ROWS
        status = "DATA_BLOCKED" if status == "CLEAN" else status
        stops.append({
            "code": "DAILY_SOURCE_MISSING_TARGET_ROW",
            "detail": "daily source has no row for target_trade_date",
            "source_name": source_name,
            "target_trade_date": target_trade_date,
        })

    if not target_row_seen:
        status = "DATA_BLOCKED" if status == "CLEAN" else status
        stops.append({
            "code": "SOURCE_SCAN_HAS_NO_TARGET_DATE",
            "detail": "source scan has no row for target_trade_date",
            "target_trade_date": target_trade_date,
        })
    if status == "REPAIR_REQUIRED" and not repair_approval_ref:
        stops.append({
            "code": "MISSING_REPAIR_APPROVAL_REF",
            "detail": "repair-required scan needs exact Junyan approval before any apply path",
        })
    return status, stops, states


def _diagnostic_stop_conditions(diagnostic: Mapping[str, Any]) -> tuple[str, str, list[str], dict[str, int], list[dict[str, Any]]]:
    if diagnostic.get("diagnostic_schema") != DIAGNOSTIC_SCHEMA:
        raise PreflightPacketError("diagnostic schema is unsupported")
    authority = diagnostic.get("authority")
    expected = {
        "selection_owner": "Junyan",
        "production_authority": False,
        "trade_authority": False,
        "claim_allowed": False,
        "no_trade_flag": True,
    }
    if not isinstance(authority, Mapping):
        raise PreflightPacketError("diagnostic authority must be an object")
    for key, expected_value in expected.items():
        # governance-mutation: SEMICONDUCTOR_PREFLIGHT_AUTHORITY_CLOSED
        if authority.get(key) != expected_value:
            raise PreflightPacketError(f"diagnostic authority boundary changed: {key}")
    if diagnostic.get("disclaimer") != DISCLAIMER:
        raise PreflightPacketError("diagnostic disclaimer changed")

    status = _require_string(diagnostic.get("status"), "diagnostic.status")
    blockers = diagnostic.get("blockers")
    if not isinstance(blockers, list) or not all(isinstance(row, Mapping) for row in blockers):
        raise PreflightPacketError("diagnostic blockers must be a list of objects")
    blocker_codes = [
        _require_string(row.get("code"), "diagnostic.blockers.code")
        for row in blockers
    ]
    counts_raw = diagnostic.get("counts")
    if not isinstance(counts_raw, Mapping):
        raise PreflightPacketError("diagnostic counts must be an object")
    counts = {
        key: _require_nonnegative_int(counts_raw.get(key), f"diagnostic.counts.{key}") or 0
        for key in (
            "semiconductor_u2_rows",
            "semiconductor_positive_channel_rows",
            "semiconductor_red_flag_only_rows",
            "semiconductor_u3_rows",
            "semiconductor_u4_ready_rows",
        )
    }
    stops: list[dict[str, Any]] = []
    forced_stops: list[dict[str, Any]] = []
    if counts["semiconductor_u2_rows"] <= 0:
        forced_stops.append({
            "code": "EMPTY_SEMICONDUCTOR_U2_POOL",
            "detail": "diagnostic counts show no semiconductor U2 rows",
        })
    # governance-mutation: SEMICONDUCTOR_PREFLIGHT_DIAGNOSTIC_COUNTS_FORCE_STOP
    if counts["semiconductor_positive_channel_rows"] <= 0:
        forced_stops.append({
            "code": "NO_POSITIVE_CHANNEL_ROWS",
            "detail": "diagnostic counts show no positive semiconductor evidence channel rows",
        })
    if counts["semiconductor_red_flag_only_rows"] > 0:
        forced_stops.append({
            "code": "RED_FLAG_ONLY_COHORT",
            "detail": "diagnostic counts show red-flag-only rows before U4 handoff",
            "red_flag_only_rows": counts["semiconductor_red_flag_only_rows"],
        })
    if counts["semiconductor_u3_rows"] <= 0:
        forced_stops.append({
            "code": "NO_SAME_RUN_U3_BATTERY",
            "detail": "diagnostic counts show no U3 battery rows",
        })
    elif counts["semiconductor_u3_rows"] < counts["semiconductor_u2_rows"]:
        forced_stops.append({
            "code": "U3_BATTERY_INCOMPLETE",
            "detail": "diagnostic counts show some U2 rows lack same-run U3 battery rows",
            "u2_rows": counts["semiconductor_u2_rows"],
            "u3_rows": counts["semiconductor_u3_rows"],
        })
    ready_rows = counts["semiconductor_u4_ready_rows"]
    if ready_rows <= 0:
        forced_stops.append({
            "code": "EMPTY_U4_READY_POOL",
            "detail": "diagnostic counts show no U4-ready rows",
        })
    elif ready_rows < 3:
        forced_stops.append({
            "code": "U4_READY_POOL_BELOW_HUMAN_SELECTION_FLOOR",
            "detail": "diagnostic counts show one or two U4-ready rows; legal selections are 0, 3, 4, or 5",
            "u4_ready_rows": ready_rows,
        })
    if diagnostic.get("u4_ready") is not True or status != "READY_FOR_U4_PACKET":
        stops.append({
            "code": "INTAKE_DIAGNOSTIC_NOT_READY",
            "detail": "intake diagnostic did not reach READY_FOR_U4_PACKET",
            "diagnostic_status": status,
            "blocker_codes": blocker_codes,
        })
    if blocker_codes:
        stops.append({
            "code": "INTAKE_DIAGNOSTIC_HAS_BLOCKERS",
            "detail": "intake diagnostic carries explicit blockers",
            "blocker_codes": blocker_codes,
        })
    if status == "READY_FOR_U4_PACKET" and diagnostic.get("u4_ready") is True and (forced_stops or blocker_codes):
        stops.append({
            "code": "RECEIPT_SELF_REPORT_MISMATCH",
            "detail": "diagnostic self-reported READY while derived counts or blockers require a stop",
            "derived_blocker_codes": [row["code"] for row in forced_stops],
            "reported_blocker_codes": blocker_codes,
        })
    stops.extend(forced_stops)
    return status, _hash(diagnostic), blocker_codes, counts, stops


def build_packet(
    *,
    source_scan: Mapping[str, Any],
    source_scan_ref: str,
    diagnostic: Mapping[str, Any],
    diagnostic_ref: str,
    target_trade_date: str,
    prepared_by: str = "Reed",
    prepared_at_utc: str | None = None,
    origin_main_sha: str | None = None,
    worktree_status: str | None = None,
    same_day_bundle_ref: str | None = None,
    same_day_bundle_hash: str | None = None,
    same_day_as_of: str | None = None,
    same_day_run_id: str | None = None,
    u3_battery_ref: str | None = None,
    u3_battery_hash: str | None = None,
    u3_battery_as_of: str | None = None,
    u3_row_count: int | None = None,
    repair_approval_ref: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    repo = repo_root or _repo_root()
    target = _require_date8(target_trade_date, "target_trade_date")
    prepared_at = _parse_aware_utc(prepared_at_utc)
    source_hash = _validate_source_scan(source_scan)
    scan_ref = _require_safe_ref(source_scan_ref, "source_scan_ref")
    diag_ref = _require_safe_ref(diagnostic_ref, "diagnostic_ref")
    repair_ref = _require_safe_ref(repair_approval_ref, "repair_approval_ref", allow_none=True)
    resolved_worktree_status, dirty_files = _worktree_state(worktree_status, repo)
    source_status, source_stops, source_states = _scan_stop_conditions(
        source_scan, target_trade_date=target, repair_approval_ref=repair_ref
    )
    diagnostic_status, diagnostic_hash, blocker_codes, counts, diagnostic_stops = (
        _diagnostic_stop_conditions(diagnostic)
    )

    same_day_ref, same_day_hash, same_day_artifact_error = _artifact_binding(
        ref=same_day_bundle_ref,
        claimed_hash=same_day_bundle_hash,
        ref_field="same_day_bundle_ref",
        hash_field="same_day_bundle_hash",
        repo_root=repo,
    )
    same_day_date = _require_date8(same_day_as_of, "same_day_as_of") if same_day_as_of else None
    same_day_identity = _require_safe_ref(same_day_run_id, "same_day_run_id", allow_none=True)
    u3_ref, u3_hash, u3_artifact_error = _artifact_binding(
        ref=u3_battery_ref,
        claimed_hash=u3_battery_hash,
        ref_field="u3_battery_ref",
        hash_field="u3_battery_hash",
        repo_root=repo,
    )
    u3_date = _require_date8(u3_battery_as_of, "u3_battery_as_of") if u3_battery_as_of else None
    u3_count = _require_nonnegative_int(u3_row_count, "u3_row_count", allow_none=True)

    stops = [*source_stops, *diagnostic_stops]
    if resolved_worktree_status != "CLEAN":
        stops.append({
            "code": "WORKTREE_NOT_CLEAN",
            "detail": "preflight packet must be regenerated from a clean or fully-owned worktree",
            "dirty_files": dirty_files,
        })

    if same_day_ref is None or same_day_date is None or same_day_identity is None:
        stops.append({
            "code": "SAME_DAY_BUNDLE_MISSING",
            "detail": "same-day U1/U2 bundle ref, as-of date, and run identity must be bound",
        })
    elif same_day_artifact_error:
        stops.append({
            "code": "SAME_DAY_BUNDLE_UNVERIFIED",
            "detail": same_day_artifact_error,
            "ref": same_day_ref,
        })
    elif same_day_date != target:
        stops.append({
            "code": "SAME_DAY_BUNDLE_DATE_MISMATCH",
            "detail": "same-day bundle as-of date does not match target_trade_date",
            "same_day_as_of": same_day_date,
            "target_trade_date": target,
        })

    if u3_ref is None or u3_date is None or u3_count is None:
        stops.append({
            "code": "U3_BATTERY_MISSING",
            "detail": "U3 battery ref, as-of date, and row count must be bound",
        })
    elif u3_artifact_error:
        stops.append({
            "code": "U3_BATTERY_UNVERIFIED",
            "detail": u3_artifact_error,
            "ref": u3_ref,
        })
    elif u3_date != target:
        stops.append({
            "code": "U3_BATTERY_DATE_MISMATCH",
            "detail": "U3 battery as-of date does not match target_trade_date",
            "u3_battery_as_of": u3_date,
            "target_trade_date": target,
        })
    elif u3_count <= 0:
        stops.append({
            "code": "U3_BATTERY_EMPTY",
            "detail": "U3 battery row count must be positive before rerun handoff",
            "u3_row_count": u3_count,
        })

    handoff_intent = "ALLOW_U1_U3_RERUN" if not stops else "STOP_BEFORE_RERUN"
    next_action = (
        "Junyan may review the packet before any same-day U1-U3 rerun command is run."
        if handoff_intent == "ALLOW_U1_U3_RERUN"
        else "Do not run same-day U1-U3; resolve stop conditions and regenerate this packet."
    )
    origin_sha = _origin_main_sha(origin_main_sha, repo)
    packet = {
        "schema": PACKET_SCHEMA,
        "packet_id": f"semiconductor-rerun-{target}-preflight",
        "prepared_by": _require_string(prepared_by, "prepared_by"),
        "prepared_at_utc": prepared_at,
        "target_trade_date": target,
        "origin_main_sha": origin_sha,
        "worktree_status": resolved_worktree_status,
        "worktree_dirty_files": dirty_files,
        "source_scan": {
            "ref": scan_ref,
            "hash": source_hash,
            "status": source_status,
            "states": source_states,
        },
        "repair_approval_ref": repair_ref,
        "diagnostic": {
            "ref": diag_ref,
            "hash": diagnostic_hash,
            "status": diagnostic_status,
            "blocker_codes": blocker_codes,
            "counts": counts,
        },
        "same_day_bundle": {
            "ref": same_day_ref,
            "hash": same_day_hash,
            "as_of": same_day_date,
            "run_identity": same_day_identity,
        },
        "u3_battery": {
            "ref": u3_ref,
            "hash": u3_hash,
            "as_of": u3_date,
            "row_count": u3_count,
        },
        "handoff_intent": handoff_intent,
        "stop_conditions": stops,
        "next_action": next_action,
        "authority": AUTHORITY,
        "disclaimer": DISCLAIMER,
    }
    packet["packet_hash"] = _hash(packet)
    return packet


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        output.write(text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-scan", required=True, type=Path)
    parser.add_argument("--source-scan-ref")
    parser.add_argument("--diagnostic", required=True, type=Path)
    parser.add_argument("--diagnostic-ref")
    parser.add_argument("--target-trade-date", required=True)
    parser.add_argument("--prepared-by", default="Reed")
    parser.add_argument("--prepared-at-utc")
    parser.add_argument("--origin-main-sha")
    parser.add_argument("--worktree-status")
    parser.add_argument("--same-day-bundle-ref")
    parser.add_argument("--same-day-bundle-hash")
    parser.add_argument("--same-day-as-of")
    parser.add_argument("--same-day-run-id")
    parser.add_argument("--u3-battery-ref")
    parser.add_argument("--u3-battery-hash")
    parser.add_argument("--u3-battery-as-of")
    parser.add_argument("--u3-row-count", type=int)
    parser.add_argument("--repair-approval-ref")
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    packet = build_packet(
        source_scan=_load_json(args.source_scan),
        source_scan_ref=args.source_scan_ref or str(args.source_scan),
        diagnostic=_load_json(args.diagnostic),
        diagnostic_ref=args.diagnostic_ref or str(args.diagnostic),
        target_trade_date=args.target_trade_date,
        prepared_by=args.prepared_by,
        prepared_at_utc=args.prepared_at_utc,
        origin_main_sha=args.origin_main_sha,
        worktree_status=args.worktree_status,
        same_day_bundle_ref=args.same_day_bundle_ref,
        same_day_bundle_hash=args.same_day_bundle_hash,
        same_day_as_of=args.same_day_as_of,
        same_day_run_id=args.same_day_run_id,
        u3_battery_ref=args.u3_battery_ref,
        u3_battery_hash=args.u3_battery_hash,
        u3_battery_as_of=args.u3_battery_as_of,
        u3_row_count=args.u3_row_count,
        repair_approval_ref=args.repair_approval_ref,
        repo_root=args.repo_root,
    )
    _write_json(args.output, packet)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreflightPacketError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
