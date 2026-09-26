#!/usr/bin/env python3
"""Freeze Macro source responses before creating an isolated build run.

This module does not publish, update current_run, or grant production authority.
It separates the network-bearing capture phase from deterministic replay and
ensures a build run_id cannot be created until the frozen bundle is verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.macro_os import collectors, contracts


SCHEMA = "ar.macro.frozen_source_bundle"
SCHEMA_VERSION = "1.0"
STATUS = "FROZEN"
SAFE_HEADERS = {"accept", "content-type", "user-agent"}
SECRET_KEYS = collectors.SECRET_QUERY_KEYS | {
    "access_token",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "x-api-key",
}
REPLAY_CREDENTIAL = "FROZEN_REPLAY_NOT_A_REAL_CREDENTIAL"
REQUEST_FIELDS = {
    "request_id",
    "source_id",
    "request_signature",
    "response_status",
    "final_locator",
    "response_headers",
    "body_path",
    "body_sha256",
    "body_bytes",
}
LOCAL_INPUT_FIELDS = {"name", "path", "sha256", "bytes"}


class PreparationError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise PreparationError("as_of must include a timezone")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise PreparationError("frozen bundle as_of is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreparationError("frozen bundle as_of is invalid") from exc
    if parsed.tzinfo is None:
        raise PreparationError("frozen bundle as_of must include a timezone")
    return parsed.astimezone(timezone.utc)


def _safe_locator(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise PreparationError("frozen response locator must be HTTPS")
    host = parsed.hostname.lower()
    port = f":{parsed.port}" if parsed.port and parsed.port != 443 else ""
    safe_query = urlencode(
        sorted(
            (key, child)
            for key, child in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in SECRET_KEYS
        )
    )
    return urlunsplit(("https", host + port, parsed.path or "/", safe_query, ""))


def _scrub_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _scrub_value(child)
            for key, child in sorted(value.items(), key=lambda row: str(row[0]))
            if str(key).casefold() not in SECRET_KEYS
        }
    if isinstance(value, list):
        return [_scrub_value(child) for child in value]
    return value


def _safe_body_identity(body: bytes | None) -> dict[str, Any] | None:
    if body is None:
        return None
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        try:
            pairs = parse_qsl(body.decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError:
            return {"opaque_bytes": len(body)}
        safe_pairs = sorted(
            (key, value)
            for key, value in pairs
            if key.casefold() not in SECRET_KEYS
        )
        return {"form": urlencode(safe_pairs)}
    return {"json": _scrub_value(value)}


def _request_signature(request: collectors.HttpRequest) -> str:
    safe_headers = {
        key.casefold(): value
        for key, value in request.headers.items()
        if key.casefold() in SAFE_HEADERS
    }
    identity = {
        "method": request.method.upper(),
        "locator": _safe_locator(request.public_locator),
        "headers": safe_headers,
        "body": _safe_body_identity(request.body),
        "allowed_hosts": sorted(host.casefold() for host in request.allowed_hosts),
    }
    return _sha256(_canonical(identity))


def _manifest_hash(value: Mapping[str, Any]) -> str:
    return _sha256(_canonical({key: child for key, child in value.items() if key != "bundle_hash"}))


def _preparation_hash(value: Mapping[str, Any]) -> str:
    return _sha256(
        _canonical({key: child for key, child in value.items() if key != "manifest_hash"})
    )


def _credential_names() -> set[str]:
    registry = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(registry)
    return {
        name
        for source in registry["sources"]
        for name in source["credential_env_vars"]
    }


def _replay_environment(environment: Mapping[str, str] | None) -> dict[str, str]:
    result = dict(os.environ if environment is None else environment)
    for name in _credential_names():
        result[name] = REPLAY_CREDENTIAL
    result["AR_OFFLINE"] = "1"
    return result


@contextmanager
def _temporary_environment(values: Mapping[str, str]):
    previous = {name: os.environ.get(name) for name in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _safe_request_id(value: str) -> str:
    if re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,127}", value) is None:
        raise PreparationError("request_id is not safe for frozen storage")
    return value


def _validate_parsed_response(
    spec: collectors.RequestSpec, body: bytes, fetched_at: str
) -> None:
    try:
        observations = spec.parser(body, fetched_at, spec)
    except Exception as exc:  # noqa: BLE001 - convert parser details to a safe boundary
        raise PreparationError(
            f"frozen response failed parser validation for {spec.request_id}"
        ) from exc
    emitted = {(row.series_id, row.metric_key) for row in observations}
    expected = {(row.series_id, row.metric_key) for row in spec.metrics}
    if emitted != expected:
        raise PreparationError(
            f"frozen response metric set differs for {spec.request_id}"
        )


def freeze_macro_inputs(
    output_dir: str | Path,
    *,
    specs: Iterable[collectors.RequestSpec],
    as_of: datetime,
    transport: collectors.Transport,
    environment: Mapping[str, str] | None = None,
    local_inputs: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """Capture and freeze validated responses without creating a run_id."""
    target = Path(output_dir)
    if target.exists():
        raise PreparationError("frozen bundle destination already exists")
    now_text = _utc(as_of)
    env = dict(os.environ if environment is None else environment)
    replay_env = _replay_environment(env)
    planned = tuple(specs)
    if not planned:
        raise PreparationError("frozen bundle requires at least one request")
    temporary = target.with_name(target.name + ".building")
    if temporary.exists():
        raise PreparationError("frozen bundle temporary destination already exists")
    responses_dir = temporary / "responses"
    responses_dir.mkdir(parents=True)
    entries: list[dict[str, Any]] = []
    local_entries: list[dict[str, Any]] = []
    try:
        for spec in planned:
            request_id = _safe_request_id(spec.request_id)
            request = spec.build_request(as_of, env)
            public_host = (urlsplit(request.public_locator).hostname or "").casefold()
            if public_host not in {host.casefold() for host in request.allowed_hosts}:
                raise PreparationError(
                    f"request origin is not allowlisted for {request_id}"
                )
            try:
                response = transport.fetch(request)
                collectors._validate_response_origin(request, response)
            except Exception as exc:  # noqa: BLE001 - freeze must stop before run creation
                raise PreparationError(
                    f"source capture failed before freeze for {request_id}"
                ) from exc
            if not 200 <= response.status < 300:
                raise PreparationError(
                    f"source capture returned non-success status for {request_id}"
                )
            safe_body, _redacted_names = collectors._redact_response_body(
                response.body, env
            )
            _validate_parsed_response(spec, safe_body, now_text)
            body_path = f"responses/{request_id}.bin"
            (temporary / body_path).write_bytes(safe_body)
            headers = {
                key.casefold(): value
                for key, value in response.headers.items()
                if key.casefold() in {"content-type", "content-length", "etag", "last-modified"}
            }
            entries.append(
                {
                    "request_id": request_id,
                    "source_id": spec.source_id,
                    "request_signature": _request_signature(request),
                    "response_status": response.status,
                    "final_locator": _safe_locator(response.final_url),
                    "response_headers": headers,
                    "body_path": body_path,
                    "body_sha256": _sha256(safe_body),
                    "body_bytes": len(safe_body),
                }
            )
        for name, source_value in sorted((local_inputs or {}).items()):
            safe_name = _safe_request_id(str(name))
            source_path = Path(source_value)
            if not source_path.is_file():
                raise PreparationError(f"local input is missing: {safe_name}")
            suffix = source_path.suffix.casefold()
            if suffix not in {".json", ".sqlite3", ".db"}:
                raise PreparationError(f"local input type is not allowed: {safe_name}")
            body = source_path.read_bytes()
            relative = f"inputs/{safe_name}{suffix}"
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(body)
            local_entries.append(
                {
                    "name": safe_name,
                    "path": relative,
                    "sha256": _sha256(body),
                    "bytes": len(body),
                }
            )
        registry = contracts.load_json(contracts.SOURCE_REGISTRY)
        contracts.validate_source_registry(registry)
        manifest: dict[str, Any] = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "status": STATUS,
            "as_of": now_text,
            "source_registry_hash": registry["registry_hash"],
            "requests": entries,
            "local_inputs": local_entries,
            "authority": {
                "production_write": False,
                "publication": False,
                "current_run_update": False,
                "trade": False,
            },
        }
        manifest["bundle_hash"] = _manifest_hash(manifest)
        (temporary / "manifest.json").write_bytes(_canonical(manifest) + b"\n")
        os.replace(temporary, target)
        return validate_frozen_bundle(
            target, specs=planned, as_of=as_of, environment=replay_env
        )
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def validate_frozen_bundle(
    bundle_dir: str | Path,
    *,
    specs: Iterable[collectors.RequestSpec],
    as_of: datetime,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root = Path(bundle_dir)
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreparationError("frozen bundle manifest is unreadable") from exc
    expected_top = {
        "schema",
        "schema_version",
        "status",
        "as_of",
        "source_registry_hash",
        "requests",
        "local_inputs",
        "authority",
        "bundle_hash",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_top:
        raise PreparationError("frozen bundle manifest shape is invalid")
    if (
        manifest["schema"] != SCHEMA
        or manifest["schema_version"] != SCHEMA_VERSION
        or manifest["status"] != STATUS
        or manifest["as_of"] != _utc(as_of)
    ):
        raise PreparationError("frozen bundle identity is invalid")
    if manifest["bundle_hash"] != _manifest_hash(manifest):
        raise PreparationError("frozen bundle manifest hash mismatch")
    expected_authority = {
        "production_write": False,
        "publication": False,
        "current_run_update": False,
        "trade": False,
    }
    if manifest["authority"] != expected_authority:
        raise PreparationError("frozen bundle authority boundary changed")
    registry = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(registry)
    if manifest["source_registry_hash"] != registry["registry_hash"]:
        raise PreparationError("frozen bundle source registry hash mismatch")

    env = _replay_environment(environment)
    planned = tuple(specs)
    rows = manifest["requests"]
    if not isinstance(rows, list) or len(rows) != len(planned):
        raise PreparationError("frozen bundle request count differs from current plan")
    declared_files = {"manifest.json"}
    signatures: set[str] = set()
    for spec, row in zip(planned, rows):
        if not isinstance(row, dict) or set(row) != REQUEST_FIELDS:
            raise PreparationError("frozen response entry shape is invalid")
        if row["request_id"] != spec.request_id or row["source_id"] != spec.source_id:
            raise PreparationError("frozen response order differs from current plan")
        request = spec.build_request(as_of, env)
        signature = _request_signature(request)
        if row["request_signature"] != signature or signature in signatures:
            raise PreparationError("frozen request signature mismatch or duplicate")
        signatures.add(signature)
        relative = Path(row["body_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise PreparationError("frozen response path is unsafe")
        path = root / relative
        try:
            body = path.read_bytes()
        except OSError as exc:
            raise PreparationError("frozen response body is missing") from exc
        # governance-mutation: ISOLATED_PREP_RESPONSE_BODY_HASH
        if len(body) != row["body_bytes"] or _sha256(body) != row["body_sha256"]:
            raise PreparationError("frozen response body hash mismatch")
        response = collectors.HttpResponse(
            status=row["response_status"],
            final_url=row["final_locator"],
            headers=row["response_headers"],
            body=body,
        )
        collectors._validate_response_origin(request, response)
        _validate_parsed_response(spec, body, manifest["as_of"])
        declared_files.add(relative.as_posix())
    local_rows = manifest["local_inputs"]
    if not isinstance(local_rows, list):
        raise PreparationError("frozen local input list is invalid")
    local_names: set[str] = set()
    for row in local_rows:
        if not isinstance(row, dict) or set(row) != LOCAL_INPUT_FIELDS:
            raise PreparationError("frozen local input entry shape is invalid")
        name = _safe_request_id(str(row["name"]))
        if name in local_names:
            raise PreparationError("frozen local input name is duplicated")
        local_names.add(name)
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise PreparationError("frozen local input path is unsafe")
        path = root / relative
        try:
            body = path.read_bytes()
        except OSError as exc:
            raise PreparationError("frozen local input is missing") from exc
        if len(body) != row["bytes"] or _sha256(body) != row["sha256"]:
            raise PreparationError("frozen local input hash mismatch")
        declared_files.add(relative.as_posix())
    actual_files = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    if actual_files != declared_files:
        raise PreparationError("frozen bundle contains missing or extra files")
    _parse_utc(manifest["as_of"])
    return manifest


def _target_date(value: str) -> str:
    if re.fullmatch(r"[0-9]{8}", str(value or "")) is None:
        raise PreparationError("target_trade_date must be YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise PreparationError("target_trade_date is not a real date") from exc
    return value


def _default_run_id(target: str, manifest: Mapping[str, Any]) -> str:
    return f"isolated_{target}_{manifest['bundle_hash'][:12]}_{uuid4().hex[:8]}"


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value) + b"\n")


def _local_input_index(root: Path, manifest: Mapping[str, Any]) -> dict[str, Path]:
    return {
        row["name"]: root / row["path"]
        for row in manifest["local_inputs"]
    }


def _assert_isolated_output_root(output_root: Path) -> None:
    resolved = output_root.resolve()
    repo_root = Path(__file__).resolve().parents[1]
    forbidden = (
        (repo_root / "public" / "data").resolve(),
        (repo_root / "experiments" / "execution_tracker").resolve(),
    )
    for root in forbidden:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        raise PreparationError("isolated build output cannot target a production path")


def validate_isolated_run(
    run_root: str | Path, *, expected_run_id: str | None = None
) -> dict[str, Any]:
    root = Path(run_root)
    manifest_path = root / "isolated_preparation_manifest.json"
    try:
        receipt = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreparationError("isolated preparation manifest is unreadable") from exc
    expected_fields = {
        "schema",
        "schema_version",
        "status",
        "run_id",
        "target_trade_date",
        "as_of",
        "frozen_bundle_hash",
        "portfolio_template_hash",
        "macro_report",
        "artifacts",
        "authority",
        "manifest_hash",
    }
    if not isinstance(receipt, dict) or set(receipt) != expected_fields:
        raise PreparationError("isolated preparation manifest shape is invalid")
    if (
        receipt["schema"] != "ar.isolated_publication_preparation"
        or receipt["schema_version"] != "1.0"
        or receipt["status"] != "ISOLATED_BUILD_COMPLETE"
        or receipt["run_id"] != (expected_run_id or root.name)
        or receipt["manifest_hash"] != _preparation_hash(receipt)
    ):
        raise PreparationError("isolated preparation identity or manifest hash mismatch")
    expected_authority = {
        "production_write": False,
        "publication": False,
        "current_run_update": False,
        "trade": False,
    }
    if receipt["authority"] != expected_authority:
        raise PreparationError("isolated preparation authority boundary changed")
    artifacts = receipt["artifacts"]
    if not isinstance(artifacts, dict) or not artifacts:
        raise PreparationError("isolated preparation artifact map is empty")
    for relative_text, expected_hash in artifacts.items():
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise PreparationError("isolated preparation artifact path is unsafe")
        path = root / relative
        if not path.is_file() or _sha256(path.read_bytes()) != expected_hash:
            raise PreparationError("isolated preparation artifact hash mismatch")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if actual != set(artifacts):
        raise PreparationError("isolated preparation has missing or extra artifacts")
    # governance-mutation: ISOLATED_PREP_NO_CURRENT_RUN
    if any(path.name == "current_run.json" for path in root.rglob("*")):
        raise PreparationError("isolated preparation contains a current_run pointer")
    return receipt


def build_isolated_macro_run(
    bundle_dir: str | Path,
    *,
    output_root: str | Path,
    target_trade_date: str,
    specs: Iterable[collectors.RequestSpec] | None = None,
    environment: Mapping[str, str] | None = None,
    run_id_factory: Callable[[], str] | None = None,
    macro_builder: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build Macro artifacts under an isolated root without publishing them."""
    bundle = Path(bundle_dir)
    target = _target_date(target_trade_date)
    planned = tuple(specs or collectors.collection_plan())
    manifest_path = bundle / "manifest.json"
    try:
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        as_of = _parse_utc(raw_manifest.get("as_of"))
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        raise PreparationError("frozen bundle manifest is unreadable") from exc
    # governance-mutation: ISOLATED_PREP_VERIFY_BEFORE_RUN_ID
    manifest = validate_frozen_bundle(
        bundle, specs=planned, as_of=as_of, environment=environment
    )
    local = _local_input_index(bundle, manifest)
    if "portfolio_template" not in local:
        raise PreparationError("frozen bundle lacks portfolio_template")

    destination = Path(output_root)
    _assert_isolated_output_root(destination)
    factory = run_id_factory or (lambda: _default_run_id(target, manifest))
    run_id = factory()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", str(run_id or "")) is None:
        raise PreparationError("generated run_id is invalid")
    final_root = destination / "runs" / run_id
    temporary = final_root.with_name(final_root.name + ".building")
    if final_root.exists() or temporary.exists():
        raise PreparationError("isolated run destination already exists")

    try:
        inputs = temporary / "inputs"
        inputs.mkdir(parents=True)
        try:
            portfolio = json.loads(local["portfolio_template"].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PreparationError("portfolio_template is not valid JSON") from exc
        if not isinstance(portfolio, dict):
            raise PreparationError("portfolio_template must be a JSON object")
        portfolio["run_id"] = run_id
        portfolio["target_trade_date"] = target
        staged_portfolio = inputs / "model_portfolio_state.json"
        _write_json(staged_portfolio, portfolio)

        calendar = local.get("release_calendar")
        staged_calendar = inputs / "release_calendar.json"
        if calendar:
            staged_calendar.write_bytes(calendar.read_bytes())
        market = local.get("market_features")
        staged_market = inputs / "market_features.json"
        if market:
            staged_market.write_bytes(market.read_bytes())

        replay = FrozenTransport(
            bundle, specs=planned, as_of=as_of, environment=environment
        )
        if macro_builder is None:
            from experiments.macro_os import m1c

            macro_builder = m1c.run
        replay_env = _replay_environment(environment)
        with _temporary_environment(replay_env):
            macro_manifest = macro_builder(
                db_path=temporary / "macro_history.sqlite3",
                output_dir=temporary / "macro",
                portfolio_path=staged_portfolio,
                calendar_path=staged_calendar,
                market_features_path=staged_market if market else None,
                as_of=as_of,
                run_id=run_id,
                target_trade_date=target,
                force_collection=False,
                transport=replay,
            )
        replay.assert_consumed()
        if not isinstance(macro_manifest, Mapping) or macro_manifest.get("run_id") != run_id:
            raise PreparationError("Macro builder returned an invalid run identity")
        artifacts = {
            path.relative_to(temporary).as_posix(): _sha256(path.read_bytes())
            for path in sorted(temporary.rglob("*"))
            if path.is_file()
        }
        receipt: dict[str, Any] = {
            "schema": "ar.isolated_publication_preparation",
            "schema_version": "1.0",
            "status": "ISOLATED_BUILD_COMPLETE",
            "run_id": run_id,
            "target_trade_date": target,
            "as_of": manifest["as_of"],
            "frozen_bundle_hash": manifest["bundle_hash"],
            "portfolio_template_hash": next(
                row["sha256"]
                for row in manifest["local_inputs"]
                if row["name"] == "portfolio_template"
            ),
            "macro_report": macro_manifest.get("report"),
            "artifacts": artifacts,
            "authority": {
                "production_write": False,
                "publication": False,
                "current_run_update": False,
                "trade": False,
            },
        }
        receipt["manifest_hash"] = _preparation_hash(receipt)
        _write_json(temporary / "isolated_preparation_manifest.json", receipt)
        validate_isolated_run(temporary, expected_run_id=run_id)
        final_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, final_root)
        return validate_isolated_run(final_root)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


