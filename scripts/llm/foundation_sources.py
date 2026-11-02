"""Bounded offline source accounting, not endpoint or runtime attestation."""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

__all__ = ["build_source_coverage", "load_source_inventory"]

_LABELS = {
    "sample_purpose": "WORKFLOW_DEBUG", "testing_status": "NOT_RUN",
    "human_review": "PENDING", "implementation_status": "IMPLEMENTED_UNTESTED",
    "production_authority": False, "trading_authority": False,
    "deployment_authority": False,
}
_DEFAULT = Path(__file__).absolute().parents[2] / "config/data-source-inventory.v1.json"
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,159}\Z")
_INTERFACE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,157}(?:\.\*)?\Z")
_HOST = re.compile(r"(?=.{1,253}\Z)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z")
_URL = re.compile(r"https?://[^\s<>\"'`\\]+", re.IGNORECASE)
_TEXT_CALL = re.compile(
    r"\b(?:fetch(?:WithTimeout|Json)?|axios(?:\.[A-Za-z_]+)?|https?\.(?:get|request)"
    r"|requests\.[A-Za-z_]+|httpx\.[A-Za-z_]+|urllib\.request\.[A-Za-z_]+"
    r"|Anthropic|OpenAI|GoogleGenerativeAI|createClient|urlopen|pro_api)\s*\("
    r"|\b(?:curl|wget)\s+"
)
_HTTP = {
    "urllib.request.urlopen", "urllib.request.Request", "urllib.request.urlretrieve",
    "http.client.HTTPConnection", "http.client.HTTPSConnection",
    "requests.get", "requests.post", "requests.put", "requests.patch",
    "requests.delete", "requests.head", "requests.request", "requests.Session",
    "httpx.get", "httpx.post", "httpx.request", "httpx.Client", "httpx.AsyncClient",
    "aiohttp.ClientSession", "curl_cffi.requests.get", "curl_cffi.requests.Session",
}
_RECEIVERS = {"pro", "api", "client", "session", "sess", "http", "https", "requests",
              "request", "httpx", "provider", "transport", "opener", "fetcher", "adapter", "sdk"}
_CALL_HINTS = {"urlopen", "urlretrieve", "fetch", "fetch_json", "fetchJson", "fetch_rows",
               "fetchWithTimeout", "_tushare_call", "_tushare_call_paged", "_tushare_request",
               "_call_tushare_api", "TushareHTTPS", "create_client", "get_json", "_get_json",
               "chat_completion", "_completion", "_post_chat_completion", "exec_module"}
_HARD_LIMITS = {"max_files": 10000, "max_file_bytes": 2 * 1024 * 1024,
                "max_total_bytes": 128 * 1024 * 1024, "max_entries": 50000,
                "max_depth": 32, "max_findings": 30000, "max_ast_nodes": 150000}


def _absolute(value):
    if (not isinstance(value, (str, Path)) or not str(value) or len(str(value)) > 4096
            or "://" in str(value) or ".." in Path(value).parts
            or any(ord(c) < 32 for c in str(value))):
        raise ValueError("SOURCE_PATH_INVALID")
    return Path(value).absolute()


def _relative(value, *, dot=False):
    if (not isinstance(value, str) or not value or len(value) > 512
            or "\\" in value or ":" in value or any(ord(c) < 32 for c in value)
            or Path(value).is_absolute() or ".." in Path(value).parts
            or (value == "." and not dot) or Path(value).as_posix() != value):
        raise ValueError("SOURCE_RELATIVE_PATH_INVALID")
    return value


