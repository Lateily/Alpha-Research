"""Offline, strict, source-bound daily technical input validation.

No provider, registration, calculation, output writer, or CLI lives here.
"""
from __future__ import annotations

import errno
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from zoneinfo import ZoneInfo

from .evidence import canonical, sha
from .technical_profiles import load_profile

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_ROWS = 2000
MAX_PACKS = 100
MAX_ROOTS = 16
MAX_EVIDENCE_FILES = 64
MAX_JSON_DEPTH = 32
MAX_DECIMAL_TEXT = 80
MAX_PACKAGE_ENTRIES = 10

ROLE_PATHS = {
    "bars": "inputs/bars.json", "calendar": "inputs/trade-calendar.json",
    "corporate_actions": "inputs/corporate-actions.json", "flow": "inputs/settled-flow.json",
    "context": "inputs/sector-context.json", "research_binding": "inputs/research-binding.json",
}

# Schema field sets are exhaustive, including every nested record type.
SCHEMAS = {key: frozenset(fields.split()) for key, fields in {
    "registry": "schema_version packs evidence_roots",
    "trusted_binding": "pack_root request_hash source_manifest_hash profile_id profile_hash mode",
    "request": "schema_version workflow_version rule_profile_hash mode pack_id ts_code industry_key as_of data_cutoff generated_at window_id exposure_status source_manifest_hash",
    "source_manifest": "schema_version sources",
    "source": "role path origin sha256 identity evidence_grade published_at available_at captured_at raw_unit normalized_unit licensing missing_reason",
    "identity": "ts_code industry_key", "unit": "price volume amount", "licensing": "license_id display_scope",
    "bars": "schema_version timeframe rows",
    "bar": "ts_code trade_date bar_close_at available_at open high low close volume amount price_basis currency",
    "calendar": "schema_version version source_hash coverage days", "coverage": "start end",
    "calendar_day": "trade_date is_open close_at suspensions", "suspension": "ts_code status source_refs",
    "corporate_actions": "schema_version ts_code price_basis coverage verified actions",
    "action": "action_id effective_date available_at kind verified source_refs",
    "flow": "schema_version ts_code rows", "flow_row": "trade_date available_at settlement_status main_net_flow main_net_flow_missing_reason currency",
    "context": "schema_version context_id industry_key as_of data_cutoff source_refs market_state sector_state rationale counter_evidence authored_by authored_at review_status reviewed_by reviewed_at invalidation_conditions supersedes context_hash review_receipt industry_mapping is_human_judgment automated_decision claim_allowed",
    "research_binding": "schema_version ts_code industry_key packet decision packet_hash decision_row_hash cohort_id causal_cluster_id method_version research_case thesis valuation red_flags u4_sources",
    "optional_evidence": "source_ref missing_reason",
    "red_flags": "ts_code as_of available_at coverage_start coverage_end verdict reasons source_refs",
    "evidence_ref": "root_alias path sha256 pointer",
    "u4_sources": "schema_version files bundle_ref feature_health_ref funnel_health_ref diagnostic_ref cyclical_flags_ref",
    "context_source": "schema_version industry_key as_of published_at available_at content",
    "mapping": "schema_version ts_code industry_key coverage_start coverage_end published_at available_at",
    "context_receipt": "schema_version context_id context_hash review_status reviewed_by reviewed_at",
    "suspension_source": "trade_date ts_code status",
    "optional_source": "schema_version kind ts_code industry_key published_at available_at content",
}.items()}


class ContractError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _NumberText(str):
    """Distinguish JSON number tokens from identifier/string tokens, without float."""


def _fail(code):
    raise ContractError(code)


def _exact(value, schema):
    if type(value) is not dict or set(value) != SCHEMAS[schema]:
        _fail("EXACT_FIELDS")


def _identifier(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value):
        _fail("INVALID_IDENTIFIER")


def _text(value):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        _fail("INVALID_TEXT")


def _hash(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        _fail("INVALID_HASH")


def _u4_hash(value):
    if type(value) is not str or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", value):
        _fail("INVALID_HASH")


def _enum(value, allowed):
    if type(value) is not str or value not in allowed:
        _fail("INVALID_ENUM")


def _boolean(value, expected=None):
    if type(value) is not bool:
        _fail("INVALID_BOOLEAN")
    if expected is not None and value != expected:
        _fail("AUTHORITY_OVERRIDE")


def _timestamp(value):
    if type(value) is not str or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})", value):
        _fail("INVALID_TIMESTAMP")
    if not value.endswith("Z") and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        _fail("INVALID_TIMESTAMP")
    try:
        if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            _fail("INVALID_TIMESTAMP")
    except ValueError:
        _fail("INVALID_TIMESTAMP")


def _date(value):
    if type(value) is not str or not re.fullmatch(r"[0-9]{8}", value):
        _fail("INVALID_DATE")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        _fail("INVALID_DATE")


def _decimal(value, nonnegative=False, price=False):
    if type(value) not in (str, _NumberText) or len(value) > MAX_DECIMAL_TEXT or not re.fullmatch(
            r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
        _fail("INVALID_DECIMAL")
    try:
        number = Decimal(value)
        if not number.is_finite() or (nonnegative and number < 0) or (price and number <= 0):
            _fail("INVALID_DECIMAL")
        # Enough precision for the entire bounded coefficient, not the host context.
        with localcontext() as context:
            context.prec = 2 * MAX_DECIMAL_TEXT + 4
            if price and number % Decimal("0.01") != 0:
                _fail("PRICE_OFF_TICK")
        return number
    except InvalidOperation:
        _fail("INVALID_DECIMAL")


def _rows(value, limit=MAX_ROWS):
    if type(value) is not list:
        _fail("INVALID_LIST")
    if len(value) > limit:
        _fail("ROW_LIMIT")
    return value


def _nullable(value, validator):
    if value is not None:
        validator(value)


def _relative(value):
    if type(value) is not str or len(value) > 512 or "\\" in value or "\x00" in value:
        _fail("UNSAFE_PATH")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in value.split("/")):
        _fail("UNSAFE_PATH")
    return value.split("/")


def _absolute(value):
    if not isinstance(value, (str, Path)):
        _fail("UNSAFE_PATH")
    path = Path(value)
    if path.anchor != "/" or ".." in path.parts or "\x00" in str(path):
        _fail("UNSAFE_PATH")
    return path


@contextmanager
def _directory(path):
    """Open each absolute ancestor with no-follow, retaining descriptor traversal."""
    path = _absolute(path)
    fd = None
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            _fail("SOURCE_MISSING")
        _fail("UNSAFE_PATH")
    finally:
        if fd is not None:
            os.close(fd)