class FrozenTransport:
    """Replay exactly one verified response for each frozen request."""

    def __init__(
        self,
        bundle_dir: str | Path,
        *,
        specs: Iterable[collectors.RequestSpec],
        as_of: datetime,
        environment: Mapping[str, str] | None = None,
    ):
        self.root = Path(bundle_dir)
        self.environment = _replay_environment(environment)
        manifest = validate_frozen_bundle(
            self.root, specs=specs, as_of=as_of, environment=self.environment
        )
        self.responses = {
            row["request_signature"]: row for row in manifest["requests"]
        }
        self.consumed: set[str] = set()

    def fetch(self, request: collectors.HttpRequest) -> collectors.HttpResponse:
        signature = _request_signature(request)
        row = self.responses.get(signature)
        if row is None or signature in self.consumed:
            raise PreparationError("request is absent from or already consumed in frozen bundle")
        self.consumed.add(signature)
        return collectors.HttpResponse(
            status=row["response_status"],
            final_url=row["final_locator"],
            headers=dict(row["response_headers"]),
            body=(self.root / row["body_path"]).read_bytes(),
        )

    def assert_consumed(self) -> None:
        if self.consumed != set(self.responses):
            raise PreparationError("offline build did not consume the complete frozen request set")


def run_after_verified_freeze(
    bundle_dir: str | Path,
    *,
    specs: Iterable[collectors.RequestSpec],
    as_of: datetime,
    environment: Mapping[str, str] | None,
    run_id_factory: Callable[[], str],
    builder: Callable[[str, FrozenTransport], Any],
    event_sink: Callable[[str], None] | None = None,
) -> Any:
    """Enforce verify -> run_id -> offline build without publishing."""
    planned = tuple(specs)
    validate_frozen_bundle(
        bundle_dir, specs=planned, as_of=as_of, environment=environment
    )
    if event_sink:
        event_sink("freeze_verified")
    run_id = run_id_factory()
    if not isinstance(run_id, str) or not run_id.strip():
        raise PreparationError("run_id factory returned an invalid identifier")
    if event_sink:
        event_sink("run_id_created")
    transport = FrozenTransport(
        bundle_dir, specs=planned, as_of=as_of, environment=environment
    )
    result = builder(run_id, transport)
    transport.assert_consumed()
    if event_sink:
        event_sink("build_completed")
    return result