def _open_readonly(path, *, directory=False):
    # Walk every component without following symlinks, including parent directories.
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ValueError("SOURCE_NOFOLLOW_UNAVAILABLE")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path.anchor, flags | os.O_DIRECTORY)
    try:
        for index, part in enumerate(path.parts[1:]):
            last = index == len(path.parts) - 2
            next_fd = os.open(part, flags | (os.O_DIRECTORY if directory or not last else 0), dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read(path, limit):
    fd = _open_readonly(path)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("SOURCE_NOT_REGULAR")
        if before.st_size > limit:
            raise ValueError("SOURCE_FILE_SIZE_LIMIT")
        chunks, size = [], 0
        while size <= limit:
            block = os.read(fd, min(65536, limit + 1 - size))
            if not block:
                break
            chunks.append(block)
            size += len(block)
        after = os.fstat(fd)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if size > limit:
            raise ValueError("SOURCE_FILE_SIZE_LIMIT")
        if identity(before) != identity(after) or size != after.st_size:
            raise ValueError("SOURCE_CHANGED_DURING_READ")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("SOURCE_INVENTORY_DUPLICATE_KEY")
        result[key] = value
    return result


def _string_list(value, *, maximum=512):
    if (not isinstance(value, list) or len(value) > maximum
            or any(not isinstance(item, str) for item in value)
            or len(set(value)) != len(value)):
        raise ValueError("SOURCE_INVENTORY_LIST_INVALID")
    return value


def _inventory(path):
    raw = _read(_absolute(path), 512 * 1024)
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("SOURCE_JSON_CONSTANT")))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("SOURCE_INVENTORY_JSON_INVALID") from None
    required = {"schema", "coverage_scope", "scan", "compatibility_catalog", "sources", *_LABELS}
    if (not isinstance(value, dict) or set(value) != required
            or value["schema"] != "ar.data-source-inventory.v1"
            or value["coverage_scope"] != "STATIC_PROVIDER_FAMILIES_NOT_ENDPOINT_CONTRACTS"
            or any(value.get(key) != expected or type(value.get(key)) is not type(expected)
                   for key, expected in _LABELS.items())):
        raise ValueError("SOURCE_INVENTORY_SCHEMA_INVALID")
    scan = value["scan"]
    if not isinstance(scan, dict) or set(scan) != {
            "roots", "exclude_directories", "exclude_paths", "extensions", *_HARD_LIMITS}:
        raise ValueError("SOURCE_SCAN_SCHEMA_INVALID")
    roots = _string_list(scan["roots"], maximum=32)
    if not roots:
        raise ValueError("SOURCE_ROOTS_REQUIRED")
    for root in roots:
        _relative(root, dot=True)
    for path_value in _string_list(scan["exclude_paths"]):
        _relative(path_value)
    for name in _string_list(scan["exclude_directories"]):
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            raise ValueError("SOURCE_EXCLUSION_INVALID")
    extensions = _string_list(scan["extensions"], maximum=32)
    if not extensions or any(not re.fullmatch(r"\.[a-z]{1,8}", item) for item in extensions):
        raise ValueError("SOURCE_EXTENSIONS_INVALID")
    for key, ceiling in _HARD_LIMITS.items():
        if type(scan[key]) is not int or not 1 <= scan[key] <= ceiling:
            raise ValueError("SOURCE_SCAN_LIMIT_INVALID")
    compatibility = value["compatibility_catalog"]
    if (not isinstance(compatibility, dict) or set(compatibility) != {"path", "source_ids"}
            or compatibility["path"] != "config/data-source-catalog.v1.json"):
        raise ValueError("SOURCE_COMPATIBILITY_INVALID")
    expected = {"tushare." + name for name in
                ("daily", "daily_basic", "moneyflow_dc", "moneyflow_ind_dc", "moneyflow_mkt_dc")}
    if set(_string_list(compatibility["source_ids"])) != expected:
        raise ValueError("SOURCE_COMPATIBILITY_SCOPE_INVALID")
    sources = value["sources"]
    fields = {"source_id", "provider", "kind", "hosts", "python_interfaces", "reference_paths",
              "rights_status", "rights_evidence_refs", "endpoint_contract", "instrumentation",
              "runtime_evidence"}
    if not isinstance(sources, list) or not 1 <= len(sources) <= 512:
        raise ValueError("SOURCE_REGISTRY_INVALID")
    identifiers = set()
    for row in sources:
        if (not isinstance(row, dict) or set(row) != fields
                or any(not isinstance(row[k], str) or not _ID.fullmatch(row[k])
                       for k in ("source_id", "provider"))
                or row["source_id"] in identifiers
                or not isinstance(row["kind"], str)
                or row["kind"] not in {"MARKET", "FILINGS", "NEWS", "MACRO", "MODEL", "OPERATIONS", "SDK"}
                or row["rights_status"] != "UNVERIFIED" or row["rights_evidence_refs"] != []
                or row["endpoint_contract"] != "NOT_DECLARED"
                or row["instrumentation"] != "NOT_ASSESSED"
                or row["runtime_evidence"] != "NOT_OBSERVED"):
            raise ValueError("SOURCE_REGISTRY_ROW_INVALID")
        identifiers.add(row["source_id"])
        hosts = _string_list(row["hosts"])
        interfaces = _string_list(row["python_interfaces"])
        if not hosts and not interfaces:
            raise ValueError("SOURCE_MATCHER_REQUIRED")
        if any(not _HOST.fullmatch(host) or ".." in host for host in hosts):
            raise ValueError("SOURCE_HOST_INVALID")
        if any(not _INTERFACE.fullmatch(item) for item in interfaces):
            raise ValueError("SOURCE_INTERFACE_INVALID")
        paths = _string_list(row["reference_paths"])
        if not paths:
            raise ValueError("SOURCE_REFERENCE_REQUIRED")
        for reference in paths:
            _relative(reference)
    return value, hashlib.sha256(raw).hexdigest()