def _fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _read(path, budget):
    path = _absolute(path)
    with _directory(path.parent) as parent:
        fd = None
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                _fail("UNSAFE_PATH")
            if before.st_nlink != 1:
                _fail("LINKED_FILE")
            if before.st_size > MAX_FILE_BYTES:
                _fail("FILE_TOO_LARGE")
            if budget[0] + before.st_size > MAX_TOTAL_BYTES:
                _fail("TOTAL_BYTES_LIMIT")
            chunks, size = [], 0
            while True:
                chunk = os.read(fd, min(65536, MAX_FILE_BYTES + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    _fail("FILE_TOO_LARGE")
                chunks.append(chunk)
            after = os.fstat(fd)
            named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if _fingerprint(before) != _fingerprint(after) or _fingerprint(after) != _fingerprint(named):
                _fail("SOURCE_CHANGED_DURING_READ")
            budget[0] += size
            return b"".join(chunks)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                _fail("SOURCE_MISSING")
            _fail("UNSAFE_PATH")
        finally:
            if fd is not None:
                os.close(fd)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _number_token(value):
    if len(value) > MAX_DECIMAL_TEXT:
        _fail("INVALID_DECIMAL")
    return _NumberText(value)


def _unicode_strings(value):
    if isinstance(value, str):
        value.encode("utf-8")
    elif type(value) is list:
        for item in value:
            _unicode_strings(item)
    elif type(value) is dict:
        for key, item in value.items():
            _unicode_strings(key)
            _unicode_strings(item)


def _json(raw):
    try:
        text = raw.decode("utf-8")
        depth, in_string, escaped = 0, False, False
        for char in text:
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char in "[{":
                depth += 1
                if depth > MAX_JSON_DEPTH:
                    _fail("JSON_DEPTH_LIMIT")
            elif char in "]}":
                depth -= 1
        value = json.loads(text, object_pairs_hook=_pairs, parse_float=_number_token, parse_int=_number_token,
                           parse_constant=lambda _: _fail("NONFINITE_JSON"))
        _unicode_strings(value)
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ContractError):
            raise
        _fail("INVALID_JSON")


def _version(value, expected):
    _enum(value["schema_version"], {expected})


def _coverage(value):
    _exact(value, "coverage")
    _date(value["start"])
    _date(value["end"])


def _ref(value, refs):
    _exact(value, "evidence_ref")
    _identifier(value["root_alias"])
    _relative(value["path"])
    _hash(value["sha256"])
    pointer = value["pointer"]
    if type(pointer) is not str or len(pointer) > 512 or (pointer and not pointer.startswith("/")):
        _fail("INVALID_POINTER")
    if re.search(r"~(?![01])", pointer):
        _fail("INVALID_POINTER")
    refs.append(value)


def _refs(values, refs):
    for value in _rows(values, MAX_EVIDENCE_FILES):
        _ref(value, refs)


def _optional(value, refs):
    _exact(value, "optional_evidence")
    if value["source_ref"] is None:
        _identifier(value["missing_reason"])
    else:
        _ref(value["source_ref"], refs)
        if value["missing_reason"] is not None:
            _fail("MISSING_REASON_CONFLICT")


def _source_manifest(value):
    _exact(value, "source_manifest")
    _version(value, "technical-source-manifest.v1")
    sources = _rows(value["sources"], 6)
    roles = [source.get("role") if type(source) is dict else None for source in sources]
    if len(roles) != 6 or any(type(role) is not str for role in roles) or set(roles) != set(ROLE_PATHS):
        _fail("SOURCE_ROLES")
    for source in sources:
        _exact(source, "source")
        _relative(source["path"])
        if source["path"] != ROLE_PATHS[source["role"]]:
            _fail("PACKAGE_LAYOUT")
        _text(source["origin"])
        _exact(source["identity"], "identity")
        for identity in source["identity"].values():
            _identifier(identity)
        _enum(source["evidence_grade"], {"E1", "E2", "E3", "E4"})
        for field in ("published_at", "available_at", "captured_at"):
            _timestamp(source[field])
        for field in ("raw_unit", "normalized_unit"):
            _exact(source[field], "unit")
            for unit in source[field].values():
                _nullable(unit, _identifier)
        _exact(source["licensing"], "licensing")
        _identifier(source["licensing"]["license_id"])
        _enum(source["licensing"]["display_scope"], {"LOCAL_ONLY", "PRIVATE_TEAM", "NO_DISPLAY"})
        if source["sha256"] is None:
            _identifier(source["missing_reason"])
        else:
            _hash(source["sha256"])
            if source["missing_reason"] is not None:
                _fail("MISSING_REASON_CONFLICT")


def _request(value):
    _exact(value, "request")
    _version(value, "technical-request.v1")
    _enum(value["workflow_version"], {"technical-workflow.v0.1"})
    for field in ("pack_id", "ts_code", "industry_key", "window_id"):
        _identifier(value[field])
    for field in ("rule_profile_hash", "source_manifest_hash"):
        _hash(value[field])
    for field in ("as_of", "data_cutoff", "generated_at"):
        _timestamp(value[field])
    _enum(value["mode"], {"HISTORICAL_REPLAY", "PROSPECTIVE_RESEARCH"})
    _enum(value["exposure_status"], {"EXPOSED", "UNEXPOSED", "UNKNOWN"})


def _binding(value):
    _exact(value, "trusted_binding")
    _absolute(value["pack_root"])
    _identifier(value["profile_id"])
    for field in ("request_hash", "source_manifest_hash", "profile_hash"):
        _hash(value[field])
    _enum(value["mode"], {"HISTORICAL_REPLAY", "PROSPECTIVE_RESEARCH"})


def _profile_matches(profile, approved):
    if type(profile) is not dict:
        return False
    try:
        return canonical(profile) == canonical(approved)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return False


def _verify_registry_bytes(manifest_raw, request_raw, trusted_binding):
    if sha(manifest_raw) != trusted_binding["source_manifest_hash"]:
        _fail("REGISTRY_MANIFEST_HASH_MISMATCH")
    if sha(request_raw) != trusted_binding["request_hash"]:
        _fail("REGISTRY_REQUEST_HASH_MISMATCH")


def _validate_role(role, value, refs):
    _exact(value, role)
    versions = {"bars": "technical-bars.v1", "calendar": "technical-calendar.v1",
                "corporate_actions": "technical-actions.v1", "flow": "technical-flow.v1",
                "context": "technical-sector-context.v1", "research_binding": "technical-research-binding.v1"}
    _version(value, versions[role])
    if role == "bars":
        if value["timeframe"] != "1d":
            _fail("UNSUPPORTED_TIMEFRAME")
        previous = None
        for row in _rows(value["rows"]):
            _exact(row, "bar")
            _identifier(row["ts_code"])
            _date(row["trade_date"])
            if previous is not None and row["trade_date"] <= previous:
                _fail("BAR_DATE_ORDER")
            previous = row["trade_date"]
            _timestamp(row["bar_close_at"])
            _timestamp(row["available_at"])
            prices = {field: _decimal(row[field], price=True) for field in ("open", "high", "low", "close")}
            if not prices["low"] <= min(prices["open"], prices["close"]) <= max(prices["open"], prices["close"]) <= prices["high"]:
                _fail("OHLC_INCONSISTENT")
            for field in ("volume", "amount"):
                _decimal(row[field], nonnegative=True)
            _enum(row["price_basis"], {"RAW", "ADJUSTED"})
            _enum(row["currency"], {"CNY"})
    elif role == "calendar":
        _identifier(value["version"])
        _hash(value["source_hash"])
        _coverage(value["coverage"])
        for day in _rows(value["days"]):
            _exact(day, "calendar_day")
            _date(day["trade_date"])
            _boolean(day["is_open"])
            _nullable(day["close_at"], _timestamp)
            for suspension in _rows(day["suspensions"]):
                _exact(suspension, "suspension")
                _identifier(suspension["ts_code"])
                _enum(suspension["status"], {"VERIFIED", "UNKNOWN"})
                _refs(suspension["source_refs"], refs)
    elif role == "corporate_actions":
        _identifier(value["ts_code"])
        _enum(value["price_basis"], {"RAW", "ADJUSTED"})
        _coverage(value["coverage"])
        _boolean(value["verified"])
        for action in _rows(value["actions"]):
            _exact(action, "action")
            _identifier(action["action_id"])
            _date(action["effective_date"])
            _timestamp(action["available_at"])
            _enum(action["kind"], {"SPLIT", "DIVIDEND", "RIGHTS", "OTHER"})
            _boolean(action["verified"])
            _refs(action["source_refs"], refs)
    elif role == "flow":
        _identifier(value["ts_code"])
        for row in _rows(value["rows"]):
            _exact(row, "flow_row")
            _date(row["trade_date"])
            _timestamp(row["available_at"])
            _enum(row["settlement_status"], {"SETTLED", "UNKNOWN", "PENDING"})
            if row["main_net_flow"] is None:
                _identifier(row["main_net_flow_missing_reason"])
            else:
                _decimal(row["main_net_flow"])
                if row["main_net_flow_missing_reason"] is not None:
                    _fail("MISSING_REASON_CONFLICT")
            _enum(row["currency"], {"CNY"})
    elif role == "context":
        for field in ("context_id", "industry_key", "authored_by"):
            _identifier(value[field])
        for field in ("as_of", "data_cutoff", "authored_at"):
            _timestamp(value[field])
        for field in ("reviewed_by", "supersedes"):
            _nullable(value[field], _identifier)
        _nullable(value["reviewed_at"], _timestamp)
        _refs(value["source_refs"], refs)
        _enum(value["market_state"], {"RISK_ON", "WEAK_REPAIR", "RISK_OFF", "STYLE_ROTATION", "UNKNOWN"})
        _enum(value["sector_state"], {"CONFIRMED", "NOT_CONFIRMED", "ADVERSE", "UNKNOWN"})
        _enum(value["review_status"], {"PENDING", "REVIEWED", "DISPUTED"})
        _text(value["rationale"])
        for field in ("counter_evidence", "invalidation_conditions"):
            for text in _rows(value[field]):
                _text(text)
        _hash(value["context_hash"])
        for field in ("review_receipt", "industry_mapping"):
            if value[field] is not None:
                _ref(value[field], refs)
        _boolean(value["is_human_judgment"], True)
        _boolean(value["automated_decision"], False)
        _boolean(value["claim_allowed"], False)
    else:
        for field in ("ts_code", "industry_key"):
            _identifier(value[field])
        for field in ("cohort_id", "causal_cluster_id", "method_version"):
            _nullable(value[field], _identifier)
        for field in ("packet", "decision", "research_case", "u4_sources"):
            if value[field] is not None:
                _ref(value[field], refs)
        for field in ("packet_hash", "decision_row_hash"):
            _nullable(value[field], _u4_hash)
        for field in ("thesis", "valuation"):
            _optional(value[field], refs)
        flags = value["red_flags"]
        _exact(flags, "red_flags")
        _identifier(flags["ts_code"])
        for field in ("as_of", "coverage_start", "coverage_end"):
            _date(flags[field])
        _timestamp(flags["available_at"])
        _enum(flags["verdict"], {"CLEAR", "ACTIVE", "UNKNOWN"})
        for reason in _rows(flags["reasons"]):
            _identifier(reason)
        _refs(flags["source_refs"], refs)


def _plain(value):
    if type(value) is _NumberText:
        return str(value)
    if type(value) is list:
        return [_plain(item) for item in value]
    if type(value) is dict:
        return {key: _plain(item) for key, item in value.items()}
    return value


def _time(value):
    _timestamp(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _market_date(value):
    return _time(value).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")


def _ledger_records(raw):
    from experiments.execution_tracker import event_ledger
    jsonl = not raw.lstrip().startswith(b"[")
    if jsonl:
        try:
            whole = _json(raw)
        except ContractError as exc:
            if exc.code != "INVALID_JSON":
                raise
        else:
            if type(whole) is dict:
                _fail("U4_DECISION_INVALID")
        lines = raw.decode("utf-8").splitlines()
        if len(lines) > MAX_ROWS:
            _fail("ROW_LIMIT")
        records = []
        for line in lines:
            _json(line.encode("utf-8"))
            records.append(json.loads(line))
        if any(line != event_ledger.canonical(record) for line, record in zip(lines, records)):
            _fail("U4_OUTER_CHAIN_INVALID")
    else:
        _json(raw)
        records = json.loads(raw)
    _rows(records)
    previous, timestamp, seen = event_ledger.GENESIS_PREV, "", set()
    for index, record in enumerate(records):
        if type(record) is not dict or set(record) != event_ledger.ALLOWED_FIELDS:
            _fail("U4_OUTER_CHAIN_INVALID")
        # technical-guard: T2_U4_OUTER_CHAIN
        if (type(record["seq"]) is not int or record["seq"] != index or record["prev"] != previous
                or record["hash"] != event_ledger.record_hash(record) or type(record["ts"]) is not str
                or record["ts"] < timestamp):
            _fail("U4_OUTER_CHAIN_INVALID")
        if type(record["kind"]) is not str or type(record["id"]) is not str or type(record["payload"]) is not dict:
            _fail("U4_OUTER_CHAIN_INVALID")
        key = (record["kind"], record["id"])
        if record["kind"] in event_ledger.UNIQUE_KINDS and key in seen:
            _fail("U4_OUTER_CHAIN_INVALID")
        seen.add(key)
        previous, timestamp = record["hash"], record["ts"]
    return records


class _FrozenEvidence:
    """Only bounded no-follow reads; never use the lock-creating ledger reader."""
    def __init__(self, roots, budget, raw, hashes):
        self.roots, self.budget, self.raw, self.hashes = roots, budget, raw, hashes
        self.files = {}

    def bytes(self, ref):
        _ref(ref, [])
        key = ref["root_alias"] + ":" + ref["path"]
        if ref["root_alias"] not in self.roots:
            _fail("UNKNOWN_EVIDENCE_ROOT")
        if key not in self.raw:
            if len(self.hashes) >= MAX_EVIDENCE_FILES:
                _fail("EVIDENCE_COUNT_LIMIT")
            try:
                self.raw[key] = _read(self.roots[ref["root_alias"]] / ref["path"], self.budget)
            except ContractError as exc:
                if exc.code == "SOURCE_MISSING":
                    return None
                raise
            self.hashes[key] = sha(self.raw[key])
        if self.hashes[key] != ref["sha256"]:
            _fail("EVIDENCE_HASH_MISMATCH")
        return self.raw[key]

    def get(self, ref, legacy=False):
        raw = self.bytes(ref)
        if raw is None:
            return None
        value = _json(raw)
        if legacy:
            # The old U4 validators require their original JSON numeric types.
            value = json.loads(raw)
        try:
            for token in ref["pointer"].split("/")[1:] if ref["pointer"] else []:
                token = token.replace("~1", "/").replace("~0", "~")
                if isinstance(value, list):
                    if not re.fullmatch(r"0|[1-9][0-9]*", token):
                        _fail("INVALID_POINTER")
                    value = value[int(token)]
                else:
                    value = value[token]
        except (KeyError, IndexError, TypeError, ValueError):
            _fail("POINTER_NOT_FOUND")
        return value

    def json_object(self, name):
        if name not in self.files:
            _fail("U4_SOURCE_NOT_BOUND")
        value = self.get(self.files[name], legacy=True)
        if type(value) is not dict:
            _fail("U4_SOURCE_MISSING")
        return value

    def sha256(self, name):
        if name not in self.files:
            _fail("U4_SOURCE_NOT_BOUND")
        raw = self.bytes(self.files[name])
        if raw is None:
            _fail("U4_SOURCE_MISSING")
        return sha(raw)


def _u4_binding(request, rb, evidence, bindings, block):
    prospective = request["mode"] == "PROSPECTIVE_RESEARCH"
    # technical-guard: T2_EXPOSURE_BOUNDARY
    if prospective and request["exposure_status"] != "UNEXPOSED":
        _fail("EXPOSURE_NOT_PROSPECTIVE")
    empty = all(rb[field] is None for field in ("packet", "decision", "packet_hash", "decision_row_hash", "u4_sources"))
    if empty:
        if prospective:
            _fail("PROSPECTIVE_SELECT_REQUIRED")
        bindings.update(u4_status="HISTORICAL_NO_U4_AUTHORITY", packet_hash=None,
                        decision_row_hash=None, cohort_id=None, causal_cluster_id=None, method_version=None)
        block("research_binding", "HISTORICAL_NO_U4_AUTHORITY")
        return
    if rb["packet"] is None or rb["u4_sources"] is None:
        _fail("U4_BINDING_INCOMPLETE")
    packet = evidence.get(rb["packet"], legacy=True)
    descriptor = evidence.get(rb["u4_sources"])
    if packet is None or descriptor is None:
        block("research_binding", "U4_SOURCE_MISSING")
        return
    _exact(descriptor, "u4_sources")
    _version(descriptor, "technical-u4-sources.v1")
    if type(descriptor["files"]) is not dict or not 1 <= len(descriptor["files"]) <= MAX_EVIDENCE_FILES:
        _fail("U4_SOURCE_SET_INVALID")
    for name, ref in descriptor["files"].items():
        _relative(name)
        _ref(ref, [])
        if ref["pointer"]:
            _fail("U4_SOURCE_SET_INVALID")
    evidence.files = descriptor["files"]
    if any(evidence.bytes(ref) is None for ref in evidence.files.values()):
        bindings["u4_status"] = "U4_SOURCE_MISSING"
        block("research_binding", "U4_SOURCE_MISSING")
        return
    _relative(descriptor["bundle_ref"])
    for field in ("feature_health_ref", "funnel_health_ref", "diagnostic_ref", "cyclical_flags_ref"):
        _nullable(descriptor[field], _relative)
    from experiments.research_funnel import u4_decision_ledger as ledger
    from experiments.research_funnel import u4_pre_decision as pre
    from experiments.research_funnel import closure_experiment as closure
    try:
        if type(packet) is not dict:
            _fail("U4_PACKET_INVALID")
        if packet.get("schema") == pre.SCHEMA:
            if any(descriptor[field] is None for field in ("feature_health_ref", "funnel_health_ref", "diagnostic_ref")):
                _fail("U4_BINDING_INCOMPLETE")
            packet_name = "technical-bound-packet.json"
            evidence.files = dict(evidence.files, **{packet_name: rb["packet"]})
            pre.validate_packet(evidence=evidence, packet_ref=packet_name,
                diagnostic_ref=descriptor["diagnostic_ref"], industry=request["industry_key"],
                method_version=rb["method_version"], bundle_ref=descriptor["bundle_ref"],
                feature_health_ref=descriptor["feature_health_ref"],
                funnel_health_ref=descriptor["funnel_health_ref"], cyclical_flags_ref=descriptor["cyclical_flags_ref"])
            row = next((row for row in packet["candidate_rows"] if row["ts_code"] == request["ts_code"]), None)
            if row is None:
                _fail("U4_IDENTITY_MISMATCH")
            if rb["decision"] is not None or rb["decision_row_hash"] is not None:
                _fail("U4_SELECT_CONTRACT_UNAVAILABLE")
            identity = dict(ts_code=row["ts_code"], industry_key=request["industry_key"],
                            cohort_id=row["cohort_id"], causal_cluster_id=row["causal_cluster_id"],
                            method_version=packet["method_version"], packet_hash=packet["packet_hash"], decision_row_hash=None)
            selected = False
        elif packet.get("schema") == closure.PACKET_SCHEMA:
            # Runtime path validators see only dedicated, captured nonproduction copies.
            bundle = closure.load_bundle_from_evidence(evidence, descriptor["bundle_ref"])
            with tempfile.TemporaryDirectory(prefix="technical-u4-source-") as temp:
                root = Path(temp)
                for name in bundle["manifest"]["artifacts"]:
                    _relative(name)
                    ref = evidence.files.get(descriptor["bundle_ref"] + "/" + name)
                    if ref is None:
                        _fail("U4_SOURCE_NOT_BOUND")
                    (root / name).parent.mkdir(parents=True, exist_ok=True)
                    (root / name).write_bytes(evidence.bytes(ref))
                (root / "manifest.json").write_bytes(evidence.bytes(evidence.files[descriptor["bundle_ref"] + "/manifest.json"]))
                ledger._validate_packet_source(packet, root)
            if rb["decision"] is None:
                _fail("U4_BINDING_INCOMPLETE")
            raw = evidence.bytes(rb["decision"])
            if raw is None:
                block("research_binding", "U4_SOURCE_MISSING")
                return
            if not raw.lstrip().startswith((b"[", b"{")):
                _fail("U4_DECISION_INVALID")
            if raw.lstrip().startswith(b"{") and b"\n" not in raw.strip():
                _fail("U4_DECISION_INVALID")
            records = _ledger_records(raw)
            state = ledger._replay_records(records)
            pointer = rb["decision"]["pointer"]
            if not re.fullmatch(r"/(0|[1-9][0-9]*)/payload", pointer):
                _fail("U4_DECISION_INVALID")
            index = int(pointer.split("/")[1])
            if index >= len(records):
                _fail("U4_DECISION_INVALID")
            event = records[index]["payload"]
            if type(event) is not dict or event != state["current"].get((ledger._packet_hash_ref(packet), request["ts_code"])):
                _fail("U4_DECISION_INVALID")
            candidate = event["candidate"]
            identity = dict(ts_code=candidate["ts_code"], industry_key=candidate["industry_code"],
                cohort_id=candidate["cohort_id"], causal_cluster_id=candidate["causal_cluster_id"],
                method_version=event["method_version"], packet_hash=packet["packet_hash"], decision_row_hash=event["record_hash"])
            selected = event["decision"] == "SELECT"
            if any(_time(ledger._registered_at_from_outer(record["ts"])) > _time(request["data_cutoff"]) for record in records):
                block("research_binding", "U4_AFTER_CUTOFF")
        else:
            _fail("U4_PACKET_INVALID")
    except ContractError:
        raise
    except (ledger.DecisionLedgerError, pre.PreDecisionError, closure.ClosureError,
            ValueError, TypeError, KeyError, AttributeError, IndexError):
        _fail("U4_ORIGINAL_EVIDENCE_INVALID")
    # technical-guard: T2_U4_EXACT_IDENTITY
    if any(identity[field] != rb[field] for field in identity) or any(
            identity[field] != request[field] for field in ("ts_code", "industry_key")):
        _fail("U4_IDENTITY_MISMATCH")
    bindings.update(identity)
    bindings["u4_status"] = "SELECT_BOUND" if selected else "HISTORICAL_NO_U4_AUTHORITY"
    if _time(packet["generated_at"]) > _time(request["data_cutoff"]):
        block("research_binding", "U4_AFTER_CUTOFF")
    if prospective and not selected:
        _fail("PROSPECTIVE_SELECT_REQUIRED")
    if not selected or not prospective:
        block("research_binding", "HISTORICAL_NO_U4_AUTHORITY")
    for field, code in (("cohort_id", "U4_COHORT_UNBOUND"), ("causal_cluster_id", "U4_CLUSTER_UNBOUND")):
        if identity[field] in {None, "UNAVAILABLE", "UNAVAILABLE_UNBOUND", "UNAVAILABLE_PENDING"}:
            block("research_binding", code)


def _semantics(result, evidence, profile):
    request, inputs, quality = result["request"], result["inputs"], result["quality"]
    cutoff, as_of = _time(request["data_cutoff"]), _market_date(request["as_of"])
    if _time(request["as_of"]) > cutoff:
        _fail("AS_OF_AFTER_CUTOFF")
    structural, promotion = [], list(result["reason_codes"])
    result["bindings"].update(ts_code=request["ts_code"], industry_key=request["industry_key"], context_hash=None)

    def block(role, code, affects_structure=False):
        promotion.append(code)
        if affects_structure:
            structural.append(code)
        if code not in quality["roles"][role]["reason_codes"]:
            quality["roles"][role]["reason_codes"].append(code)

    for source in result["source_manifest"]["sources"]:
        role = source["role"]
        if source["identity"] != {"ts_code": request["ts_code"], "industry_key": request["industry_key"]}:
            _fail("SOURCE_IDENTITY_MISMATCH")
        if inputs[role] is None:
            promotion.append("SOURCE_MISSING")
            if role in {"bars", "calendar", "corporate_actions"}:
                structural.append("SOURCE_MISSING")
            continue
        # technical-guard: T2_SOURCE_PIT
        if _time(source["published_at"]) > cutoff or _time(source["available_at"]) > cutoff:
            block(role, "SOURCE_AFTER_CUTOFF", role in {"bars", "calendar", "corporate_actions"})
        if _time(source["available_at"]) < _time(source["published_at"]) or _time(source["captured_at"]) < _time(source["available_at"]):
            _fail("SOURCE_TIME_ORDER")
        if role == "bars" and (source["normalized_unit"] != {"price": "CNY", "volume": "shares", "amount": "CNY"}
                or source["raw_unit"] != source["normalized_unit"]):
            block(role, "UNIT_CONVERSION_UNVERIFIED", True)
    bars = inputs["bars"]["rows"] if inputs["bars"] else []
    if len(bars) < profile["parameters"]["minimum_history_bars"]:
        block("bars", "INSUFFICIENT_HISTORY", True)
    for bar in bars:
        if bar["ts_code"] != request["ts_code"]:
            _fail("BAR_IDENTITY_MISMATCH")
        # technical-guard: T2_BAR_PIT
        if _time(bar["bar_close_at"]) > cutoff or _time(bar["available_at"]) > cutoff:
            block("bars", "BAR_AFTER_CUTOFF", True)
        if _time(bar["available_at"]) < _time(bar["bar_close_at"]):
            block("bars", "BAR_AVAILABLE_BEFORE_CLOSE", True)
        # technical-guard: T2_RAW_PRICE_BASIS
        if bar["price_basis"] != "RAW":
            block("bars", "PRICE_BASIS_UNSUPPORTED", True)
    calendar, actions = inputs["calendar"], inputs["corporate_actions"]
    traded = []
    if calendar and bars:
        if calendar["source_hash"] != sha(canonical({k: v for k, v in calendar.items() if k != "source_hash"})):
            block("calendar", "CALENDAR_SOURCE_HASH_MISMATCH", True)
        days = calendar["days"]
        dates = [day["trade_date"] for day in days]
        if dates != sorted(set(dates)):
            _fail("CALENDAR_DATE_ORDER")
        start, end = bars[0]["trade_date"], as_of
        if calendar["coverage"]["start"] > start or calendar["coverage"]["end"] < end:
            block("calendar", "CALENDAR_COVERAGE_UNKNOWN", True)
        date = datetime.strptime(start, "%Y%m%d")
        expected = []
        while date.strftime("%Y%m%d") <= end and len(expected) <= MAX_ROWS:
            expected.append(date.strftime("%Y%m%d"))
            date += timedelta(days=1)
        # technical-guard: T2_CALENDAR_HOLE
        if len(expected) > MAX_ROWS or any(date not in dates for date in expected):
            block("calendar", "CALENDAR_HOLE", True)
        by_date, by_bar = {day["trade_date"]: day for day in days}, {bar["trade_date"]: bar for bar in bars}
        for date in expected:
            day = by_date.get(date)
            if day is None:
                continue
            suspensions = [s for s in day["suspensions"] if s["ts_code"] == request["ts_code"]]
            if len(suspensions) > 1:
                _fail("SUSPENSION_DUPLICATE")
            suspended = False
            for suspension in suspensions:
                matches = []
                for ref in suspension["source_refs"]:
                    value = evidence.get(ref)
                    if value is not None:
                        _exact(value, "suspension_source")
                        matches.append(value == {"trade_date": date, "ts_code": request["ts_code"], "status": "VERIFIED"})
                    else:
                        matches.append(False)
                suspended = suspension["status"] == "VERIFIED" and bool(matches) and all(matches)
                if not suspended:
                    block("calendar", "SUSPENSION_UNVERIFIED", True)
            if day["is_open"] and not suspended:
                traded.append(date)
                if date not in by_bar:
                    block("bars", "OPEN_DAY_BAR_MISSING", True)
            if date in by_bar:
                bar = by_bar[date]
                if not day["is_open"] or suspensions:
                    block("bars", "BAR_ON_NONTRADED_DAY", True)
                if (day["close_at"] is None or _time(bar["bar_close_at"]) != _time(day["close_at"])
                        or _market_date(bar["bar_close_at"]) != date):
                    block("bars", "BAR_CALENDAR_CLOSE_MISMATCH", True)
                if _decimal(bar["volume"]) <= 0:
                    block("bars", "BAR_WITHOUT_TRADES", True)
        if any(bar["trade_date"] not in expected for bar in bars):
            block("bars", "BAR_OUTSIDE_WINDOW", True)
    if actions and bars:
        if actions["ts_code"] != request["ts_code"]:
            _fail("ACTION_IDENTITY_MISMATCH")
        # technical-guard: T2_ACTION_CONTINUITY
        if (not actions["verified"] or actions["coverage"]["start"] > bars[0]["trade_date"]
                or actions["coverage"]["end"] < as_of):
            block("corporate_actions", "ACTION_COVERAGE_UNKNOWN", True)
        if actions["price_basis"] != "RAW":
            block("corporate_actions", "PRICE_BASIS_UNSUPPORTED", True)
        for action in actions["actions"]:
            if bars[0]["trade_date"] <= action["effective_date"] <= as_of:
                block("corporate_actions", "CORPORATE_ACTION_BREAK", True)
    rb = inputs["research_binding"]
    if rb:
        if rb["ts_code"] != request["ts_code"] or rb["industry_key"] != request["industry_key"]:
            _fail("RESEARCH_IDENTITY_MISMATCH")
        _u4_binding(request, rb, evidence, result["bindings"], block)
        _red_flags(request, rb["red_flags"], evidence, quality, block)
    elif request["mode"] == "PROSPECTIVE_RESEARCH":
        _fail("PROSPECTIVE_SELECT_REQUIRED")
    else:
        result["bindings"].update(u4_status="HISTORICAL_NO_U4_AUTHORITY", packet_hash=None,
            decision_row_hash=None, cohort_id=None, causal_cluster_id=None, method_version=None)
        quality["red_flags"] = {"status": "UNKNOWN", "source_refs": []}
        block("research_binding", "HISTORICAL_NO_U4_AUTHORITY")
        block("research_binding", "RED_FLAG_COVERAGE_UNKNOWN")
    quality["missing_fields"] = {}
    for field in ("thesis", "valuation"):
        optional = rb[field] if rb else None
        value = evidence.get(optional["source_ref"]) if optional and optional["source_ref"] else None
        missing = value is None
        quality["missing_fields"][field] = {"value": None if missing else optional["source_ref"],
            "reason": (optional["missing_reason"] or "EVIDENCE_MISSING") if missing and optional else ("SOURCE_MISSING" if missing else None)}
        if missing:
            block("research_binding", field.upper() + "_NOT_FROZEN")
        else:
            _exact(value, "optional_source")
            _version(value, "technical-research-evidence.v1")
            _text(value["content"])
            if value["kind"] != field.upper() or any(value[key] != request[key] for key in ("ts_code", "industry_key")):
                _fail("OPTIONAL_RESEARCH_IDENTITY_MISMATCH")
            if any(_time(value[key]) > cutoff for key in ("published_at", "available_at")):
                block("research_binding", field.upper() + "_AFTER_CUTOFF")
    _flow(inputs["flow"], request, traded, quality, block)
    _context(inputs["context"], request, evidence, result["bindings"], quality, block)
    for role in ("context", "flow"):
        if quality["roles"][role]["reason_codes"]:
            if "SOURCE_AFTER_CUTOFF" in quality["roles"][role]["reason_codes"]:
                quality[role]["status"] = "DATA_BLOCKED"
                if role == "flow":
                    quality[role].update(last_two_sum=None, missing_reason="SOURCE_AFTER_CUTOFF")
    for role, data in quality["roles"].items():
        data["semantic_status"] = "DATA_BLOCKED" if data["reason_codes"] else "VALIDATED"
    quality.update(semantic_coverage="IMPLEMENTED", structural_input_status="DATA_BLOCKED" if structural else "STRUCTURALLY_VALID",
                   promotion_input_status="DATA_BLOCKED" if promotion else "VALIDATED", registration_readiness="NOT_AUTHORIZED")
    result["bindings"]["semantic_bindings_status"] = "EVALUATED"
    result.update(status="DATA_BLOCKED" if promotion or structural else "VALIDATED", reason_codes=sorted(set(promotion + structural)))


def _red_flags(request, flags, evidence, quality, block):
    if flags["ts_code"] != request["ts_code"]:
        _fail("RED_FLAG_IDENTITY_MISMATCH")
    original = {k: v for k, v in flags.items() if k != "source_refs"}
    verified = bool(flags["source_refs"])
    for ref in flags["source_refs"]:
        value = evidence.get(ref)
        if value is None:
            verified = False
            continue
        if flags["verdict"] == "UNKNOWN":
            verified = False
            continue
        _exact(value, "red_flags")
        if value["source_refs"] or {k: v for k, v in value.items() if k != "source_refs"} != original:
            _fail("RED_FLAG_SOURCE_MISMATCH")
    date = _market_date(request["as_of"])
    # technical-guard: T2_CURRENT_RED_FLAG_COVERAGE
    current = (verified and flags["as_of"] == date and flags["coverage_start"] <= date <= flags["coverage_end"]
               and _time(flags["available_at"]) <= _time(request["data_cutoff"]))
    quality["red_flags"] = {"status": flags["verdict"] if current else "UNKNOWN", "source_refs": flags["source_refs"]}
    if not current or flags["verdict"] == "UNKNOWN":
        block("research_binding", "RED_FLAG_COVERAGE_UNKNOWN")
    if flags["verdict"] == "ACTIVE":
        block("research_binding", "ACTIVE_RED_FLAG")


def _flow(flow, request, traded, quality, block):
    quality["flow"] = {"status": "DATA_BLOCKED", "trade_dates": traded[-2:], "last_two_sum": None,
                       "missing_reason": "FLOW_LAST_TWO_MISSING"}
    if flow is None:
        return
    if flow["ts_code"] != request["ts_code"]:
        _fail("FLOW_IDENTITY_MISMATCH")
    rows = flow["rows"]
    if len({row["trade_date"] for row in rows}) != len(rows):
        _fail("FLOW_DATE_DUPLICATE")
    by_date = {row["trade_date"]: row for row in rows}
    # technical-guard: T2_FLOW_LAST_TWO
    if len(traded) < 2 or any(date not in by_date or by_date[date]["main_net_flow"] is None for date in traded[-2:]):
        block("flow", "FLOW_LAST_TWO_MISSING")
        return
    pair = [by_date[date] for date in traded[-2:]]
    if any(row["settlement_status"] != "SETTLED" for row in pair):
        block("flow", "FLOW_NOT_SETTLED")
        quality["flow"]["missing_reason"] = "FLOW_NOT_SETTLED"
        return
    if any(_time(row["available_at"]) > _time(request["data_cutoff"]) for row in pair):
        block("flow", "FLOW_AFTER_CUTOFF")
        quality["flow"]["missing_reason"] = "FLOW_AFTER_CUTOFF"
        return
    with localcontext() as context:
        context.prec = MAX_DECIMAL_TEXT * 2
        total = sum((_decimal(row["main_net_flow"]) for row in pair), Decimal(0))
    quality["flow"].update(status="CONFIRMED" if total > 0 else "NOT_CONFIRMED", last_two_sum=str(total), missing_reason=None)
    if total <= 0:
        block("flow", "FLOW_NOT_POSITIVE")


def _context(context, request, evidence, bindings, quality, block):
    quality["context"] = {"status": "DATA_BLOCKED", "context_hash": None, "reason_codes": []}
    if context is None:
        return
    def blocked(code, status="DATA_BLOCKED"):
        block("context", code)
        quality["context"]["reason_codes"].append(code)
        quality["context"]["status"] = status
    if context["industry_key"] != request["industry_key"]:
        _fail("CONTEXT_MAPPING_MISMATCH")
    body = {k: v for k, v in context.items() if k not in {"context_hash", "review_receipt"}}
    expected = sha(canonical(body))
    # Unreviewed drafts are missing evidence, not authenticated confirmations.
    if context["review_status"] == "PENDING":
        blocked("CONTEXT_REVIEW_MISSING")
        return
    if context["context_hash"] != expected:
        _fail("CONTEXT_HASH_MISMATCH")
    bindings["context_hash"] = quality["context"]["context_hash"] = expected
    cutoff, date = _time(request["data_cutoff"]), _market_date(request["as_of"])
    if any(_time(context[field]) > cutoff for field in ("as_of", "data_cutoff", "authored_at")) or _market_date(context["as_of"]) != date:
        blocked("CONTEXT_AFTER_CUTOFF_OR_STALE")
    if not context["source_refs"]:
        blocked("CONTEXT_SOURCE_MISSING")
    for ref in context["source_refs"]:
        value = evidence.get(ref)
        if value is None:
            blocked("CONTEXT_SOURCE_MISSING")
            continue
        _exact(value, "context_source")
        _version(value, "technical-context-source.v1")
        _text(value["content"])
        if value["industry_key"] != request["industry_key"]:
            _fail("CONTEXT_MAPPING_MISMATCH")
        if any(_time(value[field]) > cutoff for field in ("as_of", "published_at", "available_at")) or _market_date(value["as_of"]) != date:
            blocked("CONTEXT_SOURCE_AFTER_CUTOFF")
        if _time(value["available_at"]) < _time(value["published_at"]):
            blocked("CONTEXT_SOURCE_TIME_ORDER")
    mapping = evidence.get(context["industry_mapping"]) if context["industry_mapping"] else None
    if mapping is None:
        blocked("CONTEXT_MAPPING_MISSING")
    else:
        _exact(mapping, "mapping")
        _version(mapping, "technical-industry-mapping.v1")
        for field in ("coverage_start", "coverage_end"):
            _date(mapping[field])
        if mapping["ts_code"] != request["ts_code"] or mapping["industry_key"] != request["industry_key"]:
            _fail("CONTEXT_MAPPING_MISMATCH")
        if not mapping["coverage_start"] <= date <= mapping["coverage_end"] or any(
                _time(mapping[field]) > cutoff for field in ("published_at", "available_at")):
            blocked("CONTEXT_MAPPING_STALE")
        if _time(mapping["available_at"]) < _time(mapping["published_at"]):
            blocked("CONTEXT_SOURCE_TIME_ORDER")
    receipt = evidence.get(context["review_receipt"]) if context["review_receipt"] else None
    if receipt is None:
        blocked("CONTEXT_REVIEW_MISSING")
    else:
        _exact(receipt, "context_receipt")
        _version(receipt, "technical-context-review.v1")
        if any(receipt[field] != context[field] for field in ("context_id", "context_hash", "review_status", "reviewed_by")):
            _fail("CONTEXT_RECEIPT_MISMATCH")
        # technical-guard: T2_CONTEXT_RECEIPT_PIT
        if _time(receipt["reviewed_at"]) > cutoff:
            blocked("CONTEXT_REVIEW_AFTER_CUTOFF")
        elif any(receipt[field] != context[field] for field in ("context_id", "context_hash", "review_status", "reviewed_by", "reviewed_at")):
            _fail("CONTEXT_RECEIPT_MISMATCH")
        if receipt["reviewed_by"] is None or context["reviewed_at"] is None:
            blocked("CONTEXT_REVIEW_MISSING")
        if _time(receipt["reviewed_at"]) < _time(context["authored_at"]):
            blocked("CONTEXT_REVIEW_BEFORE_AUTHORING")
    # technical-guard: T2_CONTEXT_CONFIRMATION
    if context["review_status"] == "DISPUTED":
        blocked("CONTEXT_DISPUTED")
    if context["sector_state"] == "ADVERSE" or context["market_state"] == "RISK_OFF":
        blocked("CONTEXT_ADVERSE", "ADVERSE")
    elif context["sector_state"] != "CONFIRMED" or context["market_state"] == "UNKNOWN":
        blocked("CONTEXT_NOT_CONFIRMED", "NOT_CONFIRMED")
    if not quality["context"]["reason_codes"]:
        quality["context"]["status"] = "CONFIRMED"


def _result():
    return {"schema": "technical-pack-validation.v1", "request": None, "source_manifest": None,
            "inputs": {}, "bindings": {}, "quality": {"structural_input_status": "NOT_EVALUATED",
                "promotion_input_status": "NOT_EVALUATED", "roles": {},
                "semantic_coverage": "NOT_EVALUATED"}, "status": "DATA_BLOCKED", "reason_codes": [],
            "authority": {"sample_purpose": "WORKFLOW_DEBUG", "claim_allowed": False, "no_trade_flag": True,
                          "production_authority": False, "u4_authority": False,
                          "paper_registration_authority": False, "trade_authority": False}}


def _refusal(code):
    result = _result()
    result.update(status="REFUSED", reason_codes=[code])
    result["quality"]["structural_input_status"] = "REFUSED"
    result["quality"]["promotion_input_status"] = "REFUSED"
    return result


def _layout(pack_root, expected):
    seen, count = set(), 0
    for directory, prefix in ((pack_root, ""), (pack_root / "inputs", "inputs/")):
        with _directory(directory) as fd:
            with os.scandir(fd) as entries:
                for entry in entries:
                    count += 1
                    if count > MAX_PACKAGE_ENTRIES:
                        _fail("PACKAGE_LAYOUT")
                    name = prefix + entry.name
                    if name == "inputs" and entry.is_dir(follow_symlinks=False):
                        continue
                    if name not in expected or not entry.is_file(follow_symlinks=False):
                        _fail("PACKAGE_LAYOUT")
                    seen.add(name)
    if not seen <= expected:
        _fail("PACKAGE_LAYOUT")


def _sums(raw, expected):
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeError:
        _fail("SUMS_MISMATCH")
    if len(lines) != len(expected):
        _fail("SUMS_MISMATCH")
    result = {}
    for line in lines:
        if not re.fullmatch(r"[0-9a-f]{64}  [A-Za-z0-9_./-]+", line):
            _fail("SUMS_MISMATCH")
        digest, path = line.split("  ")
        _relative(path)
        if path in result:
            _fail("SUMS_MISMATCH")
        result[path] = digest
    if result != expected:
        _fail("SUMS_MISMATCH")


def validate_pack(pack_root: Path, trusted_binding: dict, evidence_roots: dict[str, Path], profile: dict) -> dict:
    """Trusted binding/config MUST be supplied by an operator, not package JSON.

    Inputs in a refusal are empty. Structural and promotion readiness are separate.
    """
    try:
        _binding(trusted_binding)
        root = _absolute(pack_root)
        if root != _absolute(trusted_binding["pack_root"]):
            _fail("REGISTRY_PATH_MISMATCH")
        try:
            approved = load_profile(trusted_binding["profile_id"])
        except ValueError:
            _fail("PROFILE_OVERRIDE")
        if not _profile_matches(profile, approved) or trusted_binding["profile_hash"] != approved["profile_hash"]:
            _fail("PROFILE_OVERRIDE")
        if type(evidence_roots) is not dict or len(evidence_roots) > MAX_ROOTS:
            _fail("INVALID_ROOTS")
        roots = {}
        for alias, path in evidence_roots.items():
            _identifier(alias)
            roots[alias] = _absolute(path)
            if roots[alias] == root or roots[alias] in root.parents or root in roots[alias].parents:
                _fail("OVERLAPPING_INPUT_ROOTS")
        budget = [0]
        manifest_raw = _read(root / "source-manifest.json", budget)
        request_raw = _read(root / "request.json", budget)
        _verify_registry_bytes(manifest_raw, request_raw, trusted_binding)
        manifest = _json(manifest_raw)
        _source_manifest(manifest)
        request = _json(request_raw)
        _request(request)
        if request["source_manifest_hash"] != sha(manifest_raw):
            _fail("REQUEST_MANIFEST_HASH_MISMATCH")
        if request["rule_profile_hash"] != approved["profile_hash"]:
            _fail("PROFILE_OVERRIDE")
        if request["mode"] != trusted_binding["mode"]:
            _fail("REGISTRY_MODE_MISMATCH")
        sums = {"request.json": sha(request_raw), "source-manifest.json": sha(manifest_raw)}
        source_hashes, inputs, roles, refs, reasons = {}, {}, {}, [], []
        expected_paths = {"request.json", "source-manifest.json", "SHA256SUMS"}
        for source in manifest["sources"]:
            role, path = source["role"], source["path"]
            if source["sha256"] is None:
                inputs[role] = None
                roles[role] = {"status": "DATA_BLOCKED", "reason_codes": [source["missing_reason"]]}
                reasons.append("SOURCE_DECLARED_MISSING")
                continue
            sums[path] = source["sha256"]
            expected_paths.add(path)
            try:
                raw = _read(root / path, budget)
            except ContractError as exc:
                if exc.code != "SOURCE_MISSING":
                    raise
                inputs[role] = None
                roles[role] = {"status": "DATA_BLOCKED", "reason_codes": ["SOURCE_MISSING"]}
                reasons.append("SOURCE_MISSING")
                continue
            if sha(raw) != source["sha256"]:
                _fail("SOURCE_HASH_MISMATCH")
            value = _json(raw)
            _validate_role(role, value, refs)
            inputs[role] = _plain(value)
            source_hashes[path] = sha(raw)
            roles[role] = {"status": "STRUCTURALLY_VALID", "reason_codes": []}
        _layout(root, expected_paths)
        _sums(_read(root / "SHA256SUMS", budget), sums)
        evidence_hashes, evidence_raw = {}, {}
        for ref in refs:
            alias, path = ref["root_alias"], ref["path"]
            if alias not in roots:
                _fail("UNKNOWN_EVIDENCE_ROOT")
            key = alias + ":" + path
            if key not in evidence_hashes:
                if len(evidence_hashes) >= MAX_EVIDENCE_FILES:
                    _fail("EVIDENCE_COUNT_LIMIT")
                try:
                    evidence_raw[key] = _read(roots[alias] / path, budget)
                    evidence_hashes[key] = sha(evidence_raw[key])
                except ContractError as exc:
                    if exc.code != "SOURCE_MISSING":
                        raise
                    reasons.append("EVIDENCE_MISSING")
                    continue
            if evidence_hashes[key] != ref["sha256"]:
                _fail("EVIDENCE_HASH_MISMATCH")
        result = _result()
        result.update(request=request, source_manifest=manifest, inputs=inputs,
                      bindings={"request_byte_hash": sha(request_raw), "source_manifest_byte_hash": sha(manifest_raw),
                                "profile_semantic_hash": approved["profile_hash"], "mode": request["mode"],
                                "source_byte_hashes": source_hashes, "evidence_byte_hashes": evidence_hashes,
                                "semantic_bindings_status": "NOT_EVALUATED"},
                      reason_codes=sorted(set(reasons)))
        result["quality"]["roles"] = roles
        _semantics(result, _FrozenEvidence(roots, budget, evidence_raw, evidence_hashes), approved)
        return result
    except ContractError as exc:
        return _refusal(exc.code)


def load_registered_pack(registry_path: Path, pack_id: str, evidence_roots: dict[str, Path]) -> dict:
    """Reopen the separately operator-owned registry; never register from input."""
    try:
        path = _absolute(registry_path)
        _identifier(pack_id)
        registry = _json(_read(path, [0]))
        _exact(registry, "registry")
        _version(registry, "technical-registry.v1")
        packs, configured = registry["packs"], registry["evidence_roots"]
        if type(packs) is not dict or len(packs) > MAX_PACKS:
            _fail("INVALID_REGISTRY")
        if type(configured) is not dict or len(configured) > MAX_ROOTS:
            _fail("INVALID_ROOTS")
        roots = {}
        for alias, value in configured.items():
            _identifier(alias)
            roots[alias] = _absolute(value)
        if type(evidence_roots) is not dict or set(evidence_roots) != set(roots):
            _fail("EVIDENCE_ROOT_OVERRIDE")
        for alias, root in roots.items():
            if _absolute(evidence_roots[alias]) != root:
                _fail("EVIDENCE_ROOT_OVERRIDE")
        for registered_id, binding in packs.items():
            _identifier(registered_id)
            _binding(binding)
            root = _absolute(binding["pack_root"])
            if root == path or root in path.parents or any(r == path or r in path.parents for r in roots.values()):
                _fail("REGISTRY_IN_INPUT_TREE")
        if pack_id not in packs:
            _fail("PACK_NOT_REGISTERED")
        binding = packs[pack_id]
        try:
            profile = load_profile(binding["profile_id"])
        except ValueError:
            _fail("PROFILE_OVERRIDE")
        result = validate_pack(Path(binding["pack_root"]), binding, roots, profile)
        if result["request"] is not None and result["request"]["pack_id"] != pack_id:
            _fail("REGISTRY_PACK_ID_MISMATCH")
        return result
    except ContractError as exc:
        return _refusal(exc.code)
