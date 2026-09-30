#!/usr/bin/env python3
"""Opt-in GDELT metadata index for a nonproduction, read-only workbench."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


SCHEMA = "ar.gdelt-news-index.v2"
PROVIDER = "gdelt.gal.rss.v1"
ATTRIBUTION = "https://www.gdeltproject.org/"
ENDPOINT = "https://data.gdeltproject.org/gdeltv3/gal/feed.rss"
MAX_RESPONSE = 2 * 1024 * 1024
MAX_FEED_RESPONSE = 8 * 1024 * 1024
MAX_FEED_ITEMS = 50000
MAX_RECORDS = 250
MAX_EVENTS = 1000
UTC = timezone.utc
AUTHORITY = {"formal_blocking": False, "u4_selection": False,
             "paper_registration": False, "trade_action": False,
             "production_authority": False}


class IndexError(ValueError):
    pass


class SourceFailure(Exception):
    def __init__(self, code, reason=None):
        if code not in {"ACCESS_DENIED", "SOURCE_DOWN", "BAD_PROVIDER_PAYLOAD", "STALE_SOURCE"}:
            code = "SOURCE_DOWN"
        super().__init__(code)
        self.code = code
        self.reason = reason or code


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise IndexError("INVALID_JSON_VALUE") from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise IndexError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              IndexError("NONFINITE_JSON")))
    except IndexError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise IndexError("INVALID_JSON") from exc


def _time(value):
    if not isinstance(value, str):
        raise IndexError("TIME_INVALID")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IndexError("TIME_INVALID") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise IndexError("TIME_MUST_BE_AWARE")
    return result.astimezone(UTC)


def _query(query_id, query):
    if not isinstance(query_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{2,39}", query_id):
        raise IndexError("QUERY_ID_INVALID")
    if (not isinstance(query, str) or not 2 <= len(query) <= 160
            or any(ord(char) < 32 for char in query)):
        raise IndexError("QUERY_INVALID")
    terms = [term.strip().casefold() for term in query.split(",")]
    if not terms or any(not 2 <= len(term) <= 40 for term in terms) or len(set(terms)) != len(terms):
        raise IndexError("QUERY_TERMS_INVALID")
    return terms


def _article(row):
    if not isinstance(row, dict) or not {"url", "title", "seendate", "article_date_or_seen"} <= set(row):
        raise IndexError("ARTICLE_FIELDS_INVALID")
    url, title = row["url"], row["title"]
    if not isinstance(url, str) or len(url) > 2048:
        raise IndexError("ARTICLE_URL_INVALID")
    try:
        parsed = urllib.parse.urlsplit(url)
        valid_url = (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                     and not parsed.username and not parsed.password and parsed.port is None)
    except ValueError as exc:
        raise IndexError("ARTICLE_URL_INVALID") from exc
    if not valid_url:
        raise IndexError("ARTICLE_URL_INVALID")
    if not isinstance(title, str) or not title.strip() or len(title) > 500:
        raise IndexError("ARTICLE_TITLE_INVALID")
    try:
        indexed = datetime.strptime(row["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError) as exc:
        raise IndexError("ARTICLE_INDEX_TIME_INVALID") from exc
    fields = {}
    for key in ("domain", "language", "sourcecountry"):
        value = row.get(key, "")
        if not isinstance(value, str) or len(value) > 120:
            raise IndexError("ARTICLE_METADATA_INVALID")
        fields[key] = value
    article_date = _time(row["article_date_or_seen"]).isoformat()
    return {"event_id": "sha256:" + hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "url": url, "title": title.strip(), "indexed_at": indexed.isoformat(),
            "article_date_or_seen": article_date,
            **fields, "evidence_tier": "E3_UNVERIFIED_NEWS_INDEX",
            "original_article_verified": False}


def _feed(raw, modified_at, terms):
    if not isinstance(raw, bytes) or len(raw) > MAX_FEED_RESPONSE:
        raise SourceFailure("BAD_PROVIDER_PAYLOAD", "FEED_SIZE_INVALID")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise SourceFailure("BAD_PROVIDER_PAYLOAD", "XML_ENTITY_FORBIDDEN")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SourceFailure("BAD_PROVIDER_PAYLOAD", "XML_PARSE_INVALID") from exc
    if root.tag != "rss" or root.find("channel") is None:
        raise SourceFailure("BAD_PROVIDER_PAYLOAD", "RSS_SHAPE_INVALID")
    items = root.findall("./channel/item")
    if len(items) > MAX_FEED_ITEMS:
        raise SourceFailure("BAD_PROVIDER_PAYLOAD", "FEED_ITEM_LIMIT")
    indexed = _time(modified_at).strftime("%Y%m%dT%H%M%SZ")
    matched, missing = [], 0
    for item in items:
        title, url, pub_date = (item.findtext(key) for key in ("title", "link", "pubDate"))
        if not title or not url or not pub_date:
            missing += 1
            continue
        if not any(term in title.casefold() for term in terms):
            continue
        try:
            article_date = parsedate_to_datetime(pub_date)
            if article_date.tzinfo is None:
                raise ValueError("naive RSS date")
            event = _article({"url": url, "title": title, "seendate": indexed,
                              "article_date_or_seen": article_date.isoformat(),
                              "domain": urllib.parse.urlsplit(url).hostname or ""})
        except (ValueError, TypeError, IndexError) as exc:
            raise SourceFailure("BAD_PROVIDER_PAYLOAD", "MATCHED_ITEM_INVALID") from exc
        matched.append(event)
    return matched, len(items), missing


def _seal(value):
    return {**value, "snapshot_hash": digest(value)}


def validate_snapshot(value):
    fields = {"schema", "sample_purpose", "provider", "attribution_url", "content_scope",
              "latency_class", "query_id", "query", "status", "reason", "last_attempt",
              "last_good_end", "cursor_end", "events", "new_count", "authority", "snapshot_hash",
              "feed_item_count", "matched_count", "missing_metadata_count", "gap_status"}
    if not isinstance(value, dict) or set(value) != fields:
        raise IndexError("SNAPSHOT_FIELDS_INVALID")
    if value["snapshot_hash"] != digest({key: item for key, item in value.items() if key != "snapshot_hash"}):
        raise IndexError("SNAPSHOT_HASH_INVALID")
    if (value["schema"] != SCHEMA or value["sample_purpose"] != "WORKFLOW_DEBUG"
            or value["provider"] != PROVIDER or value["attribution_url"] != ATTRIBUTION
            or value["content_scope"] != "METADATA_ONLY"
            or value["latency_class"] != "RSS_INDEX_NOT_FLASH"
            or value["authority"] != AUTHORITY):
        raise IndexError("SNAPSHOT_AUTHORITY_OR_LICENSE_INVALID")
    _query(value["query_id"], value["query"])
    if value["status"] not in {"OK", "OK_NO_CHANGE", "EMPTY_VALID", "PARTIAL_METADATA",
                                "SOURCE_DELAYED",
                                "SOURCE_DOWN", "ACCESS_DENIED", "BAD_PROVIDER_PAYLOAD",
                                "STALE_SOURCE", "PARTIAL_TRUNCATED"}:
        raise IndexError("SNAPSHOT_STATUS_INVALID")
    attempt = value["last_attempt"]
    if (not isinstance(attempt, dict) or
            set(attempt) != {"at", "feed_modified_at", "query_id", "status"}
            or attempt["query_id"] != value["query_id"] or attempt["status"] != value["status"]):
        raise IndexError("SNAPSHOT_ATTEMPT_INVALID")
    _time(attempt["at"])
    if attempt["feed_modified_at"] is not None:
        _time(attempt["feed_modified_at"])
    if value["reason"] is not None and not isinstance(value["reason"], str):
        raise IndexError("SNAPSHOT_REASON_INVALID")
    if (value["cursor_end"] is None) != (value["last_good_end"] is None):
        raise IndexError("SNAPSHOT_CURSOR_INVALID")
    if (value["cursor_end"] is not None and
            (value["last_good_end"] != value["cursor_end"] or
             _time(value["cursor_end"]) > _time(attempt["at"]))):
        raise IndexError("SNAPSHOT_CURSOR_INVALID")
    if (not isinstance(value["events"], list) or len(value["events"]) > MAX_EVENTS
            or type(value["new_count"]) is not int or value["new_count"] < 0):
        raise IndexError("SNAPSHOT_EVENTS_INVALID")
    for key in ("feed_item_count", "matched_count", "missing_metadata_count"):
        if type(value[key]) is not int or value[key] < 0:
            raise IndexError("SNAPSHOT_COUNTS_INVALID")
    if value["gap_status"] not in {"UNOBSERVED_BEFORE_START", "NO_GAP_OBSERVED",
                                   "POSSIBLE_15M_FEED_GAP"}:
        raise IndexError("SNAPSHOT_GAP_INVALID")
    seen = set()
    for event in value["events"]:
        if not isinstance(event, dict) or set(event) != {"event_id", "url", "title", "indexed_at", "article_date_or_seen",
                                                   "domain", "language", "sourcecountry",
                                                   "evidence_tier", "original_article_verified"}:
            raise IndexError("SNAPSHOT_EVENTS_INVALID")
        expected = _article({"url": event["url"], "title": event["title"],
                             "seendate": _time(event["indexed_at"]).strftime("%Y%m%dT%H%M%SZ"),
                             "article_date_or_seen": event["article_date_or_seen"],
                             "domain": event["domain"], "language": event["language"],
                             "sourcecountry": event["sourcecountry"]})
        if event != expected or event["event_id"] in seen:
            raise IndexError("SNAPSHOT_EVENTS_INVALID")
        seen.add(event["event_id"])
    return value


def _read_fd(directory_fd, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RESPONSE:
            raise IndexError("SNAPSHOT_FILE_INVALID")
        raw = stream.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise IndexError("SNAPSHOT_FILE_INVALID")
        return raw


def _state_fd(root, create=False):
    root = Path(root)
    if (root.is_symlink() or not root.is_dir() or "ar-live" in root.parts
            or "ar-live" in root.resolve(strict=True).parts):
        raise IndexError("NONPRODUCTION_ROOT_REQUIRED")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if create:
            try:
                os.mkdir("gdelt-news", 0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
        return os.open("gdelt-news", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                       dir_fd=root_fd)
    finally:
        os.close(root_fd)


def read_snapshot(root):
    fd = _state_fd(root)
    try:
        return validate_snapshot(_parse(_read_fd(fd, "current.json")))
    finally:
        os.close(fd)


def _write_atomic(directory_fd, name, value):
    raw = canonical(value) + b"\n"
    temporary = "." + name + "." + os.urandom(8).hex()
    file_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                      0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(file_fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _base(query_id, query):
    return {"schema": SCHEMA, "sample_purpose": "WORKFLOW_DEBUG", "provider": PROVIDER,
            "attribution_url": ATTRIBUTION, "content_scope": "METADATA_ONLY",
            "latency_class": "RSS_INDEX_NOT_FLASH", "query_id": query_id,
            "query": query, "status": "EMPTY_VALID", "reason": None, "last_attempt": None,
            "last_good_end": None, "cursor_end": None, "events": [], "new_count": 0,
            "feed_item_count": 0, "matched_count": 0, "missing_metadata_count": 0,
            "gap_status": "UNOBSERVED_BEFORE_START",
            "authority": dict(AUTHORITY)}


def poll_once(root, *, query_id, query, now, fetch):
    terms = _query(query_id, query)
    now_dt = _time(now)
    fd = _state_fd(root, create=True)
    try:
        lock = os.open(".poll.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                       0o600, dir_fd=fd)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(lock)
            raise IndexError("POLL_LOCK_BUSY") from exc
        try:
            try:
                state = validate_snapshot(_parse(_read_fd(fd, "current.json")))
                if state["query_id"] != query_id or state["query"] != query:
                    raise IndexError("QUERY_IDENTITY_CHANGED")
            except FileNotFoundError:
                state = _seal(_base(query_id, query))
            cursor = _time(state["cursor_end"]) if state["cursor_end"] else None
            attempt = {"at": now_dt.isoformat(), "feed_modified_at": None, "query_id": query_id}
            result = {key: item for key, item in state.items() if key != "snapshot_hash"}
            result["new_count"] = 0
            try:
                response = fetch()
                if not isinstance(response, dict) or not isinstance(response.get("raw"), bytes):
                    raise SourceFailure("BAD_PROVIDER_PAYLOAD", "FEED_RESPONSE_INVALID")
                modified = _time(response.get("feed_modified_at"))
                attempt["feed_modified_at"] = modified.isoformat()
                if modified > now_dt + timedelta(minutes=1) or now_dt - modified > timedelta(minutes=30):
                    raise SourceFailure("STALE_SOURCE", "FEED_MODIFIED_OUTSIDE_FRESHNESS")
                delayed = now_dt - modified > timedelta(minutes=10)
                if cursor and modified < cursor:
                    raise SourceFailure("STALE_SOURCE", "FEED_MOVED_BACKWARDS")
                if cursor and modified == cursor:
                    result.update(status="SOURCE_DELAYED" if delayed else "OK_NO_CHANGE",
                                  reason="FEED_AGE_GT_10M" if delayed else None)
                else:
                    rows, total, missing = _feed(response["raw"], modified.isoformat(), terms)
                    result.update(feed_item_count=total, matched_count=len(rows),
                                  missing_metadata_count=missing)
                    if len(rows) >= MAX_RECORDS:
                        result.update(status="PARTIAL_TRUNCATED", reason="MATCHED_RESULT_LIMIT")
                    else:
                        recent = [event for event in result["events"]
                                  if _time(event["indexed_at"]) >= now_dt - timedelta(days=2)]
                        by_id = {event["event_id"]: event for event in recent}
                        for event in rows:
                            previous = by_id.get(event["event_id"])
                            if previous is not None and any(previous[key] != event[key]
                                                            for key in ("url", "title", "article_date_or_seen")):
                                raise IndexError("EVENT_ID_CONFLICT")
                            by_id[event["event_id"]] = event
                        if len(by_id) > MAX_EVENTS:
                            result.update(status="PARTIAL_TRUNCATED", reason="LOCAL_EVENT_LIMIT")
                        else:
                            result["new_count"] = len(by_id) - len(recent)
                            result["events"] = sorted(by_id.values(), key=lambda event:
                                                      (event["indexed_at"], event["event_id"]), reverse=True)
                            result.update(status="SOURCE_DELAYED" if delayed else "PARTIAL_METADATA" if missing
                                          else "OK" if rows else "EMPTY_VALID",
                                          reason="FEED_AGE_GT_10M" if delayed else
                                          "RSS_ITEMS_MISSING_FIELDS" if missing else None,
                                          cursor_end=modified.isoformat(), last_good_end=modified.isoformat(),
                                          gap_status="POSSIBLE_15M_FEED_GAP" if cursor and modified - cursor > timedelta(minutes=15)
                                          else "NO_GAP_OBSERVED" if cursor else "UNOBSERVED_BEFORE_START")
            except SourceFailure as exc:
                result.update(status=exc.code, reason=exc.reason)
            except IndexError as exc:
                result.update(status="BAD_PROVIDER_PAYLOAD", reason=str(exc))
            result["last_attempt"] = {**attempt, "status": result["status"]}
            snapshot = validate_snapshot(_seal(result))
            _write_atomic(fd, "current.json", snapshot)
            return snapshot
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            os.close(lock)
    finally:
        os.close(fd)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise SourceFailure("SOURCE_DOWN")


def _network_enabled():
    return os.environ.get("AR_GDELT_NETWORK") == "1" and os.environ.get("AR_OFFLINE") != "1"


def fetch_live():
    if not _network_enabled():
        raise IndexError("NETWORK_OPT_IN_REQUIRED")
    request = urllib.request.Request(ENDPOINT,
                                     headers={"User-Agent": "AlphaResearch-Nonprod-NewsIndex/1"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=10) as response:
            if response.status != 200:
                raise SourceFailure("SOURCE_DOWN")
            if "xml" not in response.headers.get("Content-Type", "").lower():
                raise SourceFailure("BAD_PROVIDER_PAYLOAD", "NON_XML_CONTENT_TYPE")
            last_modified = response.headers.get("Last-Modified")
            if not last_modified:
                raise SourceFailure("BAD_PROVIDER_PAYLOAD", "LAST_MODIFIED_MISSING")
            try:
                modified = parsedate_to_datetime(last_modified)
                if modified.tzinfo is None:
                    raise ValueError("naive Last-Modified")
            except (TypeError, ValueError) as exc:
                raise SourceFailure("BAD_PROVIDER_PAYLOAD", "LAST_MODIFIED_INVALID") from exc
            raw = response.read(MAX_FEED_RESPONSE + 1)
            if len(raw) > MAX_FEED_RESPONSE:
                raise SourceFailure("BAD_PROVIDER_PAYLOAD", "FEED_SIZE_INVALID")
            return {"raw": raw, "feed_modified_at": modified.astimezone(UTC).isoformat()}
    except urllib.error.HTTPError as exc:
        raise SourceFailure("ACCESS_DENIED" if exc.code in {401, 403} else "SOURCE_DOWN") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceFailure("SOURCE_DOWN", "TLS_OR_NETWORK_FAILURE") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox-root", type=Path, required=True)
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--query", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--offline-response", type=Path)
    source.add_argument("--network", action="store_true")
    parser.add_argument("--offline-last-modified")
    args = parser.parse_args(argv)
    if args.network:
        if args.offline_last_modified is not None:
            raise IndexError("OFFLINE_HEADER_WITH_NETWORK")
        if not _network_enabled():
            raise IndexError("NETWORK_OPT_IN_REQUIRED")
        fetch = fetch_live
    else:
        if args.offline_last_modified is None:
            raise IndexError("OFFLINE_LAST_MODIFIED_REQUIRED")
        modified = _time(args.offline_last_modified).isoformat()
        raw = args.offline_response.read_bytes()
        if len(raw) > MAX_FEED_RESPONSE:
            raise IndexError("OFFLINE_RESPONSE_TOO_LARGE")
        fetch = lambda: {"raw": raw, "feed_modified_at": modified}
    result = poll_once(args.sandbox_root, query_id=args.query_id, query=args.query,
                       now=datetime.now(UTC).isoformat(), fetch=fetch)
    print(json.dumps({key: result[key] for key in ("status", "reason", "cursor_end",
                                                  "new_count", "snapshot_hash")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (IndexError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