def load_source_inventory(path=None):
    """Load a closed, bounded registry; reject rights/authority escalation."""
    try:
        return _inventory(_DEFAULT if path is None else path)[0]
    except OSError:
        raise ValueError("SOURCE_INVENTORY_UNREADABLE") from None


def _name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([node.id, *reversed(parts)])


def _safe_interface(value):
    return value if isinstance(value, str) and _INTERFACE.fullmatch(value) else None


def _host(value):
    # Emit only a hostname. Never retain userinfo, ports, paths, queries or fragments.
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme.lower() not in {"http", "https"} or not host:
            return None
        host = host.lower()
        return host if _HOST.fullmatch(host) and ".." not in host else None
    except ValueError:
        return None


def _matches(sources, *, host=None, interface=None):
    result = set()
    for row in sources:
        if host and host in row["hosts"]:
            result.add(row["source_id"])
        if interface:
            for pattern in row["python_interfaces"]:
                if interface == pattern or (pattern.endswith(".*") and interface.startswith(pattern[:-1])):
                    result.add(row["source_id"])
    return sorted(result)


def _observation(line, kind, *, host=None, interface=None, candidates=(), reason=None):
    matched = len(candidates) == 1 and reason is None
    if reason is None and not matched:
        reason = "AMBIGUOUS_REGISTRY_MATCH" if len(candidates) > 1 else "UNREGISTERED_SOURCE"
    return {"line": line, "kind": kind, "host": host, "interface_id": _safe_interface(interface),
            "inventory_status": "REGISTERED_STATIC" if matched else "UNRESOLVED",
            "source_id": candidates[0] if matched else None, "candidate_source_ids": list(candidates),
            "reason": reason, "match_scope": "PROVIDER_FAMILY_ONLY_NOT_ENDPOINT",
            "instrumentation": "NOT_ASSESSED", "runtime_evidence": "NOT_OBSERVED",
            "rights_status": "UNVERIFIED", "rights_evidence_refs": []}


