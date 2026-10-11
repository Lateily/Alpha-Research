"""Task 1: exact structures and trusted read-only bytes, NOT semantic readiness.

All accepted structures remain DATA_BLOCKED until PIT/U4/context semantics exist.
No provider, registration, calculation, output writer, or CLI lives here.
"""
from __future__ import annotations

import errno
import json
import os
import re
import stat
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

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
    "research_binding": "schema_version ts_code industry_key packet decision packet_hash decision_row_hash cohort_id causal_cluster_id method_version research_case thesis valuation red_flags",
    "optional_evidence": "source_ref missing_reason",
    "red_flags": "ts_code as_of available_at coverage_start coverage_end verdict reasons source_refs",
    "evidence_ref": "root_alias path sha256 pointer",
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
    if not path.is_absolute() or ".." in path.parts or "\x00" in str(path):
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
        _enum(value["timeframe"], {"1d"})
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
        for field in ("packet", "decision", "research_case"):
            if value[field] is not None:
                _ref(value[field], refs)
        for field in ("packet_hash", "decision_row_hash"):
            _nullable(value[field], _hash)
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


def _result():
    return {"schema": "technical-pack-validation.v1", "request": None, "source_manifest": None,
            "inputs": {}, "bindings": {}, "quality": {"structural_input_status": "NOT_EVALUATED",
                "promotion_input_status": "NOT_EVALUATED", "roles": {},
                "semantic_coverage": "NOT_IMPLEMENTED"}, "status": "DATA_BLOCKED", "reason_codes": [],
            "authority": {"sample_purpose": "WORKFLOW_DEBUG", "claim_allowed": False, "no_trade_flag": True,
                          "production_authority": False, "u4_authority": False,
                          "paper_registration_authority": False, "trade_authority": False}}


def _refusal(code):
    result = _result()
    result.update(status="REFUSED", reason_codes=[code])
    result["quality"]["structural_input_status"] = "REFUSED"
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

    This is a structural API only. Even fully hashed inputs are DATA_BLOCKED.
    Inputs in a refusal are empty; usable structures are not semantic approval.
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
        evidence_hashes = {}
        for ref in refs:
            alias, path = ref["root_alias"], ref["path"]
            if alias not in roots:
                _fail("UNKNOWN_EVIDENCE_ROOT")
            key = alias + ":" + path
            if key not in evidence_hashes:
                if len(evidence_hashes) >= MAX_EVIDENCE_FILES:
                    _fail("EVIDENCE_COUNT_LIMIT")
                try:
                    evidence_hashes[key] = sha(_read(roots[alias] / path, budget))
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
                      reason_codes=sorted(set(reasons + ["SEMANTIC_VALIDATION_NOT_IMPLEMENTED"])))
        result["quality"]["roles"] = roles
        result["quality"]["structural_input_status"] = (
            "STRUCTURALLY_VALID" if inputs["bars"] is not None else "DATA_BLOCKED")
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
