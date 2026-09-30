#!/usr/bin/env python3
"""Offline, synthetic news-flash replay. No provider, scheduler or trade authority."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


CN = timezone(timedelta(hours=8))
UTC = timezone.utc
SCHEMA = "ar.news-flash-cassette.v1"
OUTPUT_SCHEMA = "ar.news-flash-shadow.v1"
MANIFEST_SCHEMA = "ar.news-flash-shadow-manifest.v1"
MAX_ROWS = 1500  # The provider may truncate at this limit; equality is not complete coverage.
MAX_WINDOW = timedelta(minutes=15)
MAX_COLLECTION_LAG = timedelta(minutes=5)
FILES = ("source.json", "news_flash.json", "manifest.json")
AUTHORITY = {
    "formal_blocking": False,
    "u4_selection": False,
    "paper_registration": False,
    "trade_action": False,
    "production_authority": False,
}


class NewsFlashError(ValueError):
    pass


def _canonical(value):
    try:
        return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                           separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise NewsFlashError("INVALID_JSON_VALUE") from exc


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise NewsFlashError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              NewsFlashError("NONFINITE_JSON")))
    except NewsFlashError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise NewsFlashError("INVALID_JSON") from exc


def _aware(value):
    if not isinstance(value, str):
        raise NewsFlashError("TIMESTAMP_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NewsFlashError("TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NewsFlashError("TIMESTAMP_MUST_BE_AWARE")
    return parsed.astimezone(UTC)


def _published(value):
    if not isinstance(value, str):
        raise NewsFlashError("PUBLISHED_AT_INVALID")
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=CN).astimezone(UTC)
    except ValueError as exc:
        raise NewsFlashError("PUBLISHED_AT_INVALID") from exc


def _fields(value, expected, error):
    if not isinstance(value, dict) or set(value) != expected:
        raise NewsFlashError(error)


def normalize(source):
    _fields(source, {"schema", "sample_purpose", "provider", "src", "window_start",
                     "window_end", "checked_at", "source_status", "rows"},
            "CASSETTE_FIELDS_INVALID")
    if (source["schema"] != SCHEMA or source["sample_purpose"] != "WORKFLOW_DEBUG"
            or source["provider"] != "tushare.news" or source["src"] not in {
                "sina", "wallstreetcn", "10jqka", "eastmoney", "yuncaijing",
                "fenghuang", "jinrongjie", "cls", "yicai"}):
        raise NewsFlashError("CASSETTE_IDENTITY_INVALID")
    start, end, checked = (_aware(source[key]) for key in (
        "window_start", "window_end", "checked_at"))
    if not start < end or end - start > MAX_WINDOW or checked < end:
        raise NewsFlashError("WINDOW_OR_CHECK_TIME_INVALID")
    status = source["source_status"]
    rows = source["rows"]
    if status not in {"OK", "ACCESS_DENIED", "SOURCE_DOWN"} or not isinstance(rows, list):
        raise NewsFlashError("SOURCE_STATUS_INVALID")
    if len(rows) > MAX_ROWS or (status != "OK" and rows):
        raise NewsFlashError("SOURCE_ROWS_INVALID")

    events_by_id = {}
    for row in rows:
        allowed = {"datetime", "title", "content", "channels"}
        if not isinstance(row, dict) or not {"datetime", "title", "content"} <= set(row) or set(row) - allowed:
            raise NewsFlashError("ROW_FIELDS_INVALID")
        title, content = row["title"], row["content"]
        channels = row.get("channels", "")
        if (not isinstance(title, str) or not title.strip() or len(title) > 500
                or not isinstance(content, str) or not isinstance(channels, str)):
            raise NewsFlashError("ROW_TEXT_INVALID")
        published = _published(row["datetime"])
        if published < start or published > end or published > checked:
            raise NewsFlashError("ROW_OUTSIDE_FROZEN_WINDOW")
        published_iso = published.isoformat()
        identity = _hash(_canonical([source["provider"], source["src"],
                                     published_iso, title.strip()]))
        content_hash = _hash(content.encode("utf-8"))
        event = {
            "event_id": "sha256:" + identity,
            "provider": source["provider"],
            "src": source["src"],
            "published_at": published_iso,
            "cassette_checked_at": checked.isoformat(),
            "title": title.strip(),
            "content_sha256": content_hash,
            "channels": channels,
            "source_url": None,
            "citation_status": "ORIGINAL_URL_UNAVAILABLE",
            "entity_refs": [],
            "evidence_tier": "E2_UNVERIFIED",
        }
        previous = events_by_id.get(identity)
        if previous is not None and previous != event:
            raise NewsFlashError("EVENT_CONTENT_CONFLICT")
        events_by_id[identity] = event

    if status == "ACCESS_DENIED":
        result_status, reason = "DATA_BLOCKED", "ACCESS_DENIED"
    elif status == "SOURCE_DOWN":
        result_status, reason = "SOURCE_DOWN", "SOURCE_DOWN"
    elif len(rows) == MAX_ROWS:
        result_status, reason = "PARTIAL", "POSSIBLE_SOURCE_TRUNCATION"
    elif checked - end > MAX_COLLECTION_LAG:
        result_status, reason = "PARTIAL", "COLLECTION_LAG"
    elif not rows:
        result_status, reason = "EMPTY_VALID", None
    else:
        result_status, reason = "OK", None
    return {
        "schema": OUTPUT_SCHEMA,
        "sample_purpose": "WORKFLOW_DEBUG",
        "source_authenticity": "UNVERIFIED_CASSETTE",
        "licensed_team_display": False,
        "status": result_status,
        "reason": reason,
        "provider": source["provider"],
        "src": source["src"],
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "checked_at": checked.isoformat(),
        "collection_lag_seconds": int((checked - end).total_seconds()),
        "input_sha256": _hash(_canonical(source)),
        "source_row_count": len(rows),
        "deduplicated_count": len(events_by_id),
        "events": sorted(events_by_id.values(), key=lambda event: event["event_id"]),
        "authority": dict(AUTHORITY),
    }


def _write_once(directory_fd, name, raw):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def capture(source, output_dir, *, sandbox_root):
    if os.environ.get("AR_OFFLINE") != "1":
        raise NewsFlashError("OFFLINE_ONLY")
    root_path = Path(sandbox_root).expanduser()
    if root_path.is_symlink() or not root_path.is_dir():
        raise NewsFlashError("SANDBOX_ROOT_INVALID")
    root = root_path.resolve(strict=True)
    output = Path(output_dir)
    if (".." in output.parts or output.parent.is_symlink()
            or output.parent.resolve(strict=True) != root
            or output.is_symlink() or output.exists()):
        raise NewsFlashError("OUTPUT_MUST_BE_NEW_LOCAL_DIRECTORY")
    result = normalize(source)
    source_raw, result_raw = _canonical(source), _canonical(result)
    manifest = {"schema": MANIFEST_SCHEMA, "sample_purpose": "WORKFLOW_DEBUG",
                "source_sha256": _hash(source_raw), "news_flash_sha256": _hash(result_raw),
                "status": result["status"], "authority": dict(AUTHORITY)}
    root_fd = os.open(root_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        root_stat = os.fstat(root_fd)
        os.mkdir(output.name, dir_fd=root_fd)
        batch_fd = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                           dir_fd=root_fd)
        try:
            _write_once(batch_fd, "source.json", source_raw)
            _write_once(batch_fd, "news_flash.json", result_raw)
            _write_once(batch_fd, "manifest.json", _canonical(manifest))
            os.fsync(batch_fd)
        finally:
            os.close(batch_fd)
        current = os.stat(root_path, follow_symlinks=False)
        if (not stat.S_ISDIR(current.st_mode) or
                (current.st_dev, current.st_ino) != (root_stat.st_dev, root_stat.st_ino)):
            raise NewsFlashError("SANDBOX_ROOT_REBOUND")
    finally:
        os.close(root_fd)
    return manifest


def verify(output_dir):
    directory = Path(output_dir)
    if directory.is_symlink() or not directory.is_dir() or {
            path.name for path in directory.iterdir()} != set(FILES):
        raise NewsFlashError("BATCH_FILES_INVALID")
    for name in FILES:
        if (directory / name).is_symlink() or not (directory / name).is_file():
            raise NewsFlashError("BATCH_FILES_INVALID")
    source_raw = (directory / "source.json").read_bytes()
    result_raw = (directory / "news_flash.json").read_bytes()
    manifest_raw = (directory / "manifest.json").read_bytes()
    source, result, manifest = map(_strict_json, (source_raw, result_raw, manifest_raw))
    expected = normalize(source)
    expected_manifest = {
        "schema": MANIFEST_SCHEMA, "sample_purpose": "WORKFLOW_DEBUG",
        "source_sha256": _hash(source_raw), "news_flash_sha256": _hash(result_raw),
        "status": expected["status"], "authority": dict(AUTHORITY),
    }
    if (_canonical(source) != source_raw or _canonical(result) != result_raw
            or _canonical(manifest) != manifest_raw or result != expected
            or manifest != expected_manifest):
        raise NewsFlashError("BATCH_BINDING_INVALID")
    return {"ok": True, "status": result["status"],
            "manifest_sha256": _hash(manifest_raw), "events": len(result["events"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "verify"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--sandbox-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.mode == "capture":
            if args.input is None or args.sandbox_root is None:
                raise NewsFlashError("INPUT_AND_SANDBOX_ROOT_REQUIRED")
            receipt = capture(_strict_json(args.input.read_bytes()), args.output_dir,
                              sandbox_root=args.sandbox_root)
        else:
            receipt = verify(args.output_dir)
    except (NewsFlashError, OSError) as exc:
        print(f"NEWS_FLASH_SHADOW_REFUSED: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