def _python_findings(raw, sources, max_nodes):
    try:
        tree = ast.parse(raw)
    except (SyntaxError, UnicodeError, ValueError, RecursionError, MemoryError) as error:
        line = getattr(error, "lineno", None)
        yield _observation(line, "PARSE_ERROR", reason="PYTHON_PARSE_ERROR")
        return
    nodes = []
    for node in ast.walk(tree):
        if len(nodes) >= max_nodes:
            yield _observation(None, "SCAN_LIMIT", reason="AST_NODE_LIMIT")
            return
        nodes.append(node)
    aliases, alias_counts = {}, Counter()
    for node in nodes:
        if isinstance(node, ast.Import):
            for item in node.names:
                alias = item.asname or item.name.split(".")[0]
                aliases[alias] = item.name if item.asname else alias
                alias_counts[alias] += 1
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                alias = item.asname or item.name
                aliases[alias] = (node.module + "." + item.name) if node.module and not node.level else ""
                alias_counts[alias] += 1
                if item.name == "*":
                    yield _observation(node.lineno, "DYNAMIC_BINDING", reason="STAR_IMPORT")
    shadowed = {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))}
    shadowed.update(n.arg for n in nodes if isinstance(n, ast.arg))
    shadowed.update(n.name for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    shadowed.update(n.name for n in nodes if isinstance(n, ast.ExceptHandler) and n.name)
    uncertain = shadowed | {name for name, count in alias_counts.items() if count > 1}
    provider_modules = {pattern.split(".")[0] for row in sources for pattern in row["python_interfaces"]}
    for node in nodes:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for match in _URL.finditer(node.value):
                host = _host(match.group())
                yield _observation(node.lineno, "URL_REFERENCE", host=host,
                                   candidates=_matches(sources, host=host), reason="REFERENCE_NOT_CALL")
        if not isinstance(node, ast.Call):
            continue
        name = _name(node.func)
        if name in {"exec", "eval", "__import__", "importlib.import_module"} or (
                name and name.split(".")[-1] == "exec_module"):
            yield _observation(node.lineno, "DYNAMIC_CODE", interface=name, reason="DYNAMIC_CODE_NOT_INSPECTED")
            continue
        if name == "getattr":
            receiver = _name(node.args[0]) if node.args else None
            root = receiver.split(".")[0] if receiver else None
            if root in _RECEIVERS or root in aliases:
                yield _observation(node.lineno, "DYNAMIC_METHOD", interface="getattr",
                                   reason="DYNAMIC_OR_INDIRECT_METHOD")
            continue
        if not name:
            if isinstance(node.func, (ast.Call, ast.Subscript)):
                yield _observation(node.lineno, "INDIRECT_CALL", reason="INDIRECT_CALL_TARGET")
            elif isinstance(node.func, ast.Attribute):
                yield _observation(node.lineno, "INDIRECT_METHOD", interface=node.func.attr,
                                   reason="CHAINED_RECEIVER_NOT_RESOLVED")
            continue
        root, _, tail = name.partition(".")
        canonical = aliases.get(root, root) + ("." + tail if tail else "")
        module = canonical.split(".")[0]
        provider = module in provider_modules
        network = canonical in _HTTP
        hint = root in _RECEIVERS or name.split(".")[-1] in _CALL_HINTS
        if not (provider or network or hint):
            continue
        if provider and not network:
            candidates = _matches(sources, interface=canonical)
            # A family/interface entry is not an endpoint or client binding contract.
            reason = "PROVIDER_INTERFACE_ENDPOINT_UNRESOLVED"
            if root in uncertain:
                reason = "ALIAS_OR_BINDING_AMBIGUOUS"
            if name.split(".")[-1] in {"query", "pro_api", "create_client", "getattr"}:
                reason = "SDK_SETUP_OR_DYNAMIC_DISPATCH"
            yield _observation(node.lineno, "PROVIDER_INTERFACE", interface=canonical,
                               candidates=candidates, reason=reason)
            continue
        url_node = next((kw.value for kw in node.keywords if kw.arg in {"url", "fullurl"}), None)
        if url_node is None and node.args:
            url_node = node.args[1] if canonical.endswith(".request") and len(node.args) > 1 else node.args[0]
        literal = url_node.value if isinstance(url_node, ast.Constant) and isinstance(url_node.value, str) else None
        host = _host(literal) if literal is not None else None
        if host is None and isinstance(url_node, ast.JoinedStr) and url_node.values:
            first = url_node.values[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                # Only accept a host hint when a slash terminates its authority.
                prefix = re.match(r"https?://[^/\s]+/", first.value)
                host = _host(prefix.group()) if prefix else None
        candidates = _matches(sources, host=host)
        reason = None
        if root in uncertain:
            reason = "ALIAS_OR_BINDING_AMBIGUOUS"
        elif not network:
            reason = "UNRESOLVED_RECEIVER_OR_WRAPPER"
        elif root not in aliases:
            reason = "UNPROVEN_LIBRARY_BINDING"
        elif literal is None:
            reason = "DYNAMIC_URL_OR_REQUEST_OBJECT"
        elif host is None:
            reason = "UNKNOWN_OR_INVALID_HOST"
        yield _observation(node.lineno, "NETWORK_OR_PROVIDER_CALL", host=host,
                           interface=canonical, candidates=candidates, reason=reason)


def _text_findings(raw, sources):
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        yield _observation(None, "PARSE_ERROR", reason="TEXT_DECODE_ERROR")
        return
    for number, line in enumerate(text.splitlines(), 1):
        for match in _URL.finditer(line):
            host = _host(match.group())
            yield _observation(number, "TEXT_URL_REFERENCE", host=host,
                               candidates=_matches(sources, host=host), reason="TEXT_ONLY_NOT_PARSED")
        for match in _TEXT_CALL.finditer(line):
            identifier = match.group().strip().rstrip("(").strip()
            yield _observation(number, "TEXT_CALL_CANDIDATE", interface=identifier,
                               reason="TEXT_ONLY_NOT_PARSED")
        if re.search(r"\b(?:tushare|akshare|yfinance|anthropic|openai|supabase)\b", line, re.IGNORECASE):
            yield _observation(number, "TEXT_PROVIDER_REFERENCE", reason="TEXT_ONLY_NOT_PARSED")


def build_source_coverage(repository_root, *, inventory_path=None):
    """Read declared roots offline. Static accounting never proves complete discovery."""
    root = _absolute(repository_root)
    try:
        inventory, inventory_hash = _inventory(_DEFAULT if inventory_path is None else inventory_path)
    except OSError:
        raise ValueError("SOURCE_INVENTORY_UNREADABLE") from None
    scan, sources = inventory["scan"], inventory["sources"]
    findings, files, issues, roots = [], [], [], []
    counts = Counter()
    seen = set()
    exhausted = False

    def issue(reason, file=None):
        counts[reason] += 1
        if len(issues) < 1000:
            issues.append({"file": file, "status": "UNRESOLVED", "reason": reason})

    def excluded(relative):
        parts = Path(relative).parts
        return (any(part in scan["exclude_directories"] for part in parts)
                or any(relative == p or relative.startswith(p + "/") for p in scan["exclude_paths"]))

    def inspect_file(path, relative):
        nonlocal exhausted
        if path.suffix.lower() not in scan["extensions"]:
            counts["UNSUPPORTED_EXTENSION"] += 1
            return
        if counts["files_attempted"] >= scan["max_files"]:
            issue("FILE_COUNT_LIMIT", relative)
            exhausted = True
            return
        counts["files_attempted"] += 1
        try:
            raw = _read(path, min(scan["max_file_bytes"], scan["max_total_bytes"] - counts["bytes_read"]))
        except (OSError, ValueError) as error:
            reason = str(error) if isinstance(error, ValueError) else "SOURCE_UNREADABLE_OR_SYMLINK"
            issue(reason, relative)
            if (reason == "SOURCE_FILE_SIZE_LIMIT"
                    and scan["max_total_bytes"] - counts["bytes_read"] < scan["max_file_bytes"]):
                exhausted = True
                issue("TOTAL_BYTES_LIMIT", relative)
            return
        counts["bytes_read"] += len(raw)
        digest = hashlib.sha256(raw).hexdigest()
        mode = "PYTHON_AST" if path.suffix.lower() in {".py", ".pyi"} else "BOUNDED_TEXT_ONLY"
        file_row = {"file": relative, "sha256": digest, "bytes": len(raw), "inspection": mode,
                    "status": "OBSERVED_STATIC", "finding_count": 0}
        files.append(file_row)
        iterator = (_python_findings(raw, sources, scan["max_ast_nodes"])
                    if mode == "PYTHON_AST" else _text_findings(raw, sources))
        for row in iterator:
            if len(findings) >= scan["max_findings"]:
                issue("FINDING_COUNT_LIMIT", relative)
                file_row["status"] = "PARTIAL"
                exhausted = True
                break
            findings.append({"file": relative, "file_sha256": digest, **row})
            file_row["finding_count"] += 1
            if row["kind"] in {"PARSE_ERROR", "SCAN_LIMIT"}:
                file_row["status"] = "UNRESOLVED"
        if counts["bytes_read"] >= scan["max_total_bytes"]:
            exhausted = True
            issue("TOTAL_BYTES_LIMIT", relative)

    def walk(relative, depth):
        nonlocal exhausted
        if exhausted or relative in seen:
            return
        seen.add(relative)
        if excluded(relative):
            counts["EXCLUDED_PATH_OR_DIRECTORY"] += 1
            return
        if depth > scan["max_depth"]:
            issue("DEPTH_LIMIT", relative)
            return
        path = root if relative == "." else root / relative
        try:
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                issue("SYMLINK_SKIPPED", relative)
                return
            if stat.S_ISREG(mode):
                inspect_file(path, relative)
                return
            if not stat.S_ISDIR(mode):
                issue("NONREGULAR_SKIPPED", relative)
                return
            fd = _open_readonly(path, directory=True)
            try:
                names = []
                with os.scandir(fd) as entries:
                    for entry in entries:
                        if counts["entries_seen"] >= scan["max_entries"]:
                            issue("DIRECTORY_ENTRY_LIMIT", relative)
                            exhausted = True
                            break
                        counts["entries_seen"] += 1
                        names.append(entry.name)
                for name in sorted(names):
                    if exhausted:
                        break
                    child = name if relative == "." else relative + "/" + name
                    if any(ord(c) < 32 for c in child) or "\\" in child:
                        issue("UNSAFE_PATH_SKIPPED")
                    else:
                        walk(child, depth + 1)
            finally:
                os.close(fd)
        except (OSError, ValueError):
            issue("ROOT_OR_PATH_UNREADABLE", relative)

    for declared in scan["roots"]:
        if exhausted:
            roots.append({"root": declared, "status": "NOT_SCANNED_LIMIT"})
            continue
        issue_start = sum(counts[key] for key in counts if key not in {
            "files_attempted", "bytes_read", "entries_seen", "UNSUPPORTED_EXTENSION", "EXCLUDED_PATH_OR_DIRECTORY"})
        walk(declared, 0)
        issue_end = sum(counts[key] for key in counts if key not in {
            "files_attempted", "bytes_read", "entries_seen", "UNSUPPORTED_EXTENSION", "EXCLUDED_PATH_OR_DIRECTORY"})
        roots.append({"root": declared, "status": "PARTIAL" if exhausted or issue_end > issue_start else "TRAVERSED_STATIC_ONLY"})
    registered = sum(row["inventory_status"] == "REGISTERED_STATIC" for row in findings)
    unresolved = len(findings) - registered
    issue_total = sum(counts[key] for key in counts if key not in {
        "files_attempted", "bytes_read", "entries_seen", "UNSUPPORTED_EXTENSION", "EXCLUDED_PATH_OR_DIRECTORY"})
    observed_sources = {sid for row in findings for sid in row["candidate_source_ids"]}
    return {"schema": "ar.source-coverage.v1", **_LABELS,
            "status": "PARTIAL" if unresolved or issue_total else "STATIC_ONLY",
            "read_only": True, "network_performed": False, "source_execution_performed": False,
            "inventory_sha256": inventory_hash, "scan_roots": roots,
            "scope": "DECLARED_ROOTS_SUPPORTED_FILES_ONLY_STATIC_HEURISTIC_NOT_EXHAUSTIVE",
            "snapshot_scope": "SEQUENTIAL_LOCAL_READS_NOT_ATOMIC",
            "bounds": dict(scan), "omitted_scopes": {
                "excluded_directories": scan["exclude_directories"], "excluded_paths": scan["exclude_paths"],
                "unsupported_extensions": "NOT_INSPECTED", "symlinks": "NEVER_FOLLOWED",
                "dependencies_generated_code_runtime_and_environment": "NOT_INSPECTED",
                "dynamic_dispatch_and_cross_file_dataflow": "UNRESOLVED",
                "text_languages": "NO_JS_TS_SHELL_YAML_SEMANTIC_PARSER"},
            "files": files, "findings": findings, "scan_issues": issues,
            "summary": {"files_attempted": counts["files_attempted"], "files_read": len(files),
                        "bytes_read": counts["bytes_read"], "entries_seen": counts["entries_seen"],
                        "findings": len(findings), "registered_static": registered,
                        "unresolved_findings": unresolved, "unresolved_scan_issues": issue_total,
                        "unresolved_total": unresolved + issue_total,
                        "scan_issue_details_omitted": max(0, issue_total - len(issues)),
                        "skipped_or_limited_by_reason": dict(sorted(counts.items()))},
            "registry_observation": [{"source_id": row["source_id"],
                                      "status": "REFERENCE_OR_CANDIDATE_OBSERVED" if row["source_id"] in observed_sources else "NOT_OBSERVED_NOT_ABSENT",
                                      "rights_status": "UNVERIFIED", "instrumentation": "NOT_ASSESSED",
                                      "runtime_evidence": "NOT_OBSERVED"} for row in sources],
            "compatibility_catalog": {**inventory["compatibility_catalog"],
                                      "scope": "CLOSED_FIVE_UNCHANGED_NOT_REVALIDATED",
                                      "receipt_coverage": "NOT_MEASURED"},
            "complete_source_registration": False, "endpoint_instrumentation_proven": False,
            "runtime_evidence": "NOT_OBSERVED", "rights_status": "UNVERIFIED"}
