#!/usr/bin/env python3
"""Per-announcement feed sidecar for the candidate battery (contract L, v0.1).

The 消息面 dimension reads the bounded 30-day announcement window for every
candidate and then keeps only counts and three truncated titles. This module
turns the rows it already read into addressable items so a human can later
label them (research_increment_label.py). It never calls a network or a model.

Boundaries
----------
* The sidecar is written through the battery stage's ``_write_stage`` files, so
  ``stage_battery.json`` hashes it. It is NOT part of ``_final_bundle_files()``,
  ``bundle_hash`` or ``funnel_health.battery_coverage``.
* A ticker whose announcement source was unavailable, or whose row was never
  collected, is ``DATA_BLOCKED`` with ``item_count = None`` -- never 0 items.
* ``eligibility`` compares the date-only ``notice_date`` against ``as_of``.
  The source carries no publication time, so ``same_day_as_as_of`` flags items
  that may have been published after the close of the ``as_of`` session.
* Nothing here enters U3 readiness, U4 selection, sizing or execution.

不是买卖指令；研究信号，human executes。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

FEED_FILE = "announcement_feed.json"
SCHEMA = "ar.announcement_feed"
SCHEMA_VERSION = "0.1"
SOURCE_CHANNELS = ("EASTMONEY_ANN_A", "TUSHARE_ANNS_D")
ELIGIBILITY = ("AT_OR_BEFORE_AS_OF", "AFTER_AS_OF_EXCLUDED", "DATE_UNVERIFIABLE")
PER_TICKER_STATUS = ("OK", "DATA_BLOCKED")
BLOCKED_DIMENSION_STATUS = ("DATA_BLOCKED", "NOT_RUN")
NEWS_DIMENSION = "消息面"
ROW_KEYS = {
    "item_id", "ts_code", "source_channel", "notice_date", "title", "captured_at",
    "eligibility", "same_day_as_as_of",
}
PER_TICKER_KEYS = {"ts_code", "status", "err", "item_count"}
FEED_KEYS = {
    "schema", "schema_version", "as_of", "run_id", "generated_at", "manifest_hash",
    "battery_rows_hash", "rows", "per_ticker", "rows_hash", "authority", "disclaimer",
}
AUTHORITY = {"claim_allowed": False, "gate_authority": False, "no_trade_flag": True}
DISCLAIMER = "不是买卖指令；研究信号，human executes。"
CAPTURE_KEYS = {"ts_code", "source_channel", "items", "status", "err", "captured_at"}


class AnnouncementFeedError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _hash(value: Any) -> str:
    """Same canonical hash as funnel_pipeline._hash (bare hex)."""
    return hashlib.sha256(_canonical(value)).hexdigest()


def item_id(ts_code: str, source_channel: str, notice_date: str, title_full: str) -> str:
    """Content identity of one announcement: no title, no identity."""
    # governance-mutation: ANNOUNCEMENT_ITEM_IDENTITY_BINDS_TITLE
    identity = {"ts_code": ts_code, "source_channel": source_channel,
                "notice_date": notice_date, "title_full": title_full}
    return "sha256:" + _hash(identity)


def _as_of_date(as_of: str) -> _dt.date:
    try:
        return _dt.datetime.strptime(str(as_of), "%Y%m%d").date()
    except ValueError as exc:
        raise AnnouncementFeedError(f"as_of must be YYYYMMDD: {as_of!r}") from exc


def normalize_notice_date(raw: Any) -> tuple[str, _dt.date | None]:
    """Return (display date, parsed date|None). Unparseable dates stay verbatim."""
    text = str(raw if raw is not None else "").strip()
    compact = text[:10].replace("-", "")
    try:
        parsed = _dt.datetime.strptime(compact, "%Y%m%d").date()
    except ValueError:
        return text, None
    return parsed.isoformat(), parsed


def classify(notice_date: _dt.date | None, as_of: str) -> tuple[str, bool]:
    cutoff = _as_of_date(as_of)
    if notice_date is None:
        return "DATE_UNVERIFIABLE", False
    # governance-mutation: ANNOUNCEMENT_FEED_AFTER_AS_OF_EXCLUDED
    if notice_date > cutoff:
        return "AFTER_AS_OF_EXCLUDED", False
    return "AT_OR_BEFORE_AS_OF", notice_date == cutoff


def _news_blocked(row: Mapping[str, Any] | None) -> bool:
    dims = (row or {}).get("dims") if isinstance(row, Mapping) else None
    news = dims.get(NEWS_DIMENSION) if isinstance(dims, Mapping) else None
    return not isinstance(news, Mapping) or news.get("status") in BLOCKED_DIMENSION_STATUS


def _rows_from_capture(capture: Mapping[str, Any], as_of: str) -> list[dict[str, Any]]:
    channel = capture.get("source_channel")
    items = capture.get("items")
    if channel is None or items is None:
        return []
    if channel not in SOURCE_CHANNELS or not isinstance(items, list):
        raise AnnouncementFeedError("announcement capture has an unknown channel or item list")
    rows: dict[str, dict[str, Any]] = {}
    for item in items:
        if (not isinstance(item, (list, tuple)) or len(item) != 2
                or not all(isinstance(part, str) for part in item)):
            raise AnnouncementFeedError("announcement capture item must be [date, title]")
        notice_date, parsed = normalize_notice_date(item[0])
        eligibility, same_day = classify(parsed, as_of)
        identity = item_id(capture["ts_code"], channel, notice_date, item[1])
        # The same (date, title) listed twice is one announcement.
        rows.setdefault(identity, {
            "item_id": identity,
            "ts_code": capture["ts_code"],
            "source_channel": channel,
            "notice_date": notice_date,
            "title": item[1],
            "captured_at": capture["captured_at"],
            "eligibility": eligibility,
            "same_day_as_as_of": same_day,
        })
    return list(rows.values())


def build_feed(
    *, as_of: str, run_id: str, generated_at: str, manifest: Mapping[str, Any],
    battery: Mapping[str, Any], captures: Mapping[str, Mapping[str, Any] | None],
    not_collected: Mapping[str, str],
) -> dict[str, Any]:
    """Assemble the sidecar from per-ticker worker captures.

    ``captures`` maps ts_code → capture record returned by the funnel worker
    (absent when the worker produced none). ``not_collected`` maps ts_code →
    reason for rows that were never collected (timeouts, no provider).
    """
    codes = list(manifest["ts_codes"])
    rows_by_code = {row.get("ts_code"): row for row in battery.get("results", [])}
    rows: list[dict[str, Any]] = []
    per_ticker: list[dict[str, Any]] = []
    for code in codes:
        capture = captures.get(code)
        if code in not_collected:
            per_ticker.append({"ts_code": code, "status": "DATA_BLOCKED",
                               "err": ("ROW_NOT_COLLECTED:" + str(not_collected[code]))[:120],
                               "item_count": None})
            continue
        if not isinstance(capture, Mapping) or set(capture) != CAPTURE_KEYS \
                or capture.get("ts_code") != code:
            per_ticker.append({"ts_code": code, "status": "DATA_BLOCKED",
                               "err": "ANNOUNCEMENT_CAPTURE_MISSING", "item_count": None})
            continue
        try:
            ticker_rows = _rows_from_capture(capture, as_of)
        except AnnouncementFeedError:
            per_ticker.append({"ts_code": code, "status": "DATA_BLOCKED",
                               "err": "ANNOUNCEMENT_CAPTURE_INVALID", "item_count": None})
            continue
        rows.extend(ticker_rows)
        # governance-mutation: ANNOUNCEMENT_FEED_BLOCKED_COUNT_NULL
        blocked = capture.get("status") != "OK" or _news_blocked(rows_by_code.get(code))
        per_ticker.append({
            "ts_code": code,
            "status": "DATA_BLOCKED" if blocked else "OK",
            "err": (str(capture.get("err") or "NEWS_DIMENSION_BLOCKED")[:120] if blocked else None),
            "item_count": None if blocked else len(ticker_rows),
        })
    order = {code: index for index, code in enumerate(codes)}
    rows.sort(key=lambda row: (order[row["ts_code"]], row["notice_date"], row["item_id"]))
    feed = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "run_id": run_id,
        "generated_at": generated_at,
        "manifest_hash": manifest["manifest_hash"],
        "battery_rows_hash": battery["rows_hash"],
        "rows": rows,
        "per_ticker": per_ticker,
        "rows_hash": _hash(rows),
        "authority": dict(AUTHORITY),
        "disclaimer": DISCLAIMER,
    }
    validate_feed(feed, manifest, battery)
    return feed


def validate_feed(
    feed: Mapping[str, Any], manifest: Mapping[str, Any], battery: Mapping[str, Any],
) -> dict[str, Any]:
    """Fail closed unless the sidecar is self-consistent and bound to this run."""
    if not isinstance(feed, Mapping) or set(feed) != FEED_KEYS:
        raise AnnouncementFeedError("announcement feed keys differ from contract v0.1")
    if feed.get("schema") != SCHEMA or feed.get("schema_version") != SCHEMA_VERSION:
        raise AnnouncementFeedError("announcement feed schema mismatch")
    if feed.get("authority") != AUTHORITY or feed.get("disclaimer") != DISCLAIMER:
        raise AnnouncementFeedError("announcement feed authority changed")
    # governance-mutation: ANNOUNCEMENT_FEED_RUN_BINDING
    if (feed.get("manifest_hash") != manifest.get("manifest_hash")
            or feed.get("battery_rows_hash") != battery.get("rows_hash")
            or feed.get("as_of") != battery.get("as_of")
            or feed.get("run_id") != battery.get("run_id")):
        raise AnnouncementFeedError("announcement feed is bound to another manifest, battery or run")
    rows = feed.get("rows")
    per_ticker = feed.get("per_ticker")
    if not isinstance(rows, list) or not isinstance(per_ticker, list):
        raise AnnouncementFeedError("announcement feed rows/per_ticker must be lists")
    # governance-mutation: ANNOUNCEMENT_FEED_ROWS_HASH
    if feed.get("rows_hash") != _hash(rows):
        raise AnnouncementFeedError("announcement feed rows_hash mismatch")
    codes = list(manifest.get("ts_codes") or [])
    if [entry.get("ts_code") if isinstance(entry, Mapping) else None
            for entry in per_ticker] != codes:
        raise AnnouncementFeedError("announcement feed per_ticker differs from the candidate manifest")
    battery_rows = {row.get("ts_code"): row for row in battery.get("results", [])
                    if isinstance(row, Mapping)}
    counts: dict[str, int] = {}
    seen: set[str] = set()
    as_of = str(feed["as_of"])
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != ROW_KEYS:
            raise AnnouncementFeedError("announcement feed row keys differ from contract v0.1")
        if row["ts_code"] not in battery_rows or row["source_channel"] not in SOURCE_CHANNELS:
            raise AnnouncementFeedError("announcement feed row has an unknown ticker or channel")
        if (not isinstance(row["title"], str) or not isinstance(row["notice_date"], str)
                or not isinstance(row["captured_at"], str)):
            raise AnnouncementFeedError("announcement feed row date/title/captured_at must be text")
        if row["item_id"] != item_id(row["ts_code"], row["source_channel"],
                                     row["notice_date"], row["title"]):
            raise AnnouncementFeedError("announcement feed item_id does not bind its content")
        if row["item_id"] in seen:
            raise AnnouncementFeedError("announcement feed repeats an item_id")
        seen.add(row["item_id"])
        _date_text, parsed = normalize_notice_date(row["notice_date"])
        eligibility, same_day = classify(parsed, as_of)
        if row["eligibility"] != eligibility or row["same_day_as_as_of"] is not same_day:
            raise AnnouncementFeedError("announcement feed eligibility is not recomputable")
        counts[row["ts_code"]] = counts.get(row["ts_code"], 0) + 1
    ok = blocked = 0
    for entry in per_ticker:
        if set(entry) != PER_TICKER_KEYS or entry.get("status") not in PER_TICKER_STATUS:
            raise AnnouncementFeedError("announcement feed per_ticker entry is invalid")
        code = entry["ts_code"]
        if entry["status"] == "OK":
            if (_news_blocked(battery_rows.get(code)) or entry.get("err") is not None
                    or type(entry.get("item_count")) is not int
                    or entry["item_count"] != counts.get(code, 0)):
                raise AnnouncementFeedError(f"announcement feed claims OK without evidence: {code}")
            ok += 1
        else:
            if entry.get("item_count") is not None or not entry.get("err"):
                raise AnnouncementFeedError(f"DATA_BLOCKED ticker must carry err and a null count: {code}")
            blocked += 1
    return {"rows": len(rows), "tickers_ok": ok, "tickers_blocked": blocked}


def verify_bundle_sidecar(bundle_dir: Path, payloads: Mapping[str, Any]) -> dict[str, Any] | None:
    """Verify the sidecar of one persistent bundle; old bundles without it skip.

    The battery stage manifest is the authority: a sidecar it lists must exist
    with the recorded digest, and a sidecar it does not list must not exist.
    """
    feed_path = Path(bundle_dir) / FEED_FILE
    stage_path = Path(bundle_dir) / "stage_battery.json"
    stage = json.loads(stage_path.read_text(encoding="utf-8")) if stage_path.is_file() else {}
    listed = FEED_FILE in (stage.get("artifacts") or {})
    present = feed_path.is_file() or feed_path.is_symlink()
    if not listed and not present:
        return None
    # governance-mutation: ANNOUNCEMENT_FEED_STAGE_LISTED
    if not listed or not present or feed_path.is_symlink():
        raise AnnouncementFeedError("announcement feed and battery stage manifest disagree")
    raw = feed_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != (stage.get("artifacts") or {}).get(FEED_FILE):
        raise AnnouncementFeedError("announcement feed bytes differ from the battery stage digest")
    if "candidate_battery.json" not in payloads or "candidate_manifest.json" not in payloads:
        raise AnnouncementFeedError("announcement feed present without DAG battery evidence")
    feed = json.loads(raw.decode("utf-8"))
    if feed.get("generated_at") != stage.get("generated_at"):
        raise AnnouncementFeedError("announcement feed was not written by this battery stage")
    return validate_feed(feed, payloads["candidate_manifest.json"], payloads["candidate_battery.json"])


def load_bundle_feed(bundle_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Read (feed, candidate_manifest, candidate_battery) from one bundle, verified."""
    bundle_dir = Path(bundle_dir)
    stage_path = bundle_dir / "stage_battery.json"
    if not stage_path.is_file():
        raise AnnouncementFeedError("bundle has no battery stage manifest")
    stage = json.loads(stage_path.read_text(encoding="utf-8"))
    payloads: dict[str, Any] = {}
    for name in ("candidate_manifest.json", "candidate_battery.json"):
        path = bundle_dir / name
        if not path.is_file() or path.is_symlink():
            raise AnnouncementFeedError(f"bundle is missing {name}")
        payloads[name] = json.loads(path.read_text(encoding="utf-8"))
    battery_digest = (stage.get("artifacts") or {}).get("candidate_battery.json")
    if battery_digest != hashlib.sha256((bundle_dir / "candidate_battery.json").read_bytes()).hexdigest():
        raise AnnouncementFeedError("candidate_battery.json differs from its stage digest")
    if (stage.get("binds") or {}).get("candidate_manifest_hash") != \
            payloads["candidate_manifest.json"].get("manifest_hash"):
        raise AnnouncementFeedError("candidate manifest differs from the battery stage binding")
    summary = verify_bundle_sidecar(bundle_dir, payloads)
    if summary is None:
        raise AnnouncementFeedError("bundle predates the announcement feed (no sidecar)")
    feed = json.loads((bundle_dir / FEED_FILE).read_text(encoding="utf-8"))
    return feed, payloads["candidate_manifest.json"], payloads["candidate_battery.json"]
