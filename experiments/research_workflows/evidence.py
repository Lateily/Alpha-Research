"""Strict, read-only local evidence references. Hashes prove bytes, not truth."""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


class TrialError(ValueError):
    pass


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise TrialError(f"{label}: unexpected or missing fields")


def date8(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
            raise ValueError()
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise TrialError("invalid date") from exc
    return value


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed
    except (AttributeError, ValueError) as exc:
        raise TrialError("timezone-aware timestamp required") from exc


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value):
        raise TrialError("invalid identifier")
    return value


def unique(rows, key):
    if not isinstance(rows, list) or not rows:
        raise TrialError("non-empty row list required")
    ids = [identifier(row[key]) for row in rows]
    if len(set(ids)) != len(ids):
        raise TrialError("duplicate identifiers")
    return ids


def text(value):
    rendered = (json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value)).replace("\\", "\\\\")
    for char in "`*_[]!|#":
        rendered = rendered.replace(char, "\\" + char)
    return html.escape(rendered, quote=False).replace("\n", "<br>")


def substantive(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(substantive(v) for v in value.values())
    if isinstance(value, list):
        return any(substantive(v) for v in value)
    return True


class Evidence:
    def __init__(self, sources, root, as_of):
        self.sources, self.raw, self.loaded = sources, {}, {}
        self.root = Path(root).resolve(strict=True)
        if not isinstance(sources, dict) or not sources:
            raise TrialError("sources required")
        paths = set()
        for name, source in sources.items():
            identifier(name)
            exact(source, {"path", "sha256", "company", "tier", "published_on", "format", "origin", "observed_at"}, "source")
            relative = Path(source["path"])
            if relative.is_absolute() or not relative.parts or any(p in {"..", "."} for p in relative.parts):
                raise TrialError("source path escape")
            path = self.root
            for part in relative.parts:
                path = path / part
                if path.is_symlink():
                    raise TrialError("source symlink refused")
            if path in paths or not path.is_file():
                raise TrialError("source path missing or aliased")
            paths.add(path)
            raw = path.read_bytes()
            if sha(raw) != source["sha256"]:
                raise TrialError("source hash mismatch")
            if date8(source["published_on"]) > as_of:
                raise TrialError("source after cutoff")
            identifier(source["company"])
            if source["tier"] not in {"E1", "E2", "E3", "E4"} or not source["origin"]:
                raise TrialError("source identity and tier required")
            if source["observed_at"] is not None:
                timestamp(source["observed_at"])
            if source["format"] not in {"text", "json"}:
                raise TrialError("unsupported source format")
            self.raw[name] = raw
            self.loaded[name] = json.loads(raw) if source["format"] == "json" else raw.decode("utf-8")

    def cite(self, ref, company):
        if not isinstance(ref, dict) or ref.get("source") not in self.sources:
            raise TrialError("unknown source")
        source = self.sources[ref["source"]]
        if source["company"] != company:
            raise TrialError("citation company mismatch")
        value = self.loaded[ref["source"]]
        if source["format"] == "json":
            exact(ref, {"source", "pointer", "expected"}, "JSON citation")
            pointer = ref["pointer"]
            if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
                raise TrialError("invalid JSON pointer")
            try:
                for key in pointer.split("/")[1:] if pointer else []:
                    key = key.replace("~1", "/").replace("~0", "~")
                    if isinstance(value, list):
                        if not re.fullmatch(r"0|[1-9][0-9]*", key):
                            raise ValueError()
                        value = value[int(key)]
                    else:
                        value = value[key]
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                raise TrialError("invalid JSON pointer") from exc
            locator = pointer or "/"
        else:
            exact(ref, {"source", "start", "end", "expected"}, "text citation")
            # PDF form feeds are page separators, not editor line breaks.
            lines = value.split("\n")
            start, end = ref["start"], ref["end"]
            if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
                raise TrialError("invalid line range")
            value = "\n".join(lines[start - 1:end])
            locator = f"L{start}-L{end}"
        if canonical(value) != canonical(ref["expected"]):
            raise TrialError("citation excerpt differs from original")
        return {"value": value, "source": ref["source"], "sha256": source["sha256"], "locator": locator, "published_on": source["published_on"], "tier": source["tier"]}

    def display(self, citation):
        source = self.sources[citation["source"]]
        link = "evidence/" + quote(source["path"], safe="/")
        value = citation["value"]
        excerpt = json.dumps(value, ensure_ascii=False, sort_keys=True) if not isinstance(value, str) else value
        return f"{text(excerpt)}\n\n原文：[{citation['source']}]({link})，{text(citation['locator'])}；{citation['tier']}；源日期 {citation['published_on']}。\n"

    def observation(self, ref, company, expected_date):
        citation = self.cite(ref, company)
        source = self.sources[ref["source"]]
        if source["format"] == "json":
            pointer = ref["pointer"]
            if not pointer.endswith("/close"):
                raise TrialError("brief JSON observation must reference a dated close row")
            parent = pointer.rsplit("/", 1)[0]
            row = self.loaded[ref["source"]]
            for key in parent.split("/")[1:]:
                key = key.replace("~1", "/").replace("~0", "~")
                row = row[int(key)] if isinstance(row, list) else row[key]
            if row.get("ts_code") != company:
                raise TrialError("observation row company mismatch")
            observed = date8(row.get("trade_date"))
        else:
            observed = source["published_on"]
        if observed != expected_date:
            raise TrialError("observation date does not match comparison date")
        return {**citation, "observation_date": observed}