def _parse_as_of(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreparationError("--as-of must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise PreparationError("--as-of must include a timezone")
    return parsed.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    capture = commands.add_parser(
        "capture-macro", help="capture and freeze Macro responses without a run_id"
    )
    capture.add_argument("--output", required=True)
    capture.add_argument("--as-of", required=True)
    capture.add_argument("--portfolio-template", required=True)
    capture.add_argument("--release-calendar")
    capture.add_argument("--market-features")

    build = commands.add_parser(
        "build-macro", help="verify a frozen bundle and build only in isolation"
    )
    build.add_argument("--bundle", required=True)
    build.add_argument("--output-root", required=True)
    build.add_argument("--target-trade-date", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "capture-macro":
            local_inputs: dict[str, str] = {
                "portfolio_template": args.portfolio_template
            }
            if args.release_calendar:
                local_inputs["release_calendar"] = args.release_calendar
            if args.market_features:
                local_inputs["market_features"] = args.market_features
            result = freeze_macro_inputs(
                args.output,
                specs=collectors.collection_plan(),
                as_of=_parse_as_of(args.as_of),
                transport=collectors.UrllibTransport(),
                local_inputs=local_inputs,
            )
        else:
            result = build_isolated_macro_run(
                args.bundle,
                output_root=args.output_root,
                target_trade_date=args.target_trade_date,
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (PreparationError, collectors.CollectionError, OSError, ValueError) as exc:
        print(
            f"isolated publication preparation refused: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
