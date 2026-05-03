#!/usr/bin/env python3
"""
Fetch Tushare 15000-tier concept-to-stock membership mapping.

This fetcher writes one global JSON file because concept membership is a
market-wide lookup table, not watchlist-scoped ticker data. It first tries a
single bulk membership endpoint; if that is unavailable, it falls back to the
Tushare concept list plus capped per-concept detail calls.
"""

import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import tushare as ts


CURRENT_TIER = 15000
OUTPUT_PATH = Path(__file__).parent.parent / "public" / "data" / "concept_membership.json"
MAX_MEMBERS_PER_CONCEPT = 200
FETCH_DELAY = 0.2

BULK_ENDPOINTS = ["concept_detail", "concept_membership", "ths_concept_detail"]
CONCEPT_LIST_ENDPOINT = "concept"
DETAIL_ENDPOINT = "concept_detail"
MAX_FALLBACK_CONCEPTS = 100

LAST_CONCEPT_ERRORS = []

TIER_LOCK_CUES = (
    "permission",
    "access",
    "quota",
    "privilege",
    "points",
    "level",
    "tier",
    "not enough",
    "unauthorized",
    "forbidden",
    "denied",
    "no permission",
    "no access",
    "not allowed",
    "no right",
    "not open",
    "权限",
    "积分",
    "未开通",
    "请升级",
    "没有访问",
)

