#!/usr/bin/env python3
"""Locate a connection failure without over-attributing its root cause.

Run ``probe`` once in the constrained execution environment and once in the
host terminal, then use ``compare``.  A resolver failure in one process is
reported as an observation in that process, never as proof that the host or
remote data source is broken.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit


SCHEMA = "ar.network_layer_diagnostic.v1"
COMPARISON_SCHEMA = "ar.network_layer_diagnostic_comparison.v1"
Probe = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]


class DiagnosticError(RuntimeError):
    pass


def _endpoint(value: str) -> dict[str, Any]:
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise DiagnosticError("endpoint must be an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DiagnosticError("endpoint must not contain credentials, query, or fragment")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise DiagnosticError("endpoint port is invalid") from exc
    return {
        "scheme": "https",
        "host": parsed.hostname,
        "port": port,
        "path": parsed.path or "/",
    }


def _safe_proxy_map(proxy_map: Mapping[str, str]) -> dict[str, Any]:
    routes: dict[str, dict[str, Any]] = {}
    for route, raw in sorted(proxy_map.items()):
        parsed = urlsplit(str(raw or ""))
        if not parsed.scheme or not parsed.hostname:
            continue
        try:
            port = parsed.port
        except ValueError:
            port = None
        routes[str(route)] = {
            "scheme": parsed.scheme,
            "host": parsed.hostname,
            "port": port,
        }
    return {"configured": bool(routes), "routes": routes}


def _dns_probe(endpoint: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = socket.getaddrinfo(
        endpoint["host"], endpoint["port"], type=socket.SOCK_STREAM
    )
    return {"address_count": len(rows)}


def _tcp_probe(endpoint: Mapping[str, Any]) -> Mapping[str, Any]:
    with socket.create_connection(
        (str(endpoint["host"]), int(endpoint["port"])), timeout=8
    ):
        return {"connected": True}


def _tls_probe(endpoint: Mapping[str, Any]) -> Mapping[str, Any]:
    context = ssl.create_default_context()
    with socket.create_connection(
        (str(endpoint["host"]), int(endpoint["port"])), timeout=8
    ) as raw:
        with context.wrap_socket(raw, server_hostname=str(endpoint["host"])) as wrapped:
            return {"protocol": wrapped.version()}


def _http_probe(endpoint: Mapping[str, Any]) -> Mapping[str, Any]:
    url = (
        f"https://{endpoint['host']}"
        f"{':' + str(endpoint['port']) if endpoint['port'] != 443 else ''}"
        f"{endpoint['path']}"
    )
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return {"response_status": int(response.status)}
    except urllib.error.HTTPError as exc:
        # An HTTP response, including an authorization or method error, proves
        # the request reached the application layer.
        return {"response_status": int(exc.code)}


def _layer_result(name: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"layer": name, "status": status, **extra}


def probe_endpoint(
    url: str,
    *,
    execution_context: str,
    environment: Mapping[str, str] | None = None,
    proxy_map: Mapping[str, str] | None = None,
    dns_probe: Probe = _dns_probe,
    tcp_probe: Probe = _tcp_probe,
    tls_probe: Probe = _tls_probe,
    http_probe: Probe = _http_probe,
) -> dict[str, Any]:
    endpoint = _endpoint(url)
    env = os.environ if environment is None else environment
    proxies = urllib.request.getproxies() if proxy_map is None else proxy_map
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "BLOCKED",
        "execution_context": str(execution_context or "UNKNOWN"),
        "endpoint": endpoint,
        "proxy": _safe_proxy_map(proxies),
        "layers": [],
        "failure_layer": None,
        "cause_attribution": "UNCONFIRMED_BEYOND_THIS_EXECUTION_ENVIRONMENT",
    }
    if str(env.get("AR_OFFLINE") or "").strip() == "1":
        receipt["layers"].append(
            _layer_result("EXECUTION_POLICY", "BLOCKED", code="AR_OFFLINE")
        )
        receipt["failure_layer"] = "EXECUTION_POLICY"
        return receipt

    probes = (
        ("DNS_RESOLUTION", dns_probe),
        ("TCP_CONNECT", tcp_probe),
        ("TLS_HANDSHAKE", tls_probe),
        ("HTTP_RESPONSE", http_probe),
    )
    for name, probe in probes:
        try:
            detail = dict(probe(endpoint) or {})
        except Exception as exc:  # noqa: BLE001 - classification is the purpose
            receipt["layers"].append(
                _layer_result(name, "BLOCKED", exception_type=type(exc).__name__)
            )
            receipt["failure_layer"] = name
            return receipt
        receipt["layers"].append(_layer_result(name, "PASS", **detail))

    receipt["status"] = "PASS"
    receipt["cause_attribution"] = "ENDPOINT_REACHED_FROM_THIS_EXECUTION_ENVIRONMENT"
    return receipt


def compare_receipts(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    for value in (left, right):
        if value.get("schema") != SCHEMA:
            raise DiagnosticError("comparison requires two network diagnostic receipts")
    if left.get("endpoint") != right.get("endpoint"):
        raise DiagnosticError("diagnostic receipts must target the same endpoint")

    left_status = left.get("status")
    right_status = right.get("status")
    left_failure = left.get("failure_layer")
    right_failure = right.get("failure_layer")
    if left_status != right_status:
        finding = "EXECUTION_ENVIRONMENT_PATH_DIFFERENCE"
    elif left_status == "PASS":
        finding = "ENDPOINT_REACHED_IN_BOTH_CONTEXTS"
    elif left_failure == right_failure:
        finding = "SAME_LAYER_FAILURE_OBSERVED_IN_BOTH_CONTEXTS"
    else:
        finding = "DIFFERENT_FAILURE_LAYERS_OBSERVED"

    host_dns_observed = any(
        str(value.get("execution_context") or "").upper().startswith("HOST")
        and value.get("failure_layer") == "DNS_RESOLUTION"
        for value in (left, right)
    )
    return {
        "schema": COMPARISON_SCHEMA,
        "finding": finding,
        "endpoint": left["endpoint"],
        "left": {
            "execution_context": left.get("execution_context"),
            "status": left_status,
            "failure_layer": left_failure,
        },
        "right": {
            "execution_context": right.get("execution_context"),
            "status": right_status,
            "failure_layer": right_failure,
        },
        "host_process_name_resolution_failure_observed": host_dns_observed,
        "host_dns_failure_confirmed": False,
        "cause_attribution": "BOUNDED_TO_OBSERVED_PROCESSES",
    }


def _load(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise DiagnosticError("diagnostic receipt must be a JSON object")
    return value


def _write(path: str | Path | None, value: Mapping[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(payload, end="")
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe_parser = subparsers.add_parser("probe")
    probe_parser.add_argument("--url", required=True)
    probe_parser.add_argument("--context", required=True)
    probe_parser.add_argument("--output")

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--left", required=True)
    compare_parser.add_argument("--right", required=True)
    compare_parser.add_argument("--output")
    args = parser.parse_args(argv)

    try:
        if args.command == "probe":
            value = probe_endpoint(args.url, execution_context=args.context)
        else:
            value = compare_receipts(_load(args.left), _load(args.right))
        _write(args.output, value)
        return 0 if value.get("status", "PASS") == "PASS" else 2
    except (DiagnosticError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"network diagnostic refused: {type(exc).__name__}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