CONCEPT_CODE_FIELDS = (
    "_concept_code",
    "id",
    "concept_code",
    "concept_id",
    "con_code",
    "ths_code",
    "board_code",
)
CONCEPT_NAME_FIELDS = (
    "_concept_name",
    "concept_name",
    "con_name",
    "concept",
    "board_name",
)
STOCK_CODE_FIELDS = (
    "stock_ts_code",
    "stock_code",
    "ts_code",
    "symbol",
    "code",
)
STOCK_NAME_FIELDS = (
    "stock_name",
    "name",
    "short_name",
)
LIST_CODE_FIELDS = ("code", "ts_code", "id", "concept_code", "con_code")
LIST_NAME_FIELDS = ("name", "concept_name", "con_name", "concept")


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_safe(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    try:
        if value != value:
            return None
    except (TypeError, ValueError):
        pass
    return value


def _frame_to_rows(frame):
    if frame is None:
        return []
    if isinstance(frame, dict):
        data = frame.get("data", frame)
        if isinstance(data, dict) and "fields" in data and "items" in data:
            fields = data.get("fields") or []
            return [dict(zip(fields, item)) for item in data.get("items") or []]
        if isinstance(data, list):
            return data
        return [data]
    if hasattr(frame, "to_dict"):
        return frame.to_dict(orient="records")
    if isinstance(frame, list):
        return frame
    return []


def _first_value(row, fields):
    for field in fields:
        if field in row and row[field] not in (None, ""):
            return row[field]
    return None


def _normalize_stock_ts_code(value):
    value = str(_json_safe(value) or "").strip().upper()
    if value.endswith((".SZ", ".SH")):
        return value
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 6:
        suffix = ".SH" if digits.startswith(("5", "6", "9")) else ".SZ"
        return f"{digits}{suffix}"
    return None


def _normalize_text(value):
    value = _json_safe(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _call_tushare_api(api, api_name, params):
    result = api.query(api_name, **params) if hasattr(api, "query") else getattr(api, api_name)(**params)
    if result is None:
        raise RuntimeError("Tushare returned no data object")
    if isinstance(result, dict):
        code = result.get("code")
        if code not in (None, 0, "0"):
            raise RuntimeError(f"Tushare returned code={code} msg={result.get('msg')}")
    return result


def fetch_bulk_membership_rows(api):
    LAST_CONCEPT_ERRORS.clear()
    attempted = []
    for api_name in BULK_ENDPOINTS:
        attempted.append(api_name)
        try:
            print(f"concept_detail: trying bulk {api_name}", file=sys.stderr)
            rows = _frame_to_rows(_call_tushare_api(api, api_name, {}))
            print(f"concept_detail: bulk {api_name} ok rows={len(rows)}", file=sys.stderr)
            if rows:
                return api_name, rows, attempted
            LAST_CONCEPT_ERRORS.append(f"{api_name}: empty")
        except Exception as exc:
            LAST_CONCEPT_ERRORS.append(f"{api_name}: {type(exc).__name__}: {exc}")
            print(f"concept_detail: bulk {api_name} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            time.sleep(FETCH_DELAY)
    return None, [], attempted


def fetch_concept_list(api):
    try:
        print("concept_detail: trying fallback concept list", file=sys.stderr)
        rows = _frame_to_rows(_call_tushare_api(api, CONCEPT_LIST_ENDPOINT, {"src": "ts"}))
        print(f"concept_detail: concept list ok rows={len(rows)}", file=sys.stderr)
        if not rows:
            LAST_CONCEPT_ERRORS.append(f"{CONCEPT_LIST_ENDPOINT}: empty")
        return rows
    except Exception as exc:
        LAST_CONCEPT_ERRORS.append(f"{CONCEPT_LIST_ENDPOINT}: {type(exc).__name__}: {exc}")
        print(f"concept_detail: concept list failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []
    finally:
        time.sleep(FETCH_DELAY)


def _normalize_concept_list(rows):
    concepts = []
    seen = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        safe = {str(key): _json_safe(value) for key, value in raw.items()}
        concept_code = _normalize_text(_first_value(safe, LIST_CODE_FIELDS))
        concept_name = _normalize_text(_first_value(safe, LIST_NAME_FIELDS))
        if not concept_code:
            continue
        if concept_code in seen:
            continue
        seen.add(concept_code)
        concepts.append({"ts_code": concept_code, "name": concept_name})
    return concepts


def fetch_fallback_membership_rows(api):
    attempted = list(BULK_ENDPOINTS) + [CONCEPT_LIST_ENDPOINT, f"{DETAIL_ENDPOINT}(id)"]
    concept_rows = fetch_concept_list(api)
    concepts = _normalize_concept_list(concept_rows)[:MAX_FALLBACK_CONCEPTS]
    if not concepts:
        return None, [], attempted

    rows = []
    for idx, concept in enumerate(concepts, 1):
        concept_code = concept.get("ts_code")
        if not concept_code:
            continue
        try:
            print(
                f"concept_detail: fallback {idx}/{len(concepts)} {concept_code}",
                file=sys.stderr,
            )
            # Tushare names the concept code parameter `id`; concept list rows
            # expose that same value as their concept code.
            detail_rows = _frame_to_rows(_call_tushare_api(api, DETAIL_ENDPOINT, {"id": concept_code}))
            for raw in detail_rows:
                if not isinstance(raw, dict):
                    continue
                enriched = dict(raw)
                enriched.setdefault("_concept_code", concept_code)
                if concept.get("name"):
                    enriched.setdefault("_concept_name", concept["name"])
                rows.append(enriched)
        except Exception as exc:
            LAST_CONCEPT_ERRORS.append(f"{DETAIL_ENDPOINT}({concept_code}): {type(exc).__name__}: {exc}")
            print(
                f"concept_detail: fallback {concept_code} failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        finally:
            time.sleep(FETCH_DELAY)
    return "concept+concept_detail", rows, attempted


def _concept_key(row):
    concept_code = _normalize_text(_first_value(row, CONCEPT_CODE_FIELDS))
    concept_name = _normalize_text(_first_value(row, CONCEPT_NAME_FIELDS))
    if not concept_code and not concept_name:
        return None
    return concept_code or "", concept_name or ""


def _member_from_row(row):
    ts_code = _normalize_stock_ts_code(_first_value(row, STOCK_CODE_FIELDS))
    if not ts_code:
        return None
    return {
        "ts_code": ts_code,
        "name": _normalize_text(_first_value(row, STOCK_NAME_FIELDS)),
    }


def _group_concepts(rows):
    grouped = {}
    seen_members = defaultdict(set)
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        safe = {str(key): _json_safe(value) for key, value in raw.items()}
        key = _concept_key(safe)
        member = _member_from_row(safe)
        if not key or not member:
            continue
        concept_code, concept_name = key
        group = grouped.setdefault(
            key,
            {
                "name": concept_name or None,
                "ts_code": concept_code or None,
                "members": [],
            },
        )
        if member["ts_code"] in seen_members[key]:
            continue
        seen_members[key].add(member["ts_code"])
        group["members"].append(member)

    concepts = []
    for group in grouped.values():
        members = sorted(group["members"], key=lambda row: row.get("ts_code") or "")
        member_count = len(members)
        concept = {
            "name": group.get("name"),
            "ts_code": group.get("ts_code"),
            "member_count": member_count,
            "members": members[:MAX_MEMBERS_PER_CONCEPT],
        }
        if member_count > MAX_MEMBERS_PER_CONCEPT:
            concept["_truncated"] = True
        concepts.append(concept)

    return sorted(
        concepts,
        key=lambda row: (-(row.get("member_count") or 0), row.get("name") or "", row.get("ts_code") or ""),
    )


def _looks_tier_locked(error_text):
    lowered = (error_text or "").lower()
    return any(cue in lowered for cue in TIER_LOCK_CUES)


def _last_error_text():
    if not LAST_CONCEPT_ERRORS:
        return ""
    return " | ".join(LAST_CONCEPT_ERRORS[:30])


def _base_payload(status, api_used=None, attempted=None):
    return {
        "fetched_at": _iso_now(),
        "tier": CURRENT_TIER,
        "_status": status,
        "api_used": api_used,
        "_attempted_endpoints": attempted or [],
        "concepts": [],
        "total_concepts": 0,
        "total_memberships": 0,
    }


def _success_payload(api_used, attempted, rows):
    concepts = _group_concepts(rows)
    payload = _base_payload("ok", api_used=api_used, attempted=attempted)
    payload["concepts"] = concepts
    payload["total_concepts"] = len(concepts)
    payload["total_memberships"] = sum(concept["member_count"] for concept in concepts)
    return payload


def _error_payload(status, error_text, attempted=None, api_used=None):
    payload = _base_payload(status, api_used=api_used, attempted=attempted)
    if status == "tier_locked":
        payload["_need_tier"] = CURRENT_TIER
    if error_text:
        payload["_error"] = error_text
    return payload


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def fetch_concept_membership(api):
    api_used, rows, attempted = fetch_bulk_membership_rows(api)
    if api_used and rows:
        return api_used, rows, attempted

    fallback_api_used, fallback_rows, fallback_attempted = fetch_fallback_membership_rows(api)
    attempted = fallback_attempted if fallback_attempted else attempted
    if fallback_api_used and fallback_rows:
        return fallback_api_used, fallback_rows, attempted
    return fallback_api_used, [], attempted


def main():
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_concept_detail.py", file=sys.stderr)
        return 1

    try:
        api_used, rows, attempted = fetch_concept_membership(ts.pro_api(token))
        if rows:
            payload = _success_payload(api_used, attempted, rows)
            if payload["total_memberships"] == 0:
                error_text = _last_error_text() or "Fetched rows but found no usable concept-stock memberships"
                status = "tier_locked" if _looks_tier_locked(error_text) else "endpoint_unavailable"
                payload = _error_payload(status, error_text, attempted=attempted, api_used=api_used)
        else:
            error_text = _last_error_text() or "No concept membership rows returned"
            status = "tier_locked" if _looks_tier_locked(error_text) else "endpoint_unavailable"
            payload = _error_payload(status, error_text, attempted=attempted, api_used=api_used)
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        status = "tier_locked" if _looks_tier_locked(error_text) else "fetch_failed"
        payload = _error_payload(status, error_text, attempted=[])

    try:
        _write_json(OUTPUT_PATH, payload)
        print(
            "concept_detail: "
            f"status={payload['_status']} "
            f"api_used={payload.get('api_used')} "
            f"concepts={payload['total_concepts']} "
            f"memberships={payload['total_memberships']}"
        )
    except Exception as exc:
        print(f"concept_detail: write failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
